# Backend Scripts

One-off and maintenance scripts for the Nutribox backend. These are **not part of the FastAPI application** and should be run directly with Python from the `backend/` directory.

> **Always activate the virtual environment first:**
> ```bash
> cd backend
> venv\Scripts\activate   # Windows
> source venv/bin/activate # Mac/Linux
> ```

---

## 📁 migrations/
Database schema migration and cleanup scripts. Run these **in order** when setting up a fresh database or applying schema changes.

| Script | Purpose |
|---|---|
| `migrate_menu_redesign.py` | Creates `meal_tiers`, `tier_pricing`, `weekly_menu_images`, `plan_templates` tables |
| `migrate_credits_v2.py` | Creates `credits` and `delivery_cancellations` tables (v2 schema) |
| `migrate_diet_column.py` | Adds `diet_type` column to existing plan tables |
| `migrate_meals_per_slot.py` | Adds `meals_per_slot` column |
| `migrate_name_column.py` | Adds `name` column to relevant tables |
| `migrate_weekly_menus.py` | Seeds initial weekly menu image structure |
| `drop_legacy_tables.py` | Drops old `menu_master`, `dishes` tables (non-destructive check first) |
| `drop_tables.py` | Nuclear option — drops all Nutribox tables. **Use with caution!** |

```bash
python scripts/migrations/migrate_menu_redesign.py
```

---

## 📁 checks/
Diagnostic scripts to inspect the live database schema and data. Safe to run at any time — read-only.

| Script | Purpose |
|---|---|
| `check_db_structure.py` | Lists all tables and column names |
| `check_columns.py` | Checks specific column presence |
| `check_credits_schema.py` | Validates the credits table schema |
| `check_references.py` | Checks FK references and joins |
| `check_tiers.py` | Lists all tiers in the database |
| `check_tiers_columns.py` | Checks tier table column structure |
| `list_tables.py` | Shows all tables in the Supabase DB |
| `verify_weekly_menus.py` | Checks weekly menu image coverage |

```bash
python scripts/checks/list_tables.py
```

---

## 📁 setup/
One-time setup scripts for initializing admin users and seed data.

| Script | Purpose |
|---|---|
| `create_admin.py` | Creates the first admin user account |
| `seed_plans.py` | Seeds default meal tier and plan combination data |

```bash
python scripts/setup/create_admin.py
python scripts/setup/seed_plans.py
```

---

## 📁 tests/ (backend root)
Quick API smoke tests and integration checks.

| Script | Purpose |
|---|---|
| `test_api.py` | Basic API endpoint smoke test |
| `test_overview.py` | Tests the admin credits overview endpoint |

```bash
python tests/test_api.py
```
