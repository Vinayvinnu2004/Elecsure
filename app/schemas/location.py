from pydantic import BaseModel, condecimal
from datetime import datetime
from typing import Optional

class LocationUpdate(BaseModel):
    lat: float
    lng: float

class LocationResponse(BaseModel):
    booking_id: str
    status: str
    
    # Electrician's current position
    electrician_id: Optional[str] = None
    electrician_lat: Optional[float] = None
    electrician_lng: Optional[float] = None
    last_updated: Optional[datetime] = None
    
    # Customer's fixed position (from booking)
    customer_lat: Optional[float] = None
    customer_lng: Optional[float] = None
    
    # Metadata
    is_active: bool
