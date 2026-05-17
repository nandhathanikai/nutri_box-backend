import logging
from datetime import datetime, date, timedelta, timezone
from collections import defaultdict
from sqlalchemy.orm import Session
from app.models.credit import Credit
from app.models.subscription import Subscription
from app.models.user import User
from app.utils.credits import CREDIT_EXPIRY_DAYS, compute_delivery_dates
from app.utils.email import is_email_configured, send_credit_expiry_warning

logger = logging.getLogger(__name__)

# Number of days before expiry at which we should warn the customer.
CREDIT_EXPIRY_WARN_DAYS = 7


# A customer who creates an account but never subscribes is auto-deleted after this many days.
# Subscribing once (even briefly) grants permanent immunity.
INACTIVE_ACCOUNT_GRACE_DAYS = 10


def promote_pending_credits(db: Session) -> int:
    """
    For every 'pending' credit where plan_end_date < today,
    transition to 'scheduled' and assign delivery_on dates.

    Grouping logic:
      - Group by (user_id, plan_end_date)
      - Within each group, sub-group by original_delivery_date
      - Assign sequential delivery_on dates starting from plan_end_date + 1
      - All credits from the same original_delivery_date share the same bonus day
    """
    today = date.today()

    pending_credits = (
        db.query(Credit)
        .filter(
            Credit.status == 'pending',
            Credit.plan_end_date < today,
        )
        .all()
    )

    if not pending_credits:
        return 0

    # Group by (user_id, plan_end_date) to handle each plan separately
    plan_groups = defaultdict(list)
    for credit in pending_credits:
        key = (credit.user_id, credit.plan_end_date)
        plan_groups[key].append(credit)

    processed = 0
    for (user_id, plan_end_date), group_credits in plan_groups.items():
        # Sub-group by original_delivery_date
        by_date = defaultdict(list)
        for c in group_credits:
            by_date[c.original_delivery_date].append(c)

        # Compute delivery dates
        assignments = compute_delivery_dates(by_date, plan_end_date)

        # Apply assignments
        credit_map = {c.id: c for c in group_credits}
        for assignment in assignments:
            credit = credit_map[assignment['credit_id']]
            credit.status = 'scheduled'
            credit.delivery_on = assignment['delivery_on']
            credit.updated_at = datetime.utcnow()
            processed += 1

    db.commit()
    return processed


def mark_delivered(db: Session) -> int:
    """
    Transition scheduled credits to delivered when delivery_on <= today.
    This should be run daily.
    """
    today = date.today()

    scheduled = (
        db.query(Credit)
        .filter(
            Credit.status == 'scheduled',
            Credit.delivery_on <= today,
        )
        .all()
    )

    count = 0
    for credit in scheduled:
        credit.status = 'delivered'
        credit.updated_at = datetime.utcnow()
        count += 1

    db.commit()
    return count


def delete_inactive_accounts(db: Session) -> int:
    """Hard-delete customer accounts that:

      - have role='customer'
      - were created more than INACTIVE_ACCOUNT_GRACE_DAYS ago
      - have NEVER had a subscription (not even a cancelled one)

    Cancellations + credits cascade via the User model relationships.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=INACTIVE_ACCOUNT_GRACE_DAYS)

    # Subquery of every user who has ever had a subscription
    ever_subscribed = db.query(Subscription.customer_id).distinct().subquery()

    candidates = (
        db.query(User)
        .filter(
            User.role.ilike("customer"),
            User.created_at.isnot(None),
            User.created_at < cutoff,
            ~User.id.in_(db.query(ever_subscribed.c.customer_id)),
        )
        .all()
    )

    count = 0
    for user in candidates:
        db.delete(user)
        count += 1
    db.commit()
    return count


def expire_stale_credits(db: Session) -> int:
    """
    Run daily. Expire scheduled credits that have been scheduled for more than
    CREDIT_EXPIRY_DAYS without being delivered (safety net for edge cases).

    Also identifies credits that will expire within CREDIT_EXPIRY_WARN_DAYS and
    sends a warning email to each affected customer (grouped per user so they
    receive one email, not one per credit). Respects the user's
    notif_delivery preference.
    """
    today = date.today()
    expiry_cutoff = today - timedelta(days=CREDIT_EXPIRY_DAYS)

    if CREDIT_EXPIRY_WARN_DAYS is not None:
        warn_cutoff = today - timedelta(days=CREDIT_EXPIRY_DAYS - CREDIT_EXPIRY_WARN_DAYS)
        warn_credits = (
            db.query(Credit)
            .filter(
                Credit.status == 'scheduled',
                Credit.delivery_on < warn_cutoff,
                Credit.delivery_on >= expiry_cutoff,
            )
            .all()
        )
        if warn_credits:
            # Group by user_id so each customer gets a single summary email.
            by_user: dict[int, list] = defaultdict(list)
            for c in warn_credits:
                by_user[c.user_id].append(c)

            if is_email_configured():
                for uid, credits_list in by_user.items():
                    user = db.query(User).filter(User.id == uid).first()
                    if not user:
                        continue
                    # Respect notification preference — skip if opted out.
                    if not getattr(user, "notif_delivery", True):
                        logger.debug(
                            "Skipping credit expiry email for user %s (notif_delivery=False)", uid,
                        )
                        continue
                    send_credit_expiry_warning(
                        to_email=user.email,
                        full_name=user.full_name or "",
                        credits_count=len(credits_list),
                        days_remaining=CREDIT_EXPIRY_WARN_DAYS,
                    )
            else:
                user_ids = sorted(by_user.keys())
                logger.warning(
                    "Credit expiry warning: %s credit(s) belonging to users %s "
                    "will expire within %s days. Email not configured (BREVO_API_KEY unset).",
                    len(warn_credits), user_ids, CREDIT_EXPIRY_WARN_DAYS,
                )

    count = (
        db.query(Credit)
        .filter(Credit.status == 'scheduled', Credit.delivery_on < expiry_cutoff)
        .update({"status": "not_eligible", "updated_at": datetime.utcnow()})
    )
    db.commit()
    if count:
        logger.info("Expired %s stale credits (delivery_on < %s)", count, expiry_cutoff)
    return count
