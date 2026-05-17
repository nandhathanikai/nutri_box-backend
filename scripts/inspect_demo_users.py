"""One-shot read-only check: do users 8 & 10 exist, and what tiers/subs are around?"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date
from app.database import SessionLocal
# Import all models so SQLAlchemy can resolve relationships.
from app.models.user import User
from app.models.subscription import Subscription
from app.models.meal_tier import MealTier
from app.models.menu import PlanTemplate, TierPricing, WeeklyMenuImage  # noqa: F401
from app.models.credit import Credit, DeliveryCancellation  # noqa: F401

db = SessionLocal()
try:
    for uid in (8, 10):
        u = db.query(User).filter(User.id == uid).first()
        print(f"\n=== user_id={uid} ===")
        if not u:
            print("  NOT FOUND")
            continue
        print(f"  name={u.full_name!r}  email={u.email!r}")
        subs = (
            db.query(Subscription)
            .filter(Subscription.customer_id == uid)
            .order_by(Subscription.end_date.desc().nullslast())
            .all()
        )
        for s in subs:
            print(f"  sub id={s.id} menu_id={s.menu_id} {s.start_date}..{s.end_date}")

    print("\n=== active tiers (display_order asc) ===")
    tiers = (
        db.query(MealTier)
        .filter(MealTier.is_active == True)
        .order_by(MealTier.display_order.asc())
        .all()
    )
    today = date.today()
    for t in tiers:
        prices = (
            db.query(TierPricing)
            .filter(
                TierPricing.tier_id == t.id,
                TierPricing.is_active == True,
                TierPricing.effective_from <= today,
            )
            .order_by(TierPricing.effective_from.desc())
            .all()
        )
        latest_per_diet = {}
        for p in prices:
            if p.diet_type not in latest_per_diet:
                latest_per_diet[p.diet_type] = float(p.price_per_meal)
        print(
            f"  tier={t.name!r} slug={t.slug!r} diet_support={t.diet_support} "
            f"dlv_w={t.delivery_charge_weekly} dlv_m={t.delivery_charge_monthly} "
            f"prices={latest_per_diet}"
        )

    print("\n=== existing PlanTemplates (non-legacy, active) ===")
    plans = (
        db.query(PlanTemplate)
        .filter(PlanTemplate.is_active == True, PlanTemplate.is_legacy == False)
        .all()
    )
    for p in plans:
        print(
            f"  plan id={p.id} tier_id={p.tier_id} diet={p.diet_type} "
            f"slot={p.slot_combo} dur={p.duration} meals={p.meal_count} price={p.price}"
        )
finally:
    db.close()
