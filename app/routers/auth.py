import logging
import os
import re
import secrets as py_secrets
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm, OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from datetime import datetime, timezone, timedelta
import hmac
import random
import string
from typing import Optional
from app.database import get_db
from app.models.user import User
from app.models.subscription import Subscription
from app.jobs.credit_jobs import INACTIVE_ACCOUNT_GRACE_DAYS
from app.schemas.user import (
    UserCreate, UserLogin, UserResponse, Token,
    UserUpdate, NotificationPrefsUpdate, PasswordChangeRequest,
    ForgotPasswordRequest, VerifyOtpRequest, ResetPasswordRequest
)
from app.utils.security import get_password_hash, verify_password, create_access_token, SECRET_KEY, ALGORITHM
from app.utils.rate_limit import rate_limit
from app.utils.email import send_reset_password_email, send_verification_email

logger = logging.getLogger(__name__)


# Frontend base URL used when constructing email-verification links.
# Falls back to the first configured CORS origin in dev.
def _frontend_origin() -> str:
    explicit = os.getenv("FRONTEND_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    extra = os.getenv("FRONTEND_ORIGINS", "")
    first = next((o.strip() for o in extra.split(",") if o.strip()), "")
    return (first or "http://localhost:4200").rstrip("/")


PASSWORD_MIN_LEN = 8
_PWD_RULE_MSG = (
    "Password must be at least 8 characters and include an uppercase letter, "
    "a lowercase letter, and a number."
)


def validate_password_strength(pwd: str) -> None:
    """Raise 400 if `pwd` fails the project's password policy.

    Policy: ≥8 chars, has uppercase, lowercase, digit. Special chars optional.
    Centralised so /signup, /change-password, /reset-password all agree.
    """
    if (
        len(pwd) < PASSWORD_MIN_LEN
        or not re.search(r"[A-Z]", pwd)
        or not re.search(r"[a-z]", pwd)
        or not re.search(r"\d", pwd)
    ):
        raise HTTPException(status_code=400, detail=_PWD_RULE_MSG)

router = APIRouter(tags=["Authentication"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.id == int(user_id)).first()
    if user is None:
        raise credentials_exception
    return user


def require_admin(user: User = Depends(get_current_user)) -> User:
    """Dependency that 403s anyone whose role is not admin."""
    if not user.role or user.role.lower() != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user

_check_email_limit = rate_limit(max_calls=10, period_seconds=60, scope="check_email")


@router.get("/check-email", dependencies=[Depends(_check_email_limit)])
def check_email(email: str, db: Session = Depends(get_db)):
    """Check if an email is already registered. Returns 400 if it is."""
    db_user = db.query(User).filter(User.email == email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")
    return {"message": "Email is available"}


_signup_limit = rate_limit(max_calls=5, period_seconds=600, scope="signup")


@router.post(
    "/signup",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(_signup_limit)],
)
def signup(user: UserCreate, db: Session = Depends(get_db)):
    validate_password_strength(user.password)

    db_user = db.query(User).filter(User.email == user.email).first()
    if db_user:
        raise HTTPException(status_code=400, detail="Email already registered")

    token = py_secrets.token_urlsafe(32)

    new_user = User(
        full_name=user.full_name,
        email=user.email,
        phone=user.phone,
        address_line_1=user.address_line_1,
        address_line_2=user.address_line_2,
        landmark=user.landmark,
        location_link=user.location_link,
        hashed_password=get_password_hash(user.password),
        email_verified=True,
        email_verification_token=None,
    )

    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    # Fire-and-forget the verification email. Failure here must NOT roll back
    # signup — the user can re-request via /resend-verification.
    link = f"{_frontend_origin()}/verify-email?token={token}"
    try:
        send_verification_email(new_user.email, new_user.full_name or "", link)
    except Exception:
        logger.exception("Failed to send verification email to %s", new_user.email)

    return new_user

_login_limit = rate_limit(max_calls=8, period_seconds=300, scope="login")


@router.post("/login", response_model=Token, dependencies=[Depends(_login_limit)])
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    # Find user by email (OAuth2 uses 'username' field, which we map to email)
    user = db.query(User).filter(User.email == form_data.username).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user found with this email. Please create an account.",
        )
    
    if not verify_password(form_data.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password. Please try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

# Extra route to support JSON login (if frontend doesn't use formData)
@router.post("/login/json", response_model=Token, dependencies=[Depends(_login_limit)])
def login_json(credentials: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == credentials.email).first()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No user found with this email. Please create an account.",
        )
    
    if not verify_password(credentials.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect password. Please try again.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(data={"sub": str(user.id), "email": user.email})
    return {"access_token": access_token, "token_type": "bearer"}

@router.get("/me", response_model=UserResponse)
def read_users_me(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Return the user with derived account-state flags.

    `has_subscription` is True if they've ever held a subscription (even cancelled)
    — we use that to skip the 10-day auto-delete grace banner.
    `days_until_auto_delete` is the count down to hard deletion. Null once they've
    subscribed at least once (subscribing once grants permanent immunity).
    """
    ever_subscribed = db.query(Subscription.id).filter(
        Subscription.customer_id == current_user.id
    ).first() is not None

    if ever_subscribed or (current_user.role and current_user.role.lower() == "admin"):
        days_until_auto_delete: Optional[int] = None
    elif current_user.created_at:
        created = current_user.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        days_passed = (datetime.now(timezone.utc) - created).days
        days_until_auto_delete = max(0, INACTIVE_ACCOUNT_GRACE_DAYS - days_passed)
    else:
        days_until_auto_delete = None

    payload = UserResponse.model_validate(current_user).model_copy(update={
        "has_subscription": ever_subscribed,
        "days_until_auto_delete": days_until_auto_delete,
    })
    return payload


@router.put("/me", response_model=UserResponse)
def update_me(
    payload: UserUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update the logged-in user's profile fields (everything except email/password/role)."""
    data = payload.dict(exclude_unset=True)
    for field, value in data.items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.put("/me/notifications", response_model=UserResponse)
def update_my_notifications(
    payload: NotificationPrefsUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Persist notification toggle preferences for the logged-in user."""
    data = payload.dict(exclude_unset=True)
    for field, value in data.items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.post("/change-password")
def change_password(
    payload: PasswordChangeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Authenticated password change. Requires the current password."""
    if not verify_password(payload.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    validate_password_strength(payload.new_password)

    current_user.hashed_password = get_password_hash(payload.new_password)
    db.commit()
    return {"message": "Password updated successfully."}


@router.delete("/me", status_code=status.HTTP_204_NO_CONTENT)
def delete_me(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Permanently delete the logged-in user's account.

    Cancellations and credits cascade-delete via the relationships defined on User.
    Subscriptions are kept (no FK cascade in the model) — they become orphaned history.
    """
    if current_user.role and current_user.role.lower() == "admin":
        raise HTTPException(status_code=403, detail="Admin accounts cannot self-delete.")
    db.delete(current_user)
    db.commit()
    return


_forgot_pwd_limit = rate_limit(max_calls=5, period_seconds=300, scope="forgot_password")


@router.post("/forgot-password", dependencies=[Depends(_forgot_pwd_limit)])
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Send a password-reset OTP if the email is registered.

    Always returns the same generic message — including when the email is
    unknown, when email delivery fails, and when the OTP send succeeds. This
    prevents email enumeration via response status or body. Failures are
    logged loudly so ops still sees them.
    """
    generic = {"message": "If that email is in our system, we have sent an OTP."}

    user = db.query(User).filter(User.email == payload.email).first()
    if not user:
        # Constant-shape response to match the "user exists, email sent" path.
        return generic

    otp = ''.join(random.choices(string.digits, k=6))
    user.reset_otp = otp
    user.reset_otp_expires = datetime.now(timezone.utc) + timedelta(minutes=5)
    db.commit()

    if not send_reset_password_email(to_email=user.email, otp=otp):
        # Rollback OTP so the user doesn't end up with one they never received.
        user.reset_otp = None
        user.reset_otp_expires = None
        db.commit()
        logger.error("Password-reset email failed for user_id=%s; returning generic success to avoid enumeration", user.id)

    return generic


@router.post("/verify-otp")
def verify_otp(payload: VerifyOtpRequest, db: Session = Depends(get_db)):
    """Validate the password-reset OTP without consuming it.

    Returns 200 if the OTP matches and is not expired. The OTP stays in the
    DB so the subsequent /reset-password call still validates it as the auth
    proof when the user submits a new password.
    """
    user = db.query(User).filter(User.email == payload.email).first()
    if not user or not user.reset_otp or not hmac.compare_digest(user.reset_otp, payload.otp):
        raise HTTPException(status_code=400, detail="Invalid OTP")

    now = datetime.now(timezone.utc)
    expires = user.reset_otp_expires
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not expires or expires < now:
        raise HTTPException(status_code=400, detail="OTP has expired")

    return {"message": "OTP verified"}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == payload.email).first()
    # Symmetric error: unknown email and bad OTP look identical to the caller
    # so the endpoint cannot be used to enumerate registered emails.
    if not user or not user.reset_otp or not hmac.compare_digest(user.reset_otp, payload.otp):
        raise HTTPException(status_code=400, detail="Invalid OTP")

    now = datetime.now(timezone.utc)
    expires = user.reset_otp_expires
    if expires and expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    if not expires or expires < now:
        raise HTTPException(status_code=400, detail="OTP has expired")

    validate_password_strength(payload.new_password)

    user.hashed_password = get_password_hash(payload.new_password)
    user.reset_otp = None
    user.reset_otp_expires = None
    db.commit()

    return {"message": "Password reset successful"}


# ── Email verification ────────────────────────────────────────────────────────

_resend_verify_limit = rate_limit(max_calls=3, period_seconds=600, scope="resend_verify")


@router.get("/verify-email")
def verify_email(token: str, db: Session = Depends(get_db)):
    """Mark the user matching `token` as verified. One-shot — the token is
    cleared on success so it can't be replayed."""
    if not token:
        raise HTTPException(status_code=400, detail="Verification token is required.")

    user = db.query(User).filter(User.email_verification_token == token).first()
    if not user:
        raise HTTPException(status_code=400, detail="This link is invalid or has already been used.")

    user.email_verified = True
    user.email_verification_token = None
    db.commit()
    return {"message": "Email verified successfully."}


@router.post("/resend-verification", dependencies=[Depends(_resend_verify_limit)])
def resend_verification(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Re-issue the verification email for the logged-in user. Generates a
    fresh token so older links are invalidated."""
    if current_user.email_verified:
        return {"message": "Email is already verified."}

    token = py_secrets.token_urlsafe(32)
    current_user.email_verification_token = token
    db.commit()

    link = f"{_frontend_origin()}/verify-email?token={token}"
    sent = send_verification_email(current_user.email, current_user.full_name or "", link)
    if not sent:
        logger.error("Failed to resend verification email for user_id=%s", current_user.id)
        raise HTTPException(status_code=503, detail="Could not send verification email. Please try again shortly.")
    return {"message": "Verification email sent."}
