"""Add hot-path indexes for Nutribox query patterns.

Idempotent (CREATE INDEX IF NOT EXISTS) — safe to run multiple times.
No schema changes, no data changes; only adds btree indexes.

Run once after deploy:
    python -m scripts.migrations.migrate_perf_indexes
"""
from sqlalchemy import text
from app.database import engine


STATEMENTS = [
    # Subscriptions: "find this user's active sub" + "active subs in window" — the most-repeated pattern.
    "CREATE INDEX IF NOT EXISTS ix_subscriptions_customer_end ON subscriptions (customer_id, end_date)",
    "CREATE INDEX IF NOT EXISTS ix_subscriptions_start_date    ON subscriptions (start_date)",
    "CREATE INDEX IF NOT EXISTS ix_subscriptions_menu_id       ON subscriptions (menu_id)",

    # Delivery cancellations: per-subscription lookups (calendar, today's-orders),
    # and (delivery_date, session) for dashboard-stats GROUP BY.
    "CREATE INDEX IF NOT EXISTS ix_delivery_cancellations_sub          ON delivery_cancellations (subscription_id)",
    "CREATE INDEX IF NOT EXISTS ix_delivery_cancellations_date_session ON delivery_cancellations (delivery_date, session)",
    "CREATE INDEX IF NOT EXISTS ix_delivery_cancellations_user         ON delivery_cancellations (user_id)",

    # Credits: per-user status filter is the dominant pattern.
    "CREATE INDEX IF NOT EXISTS ix_credits_user_status      ON credits (user_id, status)",
    "CREATE INDEX IF NOT EXISTS ix_credits_cancellation_id  ON credits (cancellation_id)",
    "CREATE INDEX IF NOT EXISTS ix_credits_subscription_id  ON credits (subscription_id)",

    # Plan templates: tier_id is hot for menu lookups.
    "CREATE INDEX IF NOT EXISTS ix_plan_templates_tier ON plan_templates (tier_id)",

    # Tier pricing: (tier_id, is_active, effective_from DESC) for "current price for tier" lookups.
    "CREATE INDEX IF NOT EXISTS ix_tier_pricing_lookup ON tier_pricing (tier_id, is_active, effective_from DESC)",

    # Weekly menu images: 2-stage fallback lookup pattern.
    "CREATE INDEX IF NOT EXISTS ix_weekly_menu_images_lookup ON weekly_menu_images (tier_id, diet_type, week_start_date)",

    # Users: role filter uses ilike() so use functional lower(role) for index hit.
    "CREATE INDEX IF NOT EXISTS ix_users_role_lower ON users (lower(role))",
]


def run():
    with engine.begin() as conn:
        for stmt in STATEMENTS:
            print(f"-> {stmt}")
            conn.execute(text(stmt))
    print(f"OK - {len(STATEMENTS)} indexes ensured.")


if __name__ == "__main__":
    run()
