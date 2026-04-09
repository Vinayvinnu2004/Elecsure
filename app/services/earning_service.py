"""app/services/earning_service.py - Calculation and restriction logic."""

import logging
from datetime import datetime, timedelta
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import (User, ROLE_ELECTRICIAN, 
                        Booking, STATUS_COMPLETED,
                        WeeklyReport, ElectricianProfile, ElectricianEarning)
from app.core.config import settings
from app.core.security import ist_now

logger = logging.getLogger(__name__)

def _bg_task(coro):
    import asyncio
    asyncio.create_task(coro)

async def calculate_booking_earning(db: AsyncSession, booking_id: str):
    """
    Calculate and update earnings for a completed booking.
    Ensures idempotency using booking.earning_calculated flag.
    """
    # 1. Load booking with electrician and profile
    from sqlalchemy.orm import joinedload
    r = await db.execute(
        select(Booking).options(
            joinedload(Booking.electrician).options(
                joinedload(User.earnings),
                joinedload(User.electrician_profile)
            )
        )
        .where(Booking.id == booking_id)
    )
    booking = r.scalar_one_or_none()
    
    if not booking:
        logger.error(f"Booking {booking_id} not found for earnings calculation")
        return

    # Check if already calculated or not completed
    if booking.earning_calculated or booking.status != STATUS_COMPLETED:
        return

    if not booking or not booking.electrician:
        logger.warning(f"Booking {booking_id} has no electrician assigned")
        return

    earnings = booking.electrician.earnings
    if not earnings:
        # Create earning record if it doesn't exist
        earnings = ElectricianEarning(electrician_id=booking.electrician_id)
        db.add(earnings)

    # 2. Perform calculations
    from decimal import Decimal
    service_base_price = booking.total_amount or Decimal("0.0")
    
    # Midnight Bonus Logic (12 AM to 6 AM slots)
    extra_night_bonus = Decimal("0.0")
    if booking.time_slot_start:
        hour = booking.time_slot_start.hour
        # If slot starts at 12 AM (0) or later, but before 6 AM
        if 0 <= hour < 6:
            extra_night_bonus = Decimal("50.0")
            logger.info(f"Booking {booking_id} qualified for ₹50 midnight bonus (Start: {booking.time_slot_start})")

    commission_amount = service_base_price * Decimal(str(settings.COMMISSION_RATE))
    # Earning includes the base price plus any night bonus
    electrician_earning = service_base_price + extra_night_bonus

    # 3. Update Earning Record
    # Update counters
    earnings.daily_earning = (earnings.daily_earning or Decimal("0.0")) + electrician_earning
    earnings.weekly_earning = (earnings.weekly_earning or Decimal("0.0")) + electrician_earning
    earnings.total_lifetime_earning = (earnings.total_lifetime_earning or Decimal("0.0")) + electrician_earning
    earnings.commission_due = (earnings.commission_due or Decimal("0.0")) + commission_amount

    # 4. Restriction Check
    if earnings.commission_due > 3000:
        logger.info(f"Electrician {booking.electrician_id} reached commission limit ({earnings.commission_due}). Restricted mode automatically enabled.")
        if booking.electrician.electrician_profile:
            if not booking.electrician.electrician_profile.is_restricted:
                # Trigger email if state is changing to restricted
                from app.services import notification_service
                _bg_task(notification_service.notify_elec_restricted(
                    booking.electrician.email, 
                    booking.electrician.name, 
                    float(earnings.commission_due)
                ))
            
            booking.electrician.electrician_profile.is_restricted = True
            # Automatically turn off availability when restricted
            booking.electrician.electrician_profile.is_available = False
    
    # 5. Mark booking as calculated
    booking.earning_calculated = True
    
    # Commit handled by caller to ensure atomicity
    # await db.commit()
    logger.info(f"Updated earnings for booking {booking_id}. Elec earning: {electrician_earning}, Commission: {commission_amount}")

async def reset_daily_earnings(db: AsyncSession):
    """Reset all electricians' daily earnings at midnight."""
    await db.execute(
        update(ElectricianEarning)
        .values(daily_earning=0.0)
    )
    await db.commit()
    logger.info("Daily earnings reset successfully")

async def generate_weekly_reports_and_reset(db: AsyncSession):
    """
    Generate weekly historical reports for all electricians and reset weekly counters.
    Triggered on Sunday 11:59 PM.
    """
    # Find all electricians with non-zero earnings
    r = await db.execute(
        select(ElectricianEarning).where(ElectricianEarning.weekly_earning > 0)
    )
    all_earnings = r.scalars().all()
    
    now = ist_now()
    week_start = now - timedelta(days=7)
    
    for earning in all_earnings:
        report = WeeklyReport(
            electrician_id=earning.electrician_id,
            total_earned=earning.weekly_earning,
            commission_due=earning.commission_due,
            week_start=week_start,
            week_end=now
        )
        db.add(report)
        
        # Reset weekly counter
        earning.weekly_earning = 0.0
        
    await db.commit()
    logger.info("Weekly reports generated and earnings reset")

def get_restriction_status(elec: User):
    """Determine if an electrician is restricted based on commission due or explicit admin restriction."""
    if elec.electrician_profile and elec.electrician_profile.is_restricted:
        return True, "Account in Restricted Mode. You cannot receive new order assignments."
        
    earnings = elec.earnings
    if not earnings:
        return False, None
    if earnings.commission_due > 3000:
        return True, "Account in Restricted Mode. Please clear your commission balance to start receiving orders."
    elif earnings.commission_due > 2000:
        return False, "Warning: Your commission balance is high (> 2,000). Avoid restriction mode at 3,000."
    return False, None

async def clear_commission_due(db: AsyncSession, electrician_id: str, amount: float):
    """Clear (pay) commission for an electrician."""
    r = await db.execute(
        select(ElectricianEarning).where(ElectricianEarning.electrician_id == electrician_id)
    )
    earnings = r.scalar_one_or_none()
    if not earnings:
        return False
    
    earnings.commission_due = (earnings.commission_due or 0.0) - amount
    
    # Auto-unrestrict if they dropped below the high threshold
    if earnings.commission_due <= 3000:
        r_prof = await db.execute(
            select(ElectricianProfile).where(ElectricianProfile.user_id == electrician_id)
        )
        if p := r_prof.scalar_one_or_none():
            if p.is_restricted:
                p.is_restricted = False
                # Automatically turn ON availability when restriction is lifted
                p.is_available = True
                
                if u:
                    _bg_task(notification_service.notify_elec_unrestricted(u.email, u.name))
                
                logger.info(f"Electrician {electrician_id} balance cleared. Restricted Mode removed and availability restored.")
    
    await db.commit()
    return True

