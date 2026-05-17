"""Recompute price + delivery_charge on every non-legacy PlanTemplate row.

Needed because:
  - Old rows stored a flat delivery (e.g. ₹10) instead of per-meal × meal_count.
  - The meal-count basis changed from Mon–Fri (5/10/20/40) to Mon–Sat (6/12/24/48).

New formula (matches subscriptions.py / payments.py / menu.py):
    meal_count        = MEAL_COUNT_MAP[(slot_combo, duration)]
    delivery_per_meal = tier.delivery_charge_weekly if duration == 'weekly'
                        else tier.delivery_charge_monthly
    delivery_charge   = round(delivery_per_meal * meal_count, 2)
    price             = round(price_per_meal * meal_count + delivery_charge, 2)

Idempotent: re-running yields the same numbers. Prints a before/after diff per row.

Run:
    python -m scripts.migrations.recompute_plan_pricing
"""
from app.database import SessionLocal
from app.models.menu import PlanTemplate
from app.models.meal_tier import MealTier
from app.routers.menu import MEAL_COUNT_MAP, _get_current_price


def run():
    db = SessionLocal()
    try:
        tiers = {t.id: t for t in db.query(MealTier).all()}
        plans = db.query(PlanTemplate).filter(PlanTemplate.is_legacy == False).all()  # noqa: E712

        updated = 0
        skipped = 0
        for p in plans:
            tier = tiers.get(p.tier_id)
            if not tier:
                print(f"  skip {p.id}: tier {p.tier_id} not found")
                skipped += 1
                continue

            key = (p.slot_combo, p.duration)
            if key not in MEAL_COUNT_MAP:
                print(f"  skip {p.id}: invalid slot_combo/duration {key}")
                skipped += 1
                continue

            meal_count = MEAL_COUNT_MAP[key]
            ppm = _get_current_price(str(p.tier_id), p.diet_type, db)
            if ppm <= 0:
                print(f"  skip {p.id}: no active pricing for tier={tier.slug} diet={p.diet_type}")
                skipped += 1
                continue

            delivery_per_meal = float(
                tier.delivery_charge_weekly if p.duration == "weekly"
                else tier.delivery_charge_monthly or 0
            )
            new_delivery = round(delivery_per_meal * meal_count, 2)
            new_price = round(ppm * meal_count + new_delivery, 2)

            old_price = float(p.price) if p.price is not None else None
            old_delivery = float(p.delivery_charge) if p.delivery_charge is not None else None
            old_meal_count = p.meal_count

            changed = (
                old_price != new_price
                or old_delivery != new_delivery
                or old_meal_count != meal_count
            )
            if not changed:
                continue

            print(
                f"  {tier.slug:14} {p.diet_type:8} {p.slot_combo:16} {p.duration:8} "
                f"meals {old_meal_count}->{meal_count}  "
                f"delivery ₹{old_delivery}->₹{new_delivery}  "
                f"price ₹{old_price}->₹{new_price}"
            )
            p.meal_count = meal_count
            p.total_meals = meal_count
            p.delivery_charge = new_delivery
            p.price = new_price
            updated += 1

        db.commit()
        print(f"OK - {updated} plan(s) updated, {skipped} skipped (of {len(plans)} total).")
    finally:
        db.close()


if __name__ == "__main__":
    run()
