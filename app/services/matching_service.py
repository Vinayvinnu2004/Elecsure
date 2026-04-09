"""
app/services/matching_service.py — EL Score–based electrician matching with sub-skill matching.

Assignment priority:
  1. Filter: availability + area (pincode) + main skill/sub-skill + slot overlap
  2. Separate: Group A (experienced, 10+ jobs) vs Group B (probation)
  3. Pick top 2 from A + top 1 from B for fair exposure
  4. Sort each group by EL Score descending
  5. Send to highest EL score first; fallback if not accepted in 10 min
"""

from __future__ import annotations
import logging
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, func

from app.models import (
    Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
    CANCEL_MANUAL, CANCEL_SYSTEM, CANCEL_ELECTRICIAN,
    TimeSlot, SLOT_AVAILABLE, SLOT_BOOKED, SLOT_COMPLETED, SLOT_FAILED, SLOT_CANCELLED,
    User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN, ServiceArea, ElectricianProfile, Service,
)
from app.core.security import ist_now
from app.core.config import settings

logger = logging.getLogger(__name__)
PROBATION_JOBS = 10


# ── Skill matching ────────────────────────────────────────────────────

def _has_skill(electrician: User, service_name: str) -> bool:
    """Check if electrician's skills include the requested service by mapping it through Taxonomy."""
    profile = electrician.electrician_profile
    if not profile or not profile.skills:
        return False
        
    from app.core.constants import SERVICES_TAXONOMY
    
    elec_skills = [s.strip().lower() for s in profile.skills.split(",")]
    elec_primary = profile.primary_skill.strip().lower() if profile.primary_skill else ""
    svc = service_name.strip().lower()
    
    # Reverse lookup to find the category and subcategory this service belongs to
    target_cat = ""
    target_subcat = ""
    
    for cat_name, cat_data in SERVICES_TAXONOMY.items():
        for subcat_name, services in cat_data.get("subcategories", {}).items():
            for s in services:
                if s.strip().lower() == svc:
                    target_cat = cat_name.strip().lower()
                    target_subcat = subcat_name.strip().lower()
                    break
            if target_cat: break
        if target_cat: break

    # If we found the service in our taxonomy, check against its parent categories
    if target_cat and target_subcat:
        if elec_primary and (elec_primary in target_cat or target_cat in elec_primary):
            return True
        for es in elec_skills:
            if es in target_subcat or target_subcat in es:
                return True
                
    # Fallback: Direct text matching (useful for custom/legacy services)
    if svc in elec_skills:
        return True
    for skill in elec_skills:
        if skill in svc or svc in skill:
            return True
    if elec_primary:
        if elec_primary in svc or svc in elec_primary:
            return True
            
    return False


def _covers_area(service_areas: list, pincode: str) -> bool:
    return any(sa.pincode == pincode for sa in service_areas)


async def _count_completed(db: AsyncSession, electrician_id: str) -> int:
    r = await db.execute(
        select(func.count(Booking.id)).where(
            Booking.electrician_id == electrician_id,
            Booking.status.in_([STATUS_COMPLETED, STATUS_REVIEWED]),
        )
    )
    return r.scalar() or 0


async def _get_candidates(
    db: AsyncSession,
    service_name: str,
    pincode: str,
    slot_start: Optional[datetime],
    slot_end: Optional[datetime],
    exclude_ids: list[str] = None,
) -> tuple[list[User], list[User]]:
    """
    Returns (group_a_experienced, group_b_probation) sorted by EL score desc.
    """
    exclude_ids = exclude_ids or []

    from app.models import Booking, BookingStatus

    # Identify electricians who are already busy with an active order (ASSIGNED, ACCEPTED, or STARTED)
    busy_elecs_subq = select(Booking.electrician_id).where(
        Booking.status.in_([STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED]),
        Booking.electrician_id != None
    )
    res_busy = await db.execute(busy_elecs_subq)
    # result rows are tuples, first element is electrician_id which is now str
    busy_ids = [str(r[0]) for r in res_busy.all()]

    r = await db.execute(
        select(User).join(ElectricianProfile).where(
            User.role == ROLE_ELECTRICIAN,
            User.is_verified == True,         # only verified electricians
            ElectricianProfile.is_available.isnot(False),   # treat NULL as available
            ElectricianProfile.is_restricted.isnot(True),   # exclude restricted accounts
            User.is_active.isnot(False),       # treat NULL as active
            User.id.notin_(exclude_ids + busy_ids) if (exclude_ids or busy_ids) else True,
        ).order_by(ElectricianProfile.el_score.desc())
    )
    all_elec = r.scalars().all()

    group_a, group_b = [], []

    for elec in all_elec:
        await db.refresh(elec, ["service_areas", "time_slots", "electrician_profile"])

        if not _has_skill(elec, service_name):
            continue
        if not _covers_area(elec.service_areas, pincode):
            continue

        if slot_start and slot_end:
            # Only SLOT_BOOKED means the electrician is committed and ready for orders
            # during that window. COMPLETED/FAILED are past historical records.
            has_slot = any(
                s.status == SLOT_BOOKED
                and s.start_time < slot_end
                and s.end_time > slot_start
                for s in elec.time_slots
            )
            if not has_slot:
                continue

        completed = await _count_completed(db, str(elec.id))
        if completed >= PROBATION_JOBS:
            group_a.append(elec)
        else:
            group_b.append(elec)

    return group_a, group_b


async def _get_priority_role(db: AsyncSession) -> str:
    """
    Checks the most recent booking that had an assignment attempt
    and toggles the role for the current booking.
    """
    try:
        # Find the last booking that was successfully assigned (had an electrician_id)
        r = await db.execute(
            select(Booking).where(Booking.electrician_id != None)
            .order_by(Booking.created_at.desc(), Booking.id.desc()).limit(1)
        )
        last_booking = r.scalar_one_or_none()
        
        if not last_booking:
            return "pro"  # Default start

        # Check if the electrician assigned to that booking was a pro or probationer
        # We check the role of the electrician who was given the FIRST chance 
        # (This is more robust than just checking the final winner)
        elec_r = await db.execute(select(User).where(User.id == last_booking.electrician_id))
        elec = elec_r.scalar_one_or_none()
        if not elec: return "pro"
        
        completed = await _count_completed(db, str(elec.id))
        last_role = "pro" if completed >= PROBATION_JOBS else "probation"
        
        # Toggle
        return "probation" if last_role == "pro" else "pro"
    except Exception as e:
        logger.error(f"Error determining priority role: {e}")
        return "pro"


def _get_ordered_pool(group_a: list[User], group_b: list[User], priority_role: str) -> list[User]:
    """
    Arranges top 1 Pro and top 2 Probationers into an ordered list based on priority_role.
    """
    best_pro = group_a[:1]
    best_probationers = group_b[:2]
    
    if priority_role == "pro":
        # Pro gets first chance, then probationers
        return best_pro + best_probationers
    else:
        # Probationer gets first chance, then pro, then remaining probationer
        if len(best_probationers) > 0:
            first_prob = [best_probationers[0]]
            second_prob = best_probationers[1:]
            return first_prob + best_pro + second_prob
        return best_pro


def _mask(phone: str) -> str:
    return "****" + phone[-4:] if phone and len(phone) >= 4 else "****"


async def _do_assign(db: AsyncSession, booking: Booking, elec: User) -> bool:
    now = ist_now()
    booking.electrician_id = elec.id
    booking.status = STATUS_ASSIGNED
    booking.assigned_at = now
    booking.assignment_attempts = (booking.assignment_attempts or 0) + 1
    booking.last_assignment_at = now
    booking.accepted_deadline = now + timedelta(minutes=settings.ASSIGNMENT_TIMEOUT_MINUTES)
    return True


# ── Public assignment functions ───────────────────────────────────────

async def assign_booking(db: AsyncSession, booking: Booking) -> bool:
    if not booking.service:
        await db.refresh(booking, ["service"])

    # 1. Get raw candidates sorted by EL score
    group_a, group_b = await _get_candidates(
        db,
        service_name=booking.service.name,
        pincode=booking.pincode,
        slot_start=booking.time_slot_start,
        slot_end=booking.time_slot_end,
    )
    
    # 2. Determine whose turn it is
    priority = await _get_priority_role(db)
    
    # 3. Create ordered pool
    pool = _get_ordered_pool(group_a, group_b, priority)
    
    if not pool:
        return False
        
    # Pick the first one (Priority #1)
    return await _do_assign(db, booking, pool[0])


async def reassign_booking(db: AsyncSession, booking: Booking) -> bool:
    prev_id = booking.electrician_id
    if not booking.service:
        await db.refresh(booking, ["service"])

    # Filter candidates excluding previous attempt
    group_a, group_b = await _get_candidates(
        db,
        service_name=booking.service.name,
        pincode=booking.pincode,
        slot_start=booking.time_slot_start,
        slot_end=booking.time_slot_end,
        exclude_ids=[str(prev_id)] if prev_id else [],
    )
    
    # Determine the priority that was used for this booking initially
    # or just toggle from the previous attempt's role.
    elec_r = await db.execute(select(User).where(User.id == prev_id))
    prev_elec = elec_r.scalar_one_or_none()
    
    priority = "pro"
    if prev_elec:
        comp = await _count_completed(db, str(prev_elec.id))
        prev_role = "pro" if comp >= PROBATION_JOBS else "probation"
        priority = "probation" if prev_role == "pro" else "pro"
    else:
        priority = await _get_priority_role(db)

    pool = _get_ordered_pool(group_a, group_b, priority)
    
    if pool:
        from app.services.el_score_service import apply_el_event
        from app.models import ELScoreEvent
        if prev_id:
            await apply_el_event(
                db, str(prev_id), ELScoreEvent.BOOKING_SKIPPED,
                booking_id=str(booking.id),
                notes="Did not accept within 10 minutes",
            )
        return await _do_assign(db, booking, pool[0])
    return False


async def fallback_assign(db: AsyncSession, booking: Booking) -> tuple[bool, str]:
    if not booking.service:
        await db.refresh(booking, ["service"])

    now = ist_now()
    svc  = booking.service.name
    pin  = booking.pincode

    prev_elec_id = booking.electrician_id
    
    # --- STEP 1: Try remaining time in current slot (excluding previous electrician) ---
    if booking.time_slot_end and booking.time_slot_end > now:
        ga, gb = await _get_candidates(db, svc, pin, now, booking.time_slot_end, exclude_ids=[str(prev_elec_id)] if prev_elec_id else [])
        priority = await _get_priority_role(db)
        pool = _get_ordered_pool(ga, gb, priority)
        best = pool[0] if pool else None
        if best:
            await _do_assign(db, booking, best)
            return True, f"Reassigned to prioritized candidate {best.name} within original slot"

    # --- STEP 2: Handle Next Slot OR Cancellation ---
    
    # If already rescheduled once AND the slot has completed/failed, then CANCEL.
    if booking.is_auto_rescheduled:
        booking.status = STATUS_CANCELLED
        booking.cancellation_type = CANCEL_SYSTEM
        booking.cancellation_reason = "booking is cancelled due to insufficient of electricians"
        booking.cancelled_at = now
        booking.electrician_id = None
        booking.assigned_at = None
        booking.accepted_deadline = None
        return False, "CANCELLED: No electrician available after rescheduling"

    # Try next available slots (excluding previous electrician)
    r = await db.execute(
        select(TimeSlot).join(User).join(ElectricianProfile).where(
            and_(
                TimeSlot.slot_date >= (booking.preferred_date or now),
                TimeSlot.start_time > (booking.time_slot_end or now),
                TimeSlot.status == SLOT_BOOKED,
                User.is_verified == True,     # only verified electricians
                User.id != prev_elec_id if prev_elec_id else True,
            )
        ).order_by(TimeSlot.start_time)
    )
    next_slots = r.scalars().all()

    for slot in next_slots:
        await db.refresh(slot, ["electrician"])
        elec = slot.electrician
        if not elec: continue
        await db.refresh(elec, ["electrician_profile", "service_areas"])
        profile = elec.electrician_profile
        
        if (
            profile and profile.is_available and not profile.is_restricted and elec.is_active
            and _has_skill(elec, svc)
            and _covers_area(elec.service_areas, pin)
        ):
            booking.time_slot_start = slot.start_time
            booking.time_slot_end   = slot.end_time
            booking.time_slot_id    = slot.id
            booking.is_auto_rescheduled = True  # STRIKE 1: Rescheduled once
            
            await _do_assign(db, booking, elec)
            return True, f"Reassigned to candidate {elec.name} in next slot {slot.start_time}"

    # --- STEP 3: No Next Candidate Found ---
    
    # If NO next candidate found at all, CANCEL immediately.
    booking.status = STATUS_CANCELLED
    booking.cancellation_type = CANCEL_SYSTEM
    booking.cancellation_reason = "booking is cancelled due to insufficient of electricians"
    booking.cancelled_at = now
    booking.electrician_id = None
    booking.assigned_at = None
    booking.accepted_deadline = None
    booking.electrician_phone_masked = None
    
    return False, "CANCELLED: No electrician available in next slots"


async def assign_all_pending(db: AsyncSession) -> list[Booking]:
    from app.core.security import ist_now
    now = ist_now()
    r = await db.execute(
        select(Booking).where(
            Booking.status == STATUS_REQUESTED,
            Booking.electrician_id == None,
            # (Remove the time_slot_start <= now constraint to allow for earlier pre-assignment)
        )
    )
    pending = r.scalars().all()
    assigned_bookings = []
    for b in pending:
        await db.refresh(b, ["service"])
        if await assign_booking(db, b):
            assigned_bookings.append(b)
    if assigned_bookings:
        await db.commit()
    return assigned_bookings
