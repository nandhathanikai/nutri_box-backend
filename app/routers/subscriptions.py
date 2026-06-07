from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from datetime import datetime, timezone

from app.database import get_db
from app.models.credit import DeliveryCancellation, Credit
from app.models.meal_tier import MealTier
from app.models.menu import PlanTemplate
from app.models.subscription import Subscription
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.menu import MEAL_COUNT_MAP, DURATION_WORKING_DAYS, _get_current_price
from app.utils.credits import compute_cutoff, is_cancellation_eligible, get_last_credit_delivery_date
from app.utils.rate_limit import rate_limit


router = APIRouter(prefix="/api/subscriptions", tags=["Subscriptions"])


# ── Schemas ─────────────────────────────────────────────────────────────────

class SubscribeRequest(BaseModel):
    plan_id: Optional[str] = None      # If provided, use this PlanTemplate directly
    tier_slug: Optional[str] = None    # Else, resolve from selector inputs
    diet_type: Optional[str] = None    # 'veg' | 'nonveg'
    slot_combo: Optional[str] = None   # 'breakfast_only' | 'dinner_only' | 'both'
    duration: Optional[str] = None     # 'weekly' | 'monthly'
    start_date: Optional[date] = None  # Defaults to tomorrow


class SubscriptionOut(BaseModel):
    id: int
    plan_id: Optional[str] = None
    plan_name: Optional[str] = None
    tier_name: Optional[str] = None
    diet_type: Optional[str] = None
    slot_combo: Optional[str] = None
    duration: Optional[str] = None
    meal_count: Optional[int] = None
    price_per_meal: Optional[float] = None
    total_price: Optional[float] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    status: str  # active | expiring | expired

    class Config:
        from_attributes = True


# ── Helpers ─────────────────────────────────────────────────────────────────

def _next_working_day(d: date) -> date:
    """Walk forward (if needed) until d is Mon–Sat (only Sunday is off)."""
    while d.weekday() == 6:  # 6 = Sun
        d += timedelta(days=1)
    return d


def _last_delivery_date(start: date, duration: str) -> date:
    """Return the LAST delivery date of a subscription that begins on `start`.

    `start` must already be a working day (caller is responsible). Counts forward
    `n` working days inclusive (Mon–Sat only).
    """
    n = DURATION_WORKING_DAYS.get(duration, 6)
    cur = start
    counted = 1
    while counted < n:
        cur += timedelta(days=1)
        if cur.weekday() != 6:  # not Sunday
            counted += 1
    return cur


def _serialize(
    sub: Subscription,
    db: Session,
    plans_map: Optional[dict] = None,
    tiers_map: Optional[dict] = None,
) -> SubscriptionOut:
    """Hydrate a Subscription into its response shape.

    If `plans_map` / `tiers_map` are provided (keyed by id), use them instead of
    querying. Lets list endpoints bulk-load once and avoid N+1.
    """
    today = date.today()
    if sub.end_date and sub.end_date >= today:
        status = "expiring" if (sub.end_date - today).days <= 3 else "active"
    else:
        status = "expired"

    plan = None
    tier = None
    if sub.menu_id:
        if plans_map is not None:
            plan = plans_map.get(sub.menu_id)
        else:
            plan = db.query(PlanTemplate).filter(PlanTemplate.id == sub.menu_id).first()
        if plan:
            if tiers_map is not None:
                tier = tiers_map.get(plan.tier_id)
            else:
                tier = db.query(MealTier).filter(MealTier.id == plan.tier_id).first()

    price_per_meal = float(sub.price_per_meal_snapshot) if sub.price_per_meal_snapshot else (
        float(plan.price) / plan.meal_count if plan and plan.price and plan.meal_count else None
    )

    total_price = None
    if plan and plan.price is not None:
        total_price = float(plan.price)
    elif price_per_meal and plan and plan.meal_count:
        total_price = round(price_per_meal * plan.meal_count, 2)

    return SubscriptionOut(
        id=sub.id,
        plan_id=str(sub.menu_id) if sub.menu_id else None,
        plan_name=plan.name if plan else None,
        tier_name=tier.name if tier else None,
        diet_type=plan.diet_type if plan else None,
        slot_combo=plan.slot_combo if plan else None,
        duration=plan.duration if plan else None,
        meal_count=plan.meal_count if plan else None,
        price_per_meal=price_per_meal,
        total_price=total_price,
        start_date=sub.start_date,
        end_date=sub.end_date,
        status=status,
    )


def _resolve_plan(payload: SubscribeRequest, db: Session) -> PlanTemplate:
    """Find or create the PlanTemplate matching the requested combination."""
    if payload.plan_id:
        plan = db.query(PlanTemplate).filter(PlanTemplate.id == payload.plan_id).first()
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        return plan

    # Resolve via selector inputs
    if not (payload.tier_slug and payload.diet_type and payload.slot_combo and payload.duration):
        raise HTTPException(
            status_code=400,
            detail="Provide either plan_id, or tier_slug + diet_type + slot_combo + duration.",
        )

    tier = db.query(MealTier).filter(MealTier.slug == payload.tier_slug).first()
    if not tier:
        raise HTTPException(status_code=404, detail=f"Tier '{payload.tier_slug}' not found")

    if (payload.slot_combo, payload.duration) not in MEAL_COUNT_MAP:
        raise HTTPException(status_code=400, detail="Invalid slot_combo / duration combination")

    plan = db.query(PlanTemplate).filter(
        PlanTemplate.tier_id == tier.id,
        PlanTemplate.diet_type == payload.diet_type,
        PlanTemplate.slot_combo == payload.slot_combo,
        PlanTemplate.duration == payload.duration,
        PlanTemplate.is_legacy == False,  # noqa: E712
    ).first()

    if plan:
        return plan

    # Auto-create the plan template if a matching combination doesn't exist yet
    meal_count = MEAL_COUNT_MAP[(payload.slot_combo, payload.duration)]
    ppm = _get_current_price(str(tier.id), payload.diet_type, db)
    if ppm <= 0:
        raise HTTPException(
            status_code=400,
            detail="Pricing for this tier/diet is not configured. Please contact support.",
        )
    delivery_per_meal = float(
        tier.delivery_charge_weekly if payload.duration == "weekly" else tier.delivery_charge_monthly or 0
    )
    delivery_total = round(delivery_per_meal * meal_count, 2)
    plan = PlanTemplate(
        tier_id=tier.id,
        diet_type=payload.diet_type,
        duration=payload.duration,
        slot_combo=payload.slot_combo,
        meal_count=meal_count,
        total_meals=meal_count,
        meals_per_slot=1,
        meal_slots=[payload.slot_combo],
        price=round(ppm * meal_count + delivery_total, 2),
        delivery_charge=delivery_total,
        is_active=True,
        is_legacy=False,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


# ── Endpoints ───────────────────────────────────────────────────────────────

@router.get("/me", response_model=Optional[SubscriptionOut])
def get_my_subscription(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the user's most recent active/upcoming subscription, or null."""
    today = date.today()
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.customer_id == current_user.id,
            Subscription.end_date >= today,
        )
        .order_by(Subscription.end_date.desc())
        .first()
    )
    if not sub:
        return None
    return _serialize(sub, db)


@router.get("/me/all", response_model=list[SubscriptionOut])
def get_my_subscription_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    subs = (
        db.query(Subscription)
        .filter(Subscription.customer_id == current_user.id)
        .order_by(Subscription.start_date.desc())
        .all()
    )
    if not subs:
        return []

    plan_ids = {s.menu_id for s in subs if s.menu_id}
    plans_map = {
        p.id: p for p in db.query(PlanTemplate).filter(PlanTemplate.id.in_(plan_ids)).all()
    } if plan_ids else {}
    tier_ids = {p.tier_id for p in plans_map.values() if p.tier_id}
    tiers_map = {
        t.id: t for t in db.query(MealTier).filter(MealTier.id.in_(tier_ids)).all()
    } if tier_ids else {}

    return [_serialize(s, db, plans_map, tiers_map) for s in subs]


_subscribe_limit = rate_limit(max_calls=5, period_seconds=3600, scope="subscribe")


@router.post(
    "",
    response_model=SubscriptionOut,
    status_code=201,
    dependencies=[Depends(_subscribe_limit)],
)
def create_subscription(
    payload: SubscribeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new subscription for the current user. Used when they tap Subscribe on /plans."""
    plan = _resolve_plan(payload, db)

    # Block overlap with an existing active subscription
    today = date.today()
    overlap = (
        db.query(Subscription)
        .filter(
            Subscription.customer_id == current_user.id,
            Subscription.end_date >= today,
        )
        .first()
    )
    if overlap:
        raise HTTPException(
            status_code=409,
            detail="You already have an active subscription. Wait for it to end or cancel it first.",
        )

    if payload.start_date and payload.start_date < today:
        raise HTTPException(status_code=400, detail="start_date cannot be in the past.")

    # Squeeze logic: new plan starts after the last scheduled credit delivery
    scheduled_credits = db.query(Credit).filter(
        Credit.user_id == current_user.id,
        Credit.status == 'scheduled'
    ).all()
    earliest_start = get_last_credit_delivery_date(scheduled_credits, today)
    if scheduled_credits:
        earliest_start = earliest_start + timedelta(days=1)

    requested_start = payload.start_date or (today + timedelta(days=1))
    if requested_start < earliest_start:
        requested_start = earliest_start
    if requested_start < today:
        requested_start = today + timedelta(days=1)

    # Nutribox delivers Mon–Sat. Shift Sunday starts to Monday.
    start = _next_working_day(requested_start)
    end = _last_delivery_date(start, plan.duration or "weekly")

    # Snapshot price-per-meal so future price changes don't retroactively affect this sub
    ppm_snapshot = None
    if plan.meal_count and plan.price:
        ppm_snapshot = round(float(plan.price) / plan.meal_count, 2)
    else:
        ppm_snapshot = _get_current_price(str(plan.tier_id), plan.diet_type, db) or None

    sub = Subscription(
        customer_id=current_user.id,
        menu_id=plan.id,
        start_date=start,
        end_date=end,
        price_per_meal_snapshot=ppm_snapshot,
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return _serialize(sub, db)


@router.get("/me/calendar")
def get_my_calendar(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return a day-by-day calendar for the current/most-recent active subscription.

    For each day in [start_date, end_date]:
      - is_weekend: True if Sunday (Nutribox delivers Mon–Sat; Sunday is off)
      - sessions: per-session status — delivered | today | scheduled | skipped | no_delivery

    Customer uses this to skip future weekday deliveries.
    """
    today = date.today()
    sub = (
        db.query(Subscription)
        .filter(
            Subscription.customer_id == current_user.id,
            Subscription.end_date >= today,
        )
        .order_by(Subscription.end_date.desc())
        .first()
    )
    if not sub:
        return {"subscription": None, "days": []}

    plan = db.query(PlanTemplate).filter(PlanTemplate.id == sub.menu_id).first() if sub.menu_id else None
    tier = (
        db.query(MealTier).filter(MealTier.id == plan.tier_id).first()
        if plan and plan.tier_id else None
    )

    # Sessions defined by the plan's slot_combo
    sessions: list[dict] = []
    if plan and plan.slot_combo in ("breakfast_only", "both"):
        sessions.append({"key": "BF", "label": "Breakfast"})
    if plan and plan.slot_combo in ("dinner_only", "both"):
        sessions.append({"key": "DINNER", "label": "Dinner"})

    # Pre-load every cancellation row for this subscription so we don't hit DB per day
    cancellations = db.query(DeliveryCancellation).filter(
        DeliveryCancellation.subscription_id == sub.id
    ).all()
    cancel_map = {(c.delivery_date, (c.session or "").upper()): c for c in cancellations}

    now_utc = datetime.now(timezone.utc)
    days: list[dict] = []
    cur = sub.start_date
    while cur and sub.end_date and cur <= sub.end_date:
        is_weekend = cur.weekday() == 6  # Sunday only
        day_sessions = []
        for s in sessions:
            cancellation = cancel_map.get((cur, s["key"]))
            cutoff_utc = compute_cutoff(cur)
            cutoff_passed = now_utc >= cutoff_utc

            if is_weekend:
                status_label = "no_delivery"
                cancellable = False
                undoable = False
            elif cancellation:
                status_label = "skipped"
                cancellable = False
                # Same 6 PM previous-day rule — undo only allowed before cutoff
                undoable = not cutoff_passed
            elif cur < today:
                status_label = "delivered"
                cancellable = False
                undoable = False
            elif cur == today:
                status_label = "today"
                cancellable = not cutoff_passed
                undoable = False
            else:
                status_label = "scheduled"
                cancellable = not cutoff_passed
                undoable = False

            day_sessions.append({
                "key": s["key"],
                "label": s["label"],
                "status": status_label,
                "cancellable": cancellable,
                "undoable": undoable,
                "cancellation_id": cancellation.id if cancellation else None,
                "cutoff_at": cutoff_utc.isoformat(),
            })
        days.append({
            "date": cur.isoformat(),
            "weekday": cur.strftime("%a"),
            "is_weekend": is_weekend,
            "is_today": cur == today,
            "is_past": cur < today,
            "sessions": day_sessions,
        })
        cur += timedelta(days=1)

    return {
        "subscription": {
            "id": sub.id,
            "tier_name": tier.name if tier else None,
            "duration": plan.duration if plan else None,
            "slot_combo": plan.slot_combo if plan else None,
            "diet_type": plan.diet_type if plan else None,
            "start_date": sub.start_date.isoformat() if sub.start_date else None,
            "end_date": sub.end_date.isoformat() if sub.end_date else None,
        },
        "days": days,
    }


@router.delete("/{sub_id}", status_code=204)
def cancel_my_subscription(
    sub_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Soft-cancel a subscription.

    If the customer cancels AFTER the 6 PM IST cutoff for tomorrow, tomorrow's
    delivery is already on the line for the kitchen — honor it by ending the
    subscription at tomorrow instead of today. Otherwise end today.
    """
    sub = (
        db.query(Subscription)
        .filter(Subscription.id == sub_id, Subscription.customer_id == current_user.id)
        .first()
    )
    if not sub:
        raise HTTPException(status_code=404, detail="Subscription not found")

    today = date.today()
    if sub.end_date and sub.end_date < today:
        raise HTTPException(status_code=400, detail="Subscription is already ended.")

    tomorrow = today + timedelta(days=1)
    if not is_cancellation_eligible(tomorrow, datetime.now(timezone.utc)):
        # Past cutoff — tomorrow's prep is locked in.
        sub.end_date = tomorrow
    else:
        sub.end_date = today
    db.commit()
    return
