"""
app/services/chatbot_service.py

Two fully autonomous AI agents:
  - CustomerAgent  : knows customer's bookings, profile, services; can cancel, check status, list orders
  - ElectricianAgent: knows electrician's orders, EL score, slots, earnings; can accept/start/complete, toggle availability

Each agent:
  1. Fetches the user's live data from DB on every conversation turn
  2. Detects intent and executes DB actions directly (no need for user to navigate UI)
  3. Falls back to Gemini AI for free-form questions with the live data as context
  4. Falls back to rule-based responses if Gemini is unavailable
"""

import logging
import json
import re
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload

from app.core.config import settings
from app.core.security import ist_now

logger = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt_date(dt) -> str:
    if not dt:
        return "—"
    try:
        return dt.strftime("%d %b %Y %I:%M %p")
    except Exception:
        return str(dt)


def _status_label(s: str) -> str:
    return {
        "REQUESTED": "Requested (waiting for electrician)",
        "ASSIGNED":  "Electrician Assigned (awaiting acceptance)",
        "ACCEPTED":  "Accepted (electrician on the way)",
        "STARTED":   "In Progress (service underway)",
        "COMPLETED": "Completed",
        "REVIEWED":  "Completed & Reviewed",
        "CANCELLED": "Cancelled",
    }.get(s, s)


def _extract_id(msg: str) -> Optional[str]:
    match = re.search(r'#([a-zA-Z0-9\-]+)', msg)
    if not match:
        match = re.search(r'(?:booking|order)\s+([a-zA-Z0-9\-]+)', msg, re.I)
    return match.group(1) if match else None


async def _groq_reply(prompt: str, history: list) -> Optional[str]:
    """Call Groq API (Llama-3) with 5s timeout. Returns None if unavailable."""
    if not settings.GROQ_API_KEY:
        return None
    try:
        import httpx
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {settings.GROQ_API_KEY}",
            "Content-Type": "application/json"
        }
        # Convert history format to OpenAI format
        messages = [{"role": "system", "content": "You are a helpful assistant for ElecSure."}]
        for h in history[-6:]:
            role = "assistant" if h.get("role") == "model" else "user"
            messages.append({"role": role, "content": h.get("content", "")})
        
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": "llama-3.1-8b-instant",
            "messages": messages,
            "temperature": 0.7,
            "max_tokens": 1024
        }
        
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, headers=headers, json=payload, timeout=5.0)
            if resp.status_code == 200:
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning("Groq API failed: %d - %s", resp.status_code, resp.text)
                return None
    except Exception as e:
        logger.warning("Groq skipped: %s", str(e))
        return None


# ════════════════════════════════════════════════════════════════════
#  CUSTOMER AGENT
# ════════════════════════════════════════════════════════════════════

async def customer_agent(
    message: str,
    user_id: str,
    db: AsyncSession,
    history: list,
) -> dict:
    """Full customer AI agent with profile-based access."""
    from app.models import (
        User, Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
        CANCEL_MANUAL, Service, TimeSlot, SLOT_AVAILABLE
    )

    msg = message.strip().lower()

    # ── 1. Fetch live data ────────────────────────────────────────
    r_u = await db.execute(select(User).options(joinedload(User.customer_profile)).where(User.id == user_id))
    user = r_u.scalar_one_or_none()
    if not user:
        return {"reply": "Account not found.", "action": None, "action_data": None}
    
    profile = user.customer_profile

    r_bookings = await db.execute(
        select(Booking)
        .options(joinedload(Booking.service), joinedload(Booking.electrician))
        .where(Booking.customer_id == user_id)
        .order_by(Booking.created_at.desc())
        .limit(20)
    )
    bookings = r_bookings.scalars().all()

    active_bookings = [b for b in bookings if b.status not in (STATUS_CANCELLED, STATUS_REVIEWED)]
    ongoing = [b for b in bookings if b.status in (STATUS_ACCEPTED, STATUS_STARTED)]
    pending_review = [b for b in bookings if b.status == STATUS_COMPLETED and not b.review]

    # ── 2. Intent Detection ───────────────────────────────────────

    # List Bookings
    if any(kw in msg for kw in ["my booking", "my order", "show booking", "list booking"]):
        if not active_bookings:
            return {"reply": "📋 No active bookings. Go to **Book a Service** to schedule one.", "action": "show_bookings", "action_data": []}
        lines = [f"• **#{b.id}** — {b.service.name if b.service else 'Service'} ({_status_label(b.status)})" for b in active_bookings[:8]]
        return {"reply": "📋 **Your Active Bookings:**\n\n" + "\n".join(lines), "action": "show_bookings", "action_data": None}

    # Booking Details
    if any(kw in msg for kw in ["details", "info", "status of", "about #"]):
        bid = _extract_id(message)
        if bid:
            b = next((x for x in bookings if str(x.id).lower() == bid.lower()), None)
            if not b: return {"reply": f"❌ Booking #{bid} not found.", "action": None, "action_data": None}
            elec_info = f"\n👷 **Electrician:** {b.electrician.name} | 📞 {b.electrician.phone}" if b.electrician else ""
            return {
                "reply": (
                    f"📋 **Booking #{b.id} Details:**\n\n"
                    f"• **Service:** {b.service.name if b.service else 'Service'}\n"
                    f"• **Status:** {_status_label(b.status)}\n"
                    f"• **Amount:** ₹{b.total_amount} ({'PAID' if b.is_paid else 'PENDING'})\n"
                    f"• **Address:** {b.address}" + elec_info
                ),
                "action": "booking_detail", "action_data": {"id": str(b.id)}
            }

    # Cancel Booking
    if "cancel" in msg:
        bid = _extract_id(message)
        if bid:
            b = next((x for x in bookings if str(x.id).lower() == bid.lower()), None)
            if not b: return {"reply": "❌ Booking not found.", "action": None, "action_data": None}
            if b.status in (STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED):
                return {"reply": "⚠️ Cannot cancel once assigned. Contact support.", "action": None, "action_data": None}
            if b.status == STATUS_REQUESTED:
                b.status = STATUS_CANCELLED
                b.cancelled_at = ist_now()
                b.cancellation_type = CANCEL_MANUAL
                b.cancellation_reason = "Cancelled via chat"
                await db.commit()
                return {"reply": f"✅ Booking #{bid} cancelled.", "action": "cancel_booking", "action_data": None}

    # Profile
    if any(kw in msg for kw in ["my profile", "my account", "my detail"]):
        pc = profile.pincode if profile else "—"
        addr = profile.full_address if profile else "—"
        return {
            "reply": f"👤 **Your Profile:**\n\n• Name: {user.name}\n• Email: {user.email}\n• Phone: {user.phone}\n• Pincode: {pc}\n• Address: {addr}",
            "action": "show_profile", "action_data": None
        }

    # Services
    if any(kw in msg for kw in ["service", "what can you do"]):
        return {"reply": "⚡ **ElecSure offers 200+ services!** Appliance repair, wiring, lighting, installations, and more. Go to **Book a Service** to browse.", "action": "list_services", "action_data": None}

    # ── 3. Gemini Fallback ────────────────────────────────────────
    lines = [f"- Booking #{b.id}: {b.service.name if b.service else 'Svc'}, Status: {b.status}" for b in bookings[:5]]
    booking_summary = "\n".join(lines) or "No bookings"

    system_prompt = f"""You are a smart AI assistant for ElecSure.
Customer: {user.name} | Phone: {user.phone}
Recent Bookings:
{booking_summary}
Rules: Be concise, friendly. Tell them how to use the dashboard if they ask about something you can't do here.
Message: {message}"""

    reply = await _groq_reply(system_prompt, history)
    if reply: return {"reply": reply, "action": None, "action_data": None}

    return {"reply": "I'm here to help! Try 'my bookings', 'cancel #ID', or 'track electrician'.", "action": None, "action_data": None}


# ════════════════════════════════════════════════════════════════════
#  ELECTRICIAN AGENT
# ════════════════════════════════════════════════════════════════════

async def electrician_agent(
    message: str,
    user_id: str,
    db: AsyncSession,
    history: list,
) -> dict:
    """Full electrician AI agent with profile-based access."""
    from app.models import (
        User, Booking, STATUS_REQUESTED, STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED, STATUS_COMPLETED, STATUS_REVIEWED, STATUS_CANCELLED,
        TimeSlot, SLOT_AVAILABLE, ElectricianProfile
    )

    msg = message.strip().lower()

    # ── 1. Fetch live data ────────────────────────────────────────
    r_u = await db.execute(select(User).options(joinedload(User.electrician_profile)).where(User.id == user_id))
    user = r_u.scalar_one_or_none()
    if not user: return {"reply": "Account not found.", "action": None, "action_data": None}
    
    profile = user.electrician_profile

    r_orders = await db.execute(
        select(Booking)
        .options(joinedload(Booking.service), joinedload(Booking.customer))
        .where(Booking.electrician_id == user_id)
        .order_by(Booking.created_at.desc())
        .limit(20)
    )
    orders = r_orders.scalars().all()

    new_orders = [o for o in orders if o.status == STATUS_ASSIGNED]
    active_orders = [o for o in orders if o.status in (STATUS_ACCEPTED, STATUS_STARTED)]

    # ── 2. Intent Detection ───────────────────────────────────────

    # List Orders
    if any(kw in msg for kw in ["my order", "list order", "assigned"]):
        if not orders: return {"reply": "📋 No orders assigned yet.", "action": "show_orders", "action_data": []}
        lines = [f"• **#{o.id}** — {o.service.name if o.service else 'Service'} ({_status_label(o.status)})" for o in orders[:8]]
        return {"reply": "📋 **Your Assignments:**\n\n" + "\n".join(lines), "action": "show_orders", "action_data": None}

    # Accept Order
    if "accept" in msg:
        bid = _extract_id(message)
        if bid:
            o = next((x for x in orders if str(x.id).lower() == bid.lower()), None)
            if o and o.status == STATUS_ASSIGNED:
                o.status = STATUS_ACCEPTED
                o.accepted_at = ist_now()
                await db.commit()
                return {"reply": f"✅ Order #{bid} accepted!", "action": "accept_order", "action_data": {"id": str(bid)}}

    # Start/Complete
    if "start" in msg:
        bid = _extract_id(message)
        if bid:
            o = next((x for x in orders if str(x.id).lower() == bid.lower()), None)
            if o and o.status == STATUS_ACCEPTED:
                o.status = STATUS_STARTED
                o.started_at = ist_now()
                await db.commit()
                return {"reply": f"▶️ Order #{bid} started!", "action": "start_order", "action_data": None}
    
    if "complete" in msg or "done" in msg:
        bid = _extract_id(message)
        if bid:
            o = next((x for x in orders if str(x.id).lower() == bid.lower()), None)
            if o and o.status == STATUS_STARTED:
                o.status = STATUS_COMPLETED
                o.completed_at = ist_now()
                await db.commit()
                # Refresh profile for new score later
                await db.refresh(profile)
                return {"reply": f"✅ Order #{bid} completed! Well done.", "action": "complete_order", "action_data": None}

    # EL Score
    if any(kw in msg for kw in ["score", "my rating", "rank"]):
        sc = profile.el_score if profile else 65.0
        rt = profile.rating if profile else 0.0
        return {"reply": f"📊 **Your Stats:**\n\n• EL Score: {sc:.1f}/100\n• Avg Rating: {rt:.1f}★\n• Reviews: {profile.total_reviews if profile else 0}", "action": "show_score", "action_data": None}

    # Availability
    if any(kw in msg for kw in ["available", "online", "offline"]):
        if any(kw in msg for kw in ["go online", "turn on", "make available"]):
            if profile: profile.is_available = True
            await db.commit()
            return {"reply": "✅ You are now **Online**.", "action": "toggle_availability", "action_data": {"available": True}}
        if any(kw in msg for kw in ["go offline", "turn off", "unavailable"]):
            if profile: profile.is_available = False
            await db.commit()
            return {"reply": "❌ You are now **Offline**.", "action": "toggle_availability", "action_data": {"available": False}}

    # Profile
    if any(kw in msg for kw in ["my profile", "my account", "my skill"]):
        ps = profile.primary_skill if profile else "—"
        return {"reply": f"👤 **Profile:**\n• Name: {user.name}\n• Skill: {ps}\n• Exp: {profile.experience_years if profile else 0} yrs\n• EL Score: {profile.el_score if profile else 0:.1f}", "action": "show_profile", "action_data": None}

    # ── 3. Gemini Fallback ────────────────────────────────────────
    order_summary = "\n".join([f"- Order #{o.id}: {o.service.name if o.service else 'Svc'}, Status: {o.status}" for o in orders[:5]]) or "No orders"
    
    system_prompt = f"""You are an AI assistant for an Electrician on ElecSure.
Electrician: {user.name} | EL Score: {profile.el_score if profile else 0:.1f}
Recent Orders:
{order_summary}
Rules: Professional, concise. Help with order management.
Message: {message}"""

    reply = await _groq_reply(system_prompt, history)
    if reply: return {"reply": reply, "action": None, "action_data": None}

    return {"reply": "I can help with orders! Try 'my orders', 'accept #ID', or 'go online'.", "action": None, "action_data": None}


# ── Guest / landing page agent ────────────────────────────────────

async def guest_agent(message: str, history: list) -> dict:
    """Smart agent for unauthenticated visitors — with Gemini fallback."""
    msg = message.strip().lower()

    # Services / What do you offer
    if any(kw in msg for kw in ["service", "what can", "what do you", "repair", "fix", "install", "offer"]):
        return {
            "reply": (
                "⚡ **ElecSure offers 200+ electrical services in Karimnagar:**\n\n"
                "🔧 Appliance Repair · ⚡ Wiring & Circuits · 💡 Lighting\n"
                "🔌 Installations · 🛡️ Safety Checks · 🔋 Power Backup\n\n"
                "**Register free** to book a service!"
            ),
            "action": None, "action_data": None,
        }

    # Pricing
    if any(kw in msg for kw in ["price", "cost", "charge", "fee", "rate", "how much"]):
        return {
            "reply": (
                "💰 **Pricing at ElecSure:**\n\n"
                "Prices vary by service type. Most basic repairs start from ₹199.\n"
                "You'll see the exact price before confirming your booking.\n\n"
                "Login or Register to browse services with prices!"
            ),
            "action": None, "action_data": None,
        }

    # How to book
    if any(kw in msg for kw in ["how to book", "how do i book", "booking", "book a"]):
        return {
            "reply": (
                "📅 **How to Book on ElecSure:**\n\n"
                "1️⃣ Register or Login\n"
                "2️⃣ Browse services and select one\n"
                "3️⃣ Choose your date & time slot\n"
                "4️⃣ A verified electrician is assigned automatically\n"
                "5️⃣ Track them live in your dashboard!\n\n"
                "Ready? **Register free** to get started."
            ),
            "action": None, "action_data": None,
        }

    # Location / Area coverage
    if any(kw in msg for kw in ["location", "area", "karimnagar", "where", "pincode", "available in"]):
        return {
            "reply": (
                "📍 **ElecSure currently serves Karimnagar, Telangana.**\n\n"
                "We cover all major pincodes in and around Karimnagar district.\n"
                "Enter your pincode while booking to check if we're available in your area!"
            ),
            "action": None, "action_data": None,
        }

    # Contact / Support
    if any(kw in msg for kw in ["contact", "support", "help", "phone", "call", "email"]):
        return {
            "reply": (
                "📞 **Contact ElecSure Support:**\n\n"
                "• 📧 Email: support@elecsure.com\n"
                "• 📞 Phone: +91-1800-XXX-XXXX\n\n"
                "Or login to your account and use this chat for instant help!"
            ),
            "action": None, "action_data": None,
        }

    # Register / Login
    if any(kw in msg for kw in ["register", "sign up", "signup", "login", "log in", "create account"]):
        return {
            "reply": (
                "👤 **Get Started with ElecSure:**\n\n"
                "• **New user?** Register at /register — it's free!\n"
                "• **Existing user?** Login at /login\n\n"
                "Electricians can also register and start earning!"
            ),
            "action": None, "action_data": None,
        }

    # About ElecSure
    if any(kw in msg for kw in ["about", "who are you", "what is elecsure", "tell me about"]):
        return {
            "reply": (
                "⚡ **About ElecSure:**\n\n"
                "ElecSure is Karimnagar's trusted home electrical services platform.\n"
                "We connect you with verified, skilled electricians for any electrical need.\n\n"
                "✅ Verified electricians · 📍 Live tracking · ⭐ Rated & reviewed\n\n"
                "Register free to book your first service!"
            ),
            "action": None, "action_data": None,
        }

    # ── Gemini fallback for freeform questions ────────────────────
    system_prompt = f"""You are a helpful assistant for ElecSure, a home electrical services platform in Karimnagar, Telangana.
You help visitors learn about ElecSure services, how to book, pricing, and coverage area.
Keep responses short (3-5 lines), friendly, and always encourage them to register or login.
Visitor message: {message}"""

    reply = await _groq_reply(system_prompt, history)
    if reply:
        return {"reply": reply, "action": None, "action_data": None}

    # Final fallback
    return {
        "reply": (
            "👋 Hi! I'm the ElecSure assistant.\n\n"
            "I can help with:\n"
            "• Our **services** and **pricing**\n"
            "• **How to book** an electrician\n"
            "• **Coverage areas** in Karimnagar\n\n"
            "What would you like to know?"
        ),
        "action": None, "action_data": None,
    }
async def get_ai_response(
    message: str,
    db: AsyncSession,
    history: list,
    user_id: Optional[str] = None,
    role: Optional[str] = None
) -> dict:
    """Main dispatcher for AI Chatbot."""
    if not user_id:
        return await guest_agent(message, history)
    
    if role == "electrician":
        return await electrician_agent(message, user_id, db, history)
    
    # Default to customer agent for "customer" or "admin" (admin acts as customer for testing)
    return await customer_agent(message, user_id, db, history)
