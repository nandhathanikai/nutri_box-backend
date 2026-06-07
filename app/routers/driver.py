"""
Driver Router
-------------
Endpoints for delivery partners (role = 'driver'):
  - View today's assigned deliveries grouped by session
  - Start a delivery (triggers real-time tracking)
  - Mark delivery as delivered
  - Update driver availability status
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.user import User
from app.models.subscription import Subscription
from app.models.menu import PlanTemplate
from app.models.meal_tier import MealTier
from app.models.delivery import (
    DeliveryAssignment, DeliverySession, DriverStatus
)
from app.routers.auth import get_current_user
from app.utils.ws_manager import ws_manager

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> date:
    return datetime.now(IST).date()


def require_driver(current_user: User = Depends(get_current_user)) -> User:
    if not current_user.role or current_user.role.lower() != "driver":
        raise HTTPException(status_code=403, detail="Driver access required")
    if not current_user.is_active:
        raise HTTPException(status_code=403, detail="Your driver account is inactive.")
    return current_user


router = APIRouter(
    prefix="/api/driver",
    tags=["Driver"],
)


# ── Driver's deliveries grouped by session ────────────────────────────────────

@router.get("/deliveries")
def get_my_deliveries(
    driver: User = Depends(require_driver),
    db: Session = Depends(get_db),
):
    """Return today's assignments for the logged-in driver, grouped by session."""
    today = _today_ist()

    assignments = (
        db.query(DeliveryAssignment)
        .filter(
            DeliveryAssignment.driver_id == driver.id,
            DeliveryAssignment.delivery_date == today,
        )
        .all()
    )

    if not assignments:
        return {"date": today.isoformat(), "sessions": []}

    # Load related data
    customer_ids = [a.customer_id for a in assignments if a.customer_id]
    session_ids = list({a.session_id for a in assignments})
    sub_ids = [a.subscription_id for a in assignments if a.subscription_id]

    customers = {u.id: u for u in db.query(User).filter(User.id.in_(customer_ids)).all()}
    sessions = {s.id: s for s in db.query(DeliverySession).filter(DeliverySession.id.in_(session_ids)).all()}

    # Load subscriptions → plan → tier for tier name
    subs = {s.id: s for s in db.query(Subscription).filter(Subscription.id.in_(sub_ids)).all()} if sub_ids else {}
    menu_ids = list({s.menu_id for s in subs.values() if s.menu_id})
    plans = {p.id: p for p in db.query(PlanTemplate).filter(PlanTemplate.id.in_(menu_ids)).all()} if menu_ids else {}
    tier_ids = list({p.tier_id for p in plans.values() if p.tier_id})
    tiers = {t.id: t for t in db.query(MealTier).filter(MealTier.id.in_(tier_ids)).all()} if tier_ids else {}

    # Group by session
    session_groups: dict = {}
    for a in assignments:
        sess = sessions.get(a.session_id)
        if not sess:
            continue
        cust = customers.get(a.customer_id)
        sub = subs.get(a.subscription_id)
        plan = plans.get(sub.menu_id) if sub and sub.menu_id else None
        tier = tiers.get(plan.tier_id) if plan and plan.tier_id else None

        address_parts = []
        if cust:
            if cust.address_line_1: address_parts.append(cust.address_line_1)
            if cust.address_line_2: address_parts.append(cust.address_line_2)
            if cust.landmark: address_parts.append(f"Near {cust.landmark}")

        delivery_row = {
            "assignment_id": str(a.id),
            "subscription_id": str(a.subscription_id),
            "customer_id": str(a.customer_id),
            "customer_name": cust.full_name if cust else "—",
            "customer_phone": cust.phone if cust else "—",
            "address": ", ".join(address_parts) if address_parts else "—",
            "latitude": cust.latitude if cust else None,
            "longitude": cust.longitude if cust else None,
            "location_link": cust.location_link if cust else None,
            "tier_name": tier.name if tier else "—",
            "tier_slug": tier.slug if (tier and hasattr(tier, "slug")) else "basic",
            "plan_name": plan.name if plan else "—",
            "diet_type": plan.diet_type if plan else "—",
            "status": a.status,
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
            "started_at": a.started_at.isoformat() if a.started_at else None,
            "delivered_at": a.delivered_at.isoformat() if a.delivered_at else None,
        }

        if sess.id not in session_groups:
            session_groups[sess.id] = {
                "session_id": str(sess.id),
                "session_name": sess.name,
                "slug": sess.slug,
                "display_order": sess.display_order,
                "deliveries": [],
            }
        session_groups[sess.id]["deliveries"].append(delivery_row)

    # Sort sessions by display_order
    sorted_sessions = sorted(session_groups.values(), key=lambda s: s["display_order"])
    for sg in sorted_sessions:
        sg["deliveries"].sort(key=lambda d: d["customer_name"].lower())

    return {"date": today.isoformat(), "sessions": sorted_sessions}


# ── Start Delivery ────────────────────────────────────────────────────────────

@router.post("/delivery/{assignment_id}/start")
async def start_delivery(
    assignment_id: int,
    driver: User = Depends(require_driver),
    db: Session = Depends(get_db),
):
    """Driver starts a delivery — changes status to on_the_way."""
    assignment = db.query(DeliveryAssignment).filter(
        DeliveryAssignment.id == assignment_id,
        DeliveryAssignment.driver_id == driver.id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    if assignment.status not in ("assigned",):
        raise HTTPException(status_code=400, detail=f"Cannot start delivery in status '{assignment.status}'.")

    assignment.status = "on_the_way"
    assignment.started_at = datetime.now(timezone.utc)
    db.commit()

    # Update driver status table
    ds = db.query(DriverStatus).filter(DriverStatus.driver_id == driver.id).first()
    if ds:
        ds.status = "on_delivery"
        ds.current_session_id = assignment.session_id
        ds.current_assignment_id = assignment_id
        ds.last_updated = datetime.now(timezone.utc)
        db.commit()
    else:
        db.add(DriverStatus(
            driver_id=driver.id,
            status="on_delivery",
            current_session_id=assignment.session_id,
            current_assignment_id=assignment_id,
        ))
        db.commit()

    # Broadcast status change to any listening customers
    await ws_manager.broadcast_status_change(assignment_id, "on_the_way")

    return {"assignment_id": str(assignment_id), "status": "on_the_way"}


# ── Mark Delivered ────────────────────────────────────────────────────────────

@router.post("/delivery/{assignment_id}/delivered")
async def mark_delivered(
    assignment_id: int,
    driver: User = Depends(require_driver),
    db: Session = Depends(get_db),
):
    """Driver marks an order as delivered. No OTP or proof required."""
    assignment = db.query(DeliveryAssignment).filter(
        DeliveryAssignment.id == assignment_id,
        DeliveryAssignment.driver_id == driver.id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found.")
    if assignment.status == "delivered":
        raise HTTPException(status_code=400, detail="Already marked as delivered.")

    assignment.status = "delivered"
    assignment.delivered_at = datetime.now(timezone.utc)
    db.commit()

    # Set driver back to available
    ds = db.query(DriverStatus).filter(DriverStatus.driver_id == driver.id).first()
    if ds:
        ds.status = "available"
        ds.current_assignment_id = None
        ds.last_updated = datetime.now(timezone.utc)
        db.commit()

    # Stop broadcasting — notify customer of completion
    await ws_manager.broadcast_status_change(assignment_id, "delivered")

    return {"assignment_id": str(assignment_id), "status": "delivered"}


# ── Driver Status Update ──────────────────────────────────────────────────────

class StatusPayload(BaseModel):
    status: str  # available | on_delivery | offline

    @classmethod
    def validate_status(cls, v):
        if v not in ("available", "on_delivery", "offline"):
            raise ValueError("status must be available, on_delivery, or offline")
        return v


@router.put("/status")
def update_my_status(
    payload: StatusPayload,
    driver: User = Depends(require_driver),
    db: Session = Depends(get_db),
):
    """Driver updates their own availability status."""
    if payload.status not in ("available", "on_delivery", "offline"):
        raise HTTPException(status_code=400, detail="Invalid status.")
    ds = db.query(DriverStatus).filter(DriverStatus.driver_id == driver.id).first()
    if ds:
        ds.status = payload.status
        ds.last_updated = datetime.now(timezone.utc)
    else:
        db.add(DriverStatus(driver_id=driver.id, status=payload.status))
    db.commit()
    return {"driver_id": str(driver.id), "status": payload.status}


# ── Get route for an assignment (customer coordinates) ────────────────────────

@router.get("/delivery/{assignment_id}/route")
def get_route_info(
    assignment_id: int,
    driver: User = Depends(require_driver),
    db: Session = Depends(get_db),
):
    """Return customer coordinates for a delivery so the frontend can build the route."""
    assignment = db.query(DeliveryAssignment).filter(
        DeliveryAssignment.id == assignment_id,
        DeliveryAssignment.driver_id == driver.id,
    ).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found.")

    customer = db.query(User).filter(User.id == assignment.customer_id).first()
    if not customer:
        raise HTTPException(status_code=404, detail="Customer not found.")

    return {
        "assignment_id": str(assignment_id),
        "customer_name": customer.full_name,
        "customer_phone": customer.phone,
        "address": ", ".join(filter(None, [
            customer.address_line_1,
            customer.address_line_2,
            f"Near {customer.landmark}" if customer.landmark else None,
        ])),
        "latitude": customer.latitude,
        "longitude": customer.longitude,
        "location_link": customer.location_link,
        "status": assignment.status,
    }
