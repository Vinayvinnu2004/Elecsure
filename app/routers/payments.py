"""app/routers/payments.py — Stripe payment endpoints."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Request, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.dependencies import require_customer
from app.models import Booking, STATUS_CANCELLED, User
from app.schemas.payment import PaymentIntentCreate, PaymentIntentOut
from app.schemas.common import MessageOut

router = APIRouter(prefix="/api/v1/payments", tags=["Payments"])
logger = logging.getLogger(__name__)


@router.post("/create-intent", response_model=PaymentIntentOut)
async def create_payment_intent(
    data: PaymentIntentCreate,
    user: User = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
):
    booking = await db.get(Booking, data.booking_id)
    if not booking or booking.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Booking not found")
    if booking.is_paid:
        raise HTTPException(status_code=400, detail="Booking is already paid")
    if booking.status == STATUS_CANCELLED:
        raise HTTPException(status_code=400, detail="Cannot pay for a cancelled booking")

    from app.services.payment_service import create_payment_intent
    try:
        result = await create_payment_intent(db, booking, user.email)
        return result
    except Exception as e:
        logger.error("Payment intent creation error: %s", e)
        raise HTTPException(status_code=502, detail="Payment service error. Please try again.")


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(
    request: Request,
    stripe_signature: str = Header(None, alias="stripe-signature"),
    db: AsyncSession = Depends(get_db),
):
    payload = await request.body()
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")

    from app.services.payment_service import handle_webhook
    result = await handle_webhook(db, payload, stripe_signature)
    if result.get("status") == "invalid":
        raise HTTPException(status_code=400, detail="Invalid webhook signature")
    return result


@router.get("/booking/{booking_id}/status")
async def get_payment_status(
    booking_id: str,
    user: User = Depends(require_customer),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    from app.models import Payment
    booking = await db.get(Booking, booking_id)
    if not booking or booking.customer_id != user.id:
        raise HTTPException(status_code=404, detail="Booking not found")

    if not booking.payment_id:
        return {"is_paid": False, "payment_status": None}

    payment = await db.get(Payment, booking.payment_id)
    return {
        "is_paid": booking.is_paid,
        "payment_status": payment.status if payment else None,
        "amount": payment.amount if payment else None,
    }

