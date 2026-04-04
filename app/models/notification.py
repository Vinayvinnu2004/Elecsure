"""app/models/notification.py — Notifications (email + SMS)."""

import uuid
import enum
from datetime import datetime
from sqlalchemy import Boolean, Column, DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.security import ist_now


class NotificationType(str, enum.Enum):
    EMAIL = "email"
    SMS = "sms"
    PUSH = "push"


class NotificationEvent(str, enum.Enum):
    BOOKING_CREATED = "booking_created"
    BOOKING_ASSIGNED = "booking_assigned"
    BOOKING_ACCEPTED = "booking_accepted"
    BOOKING_STARTED = "booking_started"
    BOOKING_COMPLETED = "booking_completed"
    BOOKING_CANCELLED = "booking_cancelled"
    PAYMENT_SUCCESS = "payment_success"
    REVIEW_RECEIVED = "review_received"
    EL_SCORE_CHANGED = "el_score_changed"
    ASSIGNMENT_TIMEOUT = "assignment_timeout"


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    user_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True)
    type = Column(Enum(NotificationType), nullable=False)
    event = Column(Enum(NotificationEvent), nullable=False)
    subject = Column(String(255), nullable=True)
    message = Column(Text, nullable=False)
    is_read = Column(Boolean, default=False)
    sent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=ist_now)

    user = relationship("User", back_populates="notifications")
    booking = relationship("Booking", back_populates="notifications")
