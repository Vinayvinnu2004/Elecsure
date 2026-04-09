"""app/routers/admin.py — Admin dashboard: users, bookings, services, EL score, stats."""

import logging
import asyncio
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_

from app.core.database import get_db
from app.core.dependencies import require_admin, get_current_user
from app.core.security import ist_now
from app.models import (
    User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN,
    Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
    Service, ELScoreLog, ELScoreEvent, Payment, PAYMENT_COMPLETED, Review,
    ElectricianProfile, CustomerProfile, CANCEL_SYSTEM
)
from app.schemas.common import MessageOut

router = APIRouter(prefix="/api/v1/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


# ── Dashboard Stats ──────────────────────────────────────────────────

@router.get("/stats")
async def dashboard_stats(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total_customers = (await db.execute(
        select(func.count(User.id)).where(User.role == ROLE_CUSTOMER)
    )).scalar()
    total_electricians = (await db.execute(
        select(func.count(User.id)).where(User.role == ROLE_ELECTRICIAN)
    )).scalar()
    total_bookings = (await db.execute(select(func.count(Booking.id)))).scalar()
    active_bookings = (await db.execute(
        select(func.count(Booking.id)).where(
            Booking.status.in_([STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED])
        )
    )).scalar()
    completed_bookings = (await db.execute(
        select(func.count(Booking.id)).where(
            Booking.status.in_([STATUS_COMPLETED, STATUS_REVIEWED])
        )
    )).scalar()
    cancelled_bookings = (await db.execute(
        select(func.count(Booking.id)).where(Booking.status == STATUS_CANCELLED)
    )).scalar()
    total_revenue = (await db.execute(
        select(func.sum(Payment.amount)).where(Payment.status == PAYMENT_COMPLETED)
    )).scalar() or 0.0
    
    # Needs join for availability
    available_electricians = (await db.execute(
        select(func.count(User.id))
        .join(ElectricianProfile, User.id == ElectricianProfile.user_id)
        .where(
            User.role == ROLE_ELECTRICIAN,
            ElectricianProfile.is_available == True,
            User.is_active.isnot(False),
        )
    )).scalar()

    return {
        "total_customers": total_customers,
        "total_electricians": total_electricians,
        "available_electricians": available_electricians,
        "total_bookings": total_bookings,
        "active_bookings": active_bookings,
        "completed_bookings": completed_bookings,
        "cancelled_bookings": cancelled_bookings,
        "total_revenue_inr": round(float(total_revenue), 2),
    }


# ── User Management ──────────────────────────────────────────────────

@router.get("/users")
async def list_users(
    role: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import joinedload
    q = select(User).options(joinedload(User.electrician_profile), joinedload(User.customer_profile))
    
    if role:
        q = q.where(User.role == role.upper())
        
    if search:
        q = q.where(
            User.name.ilike(f"%{search}%") |
            User.email.ilike(f"%{search}%") |
            User.phone.ilike(f"%{search}%")
        )
    q = q.order_by(User.created_at.desc())

    count_r = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_r.scalar() or 0

    r = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    users = r.scalars().all()

    items = []
    for u in users:
        score = 0.0
        rating = 0.0
        is_avail = False
        is_restricted = False
        if u.role == ROLE_ELECTRICIAN and u.electrician_profile:
            score = float(u.electrician_profile.el_score or 0.0)
            rating = float(u.electrician_profile.rating or 0.0)
            is_avail = u.electrician_profile.is_available
            is_restricted = u.electrician_profile.is_restricted
        elif u.role == ROLE_CUSTOMER and u.customer_profile:
            pass
            
        items.append({
            "id": str(u.id), "name": u.name, "email": u.email,
            "phone": u.phone, "role": u.role,
            "is_active": u.is_active, "is_verified": u.is_verified,
            "is_otp_verified": u.is_otp_verified,
            "el_score": score, "rating": rating,
            "is_available": is_avail,
            "is_restricted": is_restricted,
            "created_at": u.created_at,
        })

    return {
        "items": items,
        "total": total, "page": page, "per_page": per_page,
        "pages": -(-total // per_page),
    }



@router.post("/users/{user_id}/toggle-active", response_model=MessageOut)
async def toggle_user_active(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.is_active = not user.is_active
    user.updated_at = ist_now()
    status_str = "activated" if user.is_active else "deactivated"
    return MessageOut(message=f"User {user.name} has been {status_str}")


@router.post("/electricians/{user_id}/toggle-restriction", response_model=MessageOut)
async def toggle_electrician_restriction(
    user_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(ElectricianProfile).where(ElectricianProfile.user_id == user_id))
    profile = r.scalar_one_or_none()
    if not profile:
        raise HTTPException(status_code=404, detail="Electrician profile not found")
        
    profile.is_restricted = not profile.is_restricted
    
    # Link availability to restriction status
    if profile.is_restricted:
        profile.is_available = False
    else:
        profile.is_available = True
        # Clear commission due when unrestricting
        from app.models.earnings import ElectricianEarning
        e_r = await db.execute(select(ElectricianEarning).where(ElectricianEarning.electrician_id == user_id))
        earn = e_r.scalar_one_or_none()
        if earn:
            earn.commission_due = 0.0
            
            # Record this clearance in commission history
            try:
                from app.models.earnings import WeeklyReport
                now = ist_now()
                clearance_report = WeeklyReport(
                    electrician_id=user_id,
                    total_earned=0.0,
                    commission_due=0.0,
                    week_start=now,
                    week_end=now
                )
                db.add(clearance_report)
            except Exception as e:
                logger.error(f"Failed to record manual clearance in history: {e}")
    
    await db.commit()

    # Trigger Notifications
    r_user = await db.execute(select(User).where(User.id == user_id))
    u = r_user.scalar_one_or_none()
    if u:
        from app.services import notification_service
        if profile.is_restricted:
            from app.models import ElectricianEarning
            e_r = await db.execute(select(ElectricianEarning).where(ElectricianEarning.electrician_id == user_id))
            earn = e_r.scalar_one_or_none()
            balance = float(earn.commission_due if earn else 0.0)
            asyncio.create_task(notification_service.notify_elec_restricted(u.email, u.name, balance))
        else:
            asyncio.create_task(notification_service.notify_elec_unrestricted(u.email, u.name))
    
    status_str = "Restricted Mode ENABLED" if profile.is_restricted else "Restricted Mode DISABLED"
    return MessageOut(message=f"Electrician restriction toggled: {status_str}. Availability automatically updated.")


@router.post("/users/{user_id}/verify", response_model=MessageOut)
async def verify_user(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if user.is_verified:
        return MessageOut(message=f"{user.name} is already verified")

    user.is_verified = True
    user.updated_at = ist_now()
    await db.commit()

    if user.role == ROLE_ELECTRICIAN:
        from app.services.notification_service import notify_elec_verified
        # Use background tasks if available, or call directly
        await notify_elec_verified(user.email, user.name, user.phone)

    return MessageOut(message=f"{user.name} has been verified")


# ── Booking Management ───────────────────────────────────────────────

@router.get("/bookings")
async def list_all_bookings(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import joinedload
    q = select(Booking).options(joinedload(Booking.service), joinedload(Booking.customer), joinedload(Booking.electrician))
    
    if status:
        target_status = status.upper()
        if target_status == "COMPLETED":
            q = q.where(Booking.status.in_([STATUS_COMPLETED, STATUS_REVIEWED]))
        else:
            q = q.where(Booking.status == target_status)
            
    q = q.order_by(Booking.created_at.desc())

    count_r = await db.execute(select(func.count()).select_from(q.subquery()))
    total = count_r.scalar() or 0

    r = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    bookings = r.scalars().all()

    items = []
    for b in bookings:
        items.append({
            "id": str(b.id), "status": b.status,
            "service": b.service.name if b.service else None,
            "customer": b.customer.name if b.customer else None,
            "electrician": b.electrician.name if b.electrician else "Unassigned",
            "pincode": b.pincode,
            "total_amount": float(b.total_amount),
            "payment_type": b.payment_type or "online",
            "preferred_date": b.preferred_date,
            "created_at": b.created_at,
        })
    return {"items": items, "total": total, "page": page,
            "per_page": per_page, "pages": -(-total // per_page)}


@router.post("/bookings/{booking_id}/force-cancel", response_model=MessageOut)
async def force_cancel_booking(
    booking_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    b = await db.get(Booking, booking_id)
    if not b:
        raise HTTPException(status_code=404, detail="Booking not found")
        
    if b.status in {STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED}:
        raise HTTPException(status_code=400, detail="Booking already in terminal state")

    b.status = STATUS_CANCELLED
    b.cancelled_at = ist_now()
    b.cancellation_type = CANCEL_SYSTEM
    b.cancellation_reason = "Cancelled by admin"
    b.updated_at = ist_now()
    await db.commit()
    return MessageOut(message=f"Booking #{booking_id} force-cancelled")



# ── Service Management ────────────────────────────────────────────────

@router.get("/services")
async def list_all_services(
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(Service).order_by(Service.category, Service.name))
    services = r.scalars().all()
    # Explicitly convert IDs to strings just in case
    return [
        {
            "id": str(s.id), "category": s.category, "group": s.group,
            "name": s.name, "description": s.description,
            "base_price": s.base_price, "duration_minutes": s.duration_minutes,
            "is_active": s.is_active, "created_at": s.created_at,
        }
        for s in services
    ]


@router.post("/services/{service_id}/toggle", response_model=MessageOut)
async def toggle_service(
    service_id: str,
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    s = await db.get(Service, service_id)
    if not s:
        raise HTTPException(status_code=404, detail="Service not found")
    s.is_active = not s.is_active
    status_str = "activated" if s.is_active else "deactivated"
    return MessageOut(message=f"Service '{s.name}' {status_str}")


# ── EL Score Management ──────────────────────────────────────────────

@router.get("/electricians/{electrician_id}/el-score-logs")
async def get_el_score_logs(
    electrician_id: str,
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role != ROLE_ADMIN and user.id != electrician_id:
        raise HTTPException(status_code=403, detail="Not authorized")
    r = await db.execute(
        select(ELScoreLog)
        .where(ELScoreLog.electrician_id == electrician_id)
        .order_by(ELScoreLog.created_at.desc())
        .limit(limit)
    )
    logs = r.scalars().all()
    return [
        {
            "id": str(l.id), "event": l.event,
            "delta": l.delta, "score_before": l.score_before,
            "score_after": l.score_after, "notes": l.notes,
            "booking_id": str(l.booking_id) if l.booking_id else None, 
            "created_at": l.created_at,
        }
        for l in logs
    ]


@router.post("/electricians/{electrician_id}/adjust-el-score", response_model=MessageOut)
async def adjust_el_score(
    electrician_id: str,
    delta: float = Query(..., description="Positive to add, negative to subtract"),
    reason: str = Query("Admin adjustment"),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.services.el_score_service import apply_el_event
    new_score = await apply_el_event(
        db, electrician_id, ELScoreEvent.DAILY_AVAILABILITY,
        notes=f"Admin manual adjustment: {reason}",
        override_delta=delta,
    )
    return MessageOut(message=f"EL Score adjusted. New score: {new_score:.1f}")


# ── Electrician Leaderboard ──────────────────────────────────────────

@router.get("/leaderboard")
async def el_score_leaderboard(
    limit: int = Query(20, ge=1, le=100),
    _: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import joinedload
    r = await db.execute(
        select(User)
        .join(ElectricianProfile, User.id == ElectricianProfile.user_id)
        .options(joinedload(User.electrician_profile))
        .where(User.role == ROLE_ELECTRICIAN, User.is_active.isnot(False))
        .order_by(ElectricianProfile.el_score.desc())
        .limit(limit)
    )
    electricians = r.scalars().all()
    return [
        {
            "rank": i + 1, "id": str(e.id), "name": e.name,
            "el_score": e.electrician_profile.el_score if e.electrician_profile else 0,
            "rating": e.electrician_profile.rating if e.electrician_profile else 0,
            "total_reviews": e.electrician_profile.total_reviews if e.electrician_profile else 0,
            "is_available": e.electrician_profile.is_available if e.electrician_profile else False,
            "skills": e.electrician_profile.skills if e.electrician_profile else "",
        }
        for i, e in enumerate(electricians)
    ]

