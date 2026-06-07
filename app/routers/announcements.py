from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, validator
from typing import Optional, List
from datetime import date

from app.database import get_db
from app.models.marketing import Announcement
from app.routers.auth import require_admin, get_current_user_optional
from app.models.user import User

router = APIRouter(prefix="/api/announcements", tags=["Announcements"])
admin_only = [Depends(require_admin)]

# ── Schemas ──────────────────────────────────────────────────────────────────

class AnnouncementCreate(BaseModel):
    title:      str
    body:       str
    icon:       Optional[str] = "📢"
    audience:   Optional[str] = "All Customers"
    status:     Optional[str] = "active"
    start_date: date
    end_date:   date

    @validator("end_date")
    def end_after_start(cls, v, values):
        if "start_date" in values and v < values["start_date"]:
            raise ValueError("end_date must be after start_date")
        return v

class AnnouncementResponse(BaseModel):
    id:         int
    title:      str
    body:       str
    icon:       str
    audience:   str
    status:     str
    start_date: date
    end_date:   date
    opens:      int

    class Config:
        orm_mode = True

# ── Helpers ──────────────────────────────────────────────────────────────────

def _expire_old(db: Session):
    """Mark announcements past their end_date as expired and delete them."""
    today = date.today()
    db.query(Announcement)\
      .filter(Announcement.end_date < today, Announcement.status != "expired")\
      .update({"status": "expired"})
    # Hard-delete rows that ended more than 0 days ago
    db.query(Announcement)\
      .filter(Announcement.end_date < today)\
      .delete(synchronize_session="fetch")
    db.commit()

# ── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=List[AnnouncementResponse])
def list_announcements(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    current_user: Optional[User] = Depends(get_current_user_optional)
):
    _expire_old(db)
    q = db.query(Announcement)
    
    # Check if user is admin
    is_admin = current_user and current_user.role and current_user.role.lower() == "admin"
    
    if not is_admin:
        # Customers and unauthenticated users can only see active announcements
        q = q.filter(Announcement.status == "active")
    elif status:
        q = q.filter(Announcement.status == status)
        
    return q.order_by(Announcement.start_date.desc()).all()

@router.post("", response_model=AnnouncementResponse, dependencies=admin_only)
def create_announcement(data: AnnouncementCreate, db: Session = Depends(get_db)):
    _expire_old(db)
    ann = Announcement(**data.dict())
    db.add(ann)
    db.commit()
    db.refresh(ann)
    return ann

@router.put("/{ann_id}", response_model=AnnouncementResponse, dependencies=admin_only)
def update_announcement(ann_id: int, data: AnnouncementCreate, db: Session = Depends(get_db)):
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Announcement not found")
    for k, v in data.dict().items():
        setattr(ann, k, v)
    db.commit()
    db.refresh(ann)
    return ann

@router.patch("/{ann_id}/status", dependencies=admin_only)
def set_announcement_status(ann_id: int, status: str, db: Session = Depends(get_db)):
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Announcement not found")
    if status not in ("active", "draft", "expired"):
        raise HTTPException(400, "Invalid status")
    ann.status = status
    db.commit()
    return {"detail": "Status updated"}

@router.delete("/{ann_id}", dependencies=admin_only)
def delete_announcement(ann_id: int, db: Session = Depends(get_db)):
    ann = db.query(Announcement).filter(Announcement.id == ann_id).first()
    if not ann:
        raise HTTPException(404, "Announcement not found")
    db.delete(ann)
    db.commit()
    return {"detail": "Deleted"}
