from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.meal_tier import MealTier
from app.models.menu import PlanTemplate, TierPricing, WeeklyMenuImage
import uuid
import os
from datetime import date, timedelta
from typing import List, Optional
from pydantic import BaseModel

from app.routers.auth import require_admin

router = APIRouter(prefix="/api/menu", tags=["Menu Management API"])
admin_only = [Depends(require_admin)]

try:
    from supabase import create_client, Client
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
    supabase_client: Client = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None
except Exception:
    supabase_client = None

# ── Constants ─────────────────────────────────────────────────────────────────

# Nutribox delivers Monday–Saturday (Sunday off).
# Weekly = 6 working days. Monthly = 24 working days (4 weeks × 6).
MEAL_COUNT_MAP = {
    ('breakfast_only', 'weekly'):  6,
    ('dinner_only',    'weekly'):  6,
    ('both',           'weekly'):  12,
    ('breakfast_only', 'monthly'): 24,
    ('dinner_only',    'monthly'): 24,
    ('both',           'monthly'): 48,
}

# Number of working days a duration covers (used for end_date arithmetic)
DURATION_WORKING_DAYS = {
    'weekly':  6,
    'monthly': 24,
}

SLOT_DISPLAY = {
    'breakfast_only': 'Breakfast Only',
    'dinner_only': 'Dinner Only',
    'both': 'Breakfast + Dinner',
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def normalize_monday(d: date) -> date:
    """Normalize any date to the Monday of that week."""
    return d - timedelta(days=d.weekday())


def _auto_slug(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _get_current_price(tier_id: str, diet_type: str, db: Session, target_date: date = None) -> float:
    """Resolve the active price for a tier/diet as of target_date."""
    if not target_date:
        target_date = date.today()
    price = db.query(TierPricing).filter(
        TierPricing.tier_id == tier_id,
        TierPricing.diet_type == diet_type,
        TierPricing.effective_from <= target_date,
        TierPricing.is_active == True
    ).order_by(TierPricing.effective_from.desc()).first()
    return float(price.price_per_meal) if price else 0.0


def _generate_display_name(tier_name: str, diet_type: str, slot_combo: str, duration: str) -> str:
    diet = "Veg" if diet_type == "veg" else "Non-Veg"
    slot = SLOT_DISPLAY.get(slot_combo, slot_combo)
    dur = "Weekly" if duration == "weekly" else "Monthly"
    return f"{tier_name} · {diet} · {slot} · {dur}"


def _resolve_weekly_image(tier_id: str, diet_type: str, monday: date, db: Session) -> Optional[str]:
    """Resolve weekly menu image with fallback: exact → both → null."""
    # Try exact match
    img = db.query(WeeklyMenuImage).filter(
        WeeklyMenuImage.tier_id == tier_id,
        WeeklyMenuImage.diet_type == diet_type,
        WeeklyMenuImage.week_start_date == monday
    ).first()
    if img:
        return img.image_url
    # Fallback to 'both'
    img = db.query(WeeklyMenuImage).filter(
        WeeklyMenuImage.tier_id == tier_id,
        WeeklyMenuImage.diet_type == 'both',
        WeeklyMenuImage.week_start_date == monday
    ).first()
    return img.image_url if img else None


# ── Pydantic Schemas ──────────────────────────────────────────────────────────

class TierCreatePayload(BaseModel):
    name: str
    diet_support: str = "both"
    delivery_charge_weekly: float = 10.0
    delivery_charge_monthly: float = 0.0
    is_active: bool = True
    is_featured: bool = False


class TierUpdatePayload(BaseModel):
    name: Optional[str] = None
    diet_support: Optional[str] = None
    delivery_charge_weekly: Optional[float] = None
    delivery_charge_monthly: Optional[float] = None
    is_active: Optional[bool] = None
    is_featured: Optional[bool] = None


class ReorderItem(BaseModel):
    id: str
    display_order: int


class PricingPayload(BaseModel):
    diet_type: str  # 'veg' | 'nonveg'
    price_per_meal: float
    effective_from: Optional[date] = None


class PricingPatchPayload(BaseModel):
    is_active: bool


class WeeklyMenuPayload(BaseModel):
    tier_id: str
    diet_type: str  # 'veg' | 'nonveg' | 'both'
    week_start_date: date
    image_url: str


class CopyWeekPayload(BaseModel):
    source_week: date
    target_week: date


class PlanPatch(BaseModel):
    is_active: bool


# ── TIER ENDPOINTS ────────────────────────────────────────────────────────────

@router.get("/tiers")
def get_tiers(db: Session = Depends(get_db)):
    """Get all tiers with current pricing."""
    tiers = db.query(MealTier).order_by(MealTier.display_order.asc()).all()
    today = date.today()
    result = []
    for t in tiers:
        # Get current active pricing rows for this tier
        pricing_rows = db.query(TierPricing).filter(
            TierPricing.tier_id == t.id
        ).order_by(TierPricing.diet_type, TierPricing.effective_from.desc()).all()

        # Deduplicate: keep most recent effective_from per diet_type that is <= today
        current_pricing = {}
        for p in pricing_rows:
            if p.effective_from <= today and p.is_active:
                if p.diet_type not in current_pricing:
                    current_pricing[p.diet_type] = {
                        "id": str(p.id),
                        "diet_type": p.diet_type,
                        "price_per_meal": float(p.price_per_meal),
                        "effective_from": str(p.effective_from),
                    }

        result.append({
            "id": str(t.id),
            "name": t.name,
            "slug": t.slug,
            "display_order": t.display_order,
            "diet_support": t.diet_support,
            "delivery_charge_weekly": float(t.delivery_charge_weekly or 0),
            "delivery_charge_monthly": float(t.delivery_charge_monthly or 0),
            "is_active": t.is_active,
            "is_featured": bool(t.is_featured),
            "pricing": list(current_pricing.values()),
        })
    return result


@router.post("/tiers", dependencies=admin_only)
def create_tier(payload: TierCreatePayload, db: Session = Depends(get_db)):
    """Create a new tier. Slug is auto-generated from name."""
    if payload.diet_support not in ("veg_only", "nonveg_only", "both"):
        raise HTTPException(status_code=400, detail="diet_support must be 'veg_only', 'nonveg_only', or 'both'")

    slug = _auto_slug(payload.name)
    # Check slug uniqueness
    existing = db.query(MealTier).filter(MealTier.slug == slug).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"A tier with slug '{slug}' already exists")

    if payload.is_featured:
        # Only one featured tier at a time
        db.query(MealTier).update({"is_featured": False})

    tier = MealTier(
        name=payload.name,
        slug=slug,
        diet_support=payload.diet_support,
        delivery_charge_weekly=payload.delivery_charge_weekly,
        delivery_charge_monthly=payload.delivery_charge_monthly,
        is_active=payload.is_active,
        is_featured=payload.is_featured,
    )
    db.add(tier)
    db.commit()
    db.refresh(tier)
    return {"id": str(tier.id), "slug": tier.slug, "message": "Tier created"}


@router.put("/tiers/{tier_id}", dependencies=admin_only)
def update_tier(tier_id: str, payload: TierUpdatePayload, db: Session = Depends(get_db)):
    """Update tier properties. Regenerates slug if name changes."""
    tier = db.query(MealTier).filter(MealTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    if payload.name is not None and payload.name != tier.name:
        tier.name = payload.name
        tier.slug = _auto_slug(payload.name)

    if payload.diet_support is not None:
        if payload.diet_support not in ("veg_only", "nonveg_only", "both"):
            raise HTTPException(status_code=400, detail="Invalid diet_support value")
        old_support = tier.diet_support
        tier.diet_support = payload.diet_support
        # If changing to veg_only, soft-deactivate all nonveg pricing rows
        if payload.diet_support == "veg_only" and old_support != "veg_only":
            db.query(TierPricing).filter(
                TierPricing.tier_id == tier_id,
                TierPricing.diet_type == "nonveg"
            ).update({"is_active": False})

    if payload.delivery_charge_weekly is not None:
        tier.delivery_charge_weekly = payload.delivery_charge_weekly
    if payload.delivery_charge_monthly is not None:
        tier.delivery_charge_monthly = payload.delivery_charge_monthly
    if payload.is_active is not None:
        tier.is_active = payload.is_active
    if payload.is_featured is not None:
        if payload.is_featured:
            # Only one featured tier at a time — un-feature every other tier.
            db.query(MealTier).filter(MealTier.id != tier_id).update({"is_featured": False})
        tier.is_featured = payload.is_featured

    db.commit()
    return {"message": "Tier updated", "slug": tier.slug}


@router.delete("/tiers/{tier_id}", dependencies=admin_only)
def delete_tier(tier_id: str, db: Session = Depends(get_db)):
    """Hard-delete a tier and everything it owns: pricing rows, weekly images,
    and plan combinations. Reject if the tier is referenced by any subscription.

    Used by admin UI to clean up duplicates / unused tiers.
    """
    tier = db.query(MealTier).filter(MealTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    # Check for plans on this tier — block delete if any subscriptions reference them
    plan_ids = [p.id for p in db.query(PlanTemplate).filter(PlanTemplate.tier_id == tier_id).all()]
    if plan_ids:
        from app.models.subscription import Subscription
        sub_count = db.query(Subscription).filter(Subscription.menu_id.in_(plan_ids)).count()
        if sub_count > 0:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"This tier is referenced by {sub_count} subscription(s) and cannot be deleted. "
                    "Deactivate it instead, or migrate those subscriptions first."
                ),
            )

    # Cascade-delete dependents in order (no FK ON DELETE CASCADE on every relation)
    db.query(WeeklyMenuImage).filter(WeeklyMenuImage.tier_id == tier_id).delete(synchronize_session=False)
    db.query(TierPricing).filter(TierPricing.tier_id == tier_id).delete(synchronize_session=False)
    if plan_ids:
        db.query(PlanTemplate).filter(PlanTemplate.tier_id == tier_id).delete(synchronize_session=False)
    db.delete(tier)
    db.commit()
    return {"message": "Tier deleted"}


@router.patch("/tiers/reorder", dependencies=admin_only)
def reorder_tiers(payload: List[ReorderItem], db: Session = Depends(get_db)):
    """Reorder tiers. Accepts [{id, display_order}] array."""
    for item in payload:
        db.query(MealTier).filter(MealTier.id == item.id).update({"display_order": item.display_order})
    db.commit()
    return {"message": "Reordered"}


# ── TIER PRICING ENDPOINTS ────────────────────────────────────────────────────

@router.get("/tiers/{tier_id}/pricing")
def get_tier_pricing(tier_id: str, db: Session = Depends(get_db)):
    """Get all pricing rows for a tier."""
    tier = db.query(MealTier).filter(MealTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    pricing = db.query(TierPricing).filter(
        TierPricing.tier_id == tier_id
    ).order_by(TierPricing.diet_type, TierPricing.effective_from.desc()).all()

    today = date.today()
    return [{
        "id": str(p.id),
        "diet_type": p.diet_type,
        "price_per_meal": float(p.price_per_meal),
        "effective_from": str(p.effective_from),
        "is_active": p.is_active,
        "status": "active" if (p.effective_from <= today and p.is_active) else ("scheduled" if p.effective_from > today else "inactive"),
    } for p in pricing]


@router.post("/tiers/{tier_id}/pricing", dependencies=admin_only)
def add_tier_pricing(tier_id: str, payload: PricingPayload, db: Session = Depends(get_db)):
    """Add a new pricing row. Validates diet_support, no backdating, no duplicate."""
    tier = db.query(MealTier).filter(MealTier.id == tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    # Business Rule: Fruits Bowl (veg_only) cannot have nonveg pricing
    if tier.diet_support == "veg_only" and payload.diet_type == "nonveg":
        raise HTTPException(status_code=400, detail="This tier does not support non-veg pricing")
    if tier.diet_support == "nonveg_only" and payload.diet_type == "veg":
        raise HTTPException(status_code=400, detail="This tier does not support veg pricing")

    if payload.diet_type not in ("veg", "nonveg"):
        raise HTTPException(status_code=400, detail="diet_type must be 'veg' or 'nonveg'")

    eff_date = payload.effective_from or date.today()

    # Business Rule: No backdating
    if eff_date < date.today():
        raise HTTPException(status_code=400, detail="effective_from cannot be in the past")

    if payload.price_per_meal <= 0:
        raise HTTPException(status_code=400, detail="price_per_meal must be greater than 0")

    # Check for duplicate
    existing = db.query(TierPricing).filter(
        TierPricing.tier_id == tier_id,
        TierPricing.diet_type == payload.diet_type,
        TierPricing.effective_from == eff_date
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="A pricing row already exists for this tier/diet/date combination")

    new_price = TierPricing(
        tier_id=tier_id,
        diet_type=payload.diet_type,
        price_per_meal=payload.price_per_meal,
        effective_from=eff_date
    )
    db.add(new_price)
    db.commit()
    return {"message": "Pricing row created", "id": str(new_price.id)}


@router.patch("/tier-pricing/{pricing_id}", dependencies=admin_only)
def patch_tier_pricing(pricing_id: str, payload: PricingPatchPayload, db: Session = Depends(get_db)):
    """Toggle is_active only — price and date are immutable after creation."""
    row = db.query(TierPricing).filter(TierPricing.id == pricing_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Pricing row not found")
    row.is_active = payload.is_active
    db.commit()
    return {"message": "Updated"}


# ── PLAN COMBINATION ENDPOINTS ────────────────────────────────────────────────

@router.get("/plan-combinations")
def get_plan_combinations(db: Session = Depends(get_db)):
    """Returns all non-legacy plan combinations with computed prices."""
    plans = db.query(PlanTemplate).filter(PlanTemplate.is_legacy == False).all()
    tiers = {str(t.id): t for t in db.query(MealTier).all()}
    today = date.today()

    result = []
    for p in plans:
        tier = tiers.get(str(p.tier_id))
        if not tier:
            continue

        price_per_meal = _get_current_price(str(p.tier_id), p.diet_type, db, today)
        meal_count = p.meal_count or MEAL_COUNT_MAP.get((p.slot_combo, p.duration), 0)
        delivery_per_meal = float(tier.delivery_charge_weekly if p.duration == "weekly" else tier.delivery_charge_monthly or 0)
        delivery = round(delivery_per_meal * meal_count, 2)
        total_price = round(price_per_meal * meal_count + delivery, 2)
        display_name = _generate_display_name(tier.name, p.diet_type, p.slot_combo or "", p.duration or "")

        result.append({
            "id": str(p.id),
            "tier_id": str(p.tier_id),
            "tier_name": tier.name,
            "tier_slug": tier.slug,
            "diet_type": p.diet_type,
            "slot_combo": p.slot_combo,
            "duration": p.duration,
            "meal_count": meal_count,
            "price_per_meal": price_per_meal,
            "delivery_charge": delivery,
            "total_price": total_price,
            "display_name": display_name,
            "is_active": p.is_active,
        })
    return result


@router.patch("/plan-combinations/{plan_id}", dependencies=admin_only)
def toggle_plan_combination(plan_id: str, payload: PlanPatch, db: Session = Depends(get_db)):
    """Toggle is_active for a plan combination."""
    plan = db.query(PlanTemplate).filter(PlanTemplate.id == plan_id).first()
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    plan.is_active = payload.is_active
    db.commit()
    return {"message": "Updated"}


@router.get("/plans/compute")
def compute_plan_price(
    tier_slug: str = Query(...),
    diet_type: str = Query(...),
    slot_combo: str = Query(...),
    duration: str = Query(...),
    db: Session = Depends(get_db)
):
    """Compute plan price dynamically without needing a stored plan record."""
    tier = db.query(MealTier).filter(MealTier.slug == tier_slug).first()
    if not tier:
        raise HTTPException(status_code=404, detail=f"Tier with slug '{tier_slug}' not found")

    if (slot_combo, duration) not in MEAL_COUNT_MAP:
        raise HTTPException(status_code=400, detail="Invalid slot_combo/duration combination")

    meal_count = MEAL_COUNT_MAP[(slot_combo, duration)]
    price_per_meal = _get_current_price(str(tier.id), diet_type, db)
    delivery_per_meal = float(tier.delivery_charge_weekly if duration == "weekly" else tier.delivery_charge_monthly or 0)
    delivery = round(delivery_per_meal * meal_count, 2)
    subtotal = round(price_per_meal * meal_count, 2)
    total = round(subtotal + delivery, 2)
    display_name = _generate_display_name(tier.name, diet_type, slot_combo, duration)

    return {
        "tier_id": str(tier.id),
        "tier_name": tier.name,
        "tier_slug": tier_slug,
        "diet_type": diet_type,
        "slot_combo": slot_combo,
        "duration": duration,
        "price_per_meal": price_per_meal,
        "meal_count": meal_count,
        "delivery_charge": delivery,
        "subtotal": subtotal,
        "total": total,
        "display_name": display_name,
    }


# ── WEEKLY MENU IMAGE ENDPOINTS ───────────────────────────────────────────────

@router.get("/weekly-menu-images")
def get_weekly_images(
    week_start_date: date = Query(...),
    tier_id: Optional[str] = Query(None),
    diet_type: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Get weekly menu images with fallback resolution and coverage status."""
    monday = normalize_monday(week_start_date)

    tiers = db.query(MealTier).filter(MealTier.is_active == True).order_by(MealTier.display_order).all()
    if tier_id:
        tiers = [t for t in tiers if str(t.id) == tier_id]

    result = []
    coverage_status = []

    for tier in tiers:
        diet_types = []
        if tier.diet_support == "veg_only":
            diet_types = ["veg"]
        elif tier.diet_support == "nonveg_only":
            diet_types = ["nonveg"]
        else:
            diet_types = ["veg", "nonveg"]

        if diet_type:
            diet_types = [d for d in diet_types if d == diet_type]

        for dt in diet_types:
            image_url = _resolve_weekly_image(str(tier.id), dt, monday, db)
            coverage_status.append({
                "tier_id": str(tier.id),
                "tier_name": tier.name,
                "tier_slug": tier.slug,
                "diet_type": dt,
                "has_image": image_url is not None,
            })
            if image_url:
                result.append({
                    "tier_id": str(tier.id),
                    "tier_name": tier.name,
                    "tier_slug": tier.slug,
                    "diet_type": dt,
                    "week_start_date": str(monday),
                    "image_url": image_url,
                })

    return {"images": result, "coverage_status": coverage_status}


@router.post("/weekly-menu-images", dependencies=admin_only)
def upsert_weekly_image(payload: WeeklyMenuPayload, db: Session = Depends(get_db)):
    """Upsert a weekly menu image for tier+diet_type+week."""
    tier = db.query(MealTier).filter(MealTier.id == payload.tier_id).first()
    if not tier:
        raise HTTPException(status_code=404, detail="Tier not found")

    # Business Rule: no nonveg images for veg_only tiers
    if tier.diet_support == "veg_only" and payload.diet_type == "nonveg":
        raise HTTPException(status_code=400, detail="This tier does not support non-veg images")

    if payload.diet_type not in ("veg", "nonveg", "both"):
        raise HTTPException(status_code=400, detail="diet_type must be 'veg', 'nonveg', or 'both'")

    monday = normalize_monday(payload.week_start_date)

    existing = db.query(WeeklyMenuImage).filter(
        WeeklyMenuImage.tier_id == payload.tier_id,
        WeeklyMenuImage.diet_type == payload.diet_type,
        WeeklyMenuImage.week_start_date == monday
    ).first()

    if existing:
        existing.image_url = payload.image_url
    else:
        new_img = WeeklyMenuImage(
            tier_id=payload.tier_id,
            diet_type=payload.diet_type,
            week_start_date=monday,
            image_url=payload.image_url
        )
        db.add(new_img)

    db.commit()
    return {"message": "Weekly image saved", "week_start_date": str(monday)}


@router.delete("/weekly-menu-images/{image_id}", dependencies=admin_only)
def delete_weekly_image(image_id: str, db: Session = Depends(get_db)):
    """Hard delete an image record (Supabase file kept)."""
    img = db.query(WeeklyMenuImage).filter(WeeklyMenuImage.id == image_id).first()
    if not img:
        raise HTTPException(status_code=404, detail="Image record not found")
    db.delete(img)
    db.commit()
    return {"message": "Deleted"}


@router.post("/weekly-menu-images/copy-week", dependencies=admin_only)
def copy_week_images(payload: CopyWeekPayload, db: Session = Depends(get_db)):
    """Copy all image records from source_week to target_week."""
    m_from = normalize_monday(payload.source_week)
    m_to = normalize_monday(payload.target_week)

    source_images = db.query(WeeklyMenuImage).filter(
        WeeklyMenuImage.week_start_date == m_from
    ).all()

    copied = 0
    skipped = 0
    for img in source_images:
        existing = db.query(WeeklyMenuImage).filter(
            WeeklyMenuImage.tier_id == img.tier_id,
            WeeklyMenuImage.diet_type == img.diet_type,
            WeeklyMenuImage.week_start_date == m_to
        ).first()

        if existing:
            skipped += 1
        else:
            db.add(WeeklyMenuImage(
                tier_id=img.tier_id,
                diet_type=img.diet_type,
                week_start_date=m_to,
                image_url=img.image_url
            ))
            copied += 1

    db.commit()
    return {"message": f"Copied {copied}, skipped {skipped}", "copied": copied, "skipped": skipped}


# ── IMAGE UPLOAD ──────────────────────────────────────────────────────────────

@router.post("/upload-image", dependencies=admin_only)
async def upload_image(file: UploadFile = File(...)):
    """Upload image to Supabase storage and return public URL.

    On failure, returns a structured detail dict:
      { error_type, message, raw }
    so the admin frontend can display a clear, actionable error banner.
    """
    from app.utils.supabase_errors import classify_supabase_error

    if not supabase_client:
        raise HTTPException(
            status_code=503,
            detail={
                "error_type": "storage_not_configured",
                "message": (
                    "Supabase storage is not configured on this server. "
                    "Add SUPABASE_URL and SUPABASE_KEY to the backend .env file."
                ),
                "raw": "supabase_client is None",
            },
        )

    # Validate file type early
    allowed_types = {"image/jpeg", "image/png", "image/webp", "image/gif"}
    content_type = file.content_type or "image/jpeg"
    if content_type not in allowed_types:
        raise HTTPException(
            status_code=415,
            detail={
                "error_type": "invalid_file_type",
                "message": f"Unsupported file type '{content_type}'. Please upload a JPEG, PNG, or WebP image.",
                "raw": f"content_type={content_type}",
            },
        )

    ext = file.filename.split(".")[-1] if file.filename and "." in file.filename else "jpg"
    filename = f"menus/{uuid.uuid4()}.{ext}"
    bucket_name = os.environ.get("SUPABASE_BUCKET", "menu-images")

    try:
        contents = await file.read()

        # Guard against empty uploads
        if not contents:
            raise HTTPException(
                status_code=400,
                detail={
                    "error_type": "empty_file",
                    "message": "The uploaded file is empty. Please select a valid image.",
                    "raw": "file content length = 0",
                },
            )

        supabase_client.storage.from_(bucket_name).upload(
            filename,
            contents,
            {"content-type": content_type},
        )

    except HTTPException:
        # Re-raise our own validation HTTPExceptions unchanged
        raise
    except Exception as exc:
        status_code, detail = classify_supabase_error(exc)
        raise HTTPException(status_code=status_code, detail=detail)

    try:
        public_url = supabase_client.storage.from_(bucket_name).get_public_url(filename)
    except Exception as exc:
        # Upload succeeded but URL generation failed — still a Supabase issue
        status_code, detail = classify_supabase_error(exc)
        raise HTTPException(status_code=status_code, detail=detail)

    return {"image_url": public_url}


# ── LEGACY / DEPRECATED ENDPOINTS ────────────────────────────────────────────

@router.get("/plan-templates")
def get_plans_legacy():
    raise HTTPException(
        status_code=410,
        detail="This endpoint has been removed. Use GET /api/menu/plan-combinations instead."
    )


@router.post("/plan-templates")
def create_plan_legacy():
    raise HTTPException(
        status_code=410,
        detail="This endpoint has been removed. Use POST /api/menu/plan-combinations instead."
    )


@router.get("/weekly-menus")
def get_weekly_legacy(tier_slug: str, menu_date: date, db: Session = Depends(get_db)):
    """Legacy backward-compat endpoint for weekly menus."""
    tier = db.query(MealTier).filter(MealTier.slug == tier_slug).first()
    if not tier:
        return None
    monday = normalize_monday(menu_date)
    image_url = _resolve_weekly_image(str(tier.id), "both", monday, db)
    if image_url:
        return {"image_url": image_url}
    return None
