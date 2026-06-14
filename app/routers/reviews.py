from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

from app.database import get_db
from app.models.marketing import Review
from app.models.user import User
from app.routers.auth import get_current_user, require_admin

router = APIRouter(prefix="/api/reviews", tags=["Reviews"])

# Schemas
class ReviewCreate(BaseModel):
    rating: int
    text: str

class ReviewResponse(BaseModel):
    id: int
    customer_id: int
    customer_name: str
    customer_role: str
    rating: int
    text: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

@router.get("", response_model=List[ReviewResponse])
def get_approved_reviews(
    skip: int = 0,
    limit: int = 10,
    db: Session = Depends(get_db)
):
    """Fetch approved reviews for public display."""
    results = (
        db.query(Review)
        .filter(Review.status == "approved")
        .order_by(Review.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    # Serialize with joined customer name and role
    reviews_out = []
    for r in results:
        reviews_out.append(
            ReviewResponse(
                id=r.id,
                customer_id=r.customer_id,
                customer_name=r.customer.full_name if r.customer else "Valued Customer",
                customer_role=r.customer.role.capitalize() if r.customer and r.customer.role else "Customer",
                rating=r.rating,
                text=r.text,
                status=r.status,
                created_at=r.created_at
            )
        )
    return reviews_out

@router.get("/stats")
def get_review_stats(db: Session = Depends(get_db)):
    """Fetch public stats of reviews (total count, happy customer count)."""
    total = db.query(Review).filter(Review.status == "approved").count()
    happy = db.query(Review).filter(Review.status == "approved", Review.rating >= 4).count()
    return {
        "total_reviews": total,
        "happy_customers": happy
    }

@router.get("/my-review")
def get_my_review(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Retrieve the logged-in user's review, if any."""
    r = db.query(Review).filter(Review.customer_id == current_user.id).first()
    if not r:
        return {"review": None}
    return {
        "review": {
            "id": r.id,
            "rating": r.rating,
            "text": r.text,
            "status": r.status,
            "created_at": r.created_at
        }
    }

@router.post("")
def create_or_update_review(
    payload: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create or update a review for the logged-in customer."""
    if payload.rating < 1 or payload.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5.")
    if not payload.text.strip():
        raise HTTPException(status_code=400, detail="Review text cannot be empty.")

    # Check if review already exists
    r = db.query(Review).filter(Review.customer_id == current_user.id).first()
    if r:
        # Update existing
        r.rating = payload.rating
        r.text = payload.text.strip()
        r.created_at = datetime.utcnow()
    else:
        # Create new
        r = Review(
            customer_id=current_user.id,
            rating=payload.rating,
            text=payload.text.strip(),
            status="approved"  # Auto-approve for testing and immediate display
        )
        db.add(r)
    
    db.commit()
    db.refresh(r)
    return {"detail": "Review submitted successfully!", "review_id": r.id}

@router.delete("")
def delete_my_review(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Delete the logged-in customer's review."""
    r = db.query(Review).filter(Review.customer_id == current_user.id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Review not found.")
    db.delete(r)
    db.commit()
    return {"detail": "Review deleted successfully."}

@router.get("/admin", response_model=List[ReviewResponse])
def get_all_reviews_admin(
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Fetch all reviews for admin management."""
    results = db.query(Review).order_by(Review.created_at.desc()).all()
    reviews_out = []
    for r in results:
        reviews_out.append(
            ReviewResponse(
                id=r.id,
                customer_id=r.customer_id,
                customer_name=r.customer.full_name if r.customer else "Valued Customer",
                customer_role=r.customer.role.capitalize() if r.customer and r.customer.role else "Customer",
                rating=r.rating,
                text=r.text,
                status=r.status,
                created_at=r.created_at
            )
        )
    return reviews_out

@router.post("/{review_id}/toggle-approved")
def toggle_review_approved(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Toggle a review's approved status for display on the homepage."""
    r = db.query(Review).filter(Review.id == review_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Review not found.")
    
    if r.status == "approved":
        r.status = "pending"
    else:
        r.status = "approved"
        
    db.commit()
    db.refresh(r)
    return {"id": r.id, "status": r.status}

@router.delete("/{review_id}")
def delete_review_admin(
    review_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_admin)
):
    """Admin endpoint to delete a review."""
    r = db.query(Review).filter(Review.id == review_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Review not found.")
    db.delete(r)
    db.commit()
    return {"detail": "Review deleted successfully by admin."}
