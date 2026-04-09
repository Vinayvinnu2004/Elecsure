"""
app/services/el_score_service.py — Multi-component EL Score engine.

Formula (post-probation, 10+ jobs):
  EL = 0.25*rating + 0.10*review_vol + 0.10*toolkit + 0.15*cancel + 0.20*failed + 0.10*daily + 0.10*experience

Probation (< 10 jobs):
  EL = 0.30*toolkit + 0.25*availability + 0.25*slot_reliability + 0.20*acceptance
  Base starts at 65, gets +2 per completed job.

New electricians are included in fair exposure (top-2 experienced + top-1 probation).
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from app.models import (
    User, ELScoreLog, ELScoreEvent, SCORE_DELTAS, 
    TimeSlot, SLOT_AVAILABLE, SLOT_BOOKED, SLOT_COMPLETED, SLOT_FAILED, SLOT_CANCELLED,
    Booking, STATUS_COMPLETED, STATUS_REVIEWED, ElectricianProfile
)
from app.core.security import ist_now

MIN_SCORE, MAX_SCORE = 0.0, 100.0
PROBATION_JOBS = 10
STARTER_BASE   = 65.0
STARTER_BONUS_PER_JOB = 2.0
logger = logging.getLogger(__name__)


# ── Component scorers ─────────────────────────────────────────────────

def _rating_score(avg_rating: float, total_reviews: int) -> float:
    if total_reviews == 0:
        return 50.0
    base = (avg_rating / 5.0) * 100.0
    if total_reviews < 5:
        base *= 0.75  # trust reduction for few reviews
    return min(100.0, base)


def _review_volume_score(total_reviews: int) -> float:
    if total_reviews == 0:      return 20.0
    if total_reviews <= 5:      return 40.0
    if total_reviews <= 20:     return 70.0
    if total_reviews <= 50:     return 85.0
    return 100.0


def _toolkit_score(toolkit: str) -> float:
    return {"basic": 60.0, "advanced": 80.0, "both": 100.0}.get(str(toolkit).lower(), 30.0)


def _cancellation_score(total_accepted: int, cancelled: int) -> float:
    if total_accepted == 0:
        return 100.0
    rate = cancelled / total_accepted
    if rate <= 0.05:  return 100.0
    if rate <= 0.10:  return 80.0
    if rate <= 0.20:  return 60.0
    if rate <= 0.30:  return 40.0
    return 20.0


def _failed_slot_score(failed_slots: int, total_bookings: int) -> float:
    if total_bookings == 0:
        return 100.0
    rate = failed_slots / total_bookings
    if rate == 0:     return 100.0
    if rate <= 0.03:  return 80.0
    if rate <= 0.10:  return 50.0
    return 20.0


def _daily_slot_score(completed_today: int) -> float:
    if completed_today >= 3: return 100.0
    if completed_today == 2: return 70.0
    if completed_today == 1: return 40.0
    return 20.0


def _experience_score(total_completed: int) -> float:
    if total_completed <= 10:   return 30.0
    if total_completed <= 50:   return 60.0
    if total_completed <= 150:  return 80.0
    return 100.0


def _availability_score(is_available: bool) -> float:
    return 100.0 if is_available else 20.0


def _speed_score(avg_mins: float) -> float:
    if avg_mins <= 0: return 100.0
    if avg_mins <= 30: return 100.0
    if avg_mins <= 60: return 85.0
    if avg_mins <= 90: return 60.0
    if avg_mins <= 120: return 40.0
    return 20.0


# ── Full EL score calculation ─────────────────────────────────────────

async def calculate_el_score(db: AsyncSession, electrician_id: str) -> float:
    from sqlalchemy.orm import joinedload
    r = await db.execute(
        select(User).options(joinedload(User.electrician_profile))
        .where(User.id == electrician_id)
    )
    elec = r.scalar_one_or_none()
    if not elec or not elec.electrician_profile:
        return STARTER_BASE

    profile = elec.electrician_profile

    # Count completed jobs and calculate average time
    r_completed = await db.execute(
        select(Booking).where(
            Booking.electrician_id == electrician_id,
            Booking.status.in_([STATUS_COMPLETED, STATUS_REVIEWED]),
        )
    )
    completed_bookings = r_completed.scalars().all()
    total_completed = len(completed_bookings)
    
    completion_times = []
    for b in completed_bookings:
        if b.accepted_at and b.completed_at:
            mins = (b.completed_at - b.accepted_at).total_seconds() / 60
            completion_times.append(mins)
    avg_completion_min = round(sum(completion_times) / len(completion_times), 1) if completion_times else 0.0

    # Count cancelled slots
    r_cancelled = await db.execute(
        select(func.count(TimeSlot.id)).where(
            TimeSlot.electrician_id == electrician_id,
            TimeSlot.status == SLOT_CANCELLED,
        )
    )
    cancelled_slots = r_cancelled.scalar() or 0

    # Count failed slots
    r_failed = await db.execute(
        select(func.count(TimeSlot.id)).where(
            TimeSlot.electrician_id == electrician_id,
            TimeSlot.status == SLOT_FAILED,
        )
    )
    failed_slots = r_failed.scalar() or 0

    # Count total accepted slots
    r_accepted = await db.execute(
        select(func.count(TimeSlot.id)).where(
            TimeSlot.electrician_id == electrician_id,
            TimeSlot.status.in_([SLOT_BOOKED, SLOT_COMPLETED, SLOT_CANCELLED]),
        )
    )
    total_accepted = r_accepted.scalar() or 0

    # Count slots completed today
    import pytz
    from datetime import datetime
    IST = pytz.timezone("Asia/Kolkata")
    today = datetime.now(IST).date()
    r_today = await db.execute(
        select(func.count(TimeSlot.id)).where(
            TimeSlot.electrician_id == electrician_id,
            TimeSlot.status == SLOT_COMPLETED,
            func.date(TimeSlot.slot_date) == today,
        )
    )
    completed_today = r_today.scalar() or 0

    toolkit = str(profile.toolkit)
    avg_rating = float(profile.rating or 0.0)
    total_reviews = profile.total_reviews or 0
    is_available = profile.is_available or False

    # ── PROBATION PHASE (< 10 jobs) ───────────────────────────────────
    if total_completed < PROBATION_JOBS:
        toolkit_s = _toolkit_score(toolkit)
        avail_s   = _availability_score(is_available)
        slot_rel  = _cancellation_score(total_accepted, cancelled_slots)
        # Acceptance rate from bookings
        r_assigned = await db.execute(
            select(func.count(Booking.id)).where(
                Booking.electrician_id == electrician_id,
            )
        )
        total_assigned = r_assigned.scalar() or 0
        acceptance_rate_s = (total_completed / total_assigned * 100) if total_assigned > 0 else 80.0

        acceptance_rate_s = (total_completed / total_assigned * 100) if total_assigned > 0 else 80.0
        speed_s   = _speed_score(avg_completion_min)

        probation_score = (
            0.25 * toolkit_s +
            0.20 * avail_s +
            0.20 * slot_rel +
            0.20 * acceptance_rate_s +
            0.15 * speed_s
        )
        # Apply starter base + per-job bonus
        final = STARTER_BASE + (total_completed * STARTER_BONUS_PER_JOB)
        # Blend with component score
        final = (final * 0.5) + (probation_score * 0.5)
        # Strictly cap probation at 75 to not outrank elite experienced pros
        final = min(final, 75.0)
        return round(max(MIN_SCORE, min(MAX_SCORE, final)), 2)


    # ── FULL FORMULA (10+ jobs) ───────────────────────────────────────
    rating_s      = _rating_score(avg_rating, total_reviews)
    review_s      = _review_volume_score(total_reviews)
    toolkit_s     = _toolkit_score(toolkit)
    cancel_s      = _cancellation_score(total_accepted, cancelled_slots)
    failed_s      = _failed_slot_score(failed_slots, total_completed)
    daily_s       = _daily_slot_score(completed_today)
    experience_s  = _experience_score(total_completed)
    speed_s       = _speed_score(avg_completion_min)

    el_score = (
        0.25 * rating_s +
        0.10 * review_s +
        0.10 * toolkit_s +
        0.10 * cancel_s +
        0.15 * failed_s +
        0.10 * daily_s +
        0.10 * experience_s +
        0.10 * speed_s
    )
    return round(max(MIN_SCORE, min(MAX_SCORE, el_score)), 2)


# ── Event-based delta (for quick log updates) ─────────────────────────

async def apply_el_event(
    db: AsyncSession,
    electrician_id: str,
    event: str,
    booking_id: str | None = None,
    notes: str | None = None,
    override_delta: float | None = None,
) -> float:
    from sqlalchemy.orm import joinedload
    r = await db.execute(
        select(User).options(joinedload(User.electrician_profile))
        .where(User.id == electrician_id)
    )
    elec = r.scalar_one_or_none()
    if not elec or not elec.electrician_profile:
        return 0.0

    profile = elec.electrician_profile

    # Count completed jobs for probation check
    r_comp = await db.execute(
        select(func.count(Booking.id)).where(
            Booking.electrician_id == electrician_id,
            Booking.status.in_([STATUS_COMPLETED, STATUS_REVIEWED]),
        )
    )
    total_completed = r_comp.scalar() or 0

    if override_delta is not None:
        delta = override_delta
    else:
        delta = SCORE_DELTAS.get(event, 0)
        # Halve penalties during probation (first 10 jobs)
        if total_completed < PROBATION_JOBS and delta < 0:
            delta = delta * 0.5  # softer penalties in probation

    from datetime import timedelta
    now = ist_now()
    event_ts = now - timedelta(seconds=2)  # backdate event so adjustment floats to top

    score_before = float(profile.el_score or STARTER_BASE)
    score_after  = max(MIN_SCORE, min(MAX_SCORE, score_before + float(delta)))
    profile.el_score = score_after

    # Write event log with backdated timestamp — it will appear below the adjustment entry
    if delta != 0.0 or "review" in event:
        log = ELScoreLog(
            electrician_id=electrician_id,
            event=event,
            delta=delta,
            score_before=score_before,
            score_after=score_after,
            notes=notes,
            booking_id=booking_id,
            created_at=event_ts,
        )
        db.add(log)

    # After logging delta, do a full recalculation for accuracy
    if event not in (ELScoreEvent.DAILY_AVAILABILITY,):
        try:
            recalc = await calculate_el_score(db, electrician_id)
            if abs(recalc - score_after) > 0.01:
                # Build a clear note for the adjustment
                recalc_notes = f"Formula recalculation adjustment (Event: {event})"
                if total_completed < PROBATION_JOBS and recalc == 75.0 and score_after > 75.0:
                    recalc_notes = "EL Score capped at 75.0 during your first 10 orders (Probation Phase). Complete more orders to unlock higher scores!"
                elif total_completed >= PROBATION_JOBS and (score_before <= PROBATION_JOBS * STARTER_BONUS_PER_JOB + STARTER_BASE):
                    if event == ELScoreEvent.BOOKING_COMPLETED and total_completed == PROBATION_JOBS:
                        recalc_notes = "🎉 Graduated from Probation to Experienced status!"

                # Adjustment log gets current timestamp — appears on top of the event log
                adj_log = ELScoreLog(
                    electrician_id=electrician_id,
                    event=ELScoreEvent.RECALCULATION_ADJUSTMENT,
                    delta=round(recalc - score_after, 2),
                    score_before=score_after,
                    score_after=recalc,
                    notes=recalc_notes,
                    booking_id=booking_id,
                    created_at=now,
                )
                db.add(adj_log)

            profile.el_score = recalc
            score_after = recalc
        except Exception as e:
            logger.error(f"Recalculation error for {electrician_id}: {e}")

    # ── Notification ──
    if score_after < 40 and score_before >= 40:
        from app.services.notification_service import notify_elec_low_score_warning
        import asyncio
        asyncio.create_task(notify_elec_low_score_warning(elec.email, elec.name, score_after, elec.phone))

    return score_after


async def apply_review_score(
    db: AsyncSession, electrician_id: str, rating: int, booking_id: str, comment: str | None = None
) -> float:
    event_map = {
        5: ELScoreEvent.REVIEW_5_STAR, 4: ELScoreEvent.REVIEW_4_STAR,
        3: ELScoreEvent.REVIEW_3_STAR, 2: ELScoreEvent.REVIEW_2_STAR,
        1: ELScoreEvent.REVIEW_1_STAR,
    }
    # Use comment as notes if provided, otherwise default
    notes = comment if comment else f"{rating}-star review"
    return await apply_el_event(
        db, electrician_id, event_map.get(rating, ELScoreEvent.REVIEW_3_STAR),
        booking_id=booking_id, notes=notes,
    )


async def check_daily_bonus(db: AsyncSession, electrician_id: str, date_ist) -> None:
    # 1. Count slots completed today (for 3-slot bonus)
    r = await db.execute(
        select(func.count(TimeSlot.id)).where(
            TimeSlot.electrician_id == electrician_id,
            TimeSlot.status == SLOT_COMPLETED,
            func.date(TimeSlot.slot_date) == date_ist.date(),
        )
    )
    completed_today = r.scalar() or 0
    
    # 2. Count availability hours
    r_avail = await db.execute(
        select(func.count(TimeSlot.id)).where(
            TimeSlot.electrician_id == electrician_id,
            TimeSlot.status.in_([SLOT_AVAILABLE, SLOT_BOOKED, SLOT_COMPLETED]),
            func.date(TimeSlot.slot_date) == date_ist.date()
        )
    )
    total_avail_slots = r_avail.scalar() or 0

    if total_avail_slots >= 6:
        await apply_el_event(db, electrician_id, ELScoreEvent.DAILY_AVAILABILITY,
                              notes=f"Full Day Availability (>= 6 hours) on {date_ist.date()}")
    
    if completed_today >= 3:
        await apply_el_event(db, electrician_id, ELScoreEvent.THREE_SLOTS_DAY,
                              notes=f"3 slots completed on {date_ist.date()}")


async def recalculate_score(db: AsyncSession, electrician_id: str) -> float:
    score = await calculate_el_score(db, electrician_id)
    r = await db.execute(
        select(User).options(joinedload(User.electrician_profile))
        .where(User.id == electrician_id)
    )
    elec = r.scalar_one_or_none()
    if elec and elec.electrician_profile:
        elec.electrician_profile.el_score = score
    return score

