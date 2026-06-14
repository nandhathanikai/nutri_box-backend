"""
Admin Delivery Router
---------------------
Endpoints for:
  - Managing delivery sessions (CRUD, dynamic — admin adds Breakfast/Lunch/etc.)
  - Managing driver accounts (create, list, edit, activate/deactivate)
  - Assigning orders to drivers session-wise
  - Admin delivery monitoring view
  - Enhanced today's orders with session grouping and assignment status
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr, validator
from sqlalchemy.orm import Session
from sqlalchemy import func, and_

from app.database import get_db
from app.models.user import User
from app.models.subscription import Subscription
from app.models.menu import PlanTemplate
from app.models.meal_tier import MealTier
from app.models.credit import DeliveryCancellation
from app.models.delivery import (
    DeliverySession, DeliveryAssignment, DriverStatus
)
from app.routers.auth import require_admin, get_current_user
from app.utils.security import get_password_hash
from app.utils.geocode import geocode_user_location

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> date:
    return datetime.now(IST).date()


router = APIRouter(
    prefix="/api/delivery",
    tags=["Delivery Management"],
    dependencies=[Depends(require_admin)],
)


# ═══════════════════════════════════════════════════════════════
# SECTION 1 — Delivery Sessions (Dynamic)
# ═══════════════════════════════════════════════════════════════

class SessionCreate(BaseModel):
    name: str
    display_order: int = 0
    is_active: bool = True


class SessionUpdate(BaseModel):
    name: Optional[str] = None
    display_order: Optional[int] = None
    is_active: Optional[bool] = None


@router.get("/sessions")
def list_sessions(db: Session = Depends(get_db)):
    """List all delivery sessions ordered by display_order."""
    sessions = db.query(DeliverySession).order_by(DeliverySession.display_order).all()
    return [
        {
            "id": str(s.id),
            "name": s.name,
            "slug": s.slug,
            "display_order": s.display_order,
            "is_active": s.is_active,
        }
        for s in sessions
    ]


@router.post("/sessions", status_code=status.HTTP_201_CREATED)
def create_session(payload: SessionCreate, db: Session = Depends(get_db)):
    """Admin creates a new delivery session (e.g. Snack, Early Morning)."""
    slug = payload.name.strip().lower().replace(" ", "_")
    existing = db.query(DeliverySession).filter(DeliverySession.slug == slug).first()
    if existing:
        raise HTTPException(status_code=409, detail="A session with this name already exists.")

    s = DeliverySession(
        name=payload.name.strip(),
        slug=slug,
        display_order=payload.display_order,
        is_active=payload.is_active,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": str(s.id), "name": s.name, "slug": s.slug, "display_order": s.display_order, "is_active": s.is_active}


@router.put("/sessions/{session_id}")
def update_session(session_id: int, payload: SessionUpdate, db: Session = Depends(get_db)):
    s = db.query(DeliverySession).filter(DeliverySession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found.")
    if payload.name is not None:
        s.name = payload.name.strip()
        s.slug = s.name.lower().replace(" ", "_")
    if payload.display_order is not None:
        s.display_order = payload.display_order
    if payload.is_active is not None:
        s.is_active = payload.is_active
    db.commit()
    db.refresh(s)
    return {"id": str(s.id), "name": s.name, "slug": s.slug, "display_order": s.display_order, "is_active": s.is_active}


@router.delete("/sessions/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_session(session_id: int, db: Session = Depends(get_db)):
    s = db.query(DeliverySession).filter(DeliverySession.id == session_id).first()
    if not s:
        raise HTTPException(status_code=404, detail="Session not found.")
    # Check no assignments reference this session
    count = db.query(DeliveryAssignment).filter(DeliveryAssignment.session_id == session_id).count()
    if count > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot delete session with {count} existing assignment(s). Deactivate it instead."
        )
    db.delete(s)
    db.commit()


# ═══════════════════════════════════════════════════════════════
# SECTION 2 — Driver Management
# ═══════════════════════════════════════════════════════════════

class DriverCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    password: str
    is_active: bool = True

    @validator("password")
    def _pwd(cls, v):
        import re
        if len(v) < 8 or not re.search(r"[A-Z]", v) or not re.search(r"[a-z]", v) or not re.search(r"\d", v):
            raise ValueError("Password must be ≥8 chars with uppercase, lowercase, and a number.")
        return v


class DriverUpdate(BaseModel):
    full_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


@router.get("/drivers")
def list_drivers(
    search: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """List all driver accounts with their current assigned order counts for today."""
    today = _today_ist()
    q = db.query(User).filter(User.role == "driver")
    if search:
        like = f"%{search.strip()}%"
        q = q.filter(
            User.full_name.ilike(like) | User.email.ilike(like) | User.phone.ilike(like)
        )
    drivers = q.order_by(User.created_at.desc()).all()

    driver_ids = [d.id for d in drivers]

    # Count today's assignments per driver
    counts = (
        db.query(DeliveryAssignment.driver_id, func.count(DeliveryAssignment.id))
        .filter(
            DeliveryAssignment.driver_id.in_(driver_ids),
            DeliveryAssignment.delivery_date == today,
        )
        .group_by(DeliveryAssignment.driver_id)
        .all()
    )
    count_map = {did: cnt for did, cnt in counts}

    # Load driver statuses
    statuses = (
        db.query(DriverStatus)
        .filter(DriverStatus.driver_id.in_(driver_ids))
        .all()
    )
    status_map = {ds.driver_id: ds for ds in statuses}

    return [
        {
            "id": str(d.id),
            "full_name": d.full_name,
            "email": d.email,
            "phone": d.phone or "—",
            "is_active": d.is_active,
            "created_at": d.created_at.isoformat() if d.created_at else None,
            "today_assignments": count_map.get(d.id, 0),
            "online_status": status_map[d.id].status if d.id in status_map else "offline",
        }
        for d in drivers
    ]


@router.post("/drivers", status_code=status.HTTP_201_CREATED)
def create_driver(payload: DriverCreate, db: Session = Depends(get_db)):
    """Admin creates a new driver account in the shared users table."""
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    driver = User(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        hashed_password=get_password_hash(payload.password),
        role="driver",
        is_active=payload.is_active,
        email_verified=True,  # Admin-created accounts skip email verification
    )
    db.add(driver)
    db.commit()
    db.refresh(driver)

    # Create a default offline status row
    ds = DriverStatus(driver_id=driver.id, status="offline")
    db.add(ds)
    db.commit()

    logger.info("Admin created driver id=%s email=%s", driver.id, driver.email)
    return {"id": str(driver.id), "email": driver.email, "full_name": driver.full_name}


@router.put("/drivers/{driver_id}")
def update_driver(driver_id: int, payload: DriverUpdate, db: Session = Depends(get_db)):
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    if payload.full_name is not None:
        driver.full_name = payload.full_name
    if payload.phone is not None:
        driver.phone = payload.phone
    if payload.is_active is not None:
        driver.is_active = payload.is_active
    db.commit()
    db.refresh(driver)
    return {"id": str(driver.id), "full_name": driver.full_name, "phone": driver.phone, "is_active": driver.is_active}


@router.patch("/drivers/{driver_id}/toggle-active")
def toggle_driver_active(driver_id: int, db: Session = Depends(get_db)):
    """Flip the is_active flag for a driver."""
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    driver.is_active = not driver.is_active
    db.commit()
    return {"id": str(driver.id), "is_active": driver.is_active}


@router.delete("/drivers/{driver_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_driver(
    driver_id: int,
    db: Session = Depends(get_db),
):
    """Hard-delete a driver account.

    Deletes related driver status and nullifies/deletes assignments where needed.
    """
    driver = db.query(User).filter(User.id == driver_id, User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")

    # 1. Clean up driver status
    db.query(DriverStatus).filter(DriverStatus.driver_id == driver_id).delete()

    # 2. Nullify driver on delivery assignments
    db.query(DeliveryAssignment).filter(DeliveryAssignment.driver_id == driver_id).update(
        {DeliveryAssignment.driver_id: None, DeliveryAssignment.status: "unassigned"}
    )

    db.delete(driver)
    db.commit()
    return


# ═══════════════════════════════════════════════════════════════
# SECTION 3 — Today's Orders with Session Grouping + Assignment
# ═══════════════════════════════════════════════════════════════

@router.get("/todays-orders")
def get_delivery_orders(db: Session = Depends(get_db)):
    """Return today's orders grouped by active delivery session.
    Each session group shows orders with their assignment status.
    Only active sessions appear. New sessions added by admin appear automatically.
    """
    today = _today_ist()
    is_weekend = today.weekday() == 6  # Sunday off

    # Load active sessions ordered by display_order
    sessions = (
        db.query(DeliverySession)
        .filter(DeliverySession.is_active == True)
        .order_by(DeliverySession.display_order)
        .all()
    )

    # Build slug → session map for matching subscription slot_combo
    SESSION_SLUG_MAP = {s.slug: s for s in sessions}

    # Slot combo → which session slugs apply
    SLOT_TO_SESSIONS = {
        "breakfast_only": ["breakfast"],
        "dinner_only": ["dinner"],
        "both": ["breakfast", "dinner"],
        "lunch_only": ["lunch"],
        "all": ["breakfast", "lunch", "dinner"],
    }

    active_subs = db.query(Subscription).filter(
        Subscription.start_date <= today,
        Subscription.end_date >= today,
    ).all()

    if not active_subs:
        return {
            "date": today.isoformat(),
            "is_weekend": is_weekend,
            "sessions": [{"session": s.name, "session_id": s.id, "slug": s.slug, "orders": [], "skipped": []} for s in sessions],
        }

    sub_ids = [s.id for s in active_subs]
    customer_ids = list({s.customer_id for s in active_subs})
    menu_ids = list({s.menu_id for s in active_subs if s.menu_id})

    users = {u.id: u for u in db.query(User).filter(User.id.in_(customer_ids)).all()}
    plans = {p.id: p for p in db.query(PlanTemplate).filter(PlanTemplate.id.in_(menu_ids)).all()} if menu_ids else {}
    tier_ids = list({p.tier_id for p in plans.values() if p.tier_id})
    tiers = {t.id: t for t in db.query(MealTier).filter(MealTier.id.in_(tier_ids)).all()} if tier_ids else {}

    # Today's cancellations
    cancels = db.query(DeliveryCancellation).filter(
        DeliveryCancellation.subscription_id.in_(sub_ids),
        DeliveryCancellation.delivery_date == today,
    ).all()
    # Key: (subscription_id, session_slug)
    cancel_map = {}
    for c in cancels:
        raw = (c.session or "").upper()
        slug = "breakfast" if raw == "BF" else raw.lower()
        cancel_map[(c.subscription_id, slug)] = c

    # Today's assignments keyed by (subscription_id, session_id)
    assignments = db.query(DeliveryAssignment).filter(
        DeliveryAssignment.delivery_date == today
    ).all()
    assign_map = {(a.subscription_id, a.session_id): a for a in assignments}

    # Load drivers for assignment display
    driver_ids = list({a.driver_id for a in assignments if a.driver_id})
    drivers_map = {}
    if driver_ids:
        for d in db.query(User).filter(User.id.in_(driver_ids)).all():
            drivers_map[d.id] = d

    # Group results by session
    session_groups = {s.id: {"session": s.name, "session_id": str(s.id), "slug": s.slug, "orders": [], "skipped": []} for s in sessions}

    for sub in active_subs:
        user = users.get(sub.customer_id)
        plan = plans.get(sub.menu_id) if sub.menu_id else None
        tier = tiers.get(plan.tier_id) if (plan and plan.tier_id) else None

        slot_combo = sub.slot_combo or (plan.slot_combo if plan else None) or ""
        applicable_slugs = SLOT_TO_SESSIONS.get(slot_combo, [])

        address_parts = []
        if user:
            if user.address_line_1: address_parts.append(user.address_line_1)
            if user.address_line_2: address_parts.append(user.address_line_2)
            if user.landmark: address_parts.append(f"Near {user.landmark}")
        address = ", ".join(address_parts) if address_parts else "—"

        for slug in applicable_slugs:
            sess_obj = SESSION_SLUG_MAP.get(slug)
            if not sess_obj:
                continue  # Session exists in sub but not in active sessions

            cancellation = cancel_map.get((sub.id, slug))
            assignment = assign_map.get((sub.id, sess_obj.id))
            driver = drivers_map.get(assignment.driver_id) if assignment and assignment.driver_id else None

            row = {
                "subscription_id": str(sub.id),
                "customer_id": str(user.id) if user else None,
                "customer_name": user.full_name if user else "—",
                "customer_email": user.email if user else "",
                "customer_phone": user.phone if user and user.phone else "—",
                "address": address,
                "latitude": user.latitude if user else None,
                "longitude": user.longitude if user else None,
                "tier_name": tier.name if tier else "Customized Tier",
                "plan_name": plan.name if plan else "Customized Plan",
                "diet_type": sub.diet_type or (plan.diet_type if plan else "both"),
                "session_slug": slug,
                "assignment_id": str(assignment.id) if assignment else None,
                "assignment_status": assignment.status if assignment else "unassigned",
                "driver_id": str(driver.id) if driver else None,
                "driver_name": driver.full_name if driver else None,
                "customization_details": sub.customization_details,
            }

            if cancellation:
                row["cancelled_at"] = cancellation.cancelled_at.isoformat() if cancellation.cancelled_at else None
                session_groups[sess_obj.id]["skipped"].append(row)
            elif not is_weekend:
                session_groups[sess_obj.id]["orders"].append(row)

    # Sort each session's orders by customer name
    for sg in session_groups.values():
        sg["orders"].sort(key=lambda r: r["customer_name"].lower())
        sg["skipped"].sort(key=lambda r: r["customer_name"].lower())

    return {
        "date": today.isoformat(),
        "is_weekend": is_weekend,
        "sessions": list(session_groups.values()),
    }


# ═══════════════════════════════════════════════════════════════
# SECTION 4 — Assignment
# ═══════════════════════════════════════════════════════════════

class AssignPayload(BaseModel):
    driver_id: str          # sent as string to avoid JS 64-bit int precision loss
    session_id: str         # also a CockroachDB bigint
    subscription_ids: List[str]   # subscription IDs also bigint
    delivery_date: Optional[date] = None  # defaults to today


@router.post("/assign", status_code=status.HTTP_201_CREATED)
def assign_orders(payload: AssignPayload, db: Session = Depends(get_db)):
    """Assign a list of orders to a driver for a specific session."""
    today = _today_ist()
    d_date = payload.delivery_date or today

    driver = db.query(User).filter(User.id == int(payload.driver_id), User.role == "driver").first()
    if not driver:
        raise HTTPException(status_code=404, detail="Driver not found.")
    if not driver.is_active:
        raise HTTPException(status_code=400, detail="Driver is inactive.")

    session = db.query(DeliverySession).filter(DeliverySession.id == int(payload.session_id)).first()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")
    # Pre-cast string IDs → int (CockroachDB bigints exceed JS safe integer range)
    _driver_id  = int(payload.driver_id)
    _session_id = int(payload.session_id)

    created = []
    skipped = []
    
    sub_ids = [int(sid) for sid in payload.subscription_ids]
    subs = {s.id: s for s in db.query(Subscription).filter(Subscription.id.in_(sub_ids)).all()}
    
    existing_assignments = {
        a.subscription_id for a in db.query(DeliveryAssignment).filter(
            DeliveryAssignment.subscription_id.in_(sub_ids),
            DeliveryAssignment.session_id == _session_id,
            DeliveryAssignment.delivery_date == d_date,
        ).all()
    }

    for sub_id_str in payload.subscription_ids:
        _sub_id = int(sub_id_str)
        sub = subs.get(_sub_id)
        if not sub:
            skipped.append(sub_id_str)
            continue

        if _sub_id in existing_assignments:
            skipped.append(sub_id_str)
            continue

        assignment = DeliveryAssignment(
            subscription_id = _sub_id,
            customer_id     = sub.customer_id,
            driver_id       = _driver_id,
            session_id      = _session_id,
            delivery_date   = d_date,
            status          = "assigned",
        )
        db.add(assignment)
        created.append(sub_id_str)

    db.commit()
    logger.info("Assigned %d orders to driver %s for session %s on %s", len(created), _driver_id, _session_id, d_date)
    return {
        "assigned": len(created),
        "skipped_already_assigned": len(skipped),
        "driver_name": driver.full_name,
        "session": session.name,
    }


# ═══════════════════════════════════════════════════════════════
# SECTION 5 — Admin Monitoring View
# ═══════════════════════════════════════════════════════════════

@router.get("/monitor")
def get_monitor(db: Session = Depends(get_db)):
    """Admin delivery monitoring: all drivers with their current status and active assignment."""
    today = _today_ist()
    drivers = db.query(User).filter(User.role == "driver").all()
    driver_ids = [d.id for d in drivers]

    statuses = {ds.driver_id: ds for ds in db.query(DriverStatus).filter(DriverStatus.driver_id.in_(driver_ids)).all()}
    sessions_map = {s.id: s for s in db.query(DeliverySession).all()}

    # Count today's assignments per driver
    counts = dict(
        db.query(DeliveryAssignment.driver_id, func.count(DeliveryAssignment.id))
        .filter(DeliveryAssignment.delivery_date == today, DeliveryAssignment.driver_id.in_(driver_ids))
        .group_by(DeliveryAssignment.driver_id)
        .all()
    )

    result = []
    for d in drivers:
        ds = statuses.get(d.id)
        current_session = sessions_map.get(ds.current_session_id).name if (ds and ds.current_session_id and ds.current_session_id in sessions_map) else None
        result.append({
            "driver_id": str(d.id),
            "driver_name": d.full_name,
            "email": d.email,
            "phone": d.phone,
            "is_active": d.is_active,
            "online_status": ds.status if ds else "offline",
            "current_session": current_session,
            "current_assignment_id": str(ds.current_assignment_id) if (ds and ds.current_assignment_id) else None,
            "last_latitude": ds.last_latitude if ds else None,
            "last_longitude": ds.last_longitude if ds else None,
            "last_updated": ds.last_updated.isoformat() if ds and ds.last_updated else None,
            "today_total": counts.get(d.id, 0),
        })

    return result


# ═══════════════════════════════════════════════════════════════
# SECTION 6 — Customer Location Geocoding
# ═══════════════════════════════════════════════════════════════

class LocationUpdatePayload(BaseModel):
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_link: Optional[str] = None


@router.put("/customers/{customer_id}/location")
def update_customer_location(
    customer_id: int,
    payload: LocationUpdatePayload,
    db: Session = Depends(get_db),
):
    """Admin can update a customer's geocoded location."""
    user = db.query(User).filter(User.id == customer_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Customer not found.")

    coords = geocode_user_location(
        address=payload.address or user.address_line_1,
        location_link=payload.location_link or user.location_link,
        latitude=payload.latitude,
        longitude=payload.longitude,
    )
    if coords:
        user.latitude, user.longitude = coords
    if payload.address:
        user.address_line_1 = payload.address
    if payload.location_link:
        user.location_link = payload.location_link

    db.commit()
    return {
        "customer_id": customer_id,
        "latitude": user.latitude,
        "longitude": user.longitude,
        "geocoded": coords is not None,
    }
