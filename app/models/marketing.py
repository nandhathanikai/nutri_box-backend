from sqlalchemy import Column, Integer, String, Text, Date, DateTime, Boolean, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class Announcement(Base):
    """Admin-created announcements pushed to customers.
    Automatically expired/deleted after end_date by a background job."""
    __tablename__ = "announcements"

    id          = Column(Integer, primary_key=True, index=True)
    title       = Column(String(255), nullable=False)
    body        = Column(Text, nullable=False)
    icon        = Column(String(10), default="📢")   # emoji
    audience    = Column(String(50), default="All Customers")
    status      = Column(String(20), default="active")  # active | draft | expired
    start_date  = Column(Date, nullable=False)
    end_date    = Column(Date, nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())
    opens       = Column(Integer, default=0)       # % open rate (placeholder)

class Offer(Base):
    """Discount offers / coupon codes."""
    __tablename__ = "offers"

    id          = Column(Integer, primary_key=True, index=True)
    code        = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(String(255), nullable=False)
    type        = Column(String(10), nullable=False)   # pct | flat | free
    value       = Column(Integer, default=0)
    max_cap     = Column(Integer, nullable=True)        # max discount in ₹
    min_order   = Column(Integer, default=0)
    usage_limit = Column(Integer, nullable=True)        # null = unlimited
    used_count  = Column(Integer, default=0)
    valid_from  = Column(Date, nullable=False)
    valid_until = Column(Date, nullable=False)
    status      = Column(String(20), default="active")  # active | draft | expired
    # Audience targeting: all | new_user | existing_user
    audience    = Column(String(30), default="all", nullable=False)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

class GalleryImage(Base):
    """Showcase gallery images uploaded by admin for dashboard display."""
    __tablename__ = "gallery_images"

    id         = Column(Integer, primary_key=True, index=True)
    image_url  = Column(String(500), nullable=False)
    caption    = Column(String(255), nullable=True)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Review(Base):
    """Customer reviews about meals / brand."""
    __tablename__ = "reviews"

    id          = Column(Integer, primary_key=True, index=True)
    customer_id = Column(Integer, ForeignKey("users.id"), index=True)
    rating      = Column(Integer, nullable=False, default=5)   # 1-5 stars
    text        = Column(Text, nullable=False)
    status      = Column(String(20), default="approved", index=True)        # approved | pending | rejected
    created_at  = Column(DateTime(timezone=True), server_default=func.now(), index=True)

    # Relationship to get customer details (string to prevent circular imports)
    customer = relationship("User")

