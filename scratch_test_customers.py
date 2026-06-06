import sys
import os
sys.path.append(os.path.abspath('.'))

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal
from app.routers.admin import get_customers

# Import all models to satisfy SQLAlchemy registry
from app.models.user import User
from app.models.credit import DeliveryCancellation, Credit
from app.models.subscription import Subscription
from app.models.custom_request import CustomPlanRequest
from app.models.marketing import Offer, Announcement
from app.models.meal_tier import MealTier
from app.models.menu import PlanTemplate, TierPricing, WeeklyMenuImage
from app.models.settings import AppSettings
from app.models.audit_log import AuditLog

db = SessionLocal()
try:
    print("Invoking get_customers...")
    res = get_customers(page=1, limit=50, search=None, db=db)
    print("Success! Return structure total:", res["total"])
    print("Data sample size:", len(res["data"]))
except Exception as e:
    import traceback
    print("\n--- ERROR DETECTED ---")
    traceback.print_exc()
finally:
    db.close()
