"""app/routers/earnings.py - Electrician earnings API."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.dependencies import require_electrician
from app.models.user import User
from app.schemas.earnings import EarningsSummary
from app.services.earning_service import get_restriction_status, clear_commission_due
from app.schemas.common import MessageOut

router = APIRouter(prefix="/api/v1/earnings", tags=["Earnings"])

from sqlalchemy import select
from app.models.earnings import ElectricianEarning

@router.get("/", response_model=EarningsSummary)
async def get_earnings(user: User = Depends(require_electrician), db: AsyncSession = Depends(get_db)):
    """Retrieve earning summary for the current electrician."""
    from sqlalchemy.orm import joinedload
    # Need to load earnings explicitly or retrieve from db
    r = await db.execute(select(ElectricianEarning).where(ElectricianEarning.electrician_id == user.id))
    earnings = r.scalar_one_or_none()
    
    # We must also fetch the user again with earnings loaded for the get_restriction_status, or simply re-implement it briefly
    is_restricted = False
    message = None
    if earnings:
        if earnings.commission_due > 3000:
            is_restricted = True
            message = "Account restricted. Please clear your commission balance to ₹0 to resume work."
        elif earnings.commission_due > 2000:
            message = "Warning: Your commission balance is high (> 2,000). Avoid restriction at 3,000."
    
    return EarningsSummary(
        daily_earning=earnings.daily_earning if earnings else 0.0,
        weekly_earning=earnings.weekly_earning if earnings else 0.0,
        total_lifetime_earning=earnings.total_lifetime_earning if earnings else 0.0,
        commission_due=earnings.commission_due if earnings else 0.0,
        is_restricted=is_restricted,
        restriction_message=message
    )

@router.post("/clear-commission-mock", response_model=MessageOut)
async def clear_commission_mock(amount: float, user: User = Depends(require_electrician), db: AsyncSession = Depends(get_db)):
    """Mock endpoint to clear commission due (as if payment happened)."""
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Amount must be positive")
        
    success = await clear_commission_due(db, str(user.id), amount)
    if success:
        return MessageOut(message=f"Commission cleared by {amount}. Updated status reflected immediately.")
    raise HTTPException(status_code=500, detail="Failed to clear commission")

@router.get("/history")
async def get_earnings_history(user: User = Depends(require_electrician), db: AsyncSession = Depends(get_db)):
    """Retrieve history of all completed bookings with earnings for this electrician."""
    from sqlalchemy.orm import joinedload
    from app.models.booking import Booking, STATUS_COMPLETED, STATUS_REVIEWED

    r = await db.execute(
        select(Booking).options(joinedload(Booking.service))
        .where(
            Booking.electrician_id == user.id,
            Booking.earning_calculated == True,   # Only bookings where earnings were recorded
            Booking.status.in_([STATUS_COMPLETED, STATUS_REVIEWED]),
        ).order_by(Booking.completed_at.desc())
    )
    bookings = r.scalars().all()

    history = []
    for b in bookings:
        # Detect midnight bonus: slot start between 12AM–6AM
        midnight_bonus = 0.0
        is_midnight_slot = False
        if b.time_slot_start:
            hour = b.time_slot_start.hour
            if 0 <= hour < 6:
                midnight_bonus = 50.0
                is_midnight_slot = True

        # Format the time slot window label
        slot_label = None
        if b.time_slot_start and b.time_slot_end:
            def fmt_time(dt):
                return dt.strftime("%I:%M %p").lstrip("0")
            slot_label = f"{fmt_time(b.time_slot_start)} – {fmt_time(b.time_slot_end)}"

        history.append({
            "booking_id": str(b.id),
            "service_name": b.service.name if b.service else "Custom Service",
            "amount": float(b.total_amount or 0.0),
            "midnight_bonus": midnight_bonus,
            "is_midnight_slot": is_midnight_slot,
            "slot_label": slot_label,
            "date": b.completed_at.isoformat() if b.completed_at else (b.created_at.isoformat() if b.created_at else None),
        })
    return history

