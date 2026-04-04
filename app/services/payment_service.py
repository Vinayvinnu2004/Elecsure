"""app/services/payment_service.py — Stripe payment integration."""

import logging
import stripe
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import ist_now
from app.models import (
    Booking, Payment, 
    PAYMENT_PENDING, PAYMENT_COMPLETED, PAYMENT_FAILED, PAYMENT_REFUNDED
)

logger = logging.getLogger(__name__)

stripe.api_key = settings.STRIPE_SECRET_KEY


async def create_payment_intent(
    db: AsyncSession,
    booking: Booking,
    customer_email: str,
) -> dict:
    """Create a Stripe PaymentIntent and persist a pending Payment record."""
    amount_paise = int(booking.total_amount * 100)  # Stripe uses smallest currency unit

    try:
        intent = stripe.PaymentIntent.create(
            amount=amount_paise,
            currency="inr",
            metadata={
                "booking_id": str(booking.id),
                "customer_id": str(booking.customer_id),
            },
            receipt_email=customer_email,
            description=f"ElecSure Booking #{booking.id}",
        )
    except stripe.error.StripeError as e:
        logger.error("Stripe PaymentIntent creation failed: %s", e)
        raise

    payment = Payment(
        customer_id=booking.customer_id,
        amount=booking.total_amount,
        currency="INR",
        status=PAYMENT_PENDING,
        stripe_payment_intent_id=intent.id,
        description=f"Booking #{booking.id}",
        created_at=ist_now(),
        updated_at=ist_now(),
    )
    db.add(payment)
    await db.flush()
    await db.refresh(payment)

    booking.payment_id = payment.id

    return {
        "client_secret": intent.client_secret,
        "payment_intent_id": intent.id,
        "amount": booking.total_amount,
        "currency": "INR",
    }


async def handle_webhook(db: AsyncSession, payload: bytes, sig_header: str) -> dict:
    """Process Stripe webhook events."""
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except (ValueError, stripe.error.SignatureVerificationError) as e:
        logger.warning("Invalid Stripe webhook: %s", e)
        return {"status": "invalid"}

    event_type = event["type"]
    data = event["data"]["object"]

    if event_type == "payment_intent.succeeded":
        await _handle_payment_succeeded(db, data)
    elif event_type == "payment_intent.payment_failed":
        await _handle_payment_failed(db, data)
    elif event_type == "charge.refunded":
        await _handle_refund(db, data)

    return {"status": "processed", "type": event_type}


async def _handle_payment_succeeded(db: AsyncSession, intent: dict) -> None:
    from sqlalchemy import select
    r = await db.execute(
        select(Payment).where(Payment.stripe_payment_intent_id == intent["id"])
    )
    payment = r.scalar_one_or_none()
    if not payment:
        return

    payment.status = PAYMENT_COMPLETED
    payment.stripe_charge_id = intent.get("latest_charge")
    payment.updated_at = ist_now()

    # Mark booking as paid
    booking_id = intent.get("metadata", {}).get("booking_id")
    if booking_id:
        booking = await db.get(Booking, booking_id)
        if booking:
            booking.is_paid = True
            booking.updated_at = ist_now()

            # Notify customer
            from app.models import User
            customer = await db.get(User, booking.customer_id)
            if customer:
                import asyncio
                from app.services.notification_service import notify_payment_success
                asyncio.create_task(notify_payment_success(
                    customer.email, customer.name,
                    booking.id, payment.amount, customer.phone,
                ))

    logger.info("Payment succeeded: %s", intent["id"])


async def _handle_payment_failed(db: AsyncSession, intent: dict) -> None:
    from sqlalchemy import select
    r = await db.execute(
        select(Payment).where(Payment.stripe_payment_intent_id == intent["id"])
    )
    payment = r.scalar_one_or_none()
    if not payment:
        return
    payment.status = PAYMENT_FAILED
    payment.failure_reason = intent.get("last_payment_error", {}).get("message", "Unknown error")
    payment.updated_at = ist_now()
    logger.warning("Payment failed: %s", intent["id"])


async def _handle_refund(db: AsyncSession, charge: dict) -> None:
    from sqlalchemy import select
    payment_intent_id = charge.get("payment_intent")
    if not payment_intent_id:
        return
    r = await db.execute(
        select(Payment).where(Payment.stripe_payment_intent_id == payment_intent_id)
    )
    payment = r.scalar_one_or_none()
    if payment:
        payment.status = PAYMENT_REFUNDED
        payment.refund_id = charge.get("refunds", {}).get("data", [{}])[0].get("id")
        payment.updated_at = ist_now()
