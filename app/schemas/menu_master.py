from pydantic import BaseModel
from typing import Optional

class MenuMasterBase(BaseModel):
    menu_name: str
    weekly_price: Optional[float] = None
    monthly_price: Optional[float] = None
    weekly_delivery_charge: Optional[float] = 0.0
    monthly_delivery_charge: Optional[float] = 0.0
    description: Optional[str] = None

class MenuMasterCreate(MenuMasterBase):
    pass

class MenuMasterResponse(MenuMasterBase):
    id: int
    menu_image: Optional[str] = None

    class Config:
        from_attributes = True
