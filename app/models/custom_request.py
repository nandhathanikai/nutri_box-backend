from sqlalchemy import Column, Integer, BigInteger, String, Text, Numeric, ForeignKey, DateTime, CheckConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class CustomPlanRequest(Base):
    __tablename__ = "custom_plan_requests"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    customer_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Baseline choices
    base_tier_id = Column(UUID(as_uuid=True), ForeignKey("meal_tiers.id"), nullable=True)
    diet_type = Column(Text, nullable=False)
    slot_combo = Column(Text, nullable=False)
    duration = Column(Text, nullable=False)
    
    # The actual request text
    custom_requirements = Column(Text, nullable=False)
    
    # Status and Pricing
    status = Column(Text, default="pending", nullable=False)
    quoted_price_per_meal = Column(Numeric(8, 2), nullable=True)
    quoted_delivery_charge = Column(Numeric(6, 2), nullable=True)
    admin_note = Column(Text, nullable=True)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        CheckConstraint("status IN ('pending', 'priced', 'accepted', 'rejected', 'paid')", name="ck_custom_requests_status"),
        CheckConstraint("slot_combo IN ('breakfast_only', 'dinner_only', 'both')", name="ck_custom_requests_slot_combo"),
        CheckConstraint("duration IN ('weekly', 'monthly')", name="ck_custom_requests_duration"),
        CheckConstraint("diet_type IN ('veg', 'nonveg', 'both')", name="ck_custom_requests_diet_type"),
    )
