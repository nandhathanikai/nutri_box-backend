"""
Delivery Management Models
--------------------------
DeliverySession  — Admin-managed sessions (Breakfast, Lunch, Dinner, Snack, …)
DeliveryAssignment — Maps a (subscription, session, date) to a driver
DeliveryTracking   — GPS breadcrumb trail from driver during an active delivery
DriverStatus       — Current real-time status of a driver
"""
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Text,
    DateTime, Date, ForeignKey, UniqueConstraint
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class DeliverySession(Base):
    """Admin-managed named delivery sessions (e.g. Breakfast, Lunch, Dinner, Snack).
    Sessions are ordered by display_order so they appear consistently in UIs.
    New sessions added here automatically appear everywhere in the delivery flow.
    """
    __tablename__ = "delivery_sessions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(50), nullable=False, unique=True)        # Display name: "Breakfast"
    slug = Column(String(50), nullable=False, unique=True)        # Machine key: "breakfast"
    display_order = Column(Integer, default=0, nullable=False)    # Sort order in UI
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Reverse relationships
    assignments = relationship("DeliveryAssignment", back_populates="session_obj")


class DeliveryAssignment(Base):
    """Links one (subscription, date, session) to exactly one driver.
    One order can only be assigned to one driver — no reassignment.
    """
    __tablename__ = "delivery_assignments"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "delivery_date", "session_id",
            name="uq_assignment_sub_date_session"
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id", ondelete="SET NULL"), nullable=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    driver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id = Column(Integer, ForeignKey("delivery_sessions.id"), nullable=False, index=True)
    delivery_date = Column(Date, nullable=False, index=True)

    # Delivery lifecycle
    status = Column(
        String(20), default="assigned", nullable=False
    )  # assigned | on_the_way | delivered

    # Timestamps
    assigned_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    delivered_at = Column(DateTime(timezone=True), nullable=True)

    # Relationships
    session_obj = relationship("DeliverySession", back_populates="assignments")
    tracking_points = relationship("DeliveryTracking", back_populates="assignment", cascade="all, delete-orphan")


class DeliveryTracking(Base):
    """Individual GPS breadcrumb captured from the driver's device during an active delivery.
    Points are inserted every ~5 seconds while the driver has connectivity.
    The WebSocket manager broadcasts each point in real time — these rows serve as
    the persistent audit trail and the offline-sync buffer replay source.
    """
    __tablename__ = "delivery_tracking"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("delivery_assignments.id", ondelete="CASCADE"), nullable=False, index=True)
    driver_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    recorded_at = Column(DateTime(timezone=True), nullable=False)   # Device-side timestamp
    synced_at = Column(DateTime(timezone=True), server_default=func.now())  # Server receipt time

    # Relationship
    assignment = relationship("DeliveryAssignment", back_populates="tracking_points")


class DriverStatus(Base):
    """One row per driver — upserted on every status change.
    Tracks real-time availability for the admin monitoring view.
    """
    __tablename__ = "driver_status"

    driver_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    status = Column(
        String(20), default="offline", nullable=False
    )  # available | on_delivery | offline
    current_session_id = Column(Integer, ForeignKey("delivery_sessions.id"), nullable=True)
    current_assignment_id = Column(Integer, ForeignKey("delivery_assignments.id", ondelete="SET NULL"), nullable=True)
    last_latitude = Column(Float, nullable=True)
    last_longitude = Column(Float, nullable=True)
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
