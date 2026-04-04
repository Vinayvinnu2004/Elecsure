from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_electrician
from app.core.security import ist_now
from app.models import (
    User, Booking, ROLE_ADMIN, 
    STATUS_ACCEPTED, STATUS_ARRIVED, STATUS_STARTED
)
from app.schemas.location import LocationUpdate, LocationResponse
from app.services.location_service import location_service

router = APIRouter(prefix="/api/v1/location", tags=["Location Tracking"])

from pydantic import BaseModel

class LocationUpdateData(BaseModel):
    electrician_id: str
    lat: float
    lng: float

@router.post("/update-location")
async def update_location_in_memory(data: LocationUpdateData):
    location_service.update_location(data.electrician_id, data.lat, data.lng)
    return {"status": "success"}

@router.get("/electrician-location/{electrician_id}")
async def get_electrician_location(electrician_id: str):
    loc = location_service.get_location(electrician_id)
    if not loc:
        raise HTTPException(status_code=404, detail="Location not found")
    return {"lat": loc["lat"], "lng": loc["lng"]}

@router.post("/update")
async def update_location(
    data: LocationUpdate,
    user: User = Depends(require_electrician),
    db: AsyncSession = Depends(get_db)
):
    """
    Electrician updates their current live location.
    Coordinates must be validated.
    """
    if not (-90 <= data.lat <= 90) or not (-180 <= data.lng <= 180):
        raise HTTPException(status_code=400, detail="Invalid coordinates")

    # Load profile
    r_up = await db.execute(
        select(User).options(joinedload(User.electrician_profile))
        .where(User.id == user.id)
    )
    user = r_up.scalar_one()
    profile = user.electrician_profile
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    profile.current_lat = data.lat
    profile.current_lng = data.lng
    profile.location_updated_at = ist_now()
    
    await db.commit()
    return {"message": "Location updated", "timestamp": profile.location_updated_at}

@router.get("/{booking_id}", response_model=LocationResponse)
async def get_booking_location(
    booking_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Customer or assigned Electrician gets the latest location for an active booking.
    """
    result = await db.execute(
        select(Booking)
        .options(joinedload(Booking.electrician).joinedload(User.electrician_profile))
        .where(Booking.id == booking_id)
    )
    booking = result.scalar_one_or_none()
    
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    # Security: Only admin, assigned electrician, or the booking's customer can view
    if user.role != ROLE_ADMIN and user.id not in (booking.customer_id, booking.electrician_id):
        raise HTTPException(status_code=403, detail="Access denied to this tracking data")

    # Is tracking active? Usually when ACCEPTED, ARRIVED or STARTED
    is_active = booking.status in (STATUS_ACCEPTED, STATUS_ARRIVED, STATUS_STARTED)
    
    elec = booking.electrician
    profile = elec.electrician_profile if elec else None
    
    return LocationResponse(
        booking_id=str(booking.id),
        status=booking.status,
        electrician_id=str(elec.id) if elec else None,
        electrician_lat=profile.current_lat if (profile and is_active) else None,
        electrician_lng=profile.current_lng if (profile and is_active) else None,
        last_updated=profile.location_updated_at if (profile and is_active) else None,
        customer_lat=booking.latitude,
        customer_lng=booking.longitude,
        is_active=is_active
    )

