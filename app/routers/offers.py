from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import date

from app.database import get_db
from app.models.marketing import Offer
from app.models.subscription import Subscription
from app.routers.auth import require_admin, get_current_user, get_current_user_optional
from app.models.user import User

router = APIRouter(prefix="/api/offers", tags=["Offers"])
admin_only = [Depends(require_admin)]

# ── Schemas ──────────────────────────────────────────────────────────────────

class OfferCreate(BaseModel):
    code:        str
    description: str
    type:        str           # pct | flat | free
    value:       Optional[int] = 0
    max_cap:     Optional[int] = None
    min_order:   Optional[int] = 0
    usage_limit: Optional[int] = None
    valid_from:  date
    valid_until: date
    status:      Optional[str] = "active"
    audience:    Optional[str] = "all"   # all | new_user | existing_user

    @validator("type")
    def valid_type(cls, v):
        if v not in ("pct", "flat", "free"):
            raise ValueError("type must be pct, flat, or free")
        return v

    @validator("audience")
    def valid_audience(cls, v):
        if v not in ("all", "new_user", "existing_user"):
            raise ValueError("audience must be all, new_user, or existing_user")
        return v

    @validator("code")
    def uppercase_code(cls, v):
        return v.strip().upper()

class OfferResponse(BaseModel):
    id:          int
    code:        str
    description: str
    type:        str
    value:       int
    max_cap:     Optional[int]
    min_order:   int
    usage_limit: Optional[int]
    used_count:  int
    valid_from:  date
    valid_until: date
    status:      str
    audience:    str

    class Config:
        from_attributes = True

class OfferValidateRequest(BaseModel):
    code:        str
    order_total: int

# ── Helpers ──────────────────────────────────────────────────────────────────

def _auto_expire(db: Session):
    today = date.today()
    db.query(Offer)\
      .filter(Offer.valid_until < today, Offer.status == "active")\
      .update({"status": "expired"})
    db.commit()

# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[OfferResponse])
def list_offers(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    _auto_expire(db)
    q = db.query(Offer)
    
    # Check if user is admin
    is_admin = current_user and current_user.role and current_user.role.lower() == "admin"
    
    if not is_admin:
        # Customers and unauthenticated users can only see active offers
        q = q.filter(Offer.status == "active")
    elif status:
        q = q.filter(Offer.status == status)
        
    return q.order_by(Offer.id.desc()).all()

@router.post("", response_model=OfferResponse, dependencies=admin_only)
def create_offer(data: OfferCreate, db: Session = Depends(get_db)):
    existing = db.query(Offer).filter(Offer.code == data.code).first()
    if existing:
        raise HTTPException(400, f"Coupon code '{data.code}' already exists")
    offer = Offer(**data.dict())
    db.add(offer)
    db.commit()
    db.refresh(offer)
    return offer

@router.put("/{offer_id}", response_model=OfferResponse, dependencies=admin_only)
def update_offer(offer_id: int, data: OfferCreate, db: Session = Depends(get_db)):
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(404, "Offer not found")
    # check code uniqueness if changed
    if data.code != offer.code:
        dup = db.query(Offer).filter(Offer.code == data.code).first()
        if dup:
            raise HTTPException(400, f"Code '{data.code}' already in use")
    for k, v in data.dict().items():
        setattr(offer, k, v)
    db.commit()
    db.refresh(offer)
    return offer

@router.patch("/{offer_id}/status", dependencies=admin_only)
def set_offer_status(offer_id: int, status: str, db: Session = Depends(get_db)):
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(404, "Offer not found")
    if status not in ("active", "draft", "expired"):
        raise HTTPException(400, "Invalid status")
    offer.status = status
    db.commit()
    return {"detail": "Status updated"}

@router.delete("/{offer_id}", dependencies=admin_only)
def delete_offer(offer_id: int, db: Session = Depends(get_db)):
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(404, "Offer not found")
    db.delete(offer)
    db.commit()
    return {"detail": "Deleted"}

@router.post("/validate")
def validate_offer(req: OfferValidateRequest, db: Session = Depends(get_db)):
    """Validate a coupon code at checkout and return discount amount."""
    _auto_expire(db)
    today = date.today()
    offer = db.query(Offer).filter(
        Offer.code == req.code.strip().upper(),
        Offer.status == "active",
        Offer.valid_from <= today,
        Offer.valid_until >= today
    ).first()

    if not offer:
        raise HTTPException(404, "Invalid or expired coupon code")

    if offer.usage_limit and offer.used_count >= offer.usage_limit:
        raise HTTPException(400, "This coupon has reached its usage limit")

    if req.order_total < offer.min_order:
        raise HTTPException(400, f"Minimum order value ₹{offer.min_order} required for this coupon")

    # Calculate discount
    if offer.type == "pct":
        discount = int(req.order_total * offer.value / 100)
        if offer.max_cap:
            discount = min(discount, offer.max_cap)
    elif offer.type == "flat":
        discount = min(offer.value, req.order_total)
    else:  # free delivery
        discount = offer.max_cap or 40  # delivery charge cap

    return {
        "valid":    True,
        "code":     offer.code,
        "type":     offer.type,
        "discount": discount,
        "message":  f"₹{discount} discount applied!"
    }

@router.post("/{offer_id}/redeem")
def redeem_offer(
    offer_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Increment the used_count on successful order placement."""
    offer = db.query(Offer).filter(Offer.id == offer_id).first()
    if not offer:
        raise HTTPException(404, "Offer not found")
    offer.used_count += 1
    if offer.usage_limit and offer.used_count >= offer.usage_limit:
        offer.status = "expired"
    db.commit()
    return {"detail": "Redeemed"}


@router.get("/my-offers", response_model=List[OfferResponse])
def get_my_offers(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return active, audience-matched offers for the logged-in customer.

    - audience='all'           → returned for every user
    - audience='new_user'      → returned only if user has NEVER had a subscription
    - audience='existing_user' → returned only if user HAS had at least one subscription
    """
    _auto_expire(db)
    today = date.today()

    # Determine if this user has ever subscribed
    ever_subscribed = db.query(Subscription.id).filter(
        Subscription.customer_id == current_user.id
    ).first() is not None

    # Build audience filter
    from sqlalchemy import or_
    if ever_subscribed:
        audience_filter = or_(Offer.audience == "all", Offer.audience == "existing_user")
    else:
        audience_filter = or_(Offer.audience == "all", Offer.audience == "new_user")

    offers = db.query(Offer).filter(
        Offer.status == "active",
        Offer.valid_from <= today,
        Offer.valid_until >= today,
        audience_filter,
    ).order_by(Offer.id.desc()).all()

    return offers
