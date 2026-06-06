import sys
import os
sys.path.append(os.path.abspath('.'))

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal
from app.models.subscription import Subscription
from app.models.menu import PlanTemplate
from datetime import date, timedelta

# Import other models to register them in SQLAlchemy
from app.models.user import User
from app.models.credit import DeliveryCancellation, Credit
from app.models.custom_request import CustomPlanRequest
from app.models.marketing import Offer, Announcement
from app.models.meal_tier import MealTier
from app.models.settings import AppSettings
from app.models.audit_log import AuditLog

db = SessionLocal()
try:
    # Get first plan template
    plan = db.query(PlanTemplate).first()
    if not plan:
        print("No plan templates found!")
        sys.exit(1)
        
    print(f"Using plan template: ID={plan.id} | Tier ID={plan.tier_id} | Price={plan.price}")
    
    # Create active subscription for testcustomer@nutribox.com (User ID: 1179615965357277185)
    sub = Subscription(
        customer_id=1179615965357277185,
        menu_id=plan.id,
        razorpay_payment_id="pay_dummy_123456",
        razorpay_order_id="order_dummy_123456",
        start_date=date.today(),
        end_date=date.today() + timedelta(days=30)
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    print(f"Successfully added dummy subscription: Sub ID={sub.id} for user testcustomer@nutribox.com")
finally:
    db.close()
