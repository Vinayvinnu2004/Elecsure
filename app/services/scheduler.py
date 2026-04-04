"""
app/services/scheduler.py — APScheduler background jobs for notifications and maintenance.
"""

import logging
import random
import asyncio
from datetime import datetime, timedelta
import pytz
from sqlalchemy import select, func, and_, or_
from sqlalchemy.orm import joinedload
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.core.config import settings
from app.core.security import ist_now, generate_secure_token
from app.services.earning_service import reset_daily_earnings, generate_weekly_reports_and_reset
from app.models import (
    User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN, 
    Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
    TimeSlot, SLOT_AVAILABLE, SLOT_BOOKED, SLOT_COMPLETED, SLOT_FAILED, SLOT_CANCELLED,
    ELScoreLog, ElectricianProfile, CustomerProfile, ActionToken, CANCEL_SYSTEM, ELScoreEvent
)
from app.services.el_score_service import apply_el_event
from app.services.matching_service import reassign_booking, fallback_assign, assign_all_pending
from app.services.notification_service import (
    notify_promo, PROMO_MESSAGES,
    # note: some names were slightly different in my previous attempt
    notify_elec_slot_reminder, notify_elec_new_order, notify_booking_cancelled, 
    notify_elec_order_timeout_warning,
    notify_booking_cancelled_timeout_apology,
    notify_elec_order_timeout_penalty,
    notify_elec_weekly_summary,
    notify_elec_availability_reminder
)

IST = pytz.timezone(settings.TIMEZONE)
logger = logging.getLogger(__name__)
scheduler = AsyncIOScheduler(timezone=IST)


# ── Customer Promotions ───────────────────────────────────

async def send_daily_promotions():
    """Daily 12 PM: Send randomized promo messages to inactive customers."""
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            seven_days_ago = ist_now() - timedelta(days=7)
            q = select(User).where(User.role == ROLE_CUSTOMER, User.is_active.isnot(False))
            customers = (await db.execute(q)).scalars().all()
            
            month = ist_now().month
            is_summer = 3 <= month <= 6
            is_monsoon = 7 <= month <= 8
            
            for cust in customers:
                last_b = await db.execute(select(Booking).where(Booking.customer_id == cust.id).order_by(Booking.created_at.desc()).limit(1))
                lb = last_b.scalar_one_or_none()
                if lb and lb.created_at > seven_days_ago:
                    continue
                
                valid_indices = []
                for i, msg in enumerate(PROMO_MESSAGES):
                    if "AC" in msg or "Summer" in msg:
                        if not is_summer: continue
                    if "Monsoon" in msg or "earthing" in msg:
                        if not is_monsoon: continue
                    valid_indices.append(i)
                
                if not valid_indices:
                    valid_indices = list(range(len(PROMO_MESSAGES)))
                
                idx = random.choice(valid_indices)
                extra_data = {}
                if "{days_ago}" in PROMO_MESSAGES[idx]:
                    extra_data["days_ago"] = (ist_now() - lb.created_at).days if lb else 30
                
                await notify_promo(cust.email, cust.phone, cust.name, idx, extra_data)
            
            await db.commit()
            logger.info("Daily promotions sent.")
    except Exception as e:
        logger.error("send_daily_promotions error: %s", e)


async def electrician_slot_reminders():
    """Daily 9 AM: Remind electricians of their bookings."""
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            now = ist_now()
            week_end = now + timedelta(days=7)
            elecs = (await db.execute(select(User).where(User.role == ROLE_ELECTRICIAN, User.is_active.isnot(False)))).scalars().all()
            for elec in elecs:
                res = await db.execute(select(func.count(TimeSlot.id)).where(TimeSlot.electrician_id == elec.id, TimeSlot.status == SLOT_BOOKED, TimeSlot.start_time >= now, TimeSlot.start_time < week_end))
                count = res.scalar() or 0
                if count > 0:
                    await notify_elec_slot_reminder(elec.email, elec.name, count, elec.phone)
            logger.info("Electrician slot reminders sent.")
    except Exception as e:
        logger.error("electrician_slot_reminders error: %s", e)

# ── Maintenance Job ──────────────────────────────────────────────────

async def fallback_check():
    """Check for assignment timeouts and clean up REQUESTED bookings."""
    try:
        from app.core.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            now = ist_now()
            
            # 1. Warning for jobs about to timeout
            warning_limit = now + timedelta(minutes=2) 
            r_warn = await db.execute(select(Booking).options(joinedload(Booking.electrician), joinedload(Booking.service)).where(
                Booking.status == STATUS_ASSIGNED,
                Booking.accepted_deadline <= warning_limit,
                Booking.accepted_deadline > now
            ))
            for b in r_warn.scalars().all():
                if b.electrician:
                    asyncio.create_task(notify_elec_order_timeout_warning(
                        b.electrician.email, b.electrician.name, 
                        b.service.name if b.service else "Service", 
                        str(b.id), b.electrician.phone
                    ))

            # 2. Reassignment for timed out jobs
            r = await db.execute(select(Booking).options(joinedload(Booking.electrician), joinedload(Booking.customer), joinedload(Booking.service)).where(
                Booking.status == STATUS_ASSIGNED,
                Booking.accepted_deadline <= now,
            ))
            timed_out = r.scalars().all()
            for booking in timed_out:
                if (booking.assignment_attempts or 0) >= 3:
                    booking.status = STATUS_CANCELLED
                    booking.cancellation_type = CANCEL_SYSTEM
                    booking.cancellation_reason = "Booking cancelled: No electrician accepted within 30 minutes."
                    booking.cancelled_at = now
                    
                    if booking.electrician:
                        await apply_el_event(db, str(booking.electrician_id), ELScoreEvent.BOOKING_SKIPPED, booking_id=str(booking.id), notes="Timeout")
                        asyncio.create_task(notify_elec_order_timeout_penalty(booking.electrician.email, booking.electrician.name, str(booking.id), booking.electrician.phone))
                    
                    if booking.customer:
                        asyncio.create_task(notify_booking_cancelled_timeout_apology(booking.customer.email, booking.customer.name, str(booking.id), booking.customer.phone))
                    continue

                if await reassign_booking(db, booking):
                    new_elec = await db.get(User, booking.electrician_id)
                    if new_elec:
                        token_str = generate_secure_token()
                        at = ActionToken(user_id=str(new_elec.id), booking_id=str(booking.id), token=token_str, action="accept", expires_at=now + timedelta(minutes=10))
                        db.add(at)
                        await db.flush()
                        accept_url = f"{settings.BASE_URL}/api/v1/bookings/action/{token_str}"
                        ist_time = (booking.time_slot_start or booking.preferred_date).strftime("%d %b %Y %I:%M %p")
                        asyncio.create_task(notify_elec_new_order(
                            new_elec.email, new_elec.name, str(booking.id), 
                            booking.service.name if booking.service else "Service",
                            booking.customer.name if booking.customer else "Customer",
                            booking.address, ist_time, accept_url, new_elec.phone,
                        ))

            # 3. Handle REQUESTED bookings whose time has passed
            r_req = await db.execute(select(Booking).options(joinedload(Booking.customer)).where(
                Booking.status == STATUS_REQUESTED,
                or_(and_(Booking.time_slot_end != None, Booking.time_slot_end <= now),
                    and_(Booking.time_slot_end == None, Booking.preferred_date < now - timedelta(days=1)))
            ))
            for b in r_req.scalars().all():
                b.status = STATUS_CANCELLED
                b.cancellation_type = CANCEL_SYSTEM
                b.cancellation_reason = "No electrician found in time."
                b.cancelled_at = now
                if b.customer:
                    asyncio.create_task(notify_booking_cancelled(b.customer.email, b.customer.name, str(b.id), b.cancellation_reason, b.customer.phone))

            # 4. Periodically try matching pending
            await assign_all_pending(db)

            await db.commit()
    except Exception as e:
        logger.error("fallback_check error: %s", e)


def start_scheduler():
    scheduler.add_job(fallback_check, trigger=IntervalTrigger(seconds=settings.FALLBACK_CHECK_INTERVAL_SECONDS), id="fallback_check", replace_existing=True)
    scheduler.add_job(send_daily_promotions, trigger=CronTrigger(hour=12, minute=0), id="promo", replace_existing=True)
    scheduler.add_job(electrician_slot_reminders, trigger=CronTrigger(hour=9, minute=0), id="slot_reminders", replace_existing=True)
    
    from app.core.database import AsyncSessionLocal
    async def _daily_reset():
        async with AsyncSessionLocal() as db: await reset_daily_earnings(db)
    async def _weekly_reset():
        async with AsyncSessionLocal() as db: await generate_weekly_reports_and_reset(db)

    scheduler.add_job(_daily_reset, trigger=CronTrigger(hour=23, minute=59), id="daily_earning_reset", replace_existing=True)
    scheduler.add_job(_weekly_reset, trigger=CronTrigger(day_of_week='sun', hour=23, minute=59), id="weekly_earning_reset", replace_existing=True)
    
    scheduler.start()
    logger.info("APScheduler started.")

def stop_scheduler():
    if scheduler.running:
        scheduler.shutdown(wait=False)
