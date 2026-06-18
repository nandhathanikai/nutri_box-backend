"""
migrate_to_supabase.py
======================
Creates all tables in Supabase (via SQLAlchemy models) and migrates data from
the CSV exports in the ../data/ directory.

Run from the backend/ directory:
    python scripts/migrate_to_supabase.py

Requirements (already in requirements.txt):
    psycopg2-binary, sqlalchemy, python-dotenv
"""

import csv
import json
import os
import sys
import uuid
from datetime import datetime, date
from pathlib import Path

# â”€â”€ Add backend root to sys.path so app.* imports work â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv
load_dotenv(BACKEND_DIR / ".env")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    print("ERROR: DATABASE_URL not set in .env")
    sys.exit(1)

DATA_DIR = BACKEND_DIR.parent / "data"

# â”€â”€ Engine (no pool tricks needed for a one-shot script) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
engine = create_engine(
    DATABASE_URL,
    connect_args={"connect_timeout": 30},
    echo=False,
)
Session = sessionmaker(bind=engine)


# â”€â”€ Helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def nullify(val):
    """Return None for empty strings and the literal string 'null'."""
    if val in ("", "null", "NULL", None):
        return None
    return val


def to_bool(val):
    if val is None:
        return None
    return str(val).lower() in ("true", "1", "yes", "t")


def to_int(val):
    v = nullify(val)
    if v is None:
        return None
    return int(v)


def to_float(val):
    v = nullify(val)
    if v is None:
        return None
    return float(v)


def to_uuid(val):
    v = nullify(val)
    if v is None:
        return None
    return str(uuid.UUID(v))  # normalise to canonical UUID string


def to_json(val):
    v = nullify(val)
    if v is None:
        return None
    try:
        return json.loads(v)
    except Exception:
        return v  # store as plain string if not valid JSON


def read_csv(filename):
    path = DATA_DIR / filename
    if not path.exists():
        print(f"  [SKIP] {filename} not found in {DATA_DIR}")
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def run(conn, sql, params=None):
    conn.execute(text(sql), params or {})


# â”€â”€ Step 1: Create all tables via SQLAlchemy ORM â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def create_tables():
    print("\n[1/3] Creating tables via SQLAlchemy models...")

    # Import all models in dependency order so they register with Base.metadata
    from app.database import Base
    from app.models import settings as _settings              # noqa  (no FKs)
    from app.models import audit_log as _audit                # noqa  (no FKs)
    from app.models import marketing as _marketing            # noqa  (FK to users - lazy ref)
    from app.models.meal_tier import MealTier                 # noqa  (must be before menu)
    from app.models import menu as _menu                      # noqa  (FK to meal_tiers)
    from app.models import custom_request as _custom          # noqa  (FK to meal_tiers + users)
    from app.models.user import User                          # noqa  (no external FKs)
    from app.models.subscription import Subscription          # noqa  (FK to users + plan_templates)
    from app.models import credit as _credit                  # noqa  (FK to users + subscriptions)
    from app.models import delivery as _delivery              # noqa  (FK to users + subscriptions)

    Base.metadata.create_all(bind=engine)
    print("  All tables created / verified.")


# â”€â”€ Step 2: Migrate data â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def migrate_meal_tiers(conn):
    """query-results (13).csv â†’ meal_tiers"""
    rows = read_csv("query-results (13).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into meal_tiers...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO meal_tiers (
                id, name, slug, display_order, diet_support,
                delivery_charge_weekly, delivery_charge_monthly,
                is_active, is_featured, created_at, updated_at,
                price_per_meal, diet_type,
                weekly_delivery_charge, monthly_delivery_charge, description
            ) VALUES (
                :id, :name, :slug, :display_order, :diet_support,
                :delivery_charge_weekly, :delivery_charge_monthly,
                :is_active, :is_featured, :created_at, :updated_at,
                :price_per_meal, :diet_type,
                :weekly_delivery_charge, :monthly_delivery_charge, :description
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":                       to_uuid(r["id"]),
            "name":                     r["name"],
            "slug":                     nullify(r["slug"]),
            "display_order":            to_int(r["display_order"]) or 0,
            "diet_support":             nullify(r.get("diet_support")) or "both",
            "delivery_charge_weekly":   to_float(r.get("delivery_charge_weekly")) or 10.0,
            "delivery_charge_monthly":  to_float(r.get("delivery_charge_monthly")) or 0.0,
            "is_active":                to_bool(r.get("is_active", "true")),
            "is_featured":              to_bool(r.get("is_featured", "false")),
            "created_at":               nullify(r.get("created_at")),
            "updated_at":               nullify(r.get("updated_at")),
            "price_per_meal":           to_float(r.get("price_per_meal")),
            "diet_type":                nullify(r.get("diet_type")),
            "weekly_delivery_charge":   to_float(r.get("weekly_delivery_charge")),
            "monthly_delivery_charge":  to_float(r.get("monthly_delivery_charge")),
            "description":              nullify(r.get("description")),
        })
    print(f"  âœ“ meal_tiers done.")


def migrate_tier_pricing(conn):
    """query-results (16).csv â†’ tier_pricing"""
    rows = read_csv("query-results (16).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into tier_pricing...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO tier_pricing (id, tier_id, diet_type, price_per_meal, is_active, effective_from, created_at)
            VALUES (:id, :tier_id, :diet_type, :price_per_meal, :is_active, :effective_from, :created_at)
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":             to_uuid(r["id"]),
            "tier_id":        to_uuid(r["tier_id"]),
            "diet_type":      r["diet_type"],
            "price_per_meal": to_float(r["price_per_meal"]),
            "is_active":      to_bool(r.get("is_active", "true")),
            "effective_from": nullify(r.get("effective_from")),
            "created_at":     nullify(r.get("created_at")),
        })
    print(f"  âœ“ tier_pricing done.")


def migrate_plan_templates(conn):
    """query-results (3).csv â†’ plan_templates"""
    rows = read_csv("query-results (3).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into plan_templates...")
    for r in rows:
        # meal_slots is stored as a PostgreSQL array text in the CSV (or null)
        meal_slots_raw = nullify(r.get("meal_slots"))
        # Convert CSV array-like string to a proper list for SQLAlchemy
        # The CSV might have values like '["breakfast_only"]'
        meal_slots = None
        if meal_slots_raw:
            try:
                meal_slots = json.loads(meal_slots_raw)
            except Exception:
                meal_slots = [meal_slots_raw]

        conn.execute(text("""
            INSERT INTO plan_templates (
                id, name, tier_id, diet_type, duration, meal_slots,
                meals_per_slot, total_meals, price, delivery_charge,
                is_active, slot_combo, meal_count, is_legacy
            ) VALUES (
                :id, :name, :tier_id, :diet_type, :duration, :meal_slots,
                :meals_per_slot, :total_meals, :price, :delivery_charge,
                :is_active, :slot_combo, :meal_count, :is_legacy
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":              to_uuid(r["id"]),
            "name":            nullify(r.get("name")) or "",
            "tier_id":         to_uuid(r["tier_id"]),
            "diet_type":       r["diet_type"],
            "duration":        nullify(r.get("duration")),
            "meal_slots":      meal_slots,
            "meals_per_slot":  to_int(r.get("meals_per_slot")),
            "total_meals":     to_int(r.get("total_meals")),
            "price":           to_float(r.get("price")),
            "delivery_charge": to_float(r.get("delivery_charge")),
            "is_active":       to_bool(r.get("is_active", "true")),
            "slot_combo":      nullify(r.get("slot_combo")),
            "meal_count":      to_int(r.get("meal_count")),
            "is_legacy":       to_bool(r.get("is_legacy", "false")),
        })
    print(f"  âœ“ plan_templates done.")


def migrate_users(conn):
    """query-results (1).csv â†’ users"""
    rows = read_csv("query-results (1).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into users...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO users (
                id, full_name, email, phone,
                address_line_1, address_line_2, landmark, location_link,
                latitude, longitude,
                hashed_password, role,
                reset_otp, reset_otp_expires,
                email_verified, email_verification_token,
                notif_delivery, notif_subscriptions, notif_offers,
                created_at, is_active
            ) VALUES (
                :id, :full_name, :email, :phone,
                :address_line_1, :address_line_2, :landmark, :location_link,
                :latitude, :longitude,
                :hashed_password, :role,
                :reset_otp, :reset_otp_expires,
                :email_verified, :email_verification_token,
                :notif_delivery, :notif_subscriptions, :notif_offers,
                :created_at, :is_active
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":                       to_int(r["id"]),
            "full_name":                nullify(r.get("full_name")),
            "email":                    r["email"],
            "phone":                    nullify(r.get("phone")),
            "address_line_1":           nullify(r.get("address_line_1")),
            "address_line_2":           nullify(r.get("address_line_2")),
            "landmark":                 nullify(r.get("landmark")),
            "location_link":            nullify(r.get("location_link")),
            "latitude":                 to_float(r.get("latitude")),
            "longitude":                to_float(r.get("longitude")),
            "hashed_password":          r["hashed_password"],
            "role":                     r.get("role", "customer"),
            "reset_otp":                nullify(r.get("reset_otp")),
            "reset_otp_expires":        nullify(r.get("reset_otp_expires")),
            "email_verified":           to_bool(r.get("email_verified", "false")),
            "email_verification_token": nullify(r.get("email_verification_token")),
            "notif_delivery":           to_bool(r.get("notif_delivery", "true")),
            "notif_subscriptions":      to_bool(r.get("notif_subscriptions", "true")),
            "notif_offers":             to_bool(r.get("notif_offers", "false")),
            "created_at":               nullify(r.get("created_at")),
            "is_active":                to_bool(r.get("is_active", "true")),
        })
    print(f"  âœ“ users done.")


def migrate_subscriptions(conn):
    """query-results (4).csv â†’ subscriptions"""
    rows = read_csv("query-results (4).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into subscriptions...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO subscriptions (
                id, customer_id, menu_id, start_date, end_date,
                price_per_meal_snapshot, razorpay_order_id, razorpay_payment_id,
                customization_details, diet_type, slot_combo
            ) VALUES (
                :id, :customer_id, :menu_id, :start_date, :end_date,
                :price_per_meal_snapshot, :razorpay_order_id, :razorpay_payment_id,
                :customization_details, :diet_type, :slot_combo
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":                    to_int(r["id"]),
            "customer_id":           to_int(r.get("customer_id")),
            "menu_id":               to_uuid(r.get("menu_id")),
            "start_date":            nullify(r.get("start_date")),
            "end_date":              nullify(r.get("end_date")),
            "price_per_meal_snapshot": to_float(r.get("price_per_meal_snapshot")),
            "razorpay_order_id":     nullify(r.get("razorpay_order_id")),
            "razorpay_payment_id":   nullify(r.get("razorpay_payment_id")),
            "customization_details": nullify(r.get("customization_details")),
            "diet_type":             nullify(r.get("diet_type")),
            "slot_combo":            nullify(r.get("slot_combo")),
        })
    print(f"  âœ“ subscriptions done.")


def migrate_delivery_sessions(conn):
    """query-results (10).csv â†’ delivery_sessions"""
    rows = read_csv("query-results (10).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into delivery_sessions...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO delivery_sessions (id, name, slug, display_order, is_active, created_at)
            VALUES (:id, :name, :slug, :display_order, :is_active, :created_at)
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":            to_int(r["id"]),
            "name":          r["name"],
            "slug":          r["slug"],
            "display_order": to_int(r.get("display_order")) or 0,
            "is_active":     to_bool(r.get("is_active", "true")),
            "created_at":    nullify(r.get("created_at")),
        })
    print(f"  âœ“ delivery_sessions done.")


def migrate_delivery_assignments(conn):
    """query-results (9).csv â†’ delivery_assignments"""
    rows = read_csv("query-results (9).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into delivery_assignments...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO delivery_assignments (
                id, subscription_id, customer_id, driver_id, session_id,
                delivery_date, status, assigned_at, started_at, delivered_at
            ) VALUES (
                :id, :subscription_id, :customer_id, :driver_id, :session_id,
                :delivery_date, :status, :assigned_at, :started_at, :delivered_at
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":              to_int(r["id"]),
            "subscription_id": to_int(r.get("subscription_id")),
            "customer_id":     to_int(r.get("customer_id")),
            "driver_id":       to_int(r.get("driver_id")),
            "session_id":      to_int(r.get("session_id")),
            "delivery_date":   nullify(r.get("delivery_date")),
            "status":          r.get("status", "assigned"),
            "assigned_at":     nullify(r.get("assigned_at")),
            "started_at":      nullify(r.get("started_at")),
            "delivered_at":    nullify(r.get("delivered_at")),
        })
    print(f"  âœ“ delivery_assignments done.")


def migrate_delivery_tracking(conn):
    """query-results (11).csv â†’ delivery_tracking"""
    rows = read_csv("query-results (11).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into delivery_tracking...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO delivery_tracking (
                id, assignment_id, driver_id, latitude, longitude, recorded_at, synced_at
            ) VALUES (
                :id, :assignment_id, :driver_id, :latitude, :longitude, :recorded_at, :synced_at
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":            to_int(r["id"]),
            "assignment_id": to_int(r["assignment_id"]),
            "driver_id":     to_int(r.get("driver_id")),
            "latitude":      to_float(r["latitude"]),
            "longitude":     to_float(r["longitude"]),
            "recorded_at":   nullify(r.get("recorded_at")),
            "synced_at":     nullify(r.get("synced_at")),
        })
    print(f"  âœ“ delivery_tracking done.")


def migrate_app_settings(conn):
    """query-results (6).csv â†’ app_settings"""
    rows = read_csv("query-results (6).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into app_settings...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO app_settings (
                id, business_name, address, phone_number, email, city, instagram_link,
                opens_at, closes_at, timezone,
                notif_new_order, notif_credit_earned, notif_payment_fail, notif_new_customer,
                notif_cust_credit, notif_cust_reminder, notif_cust_order_sms, notif_cust_delivery,
                payment_gateway, payment_api_key, payment_api_secret,
                payment_cod_enabled, payment_upi_enabled,
                gst_rate, gstin,
                credit_cutoff_hours, credit_delivery_delay, credit_max_per_plan,
                credit_deliver_no_renew, credit_of_credit
            ) VALUES (
                :id, :business_name, :address, :phone_number, :email, :city, :instagram_link,
                :opens_at, :closes_at, :timezone,
                :notif_new_order, :notif_credit_earned, :notif_payment_fail, :notif_new_customer,
                :notif_cust_credit, :notif_cust_reminder, :notif_cust_order_sms, :notif_cust_delivery,
                :payment_gateway, :payment_api_key, :payment_api_secret,
                :payment_cod_enabled, :payment_upi_enabled,
                :gst_rate, :gstin,
                :credit_cutoff_hours, :credit_delivery_delay, :credit_max_per_plan,
                :credit_deliver_no_renew, :credit_of_credit
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":                    to_int(r["id"]),
            "business_name":         nullify(r.get("business_name")),
            "address":               nullify(r.get("address")),
            "phone_number":          nullify(r.get("phone_number")),
            "email":                 nullify(r.get("email")),
            "city":                  nullify(r.get("city")),
            "instagram_link":        nullify(r.get("instagram_link")),
            "opens_at":              nullify(r.get("opens_at")),
            "closes_at":             nullify(r.get("closes_at")),
            "timezone":              nullify(r.get("timezone")),
            "notif_new_order":       to_bool(r.get("notif_new_order", "true")),
            "notif_credit_earned":   to_bool(r.get("notif_credit_earned", "true")),
            "notif_payment_fail":    to_bool(r.get("notif_payment_fail", "true")),
            "notif_new_customer":    to_bool(r.get("notif_new_customer", "false")),
            "notif_cust_credit":     to_bool(r.get("notif_cust_credit", "true")),
            "notif_cust_reminder":   to_bool(r.get("notif_cust_reminder", "true")),
            "notif_cust_order_sms":  to_bool(r.get("notif_cust_order_sms", "true")),
            "notif_cust_delivery":   to_bool(r.get("notif_cust_delivery", "true")),
            "payment_gateway":       nullify(r.get("payment_gateway")),
            "payment_api_key":       nullify(r.get("payment_api_key")),
            "payment_api_secret":    nullify(r.get("payment_api_secret")),
            "payment_cod_enabled":   to_bool(r.get("payment_cod_enabled", "true")),
            "payment_upi_enabled":   to_bool(r.get("payment_upi_enabled", "true")),
            "gst_rate":              to_float(r.get("gst_rate")) or 5.0,
            "gstin":                 nullify(r.get("gstin")),
            "credit_cutoff_hours":   to_int(r.get("credit_cutoff_hours")) or 6,
            "credit_delivery_delay": to_int(r.get("credit_delivery_delay")) or 1,
            "credit_max_per_plan":   to_int(r.get("credit_max_per_plan")) or 0,
            "credit_deliver_no_renew": to_bool(r.get("credit_deliver_no_renew", "true")),
            "credit_of_credit":      to_bool(r.get("credit_of_credit", "false")),
        })
    print(f"  âœ“ app_settings done.")


def migrate_audit_logs(conn):
    """query-results (7).csv â†’ audit_logs"""
    rows = read_csv("query-results (7).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into audit_logs...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO audit_logs (id, actor_id, actor_email, action, target_type, target_id, details, created_at)
            VALUES (:id, :actor_id, :actor_email, :action, :target_type, :target_id, :details, :created_at)
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":          to_int(r["id"]),
            "actor_id":    to_int(r.get("actor_id")),
            "actor_email": nullify(r.get("actor_email")),
            "action":      r["action"],
            "target_type": nullify(r.get("target_type")),
            "target_id":   nullify(r.get("target_id")),
            "details":     json.dumps(to_json(r.get("details"))) if to_json(r.get("details")) is not None else None,
            "created_at":  nullify(r.get("created_at")),
        })
    print(f"  âœ“ audit_logs done.")


def migrate_custom_plan_requests(conn):
    """query-results (8).csv â†’ custom_plan_requests"""
    rows = read_csv("query-results (8).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into custom_plan_requests...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO custom_plan_requests (
                id, customer_id, base_tier_id, diet_type, slot_combo, duration,
                custom_requirements, status, quoted_price_per_meal, quoted_delivery_charge,
                created_at, updated_at
            ) VALUES (
                :id, :customer_id, :base_tier_id, :diet_type, :slot_combo, :duration,
                :custom_requirements, :status, :quoted_price_per_meal, :quoted_delivery_charge,
                :created_at, :updated_at
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":                    to_uuid(r["id"]),
            "customer_id":           to_int(r["customer_id"]),
            "base_tier_id":          to_uuid(r.get("base_tier_id")),
            "diet_type":             r["diet_type"],
            "slot_combo":            r["slot_combo"],
            "duration":              r["duration"],
            "custom_requirements":   r["custom_requirements"],
            "status":                r.get("status", "pending"),
            "quoted_price_per_meal": to_float(r.get("quoted_price_per_meal")),
            "quoted_delivery_charge": to_float(r.get("quoted_delivery_charge")),
            "created_at":            nullify(r.get("created_at")),
            "updated_at":            nullify(r.get("updated_at")),
        })
    print(f"  âœ“ custom_plan_requests done.")


def migrate_gallery_images(conn):
    """query-results (12).csv â†’ gallery_images"""
    rows = read_csv("query-results (12).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into gallery_images...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO gallery_images (id, image_url, caption, sort_order, created_at)
            VALUES (:id, :image_url, :caption, :sort_order, :created_at)
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":         to_int(r["id"]),
            "image_url":  r["image_url"],
            "caption":    nullify(r.get("caption")),
            "sort_order": to_int(r.get("sort_order")) or 0,
            "created_at": nullify(r.get("created_at")),
        })
    print(f"  âœ“ gallery_images done.")


def migrate_offers(conn):
    """query-results (14).csv â†’ offers"""
    rows = read_csv("query-results (14).csv")
    if not rows:
        return
    print(f"  Inserting {len(rows)} rows into offers...")
    for r in rows:
        conn.execute(text("""
            INSERT INTO offers (
                id, code, description, type, value, max_cap, min_order,
                usage_limit, used_count, valid_from, valid_until, status, created_at, audience
            ) VALUES (
                :id, :code, :description, :type, :value, :max_cap, :min_order,
                :usage_limit, :used_count, :valid_from, :valid_until, :status, :created_at, :audience
            )
            ON CONFLICT (id) DO NOTHING
        """), {
            "id":          to_int(r["id"]),
            "code":        r["code"],
            "description": r["description"],
            "type":        r["type"],
            "value":       to_int(r.get("value")) or 0,
            "max_cap":     to_int(r.get("max_cap")),
            "min_order":   to_int(r.get("min_order")) or 0,
            "usage_limit": to_int(r.get("usage_limit")),
            "used_count":  to_int(r.get("used_count")) or 0,
            "valid_from":  nullify(r.get("valid_from")),
            "valid_until": nullify(r.get("valid_until")),
            "status":      r.get("status", "active"),
            "created_at":  nullify(r.get("created_at")),
            "audience":    r.get("audience", "all"),
        })
    print(f"  [OK] offers done.")


def migrate_alembic_version(conn):
    """query-results (5).csv -> alembic_version"""
    # Create alembic_version table if it doesn't exist (SQLAlchemy create_all doesn't manage it)
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL,
            CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
        )
    """))
    rows = read_csv("query-results (5).csv")
    if not rows:
        return
    print(f"  Inserting alembic_version...")
    for r in rows:
        version = nullify(r.get("version_num"))
        if version:
            conn.execute(text("""
                INSERT INTO alembic_version (version_num)
                VALUES (:version_num)
                ON CONFLICT (version_num) DO NOTHING
            """), {"version_num": version})
    print(f"  [OK] alembic_version done.")


def reset_sequences(conn):
    """Reset PostgreSQL sequences for integer PK tables so new inserts don't conflict."""
    print("\n  Resetting sequences...")
    int_pk_tables = [
        ("users", "users_id_seq"),
        ("subscriptions", "subscriptions_id_seq"),
        ("delivery_sessions", "delivery_sessions_id_seq"),
        ("delivery_assignments", "delivery_assignments_id_seq"),
        ("delivery_tracking", "delivery_tracking_id_seq"),
        ("audit_logs", "audit_logs_id_seq"),
        ("app_settings", "app_settings_id_seq"),
        ("gallery_images", "gallery_images_id_seq"),
        ("offers", "offers_id_seq"),
    ]
    for table, seq in int_pk_tables:
        try:
            conn.execute(text(f"""
                SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 1))
            """))
            print(f"    âœ“ {seq} reset")
        except Exception as e:
            print(f"    [WARN] Could not reset {seq}: {e}")


# â”€â”€ Main â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def main():
    print("=" * 60)
    print("  Nutribox -> Supabase Migration Script")
    print("=" * 60)
    print(f"  Database: {DATABASE_URL[:50]}...")
    print(f"  Data dir: {DATA_DIR}")

    # Step 1: Create tables
    create_tables()

    # Step 2: Migrate data in dependency order
    print("\n[2/3] Migrating data...")
    with engine.begin() as conn:
        # Independent tables first
        migrate_meal_tiers(conn)
        migrate_tier_pricing(conn)
        migrate_plan_templates(conn)
        migrate_users(conn)
        migrate_delivery_sessions(conn)
        migrate_app_settings(conn)
        migrate_audit_logs(conn)
        migrate_gallery_images(conn)
        migrate_offers(conn)
        migrate_alembic_version(conn)

        # Tables with FK dependencies
        migrate_subscriptions(conn)
        migrate_custom_plan_requests(conn)
        migrate_delivery_assignments(conn)
        migrate_delivery_tracking(conn)

        # Reset sequences so future inserts get correct IDs
        reset_sequences(conn)

    # Step 3: Verify
    print("\n[3/3] Verification...")
    with engine.connect() as conn:
        tables = [
            "users", "meal_tiers", "tier_pricing", "plan_templates",
            "subscriptions", "delivery_sessions", "delivery_assignments",
            "delivery_tracking", "app_settings", "audit_logs",
            "gallery_images", "offers", "custom_plan_requests",
            "announcements", "credits", "delivery_cancellations",
            "driver_status", "weekly_menu_images", "reviews",
        ]
        for t in tables:
            try:
                result = conn.execute(text(f"SELECT COUNT(*) FROM {t}"))
                count = result.scalar()
                print(f"  {t:35s}: {count} rows")
            except Exception as e:
                print(f"  {t:35s}: ERROR â€” {e}")

    print("\nâœ… Migration complete!")


if __name__ == "__main__":
    main()


