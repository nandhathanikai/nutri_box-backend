from datetime import datetime, date, time, timedelta
from typing import List, Dict, Any
import pytz

CANCELLATION_CUTOFF_HOUR = 18      # 6 PM
CANCELLATION_CUTOFF_TZ   = "Asia/Kolkata"   # IST — adjust if needed
CREDIT_DAYS_PER_CANCEL   = 1       # Always 1 day per session cancel
CREDIT_EXPIRY_DAYS       = 90      # Credits expire 90 days after becoming 'scheduled' if unused

IST = pytz.timezone(CANCELLATION_CUTOFF_TZ)

def compute_cutoff(delivery_date: date) -> datetime:
    """
    Returns the cutoff datetime in UTC for a given delivery_date.
    Cutoff = 6:00 PM IST on the DAY BEFORE delivery_date.
    """
    day_before = delivery_date - timedelta(days=1)
    cutoff_naive = datetime.combine(day_before, time(CANCELLATION_CUTOFF_HOUR, 0, 0))
    cutoff_ist = IST.localize(cutoff_naive)
    return cutoff_ist.astimezone(pytz.utc)

def is_cancellation_eligible(delivery_date: date, cancelled_at_utc: datetime) -> bool:
    if cancelled_at_utc.tzinfo is None:
        cancelled_at_utc = cancelled_at_utc.replace(tzinfo=pytz.utc)
    cutoff_utc = compute_cutoff(delivery_date)
    return cancelled_at_utc < cutoff_utc

def compute_delivery_dates(credits_by_date: Dict[date, list], plan_end_date: date) -> List[dict]:
    """
    Given credits grouped by original_delivery_date and a plan_end_date,
    assign sequential delivery_on dates starting from plan_end_date + 1.

    All credits from the same original_delivery_date share the same bonus day.
    Dates are sorted chronologically.

    Returns list of dicts: [{ 'credit_id': int, 'delivery_on': date }, ...]
    """
    sorted_dates = sorted(credits_by_date.keys())
    result = []
    bonus_day = plan_end_date + timedelta(days=1)

    for orig_date in sorted_dates:
        for credit in credits_by_date[orig_date]:
            result.append({
                'credit_id': credit.id if hasattr(credit, 'id') else credit['id'],
                'delivery_on': bonus_day,
            })
        bonus_day += timedelta(days=1)

    return result

def get_last_credit_delivery_date(scheduled_credits: list, plan_end_date: date) -> date:
    """
    Returns the last delivery_on date among scheduled credits for a user,
    or plan_end_date if no scheduled credits exist.
    Used to determine when a new plan can start (squeeze logic).
    """
    if not scheduled_credits:
        return plan_end_date

    last = max(c.delivery_on for c in scheduled_credits if c.delivery_on)
    return last if last else plan_end_date
