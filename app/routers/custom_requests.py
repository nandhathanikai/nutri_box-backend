from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import date, timedelta
from uuid import UUID

from app.database import get_db
from app.models.custom_request import CustomPlanRequest
from app.models.user import User
from app.models.meal_tier import MealTier
from app.models.menu import PlanTemplate
from app.models.subscription import Subscription
from app.routers.auth import get_current_user, require_admin
from app.routers.menu import MEAL_COUNT_MAP

router = APIRouter(prefix="/api/custom-requests", tags=["Custom Plan Requests"])

# --- SCHEMAS ---

class CustomRequestCreate(BaseModel):
    base_tier_id: Optional[UUID] = None
    diet_type: str
    slot_combo: str
    duration: str
    custom_requirements: str

class CustomRequestResponse(BaseModel):
    id: UUID
    customer_id: int
    customer_name: str
    customer_email: str
    base_tier_id: Optional[UUID]
    base_tier_name: Optional[str]
    diet_type: str
    slot_combo: str
    duration: str
    custom_requirements: str
    status: str
    quoted_price_per_meal: Optional[float]
    quoted_delivery_charge: Optional[float]
    quoted_total: Optional[float]
    meal_count: Optional[int]
    created_at: str
    
    class Config:
        orm_mode = True

class CustomRequestPricePatch(BaseModel):
    price_per_meal: float
    delivery_charge: float

class CustomRequestStatusPatch(BaseModel):
    status: str  # 'accepted', 'rejected'

class CustomPayOrderResponse(BaseModel):
    order_id: str
    amount: int       # paise
    currency: str
    key_id: str
    plan_name: str
    total: float      # INR display

class CustomVerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# --- ROUTES ---

@router.post("", response_model=CustomRequestResponse)
def create_custom_request(
    payload: CustomRequestCreate, 
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Customer submits a new custom plan request."""
    if payload.base_tier_id:
        tier = db.query(MealTier).filter(MealTier.id == payload.base_tier_id).first()
        if not tier:
            raise HTTPException(status_code=404, detail="Base tier not found")

    new_req = CustomPlanRequest(
        customer_id=current_user.id,
        base_tier_id=payload.base_tier_id,
        diet_type=payload.diet_type,
        slot_combo=payload.slot_combo,
        duration=payload.duration,
        custom_requirements=payload.custom_requirements,
        status="pending"
    )
    db.add(new_req)
    db.commit()
    db.refresh(new_req)

    return _format_request(new_req, current_user, db)


@router.get("/my-requests", response_model=List[CustomRequestResponse])
def get_my_requests(
    db: Session = Depends(get_db), 
    current_user: User = Depends(get_current_user)
):
    """Customer views their own custom plan requests."""
    requests = db.query(CustomPlanRequest).filter(
        CustomPlanRequest.customer_id == current_user.id
    ).order_by(CustomPlanRequest.created_at.desc()).all()
    
    return [_format_request(req, current_user, db) for req in requests]


@router.get("", response_model=List[CustomRequestResponse])
def get_all_requests(
    status: Optional[str] = None,
    db: Session = Depends(get_db), 
    admin: User = Depends(require_admin)
):
    """Admin views all custom plan requests."""
    query = db.query(CustomPlanRequest)
    if status:
        query = query.filter(CustomPlanRequest.status == status)
    
    requests = query.order_by(CustomPlanRequest.created_at.desc()).all()
    
    # Batch fetch users
    user_ids = {r.customer_id for r in requests}
    users = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}
    
    return [_format_request(req, users.get(req.customer_id), db) for req in requests]


@router.patch("/{request_id}/price")
def price_custom_request(
    request_id: UUID,
    payload: CustomRequestPricePatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Admin sets the price for a custom request."""
    req = db.query(CustomPlanRequest).filter(CustomPlanRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")

    if req.status not in ("pending",):
        raise HTTPException(status_code=400, detail="Can only price a pending request")
        
    req.quoted_price_per_meal = payload.price_per_meal
    req.quoted_delivery_charge = payload.delivery_charge
    req.status = "priced"
    
    db.commit()
    
    return {"message": "Request priced successfully"}


@router.patch("/{request_id}/status")
def update_request_status(
    request_id: UUID,
    payload: CustomRequestStatusPatch,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    """Admin accepts or rejects a request."""
    if payload.status not in ("accepted", "rejected"):
        raise HTTPException(status_code=400, detail="Invalid status")
        
    req = db.query(CustomPlanRequest).filter(CustomPlanRequest.id == request_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
        
    req.status = payload.status
    db.commit()
    return {"message": f"Request marked as {payload.status}"}


@router.post("/{request_id}/pay-order", response_model=CustomPayOrderResponse)
def create_custom_pay_order(
    request_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Customer initiates payment for a priced custom plan.
    Creates a Razorpay order for the quoted amount.
    """
    import os
    import razorpay

    req = db.query(CustomPlanRequest).filter(
        CustomPlanRequest.id == request_id,
        CustomPlanRequest.customer_id == current_user.id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "priced":
        raise HTTPException(status_code=400, detail="This request is not ready for payment yet")
    if req.quoted_price_per_meal is None:
        raise HTTPException(status_code=400, detail="Price has not been set by admin yet")

    # Calculate total from quoted price
    meal_count_map = {
        ("breakfast_only", "weekly"): 6,
        ("dinner_only", "weekly"): 6,
        ("both", "weekly"): 12,
        ("breakfast_only", "monthly"): 24,
        ("dinner_only", "monthly"): 24,
        ("both", "monthly"): 48,
    }
    meal_count = meal_count_map.get((req.slot_combo, req.duration), 6)
    ppm = float(req.quoted_price_per_meal)
    delivery = float(req.quoted_delivery_charge or 0)
    total_inr = round(ppm * meal_count + delivery, 2)
    amount_paise = int(round(total_inr * 100))

    key_id = os.getenv("RAZORPAY_KEY_ID", "")
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    if not key_id or not key_secret:
        raise HTTPException(status_code=503, detail="Payment gateway not configured")

    rzp = razorpay.Client(auth=(key_id, key_secret))
    short_id = str(req.id)[:8]
    order = rzp.order.create({
        "amount": amount_paise,
        "currency": "INR",
        "receipt": f"cx_u{current_user.id}_{short_id}",
        "notes": {
            "type": "custom_plan",
            "custom_request_id": str(req.id),
            "user_id": str(current_user.id),
            "diet_type": req.diet_type,
            "slot_combo": req.slot_combo,
            "duration": req.duration,
        },
    })

    diet_label = "Veg" if req.diet_type == "veg" else "Non-Veg" if req.diet_type == "nonveg" else "Veg & Non-Veg"
    plan_name = f"Custom {diet_label} Plan ({req.duration.title()})"

    return CustomPayOrderResponse(
        order_id=order["id"],
        amount=amount_paise,
        currency="INR",
        key_id=key_id,
        plan_name=plan_name,
        total=total_inr,
    )


@router.post("/{request_id}/verify-payment")
def verify_custom_payment(
    request_id: UUID,
    payload: CustomVerifyPaymentRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Verify Razorpay HMAC signature for a custom plan payment.
    On success: mark request as 'paid' and create a Subscription record.
    """
    import os
    import hmac as hmaclib
    import hashlib
    from app.routers.subscriptions import _next_working_day, _last_delivery_date, _serialize

    req = db.query(CustomPlanRequest).filter(
        CustomPlanRequest.id == request_id,
        CustomPlanRequest.customer_id == current_user.id
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status not in ("priced",):
        raise HTTPException(status_code=400, detail="Payment cannot be verified for this request")

    # Verify HMAC signature
    key_secret = os.getenv("RAZORPAY_KEY_SECRET", "")
    message = f"{payload.razorpay_order_id}|{payload.razorpay_payment_id}"
    generated = hmaclib.new(
        key_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    if not hmaclib.compare_digest(generated, payload.razorpay_signature):
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")

    # Idempotency: check if subscription already exists for this order
    existing = db.query(Subscription).filter(
        Subscription.razorpay_order_id == payload.razorpay_order_id
    ).first()
    if existing:
        req.status = "paid"
        db.commit()
        return {"message": "Payment already recorded", "subscription_id": str(existing.id)}

    # Block duplicate active subscriptions
    today = date.today()
    overlap = db.query(Subscription).filter(
        Subscription.customer_id == current_user.id,
        Subscription.end_date >= today,
    ).first()
    if overlap:
        raise HTTPException(status_code=409, detail="You already have an active subscription.")

    # Calculate meal count and price snapshot
    meal_count_map = {
        ("breakfast_only", "weekly"): 6,
        ("dinner_only", "weekly"): 6,
        ("both", "weekly"): 12,
        ("breakfast_only", "monthly"): 24,
        ("dinner_only", "monthly"): 24,
        ("both", "monthly"): 48,
    }
    meal_count = meal_count_map.get((req.slot_combo, req.duration), 6)
    ppm_snapshot = float(req.quoted_price_per_meal) if req.quoted_price_per_meal else None

    # Determine start and end dates
    start = _next_working_day(today + timedelta(days=1))
    end = _last_delivery_date(start, req.duration)

    # Find a matching PlanTemplate (best-effort; can be None)
    plan_template = db.query(PlanTemplate).filter(
        PlanTemplate.diet_type == req.diet_type,
        PlanTemplate.slot_combo == req.slot_combo,
        PlanTemplate.duration == req.duration,
        PlanTemplate.is_active == True,
    ).first()

    sub = Subscription(
        customer_id=current_user.id,
        menu_id=plan_template.id if plan_template else None,
        start_date=start,
        end_date=end,
        price_per_meal_snapshot=ppm_snapshot,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
    )
    db.add(sub)

    # Mark the custom request as paid
    req.status = "paid"

    try:
        db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=500, detail="Failed to create subscription. Please contact support.")

    db.refresh(sub)
    return _serialize(sub, db)


# --- HELPERS ---

def _get_meal_count(slot_combo: str, duration: str) -> int:
    meal_count_map = {
        ("breakfast_only", "weekly"): 6,
        ("dinner_only", "weekly"): 6,
        ("both", "weekly"): 12,
        ("breakfast_only", "monthly"): 24,
        ("dinner_only", "monthly"): 24,
        ("both", "monthly"): 48,
    }
    return meal_count_map.get((slot_combo, duration), 6)


def _format_request(req: CustomPlanRequest, user: User, db: Session) -> dict:
    tier_name = None
    if req.base_tier_id:
        tier = db.query(MealTier).filter(MealTier.id == req.base_tier_id).first()
        if tier:
            tier_name = tier.name

    meal_count = _get_meal_count(req.slot_combo, req.duration)
    quoted_total = None
    if req.quoted_price_per_meal is not None:
        ppm = float(req.quoted_price_per_meal)
        delivery = float(req.quoted_delivery_charge or 0)
        quoted_total = round(ppm * meal_count + delivery, 2)

    return {
        "id": req.id,
        "customer_id": req.customer_id,
        "customer_name": user.full_name if user else "Unknown",
        "customer_email": user.email if user else "Unknown",
        "base_tier_id": req.base_tier_id,
        "base_tier_name": tier_name,
        "diet_type": req.diet_type,
        "slot_combo": req.slot_combo,
        "duration": req.duration,
        "custom_requirements": req.custom_requirements,
        "status": req.status,
        "quoted_price_per_meal": float(req.quoted_price_per_meal) if req.quoted_price_per_meal is not None else None,
        "quoted_delivery_charge": float(req.quoted_delivery_charge) if req.quoted_delivery_charge is not None else None,
        "quoted_total": quoted_total,
        "meal_count": meal_count,
        "created_at": req.created_at.isoformat() if req.created_at else None
    }
