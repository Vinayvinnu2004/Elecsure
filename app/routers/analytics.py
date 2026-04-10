"""app/routers/analytics.py — Customer and Electrician analytics endpoints."""

import logging
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import ist_now
from app.models import (
    User, Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
    Payment, Review, TimeSlot, ElectricianProfile
)

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])
logger = logging.getLogger(__name__)


@router.get("/customer")
async def customer_analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import pytz
    from datetime import datetime
    IST = pytz.timezone("Asia/Kolkata")
    now = ist_now()

    from sqlalchemy.orm import joinedload
    # Single query with JOIN — eliminates N+1 refresh loop
    all_bookings = (await db.execute(
        select(Booking).options(joinedload(Booking.service))
        .where(Booking.customer_id == user.id)
    )).scalars().all()

    status_counts = {}
    for b in all_bookings:
        s = b.status
        status_counts[s] = status_counts.get(s, 0) + 1

    total         = len(all_bookings)
    completed     = status_counts.get(STATUS_COMPLETED, 0) + status_counts.get(STATUS_REVIEWED, 0)
    cancelled     = status_counts.get(STATUS_CANCELLED, 0)
    ongoing       = status_counts.get(STATUS_STARTED, 0)
    requested     = status_counts.get(STATUS_REQUESTED, 0)
    accepted      = status_counts.get(STATUS_ACCEPTED, 0)
    assigned      = status_counts.get(STATUS_ASSIGNED, 0)

    # Service usage
    svc_count: dict = {}
    cat_count: dict = {}
    total_spent = 0.0
    for b in all_bookings:
        if b.service:
            svc_count[b.service.name] = svc_count.get(b.service.name, 0) + 1
            cat_count[b.service.category] = cat_count.get(b.service.category, 0) + 1
        if b.is_paid or b.status in (STATUS_COMPLETED, STATUS_REVIEWED):
            total_spent += float(b.total_amount or 0.0)

    most_requested_svc = max(svc_count, key=svc_count.get) if svc_count else "—"
    most_requested_cat = max(cat_count, key=cat_count.get) if cat_count else "—"
    avg_cost = round(total_spent / completed, 2) if completed > 0 else 0.0



    # Monthly spending (current month)
    monthly_spent = sum(
        float(b.total_amount or 0.0) for b in all_bookings
        if (b.is_paid or b.status in (STATUS_COMPLETED, STATUS_REVIEWED)) and b.created_at
        and b.created_at.month == now.month
        and b.created_at.year == now.year
    )

    return {
        "booking_status_overview": {
            "total_bookings": total,
            "completed": completed,
            "cancelled": cancelled,
            "ongoing": ongoing,
        },
        "service_usage": {
            "most_requested_service": most_requested_svc,
            "most_requested_category": most_requested_cat,
            "service_breakdown": dict(sorted(svc_count.items(), key=lambda x: -x[1])[:5]),
            "category_breakdown": cat_count,
        },
        "spending": {
            "total_spent": round(total_spent, 2),
            "avg_cost_per_service": avg_cost,
            "monthly_spending": round(monthly_spent, 2),
        },
    }


@router.get("/electrician")
async def electrician_analytics(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import pytz
    from datetime import datetime
    IST = pytz.timezone("Asia/Kolkata")
    now = ist_now()

    from sqlalchemy.orm import joinedload
    # Load user with profile and earnings
    r_u = await db.execute(select(User).options(joinedload(User.electrician_profile), joinedload(User.earnings)).where(User.id == user.id))
    user = r_u.scalar_one()
    profile = user.electrician_profile
    earnings = user.earnings

    all_bookings = (await db.execute(
        select(Booking).options(joinedload(Booking.service))
        .where(Booking.electrician_id == user.id)
    )).scalars().all()

    status_counts: dict = {}
    total_earnings = 0.0
    svc_count: dict = {}
    cat_count: dict = {}
    completion_times = []

    for b in all_bookings:
        s = b.status
        status_counts[s] = status_counts.get(s, 0) + 1
        if b.status in (STATUS_COMPLETED, STATUS_REVIEWED):
            # For electricians, any completed job means they earned the money (whether COD or Online)
            total_earnings += float(b.total_amount or 0.0)
            if b.accepted_at and b.completed_at:
                mins = (b.completed_at - b.accepted_at).total_seconds() / 60
                completion_times.append(mins)
        if b.service:
            svc_count[b.service.name] = svc_count.get(b.service.name, 0) + 1
            cat_count[b.service.category] = cat_count.get(b.service.category, 0) + 1

    total         = len(all_bookings)
    completed     = status_counts.get(STATUS_COMPLETED, 0) + status_counts.get(STATUS_REVIEWED, 0)
    assigned      = status_counts.get(STATUS_ASSIGNED, 0)
    accepted      = status_counts.get(STATUS_ACCEPTED, 0)
    rejected      = status_counts.get(STATUS_CANCELLED, 0)
    active        = status_counts.get(STATUS_STARTED, 0)

    # Dynamic Earnings Calculation (Robust against scheduler misses)
    daily_earnings = 0.0
    weekly_earnings = 0.0
    monthly_earnings = 0.0

    for b in all_bookings:
        if b.status in (STATUS_COMPLETED, STATUS_REVIEWED):
            val = float(b.total_amount or 0.0)
            
            # Re-apply midnight bonus logic for accurate analytics display
            if b.time_slot_start and 0 <= b.time_slot_start.hour < 6:
                val += 50.0

            if b.completed_at:
                # 1. Daily (IST Today)
                if b.completed_at.date() == now.date():
                    daily_earnings += val
                
                # 2. Weekly (Last 7 days)
                if (now - b.completed_at).days < 7:
                    weekly_earnings += val
                
                # 3. Monthly (Current Calendar Month)
                if b.completed_at.month == now.month and b.completed_at.year == now.year:
                    monthly_earnings += val

    avg_job_value      = round(total_earnings / completed, 2) if completed > 0 else 0.0
    avg_completion_min = round(sum(completion_times) / len(completion_times), 1) if completion_times else 0.0

    # Ratings
    r_reviews = await db.execute(
        select(Review).where(Review.electrician_id == user.id)
    )
    reviews = r_reviews.scalars().all()
    pos_reviews = sum(1 for r in reviews if r.rating >= 4)
    neg_reviews = sum(1 for r in reviews if r.rating <= 2)

    total_revs = len(reviews)
    avg_rating = round(sum(r.rating for r in reviews) / total_revs, 1) if total_revs > 0 else 0.0

    most_performed = max(svc_count, key=svc_count.get) if svc_count else "—"

    # Category breakdown as percentage
    total_svc = sum(cat_count.values()) or 1
    cat_pct = {k: round(v / total_svc * 100, 1) for k, v in cat_count.items()}

    return {
        "order_performance": {
            "total_assigned": total,
            "completed": completed,
            "assigned_pending": assigned,
            "accepted": accepted,
            "rejected": rejected,
            "active": active,
        },
        "earnings": {
            "daily_earning": round(daily_earnings, 2),
            "weekly_earning": round(weekly_earnings, 2),
            "total_lifetime_earning": round(earnings.total_lifetime_earning or 0.0, 2) if earnings else 0.0,
            "commission_due": round(earnings.commission_due or 0.0, 2) if earnings else 0.0,
            "avg_job_value": avg_job_value,
        },
        "service_analytics": {
            "most_performed_service": most_performed,
            "category_breakdown": cat_pct,
            "service_breakdown": dict(sorted(svc_count.items(), key=lambda x: -x[1])[:5]),
        },
        "rating_feedback": {
            "average_rating": avg_rating,
            "total_reviews": total_revs,
            "positive_reviews": pos_reviews,
            "negative_reviews": neg_reviews,
        },
        "work_efficiency": {
            "avg_completion_minutes": avg_completion_min,
            "el_score": round(profile.el_score or 65.0, 1) if profile else 65.0,
        },
    }

