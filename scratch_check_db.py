import sys
import os
sys.path.append(os.path.abspath('.'))

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal
from app.models.user import User
from app.models.subscription import Subscription
from app.models.credit import DeliveryCancellation, Credit
from app.models.menu import PlanTemplate
from app.models.meal_tier import MealTier

db = SessionLocal()
try:
    print("--- ALL USERS ---")
    users = db.query(User).all()
    for u in users:
        print(f"ID: {u.id} | Email: {u.email} | Name: {u.full_name} | Role: {u.role}")

    print("\n--- ALL SUBSCRIPTIONS ---")
    subs = db.query(Subscription).all()
    for s in subs:
        print(f"Sub ID: {s.id} | Customer ID: {s.customer_id} | Start: {s.start_date} | End: {s.end_date}")
finally:
    db.close()
