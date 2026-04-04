"""app/routers/slots.py — Electrician time slot management with predefined slot types."""

import logging
from datetime import datetime, timedelta
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
import pytz

from app.core.database import get_db
from app.core.dependencies import require_electrician
from app.core.security import ist_now
from app.core.constants import TIME_SLOTS, SLOT_TYPE_LABELS
from app.models import (
    TimeSlot, SLOT_AVAILABLE, SLOT_BOOKED, SLOT_COMPLETED, SLOT_FAILED, SLOT_CANCELLED, SLOT_OVER,
    User, ROLE_ELECTRICIAN, ServiceArea, ElectricianProfile
)
from app.schemas.user import TimeSlotIn, TimeSlotOut
from app.schemas.common import MessageOut

router = APIRouter(prefix="/api/v1/slots", tags=["Slots"])
logger = logging.getLogger(__name__)
IST = pytz.timezone("Asia/Kolkata")


def _current_week_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(IST).replace(tzinfo=None)
    monday = now - timedelta(days=now.weekday())
    week_start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    week_end   = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)
    if now > week_end:
        week_start += timedelta(weeks=1)
        week_end   += timedelta(weeks=1)
    return week_start, week_end


@router.get("/available-week")
async def get_available_week():
    start, end = _current_week_bounds()
    return {"week_start": start, "week_end": end}


@router.get("/slot-types")
async def get_slot_types():
    """Return predefined slot windows with labels and surcharges."""
    return [
        {
            "id":        s["id"],
            "label":     s["label"],
            "type":      s["type"],
            "type_label": SLOT_TYPE_LABELS[s["type"]],
            "surcharge": s["surcharge"],
        }
        for s in TIME_SLOTS
    ]


@router.get("/my", response_model=List[TimeSlotOut])
async def get_my_slots(
    user: User = Depends(require_electrician),
    db: AsyncSession = Depends(get_db),
    history: bool = Query(False, description="Get all failed/completed historical slots"),
):
    now = ist_now()
    if history:
        r = await db.execute(
            select(TimeSlot).where(
                TimeSlot.electrician_id == user.id,
                and_(
                    TimeSlot.status.in_([SLOT_FAILED, SLOT_COMPLETED, SLOT_CANCELLED, SLOT_AVAILABLE, SLOT_BOOKED, SLOT_OVER]),
                    TimeSlot.end_time < now
                )
            ).order_by(TimeSlot.start_time.desc())
        )
    else:
        week_start, week_end = _current_week_bounds()
        r = await db.execute(
            select(TimeSlot).where(
                TimeSlot.electrician_id == user.id,
                TimeSlot.slot_date >= week_start,
                TimeSlot.slot_date <= week_end,
            ).order_by(TimeSlot.start_time)
        )
    
    slots = r.scalars().all()
    # Auto-update status for past slots
    changed = False
    for s in slots:
        if s.end_time < now:
            if s.status == SLOT_AVAILABLE:
                s.status = SLOT_OVER
                s.status_updated_at = now
                changed = True
            elif s.status == SLOT_BOOKED or s.status == SLOT_COMPLETED:
                if s.violated_mid_slot:
                    s.status = SLOT_FAILED
                    s.status_updated_at = now
                    changed = True
                elif s.status == SLOT_BOOKED:
                    s.status = SLOT_COMPLETED
                    s.auto_completed_at = now
                    s.status_updated_at = now
                    changed = True
            
    if changed:
        await db.commit()
    
    return slots


@router.post("/", response_model=TimeSlotOut, status_code=201)
async def create_slot(
    data: TimeSlotIn,
    user: User = Depends(require_electrician),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Your account is pending admin verification. You cannot create slots yet.")
        
    week_start, week_end = _current_week_bounds()
    slot_date_naive = data.slot_date.replace(tzinfo=None)

    if slot_date_naive < week_start or slot_date_naive > week_end:
        raise HTTPException(
            status_code=400,
            detail=f"Slots can only be created for {week_start.date()} – {week_end.date()}",
        )
    
    if data.end_time.replace(tzinfo=None) < ist_now():
        raise HTTPException(status_code=400, detail="Cannot create a slot in the past.")

    if data.start_time >= data.end_time:
        raise HTTPException(status_code=400, detail="Start time must be before end time")

    # Overlap check
    r = await db.execute(
        select(TimeSlot).where(
            TimeSlot.electrician_id == user.id,
            TimeSlot.status.in_([SLOT_AVAILABLE, SLOT_BOOKED]),
            TimeSlot.start_time < data.end_time,
            TimeSlot.end_time > data.start_time,
        )
    )
    if r.scalars().first():
        raise HTTPException(status_code=400, detail="Slot is already booked")

    # Determine initial status
    initial_status = SLOT_BOOKED
    if data.end_time.replace(tzinfo=None) <= ist_now():
        initial_status = SLOT_FAILED

    slot = TimeSlot(
        electrician_id=user.id,
        slot_date=data.slot_date,
        start_time=data.start_time,
        end_time=data.end_time,
        status=initial_status,
        created_at=ist_now(),
    )
    db.add(slot)
    await db.flush()
    await db.refresh(slot)
    return slot


@router.delete("/{slot_id}", response_model=MessageOut)
async def delete_slot(
    slot_id: str,
    user: User = Depends(require_electrician),
    db: AsyncSession = Depends(get_db),
):
    slot = await db.get(TimeSlot, slot_id)
    if not slot or slot.electrician_id != user.id:
        raise HTTPException(status_code=404, detail="Slot not found")
    
    now_ist = ist_now()
    if slot.end_time < now_ist:
        raise HTTPException(status_code=400, detail="Cannot delete a past slot.")

    if slot.status == SLOT_COMPLETED:
        raise HTTPException(status_code=400, detail="Cannot delete a completed slot.")

    # Rule: Always apply penalty for deleting an active/future slot (Commitment Breach)
    from app.services.el_score_service import apply_el_event
    from app.models import ELScoreEvent
    await apply_el_event(db, str(user.id), ELScoreEvent.SLOT_CANCELLED,
                        notes=f"Slot commitment {slot_id} cancelled by electrician")
    
    await db.delete(slot)
    await db.commit()

    return MessageOut(message="Slot cancelled. A small EL Score penalty has been applied for commitment breach.")


@router.get("/public/{pincode}")
async def get_available_slots_for_pincode(
    pincode: str,
    date: str = Query(None, description="YYYY-MM-DD"),
    db: AsyncSession = Depends(get_db),
):
    """Returns predefined available slot windows for a pincode (used in booking form)."""
    now = ist_now()
    week_start, week_end = _current_week_bounds()

    # Check which slot windows have available electricians for this pincode
    available_windows = []

    for slot_def in TIME_SLOTS:
        # Build datetime for the query date (or today)
        if date:
            try:
                target_date = datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                target_date = datetime.now(IST).replace(tzinfo=None)
        else:
            target_date = datetime.now(IST).replace(tzinfo=None)

        start_h, start_m = map(int, slot_def["start"].split(":"))
        end_h,   end_m   = map(int, slot_def["end"].split(":"))

        slot_start = target_date.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
        # Handle midnight crossing
        if end_h == 0:
            slot_end = (target_date + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        else:
            slot_end = target_date.replace(hour=end_h, minute=end_m, second=0, microsecond=0)

        if slot_end <= now:
            continue  # skip past slots

        # Find actual TimeSlot DB record for this window
        r = await db.execute(
            select(TimeSlot).join(
                User, TimeSlot.electrician_id == User.id
            ).join(
                ElectricianProfile, TimeSlot.electrician_id == ElectricianProfile.user_id
            ).join(
                ServiceArea, and_(
                    ServiceArea.electrician_id == User.id,
                    ServiceArea.pincode == pincode,
                )
            ).where(
                TimeSlot.status == SLOT_AVAILABLE,
                TimeSlot.start_time <= slot_end,
                TimeSlot.end_time >= slot_start,
                User.role == ROLE_ELECTRICIAN,
                User.is_active.isnot(False),
                User.is_verified == True,
                ElectricianProfile.is_available == True,
            ).limit(1)
        )
        matched_slot = r.scalars().first()

        available_windows.append({
            "slot_id":     slot_def["id"],          # string label key e.g. "06-09"
            "db_slot_id":  str(matched_slot.id) if matched_slot else None,  # UUID string
            "label":       slot_def["label"],
            "type":        slot_def["type"],
            "type_label":  SLOT_TYPE_LABELS[slot_def["type"]],
            "surcharge":   slot_def["surcharge"],
            "start_time":  slot_start.isoformat(),
            "end_time":    slot_end.isoformat(),
            "available":   matched_slot is not None,
        })

    return available_windows

