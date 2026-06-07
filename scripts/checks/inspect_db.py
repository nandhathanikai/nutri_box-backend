import app.models.user
import app.models.subscription
import app.models.menu
import app.models.credit
import app.models.settings
import app.models.marketing
import app.models.audit_log
import app.models.delivery
from app.database import SessionLocal
from app.models.user import User
from app.models.subscription import Subscription
from sqlalchemy import text

db = SessionLocal()

# ── Customer ──────────────────────────────────────────────────────
u = db.query(User).filter(User.email == 'nandhagopalt@gmail.com').first()
if not u:
    print('USER NOT FOUND'); db.close(); exit(1)
print(f'User: id={u.id}  name={u.full_name}  role={u.role}')

subs = db.query(Subscription).filter(Subscription.customer_id == u.id).all()
for s in subs:
    print(f'  Sub: id={s.id}  menu_id={s.menu_id}  '
          f'start={s.start_date}  end={s.end_date}')

# ── Meal tiers ─────────────────────────────────────────────────────
tiers = db.execute(text('SELECT id, name FROM meal_tiers LIMIT 10')).fetchall()
print('Tiers:', list(tiers))

# ── Delivery sessions ─────────────────────────────────────────────
sessions = db.execute(text(
    'SELECT id, name, slug FROM delivery_sessions ORDER BY display_order'
)).fetchall()
print('Sessions:', list(sessions))

# ── All tables ────────────────────────────────────────────────────
tables = db.execute(text(
    "SELECT table_name FROM information_schema.tables "
    "WHERE table_catalog = 'defaultdb' AND table_schema = 'public'"
)).fetchall()
print('Tables:', sorted([r[0] for r in tables]))

db.close()
