"""
Nutribox Menu Management Redesign — Migration Script
Run once. Safe to re-run (idempotent checks before each step).

Steps:
1. Add new columns to meal_tiers (skip if already exist)
2. Create tier_pricing table (skip if exists)
3. Create weekly_menu_images table (skip if exists)
4. Add new columns to plan_templates (skip if already exist)
5. Update subscriptions table (skip if column already exists)
6. Seed tier slugs/display_order/diet_support for the 4 canonical tiers
7. Seed tier_pricing rows with initial prices
8. Seed canonical plan combinations (all valid combos) for all tiers
9. Migrate existing weekly_menus rows → weekly_menu_images (if table exists)
10. Mark all existing non-seeded plan_templates rows as is_legacy=True
11. Print summary report
"""

import os
import sys
import uuid
from datetime import date, timedelta
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

load_dotenv()

from app.database import engine
from sqlalchemy import text, inspect


def column_exists(inspector, table: str, col: str) -> bool:
    try:
        cols = [c['name'] for c in inspector.get_columns(table)]
        return col in cols
    except Exception:
        return False


def table_exists(conn, table: str) -> bool:
    result = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = :t)"
    ), {"t": table}).scalar()
    return bool(result)


def run_migration():
    print("=" * 60)
    print("  Nutribox Menu Management Redesign Migration")
    print("=" * 60)

    tiers_seeded = 0
    pricing_created = 0
    combos_seeded = 0
    images_migrated = 0

    with engine.connect() as conn:
        inspector = inspect(engine)

        # ── Step 1: Modify meal_tiers ──────────────────────────────────
        print("\n[Step 1] Modifying meal_tiers table...")
        new_cols = {
            "slug":                   "VARCHAR(100)",
            "display_order":          "INTEGER DEFAULT 0",
            "diet_support":           "VARCHAR(20) DEFAULT 'both'",
            "delivery_charge_weekly": "NUMERIC(8,2) DEFAULT 10.00",
            "delivery_charge_monthly":"NUMERIC(8,2) DEFAULT 0.00",
            "is_active":              "BOOLEAN DEFAULT TRUE",
        }
        for col, col_type in new_cols.items():
            if not column_exists(inspector, 'meal_tiers', col):
                print(f"  Adding column '{col}'...")
                conn.execute(text(f"ALTER TABLE meal_tiers ADD COLUMN {col} {col_type}"))
            else:
                print(f"  Column '{col}' already exists, skipping.")

        # Add UNIQUE constraint on slug if not there
        try:
            conn.execute(text("ALTER TABLE meal_tiers ADD CONSTRAINT uq_meal_tiers_slug UNIQUE (slug)"))
            print("  Added UNIQUE constraint on slug.")
        except Exception:
            print("  UNIQUE constraint on slug already exists.")

        conn.commit()

        # ── Step 2: Create tier_pricing ────────────────────────────────
        print("\n[Step 2] Creating tier_pricing table...")
        if not table_exists(conn, 'tier_pricing'):
            conn.execute(text("""
                CREATE TABLE tier_pricing (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tier_id UUID NOT NULL REFERENCES meal_tiers(id) ON DELETE CASCADE,
                    diet_type VARCHAR(10) NOT NULL CHECK (diet_type IN ('veg', 'nonveg')),
                    price_per_meal NUMERIC(8,2) NOT NULL,
                    is_active BOOLEAN DEFAULT TRUE,
                    effective_from DATE NOT NULL DEFAULT CURRENT_DATE,
                    created_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_tier_pricing_tier_diet_date UNIQUE (tier_id, diet_type, effective_from)
                )
            """))
            print("  Created tier_pricing table.")
        else:
            print("  tier_pricing table already exists, skipping.")
        conn.commit()

        # ── Step 3: Create weekly_menu_images ─────────────────────────
        print("\n[Step 3] Creating weekly_menu_images table...")
        if not table_exists(conn, 'weekly_menu_images'):
            conn.execute(text("""
                CREATE TABLE weekly_menu_images (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    tier_id UUID NOT NULL REFERENCES meal_tiers(id) ON DELETE CASCADE,
                    diet_type VARCHAR(10) NOT NULL CHECK (diet_type IN ('veg', 'nonveg', 'both')),
                    week_start_date DATE NOT NULL,
                    image_url TEXT NOT NULL,
                    uploaded_at TIMESTAMP DEFAULT NOW(),
                    CONSTRAINT uq_weekly_menu_images_tier_diet_date UNIQUE (tier_id, diet_type, week_start_date)
                )
            """))
            print("  Created weekly_menu_images table.")
        else:
            print("  weekly_menu_images table already exists, skipping.")
        conn.commit()

        # ── Step 4: Modify plan_templates ─────────────────────────────
        print("\n[Step 4] Modifying plan_templates table...")

        # Drop NOT NULL constraints on legacy columns that may not exist
        for col in ['meal_slots', 'total_meals', 'price', 'delivery_charge']:
            if column_exists(inspector, 'plan_templates', col):
                try:
                    conn.execute(text(f"ALTER TABLE plan_templates ALTER COLUMN {col} DROP NOT NULL"))
                except Exception:
                    pass

        new_plan_cols = {
            "slot_combo": "VARCHAR(20)",
            "duration":   "VARCHAR(10)",
            "meal_count": "INTEGER",
            "is_active":  "BOOLEAN DEFAULT TRUE",
            "is_legacy":  "BOOLEAN DEFAULT FALSE",
        }
        for col, col_type in new_plan_cols.items():
            if not column_exists(inspector, 'plan_templates', col):
                print(f"  Adding column '{col}'...")
                conn.execute(text(f"ALTER TABLE plan_templates ADD COLUMN {col} {col_type}"))
            else:
                print(f"  Column '{col}' already exists, skipping.")

        conn.commit()

        # ── Step 5: Update subscriptions ──────────────────────────────
        print("\n[Step 5] Updating subscriptions table...")
        if table_exists(conn, 'subscriptions') and not column_exists(inspector, 'subscriptions', 'price_per_meal_snapshot'):
            conn.execute(text("ALTER TABLE subscriptions ADD COLUMN price_per_meal_snapshot NUMERIC(8,2)"))
            print("  Added price_per_meal_snapshot column.")
        else:
            print("  price_per_meal_snapshot column already exists or subscriptions table missing.")
        conn.commit()

        # Re-inspect after schema changes
        inspector = inspect(engine)

        # ── Step 6: Seed tier data ─────────────────────────────────────
        print("\n[Step 6] Seeding canonical meal_tiers data...")
        tiers_to_seed = [
            ("Classic",      "classic",      1, "both",     10.00, 0.00),
            ("Premium",      "premium",      2, "both",     10.00, 0.00),
            ("Protein Rich", "protein_rich", 3, "both",     10.00, 0.00),
            ("Fruits Bowl",  "fruits_bowl",  4, "veg_only", 10.00, 0.00),
        ]

        tier_id_map = {}  # name -> canonical id

        for name, slug, order, diet, d_weekly, d_monthly in tiers_to_seed:
            rows = conn.execute(text("SELECT id FROM meal_tiers WHERE name = :name"), {"name": name}).fetchall()

            if not rows:
                # Create new tier
                new_id = str(uuid.uuid4())
                conn.execute(text("""
                    INSERT INTO meal_tiers (id, name, slug, display_order, diet_support,
                        delivery_charge_weekly, delivery_charge_monthly, is_active)
                    VALUES (:id, :name, :slug, :order, :diet, :dw, :dm, TRUE)
                    ON CONFLICT DO NOTHING
                """), {"id": new_id, "name": name, "slug": slug, "order": order,
                       "diet": diet, "dw": d_weekly, "dm": d_monthly})
                tier_id_map[name] = new_id
                print(f"  Created tier '{name}' (slug: {slug})")
                tiers_seeded += 1
            else:
                # Pick canonical (prefer one with plan_templates refs)
                target_id = None
                for row in rows:
                    tid = str(row[0])
                    plan_count = conn.execute(
                        text("SELECT count(*) FROM plan_templates WHERE tier_id = :id"), {"id": tid}
                    ).scalar() or 0
                    if plan_count > 0:
                        target_id = tid
                        break
                if not target_id:
                    target_id = str(rows[0][0])

                conn.execute(text("""
                    UPDATE meal_tiers
                    SET slug = :slug, display_order = :order, diet_support = :diet,
                        delivery_charge_weekly = :dw, delivery_charge_monthly = :dm, is_active = TRUE
                    WHERE id = :id
                """), {"slug": slug, "order": order, "diet": diet, "dw": d_weekly, "dm": d_monthly, "id": target_id})

                # Delete duplicates
                for row in rows:
                    if str(row[0]) != target_id:
                        print(f"  Deleting duplicate tier '{name}' (id: {row[0]})...")
                        conn.execute(text("DELETE FROM meal_tiers WHERE id = :id"), {"id": str(row[0])})

                tier_id_map[name] = target_id
                print(f"  Updated tier '{name}' (slug={slug}, id={target_id})")
                tiers_seeded += 1

        conn.commit()

        # ── Step 7: Seed tier_pricing ─────────────────────────────────
        print("\n[Step 7] Seeding tier_pricing rows...")
        pricing_data = [
            ("Classic",      "veg",    95.00),
            ("Classic",      "nonveg", 95.00),
            ("Premium",      "veg",    115.00),
            ("Premium",      "nonveg", 115.00),
            ("Protein Rich", "veg",    140.00),
            ("Protein Rich", "nonveg", 140.00),
            ("Fruits Bowl",  "veg",    140.00),
        ]

        for tier_name, diet_type, price in pricing_data:
            tid = tier_id_map.get(tier_name)
            if not tid:
                tid = conn.execute(
                    text("SELECT id FROM meal_tiers WHERE name = :name"), {"name": tier_name}
                ).scalar()
            if tid:
                result = conn.execute(text("""
                    INSERT INTO tier_pricing (tier_id, diet_type, price_per_meal, effective_from, is_active)
                    VALUES (:tier_id, :diet_type, :price, '2025-01-01', TRUE)
                    ON CONFLICT ON CONSTRAINT uq_tier_pricing_tier_diet_date DO NOTHING
                """), {"tier_id": str(tid), "diet_type": diet_type, "price": price})
                if result.rowcount > 0:
                    print(f"  Seeded: {tier_name} / {diet_type} = Rs.{price}")
                    pricing_created += 1
                else:
                    print(f"  Already exists: {tier_name} / {diet_type}")

        conn.commit()


        # ── Step 8: Seed plan combinations ────────────────────────────
        print("\n[Step 8] Seeding canonical plan combinations...")
        MEAL_COUNT_MAP = {
            ('breakfast_only', 'weekly'):   6,
            ('dinner_only',    'weekly'):   6,
            ('both',           'weekly'):  12,
            ('breakfast_only', 'monthly'): 24,
            ('dinner_only',    'monthly'): 24,
            ('both',           'monthly'): 48,
        }

        canonical_slugs = ['classic', 'premium', 'protein_rich', 'fruits_bowl']
        all_tiers = conn.execute(
            text("SELECT id, name, diet_support FROM meal_tiers WHERE slug = ANY(:slugs)"),
            {"slugs": canonical_slugs}
        ).fetchall()

        for tier_row in all_tiers:
            tid   = str(tier_row[0])
            tname = tier_row[1]
            dsup  = tier_row[2] or 'both'

            if dsup == 'veg_only':
                diets = ['veg']
            elif dsup == 'nonveg_only':
                diets = ['nonveg']
            else:
                diets = ['veg', 'nonveg']

            for diet in diets:
                for (combo, duration), count in MEAL_COUNT_MAP.items():
                    result = conn.execute(text("""
                        INSERT INTO plan_templates
                            (id, tier_id, diet_type, slot_combo, duration, meal_count,
                             is_active, is_legacy, name)
                        VALUES
                            (gen_random_uuid(), :tier_id, :diet, :combo, :duration, :count,
                             TRUE, FALSE, '')
                        ON CONFLICT DO NOTHING
                    """), {"tier_id": tid, "diet": diet, "combo": combo,
                           "duration": duration, "count": count})
                    if result.rowcount > 0:
                        combos_seeded += 1

        print(f"  Seeded {combos_seeded} new plan combinations.")
        conn.commit()

        # ── Step 9: Migrate weekly_menus → weekly_menu_images ─────────
        print("\n[Step 9] Migrating weekly_menus → weekly_menu_images...")
        if table_exists(conn, 'weekly_menus'):
            old_menus = conn.execute(
                text("SELECT tier_id, menu_date, image_url FROM weekly_menus")
            ).fetchall()
            for menu in old_menus:
                d = menu[1]
                monday = d - timedelta(days=d.weekday())
                result = conn.execute(text("""
                    INSERT INTO weekly_menu_images (tier_id, diet_type, week_start_date, image_url)
                    VALUES (:tier_id, 'both', :monday, :image_url)
                    ON CONFLICT ON CONSTRAINT uq_weekly_menu_images_tier_diet_date DO NOTHING
                """), {"tier_id": str(menu[0]), "monday": monday, "image_url": menu[2]})
                if result.rowcount > 0:
                    images_migrated += 1
            print(f"  Migrated {images_migrated} images from weekly_menus.")
        else:
            print("  weekly_menus table not found, skipping migration.")
        conn.commit()

        # ── Step 10: Mark legacy plan_templates ───────────────────────
        print("\n[Step 10] Marking legacy plan_templates rows...")
        result = conn.execute(text(
            "UPDATE plan_templates SET is_legacy = TRUE WHERE slot_combo IS NULL"
        ))
        print(f"  Marked {result.rowcount} rows as legacy.")
        conn.commit()

        # ── Summary ────────────────────────────────────────────────────
        print("\n" + "=" * 60)
        print("  MIGRATION COMPLETE ✓")
        print("=" * 60)
        print(f"  Tiers processed:        {tiers_seeded}")
        print(f"  Pricing rows created:   {pricing_created}")
        print(f"  Plan combos seeded:     {combos_seeded}")
        print(f"  Images migrated:        {images_migrated}")
        print("=" * 60)


if __name__ == "__main__":
    run_migration()
