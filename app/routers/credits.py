from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, date, timezone
from typing import Optional
from collections import defaultdict

from app.database import get_db
from app.models.credit import Credit, DeliveryCancellation
from app.models.menu import PlanTemplate
from app.models.subscription import Subscription
from app.models.user import User
from app.schemas.credit import (
    CancelDeliveryRequest, CancelDeliveryResponse,
    MyCreditsResponse, CreditOut, CreditBalanceSummary,
    ManualCreditRequest, AdminCreditOut, OverviewCustomer, StatsResponse,
)
from app.utils.credits import is_cancellation_eligible, compute_cutoff, CREDIT_DAYS_PER_CANCEL
from app.jobs.credit_jobs import promote_pending_credits, mark_delivered
from app.routers.auth import get_current_user, require_admin

router = APIRouter(tags=["Credits"])


# ── Customer Endpoints ────────────────────────────────────────────────────────

@router.post("/api/deliveries/{delivery_date}/cancel", response_model=CancelDeliveryResponse)
def cancel_delivery(
    delivery_date: date,
    payload: CancelDeliveryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    # Lookup active subscription
    sub = db.query(Subscription).filter(
        Subscription.customer_id == user.id,
        Subscription.start_date <= delivery_date,
        Subscription.end_date >= delivery_date
    ).first()

    if not sub:
        raise HTTPException(status_code=404, detail="No active subscription found for this date.")

    # Mon–Sat only — there's nothing to cancel on Sunday.
    if delivery_date.weekday() == 6:
        raise HTTPException(status_code=400, detail="No deliveries scheduled on Sundays.")

    # Prevent duplicate cancellations for the same (user, date, session).
    existing = db.query(DeliveryCancellation).filter(
        DeliveryCancellation.user_id == user.id,
        DeliveryCancellation.delivery_date == delivery_date,
        DeliveryCancellation.session == payload.session,
    ).first()
    if existing:
        raise HTTPException(
            status_code=409,
            detail="This delivery has already been cancelled.",
        )

    cancelled_at = datetime.utcnow()
    eligible = is_cancellation_eligible(delivery_date, cancelled_at)
    cutoff = compute_cutoff(delivery_date)

    # Both rows (and their cross-reference) commit atomically so we never end up
    # with a cancellation that was supposed to issue a credit but didn't.
    try:
        cancellation = DeliveryCancellation(
            user_id=user.id,
            subscription_id=sub.id,
            delivery_date=delivery_date,
            session=payload.session,
            cancelled_at=cancelled_at,
            cutoff_deadline=cutoff,
            is_eligible=eligible,
        )
        db.add(cancellation)

        credit = None
        if eligible:
            db.flush()  # assigns cancellation.id without committing
            credit = Credit(
                user_id=user.id,
                subscription_id=sub.id,
                cancellation_id=cancellation.id,
                session=payload.session,
                original_delivery_date=delivery_date,
                credit_days=CREDIT_DAYS_PER_CANCEL,
                status="pending",
                plan_end_date=sub.end_date,
                is_manual=False,
            )
            db.add(credit)
            db.flush()  # assigns credit.id
            cancellation.credit_id = credit.id

        db.commit()
        db.refresh(cancellation)
        if credit is not None:
            db.refresh(credit)
    except Exception:
        db.rollback()
        raise

    if eligible:
        msg = (
            f"Cancellation recorded. {CREDIT_DAYS_PER_CANCEL} credit day(s) for {payload.session} "
            f"will be delivered after your plan ends on {sub.end_date.strftime('%B %d')}."
        )
        return CancelDeliveryResponse(eligible=True, message=msg, credit_id=credit.id)
    else:
        msg = f"Cancellation recorded, but the 6 PM cutoff for {delivery_date.strftime('%B %d')} has passed. No credit issued."
        return CancelDeliveryResponse(eligible=False, message=msg, credit_id=None)


@router.post("/api/deliveries/{delivery_date}/uncancel")
def uncancel_delivery(
    delivery_date: date,
    payload: CancelDeliveryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Undo a previously-recorded skip. Allowed only before the 6 PM previous-day cutoff."""
    cancellation = db.query(DeliveryCancellation).filter(
        DeliveryCancellation.user_id == user.id,
        DeliveryCancellation.delivery_date == delivery_date,
        DeliveryCancellation.session == payload.session,
    ).first()
    if not cancellation:
        raise HTTPException(status_code=404, detail="No skip found for this delivery.")

    # Re-compute the cutoff fresh — DB stores naive UTC, and we don't want to depend on it.
    cutoff_utc = compute_cutoff(delivery_date)
    now_utc = datetime.now(timezone.utc)
    if now_utc >= cutoff_utc:
        raise HTTPException(
            status_code=400,
            detail="The 6 PM cutoff has passed — this skip can no longer be undone.",
        )

    # Remove any associated credit. At this point the plan has not ended yet
    # (cutoff is the day before delivery), so the credit is still 'pending'.
    if cancellation.credit_id:
        credit = db.query(Credit).filter(Credit.id == cancellation.credit_id).first()
        if credit and credit.status == "pending":
            db.delete(credit)

    db.delete(cancellation)
    db.commit()

    return {"message": f"Skip for {delivery_date.strftime('%B %d')} ({payload.session}) cancelled."}


@router.get("/api/credits/me", response_model=MyCreditsResponse)
def get_my_credits(db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    credits = db.query(Credit).filter(Credit.user_id == user.id).order_by(Credit.created_at.desc()).all()

    pending = sum(c.credit_days for c in credits if c.status == "pending")
    scheduled = sum(c.credit_days for c in credits if c.status == "scheduled")
    delivered = sum(c.credit_days for c in credits if c.status == "delivered")

    # Bulk-load cancellations once, keyed by id — avoids N+1.
    cancel_ids = [c.cancellation_id for c in credits if c.cancellation_id]
    cancel_map = {
        canc.id: canc for canc in db.query(DeliveryCancellation)
        .filter(DeliveryCancellation.id.in_(cancel_ids)).all()
    } if cancel_ids else {}

    out_credits = []
    for c in credits:
        canc = cancel_map.get(c.cancellation_id) if c.cancellation_id else None
        out_credits.append(CreditOut(
            id=c.id,
            session=c.session,
            original_delivery_date=c.original_delivery_date,
            delivery_on=c.delivery_on,
            credit_days=c.credit_days,
            status=c.status,
            plan_end_date=c.plan_end_date,
            is_manual=c.is_manual,
            notes=c.notes,
            cancelled_at=canc.cancelled_at if canc else None,
            created_at=c.created_at,
        ))

    return MyCreditsResponse(
        balance=CreditBalanceSummary(pending=pending, scheduled=scheduled, delivered=delivered),
        credits=out_credits
    )


# ── Admin Endpoints ───────────────────────────────────────────────────────────

@router.get("/api/admin/credits/stats", response_model=StatsResponse)
def get_credit_stats(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Return aggregate credit counts — one grouped SQL query, no ORM hydration."""
    rows = db.query(Credit.status, func.count(Credit.id)).group_by(Credit.status).all()
    counts = {status: cnt for status, cnt in rows}
    return StatsResponse(
        pending=counts.get("pending", 0),
        scheduled=counts.get("scheduled", 0),
        delivered=counts.get("delivered", 0),
        total=sum(counts.values()),
    )


@router.get("/api/admin/credits/overview")
def get_credits_overview(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Returns customers who have active (pending or scheduled) credits,
    grouped with their plan and credit details.
    """
    active_credits = (
        db.query(Credit)
        .filter(Credit.status.in_(["pending", "scheduled"]))
        .order_by(Credit.original_delivery_date.asc())
        .all()
    )
    if not active_credits:
        return []

    # Group by customer
    by_customer = defaultdict(list)
    for c in active_credits:
        by_customer[c.user_id].append(c)

    user_ids = list(by_customer.keys())
    cancel_ids = [c.cancellation_id for c in active_credits if c.cancellation_id]

    # Bulk-load users, latest subscription per user, and cancellations — three queries total.
    users_map = {u.id: u for u in db.query(User).filter(User.id.in_(user_ids)).all()}

    latest_sub_subq = (
        db.query(
            Subscription.customer_id.label("customer_id"),
            Subscription.start_date.label("start_date"),
            Subscription.end_date.label("end_date"),
            func.row_number()
                .over(partition_by=Subscription.customer_id,
                      order_by=Subscription.end_date.desc().nullslast())
                .label("rn"),
        )
        .filter(Subscription.customer_id.in_(user_ids))
        .subquery()
    )
    sub_rows = (
        db.query(
            latest_sub_subq.c.customer_id,
            latest_sub_subq.c.start_date,
            latest_sub_subq.c.end_date,
        )
        .filter(latest_sub_subq.c.rn == 1)
        .all()
    )
    sub_map = {r.customer_id: r for r in sub_rows}

    cancel_map = {
        canc.id: canc for canc in db.query(DeliveryCancellation)
        .filter(DeliveryCancellation.id.in_(cancel_ids)).all()
    } if cancel_ids else {}

    today = date.today()
    results = []
    for user_id, user_credits in by_customer.items():
        user = users_map.get(user_id)
        if not user:
            continue

        sub = sub_map.get(user_id)
        pending_count = sum(1 for c in user_credits if c.status == "pending")
        scheduled_count = sum(1 for c in user_credits if c.status == "scheduled")

        credit_list = []
        for c in user_credits:
            canc = cancel_map.get(c.cancellation_id) if c.cancellation_id else None
            credit_list.append({
                "id": c.id,
                "customer_name": user.full_name,
                "customer_id": user.id,
                "customer_email": user.email,
                "session": c.session,
                "original_delivery_date": c.original_delivery_date,
                "delivery_on": c.delivery_on,
                "cancelled_at": canc.cancelled_at if canc else None,
                "credit_days": c.credit_days,
                "plan_end_date": c.plan_end_date,
                "plan_name": "Nutribox Plan",
                "plan_start": sub.start_date if sub else None,
                "plan_end": sub.end_date if sub else None,
                "status": c.status,
                "is_manual": c.is_manual,
                "notes": c.notes,
                "created_at": c.created_at,
            })

        results.append({
            "customer_id": user.id,
            "customer_name": user.full_name,
            "customer_email": user.email,
            "plan_name": "Nutribox Plan",
            "plan_start": sub.start_date if sub else None,
            "plan_end": sub.end_date if sub else None,
            "plan_status": "active" if sub and sub.end_date and sub.end_date >= today else "completed",
            "pending_count": pending_count,
            "scheduled_count": scheduled_count,
            "delivered_count": 0,
            "credits": credit_list,
        })

    return results


@router.get("/api/admin/credits")
def get_all_credits(
    status_filter: Optional[str] = Query(None, alias="status"),
    month: Optional[str] = Query(None),  # format YYYY-MM
    user_id: Optional[int] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1),
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    query = db.query(Credit).join(User)

    if status_filter:
        query = query.filter(Credit.status == status_filter)
    if user_id:
        query = query.filter(Credit.user_id == user_id)
    if search:
        query = query.filter(User.full_name.ilike(f"%{search}%"))
    if month:
        try:
            year, mon = month.split("-")
            query = query.filter(
                func.extract('year', Credit.original_delivery_date) == int(year),
                func.extract('month', Credit.original_delivery_date) == int(mon),
            )
        except Exception:
            pass

    total = query.count()
    credits = query.order_by(Credit.created_at.desc()).offset((page - 1) * limit).limit(limit).all()

    # Bulk-load subscriptions + cancellations referenced by this page of credits.
    sub_ids = {c.subscription_id for c in credits if c.subscription_id}
    cancel_ids = {c.cancellation_id for c in credits if c.cancellation_id}
    sub_map = {
        s.id: s for s in db.query(Subscription).filter(Subscription.id.in_(sub_ids)).all()
    } if sub_ids else {}
    cancel_map = {
        canc.id: canc for canc in db.query(DeliveryCancellation)
        .filter(DeliveryCancellation.id.in_(cancel_ids)).all()
    } if cancel_ids else {}

    results = []
    for c in credits:
        u = c.user
        sub = sub_map.get(c.subscription_id) if c.subscription_id else None
        canc = cancel_map.get(c.cancellation_id) if c.cancellation_id else None
        cancelled_at = canc.cancelled_at if canc else None

        results.append({
            "id": c.id,
            "customer_name": u.full_name if u else "Unknown",
            "customer_id": u.id if u else None,
            "customer_email": u.email if u else None,
            "session": c.session,
            "original_delivery_date": c.original_delivery_date,
            "delivery_on": c.delivery_on,
            "cancelled_at": cancelled_at,
            "credit_days": c.credit_days,
            "plan_end_date": c.plan_end_date,
            "plan_name": "Nutribox Plan",
            "plan_start": sub.start_date if sub else None,
            "plan_end": sub.end_date if sub else None,
            "status": c.status,
            "is_manual": c.is_manual,
            "notes": c.notes,
            "created_at": c.created_at,
        })

    return {
        "total": total,
        "page": page,
        "limit": limit,
        "data": results
    }


@router.post("/api/admin/credits/manual")
def add_manual_credit(
    payload: ManualCreditRequest,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Add a manual credit for a customer (bypasses cutoff check)."""
    user = db.query(User).filter(User.id == payload.customer_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Customer not found")

    # Find most recent subscription (for context)
    sub = db.query(Subscription).filter(
        Subscription.customer_id == payload.customer_id,
    ).order_by(Subscription.end_date.desc()).first()

    # Validate that the requested session is actually offered by the plan's
    # slot_combo. Stops "Lunch credit on a breakfast-only plan" data corruption.
    if sub and sub.menu_id:
        plan = db.query(PlanTemplate).filter(PlanTemplate.id == sub.menu_id).first()
        slot_combo = (plan.slot_combo if plan else "") or ""
        session_norm = (payload.session or "").upper()
        allowed: set[str] = set()
        if slot_combo in ("breakfast_only", "both"):
            allowed.add("BF")
        if slot_combo in ("dinner_only", "both"):
            allowed.add("DINNER")
        if allowed and session_norm not in allowed:
            raise HTTPException(
                status_code=400,
                detail=f"Session '{payload.session}' is not part of this customer's plan (slot_combo={slot_combo}).",
            )

    credit = Credit(
        user_id=payload.customer_id,
        subscription_id=sub.id if sub else None,
        cancellation_id=None,
        session=payload.session,
        original_delivery_date=payload.delivery_on,
        delivery_on=payload.delivery_on,
        credit_days=CREDIT_DAYS_PER_CANCEL,
        status="scheduled",
        plan_end_date=sub.end_date if sub else None,
        is_manual=True,
        notes=payload.note or f"Admin manual credit by {admin.full_name}",
    )
    db.add(credit)
    db.commit()
    db.refresh(credit)

    return {
        "message": f"Manual credit added for {user.full_name}",
        "credit_id": credit.id,
        "delivery_on": str(credit.delivery_on),
    }


@router.patch("/api/admin/credits/{credit_id}")
def update_credit(
    credit_id: int,
    payload: dict,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin)
):
    credit = db.query(Credit).filter(Credit.id == credit_id).first()
    if not credit:
        raise HTTPException(status_code=404, detail="Credit not found")

    if "status" in payload:
        credit.status = payload["status"]
    if "notes" in payload:
        credit.notes = payload["notes"]
    if "delivery_on" in payload and payload["delivery_on"]:
        credit.delivery_on = payload["delivery_on"]

    credit.updated_at = datetime.utcnow()
    db.commit()
    return {"message": "Credit updated successfully", "status": credit.status}


@router.post("/api/credits/process")
def process_pending_credits_endpoint(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """
    Two-phase processing:
    1. Promote pending → scheduled (assign delivery dates)
    2. Mark scheduled → delivered (where delivery_on <= today)
    """
    promoted = promote_pending_credits(db)
    marked = mark_delivered(db)

    return {
        "promoted": promoted,
        "delivered": marked,
        "message": (
            f"{promoted} credit(s) scheduled for delivery. "
            f"{marked} credit(s) marked as delivered."
        ),
    }


# ── Customers list for dropdowns ──────────────────────────────────────────────

@router.get("/api/admin/customers/list")
def get_customers_list(
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Simple customer list for admin dropdowns (manual credit, compose message)."""
    users = db.query(User).filter(User.role == "customer").order_by(User.full_name).all()
    return [{"id": u.id, "name": u.full_name, "email": u.email} for u in users]
