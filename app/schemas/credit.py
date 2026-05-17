from pydantic import BaseModel
from datetime import date, datetime
from typing import Optional, List
from enum import Enum

class CreditStatus(str, Enum):
    pending      = "pending"
    scheduled    = "scheduled"
    delivered    = "delivered"
    not_eligible = "not_eligible"

# ── Customer-side requests ────────────────────────────────────────────────────

class CancelDeliveryRequest(BaseModel):
    session: str
    reason: Optional[str] = None

class CancelDeliveryResponse(BaseModel):
    eligible: bool
    message: str
    credit_id: Optional[int] = None

# ── Admin requests ────────────────────────────────────────────────────────────

class ManualCreditRequest(BaseModel):
    customer_id: int
    session: str              # BF, LUNCH, DINNER, SNACK
    delivery_on: date
    note: Optional[str] = None

# ── Response models ───────────────────────────────────────────────────────────

class CreditOut(BaseModel):
    id: int
    session: str
    original_delivery_date: date
    delivery_on: Optional[date] = None
    credit_days: int
    status: str
    plan_end_date: Optional[date] = None
    is_manual: bool = False
    notes: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class CreditBalanceSummary(BaseModel):
    pending: int
    scheduled: int
    delivered: int

class MyCreditsResponse(BaseModel):
    balance: CreditBalanceSummary
    credits: List[CreditOut]

# ── Admin response models ────────────────────────────────────────────────────

class AdminCreditOut(BaseModel):
    id: int
    customer_name: str
    customer_id: int
    customer_email: Optional[str] = None
    session: str
    original_delivery_date: date
    delivery_on: Optional[date] = None
    cancelled_at: Optional[datetime] = None
    credit_days: int
    plan_end_date: Optional[date] = None
    plan_name: Optional[str] = None
    plan_start: Optional[date] = None
    plan_end: Optional[date] = None
    status: str
    is_manual: bool = False
    notes: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class OverviewCustomer(BaseModel):
    customer_id: int
    customer_name: str
    customer_email: str
    plan_name: Optional[str] = None
    plan_start: Optional[date] = None
    plan_end: Optional[date] = None
    plan_status: Optional[str] = None
    pending_count: int = 0
    scheduled_count: int = 0
    delivered_count: int = 0
    credits: List[AdminCreditOut] = []

class StatsResponse(BaseModel):
    pending: int
    scheduled: int
    delivered: int
    total: int
