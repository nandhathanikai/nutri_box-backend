from sqlalchemy import Column, Integer, String, Text, Boolean, Float
from app.database import Base

class AppSettings(Base):
    """Singleton table — only one row ever exists (id=1).
    Stores ALL application-wide settings: contact info, operational hours,
    notification toggles, payment config, credit rules."""
    __tablename__ = "app_settings"

    id = Column(Integer, primary_key=True, index=True)

    # ── Contact / Footer Info ──────────────────────────────────────────────
    business_name     = Column(String, nullable=True, default="Nutribox Kitchen")
    address           = Column(Text, nullable=True)
    phone_number      = Column(String, nullable=True)
    email             = Column(String, nullable=True)
    city              = Column(String, nullable=True, default="Chennai")
    instagram_link    = Column(String, nullable=True)

    # ── Operating Hours ────────────────────────────────────────────────────
    opens_at          = Column(String, nullable=True, default="08:00")
    closes_at         = Column(String, nullable=True, default="22:00")
    timezone          = Column(String, nullable=True, default="IST")

    # ── Admin Notifications ────────────────────────────────────────────────
    notif_new_order        = Column(Boolean, default=True)
    notif_credit_earned    = Column(Boolean, default=True)
    notif_payment_fail     = Column(Boolean, default=True)
    notif_new_customer     = Column(Boolean, default=False)

    # ── Customer Notifications ─────────────────────────────────────────────
    notif_cust_credit      = Column(Boolean, default=True)
    notif_cust_reminder    = Column(Boolean, default=True)
    notif_cust_order_sms   = Column(Boolean, default=True)
    notif_cust_delivery    = Column(Boolean, default=True)

    # ── Payment ────────────────────────────────────────────────────────────
    payment_gateway        = Column(String, nullable=True, default="Razorpay")
    payment_api_key        = Column(String, nullable=True)
    payment_api_secret     = Column(String, nullable=True)
    payment_cod_enabled    = Column(Boolean, default=True)
    payment_upi_enabled    = Column(Boolean, default=True)
    gst_rate               = Column(Float, default=5.0)
    gstin                  = Column(String, nullable=True)

    # ── Credit Rules ──────────────────────────────────────────────────────
    credit_cutoff_hours    = Column(Integer, default=6)
    credit_delivery_delay  = Column(Integer, default=1)
    credit_max_per_plan    = Column(Integer, default=0)   # 0 = unlimited
    credit_deliver_no_renew = Column(Boolean, default=True)
    credit_of_credit       = Column(Boolean, default=False)
