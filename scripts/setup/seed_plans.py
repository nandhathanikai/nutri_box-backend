"""
Seed script: Creates the 3 meal tiers and 12 plan templates for Nutribox.
Run with: venv\Scripts\python.exe seed_plans.py
"""
import sys, os, requests, json

BASE = "http://localhost:8000/api/menu"

# ─── Step 1: Create tiers ────────────────────────────────────────────────────
TIERS = [
    {"name": "Classic",  "price_per_meal": 95.0,  "diet_type": "both", "weekly_delivery_charge": 10.0, "monthly_delivery_charge": 0.0, "description": "Budget-friendly daily meals — ₹95/meal"},
    {"name": "Standard", "price_per_meal": 115.0, "diet_type": "both", "weekly_delivery_charge": 10.0, "monthly_delivery_charge": 0.0, "description": "Well-balanced nutrition — ₹115/meal"},
    {"name": "Premium",  "price_per_meal": 140.0, "diet_type": "both", "weekly_delivery_charge": 10.0, "monthly_delivery_charge": 0.0, "description": "Chef-curated premium meals — ₹140/meal"},
]

print("=== Creating Tiers ===")
tier_ids = {}
for t in TIERS:
    r = requests.post(f"{BASE}/tiers", json=t)
    if r.ok:
        data = r.json()
        tier_ids[t["name"]] = data["id"]
        print(f"  [OK] {t['name']} tier -> id={data['id']}")
    else:
        print(f"  [ERR] {t['name']}: {r.text}")
        sys.exit(1)

# ─── Step 2: Create 12 plan templates ────────────────────────────────────────
# Formula:
#   price          = total_meals × price_per_meal
#   delivery_charge = total_meals × weekly_delivery (₹10) for weekly  | 0 for monthly
#
# Plans per tier:
#   1. Weekly  | 1 slot  (B or D) | 6 meals
#   2. Weekly  | 2 slots (B + D)  | 12 meals
#   3. Monthly | 1 slot  (B or D) | 24 meals (free delivery)
#   4. Monthly | 2 slots (B + D)  | 48 meals (free delivery)

PLAN_DEFS = [
    # duration   meal_slots                          meals_per_slot  total  delivery_per_meal
    ("weekly",  ["breakfast", "dinner"],             6,              6,     10.0),  # 1-slot weekly
    ("weekly",  ["breakfast", "dinner"],             6,              12,    10.0),  # 2-slot weekly
    ("monthly", ["breakfast", "dinner"],             24,             24,    0.0),   # 1-slot monthly
    ("monthly", ["breakfast", "dinner"],             24,             48,    0.0),   # 2-slot monthly
]

# Correct total_meals:
PLAN_DEFS = [
    ("weekly",  ["breakfast", "dinner"], 6,  6,  10.0),   # single-slot weekly  (customer picks 1)
    ("weekly",  ["breakfast", "dinner"], 6,  12, 10.0),   # dual-slot weekly
    ("monthly", ["breakfast", "dinner"], 24, 24, 0.0),    # single-slot monthly
    ("monthly", ["breakfast", "dinner"], 24, 48, 0.0),    # dual-slot monthly
]

ppm = {"Classic": 95.0, "Standard": 115.0, "Premium": 140.0}

print("\n=== Creating Plan Templates ===")
for tier_name, tier_id in tier_ids.items():
    for (duration, slots, meals_per_slot, total_meals, del_per_meal) in PLAN_DEFS:
        price            = round(total_meals * ppm[tier_name], 2)
        delivery_charge  = round(total_meals * del_per_meal, 2)
        slot_label = "1-slot" if total_meals in [6, 24] else "2-slot"

        plan = {
            "tier_id":        tier_id,
            "duration":       duration,
            "meal_slots":     slots,
            "meals_per_slot": meals_per_slot,
            "total_meals":    total_meals,
            "price":          price,
            "delivery_charge": delivery_charge,
            "is_active":      True
        }
        r = requests.post(f"{BASE}/plan-templates", json=plan)
        if r.ok:
            print(f"  [OK] {tier_name} | {duration} | {slot_label} | {total_meals} meals | INR {price} + INR {delivery_charge} delivery")
        else:
            print(f"  [ERR] {tier_name}/{duration}/{slot_label}: {r.text}")

print("\nAll done! Refresh the Admin → Menu Management → Plan Templates tab.")
