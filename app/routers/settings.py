from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional

from app.database import get_db
from app.models.settings import AppSettings
from app.routers.auth import require_admin

router = APIRouter(prefix="/settings", tags=["Settings"])

# ── Pydantic schemas ──────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    # Contact
    business_name:     Optional[str]   = None
    address:           Optional[str]   = None
    phone_number:      Optional[str]   = None
    email:             Optional[str]   = None
    city:              Optional[str]   = None
    instagram_link:    Optional[str]   = None
    # Hours
    opens_at:          Optional[str]   = None
    closes_at:         Optional[str]   = None
    timezone:          Optional[str]   = None
    # Admin notifications
    notif_new_order:      Optional[bool] = None
    notif_credit_earned:  Optional[bool] = None
    notif_payment_fail:   Optional[bool] = None
    notif_new_customer:   Optional[bool] = None
    # Customer notifications
    notif_cust_credit:    Optional[bool] = None
    notif_cust_reminder:  Optional[bool] = None
    notif_cust_order_sms: Optional[bool] = None
    notif_cust_delivery:  Optional[bool] = None
    # Payment
    payment_gateway:        Optional[str]   = None
    payment_api_key:        Optional[str]   = None
    payment_api_secret:     Optional[str]   = None
    payment_cod_enabled:    Optional[bool]  = None
    payment_upi_enabled:    Optional[bool]  = None
    gst_rate:               Optional[float] = None
    gstin:                  Optional[str]   = None
    # Credit rules
    credit_cutoff_hours:    Optional[int]  = None
    credit_delivery_delay:  Optional[int]  = None
    credit_max_per_plan:    Optional[int]  = None
    credit_deliver_no_renew: Optional[bool] = None
    credit_of_credit:       Optional[bool] = None


class PublicSettings(BaseModel):
    """What the unauthenticated footer / contact page is allowed to see."""
    business_name:  Optional[str] = None
    address:        Optional[str] = None
    phone_number:   Optional[str] = None
    email:          Optional[str] = None
    city:           Optional[str] = None
    instagram_link: Optional[str] = None
    opens_at:       Optional[str] = None
    closes_at:      Optional[str] = None
    timezone:       Optional[str] = None


class AdminSettings(BaseModel):
    """Full admin view. Secret values are masked, never returned in plaintext."""
    business_name:     Optional[str]   = None
    address:           Optional[str]   = None
    phone_number:      Optional[str]   = None
    email:             Optional[str]   = None
    city:              Optional[str]   = None
    instagram_link:    Optional[str]   = None
    opens_at:          Optional[str]   = None
    closes_at:         Optional[str]   = None
    timezone:          Optional[str]   = None
    notif_new_order:      Optional[bool] = None
    notif_credit_earned:  Optional[bool] = None
    notif_payment_fail:   Optional[bool] = None
    notif_new_customer:   Optional[bool] = None
    notif_cust_credit:    Optional[bool] = None
    notif_cust_reminder:  Optional[bool] = None
    notif_cust_order_sms: Optional[bool] = None
    notif_cust_delivery:  Optional[bool] = None
    payment_gateway:        Optional[str]   = None
    payment_api_key:        Optional[str]   = None
    payment_api_secret_set: bool = False         # boolean flag, never the secret itself
    payment_cod_enabled:    Optional[bool]  = None
    payment_upi_enabled:    Optional[bool]  = None
    gst_rate:               Optional[float] = None
    gstin:                  Optional[str]   = None
    credit_cutoff_hours:    Optional[int]  = None
    credit_delivery_delay:  Optional[int]  = None
    credit_max_per_plan:    Optional[int]  = None
    credit_deliver_no_renew: Optional[bool] = None
    credit_of_credit:       Optional[bool] = None


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create(db: Session) -> AppSettings:
    settings = db.query(AppSettings).first()
    if not settings:
        settings = AppSettings()
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def _to_admin(settings: AppSettings) -> AdminSettings:
    """Project the model into the admin response, masking the secret."""
    data = {col.name: getattr(settings, col.name) for col in AppSettings.__table__.columns}
    data["payment_api_secret_set"] = bool(settings.payment_api_secret)
    data.pop("payment_api_secret", None)
    data.pop("id", None)
    return AdminSettings(**data)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=PublicSettings)
def get_public_settings(db: Session = Depends(get_db)):
    """Public endpoint — only returns business info that the footer / contact page needs."""
    settings = _get_or_create(db)
    return PublicSettings(
        business_name=settings.business_name,
        address=settings.address,
        phone_number=settings.phone_number,
        email=settings.email,
        city=settings.city,
        instagram_link=settings.instagram_link,
        opens_at=settings.opens_at,
        closes_at=settings.closes_at,
        timezone=settings.timezone,
    )


@router.get("/admin", response_model=AdminSettings, dependencies=[Depends(require_admin)])
def get_admin_settings(db: Session = Depends(get_db)):
    """Admin-only — returns every field except the payment secret."""
    return _to_admin(_get_or_create(db))


@router.put("", response_model=AdminSettings, dependencies=[Depends(require_admin)])
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    settings = _get_or_create(db)
    for field, value in data.dict(exclude_unset=True).items():
        # Allow blank string for the secret to mean "leave unchanged"
        if field == "payment_api_secret" and value in (None, ""):
            continue
        setattr(settings, field, value)
    db.commit()
    db.refresh(settings)
    return _to_admin(settings)


@router.post("/clear-dashboard", dependencies=[Depends(require_admin)])
def clear_dashboard(db: Session = Depends(get_db)):
    """Reset all revenue, orders, cancellations, custom requests, and credits.
    This restores the dashboard stats back to 0.
    """
    from fastapi import HTTPException
    from app.models.subscription import Subscription
    from app.models.credit import Credit, DeliveryCancellation
    from app.models.custom_request import CustomPlanRequest
    from app.models.audit_log import AuditLog

    try:
        # 1. Nullify circular FK dependencies to prevent constraint errors
        db.query(DeliveryCancellation).update({DeliveryCancellation.credit_id: None})
        db.query(Credit).update({Credit.cancellation_id: None})
        db.commit()

        # 2. Sequential delete to obey foreign key constraints safely
        db.query(DeliveryCancellation).delete()
        db.query(Credit).delete()
        db.query(Subscription).delete()
        db.query(CustomPlanRequest).delete()
        db.query(AuditLog).delete()
        
        db.commit()
        return {"status": "success", "message": "Dashboard statistics have been successfully reset."}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Failed to clear dashboard: {str(e)}")
