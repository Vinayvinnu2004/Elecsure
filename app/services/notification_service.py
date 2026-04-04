"""
app/services/notification_service.py — Multi-provider email & SMS notifications.
Supports: Email (SMTP), SMS (AWS SNS, MSG91, Nexmo, Twilio), Verification Links.
Complete set of notification functions covering all booking lifecycle events.
"""

import logging
import random
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

import aiosmtplib

from app.core.config import settings
from app.core.security import ist_now

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
    """Send SMS using Twilio exclusively."""
    if not to_number:
        logger.warning("No phone number provided for SMS")
        return False
    
    to_number = to_number.strip()
    if not to_number.startswith("+"):
        to_number = "+91" + to_number.lstrip("0")
    
    if settings.DEBUG:
        logger.info("DEBUG MODE: SMS to %s | Message: %s", to_number, message)
        return True
    
    # Twilio is the ONLY allowed provider
    if settings.TWILIO_ACCOUNT_SID and settings.TWILIO_AUTH_TOKEN:
        logger.info("Attempting Twilio SMS to %s", to_number)
        return await _send_sms_twilio(to_number, message)
    
    logger.error("Twilio not configured in .env — cannot send SMS")
    return False






async def _send_sms_twilio(to_number: str, message: str) -> bool:
    """Send SMS using Twilio API."""
    try:
        from twilio.rest import Client
        from twilio.base.exceptions import TwilioException
        
        logger.info("Attempting Twilio SMS to %s from %s", to_number, settings.TWILIO_PHONE_NUMBER)
        client = Client(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN)
        
        # Test client connection first
        account = client.api.accounts(settings.TWILIO_ACCOUNT_SID).fetch()
        logger.info("Twilio account status: %s", account.status)
        
        twilio_message = client.messages.create(
            body=message,
            from_=settings.TWILIO_PHONE_NUMBER,
            to=to_number,
        )
        logger.info("SMS sent via Twilio → %s | SID: %s | Status: %s", to_number, twilio_message.sid, twilio_message.status)
        return True
    except TwilioException as twilio_exc:
        logger.error("Twilio SMS failed → %s | Twilio Error: %s | Code: %s", to_number, str(twilio_exc), getattr(twilio_exc, 'code', 'N/A'))
        return False
    except Exception as exc:
        logger.error("Twilio SMS error → %s | %s", to_number, str(exc))
        return False


# ── Template Helpers ──────────────────────────────────────────────────

def _row(label: str, value: str) -> str:
    return f'<tr><td style="padding:10px 14px;background:#f3f4f6;font-weight:600;width:38%;font-size:13px;color:#374151">{label}</td><td style="padding:10px 14px;font-size:14px;color:#111827">{value}</td></tr>'

def _table(*rows: str) -> str:
    return '<table style="width:100%;border-collapse:separate;border-spacing:0 3px;margin:18px 0">' + "".join(rows) + "</table>"

def _template(title: str, body: str, cta_url: str = "", cta_text: str = "") -> str:
    cta = f'<a href="{cta_url}" style="display:inline-block;margin-top:22px;padding:13px 30px;background:#f59e0b;color:#1a1a1a;font-weight:700;font-size:15px;border-radius:8px;text-decoration:none">{cta_text}</a>' if cta_url else ""
    year = ist_now().year
    return f"""
<div style="font-family:'Helvetica Neue',Arial,sans-serif;max-width:600px;margin:0 auto;background:#ffffff;border-radius:14px;overflow:hidden;border:1px solid #e5e7eb;box-shadow:0 4px 20px rgba(0,0,0,0.08)">
  <div style="background:linear-gradient(135deg,#1e3a5f 0%,#2d5a8e 100%);padding:32px 28px;text-align:center">
    <div style="font-size:28px;font-weight:900;color:#fff;letter-spacing:-0.5px">&#x26A1; ElecSure</div>
    <div style="color:#fde68a;font-size:13px;margin-top:4px">Professional Home Electrical Services</div>
  </div>
  <div style="padding:32px 28px">
    <h2 style="color:#1e3a5f;font-size:20px;font-weight:700;margin:0 0 20px;padding-bottom:14px;border-bottom:2px solid #f59e0b">{title}</h2>
    <div style="color:#374151;font-size:15px;line-height:1.75">{body}</div>
    {cta}
  </div>
  <div style="background:#f9fafb;padding:18px 28px;text-align:center;border-top:1px solid #e5e7eb;font-size:12px;color:#9ca3af">
    &copy; {year} ElecSure &nbsp;|&nbsp; Support: {settings.SUPPORT_PHONE}&nbsp;|&nbsp; Automated message — please do not reply.
  </div>
</div>"""


# ── FEATURE 1: OTP ───────────────────────────────────────────────────

async def notify_otp(to_email: str, to_phone: str, email_otp: str, mobile_otp: str, purpose: str = "registration") -> None:
    """Send email OTP for verification. Mobile SMS is disabled."""
    subject = "Verification Code — ElecSure"
    verb = "registering with" if purpose == "registration" else "resetting your password on"
    body = f"""<p>Hi there,</p>
    <p>Thank you for {verb} <strong>ElecSure</strong>. Please use the following One-Time Password (OTP) to verify your account:</p>
    <div style="background:#f3f4f6;padding:24px;text-align:center;margin:20px 0;border-radius:12px;border:1px dashed #ced4da">
        <span style="font-size:36px;font-weight:800;letter-spacing:8px;color:#1e3a5f">{email_otp}</span>
    </div>
    <p style="text-align:center;color:#6b7280;font-size:14px">This code expires in <strong>10 minutes</strong>. Never share this with anyone. If you did not request this, please ignore this email.</p>"""
    
    await send_email(to_email, subject, _template("Verify Your Account", body))


async def notify_verification_link(to_email: str, to_phone: str, verification_url: str, name: str = "User", verify_type: str = "email") -> None:
    """Send email verification link for account verification."""
    subject = "Verify Your Email — ElecSure"
    
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>Thank you for registering with <strong>ElecSure</strong>. Please verify your email address to complete your registration.</p>
    <p>Click the button below to verify your email:</p>"""
    
    # Send email with verification link
    await send_email(to_email, subject, _template("Verify Your Email", body, verification_url, "Verify Email Address"))


# ── FEATURE 2: Customer Booking Notifications ────────────────────────

async def notify_booking_created(email: str, name: str, booking_id: str, service_name: str, phone: str, ist_time: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>⚡ <strong>Booking Confirmed!</strong> Your request for <strong>{service_name}</strong> on <strong>{ist_time}</strong> has been received.</p>
    <p>We're finding the best electrician for you. Sit tight!</p>
    {_table(_row("Booking ID", f"#{booking_id}"), _row("Service", service_name), _row("Scheduled", ist_time))}
    <p>Need help? Call us: <strong>{settings.SUPPORT_PHONE}</strong></p>"""
    await send_email(email, f"Booking #{booking_id} Received — ElecSure", _template("Booking Received!", body))

async def notify_booking_assigned(email: str, name: str, elec_name: str, elec_phone: str, elec_rating: float, booking_id: str, service_name: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>👷 <strong>Great news!</strong> <strong>{elec_name}</strong> has been assigned to your <strong>{service_name}</strong> booking.</p>
    {_table(_row("Electrician", elec_name), _row("Rating", f"{elec_rating} ★"), _row("Contact", elec_phone))}
    <p>You can track the progress live on the ElecSure app!</p>"""
    await send_email(email, f"Electrician Assigned — Booking #{booking_id}", _template("Electrician Assigned!", body))

async def notify_booking_accepted(email: str, name: str, elec_name: str, booking_id: str, date_str: str, address: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>✅ <strong>{elec_name}</strong> has accepted your booking and is getting ready!</p>
    {_table(_row("Scheduled", date_str), _row("Address", address))}
    <p>We'll notify you when they're on the way!</p>"""
    await send_email(email, f"Order Accepted! — Booking #{booking_id}", _template("Electrician Confirmed", body))

async def notify_booking_arrived(email: str, name: str, elec_name: str, booking_id: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>📍 <strong>{elec_name} has arrived!</strong> Your electrician has reached the service location.</p>
    <p>Please meet them at the door or guide them if needed.</p>"""
    await send_email(email, f"Electrician Arrived — Booking #{booking_id}", _template("Electrician is Here!", body))

async def notify_booking_started(email: str, name: str, elec_name: str, service_name: str, booking_id: str, phone: str, duration: int = 30) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>🔧 <strong>Your service has started!</strong> <strong>{elec_name}</strong> is currently working on your <strong>{service_name}</strong>.</p>
    <p>Estimated completion: <strong>{duration} mins</strong>. Stay nearby if needed!</p>"""
    await send_email(email, f"Service Started — Booking #{booking_id}", _template("Work in Progress", body))

async def notify_booking_completed(email: str, name: str, elec_name: str, service_name: str, booking_id: str, amount: float, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>🎉 <strong>Service Complete!</strong> <strong>{elec_name}</strong> has finished your <strong>{service_name}</strong>.</p>
    {_table(_row("Service Amount", f"₹{amount:,.2f}"))}
    <p>How was the experience? Please take a moment to rate us on ElecSure.</p>
    <p>Thank you for choosing us ⚡</p>"""
    await send_email(email, f"Service Complete! — Booking #{booking_id}", _template("Job Completed", body, f"{settings.BASE_URL}/customer", "Rate Experience"))

async def notify_review_given(email: str, name: str, elec_name: str, rating: int, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>💬 <strong>Thanks for your review!</strong> Your feedback helps us maintain quality service.</p>
    <p>You rated <strong>{elec_name}</strong> <strong>{rating}/5 ★</strong> — much appreciated!</p>"""
    await send_email(email, "Thank You for Your Feedback — ElecSure", _template("Review Received", body))


async def notify_booking_cancelled(email: str, name: str, booking_id: str, reason: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>❌ <strong>Booking Cancelled!</strong> Your booking for <strong>#{booking_id}</strong> has been cancelled.</p>
    {_table(_row("Reason", reason))}
    <p>Feel free to book again on ElecSure anytime ⚡</p>"""
    await send_email(email, f"Booking #{booking_id} Cancelled — ElecSure", _template("Booking Cancelled", body))


async def notify_booking_cancelled_timeout_apology(email: str, name: str, booking_id: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>😔 <strong>We're extremely sorry!</strong> We couldn't find an available electrician for your booking <strong>#{booking_id}</strong> within the last 30 minutes.</p>
    <p>To ensure quality service, we've had to cancel this request. We're working hard to increase our team size in your area.</p>
    <p>Please try booking again in a little while. We appreciate your patience ⚡</p>"""
    await send_email(email, f"Sincere Apology — Booking #{booking_id}", _template("Booking Cancelled", body))


# ── FEATURE 3: Electrician Booking Notifications ─────────────────────

async def notify_elec_new_order(email: str, name: str, booking_id: str, service_name: str, customer_name: str, address: str, date_str: str, accept_url: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>🆕 <strong>New Job Alert!</strong> A <strong>{service_name}</strong> booking for <strong>{customer_name}</strong> has been assigned to you.</p>
    {_table(_row("Date/Time", date_str), _row("Area", address))}
    <p>Please accept within <strong>10 minutes</strong> to keep your EL Score!</p>"""
    await send_email(email, f"New Order Assigned — #{booking_id}", _template("New Job Alert!", body, accept_url, "Accept Order"))

async def notify_elec_order_accepted(email: str, name: str, service_name: str, date_str: str, customer_name: str, cust_phone: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>✅ <strong>You've accepted the booking</strong> for <strong>{service_name}</strong> on <strong>{date_str}</strong>.</p>
    {_table(_row("Customer", customer_name), _row("Contact", cust_phone))}
    <p>Be on time to earn bonus EL Score points! ⭐</p>"""
    await send_email(email, "Booking Accepted — ElecSure", _template("Confirmation", body))

async def notify_elec_service_started(email: str, name: str, customer_name: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>🔧 <strong>Service marked as Started</strong> for <strong>{customer_name}</strong>.</p>
    <p>Complete professionally to earn top ratings and EL Score boost!</p>"""
    await send_email(email, "Job In Progress — ElecSure", _template("Service Started", body))

async def notify_elec_service_completed(email: str, name: str, service_name: str, customer_name: str, amount: float, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>🎉 <strong>Job Done!</strong> You've completed <strong>{service_name}</strong> for <strong>{customer_name}</strong>.</p>
    <p>💰 Earnings: <strong>₹{amount:,.2f}</strong> added to your account.</p>
    <p>Great work — keep it up! ⚡</p>"""
    await send_email(email, "Job Completed Successfully — ElecSure", _template("Congratulations!", body))

async def notify_elec_review_received(email: str, name: str, customer_name: str, rating: int, comment: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>⭐ <strong>New Review!</strong> <strong>{customer_name}</strong> rated you <strong>{rating}/5</strong></p>
    <p style="font-style:italic;color:#6b7280;margin:16px 0;padding-left:12px;border-left:3px solid #f59e0b">"{comment or 'No comment provided'}"</p>
    <p>Your EL Score has been updated. Check your dashboard!</p>"""
    await send_email(email, "You've Received a New Review!", _template("Great Work!", body))



# ── FEATURE 4: Customer Promotions ───────────────────────────────────

PROMO_MESSAGES = [
    "⚡ How's your home's electrical health? Quick check-up services start at just ₹349. Book now on ElecSure!",
    "☀️ Summer is here! Is your AC running efficiently? Get it serviced before the heat hits hard. Book on ElecSure today!",
    "🌀 Is your ceiling fan making noise or running slow? Don't ignore it — book a fan repair in 2 minutes on ElecSure!",
    "💡 Are your LED lights flickering? That could be a wiring issue. Get it checked before it becomes a bigger problem!",
    "🖥️ Computer flickering or facing power issues? Our electricians handle home power socket and UPS repairs too!",
    "🔌 Experiencing frequent power trips at home? Our experts can diagnose and fix it same day. Book on ElecSure!",
    "🍳 Is your mixer or grinder running weak? Electrical motor issues are our speciality. Book a repair today!",
    "🌧️ Monsoon is coming — is your home's earthing and wiring safe? Get a safety audit on ElecSure before it's too late!",
    "🏠 Haven't had an electrical check-up in over 6 months? Book a full home inspection",
    "⭐ Your last service was {days_ago} days ago. Time for a follow-up? Book your next service on ElecSure!",
    "🌙 Late night electrical issue? Don't panic! ElecSure has electricians available 24/7. Book now and get help fast! ⚡",
    "🏠 Did you know? 80% of home fires are caused by faulty wiring. Get a FREE safety check with your next booking on ElecSure!",
    "💡 Tip of the day: If your electricity bill has suddenly increased, you may have a faulty appliance or wiring issue. Let our experts check it! Book now ⚡",
    "🌧️ Monsoon Safety Alert! Wet season + faulty wiring = danger. Get your home's earthing checked today. Book on ElecSure in just 2 minutes!",
    "🎉 Special Offer! Book any service this weekend and get priority assignment — your electrician arrives faster! Open ElecSure now ⚡",
    "🔋 Is your inverter not holding charge like before? Battery and inverter servicing starts at just ₹149 on ElecSure. Book today!",
    "😴 Trouble sleeping because of fan noise? A wobbly or noisy fan is just one booking away from being fixed. Sleep peacefully tonight! 🌙",
    "⚡ Power fluctuations damaging your expensive appliances? Get a voltage stabilizer installed by our certified electricians. Book now!",
    "🍿 Movie night ruined by flickering lights? Don't let electrical issues spoil your fun. Quick fix — book on ElecSure right now!",
    "🌡️ Summer is peak season for electrical faults. AC tripping, overloaded circuits, fan failures — we handle it all! Book before the rush ☀️",
    "🔌 How many extension boards are you using at home? Overloaded sockets are a silent fire hazard. Get proper wiring done — book on ElecSure!",
    "📱 Did you know you can book an electrician in under 60 seconds on ElecSure? Try it now — your home deserves the best care! ⚡",
    "🏡 Moving into a new home? Get a complete electrical inspection before settling in. Avoid surprises — book ElecSure today!",
    "💧 Water heater not heating properly? Could be a heating element issue. Our electricians fix it same day! Book on ElecSure ⚡",
    "🎓 Back to school season! Make sure your child's study room has proper lighting and safe sockets. Book an electrical check today!",
    "🌟 Your home deserves 5-star electrical care! Our top-rated electricians are just one tap away. Book on ElecSure now ⚡",
    "🔦 Frequent power cuts in your area? Get an inverter or UPS installed and never sit in the dark again! Book on ElecSure today!",
    "🍽️ Is your refrigerator or fan running slow? Could be a motor issue. Get it fixed before your next cooking session! Book now ⚡",
    "⭐ You gave {elec_name} a {rating}/5 rating last time! They're available again this week — want to book them for your next service?",
    "🚿 Geyser taking too long to heat water? Heating element or thermostat might need replacement. Quick fix — book on ElecSure! ⚡",
    "💼 Office electrical issues? ElecSure also handles commercial bookings! Server room cooling, office wiring, CCTV installation — we do it all!",
    "🌈 Festival season is here! Decorative lighting installation, extra socket fitting, outdoor wiring — book ElecSure for a bright celebration! 🎉",
    "🔧 Small electrical issues ignored today become big expensive problems tomorrow. A quick ₹199 check-up can save you ₹5000 later! Book now ⚡",
    "👨‍👩‍👧 Family safety first! Old wiring in homes built before 2010 can be dangerous. Schedule a full home wiring inspection on ElecSure today!",
    "😤 Tired of calling random electricians who show up late or overcharge? ElecSure electricians are verified, rated, and always on time! Book now ⚡",
]

async def notify_promo(email: str, phone: str, name: str, index: int, extra_data: dict = None) -> None:
    msg = PROMO_MESSAGES[index]
    if extra_data:
        msg = msg.format(**extra_data)
    
    body = f"<p>Hi <strong>{name}</strong>,</p><p>{msg}</p>"
    await send_email(email, "Special Note from ElecSure ⚡", _template("Thinking of You!", body, f"{settings.BASE_URL}/customer", "Open App"))


# ── FEATURE 5: Electrician Engagement ────────────────────────────────

async def notify_elec_score_weekly(email: str, name: str, change_str: str, new_score: float, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>Your weekly performance review is here!</p>
    {_table(_row("Weekly Change", change_str), _row("Current EL Score", f"<strong>{new_score:.1f} / 100</strong>"))}
    <p>Keep delivering great service to maintain a high EL Score!</p>"""
    await send_email(email, "Your Weekly EL Score Report — ElecSure", _template("Weekly Summary", body))

async def notify_elec_slot_reminder(email: str, name: str, count: int, phone: str) -> None:
    body = f"<p>Hi <strong>{name}</strong>,</p><p>📅 You have {count} slots booked this week. 💡 Pro tip: Peak hour slots (6–9 PM) earn 30% more!</p>"
    await send_email(email, "Slot Reminder — ElecSure", _template("Check Your Bookings", body))

async def notify_elec_midnight_bonus(email: str, name: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>🌙 <strong>Midnight Bonus Alert!</strong> Book a slot between 11 PM–2 AM and earn <strong>₹50 extra</strong> per job.</p>
    <p>Limited slots available — grab yours now and maximize your earnings! ⚡</p>"""
    await send_email(email, "Midnight Bonus Opportunity — ElecSure", _template("Earn Extra Tonight!", body, f"{settings.BASE_URL}/electrician", "View Available Slots"))

async def notify_elec_availability_reminder(email: str, name: str, hours: float, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>👋 You've been offline for <strong>{hours:.1f} hours</strong> during peak demand time!</p>
    <p>Customers are looking for help and opportunities are waiting. Switch on your availability to start receiving orders! ⚡</p>"""
    await send_email(email, "Come Back Online — Missed Opportunities", _template("Peak Demand Right Now!", body, f"{settings.BASE_URL}/electrician", "Go Online Now"))

async def notify_elec_order_timeout_warning(email: str, name: str, service_name: str, booking_id: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>⏰ <strong>Action Required!</strong> You have a pending booking for <strong>{service_name}</strong> (Booking ID: <strong>#{booking_id}</strong>) that needs your response.</p>
    <p>Please accept within <strong>2 minutes</strong> or it will be reassigned! ⚡</p>"""
    await send_email(email, "Urgent: Accept Your Order Now — ElecSure", _template("Pending Booking", body, f"{settings.BASE_URL}/electrician", "Accept Now"))


async def notify_elec_order_timeout_penalty(email: str, name: str, booking_id: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>⚠️ <strong>Important Warning!</strong> You failed to accept booking <strong>#{booking_id}</strong> despite multiple reminders.</p>
    <p>As a result, <strong>10 points</strong> have been deducted from your EL Score. Repeatedly ignoring assigned orders will lead to account suspension.</p>
    <p>Please stay active when your status is set to 'Available' ⚡</p>"""
    await send_email(email, "EL Score Deducted — Action Required", _template("Warning: Order Not Accepted", body))

async def notify_elec_low_score_warning(email: str, name: str, score: float, phone: str) -> None:
    body = f"<p>Hi <strong>{name}</strong>,</p><p>🚨 <strong>Alert!</strong> Your EL Score has dropped below <strong>40</strong>.</p><p>You're at risk of being deprioritized in job matching. Tips: Accept jobs faster, be on time, collect good reviews! 💪</p>"
    await send_email(email, "Urgent: Low EL Score Alert", _template("Action Required", body))

async def notify_elec_weekly_summary(email: str, name: str, data: dict, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>📈 <strong>Your Weekly ElecSure Report:</strong></p>
    {_table(
        _row("Jobs Completed", data['count']),
        _row("Earnings", f"₹{data['amount']:,.2f}"),
        _row("Avg Rating", f"{data['rating']:.1f} ★"),
        _row("EL Score", data['score'])
    )}
    <p>Keep up the great work! Book more slots to earn more this week ⚡</p>"""
    await send_email(email, "Weekly Performance Summary", _template("Great Week!", body))

async def notify_elec_verified(email: str, name: str, phone: str) -> None:
    body = f"""<p>Hi <strong>{name}</strong>,</p>
    <p>Your account is verified, you can now start managing slots and receiving orders.</p>
    <p>Welcome to the ElecSure team! ⚡</p>"""
    await send_email(email, "Account Verified — ElecSure", _template("Verification Successful!", body, f"{settings.BASE_URL}/electrician", "Go to Dashboard"))


async def notify_elec_motivation(email: str, name: str, msg: str) -> None:
    """Send custom motivational or engagement messages to electricians via email."""
    body = f"<p>Hi <strong>{name}</strong>,</p><p>{msg}</p>"
    await send_email(email, "Message from ElecSure Team ⚡", _template("Team Message", body))
