"""app/schemas/service.py"""

from typing import Optional, List
from pydantic import BaseModel


class ServiceOut(BaseModel):
    id: str
    category: str
    group: str
    name: str
    description: Optional[str] = None
    base_price: float
    duration_minutes: int
    is_active: bool
    model_config = {"from_attributes": True}


class ServiceListOut(BaseModel):
    category: str
    services: List[ServiceOut]
