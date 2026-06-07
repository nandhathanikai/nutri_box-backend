import app.models.credit, app.models.delivery
from app.database import SessionLocal
from sqlalchemy import text

db = SessionLocal()

# Check drivers
drivers = db.execute(text("SELECT id, full_name, email, role, is_active FROM users WHERE role = 'driver'")).fetchall()
print("DRIVERS:")
for d in drivers:
    print(f"  id={d[0]}  name={d[1]}  email={d[2]}  role={d[3]}  active={d[4]}")

# Check plan templates slot_combo
plans = db.execute(text("SELECT id, name, slot_combo FROM plan_templates LIMIT 5")).fetchall()
print("\nPLAN TEMPLATES (slot_combo):")
for p in plans:
    print(f"  id={p[0]}  name={p[1]}  slot_combo={p[2]}")

# Check the subscription's plan
sub = db.execute(text("SELECT id, menu_id FROM subscriptions WHERE customer_id = (SELECT id FROM users WHERE email='nandhagopalt@gmail.com') LIMIT 1")).fetchone()
print(f"\nCustomer subscription: sub_id={sub[0]}  menu_id={sub[1]}")

if sub[1]:
    plan = db.execute(text(f"SELECT id, name, slot_combo FROM plan_templates WHERE id = '{sub[1]}'")).fetchone()
    print(f"  Plan: name={plan[1]}  slot_combo={plan[2]}")

db.close()
