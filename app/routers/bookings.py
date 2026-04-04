"""app/routers/bookings.py — Full booking lifecycle for customers and electricians."""

import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_customer, require_electrician
from app.core.security import ist_now
from app.models import (User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN, 
                        Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, 
                        STATUS_ARRIVED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
                        ActionToken)
from app.schemas.booking import BookingCreate, BookingListOut, ReviewCreate
from app.schemas.common import MessageOut
from app.services.booking_service import BookingService

router = APIRouter(prefix="/api/v1/bookings", tags=["Bookings"])
logger = logging.getLogger(__name__)

# ── Helpers (Formatting) ──────────────────────────────────────────────

def _booking_out(b: Booking, viewer_role: str = ROLE_CUSTOMER) -> dict:
    """Formats the booking record for JSON response."""
    svc = None
    if b.service:
        svc = {"id": str(b.service.id), "name": b.service.name,
               "category": b.service.category, "base_price": b.service.base_price}
    review = None
    if b.review:
        review = {"id": str(b.review.id), "rating": b.review.rating,
                  "comment": b.review.comment, "created_at": b.review.created_at,
                  "customer_id": str(b.review.customer_id)}

    show_contact = b.status in (
        STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_ARRIVED,
        STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED
    )
    
    elec_name = elec_phone = elec_alt_phone = None
    if show_contact and b.electrician:
        elec_name = b.electrician.name
        elec_phone = b.electrician.phone
        elec_alt_phone = b.electrician.alternate_phone

    cust_name = cust_phone = cust_alt_phone = cust_address = None
    if show_contact and b.customer:
        cust_name = b.customer.name
        cust_phone = b.customer.phone
        cust_alt_phone = b.customer.alternate_phone
        cust_address = b.address

    return {
        "id": str(b.id), "status": b.status if b.status else STATUS_REQUESTED,
        "service": svc,
        "customer_id": str(b.customer_id), "electrician_id": str(b.electrician_id) if b.electrician_id else None,
        "address": b.address, "pincode": b.pincode, "district": b.district,
        "problem_description": b.problem_description,
        "latitude": getattr(b, "latitude", None), "longitude": getattr(b, "longitude", None),
        "preferred_date": b.preferred_date,
        "time_slot_start": b.time_slot_start, "time_slot_end": b.time_slot_end,
        "total_amount": b.total_amount or 0.0, 
        "is_paid": bool(b.is_paid),
        "payment_type": getattr(b, "payment_type", "online") or "online",
        "cancellation_reason": b.cancellation_reason, "cancelled_at": b.cancelled_at,
        "created_at": b.created_at, "accepted_at": b.accepted_at, "arrived_at": b.arrived_at,
        "started_at": b.started_at, "completed_at": b.completed_at,
        # Masked phones removed from model but kept in schema response if needed (derived now)
        "customer_phone_masked": ("****" + b.customer.phone[-4:]) if (b.customer and b.customer.phone and len(b.customer.phone) >= 4) else None,
        "electrician_phone_masked": ("****" + b.electrician.phone[-4:]) if (b.electrician and b.electrician.phone and len(b.electrician.phone) >= 4) else None,
        "electrician_name": elec_name,
        "electrician_phone": elec_phone,
        "electrician_alt_phone": elec_alt_phone,
        "customer_name": cust_name,
        "customer_phone": cust_phone,
        "customer_alt_phone": cust_alt_phone,
        "customer_address": cust_address,
        "review": review,
        "acknowledged_at": b.acknowledged_at,
    }


# ── API Endpoints ─────────────────────────────────────────────────────

@router.post("/", status_code=201)
async def create_booking(
    data: BookingCreate,
    user: User = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import joinedload
    booking = await BookingService.create_booking(db, user, data)
    # Eagerly reload with relations so _booking_out can safely access .customer, .service etc.
    r = await db.execute(
        select(Booking).options(
            joinedload(Booking.service),
            joinedload(Booking.customer),
            joinedload(Booking.electrician),
            joinedload(Booking.review),
        ).where(Booking.id == booking.id)
    )
    booking = r.scalar_one()
    return _booking_out(booking, viewer_role=ROLE_CUSTOMER)


@router.get("/my", response_model=BookingListOut)
async def my_bookings(
    status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    per_page: int = Query(10, ge=1, le=50),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import joinedload
    q = select(Booking).options(
        joinedload(Booking.service), joinedload(Booking.customer),
        joinedload(Booking.electrician), joinedload(Booking.review)
    )
    if user.role == ROLE_CUSTOMER:
        q = q.where(Booking.customer_id == user.id)
    else:
        q = q.where(Booking.electrician_id == user.id)

    if status:
        q = q.where(Booking.status == status.upper())

    q = q.order_by(Booking.created_at.desc())
    
    # Count
    count_q = select(func.count(Booking.id))
    if user.role == ROLE_CUSTOMER:
        count_q = count_q.where(Booking.customer_id == user.id)
    else:
        count_q = count_q.where(Booking.electrician_id == user.id)
        
    total_r = await db.execute(count_q)
    total = total_r.scalar() or 0
    
    bookings_r = await db.execute(q.offset((page - 1) * per_page).limit(per_page))
    bookings = bookings_r.scalars().all()

    items = [_booking_out(b, viewer_role=user.role) for b in bookings]
    return {"items": items, "total": total, "page": page, "per_page": per_page, "pages": -(-total // per_page)}


@router.get("/{booking_id}")
async def get_booking(
    booking_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    b = await BookingService.get_booking_by_id(db, booking_id, user_id=str(user.id), role=user.role)
    return _booking_out(b, viewer_role=user.role)


@router.post("/{booking_id}/cancel", response_model=MessageOut)
async def cancel_booking(
    booking_id: str,
    user: User = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
):
    await BookingService.cancel_booking(db, user, booking_id)
    return MessageOut(message="Booking cancelled successfully")


@router.get("/action/{token}")
async def handle_action_token(token: str, db: AsyncSession = Depends(get_db)):
    """One-click email actions via BookingService."""
    at_r = await db.execute(select(ActionToken).where(ActionToken.token == token, ActionToken.is_used == False))
    at = at_r.scalar_one_or_none()
    if not at or at.expires_at < ist_now():
        raise HTTPException(status_code=400, detail="Invalid, used or expired token")
        
    b = await BookingService.transition_status(db, str(at.booking_id), at.action)
    at.is_used = True
    at.used_at = ist_now()
    await db.commit()
    return {"message": "Action completed!", "booking_id": str(b.id), "status": b.status}


@router.post("/{booking_id}/accept", response_model=MessageOut)
async def accept_booking(booking_id: str, user: User = Depends(require_electrician), db: AsyncSession = Depends(get_db)):
    await BookingService.transition_status(db, booking_id, "accept", current_user=user)
    return MessageOut(message="Booking accepted successfully")


@router.post("/{booking_id}/arrived", response_model=MessageOut)
async def mark_arrived(booking_id: str, user: User = Depends(require_electrician), db: AsyncSession = Depends(get_db)):
    await BookingService.transition_status(db, booking_id, "arrived", current_user=user)
    return MessageOut(message="Arrival recorded successfully")


@router.post("/{booking_id}/start", response_model=MessageOut)
async def start_booking(booking_id: str, user: User = Depends(require_electrician), db: AsyncSession = Depends(get_db)):
    await BookingService.transition_status(db, booking_id, "start", current_user=user)
    return MessageOut(message="Service started")


@router.post("/{booking_id}/complete", response_model=MessageOut)
async def complete_booking(booking_id: str, user: User = Depends(require_electrician), db: AsyncSession = Depends(get_db)):
    await BookingService.transition_status(db, booking_id, "complete", current_user=user)
    return MessageOut(message="Service completed successfully")


@router.post("/{booking_id}/review", response_model=MessageOut)
async def submit_review(
    booking_id: str, data: ReviewCreate,
    user: User = Depends(require_customer), db: AsyncSession = Depends(get_db)
):
    await BookingService.submit_review(db, user, booking_id, data)
    return MessageOut(message="Thank you for your review!")


@router.post("/{booking_id}/acknowledge", response_model=MessageOut)
async def acknowledge_review(booking_id: str, user: User = Depends(require_electrician), db: AsyncSession = Depends(get_db)):
    b = await BookingService.get_booking_by_id(db, booking_id)
    if str(b.electrician_id) != str(user.id): raise HTTPException(status_code=403, detail="Forbidden")
    if b.status != STATUS_REVIEWED: raise HTTPException(status_code=400, detail="Review not submitted yet")
    b.acknowledged_at = ist_now()
    await db.commit()
    return MessageOut(message="Review acknowledged")
