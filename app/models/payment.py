"""app/models/payment.py — Stripe payment records and logs."""

import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text, Index, Numeric
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.security import ist_now

# Payment Status Constants
PAYMENT_PENDING = "PENDING"
PAYMENT_COMPLETED = "COMPLETED"
PAYMENT_FAILED = "FAILED"
PAYMENT_REFUNDED = "REFUNDED"


class Payment(Base):
    __tablename__ = "payments"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    customer_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="CASCADE"), nullable=True, index=True)
    amount = Column(Numeric(10, 2), nullable=False)
    currency = Column(String(10), default="INR")
    status = Column(String(20), default=PAYMENT_PENDING, nullable=False, index=True) # VARCHAR
    stripe_payment_intent_id = Column(String(255), unique=True, nullable=True)
    stripe_charge_id = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    failure_reason = Column(Text, nullable=True)
    refund_id = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=ist_now)
    updated_at = Column(DateTime, default=ist_now, onupdate=ist_now)

    customer = relationship("User", foreign_keys=[customer_id], back_populates="payments")
    booking = relationship("Booking", foreign_keys=[booking_id], uselist=False)
    logs = relationship("PaymentLog", back_populates="payment", cascade="all, delete-orphan")


class PaymentLog(Base):
    """Table to log every event/webhook related to a payment."""
    __tablename__ = "payment_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    payment_id = Column(String(36), ForeignKey("payments.id", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(100), nullable=False) # e.g. payment_intent.succeeded
    payload = Column(Text, nullable=True) # JSON raw response
    created_at = Column(DateTime, default=ist_now)

    payment = relationship("Payment", back_populates="logs")

