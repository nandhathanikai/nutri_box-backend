"""
Razorpay payment router — handles order creation and payment verification.

Flow:
  1. POST /api/payments/create-order  → create Razorpay order, return order_id + key_id
  2. Frontend opens Razorpay Checkout JS modal
  3. POST /api/payments/verify        → verify HMAC, then create subscription record
"""

import hashlib
import hmac
import logging
import os
from datetime import date, timedelta
from typing import Optional

import razorpay
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

from app.database import get_db
from app.models.meal_tier import MealTier
from app.models.menu import PlanTemplate
from app.models.subscription import Subscription
from app.models.user import User
from app.routers.auth import get_current_user
from app.routers.menu import MEAL_COUNT_MAP, DURATION_WORKING_DAYS, _get_current_price
from app.routers.subscriptions import (
    _resolve_plan,
    _next_working_day,
    _last_delivery_date,
    _serialize,
    SubscribeRequest,
    SubscriptionOut,
)

router = APIRouter(prefix="/api/payments", tags=["Payments"])

# ── Razorpay client ──────────────────────────────────────────────────────────

KEY_ID         = os.getenv("RAZORPAY_KEY_ID", "")
KEY_SECRET     = os.getenv("RAZORPAY_KEY_SECRET", "")
WEBHOOK_SECRET = os.getenv("RAZORPAY_WEBHOOK_SECRET", "")

def _rzp_client() -> razorpay.Client:
    if not KEY_ID or not KEY_SECRET:
        raise HTTPException(
            status_code=503,
            detail="Payment gateway not configured. Contact support.",
        )
    return razorpay.Client(auth=(KEY_ID, KEY_SECRET))


# ── Schemas ──────────────────────────────────────────────────────────────────

class CreateOrderRequest(BaseModel):
    tier_slug:  str
    diet_type:  str
    slot_combo: str
    duration:   str


class CreateOrderResponse(BaseModel):
    order_id:  str
    amount:    int          # paise
    currency:  str
    key_id:    str
    plan_name: str
    total:     float        # INR — display to user


class VerifyRequest(BaseModel):
    razorpay_order_id:   str
    razorpay_payment_id: str
    razorpay_signature:  str
    # Plan details so we can create the subscription
    tier_slug:  str
    diet_type:  str
    slot_combo: str
    duration:   str
    start_date: Optional[date] = None


# ── Helpers ──────────────────────────────────────────────────────────────────

def _verify_signature(order_id: str, payment_id: str, signature: str) -> bool:
    """HMAC-SHA256 verification exactly as specified by Razorpay docs."""
    message = f"{order_id}|{payment_id}"
    generated = hmac.new(
        KEY_SECRET.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(generated, signature)


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/create-order", response_model=CreateOrderResponse)
def create_order(
    payload: CreateOrderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Resolve the plan price and create a Razorpay order.
    Returns the order_id + key_id that the frontend needs to open Checkout JS.
    Does NOT create a Subscription record — that happens only after payment verification.
    """
    # Block if user already has an active subscription
    today = date.today()
    overlap = (
        db.query(Subscription)
        .filter(
            Subscription.customer_id == current_user.id,
            Subscription.end_date >= today,
        )
        .first()
    )
    if overlap:
        raise HTTPException(
            status_code=409,
            detail="You already have an active subscription.",
        )

    # Resolve the plan to ensure it exists
    sub_req = SubscribeRequest(
        tier_slug=payload.tier_slug,
        diet_type=payload.diet_type,
        slot_combo=payload.slot_combo,
        duration=payload.duration,
    )
    plan = _resolve_plan(sub_req, db)

    tier = db.query(MealTier).filter(MealTier.slug == payload.tier_slug).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    meal_count = MEAL_COUNT_MAP[(payload.slot_combo, payload.duration)]
    ppm = _get_current_price(str(tier.id), payload.diet_type, db)
    if ppm <= 0:
        raise HTTPException(status_code=400, detail="Plan price is not configured.")

    delivery_per_meal = float(tier.delivery_charge_weekly if payload.duration == "weekly" else tier.delivery_charge_monthly or 0)
    delivery = round(delivery_per_meal * meal_count, 2)
    amount_inr = round(ppm * meal_count + delivery, 2)
    amount_paise = int(round(amount_inr * 100))  # Razorpay expects paise

    rzp = _rzp_client()
    # Razorpay requires receipt to be <= 40 chars. 
    # plan.id is a 36-char UUID, so we truncate it.
    short_plan_id = str(plan.id)[:8]
    order = rzp.order.create({
        "amount":   amount_paise,
        "currency": "INR",
        "receipt":  f"nx_u{current_user.id}_{short_plan_id}",
        "notes": {
            "user_id":    str(current_user.id),
            "plan_id":    str(plan.id),
            "tier_slug":  payload.tier_slug,
            "diet_type":  payload.diet_type,
            "slot_combo": payload.slot_combo,
            "duration":   payload.duration,
        },
    })

    return CreateOrderResponse(
        order_id=order["id"],
        amount=amount_paise,
        currency="INR",
        key_id=KEY_ID,
        plan_name=plan.name or f"{payload.tier_slug} / {payload.diet_type}",
        total=amount_inr,
    )


def _create_subscription_from_payment(
    *,
    db: Session,
    user_id: int,
    tier_slug: str,
    diet_type: str,
    slot_combo: str,
    duration: str,
    razorpay_order_id: str,
    razorpay_payment_id: str,
    requested_start: Optional[date] = None,
) -> Subscription:
    """Idempotently create a subscription for a verified payment.

    If a Subscription with this `razorpay_order_id` already exists, returns it
    unchanged. Otherwise creates one. This is the single source of truth used
    by both /verify (browser flow) and /webhook (server-to-server flow).

    A Razorpay order_id is generated once per checkout attempt and is unique,
    so it is the natural idempotency key. We commit before returning so a
    concurrent caller hitting the unique index will fail fast instead of
    creating a duplicate.
    """
    existing = (
        db.query(Subscription)
        .filter(Subscription.razorpay_order_id == razorpay_order_id)
        .first()
    )
    if existing:
        return existing

    today = date.today()

    # Block if user already has an active subscription on a *different* order.
    overlap = (
        db.query(Subscription)
        .filter(
            Subscription.customer_id == user_id,
            Subscription.end_date >= today,
        )
        .first()
    )
    if overlap:
        raise HTTPException(
            status_code=409,
            detail="A subscription was already activated for your account.",
        )

    sub_req = SubscribeRequest(
        tier_slug=tier_slug,
        diet_type=diet_type,
        slot_combo=slot_combo,
        duration=duration,
    )
    plan = _resolve_plan(sub_req, db)

    start_seed = requested_start or (today + timedelta(days=1))
    if start_seed < today:
        start_seed = today + timedelta(days=1)

    start = _next_working_day(start_seed)
    end   = _last_delivery_date(start, plan.duration or "weekly")

    if plan.meal_count and plan.price:
        ppm_snapshot = round(float(plan.price) / plan.meal_count, 2)
    else:
        ppm_snapshot = _get_current_price(str(plan.tier_id), plan.diet_type, db) or None

    sub = Subscription(
        customer_id=user_id,
        menu_id=plan.id,
        start_date=start,
        end_date=end,
        price_per_meal_snapshot=ppm_snapshot,
        razorpay_order_id=razorpay_order_id,
        razorpay_payment_id=razorpay_payment_id,
    )
    db.add(sub)
    try:
        db.commit()
    except Exception:
        # Unique constraint race: another worker just inserted the same order.
        db.rollback()
        sub = (
            db.query(Subscription)
            .filter(Subscription.razorpay_order_id == razorpay_order_id)
            .first()
        )
        if sub:
            return sub
        raise
    db.refresh(sub)
    return sub


@router.post("/verify", response_model=SubscriptionOut, status_code=201)
def verify_payment(
    payload: VerifyRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Verify Razorpay HMAC signature, then create and activate the subscription.
    Idempotent on razorpay_order_id — calling twice returns the same subscription.
    """
    if not _verify_signature(
        payload.razorpay_order_id,
        payload.razorpay_payment_id,
        payload.razorpay_signature,
    ):
        raise HTTPException(status_code=400, detail="Payment verification failed. Invalid signature.")

    sub = _create_subscription_from_payment(
        db=db,
        user_id=current_user.id,
        tier_slug=payload.tier_slug,
        diet_type=payload.diet_type,
        slot_combo=payload.slot_combo,
        duration=payload.duration,
        razorpay_order_id=payload.razorpay_order_id,
        razorpay_payment_id=payload.razorpay_payment_id,
        requested_start=payload.start_date,
    )
    return _serialize(sub, db)


# ── Webhook ───────────────────────────────────────────────────────────────────
#
# Configure in Razorpay Dashboard → Settings → Webhooks:
#   URL:     https://<your-domain>/api/payments/webhook
#   Secret:  same value as RAZORPAY_WEBHOOK_SECRET env var
#   Events:  payment.captured (at minimum)
#
# Razorpay retries non-2xx responses, so we MUST return 200 once we've
# acknowledged the event — even for "ignored" event types — and we MUST be
# idempotent (the same event may be redelivered).

@router.post("/webhook", status_code=200)
async def razorpay_webhook(
    request: Request,
    x_razorpay_signature: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    """Server-to-server fallback for Razorpay payment events.

    Protects against the case where the browser closes between payment and
    /verify — Razorpay will still POST here and we create the subscription.
    """
    if not WEBHOOK_SECRET:
        logger.error("Razorpay webhook hit but RAZORPAY_WEBHOOK_SECRET is unset")
        raise HTTPException(status_code=503, detail="Webhook not configured")

    if not x_razorpay_signature:
        raise HTTPException(status_code=400, detail="Missing signature header")

    raw_body = await request.body()
    expected = hmac.new(
        WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, x_razorpay_signature):
        logger.warning("Razorpay webhook signature mismatch")
        raise HTTPException(status_code=400, detail="Invalid signature")

    import json
    try:
        body = json.loads(raw_body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Malformed JSON")

    event = body.get("event")
    if event != "payment.captured":
        # Acknowledge and ignore — Razorpay will not retry on 200.
        return {"status": "ignored", "event": event}

    try:
        payment_entity = body["payload"]["payment"]["entity"]
        order_id   = payment_entity["order_id"]
        payment_id = payment_entity["id"]
        notes      = payment_entity.get("notes") or {}
        user_id    = int(notes["user_id"])
        tier_slug  = notes["tier_slug"]
        diet_type  = notes["diet_type"]
        slot_combo = notes["slot_combo"]
        duration   = notes["duration"]
    except (KeyError, TypeError, ValueError) as e:
        logger.error("Webhook payload missing required fields: %s", e)
        # 200 because we don't want infinite retries on malformed Razorpay data;
        # something's broken on their side and we've logged it.
        return {"status": "bad_payload"}

    try:
        sub = _create_subscription_from_payment(
            db=db,
            user_id=user_id,
            tier_slug=tier_slug,
            diet_type=diet_type,
            slot_combo=slot_combo,
            duration=duration,
            razorpay_order_id=order_id,
            razorpay_payment_id=payment_id,
        )
    except HTTPException as e:
        # 409 overlap: a different sub already covers this user. Log and ack.
        logger.warning("Webhook subscription creation rejected: %s", e.detail)
        return {"status": "rejected", "detail": e.detail}

    return {"status": "ok", "subscription_id": sub.id}
