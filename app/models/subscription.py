from sqlalchemy import Column, Integer, BigInteger, String, Date, ForeignKey, Numeric
from sqlalchemy.dialects.postgresql import UUID
from app.database import Base

class Subscription(Base):
    __tablename__ = "subscriptions"

    id = Column(BigInteger, primary_key=True, index=True, autoincrement=True)
    customer_id = Column(BigInteger, ForeignKey("users.id"), index=True)
    menu_id = Column(UUID(as_uuid=True), ForeignKey("plan_templates.id"), index=True)
    start_date = Column(Date, index=True)
    end_date = Column(Date, index=True)
    price_per_meal_snapshot = Column(Numeric(8, 2), nullable=True) # For price history
    customization_details = Column(String, nullable=True)
    diet_type             = Column(String, nullable=True)
    slot_combo            = Column(String, nullable=True)

    # Razorpay payment references (nullable for legacy/manually-created subs).
    # order_id is UNIQUE — same Razorpay order can only ever back one subscription,
    # which is the idempotency guarantee for /verify and /webhook.
    razorpay_order_id   = Column(String, nullable=True, unique=True, index=True)
    razorpay_payment_id = Column(String, nullable=True, index=True)
