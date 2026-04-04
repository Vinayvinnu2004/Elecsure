"""app/models/el_score.py — EL Score change log."""

import uuid
from datetime import datetime
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship
from app.core.database import Base
from app.core.security import ist_now

# EL Score Event Constants
class ELScoreEvent:
    SLOT_COMPLETED = "slot_completed"           # +2 per slot completed (daily 3 = bonus)
    SLOT_FAILED = "slot_failed"                 # -5 (turned off during slot)
    SLOT_CANCELLED = "slot_cancelled"           # -3
    BOOKING_COMPLETED = "booking_completed"     # +5
    BOOKING_FAST = "booking_fast"               # +3 (completed quickly)
    BOOKING_SKIPPED = "booking_skipped"         # -10 (didn't accept)
    BOOKING_CANCELLED_BY_ELEC = "booking_cancelled_by_elec"  # -8
    REVIEW_5_STAR = "review_5_star"             # +4
    REVIEW_4_STAR = "review_4_star"             # +2
    REVIEW_3_STAR = "review_3_star"             # 0
    REVIEW_2_STAR = "review_2_star"             # -2
    REVIEW_1_STAR = "review_1_star"             # -5
    DAILY_AVAILABILITY = "daily_availability"   # +1
    THREE_SLOTS_DAY = "three_slots_day"         # +5 bonus
    TOOLKIT_ADVANCED = "toolkit_advanced"       # +3
    SKILL_ADDED = "skill_added"                 # +1 per skill
    AVAILABILITY_MID_SLOT = "availability_mid_slot"  # -7 (turned off mid-slot)
    RECALCULATION_ADJUSTMENT = "recalculation_adjustment"  # Formula jump (e.g. probation end)

SCORE_DELTAS = {
    ELScoreEvent.SLOT_COMPLETED: 2,
    ELScoreEvent.SLOT_FAILED: -5,
    ELScoreEvent.SLOT_CANCELLED: -3,
    ELScoreEvent.BOOKING_COMPLETED: 5,
    ELScoreEvent.BOOKING_FAST: 3,
    ELScoreEvent.BOOKING_SKIPPED: -10,
    ELScoreEvent.BOOKING_CANCELLED_BY_ELEC: -8,
    ELScoreEvent.REVIEW_5_STAR: 4,
    ELScoreEvent.REVIEW_4_STAR: 2,
    ELScoreEvent.REVIEW_3_STAR: 0,
    ELScoreEvent.REVIEW_2_STAR: -2,
    ELScoreEvent.REVIEW_1_STAR: -5,
    ELScoreEvent.DAILY_AVAILABILITY: 1,
    ELScoreEvent.THREE_SLOTS_DAY: 5,
    ELScoreEvent.TOOLKIT_ADVANCED: 3,
    ELScoreEvent.SKILL_ADDED: 0,
    ELScoreEvent.AVAILABILITY_MID_SLOT: -7,
    ELScoreEvent.RECALCULATION_ADJUSTMENT: 0,
}


class ELScoreLog(Base):
    __tablename__ = "el_score_logs"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()), index=True)
    electrician_id = Column(String(36), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    event = Column(String(50), nullable=False)
    delta = Column(Float, nullable=False)
    score_before = Column(Float, nullable=False)
    score_after = Column(Float, nullable=False)
    notes = Column(Text, nullable=True)
    booking_id = Column(String(36), ForeignKey("bookings.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime, default=ist_now)

    electrician = relationship("User", back_populates="el_score_logs")
