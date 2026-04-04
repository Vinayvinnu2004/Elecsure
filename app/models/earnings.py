"""app/models/earnings.py - Weekly earnings reports."""

import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Numeric, UniqueConstraint
from app.core.database import Base
from app.core.security import ist_now

from sqlalchemy.orm import relationship

class ElectricianEarning(Base):
    """Table to store denormalized up-to-date earnings to avoid constant aggregations."""
    __tablename__ = "electrician_earnings"
    __table_args__ = (UniqueConstraint("electrician_id", name="uq_elec_earning"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    electrician_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True, index=True)
    
    daily_earning = Column(Numeric(10, 2), default=0.0)
    weekly_earning = Column(Numeric(10, 2), default=0.0)
    total_lifetime_earning = Column(Numeric(10, 2), default=0.0)
    commission_due = Column(Numeric(10, 2), default=0.0)
    
    updated_at = Column(DateTime, default=ist_now, onupdate=ist_now)

    electrician = relationship("User", back_populates="earnings")


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"
    __table_args__ = (UniqueConstraint("electrician_id", "week_start", name="uq_elec_week"),)

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    electrician_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    total_earned = Column(Numeric(10, 2), nullable=False)
    commission_due = Column(Numeric(10, 2), nullable=False)
    
    week_start = Column(DateTime, nullable=False)
    week_end = Column(DateTime, nullable=False)
    
    created_at = Column(DateTime, default=ist_now)

    electrician = relationship("User", back_populates="weekly_reports")
