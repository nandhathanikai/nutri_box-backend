from sqlalchemy import Column, Integer, String, Boolean, Date, DateTime, ForeignKey, Text
from sqlalchemy.orm import relationship
from app.database import Base
from datetime import datetime

class DeliveryCancellation(Base):
    __tablename__ = "delivery_cancellations"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subscription_id = Column(Integer, ForeignKey("subscriptions.id"), nullable=False)
    delivery_date   = Column(Date, nullable=False)
    session         = Column(String(50), nullable=False)
    cancelled_at    = Column(DateTime, nullable=False)
    cutoff_deadline = Column(DateTime, nullable=False)
    is_eligible     = Column(Boolean, default=False, nullable=False)
    credit_id       = Column(Integer, ForeignKey("credits.id"), nullable=True)
    created_at      = Column(DateTime, default=datetime.utcnow)

    user         = relationship("User", back_populates="cancellations")
    credit       = relationship("Credit", foreign_keys=[credit_id], post_update=True)


class Credit(Base):
    __tablename__ = "credits"

    id                    = Column(Integer, primary_key=True, index=True)
    user_id               = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    subscription_id       = Column(Integer, ForeignKey("subscriptions.id"), nullable=True)
    cancellation_id       = Column(Integer, ForeignKey("delivery_cancellations.id"), nullable=True)

    # Session & date info
    session               = Column(String(50), nullable=False)          # BF, LUNCH, DINNER, SNACK
    original_delivery_date = Column(Date, nullable=False)               # Date customer originally cancelled
    delivery_on           = Column(Date, nullable=True)                 # Scheduled bonus delivery date (assigned after plan ends)

    # Credit metadata
    credit_days           = Column(Integer, default=1, nullable=False)
    status                = Column(String(20), default="pending", nullable=False)  # pending, scheduled, delivered, not_eligible
    plan_end_date         = Column(Date, nullable=True)                 # When the source plan ends
    is_manual             = Column(Boolean, default=False, nullable=False)
    notes                 = Column(Text, nullable=True)

    # Timestamps
    created_at            = Column(DateTime, default=datetime.utcnow)
    updated_at            = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    user               = relationship("User", back_populates="credits")
    cancellation_assoc = relationship("DeliveryCancellation", foreign_keys=[cancellation_id])
