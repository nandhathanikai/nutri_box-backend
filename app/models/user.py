from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    phone = Column(String)

    # Address details
    address_line_1 = Column(String)
    address_line_2 = Column(String, nullable=True)
    landmark = Column(String, nullable=True)
    location_link = Column(String, nullable=True)

    # Geocoded coordinates (populated from address or GPS or map link)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Account state — used to activate/deactivate drivers
    is_active = Column(Boolean, default=True, nullable=False)

    # Auth
    hashed_password = Column(String, nullable=False)
    role = Column(String, default="customer")
    reset_otp = Column(String(6), nullable=True)
    reset_otp_expires = Column(DateTime(timezone=True), nullable=True)

    # Email verification
    email_verified            = Column(Boolean, default=False, nullable=False)
    email_verification_token  = Column(String, nullable=True, index=True)

    # Notification preferences
    notif_delivery      = Column(Boolean, default=True,  nullable=False)
    notif_subscriptions = Column(Boolean, default=True,  nullable=False)
    notif_offers        = Column(Boolean, default=False, nullable=False)

    # Account lifecycle
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    cancellations = relationship("DeliveryCancellation", back_populates="user", cascade="all, delete-orphan")
    credits = relationship("Credit", back_populates="user", cascade="all, delete-orphan")

