"""app/models/booking.py — Booking lifecycle, time slots, reviews, action tokens, and history."""

import uuid
from datetime import datetime
from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey,
                        Integer, String, Text, UniqueConstraint, Index, Numeric)
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.security import ist_now

# Booking Status Constants
STATUS_REQUESTED = "REQUESTED"
STATUS_ASSIGNED = "ASSIGNED"
STATUS_ACCEPTED = "ACCEPTED"
STATUS_ARRIVED = "ARRIVED"
STATUS_STARTED = "STARTED"
STATUS_COMPLETED = "COMPLETED"
STATUS_REVIEWED = "REVIEWED"
STATUS_CANCELLED = "CANCELLED"

# Cancellation Type Constants
CANCEL_MANUAL = "MANUAL"
CANCEL_SYSTEM = "SYSTEM"
CANCEL_ELECTRICIAN = "ELECTRICIAN"

# Slot Status Constants
SLOT_AVAILABLE = "AVAILABLE"
SLOT_BOOKED = "BOOKED"
SLOT_COMPLETED = "COMPLETED"
SLOT_FAILED = "FAILED"
SLOT_CANCELLED = "CANCELLED"
SLOT_OVER = "OVER"  # For unbooked past slots


class TimeSlot(Base):
    __tablename__ = "time_slots"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    electrician_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    slot_date = Column(DateTime, nullable=False, index=True)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    status = Column(String(20), default=SLOT_AVAILABLE, nullable=False) # VARCHAR
    status_updated_at = Column(DateTime, nullable=True)
    auto_completed_at = Column(DateTime, nullable=True)
    violated_mid_slot = Column(Boolean, default=False)
    created_at = Column(DateTime, default=ist_now)

    electrician = relationship("User", back_populates="time_slots")
    bookings = relationship("Booking", back_populates="time_slot")


class Booking(Base):
    __tablename__ = "bookings"
    __table_args__ = (
        Index("ix_bookings_elec_status", "electrician_id", "status"),
        Index("ix_bookings_cust_status", "customer_id", "status"),
    )

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    electrician_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    service_id = Column(String(36), ForeignKey("services.id", ondelete="RESTRICT"), nullable=False, index=True)
    time_slot_id = Column(String(36), ForeignKey("time_slots.id", ondelete="SET NULL"), nullable=True)

    # Customer address snapshot
    address = Column(Text, nullable=False)
    pincode = Column(String(10), nullable=False, index=True)
    district = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)

    # Problem
    problem_description = Column(Text, nullable=False)

    # Scheduling
    preferred_date = Column(DateTime, nullable=False)
    time_slot_start = Column(DateTime, nullable=True)
    time_slot_end = Column(DateTime, nullable=True)

    # Status
    status = Column(String(20), default=STATUS_REQUESTED, nullable=False, index=True) # VARCHAR + Index

    # Cancellation
    cancellation_type = Column(String(20), nullable=True) # VARCHAR
    cancellation_reason = Column(Text, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)

    # Payment
    payment_id = Column(String(36), ForeignKey("payments.id", ondelete="SET NULL"), nullable=True)
    total_amount = Column(Numeric(10, 2), default=0.0)
    is_paid = Column(Boolean, default=False)
    payment_type = Column(String(10), default="online") 
    deleted_at = Column(DateTime, nullable=True) # Soft delete    
    # Financial tracking status
    earning_calculated = Column(Boolean, default=False)

    # Privacy — Redundant fields removed (customer_phone_masked, electrician_phone_masked)

    # Action token for email workflow
    action_token = Column(String(255), nullable=True)
    action_token_expiry = Column(DateTime, nullable=True)

    # Assignment tracking
    assignment_attempts = Column(Integer, default=0)
    last_assignment_at = Column(DateTime, nullable=True)
    accepted_deadline = Column(DateTime, nullable=True)
    is_auto_rescheduled = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=ist_now, index=True)
    updated_at = Column(DateTime, default=ist_now, onupdate=ist_now)
    assigned_at = Column(DateTime, nullable=True)
    accepted_at = Column(DateTime, nullable=True)
    arrived_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)

    # Relationships
    customer = relationship("User", foreign_keys=[customer_id], back_populates="customer_bookings")
    electrician = relationship("User", foreign_keys=[electrician_id], back_populates="electrician_bookings")
    service = relationship("Service", back_populates="bookings")
    time_slot = relationship("TimeSlot", back_populates="bookings")
    review = relationship("Review", back_populates="booking", uselist=False)
    payment = relationship("Payment", foreign_keys=[payment_id], uselist=False)
    notifications = relationship("Notification", back_populates="booking")
    history = relationship("BookingHistory", back_populates="booking", cascade="all, delete-orphan")


class BookingHistory(Base):
    """Table to track every status change of a booking."""
    __tablename__ = "booking_history"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=False, index=True)
    old_status = Column(String(20), nullable=True)
    new_status = Column(String(20), nullable=False)
    changed_by_id = Column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=ist_now)

    booking = relationship("Booking", back_populates="history")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("booking_id", "customer_id", name="uq_booking_review"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="CASCADE"), unique=True, nullable=False)
    electrician_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    rating = Column(Integer, nullable=False) 
    comment = Column(Text, nullable=True)
    created_at = Column(DateTime, default=ist_now)

    booking = relationship("Booking", back_populates="review")
    electrician = relationship("User", foreign_keys=[electrician_id], back_populates="reviews_received")
    customer = relationship("User", foreign_keys=[customer_id], back_populates="reviews_given")


class ActionToken(Base):
    __tablename__ = "action_tokens"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True)
    token = Column(String(128), unique=True, nullable=False, index=True)
    action = Column(String(50), nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    is_used = Column(Boolean, default=False)

    user = relationship("User", back_populates="action_tokens")

