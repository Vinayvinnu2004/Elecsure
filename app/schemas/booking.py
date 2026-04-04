"""app/schemas/booking.py — Booking schemas with friendly validation messages."""

from datetime import datetime
from typing import Optional
from pydantic import BaseModel, field_validator


class BookingCreate(BaseModel):
    service_id: str
    preferred_date: datetime
    time_slot_id: Optional[str] = None   # UUID DB id or null
    time_slot_start: Optional[datetime] = None
    time_slot_end: Optional[datetime] = None
    problem_description: str
    address: str
    pincode: str
    district: Optional[str] = None
    state: Optional[str] = None
    latitude: float
    longitude: float
    payment_type: Optional[str] = "online"  # 'online' or 'cod'

    @field_validator("problem_description")
    @classmethod
    def desc_required(cls, v: str) -> str:
        if not v or len(v.strip()) < 20:
            raise ValueError(
                "Please describe the problem in at least 20 characters so our electrician is prepared"
            )
        return v.strip()

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: str) -> str:
        if not v.strip().isdigit() or len(v.strip()) != 6:
            raise ValueError("Please enter a valid 6-digit pincode")
        return v.strip()

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        if not v or len(v.strip()) < 10:
            raise ValueError("Please enter a complete address (at least 10 characters)")
        return v.strip()

    @field_validator("preferred_date")
    @classmethod
    def validate_date(cls, v: datetime) -> datetime:
        from datetime import date
        if v.date() < date.today():
            raise ValueError("Preferred date cannot be in the past")
        return v


class ReviewCreate(BaseModel):
    rating: int  # non-ID integer
    comment: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def validate_rating(cls, v: int) -> int:
        if v < 1 or v > 5:
            raise ValueError("Rating must be between 1 and 5 stars")
        return v


class ReviewOut(BaseModel):
    id: str
    rating: int
    comment: Optional[str] = None
    customer_id: str
    created_at: datetime
    model_config = {"from_attributes": True}


class ServiceSnap(BaseModel):
    id: str
    name: str
    category: str
    base_price: float
    model_config = {"from_attributes": True}


class BookingOut(BaseModel):
    id: str
    status: str
    service: Optional[ServiceSnap] = None
    customer_id: str
    electrician_id: Optional[str] = None
    address: Optional[str] = None
    pincode: Optional[str] = None
    district: Optional[str] = None
    problem_description: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    preferred_date: Optional[datetime] = None
    time_slot_start: Optional[datetime] = None
    time_slot_end: Optional[datetime] = None
    total_amount: float = 0.0
    is_paid: bool = False
    payment_type: Optional[str] = "online"
    cancellation_reason: Optional[str] = None
    cancelled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    customer_phone_masked: Optional[str] = None
    customer_name: Optional[str] = None
    customer_phone: Optional[str] = None
    customer_alt_phone: Optional[str] = None
    customer_address: Optional[str] = None
    electrician_name: Optional[str] = None
    electrician_phone: Optional[str] = None
    electrician_alt_phone: Optional[str] = None
    electrician_phone_masked: Optional[str] = None
    review: Optional[ReviewOut] = None
    created_at: Optional[datetime] = None
    model_config = {"from_attributes": True}


class BookingListOut(BaseModel):
    items: list[BookingOut]
    total: int
    model_config = {"from_attributes": True}


class ActionTokenUse(BaseModel):
    token: str
