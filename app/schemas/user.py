from pydantic import BaseModel, EmailStr
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    full_name: str
    email: EmailStr
    phone: Optional[str] = None
    address_line_1: Optional[str] = None   # drivers created by admin have no address
    address_line_2: Optional[str] = None
    landmark: Optional[str] = None
    location_link: Optional[str] = None
    role: Optional[str] = "customer"


class UserCreate(UserBase):
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserResponse(UserBase):
    id: int
    notif_delivery: Optional[bool] = True
    notif_subscriptions: Optional[bool] = True
    notif_offers: Optional[bool] = False
    email_verified: Optional[bool] = False
    is_active: Optional[bool] = True
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    # Account-state derivations populated by the /me endpoint, not stored on the model
    has_subscription: Optional[bool] = None
    days_until_auto_delete: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Fields a user can update on their own profile."""
    full_name: Optional[str] = None
    phone: Optional[str] = None
    address_line_1: Optional[str] = None
    address_line_2: Optional[str] = None
    landmark: Optional[str] = None
    location_link: Optional[str] = None
    # Customer can update their geocoded coordinates directly (from GPS or map link)
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class NotificationPrefsUpdate(BaseModel):
    notif_delivery: Optional[bool] = None
    notif_subscriptions: Optional[bool] = None
    notif_offers: Optional[bool] = None


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyOtpRequest(BaseModel):
    email: EmailStr
    otp: str


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    new_password: str


# JWT Token Schema
class Token(BaseModel):
    access_token: str
    token_type: str


