"""app/schemas/user.py — User profile schemas."""

from datetime import datetime
from typing import Optional, List
from pydantic import BaseModel, EmailStr


class ServiceAreaIn(BaseModel):
    pincode: str
    district: Optional[str] = None
    state: Optional[str] = None


class ServiceAreaOut(ServiceAreaIn):
    id: str
    model_config = {"from_attributes": True}


class TimeSlotIn(BaseModel):
    slot_date: datetime
    start_time: datetime
    end_time: datetime


class TimeSlotOut(BaseModel):
    id: str
    slot_date: datetime
    start_time: datetime
    end_time: datetime
    status: str
    violated_mid_slot: bool = False
    model_config = {"from_attributes": True}


class LocationUpdate(BaseModel):
    latitude: float
    longitude: float


class CustomerProfileOut(BaseModel):
    flat_no: Optional[str] = None
    landmark: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    full_address: Optional[str] = None
    model_config = {"from_attributes": True}


class ElectricianProfileOut(BaseModel):
    is_available: bool
    skills: Optional[str] = None
    primary_skill: Optional[str] = None
    experience_years: Optional[int] = None
    toolkit: str
    el_score: float
    rating: float
    total_reviews: int
    is_restricted: bool = False
    model_config = {"from_attributes": True}


class ElectricianEarningOut(BaseModel):
    daily_earning: float
    weekly_earning: float
    total_lifetime_earning: float
    commission_due: float
    model_config = {"from_attributes": True}


class UserOut(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    alternate_phone: Optional[str] = None
    role: str
    is_active: bool
    is_verified: bool
    has_password: bool = False
    auth_provider: str = "local"
    profile_photo: Optional[str] = None
    created_at: Optional[datetime] = None
    
    # Profiles
    customer_profile: Optional[CustomerProfileOut] = None
    electrician_profile: Optional[ElectricianProfileOut] = None
    earnings: Optional[ElectricianEarningOut] = None
    
    model_config = {"from_attributes": True}


class UserProfileUpdate(BaseModel):
    email: Optional[EmailStr] = None
    name: Optional[str] = None
    phone: Optional[str] = None
    alternate_phone: Optional[str] = None
    flat_no: Optional[str] = None
    landmark: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    full_address: Optional[str] = None


class ElectricianProfileUpdate(UserProfileUpdate):
    skills: Optional[str] = None
    primary_skill: Optional[str] = None
    experience_years: Optional[int] = None
    toolkit: Optional[str] = None


class EmailChangeRequest(BaseModel):
    new_email: EmailStr


class EmailChangeVerify(BaseModel):
    new_email: EmailStr
    otp: str
