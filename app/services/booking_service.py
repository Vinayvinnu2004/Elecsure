"""app/services/booking_service.py — Core booking lifecycle logic."""

import logging
from typing import Optional, List, Dict, Any
from datetime import timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from fastapi import HTTPException
from sqlalchemy.orm import joinedload

from app.core.constants import KARIMNAGAR_PINCODES, GEOFENCE_RADIUS_KM, KARIMNAGAR_BOUNDS
from app.core.security import ist_now, generate_secure_token
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models import (
    User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN,
    Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, 
    STATUS_ARRIVED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
    CANCEL_MANUAL, CANCEL_SYSTEM, CANCEL_ELECTRICIAN,
    TimeSlot, SLOT_AVAILABLE, SLOT_BOOKED, SLOT_COMPLETED, SLOT_FAILED, SLOT_CANCELLED,
    Service, Review, ActionToken, ELScoreEvent, BookingHistory, ElectricianProfile,
)
from app.schemas.booking import BookingCreate, ReviewCreate
from app.services.matching_service import assign_booking
from app.services.notification_service import (
    notify_booking_created, notify_booking_assigned, notify_elec_new_order, notify_booking_cancelled,
    notify_booking_accepted, notify_elec_order_accepted, notify_booking_arrived,
    notify_booking_started, notify_elec_service_started, notify_booking_completed,
    notify_elec_service_completed, notify_review_given, notify_elec_review_received
)
from app.services.earning_service import calculate_booking_earning
from app.services.el_score_service import apply_el_event, apply_review_score

logger = logging.getLogger(__name__)

async def record_history(db: AsyncSession, booking_id: str, status: str, notes: str = None, changed_by: str = None):
    # If changed_by is "system" or not a valid UUID, set changed_by_id to None
    # Assuming UUID-like string. If "system", it won't match a user ID.
    import uuid
    cb_id = None
    if changed_by and changed_by != "system":
        try:
            # Simple check if it looks like a UUID
            uuid.UUID(str(changed_by))
            cb_id = str(changed_by)
        except:
            cb_id = None

    history = BookingHistory(
        booking_id=booking_id,
        new_status=status,
        comment=notes,
        changed_by_id=cb_id,
        created_at=ist_now()
    )
    db.add(history)

def _get_distance_km(lat1, lon1, lat2, lon2):
    import math
    R = 6371.0 # Earth radius
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.asin(math.sqrt(a))
    return R * c

def _bg_task(coro_func, *args, **kwargs):
    import asyncio
    async def _wrapped():
        async with AsyncSessionLocal() as db:
            try:
                await coro_func(db, *args, **kwargs)
                await db.commit()
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Background task failed")
    asyncio.create_task(_wrapped())

class BookingService:

    @staticmethod
    async def create_booking(db: AsyncSession, user: User, data: BookingCreate) -> Booking:
        # 1. Geofence validation
        pin_data = KARIMNAGAR_PINCODES.get(data.pincode)
        if not pin_data:
            raise HTTPException(status_code=400, detail="Service not available in this pincode")
        
        dist = _get_distance_km(data.latitude, data.longitude, pin_data["lat"], pin_data["lng"])
        if dist > GEOFENCE_RADIUS_KM:
            raise HTTPException(status_code=400, detail=f"Location must be within {GEOFENCE_RADIUS_KM}km of the pincode center")

        # 2. Fetch service to get pricing
        r_svc = await db.execute(select(Service).where(Service.id == data.service_id))
        svc = r_svc.scalar_one_or_none()
        if not svc:
            raise HTTPException(status_code=400, detail="Requested service no longer exists")

        now = ist_now()
        booking = Booking(
            customer_id=user.id,
            service_id=data.service_id,
            preferred_date=data.preferred_date,
            time_slot_id=data.time_slot_id,
            time_slot_start=data.time_slot_start,
            time_slot_end=data.time_slot_end,
            address=data.address,
            pincode=data.pincode,
            district=data.district or "Karimnagar",
            state=data.state or "Telangana",
            latitude=data.latitude,
            longitude=data.longitude,
            problem_description=data.problem_description,
            payment_type=data.payment_type or "online",
            total_amount=svc.base_price,
            status=STATUS_REQUESTED,
            created_at=now,
            updated_at=now
        )
        db.add(booking)
        await db.flush()
        
        # Record initial history
        await record_history(db, booking.id, STATUS_REQUESTED, notes="Booking created", changed_by=user.id)
        
        # Start assignment & notification logic
        async def _match_and_notify(bg_db: AsyncSession, b_id: str):
            import asyncio
            # RACE CONDITION FIX: Give the main request session (in get_db) a moment to commit.
            # Without this, the background session might try to select the booking before it exists in DB.
            await asyncio.sleep(0.5)
            
            r = await bg_db.execute(
                select(Booking)
                .options(joinedload(Booking.service), joinedload(Booking.customer))
                .where(Booking.id == b_id)
            )
            b = r.scalar_one_or_none()
            if b:
                if await assign_booking(bg_db, b):
                    await record_history(bg_db, b.id, b.status, notes="Electrician assigned auto", changed_by="system")
                    await notify_booking_assigned(bg_db, b)
                    await notify_elec_new_order(bg_db, b)
                await notify_booking_created(bg_db, b)
            else:
                logger.error(f"Background task could not find booking {b_id} even after delay.")

        _bg_task(_match_and_notify, str(booking.id))
        
        return booking

    @staticmethod
    async def get_booking_by_id(db: AsyncSession, booking_id: str, user_id: str = None, role: str = None) -> Booking:
        q = select(Booking).where(Booking.id == booking_id).options(
            joinedload(Booking.service), joinedload(Booking.customer),
            joinedload(Booking.electrician), joinedload(Booking.review)
        )
        r = await db.execute(q)
        b = r.scalar_one_or_none()
        if not b: raise HTTPException(status_code=404, detail="Booking not found")
        
        # Auth check
        if role == ROLE_CUSTOMER and str(b.customer_id) != user_id: raise HTTPException(status_code=403, detail="Forbidden")
        if role == ROLE_ELECTRICIAN and str(b.electrician_id) != user_id: raise HTTPException(status_code=403, detail="Forbidden")
        
        return b

    @staticmethod
    async def cancel_booking(db: AsyncSession, user: User, booking_id: str) -> Booking:
        b = await BookingService.get_booking_by_id(db, booking_id, user_id=str(user.id), role=ROLE_CUSTOMER)
        if b.status not in [STATUS_REQUESTED, STATUS_ASSIGNED]:
            raise HTTPException(status_code=400, detail="Cannot cancel after acceptance")
        
        b.status = STATUS_CANCELLED
        b.cancellation_type = CANCEL_MANUAL
        b.updated_at = ist_now()
        
        await record_history(db, b.id, STATUS_CANCELLED, notes="Cancelled by customer", changed_by=user.id)
        # Slot status is NOT changed here. Slots are purely about the electrician's time commitment,
        # not about booking outcomes. The slot remains BOOKED until its end time is reached.

        await db.commit()
        
        async def _notify_cancel(bg_db, b_id):
            r = await bg_db.execute(select(Booking).where(Booking.id == b_id))
            if (b := r.scalar_one_or_none()): await notify_booking_cancelled(bg_db, b)
        
        _bg_task(_notify_cancel, b.id)
        return b

    @staticmethod
    async def submit_review(db: AsyncSession, user: User, booking_id: str, data: ReviewCreate) -> Review:
        b = await BookingService.get_booking_by_id(db, booking_id, user_id=str(user.id), role=ROLE_CUSTOMER)
        if b.status != STATUS_COMPLETED:
            raise HTTPException(status_code=400, detail="Can only review completed bookings")
        
        existing = await db.execute(select(Review).where(Review.booking_id == booking_id))
        if existing.scalar(): raise HTTPException(status_code=400, detail="Review already exists")

        rev = Review(
            booking_id=booking_id,
            customer_id=user.id,
            electrician_id=b.electrician_id,
            rating=data.rating,
            comment=data.comment,
            created_at=ist_now()
        )
        db.add(rev)
        b.status = STATUS_REVIEWED
        
        await record_history(db, b.id, STATUS_REVIEWED, notes=f"Review given: {data.rating} stars", changed_by=user.id)

        if b.electrician_id:
            # ── Update rating aggregate BEFORE EL recalculation ──────────────
            # calculate_el_score() reads profile.rating + profile.total_reviews.
            # If we don't update them now the recalculation uses stale pre-review
            # values and produces a negative "Recalculation Adjustment" that
            # cancels out the review bonus.
            r_prof = await db.execute(
                select(ElectricianProfile).where(ElectricianProfile.user_id == b.electrician_id)
            )
            prof = r_prof.scalar_one_or_none()
            if prof:
                old_total  = prof.total_reviews or 0
                old_rating = float(prof.rating or 0.0)
                new_total  = old_total + 1
                new_rating = round(((old_rating * old_total) + data.rating) / new_total, 2)
                prof.total_reviews = new_total
                prof.rating        = new_rating
            await apply_review_score(db, str(b.electrician_id), data.rating, b.id, comment=data.comment)

        await db.commit()
        
        # Background notifications
        async def _notify_review(bg_db, rev_id):
            r = await bg_db.execute(select(Review).where(Review.id == rev_id).options(joinedload(Review.booking)))
            if (rv := r.scalar_one_or_none()):
                await notify_review_given(bg_db, rv)
                if rv.booking and rv.booking.electrician_id:
                    await notify_elec_review_received(bg_db, rv)
        
        _bg_task(_notify_review, rev.id)
        return rev

    @staticmethod
    async def transition_status(db: AsyncSession, booking_id: str, action: str, current_user: User = None) -> Booking:
        b = await BookingService.get_booking_by_id(db, booking_id)
        now = ist_now()
        uid = current_user.id if current_user else "system"
        
        if action == "accept":
            if b.status != STATUS_ASSIGNED: raise HTTPException(status_code=400, detail="Order not available")
            b.status = STATUS_ACCEPTED
            b.accepted_at = now
            await record_history(db, b.id, STATUS_ACCEPTED, notes="Electrician accepted", changed_by=uid)
            
            async def _n_accept(bg_db, bid):
                r = await bg_db.execute(select(Booking).where(Booking.id == bid))
                if (bx := r.scalar_one_or_none()):
                    await notify_booking_accepted(bg_db, bx)
                    await notify_elec_order_accepted(bg_db, bid)
            _bg_task(_n_accept, b.id)
        
        elif action == "arrived":
            if b.status != STATUS_ACCEPTED: raise HTTPException(status_code=400, detail="Invalid transition")
            b.status = STATUS_ARRIVED
            b.arrived_at = now
            await record_history(db, b.id, STATUS_ARRIVED, notes="Electrician arrived", changed_by=uid)
            
            async def _n_arrive(bg_db, bid):
                r = await bg_db.execute(select(Booking).where(Booking.id == bid))
                if (bx := r.scalar_one_or_none()): await notify_booking_arrived(bg_db, bx)
            _bg_task(_n_arrive, b.id)
        
        elif action == "start":
            if b.status not in [STATUS_ACCEPTED, STATUS_ARRIVED]: raise HTTPException(status_code=400, detail="Invalid transition")
            b.status = STATUS_STARTED
            b.started_at = now
            await record_history(db, b.id, STATUS_STARTED, notes="Service started", changed_by=uid)
            
            async def _n_start(bg_db, bid):
                r = await bg_db.execute(select(Booking).where(Booking.id == bid))
                if (bx := r.scalar_one_or_none()):
                    await notify_booking_started(bg_db, bx)
                    await notify_elec_service_started(bg_db, bid)
            _bg_task(_n_start, b.id)
            
        elif action == "complete":
            if b.status != STATUS_STARTED: raise HTTPException(status_code=400, detail="Invalid transition")
            b.status = STATUS_COMPLETED
            b.completed_at = now
            await calculate_booking_earning(db, b.id)
            await apply_el_event(db, str(b.electrician_id), ELScoreEvent.BOOKING_COMPLETED, booking_id=b.id)
            await record_history(db, b.id, STATUS_COMPLETED, notes="Service completed", changed_by=uid)
            
            async def _n_complete(bg_db, bid):
                r = await bg_db.execute(select(Booking).where(Booking.id == bid))
                if (bx := r.scalar_one_or_none()):
                    await notify_booking_completed(bg_db, bx)
                    await notify_elec_service_completed(bg_db, bid)
            _bg_task(_n_complete, b.id)
            # Slot status is NOT changed here. Slots are finalized independently
            # by the scheduler (end-of-slot check) and the availability toggle logic.
            
        else:
            raise HTTPException(status_code=400, detail="Invalid action")

        b.updated_at = now
        await db.commit()
        return b

