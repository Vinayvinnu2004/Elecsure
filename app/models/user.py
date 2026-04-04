"""app/models/user.py - User model (customers, electricians, admins)."""

import uuid
from datetime import datetime
from sqlalchemy import (Boolean, Column, DateTime, Float, Integer,
                        String, Text, ForeignKey, UniqueConstraint, Index, Numeric)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.security import ist_now

# Roles Constants
ROLE_CUSTOMER = "customer"
ROLE_ELECTRICIAN = "electrician"
ROLE_ADMIN = "admin"

# Toolkit Constants
TOOLKIT_BASIC = "basic"
TOOLKIT_ADVANCED = "advanced"
TOOLKIT_BOTH = "both"
TOOLKIT_NONE = "none"


class PendingUser(Base):
    __tablename__ = "pending_users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20), nullable=False)
    role = Column(String(20), nullable=False, default=ROLE_CUSTOMER) # Using VARCHAR
    user_data = Column(Text, nullable=False)  # JSON string of registration data

    # Notification and Security
    otp_code = Column(String(10), nullable=False) 
    otp_mobile_code = Column(String(10), nullable=False) 
    otp_expires_at = Column(DateTime, nullable=False)
    otp_attempts = Column(Integer, default=0)
    otp_blocked_until = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=ist_now)


class User(Base):
    """Core Authentication and Basic User Info table."""
    __tablename__ = "users"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    name = Column(String(150), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    phone = Column(String(20), nullable=False, index=True)
    alternate_phone = Column(String(20), nullable=True)
    hashed_password = Column(String(255), nullable=True)  # nullable for OAuth users
    role = Column(String(20), nullable=False, default=ROLE_CUSTOMER, index=True) # VARCHAR + Index
    is_active = Column(Boolean, default=True)
    is_verified = Column(Boolean, default=False)  # Admin Approval
    is_otp_verified = Column(Boolean, default=False) # Email/Phone verified
    new_email_temp = Column(String(255), nullable=True) # For sensitive email change flow
    failed_login_attempts = Column(Integer, default=0)
    login_blocked_until = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True) # Soft delete

    # OAuth & Profile
    google_id = Column(String(128), unique=True, nullable=True, index=True)
    auth_provider = Column(String(20), default="local", nullable=False)  # local/google/hybrid
    profile_photo = Column(String(512), nullable=True)
    refresh_token = Column(Text, nullable=True)

    # Timestamps
    created_at = Column(DateTime, default=ist_now)
    updated_at = Column(DateTime, default=ist_now, onupdate=ist_now)
    last_login = Column(DateTime, nullable=True)

    # Notification and Security
    otp_code = Column(String(10), nullable=True)
    otp_mobile_code = Column(String(10), nullable=True)
    otp_expires_at = Column(DateTime, nullable=True)
    otp_attempts = Column(Integer, default=0)
    otp_blocked_until = Column(DateTime, nullable=True)
    last_promo_index = Column(Integer, default=-1)

    # Profiles (Split)
    electrician_profile = relationship("ElectricianProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    customer_profile = relationship("CustomerProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")

    # Relationships
    customer_bookings = relationship("Booking", foreign_keys="Booking.customer_id", back_populates="customer")
    electrician_bookings = relationship("Booking", foreign_keys="Booking.electrician_id", back_populates="electrician")
    service_areas = relationship("ServiceArea", back_populates="electrician", cascade="all, delete-orphan")
    time_slots = relationship("TimeSlot", back_populates="electrician", cascade="all, delete-orphan")
    reviews_received = relationship("Review", foreign_keys="Review.electrician_id", back_populates="electrician")
    reviews_given = relationship("Review", foreign_keys="Review.customer_id", back_populates="customer")
    el_score_logs = relationship("ELScoreLog", back_populates="electrician", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="user", cascade="all, delete-orphan")
    action_tokens = relationship("ActionToken", back_populates="user", cascade="all, delete-orphan")
    payments = relationship("Payment", foreign_keys="Payment.customer_id", back_populates="customer")
    earnings = relationship("ElectricianEarning", back_populates="electrician", uselist=False, cascade="all, delete-orphan")
    weekly_reports = relationship("WeeklyReport", back_populates="electrician", cascade="all, delete-orphan")

    @property
    def has_password(self) -> bool:
        return self.hashed_password is not None and len(self.hashed_password) > 0


class CustomerProfile(Base):
    __tablename__ = "customer_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    
    # Address (Split from User)
    flat_no = Column(String(100), nullable=True)
    landmark = Column(String(200), nullable=True)
    village = Column(String(100), nullable=True)
    district = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    pincode = Column(String(10), nullable=True, index=True)
    full_address = Column(Text, nullable=True)

    user = relationship("User", back_populates="customer_profile")


class ElectricianProfile(Base):
    __tablename__ = "electrician_profiles"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)

    # Electrician-specific fields
    is_available = Column(Boolean, default=True)
    skills = Column(Text, nullable=True)           # comma-separated
    primary_skill = Column(String(150), nullable=True)
    experience_years = Column(Integer, nullable=True)
    toolkit = Column(String(20), default=TOOLKIT_NONE) # VARCHAR
    el_score = Column(Numeric(10, 2), default=50.0)
    rating = Column(Numeric(10, 2), default=0.0)
    total_reviews = Column(Integer, default=0)
    is_restricted = Column(Boolean, default=False)

    # Real-time location
    current_lat = Column(Float, nullable=True)
    current_lng = Column(Float, nullable=True)
    location_updated_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="electrician_profile")


class ServiceArea(Base):
    __tablename__ = "service_areas"
    __table_args__ = (UniqueConstraint("electrician_id", "pincode", name="uq_elec_pin"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    electrician_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    pincode = Column(String(10), nullable=False, index=True)
    district = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    
    # New spatial fields
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    radius_km = Column(Float, default=10.0)

    electrician = relationship("User", back_populates="service_areas")

