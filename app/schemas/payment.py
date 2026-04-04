"""app/schemas/payment.py"""

from pydantic import BaseModel


class PaymentIntentCreate(BaseModel):
    booking_id: str


class PaymentIntentOut(BaseModel):
    client_secret: str
    payment_intent_id: str
    amount: float
    currency: str


class WebhookEvent(BaseModel):
    type: str
    data: dict
