from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.marketing import GalleryImage
from app.routers.auth import require_admin
from pydantic import BaseModel
from typing import List, Optional

router = APIRouter(prefix="/api/gallery", tags=["Gallery Management API"])
admin_only = [Depends(require_admin)]

class GalleryCreatePayload(BaseModel):
    image_url: str
    caption: Optional[str] = None
    sort_order: Optional[int] = 0

@router.get("")
def get_gallery(db: Session = Depends(get_db)):
    """Fetch all images uploaded in the showcase gallery, ordered by sort_order and ID."""
    images = db.query(GalleryImage).order_by(GalleryImage.sort_order.asc(), GalleryImage.id.asc()).all()
    return [{
        "id": str(img.id),          # str to prevent JS integer precision loss on 64-bit IDs
        "image_url": img.image_url,
        "caption": img.caption,
        "sort_order": img.sort_order,
        "created_at": img.created_at
    } for img in images]

@router.post("", dependencies=admin_only)
def add_gallery_image(payload: GalleryCreatePayload, db: Session = Depends(get_db)):
    """Add a new image to the showcase gallery. Validates maximum limit of 10 images."""
    count = db.query(GalleryImage).count()
    if count >= 10:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum limit of 10 gallery images reached. Please delete an existing image to upload a new one."
        )
    
    new_image = GalleryImage(
        image_url=payload.image_url,
        caption=payload.caption,
        sort_order=payload.sort_order
    )
    db.add(new_image)
    db.commit()
    db.refresh(new_image)
    return {"message": "Image added successfully", "id": str(new_image.id), "image_url": new_image.image_url}

@router.delete("/{image_id}", dependencies=admin_only)
def delete_gallery_image(image_id: str, db: Session = Depends(get_db)):
    """Delete a gallery image by ID. Accepts ID as string to handle 64-bit precision safely."""
    try:
        image_id_int = int(image_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid image ID")
    image = db.query(GalleryImage).filter(GalleryImage.id == image_id_int).first()
    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gallery image not found"
        )
    db.delete(image)
    db.commit()
    return {"message": "Image deleted successfully"}
