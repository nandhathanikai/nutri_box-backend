"""Seed demo subscriptions for design verification.

User 8  -> weekly  sub on the first active tier (veg, both slots), starting Monday of the current week.
User 10 -> monthly sub on the first active tier (veg, both slots), starting Monday two weeks ago.

Idempotent: re-running deletes any prior demo sub for that (user, plan, start_date) before re-inserting.
Bypasses the API's "active sub already exists" check on purpose — this is a seed script for testing.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, timedelta
from decimal import Decimal

from app.database import SessionLocal
from app.models.user import User
from app.models.subscription import Subscription
from app.models.meal_tier import MealTier
from app.models.menu import PlanTemplate, TierPricing, WeeklyMenuImage  # noqa: F401
from app.models.credit import Credit, DeliveryCancellation  # noqa: F401


WEEKLY_WORKING_DAYS = 6
MONTHLY_WORKING_DAYS = 24


def monday_of(d: date) -> date:
    return d - timedelta(days=d.weekday())


def last_delivery_date(start: date, working_days: int) -> date:
    """Walk `working_days` Mon-Sat days starting from `start` (inclusive)."""
    cur = start
    counted = 1
    while counted < working_days:
        cur += timedelta(days=1)
        if cur.weekday() != 6:  # not Sunday
            counted += 1
    return cur


def pick_demo_plan(db, duration: str, slot_combo: str = "both", diet: str = "veg"):
    """First active tier by display_order with veg & both-slots plan template."""
    tier = (
        db.query(MealTier)
        .filter(MealTier.is_active == True)
        .order_by(MealTier.display_order.asc())
        .first()
    )
    if not tier:
        raise SystemExit("No active tier in meal_tiers — cannot seed demo data.")

    plan = (
        db.query(PlanTemplate)
        .filter(
            PlanTemplate.tier_id == tier.id,
            PlanTemplate.diet_type == diet,
            PlanTemplate.slot_combo == slot_combo,
            PlanTemplate.duration == duration,
            PlanTemplate.is_active == True,
            PlanTemplate.is_legacy == False,
        )
        .order_by(PlanTemplate.id)  # deterministic when duplicates exist
        .first()
    )
    if not plan:
        raise SystemExit(
            f"No matching PlanTemplate found for tier={tier.name} diet={diet} "
            f"slot={slot_combo} duration={duration}. Run the API once to auto-create it."
        )

    # Latest active price-per-meal for this tier+diet, effective on or before today
    today = date.today()
    pricing = (
        db.query(TierPricing)
        .filter(
            TierPricing.tier_id == tier.id,
            TierPricing.diet_type == diet,
            TierPricing.is_active == True,
            TierPricing.effective_from <= today,
        )
        .order_by(TierPricing.effective_from.desc())
        .first()
    )
    ppm = Decimal(str(pricing.price_per_meal)) if pricing else None
    return tier, plan, ppm


def upsert_demo_sub(db, user_id: int, plan, start_date: date, end_date: date, ppm):
    """Replace any prior subscription with the same (customer, plan, start_date)."""
    existing = (
        db.query(Subscription)
        .filter(
            Subscription.customer_id == user_id,
            Subscription.menu_id == plan.id,
            Subscription.start_date == start_date,
        )
        .all()
    )
    for s in existing:
        # Clear dependent rows so the delete doesn't trip FK constraints.
        db.query(DeliveryCancellation).filter(
            DeliveryCancellation.subscription_id == s.id
        ).delete(synchronize_session=False)
        db.query(Credit).filter(Credit.subscription_id == s.id).delete(synchronize_session=False)
        db.delete(s)
    db.flush()

    sub = Subscription(
        customer_id=user_id,
        menu_id=plan.id,
        start_date=start_date,
        end_date=end_date,
        price_per_meal_snapshot=ppm,
    )
    db.add(sub)
    db.flush()
    return sub


def main():
    db = SessionLocal()
    try:
        today = date.today()
        this_monday = monday_of(today)
        two_weeks_ago_monday = this_monday - timedelta(days=14)

        # ── User 8: weekly demo ────────────────────────────────────────────
        u8 = db.query(User).filter(User.id == 8).first()
        if not u8:
            raise SystemExit("user_id=8 not found.")
        tier_w, plan_w, ppm_w = pick_demo_plan(db, duration="weekly")
        start_w = this_monday
        end_w = last_delivery_date(start_w, WEEKLY_WORKING_DAYS)
        sub_w = upsert_demo_sub(db, 8, plan_w, start_w, end_w, ppm_w)
        print(
            f"[user 8] weekly  -> tier={tier_w.name!r} plan={plan_w.id} "
            f"{start_w} .. {end_w} ppm={ppm_w}  (sub id={sub_w.id})"
        )

        # ── User 10: monthly demo ──────────────────────────────────────────
        u10 = db.query(User).filter(User.id == 10).first()
        if not u10:
            raise SystemExit("user_id=10 not found.")
        tier_m, plan_m, ppm_m = pick_demo_plan(db, duration="monthly")
        start_m = two_weeks_ago_monday
        end_m = last_delivery_date(start_m, MONTHLY_WORKING_DAYS)
        sub_m = upsert_demo_sub(db, 10, plan_m, start_m, end_m, ppm_m)
        print(
            f"[user 10] monthly -> tier={tier_m.name!r} plan={plan_m.id} "
            f"{start_m} .. {end_m} ppm={ppm_m}  (sub id={sub_m.id})"
        )

        db.commit()
        print("\nCommitted.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    main()
