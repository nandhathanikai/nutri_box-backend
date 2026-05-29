import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session
from sqlalchemy import func, or_
from pydantic import BaseModel, EmailStr, validator
from typing import Optional
from app.database import get_db
from app.models.user import User
from app.models.subscription import Subscription
from app.models.menu import PlanTemplate
from app.models.meal_tier import MealTier
from app.models.credit import DeliveryCancellation, Credit
from app.models.marketing import Offer
from app.models.audit_log import AuditLog
from app.routers.auth import require_admin, get_current_user
from app.utils.security import get_password_hash
from datetime import date, datetime, timedelta, timezone
from dateutil.relativedelta import relativedelta

logger = logging.getLogger(__name__)

# India Standard Time = UTC+05:30. Used everywhere we must reason about "today
# from the customer's perspective" rather than the server's local TZ.
IST = timezone(timedelta(hours=5, minutes=30))


def _today_ist() -> date:
    return datetime.now(IST).date()

router = APIRouter(tags=["Admin"], dependencies=[Depends(require_admin)])


@router.get("/dashboard-stats")
def get_dashboard_stats(db: Session = Depends(get_db)):
    today = date.today()
    this_month_start = today.replace(day=1)

    # 1. Active Customers (customers with an active subscription)
    active_customers = db.query(Subscription.customer_id).filter(
        Subscription.end_date >= today
    ).distinct().count()

    # 2. Monthly Revenue (Sum of PlanTemplate.price for subscriptions started this month)
    rev_result = db.query(func.sum(PlanTemplate.price)).join(
        Subscription, Subscription.menu_id == PlanTemplate.id
    ).filter(
        Subscription.start_date >= this_month_start
    ).scalar()
    monthly_revenue = float(rev_result) if rev_result else 0.0

    if monthly_revenue >= 100000:
        monthly_revenue_str = f"₹{round(monthly_revenue / 100000, 2)}L"
    else:
        monthly_revenue_str = f"₹{int(monthly_revenue):,}"

    # 3. Cancellations (Total this month)
    cancellations = db.query(DeliveryCancellation).filter(
        DeliveryCancellation.delivery_date >= this_month_start
    ).count()

    # 4. Active Offers
    active_offers = db.query(Offer).filter(Offer.status == 'active').count()

    # 5. Revenue Trend (last 6 months) — single grouped query, bucketed in Python.
    six_months_start = date(
        today.year + (today.month - 6) // 12,
        (today.month - 6) % 12 + 1,
        1,
    )
    month_trunc = func.date_trunc("month", Subscription.start_date).label("m")
    rev_rows = (
        db.query(month_trunc, func.sum(PlanTemplate.price))
        .join(Subscription, Subscription.menu_id == PlanTemplate.id)
        .filter(Subscription.start_date >= six_months_start)
        .group_by(month_trunc)
        .all()
    )
    rev_by_month: dict[tuple[int, int], float] = {}
    for bucket, total in rev_rows:
        if bucket is None:
            continue
        rev_by_month[(bucket.year, bucket.month)] = float(total) if total else 0.0

    trend_labels: list[str] = []
    trend_data: list[float] = []
    for i in range(5, -1, -1):
        y = today.year + (today.month - i - 1) // 12
        m = (today.month - i - 1) % 12 + 1
        trend_labels.append(date(y, m, 1).strftime("%b"))
        trend_data.append(rev_by_month.get((y, m), 0.0))

    # 6. Cancellations by session
    cancel_stats = db.query(DeliveryCancellation.session, func.count(DeliveryCancellation.id)).filter(
        DeliveryCancellation.delivery_date >= this_month_start
    ).group_by(DeliveryCancellation.session).all()

    cancel_dict = {row[0].lower() if row[0] else '': row[1] for row in cancel_stats}
    cancel_labels = ['Breakfast', 'Dinner', 'Snack']
    cancel_data = [
        cancel_dict.get('breakfast', 0) + cancel_dict.get('bf', 0),
        cancel_dict.get('dinner', 0),
        cancel_dict.get('snack', 0),
    ]

    return {
        "activeCustomers": active_customers,
        "monthlyRevenue": monthly_revenue_str,
        "cancellations": cancellations,
        "activeOffers": active_offers,
        "revenueTrend": {
            "labels": trend_labels,
            "data": trend_data
        },
        "cancellationsBySession": {
            "labels": cancel_labels,
            "data": cancel_data
        }
    }


@router.get("/customers")
def get_customers(
    page: int = Query(1, ge=1),
    limit: int = Query(50, ge=1, le=200),
    search: Optional[str] = Query(None, description="Substring match on name, email, or phone"),
    db: Session = Depends(get_db),
):
    """Admin customer list — paginated.

    Returns {total, page, limit, data}. Default 50 per page, max 200. Server
    enforces both bounds so the frontend can't accidentally request 100k rows.
    """
    today = date.today()

    base_q = db.query(User).filter(User.role.in_(["customer", "admin"]))
    if search:
        like = f"%{search.strip()}%"
        base_q = base_q.filter(or_(
            User.full_name.ilike(like),
            User.email.ilike(like),
            User.phone.ilike(like),
        ))

    total = base_q.count()
    users = (
        base_q.order_by(User.id.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    if not users:
        return {"total": total, "page": page, "limit": limit, "data": []}

    user_ids = [u.id for u in users]

    # 2) Latest subscription per customer + its plan, in one shot.
    # Window function via Postgres: rank subs by end_date desc per customer, take rank=1.
    latest_sub_subq = (
        db.query(
            Subscription.customer_id.label("customer_id"),
            Subscription.start_date.label("start_date"),
            Subscription.end_date.label("end_date"),
            Subscription.menu_id.label("menu_id"),
            func.row_number()
                .over(partition_by=Subscription.customer_id,
                      order_by=Subscription.end_date.desc().nullslast())
                .label("rn"),
        )
        .filter(Subscription.customer_id.in_(user_ids))
        .subquery()
    )

    latest_rows = (
        db.query(
            latest_sub_subq.c.customer_id,
            latest_sub_subq.c.start_date,
            latest_sub_subq.c.end_date,
            PlanTemplate.name.label("plan_name"),
            PlanTemplate.slot_combo.label("slot_combo"),
        )
        .outerjoin(PlanTemplate, PlanTemplate.id == latest_sub_subq.c.menu_id)
        .filter(latest_sub_subq.c.rn == 1)
        .all()
    )
    sub_map = {row.customer_id: row for row in latest_rows}

    # 3) Pending+scheduled credit counts grouped by user
    credit_counts_rows = (
        db.query(Credit.user_id, func.count(Credit.id))
        .filter(
            Credit.user_id.in_(user_ids),
            Credit.status.in_(["pending", "scheduled"]),
        )
        .group_by(Credit.user_id)
        .all()
    )
    credit_map = {uid: cnt for uid, cnt in credit_counts_rows}

    SLOT_LABELS = {
        "breakfast_only": "Breakfast",
        "dinner_only": "Dinner",
        "both": "Breakfast + Dinner",
    }

    customer_list = []
    for u in users:
        row = sub_map.get(u.id)

        plan_name = "Basic"
        sessions_str = "Lunch Only"
        s_date = ""
        e_date = ""
        status_val = "EXPIRED"

        if row is not None:
            s_date = str(row.start_date) if row.start_date else ""
            e_date = str(row.end_date) if row.end_date else ""
            plan_name = row.plan_name or "Plan"
            sessions_str = SLOT_LABELS.get(row.slot_combo or "", sessions_str)

            if row.end_date and row.end_date >= today:
                status_val = "EXPIRING" if (row.end_date - today).days <= 3 else "ACTIVE"

        customer_list.append({
            "id": u.id,
            "email": u.email,
            "name": u.full_name,
            "phone": u.phone or "N/A",
            "plan": plan_name,
            "sessions": sessions_str,
            "startDate": s_date or "N/A",
            "endDate": e_date or "N/A",
            "credits": credit_map.get(u.id, 0),
            "status": status_val,
            "role": u.role or "customer",
        })

    return {"total": total, "page": page, "limit": limit, "data": customer_list}


@router.get("/todays-orders")
def get_todays_orders(db: Session = Depends(get_db)):
    """List every meal that needs to be sent today, plus the ones skipped by customers.

    A "today's order" is one row per (active subscription, session) for today, where:
      - today is a delivery day (Mon–Sat; Sunday is off),
      - today falls within [start_date, end_date] of the subscription,
      - the plan's slot_combo defines which sessions (BF / DINNER) are due today.

    Sessions the customer cancelled (DeliveryCancellation row for today) appear under `skipped`.
    The rest appear under `orders`.
    """
    today = _today_ist()
    is_weekend = today.weekday() == 6  # Sunday only

    # Pull every subscription whose window includes today.
    active_subs = db.query(Subscription).filter(
        Subscription.start_date <= today,
        Subscription.end_date >= today,
    ).all()

    if not active_subs:
        return {"date": today.isoformat(), "is_weekend": is_weekend, "orders": [], "skipped": []}

    sub_ids = [s.id for s in active_subs]
    customer_ids = list({s.customer_id for s in active_subs})
    menu_ids = list({s.menu_id for s in active_subs if s.menu_id})

    users = {u.id: u for u in db.query(User).filter(User.id.in_(customer_ids)).all()}
    plans = {p.id: p for p in db.query(PlanTemplate).filter(PlanTemplate.id.in_(menu_ids)).all()} if menu_ids else {}
    tier_ids = list({p.tier_id for p in plans.values() if p.tier_id})
    tiers = {t.id: t for t in db.query(MealTier).filter(MealTier.id.in_(tier_ids)).all()} if tier_ids else {}

    # Today's cancellations keyed by (subscription_id, session_upper)
    today_cancels = db.query(DeliveryCancellation).filter(
        DeliveryCancellation.subscription_id.in_(sub_ids),
        DeliveryCancellation.delivery_date == today,
    ).all()
    cancel_map = {(c.subscription_id, (c.session or "").upper()): c for c in today_cancels}

    SESSION_LABELS = {"BF": "Breakfast", "DINNER": "Dinner"}

    orders: list[dict] = []
    skipped: list[dict] = []

    for sub in active_subs:
        user = users.get(sub.customer_id)
        plan = plans.get(sub.menu_id) if sub.menu_id else None
        tier = tiers.get(plan.tier_id) if (plan and plan.tier_id) else None

        # Determine which sessions are due today based on slot_combo
        session_keys: list[str] = []
        slot_combo = (plan.slot_combo if plan else None) or ""
        if slot_combo in ("breakfast_only", "both"):
            session_keys.append("BF")
        if slot_combo in ("dinner_only", "both"):
            session_keys.append("DINNER")

        if not session_keys:
            continue

        address_parts = []
        if user:
            if user.address_line_1: address_parts.append(user.address_line_1)
            if user.address_line_2: address_parts.append(user.address_line_2)
            if user.landmark: address_parts.append(f"Near {user.landmark}")
        address = ", ".join(address_parts) if address_parts else "—"

        for sk in session_keys:
            row = {
                "subscription_id": sub.id,
                "customer_id": user.id if user else None,
                "customer_name": user.full_name if user else "—",
                "customer_email": user.email if user else "",
                "customer_phone": (user.phone if user and user.phone else "—"),
                "address": address,
                "tier_name": (tier.name if tier else "—"),
                "plan_name": (plan.name if plan and plan.name else (tier.name if tier else "Plan")),
                "diet_type": (plan.diet_type if plan else "—"),
                "session_key": sk,
                "session_label": SESSION_LABELS.get(sk, sk),
            }

            cancellation = cancel_map.get((sub.id, sk))
            if cancellation:
                row["cancelled_at"] = cancellation.cancelled_at.isoformat() if cancellation.cancelled_at else None
                skipped.append(row)
            elif is_weekend:
                # Skip weekends entirely (no delivery)
                continue
            else:
                orders.append(row)

    # Stable ordering: session first (BF before DINNER), then customer name
    session_order = {"BF": 0, "DINNER": 1}
    orders.sort(key=lambda r: (session_order.get(r["session_key"], 9), r["customer_name"].lower()))
    skipped.sort(key=lambda r: (session_order.get(r["session_key"], 9), r["customer_name"].lower()))

    return {
        "date": today.isoformat(),
        "is_weekend": is_weekend,
        "orders": orders,
        "skipped": skipped,
    }


@router.get("/reports")
def get_reports(period: str = "week", db: Session = Depends(get_db)):
    today = date.today()

    if period == "week":
        start_date = today - timedelta(days=7)
    elif period == "quarter":
        start_date = today - relativedelta(months=3)
    else:  # month
        start_date = today - relativedelta(months=1)

    rev_result = db.query(func.sum(PlanTemplate.price)).join(
        Subscription, Subscription.menu_id == PlanTemplate.id
    ).filter(Subscription.start_date >= start_date).scalar()
    rev = float(rev_result) if rev_result else 0.0

    orders = db.query(Subscription).filter(Subscription.start_date >= start_date).count()

    # New customers — count distinct customer_ids whose earliest subscription falls in window
    new_customers_query = (
        db.query(Subscription.customer_id, func.min(Subscription.start_date).label("first"))
        .group_by(Subscription.customer_id)
        .subquery()
    )
    new_customers = db.query(new_customers_query).filter(
        new_customers_query.c.first >= start_date
    ).count()

    aov = (rev / orders) if orders > 0 else 0.0

    top_items_data = db.query(
        PlanTemplate.name,
        func.count(Subscription.id).label('orders'),
        func.sum(PlanTemplate.price).label('revenue')
    ).join(Subscription, Subscription.menu_id == PlanTemplate.id).filter(
        Subscription.start_date >= start_date
    ).group_by(PlanTemplate.name).order_by(func.count(Subscription.id).desc()).limit(5).all()

    top_items = [{
        "name": item[0] or "Custom Plan",
        "orders": item[1],
        "revenue": f"₹{int(item[2] or 0):,}"
    } for item in top_items_data]

    chart_labels = []
    chart_values = []

    if period == "week":
        for d in range(6, -1, -1):
            day = today - timedelta(days=d)
            day_rev = db.query(func.sum(PlanTemplate.price)).join(
                Subscription, Subscription.menu_id == PlanTemplate.id
            ).filter(Subscription.start_date == day).scalar()
            chart_labels.append(day.strftime("%a"))
            chart_values.append(float(day_rev) if day_rev else 0.0)
    elif period == "month":
        for w in range(3, -1, -1):
            w_start = start_date + timedelta(days=w * 7)
            w_end = w_start + timedelta(days=7)
            w_rev = db.query(func.sum(PlanTemplate.price)).join(
                Subscription, Subscription.menu_id == PlanTemplate.id
            ).filter(
                Subscription.start_date >= w_start,
                Subscription.start_date < w_end
            ).scalar()
            chart_labels.append(f"Wk{4 - w}")
            chart_values.append(float(w_rev) if w_rev else 0.0)
    else:
        for m in range(2, -1, -1):
            m_start = start_date + relativedelta(months=2 - m)
            m_end = m_start + relativedelta(months=1)
            m_rev = db.query(func.sum(PlanTemplate.price)).join(
                Subscription, Subscription.menu_id == PlanTemplate.id
            ).filter(
                Subscription.start_date >= m_start,
                Subscription.start_date < m_end
            ).scalar()
            chart_labels.append(m_start.strftime("%b"))
            chart_values.append(float(m_rev) if m_rev else 0.0)

    user_counts = db.query(
        Subscription.customer_id,
        func.count(Subscription.id)
    ).group_by(Subscription.customer_id).all()

    seg = {"New": 0, "Occasional": 0, "Regular": 0, "Loyal": 0}
    for _, count in user_counts:
        if count == 1:
            seg["New"] += 1
        elif count <= 5:
            seg["Occasional"] += 1
        elif count <= 15:
            seg["Regular"] += 1
        else:
            seg["Loyal"] += 1

    total_users = sum(seg.values()) or 1
    segments = [
        {"label": "New (1 order)", "count": seg["New"], "pct": round(seg["New"] / total_users * 100), "color": "#5b9bd5"},
        {"label": "Occasional (2–5)", "count": seg["Occasional"], "pct": round(seg["Occasional"] / total_users * 100), "color": "#2d6a10"},
        {"label": "Regular (6–15)", "count": seg["Regular"], "pct": round(seg["Regular"] / total_users * 100), "color": "#c47a1a"},
        {"label": "Loyal (16+)", "count": seg["Loyal"], "pct": round(seg["Loyal"] / total_users * 100), "color": "#c83b3b"},
    ]

    return {
        "revenue": f"₹{int(rev):,}",
        "totalOrders": orders,
        "newCustomers": new_customers,
        "aov": f"₹{int(aov)}",
        "chartData": {
            "labels": chart_labels,
            "values": chart_values
        },
        "topItems": top_items,
        "segments": segments
    }


class AdminUserCreate(BaseModel):
    full_name: str
    email: EmailStr
    phone: str
    password: str
    address_line_1: str = ""
    address_line_2: Optional[str] = None
    landmark: Optional[str] = None
    location_link: Optional[str] = None
    role: str = "customer"        # 'customer' | 'admin'

    @validator("role")
    def _valid_role(cls, v: str):
        v = (v or "").lower().strip()
        if v not in ("customer", "admin"):
            raise ValueError("role must be 'customer' or 'admin'")
        return v

    @validator("password")
    def _password_strength(cls, v: str):
        import re
        if (
            len(v) < 8
            or not re.search(r"[A-Z]", v)
            or not re.search(r"[a-z]", v)
            or not re.search(r"\d", v)
        ):
            raise ValueError(
                "password must be at least 8 characters and include an uppercase letter, "
                "a lowercase letter, and a number"
            )
        return v


@router.post("/customers", status_code=status.HTTP_201_CREATED)
def admin_create_user(
    payload: AdminUserCreate,
    db: Session = Depends(get_db),
):
    """Admin creates a customer or another admin.

    Same shape as public `/api/auth/signup` but with a role selector.
    Address fields stay optional (admin may add a customer who hasn't given one).
    """
    existing = db.query(User).filter(User.email == payload.email).first()
    if existing:
        raise HTTPException(status_code=409, detail="An account with this email already exists.")

    new_user = User(
        full_name=payload.full_name,
        email=payload.email,
        phone=payload.phone,
        address_line_1=payload.address_line_1 or None,
        address_line_2=payload.address_line_2,
        landmark=payload.landmark,
        location_link=payload.location_link,
        hashed_password=get_password_hash(payload.password),
        role=payload.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)

    return {
        "id": new_user.id,
        "email": new_user.email,
        "full_name": new_user.full_name,
        "role": new_user.role,
    }


@router.delete("/customers/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_customer(
    user_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """Hard-delete a customer account. Cancellations + credits cascade via the User model.

    Subscriptions are kept (no FK cascade) — orphaned rows preserve revenue history.
    Blocked: deleting yourself, or deleting another admin via this endpoint.
    """
    if not admin.role or admin.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot delete your own admin account here.")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target.role and target.role.lower() == "admin":
        raise HTTPException(status_code=403, detail="Cannot delete another admin via this endpoint.")

    # Snapshot identifying fields BEFORE the cascade deletes the row, so the
    # audit log preserves who was deleted even after the user row is gone.
    snapshot = {
        "email": target.email,
        "full_name": target.full_name,
        "phone": target.phone,
        "created_at": target.created_at.isoformat() if target.created_at else None,
    }

    # Disassociate subscriptions to satisfy the foreign key constraint and preserve records
    db.query(Subscription).filter(Subscription.customer_id == user_id).update({Subscription.customer_id: None})

    db.delete(target)
    db.add(AuditLog(
        actor_id=admin.id,
        actor_email=admin.email,
        action="admin.customer.delete",
        target_type="user",
        target_id=str(user_id),
        details=snapshot,
    ))
    db.commit()
    logger.info("Admin %s (id=%s) deleted customer id=%s email=%s", admin.email, admin.id, user_id, snapshot["email"])
    return


class ChangeRolePayload(BaseModel):
    role: str

    @validator("role")
    def _valid_role(cls, v: str):
        v = (v or "").lower().strip()
        if v not in ("customer", "admin"):
            raise ValueError("role must be 'customer' or 'admin'")
        return v


@router.put("/customers/{user_id}/role")
def change_customer_role(
    user_id: int,
    payload: ChangeRolePayload,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_user),
):
    """Change a user's role to either 'customer' or 'admin'."""
    if not admin.role or admin.role.lower() != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")

    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="You cannot change your own role.")

    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    target.role = payload.role
    db.commit()
    return {"message": f"Role updated to {payload.role}"}
