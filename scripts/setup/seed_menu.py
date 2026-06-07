"""
Seeds:
  1. Delivery sessions (Breakfast, Lunch, Dinner) — already done, skip if present
  2. A test active subscription for nandhagopalt@gmail.com (this week)

Run from backend/:  venv\Scripts\python seed_menu.py
"""
import app.models.credit
import app.models.delivery

from app.database import SessionLocal
from sqlalchemy import text
from datetime import date, timedelta

db = SessionLocal()

# ── 1. Delivery sessions ──────────────────────────────────────────
existing = db.execute(text('SELECT COUNT(*) FROM delivery_sessions')).scalar()
if existing == 0:
    db.execute(text("""
        INSERT INTO delivery_sessions (name, slug, display_order, is_active)
        VALUES
            ('Breakfast', 'breakfast', 1, true),
            ('Lunch',     'lunch',     2, true),
            ('Dinner',    'dinner',    3, true)
        ON CONFLICT (slug) DO NOTHING
    """))
    db.commit()
    print('Seeded delivery sessions.')
else:
    print(f'Sessions already present ({existing})')

sessions = db.execute(text('SELECT id, name FROM delivery_sessions ORDER BY display_order')).fetchall()
print('Sessions:', [(r[0], r[1]) for r in sessions])

# ── 2. Customer ───────────────────────────────────────────────────
user = db.execute(text(
    "SELECT id, full_name, latitude, longitude FROM users WHERE email = 'nandhagopalt@gmail.com'"
)).fetchone()
if not user:
    print('USER NOT FOUND'); db.close(); exit(1)

customer_id, full_name, lat, lng = user
print(f'\nCustomer: id={customer_id}  name={full_name}  lat={lat}  lng={lng}')

# ── 3. Pick a plan template ───────────────────────────────────────
plan = db.execute(text('SELECT id FROM plan_templates LIMIT 1')).fetchone()
plan_id = str(plan[0]) if plan else None
print(f'Plan template: {plan_id}')

# ── 4. Create subscription via raw SQL ────────────────────────────
today = date.today()
end_of_week = today + timedelta(days=6)

existing_sub = db.execute(text(
    f"SELECT id FROM subscriptions WHERE customer_id = {customer_id} AND end_date >= '{today}'"
)).fetchone()

if existing_sub:
    print(f'Subscription already active: id={existing_sub[0]}')
else:
    db.execute(text(f"""
        INSERT INTO subscriptions (customer_id, menu_id, start_date, end_date, price_per_meal_snapshot)
        VALUES (
            {customer_id},
            '{plan_id}',
            '{today}',
            '{end_of_week}',
            150.00
        )
    """))
    db.commit()
    new_sub = db.execute(text(
        f"SELECT id, start_date, end_date FROM subscriptions "
        f"WHERE customer_id = {customer_id} AND end_date >= '{today}' LIMIT 1"
    )).fetchone()
    print(f'Created subscription: id={new_sub[0]}  {new_sub[1]} -> {new_sub[2]}')

# ── 5. Verify: should appear in today's orders ────────────────────
check = db.execute(text(f"""
    SELECT s.id, u.full_name, u.email, s.start_date, s.end_date
    FROM subscriptions s
    JOIN users u ON u.id = s.customer_id
    WHERE s.start_date <= '{today}'
      AND s.end_date >= '{today}'
      AND u.id = {customer_id}
""")).fetchall()

print(f'\nActive subscriptions today for {full_name}: {len(check)}')
for row in check:
    print(f'  sub_id={row[0]}  {row[1]} ({row[2]})  {row[3]} → {row[4]}')

# ── 6. Customer lat/lng — needed for map routing ──────────────────
if not lat:
    print('\n⚠️  Customer has no GPS coordinates — updating with Chennai coords for testing...')
    db.execute(text(f"""
        UPDATE users SET latitude = 13.0827, longitude = 80.2707
        WHERE id = {customer_id}
    """))
    db.commit()
    print('   Set to Chennai central: 13.0827, 80.2707')

print('\n✅ Setup complete!')
print(f'   Go to Admin → Today\'s Orders to see {full_name}\'s orders')
print(f'   Then assign to a driver and test the flow')

db.close()
