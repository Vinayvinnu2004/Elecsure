"""
app/services/notification_service.py — Multi-provider email & SMS notifications.
"""

import logging
import random
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import TYPE_CHECKING, Optional

import aiosmtplib
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import ist_now

if TYPE_CHECKING:
    from app.models import Booking, User, Review

logger = logging.getLogger(__name__)


# ── Low-level senders ─────────────────────────────────────────────────

async def send_email(to: str, subject: str, html_body: str) -> bool:
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning("SMTP not configured — skipping email to %s", to)
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["From"] = f"{settings.EMAIL_FROM_NAME} <{settings.EMAIL_FROM}>"
        msg["To"] = to
        msg["Subject"] = subject
        msg.attach(MIMEText(html_body, "html"))
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            start_tls=True,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
        )
        logger.info("Email sent → %s | %s", to, subject)
        return True
    except Exception as exc:
        logger.error("Email failed → %s | %s", to, exc)
        return False


async def send_sms(to_number: str, message: str) -> bool:
    if not to_number: return False
    to_number = to_number.strip()
    if not to_number.startswith("+"): to_number = "+91" + to_number.lstrip("0")
    if settings.DEBUG:
        logger.info("DEBUG MODE: SMS to %s | %s", to_number, message)
        return True
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        return await _send_sms_twilio(to_number, message)
    return False


async def _send_sms_twilio(to_number: str, message: str) -> bool:
    try:
        from twilio.rest import Client
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        client.messages.create(body=message, from_=settings.TWILIO_PHONE_NUMBER, to=to_number)
        return True
    except Exception as exc:
        logger.error("Twilio failed: %s", str(exc))
        return False


# ── Template Helpers ──────────────────────────────────────────────────

def _row(label: str, value: str) -> str:
    return f'<tr><td style="padding:16px;background:#1f2937;font-weight:700;width:40%;font-size:13px;color:#9ca3af;text-transform:uppercase;letter-spacing:0.5px;border-bottom:1px solid #374151">{label}</td><td style="padding:16px;background:#1f2937;font-size:16px;color:#fff;font-weight:600;border-bottom:1px solid #374151">{value}</td></tr>'

def _table(*rows: str) -> str:
    return '<table style="width:100%;border-collapse:collapse;margin:24px 0;border-radius:12px;overflow:hidden;border:1px solid #374151">' + "".join(rows) + "</table>"

def _template(title: str, body: str, cta_url: str = "", cta_text: str = "") -> str:
    cta = f'<div style="text-align:center;margin-top:30px"><a href="{cta_url}" style="display:inline-block;padding:14px 40px;background:#f59e0b;color:#1a1a1a;font-weight:800;font-size:16px;border-radius:10px;text-decoration:none;box-shadow:0 4px 12px rgba(245,158,11,0.3)">{cta_text}</a></div>' if cta_url else ""
    year = ist_now().year
    return f"""
<div style="font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif;max-width:600px;margin:0 auto;background:#111827;border-radius:16px;overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,0.2)">
  <div style="background:linear-gradient(135deg,#1e3a5f 0%,#2d5a8e 100%);padding:40px 20px;text-align:center;border-bottom:4px solid #f59e0b">
    <div style="font-size:32px;font-weight:900;color:#fff;letter-spacing:-1px">
      <span style="color:#f59e0b">&#x26A1;</span> ElecSure
    </div>
    <div style="color:#fde68a;font-size:14px;margin-top:6px;font-weight:600;text-transform:uppercase;letter-spacing:1px">Professional Home Electrical Services</div>
  </div>
  <div style="padding:40px 32px">
    <h1 style="color:#fff;font-size:24px;font-weight:800;margin:0 0 24px;border-bottom:2px solid #374151;padding-bottom:12px">{title}</h1>
    <div style="color:#d1d5db;font-size:16px;line-height:1.8">
      {body}
    </div>
    {cta}
  </div>
  <div style="background:#1f2937;padding:24px 32px;text-align:center;color:#9ca3af;font-size:12px;border-top:1px solid #374151">
    <p style="margin:0">Thank you for choosing <strong>ElecSure</strong> &nbsp;&#x26A1;</p>
    <p style="margin:8px 0 0">&copy; {year} ElecSure. Professional Service Guaranteed. &nbsp;|&nbsp; Support: {settings.SUPPORT_PHONE}</p>
  </div>
</div>"""


# ── Notifications ─────────────────────────────────────────────────────

async def notify_otp(to_email: str, to_phone: str, email_otp: str, mobile_otp: str, purpose: str = "registration") -> None:
    verb = "registering" if purpose == "registration" else "accessing your account"
    body = f"""<p>Hi,</p><p>Welcome to <strong>ElecSure</strong>! To complete {verb}, please use the verification codes below:</p>
    {_table(_row('Email Code', f'<span style="font-size:24px;letter-spacing:4px;color:#f59e0b;font-weight:800">{email_otp}</span>'), _row('Mobile Code', f'<span style="font-size:24px;letter-spacing:4px;color:#fde68a;font-weight:800">{mobile_otp}</span>'))}
    <p style="font-size:13px;color:#9ca3af;margin-top:20px">These codes will expire in 10 minutes. <strong>Please do not share them with anyone.</strong></p>"""
    await send_email(to_email, f"Verify Your Account — ElecSure", _template("Verification Required", body))
    await send_sms(to_phone, f"ElecSure OTP: {mobile_otp} (Valid for 10 mins)")


async def notify_verification_link(to_email: str, to_phone: str, verification_url: str, name: str = "User") -> None:
    await send_email(to_email, "Verify Your Email", _template("Verify Email", f"Hi {name}, click below to verify your email.", verification_url, "Verify Now"))
    await send_sms(to_phone, f"Hi {name}, verify your ElecSure account via email.")


async def notify_booking_created(db: "AsyncSession", booking: "Booking") -> None:
    await db.refresh(booking, ["customer", "service"])
    c = booking.customer
    if not c: return
    body = f"<p>Hi <strong>{c.name}</strong>,</p><p>⚡ <strong>Booking Confirmed!</strong> Your request for <strong>{booking.service.name}</strong> has been received and is being processed.</p>{_table(_row('Booking ID', f'#{booking.id}'), _row('Service', booking.service.name), _row('Pincode', booking.pincode))}"
    await send_email(c.email, f"Booking #{booking.id} Received — ElecSure", _template("Booking Confirmed!", body))
    await send_sms(c.phone, f"ElecSure: Booking #{booking.id} received for {booking.service.name}. We are assigning an electrician now!")


async def notify_booking_assigned(db: "AsyncSession", booking: "Booking") -> None:
    await db.refresh(booking, ["customer", "service", "electrician"])
    c, e = booking.customer, booking.electrician
    if not c or not e: return
    body = f"<p>Hi <strong>{c.name}</strong>,</p><p>👷 <strong>Great news!</strong> <strong>{e.name}</strong> has been assigned to your <strong>{booking.service.name}</strong> booking.</p>{_table(_row('Electrician', e.name), _row('Expertise', e.electrician_profile.primary_skill if e.electrician_profile else 'Electrical'))}"
    await send_email(c.email, f"Electrician Assigned — Booking #{booking.id}", _template("Electrician Assigned!", body))
    await send_sms(c.phone, f"ElecSure: Electrician {e.name} is assigned to booking #{booking.id}.")


async def notify_booking_accepted(db: "AsyncSession", booking: "Booking") -> None:
    await db.refresh(booking, ["customer", "electrician", "service"])
    c, e = booking.customer, booking.electrician
    if not c or not e: return
    body = f"<p>Hi <strong>{c.name}</strong>,</p><p>✅ <strong>Your booking has been accepted!</strong> <strong>{e.name}</strong> is now preparing to visit your location.</p>{_table(_row('Electrician', e.name), _row('Service', booking.service.name), _row('Booking ID', f'#{booking.id}'), _row('Status', 'Accepted'))}<p>You can track the electrician's live location on your dashboard.</p>"
    await send_email(c.email, f"Booking Accepted — {booking.service.name}", _template("Electrician on the Way!", body, f"{settings.BASE_URL}/customer", "Track Live Location"))
    await send_sms(c.phone, f"ElecSure: {e.name} accepted your booking #{booking.id}. Track live on the dashboard.")


async def notify_booking_arrived(db: "AsyncSession", booking: "Booking") -> None:
    await db.refresh(booking, ["customer", "electrician", "service"])
    c, e = booking.customer, booking.electrician
    if not c or not e: return
    body = f"<p>Hi <strong>{c.name}</strong>,</p><p>📍 <strong>Your electrician has arrived!</strong> <strong>{e.name}</strong> is at your service address now.</p>{_table(_row('Service', booking.service.name), _row('Electrician', e.name), _row('Status', 'At Location'))}<p>Please ensure someone is available to provide access to the area requiring service.</p>"
    await send_email(c.email, f"Electrician Arrived — Booking #{booking.id}", _template("Arrived at Location", body))
    await send_sms(c.phone, f"ElecSure: {e.name} has arrived for your job #{booking.id}. Please provide access.")


async def notify_booking_started(db: "AsyncSession", booking: "Booking") -> None:
    await db.refresh(booking, ["customer", "electrician", "service"])
    c, e = booking.customer, booking.electrician
    if not c or not e: return
    body = f"<p>Hi <strong>{c.name}</strong>,</p><p>🔧 <strong>Service is in progress!</strong> work has officially started on your request.</p>{_table(_row('Service', booking.service.name), _row('Started At', ist_now().strftime('%H:%M %p')), _row('Booking ID', f'#{booking.id}'))}<p>We'll notify you once the job is completed successfully.</p>"
    await send_email(c.email, f"Service Started — Booking #{booking.id}", _template("Work in Progress", body))
    await send_sms(c.phone, f"ElecSure: Service started for booking #{booking.id}. Sit back while we fix it!")


async def notify_booking_completed(db: "AsyncSession", booking: "Booking") -> None:
    await db.refresh(booking, ["customer", "service", "electrician"])
    c = booking.customer
    if not c: return
    body = f"<p>Hi <strong>{c.name}</strong>,</p><p>🎉 <strong>Service Complete!</strong> <strong>{booking.electrician.name if booking.electrician else 'Your electrician'}</strong> has finished your <strong>{booking.service.name}</strong>.</p>{_table(_row('Service Amount', f'₹{booking.total_amount:.2f}'), _row('Status', 'Success'))}<p>How was the experience? Please take a moment to rate us on ElecSure.</p>"
    await send_email(c.email, f"Service Complete! — Booking #{booking.id}", _template("Job Completed", body, f"{settings.BASE_URL}/customer", "Rate Experience"))
    await send_sms(c.phone, f"ElecSure: Booking #{booking.id} completed! Rate us on the dashboard.")


async def notify_booking_cancelled(db: "AsyncSession", booking: "Booking") -> None:
    await db.refresh(booking, ["customer", "service"])
    c = booking.customer
    if not c: return
    body = f"<p>Hi <strong>{c.name}</strong>,</p><p>❌ <strong>Booking Cancelled.</strong> Your booking for <strong>{booking.service.name}</strong> has been cancelled.</p>{_table(_row('Booking ID', f'#{booking.id}'), _row('Reason', booking.cancellation_reason or 'Internal Adjustment'))}<p>We apologize for any inconvenience caused. If you have questions, please contact our support team.</p>"
    await send_email(c.email, f"Booking Cancelled — #{booking.id}", _template("Cancelled", body))
    await send_sms(c.phone, f"ElecSure: Booking #{booking.id} cancelled. Reason: {booking.cancellation_reason or 'Internal System'}")


async def notify_elec_new_order(db: "AsyncSession", booking: "Booking") -> None:
    await db.refresh(booking, ["electrician", "service", "customer"])
    e = booking.electrician
    if not e: return
    body = f"<p>Hi <strong>{e.name}</strong>,</p><p>🚀 <strong>New Job Assigned!</strong> A customer is waiting for your expertise.</p>{_table(_row('Service', booking.service.name), _row('Pincode', booking.pincode), _row('Customer', booking.customer.name if booking.customer else 'ElecSure User'), _row('Address', booking.address))}<p>Accept the job quickly to maintain your EL Score!</p>"
    await send_email(e.email, f"⚡ New Job: {booking.service.name}", _template("New Assignment", body, f"{settings.BASE_URL}/electrician", "View Details & Accept"))
    await send_sms(e.phone, f"ElecSure: New job #{booking.id} ({booking.service.name}). Accept it now on your dashboard!")


async def notify_elec_order_accepted(db: "AsyncSession", booking_id: str) -> None:
    from app.models import Booking
    r = await db.execute(select(Booking).where(Booking.id == booking_id).options(joinedload(Booking.electrician)))
    b = r.scalar_one_or_none()
    if b and b.electrician:
        await send_email(b.electrician.email, "Accepted", _template("Accepted", "You accepted the job."))


async def notify_elec_service_started(db: "AsyncSession", booking_id: str) -> None:
    from app.models import Booking
    r = await db.execute(select(Booking).where(Booking.id == booking_id).options(joinedload(Booking.electrician)))
    b = r.scalar_one_or_none()
    if b and b.electrician:
        await send_email(b.electrician.email, "Started", _template("Started", "Job started."))


async def notify_elec_service_completed(db: "AsyncSession", booking_id: str) -> None:
    from app.models import Booking
    r = await db.execute(select(Booking).where(Booking.id == booking_id).options(joinedload(Booking.electrician)))
    b = r.scalar_one_or_none()
    if b and b.electrician:
        await send_email(b.electrician.email, "Completed", _template("Done", "Earnings added!"))


async def notify_review_given(db: "AsyncSession", review: "Review") -> None:
    await db.refresh(review, ["customer"])
    if review.customer:
        await send_email(review.customer.email, "Review Received", _template("Thanks", "Thanks for the feedback!"))


async def notify_elec_review_received(db: "AsyncSession", review: "Review") -> None:
    await db.refresh(review, ["booking", "customer"])
    await db.refresh(review.booking, ["electrician", "service"])
    e = review.booking.electrician
    if not e: return
    body = f"<p>Hi <strong>{e.name}</strong>,</p><p>🌟 <strong>A customer left you a review!</strong></p>{_table(_row('Rating', '★' * review.rating), _row('Service', review.booking.service.name))}<p style='font-style:italic;color:#9ca3af;padding:12px;background:#1f2937;border-radius:8px'>\"{review.comment or 'No comment provided'}\"</p><p>Great feedback improves your EL Score and helps you get more orders!</p>"
    await send_email(e.email, f"New {review.rating}-Star Review Received", _template("New Feedback Received", body, f"{settings.BASE_URL}/electrician", "Acknowledge Review"))


async def notify_elec_score_weekly(email: str, name: str, change_str: str, new_score: float, phone: str = "") -> None:
    await send_email(email, "Weekly Score", _template("Score", f"New score: {new_score}"))


async def notify_elec_slot_reminder(email: str, name: str, count: int, phone: str = "") -> None:
    await send_email(email, "Slot Reminder", _template("Reminder", f"You have {count} slots."))


async def notify_elec_midnight_bonus(email: str, name: str, phone: str = "") -> None:
    await send_email(email, "Midnight Bonus", _template("Bonus", "Earn extra tonight!"))


async def notify_elec_availability_reminder(email: str, name: str, hours: float, phone: str = "") -> None:
    await send_email(email, "Availability", _template("Offline", "You've been offline."))


async def notify_elec_order_timeout_warning(email: str, name: str, service_name: str, booking_id: str, phone: str = "") -> None:
    await send_email(email, "Timeout Warning", _template("Urgent", "Accept booking now."))


async def notify_elec_low_score_warning(email: str, name: str, score: float, phone: str = "") -> None:
    await send_email(email, "Low Score Alert", _template("Warning", f"Score below 40: {score}"))


async def notify_elec_weekly_summary(email: str, name: str, data: dict, phone: str = "") -> None:
    await send_email(email, "Weekly Summary", _template("Report", "Weekly stats are ready."))


async def notify_elec_verified(email: str, name: str, phone: str = "") -> None:
    await send_email(email, "Verified", _template("Welcome", "You are verified!"))


async def notify_elec_motivation(email: str, name: str, msg: str) -> None:
    await send_email(email, "Motivation", _template("Team Message", msg))


async def notify_elec_restricted(email: str, name: str, balance: float) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>⛔ <strong>Your account has been restricted.</strong></p>
    <p>Your pending commission balance has exceeded the ₹3,000 threshold. To maintain platform stability, your account is now in **Restricted Mode**.</p>
    {_table(_row('Pending Balance', f'₹{balance:,.2f}'), _row('Status', '<span style="color:#ef4444;font-weight:700">RESTRICTED</span>'), _row('Action', 'Payment Required'))}
    <p><strong>Note:</strong> You will not receive any new job assignments until this balance is cleared. Once you pay the commission, your account will be automatically restored.</p>"""
    await send_email(email, "⚠️ Account Restricted — Clear Balance to Resume", _template("Account Restricted", body, f"{settings.BASE_URL}/electrician", "Pay Commission Now"))


async def notify_elec_unrestricted(email: str, name: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>✅ <strong>Account Restored!</strong></p>
    <p>Thank you for clearing your pending commission. Your account is now back in **Good Standing** and you are eligible to receive new assignments immediately.</p>
    {_table(_row('Status', '<span style="color:#10b981;font-weight:700">ACTIVE</span>'), _row('Availability', 'Restored to Online'))}
    <p>Go to your dashboard to ensure your time slots are updated!</p>"""
    await send_email(email, "✅ Access Restored — Welcome Back!", _template("Welcome Back Online", body, f"{settings.BASE_URL}/electrician", "Go to Dashboard"))


async def notify_elec_commission_cleared(email: str, name: str, amount: float, remaining: float) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>💰 <strong>Payment Received!</strong></p>
    <p>We have successfully recorded your commission payment of ₹{amount:,.2f}.</p>
    {_table(_row('Amount Paid', f'₹{amount:,.2f}'), _row('Remaining Balance', f'₹{remaining:,.2f}'))}
    <p>Thank you for your timely payment. It helps us keep the ElecSure ecosystem growing!</p>"""
    await send_email(email, "💰 Commission Payment Received", _template("Payment Confirmed", body))


async def notify_promo(email: str, phone: str, name: str, index: int) -> None:
    msg = PROMO_MESSAGES[index % len(PROMO_MESSAGES)]
    await send_email(email, "Special Offer", _template("Promo", msg))


PROMO_MESSAGES = [
    "⚡ Is your home power-bill ready? Book an Energy Audit slot today and save 15% on electricity!",
    "🌈 Festival season is here! Decorative lighting installation — book now! 🎉",
    "🔧 Small issues today become big problems tomorrow. A ₹199 check-up saves ₹5000 later! ⚡",
]
