from sqlalchemy import Column, Integer, String, Float, Boolean, Text, Numeric, Date, ForeignKey, CheckConstraint, DateTime, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.sql import func
import uuid
from app.database import Base

class MealTier(Base):
    __tablename__ = "meal_tiers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=False)
    slug = Column(Text, unique=True, nullable=True) # Will be unique once seeded
    display_order = Column(Integer, default=0)
    diet_support = Column(Text, default="both")  # 'veg_only' | 'nonveg_only' | 'both'
    delivery_charge_weekly = Column(Numeric(8, 2), default=10.00)
    delivery_charge_monthly = Column(Numeric(8, 2), default=0.00)
    is_active = Column(Boolean, default=True)
    is_featured = Column(Boolean, default=False, nullable=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # Keep old columns for backward compatibility during migration
    price_per_meal = Column(Numeric(8, 2), nullable=True)
    diet_type = Column(Text, nullable=True)
    weekly_delivery_charge = Column(Numeric(6, 2), nullable=True)
    monthly_delivery_charge = Column(Numeric(6, 2), nullable=True)
    description = Column(Text, nullable=True)

    __table_args__ = (
        CheckConstraint("diet_support IN ('veg_only', 'nonveg_only', 'both')", name="ck_meal_tiers_diet_support"),
    )
