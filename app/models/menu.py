from sqlalchemy import Column, Integer, String, Boolean, Text, Numeric, Date, ForeignKey, DateTime, CheckConstraint, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from sqlalchemy.sql import func
from app.database import Base
import uuid
from datetime import date


class PlanTemplate(Base):
    __tablename__ = "plan_templates"
    __table_args__ = (
        CheckConstraint("slot_combo IN ('breakfast_only', 'dinner_only', 'both')", name="ck_plan_templates_slot_combo"),
        CheckConstraint("duration IN ('weekly', 'monthly')", name="ck_plan_templates_duration"),
        {'extend_existing': True},
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(Text, nullable=True, default="")
    tier_id = Column(UUID(as_uuid=True), ForeignKey("meal_tiers.id"), nullable=False)
    diet_type = Column(Text, nullable=False, default="both")
    duration = Column(Text, nullable=True)
    meal_slots = Column(ARRAY(Text), nullable=True)
    meals_per_slot = Column(Integer, nullable=True)
    total_meals = Column(Integer, nullable=True)
    price = Column(Numeric(8, 2), nullable=True)
    delivery_charge = Column(Numeric(6, 2), nullable=True)
    is_active = Column(Boolean, default=True)
    slot_combo = Column(Text, nullable=True)
    meal_count = Column(Integer, nullable=True)
    is_legacy = Column(Boolean, default=False)


class TierPricing(Base):
    __tablename__ = "tier_pricing"
    __table_args__ = (
        CheckConstraint("diet_type IN ('veg', 'nonveg')", name="ck_tier_pricing_diet_type"),
        UniqueConstraint('tier_id', 'diet_type', 'effective_from', name='uq_tier_pricing_tier_diet_date'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tier_id = Column(UUID(as_uuid=True), ForeignKey("meal_tiers.id", ondelete="CASCADE"), nullable=False)
    diet_type = Column(Text, nullable=False)
    price_per_meal = Column(Numeric(8, 2), nullable=False)
    is_active = Column(Boolean, default=True)
    effective_from = Column(Date, nullable=False, default=date.today)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WeeklyMenuImage(Base):
    __tablename__ = "weekly_menu_images"
    __table_args__ = (
        CheckConstraint("diet_type IN ('veg', 'nonveg', 'both')", name="ck_weekly_menu_images_diet_type"),
        UniqueConstraint('tier_id', 'diet_type', 'week_start_date', name='uq_weekly_menu_images_tier_diet_date'),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tier_id = Column(UUID(as_uuid=True), ForeignKey("meal_tiers.id", ondelete="CASCADE"), nullable=False)
    diet_type = Column(Text, nullable=False)
    week_start_date = Column(Date, nullable=False)
    image_url = Column(Text, nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now())
