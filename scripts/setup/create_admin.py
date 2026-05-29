"""
Utility script: create or reset the admin user in the Nutribox DB.
Run with: venv\Scripts\python.exe create_admin.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from app.database import SessionLocal
from app.models.user import User
from app.models.credit import DeliveryCancellation, Credit
from app.models.subscription import Subscription
from app.models.custom_request import CustomPlanRequest
from app.models.marketing import Offer, Announcement
from app.models.meal_tier import MealTier
from app.models.menu import PlanTemplate, TierPricing, WeeklyMenuImage
from app.models.settings import AppSettings
from app.models.audit_log import AuditLog
from app.utils.security import get_password_hash

db = SessionLocal()

# Show all existing users
users = db.query(User).all()
print(f"\n=== Existing users ({len(users)}) ===")
for u in users:
    print(f"  id={u.id}  email={u.email}  role={u.role}  name={u.full_name}")

# Create / update admin user
ADMIN_EMAIL = "admin@nutribox.com"
ADMIN_PASSWORD = "Admin@123"

admin = db.query(User).filter(User.email == ADMIN_EMAIL).first()
if admin:
    print(f"\nAdmin user found (id={admin.id}). Resetting password to: {ADMIN_PASSWORD}")
    admin.hashed_password = get_password_hash(ADMIN_PASSWORD)
    admin.role = "admin"
    db.commit()
    print("Password updated.")
else:
    print(f"\nNo admin user found. Creating new admin: {ADMIN_EMAIL} / {ADMIN_PASSWORD}")
    new_admin = User(
        full_name="Admin",
        email=ADMIN_EMAIL,
        phone="9999999999",
        hashed_password=get_password_hash(ADMIN_PASSWORD),
        role="admin"
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)
    print(f"Admin created with id={new_admin.id}")

db.close()
print("\nDone. You can now log in with:")
print(f"  Email:    {ADMIN_EMAIL}")
print(f"  Password: {ADMIN_PASSWORD}")
