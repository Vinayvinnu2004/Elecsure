"""app/routers/users.py — User profile management, service areas, availability, location."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.dependencies import get_current_user, require_electrician, require_electrician_login
from app.core.security import ist_now, sanitize_html
from app.models import (
    User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN, 
    ServiceArea, ElectricianProfile, 
    Booking, STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED,
    TimeSlot, SLOT_AVAILABLE, ELScoreEvent
)
from app.schemas.user import (
    UserOut, UserProfileUpdate, ElectricianProfileUpdate,
    ServiceAreaIn, ServiceAreaOut, LocationUpdate,
    EmailChangeRequest, EmailChangeVerify
)
from app.schemas.common import MessageOut

router = APIRouter(prefix="/api/v1/users", tags=["Users"])
logger = logging.getLogger(__name__)


# ── Profile ───────────────────────────────────────────────────────────

@router.get("/me", response_model=UserOut)
async def get_my_profile(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    from sqlalchemy.orm import selectinload
    r = await db.execute(
        select(User).options(
            selectinload(User.customer_profile),
            selectinload(User.electrician_profile),
            selectinload(User.earnings)
        ).where(User.id == user.id)
    )
    return r.scalar_one()


@router.put("/me", response_model=UserOut)
async def update_my_profile(
    data: UserProfileUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import selectinload
    # Reload with all relations needed
    r0 = await db.execute(
        select(User).options(
            selectinload(User.customer_profile),
            selectinload(User.electrician_profile),
            selectinload(User.earnings),
        ).where(User.id == user.id)
    )
    user = r0.scalar_one()

    updates = data.model_dump(exclude_unset=True)
    if "phone" in updates and updates["phone"]:
        r = await db.execute(select(User).where(User.phone == updates["phone"].strip(), User.id != user.id))
        if r.scalars().first():
            raise HTTPException(status_code=400, detail="Mobile is already registered")
    
    if "email" in updates and updates["email"]:
        email_clean = updates["email"].lower().strip()
        r = await db.execute(select(User).where(User.email == email_clean, User.id != user.id))
        if r.scalars().first():
            raise HTTPException(status_code=400, detail="Email already registered")
        updates["email"] = email_clean

    # Fields that belong to User model
    USER_FIELDS = {"email", "name", "phone", "alternate_phone"}
    # Fields that belong to CustomerProfile model
    CUSTOMER_PROFILE_FIELDS = {"flat_no", "landmark", "village", "district", "state", "pincode", "full_address"}

    for field, value in updates.items():
        if field in USER_FIELDS:
            if isinstance(value, str) and field not in ("email", "phone"):
                value = sanitize_html(value)
            setattr(user, field, value)
        elif field in CUSTOMER_PROFILE_FIELDS and user.role == "customer":
            if user.customer_profile is None:
                from app.models.user import CustomerProfile
                cp = CustomerProfile(user_id=user.id)
                db.add(cp)
                user.customer_profile = cp
            if isinstance(value, str):
                value = sanitize_html(value)
            setattr(user.customer_profile, field, value)

    user.updated_at = ist_now()
    await db.commit()
    
    r_reload = await db.execute(
        select(User)
        .options(
            selectinload(User.customer_profile),
            selectinload(User.electrician_profile),
            selectinload(User.earnings)
        )
        .where(User.id == user.id)
    )
    return r_reload.scalar_one()


@router.put("/me/electrician", response_model=UserOut)
async def update_electrician_profile(
    data: ElectricianProfileUpdate,
    user: User = Depends(require_electrician_login),
    db: AsyncSession = Depends(get_db),
):
    try:
        from sqlalchemy.orm import joinedload
        r_up = await db.execute(
            select(User)
            .options(joinedload(User.electrician_profile), joinedload(User.customer_profile))
            .where(User.id == user.id)
        )
        user = r_up.scalar_one()
        profile = user.electrician_profile
        c_profile = user.customer_profile
        if not c_profile:
            from app.models.user import CustomerProfile
            c_profile = CustomerProfile(user_id=user.id)
            db.add(c_profile)
            user.customer_profile = c_profile

        if not profile:
            raise HTTPException(status_code=404, detail="Electrician profile not found")

        updates = data.model_dump(exclude_unset=True)

        if "phone" in updates and updates["phone"]:
            target_phone = str(updates["phone"]).strip()
            from sqlalchemy import func
            r = await db.execute(
                select(User).where(
                    func.trim(User.phone) == target_phone, 
                    User.id != user.id
                )
            )
            colliding_user = r.scalars().first()
            if colliding_user:
                raise HTTPException(status_code=400, detail="Mobile number is already registered to another account")

        if "email" in updates and updates["email"]:
            email_clean = updates["email"].lower().strip()
            r = await db.execute(select(User).where(User.email == email_clean, User.id != user.id))
            if r.scalars().first():
                raise HTTPException(status_code=400, detail="Email already registered")
            updates["email"] = email_clean

        # Toolkit EL bonus
        if "toolkit" in updates and updates["toolkit"]:
            toolkit_order = {"none": 0, "basic": 1, "advanced": 2, "both": 3}
            old_val = str(profile.toolkit or "none").lower()
            new_val = str(updates["toolkit"]).lower()
            
            if toolkit_order.get(new_val, 0) > toolkit_order.get(old_val, 0):
                from app.services.el_score_service import apply_el_event
                await apply_el_event(db, user.id, ELScoreEvent.TOOLKIT_ADVANCED,
                                      notes=f"Toolkit upgraded from {old_val} to {new_val}")
            
            profile.toolkit = new_val

        # Skills bonus
        if "skills" in updates:
            new_skills_raw = str(updates.get("skills") or "")
            old_skills_raw = str(profile.skills or "")
            
            old_skills = {s.strip().lower() for s in old_skills_raw.split(",") if s.strip()}
            new_skills = {s.strip().lower() for s in new_skills_raw.split(",") if s.strip()}
            
            added = new_skills - old_skills
            if added:
                from app.services.el_score_service import apply_el_event
                for skill_name in added:
                    await apply_el_event(db, user.id, ELScoreEvent.SKILL_ADDED,
                                          notes=f"New skill added: {skill_name}")
            profile.skills = new_skills_raw

        # Update core user fields
        for field in ("email", "phone", "name", "alternate_phone"):
            if field in updates:
                val = updates[field]
                if isinstance(val, str) and field not in ("email", "phone"):
                    val = sanitize_html(val)
                setattr(user, field, val)

        # Update specialized profile fields
        for field in ("experience_years", "bio", "id_proof_url", "is_available", "primary_skill"):
            if field in updates:
                setattr(profile, field, updates[field])

        # Update customer profile fields (address)
        if c_profile:
            for field in ("pincode", "district", "state", "full_address", "flat_no", "village", "landmark"):
                if field in updates:
                    setattr(c_profile, field, updates[field])
                
        user.updated_at = ist_now()
        await db.commit()
        
        # Reload with all relations
        r_reload = await db.execute(
            select(User)
            .options(
                joinedload(User.electrician_profile),
                joinedload(User.customer_profile),
                joinedload(User.earnings)
            )
            .where(User.id == user.id)
        )
        return r_reload.scalar_one()
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Final Catch: Profile update failed for user %s: %s", getattr(user, 'id', 'unknown'), e)
        raise HTTPException(
            status_code=500, 
            detail=f"System error during update. Error: {str(e)}"
        )


# ── Availability Toggle ───────────────────────────────────────────────

@router.post("/me/availability", response_model=MessageOut)
async def toggle_availability(
    user: User = Depends(require_electrician),
    db: AsyncSession = Depends(get_db),
):
    try:
        # Load profile
        from sqlalchemy.orm import joinedload
        r_up = await db.execute(
            select(User).options(joinedload(User.electrician_profile))
            .where(User.id == user.id)
        )
        user = r_up.scalar_one()
        profile = user.electrician_profile
        if not profile:
            raise HTTPException(status_code=404, detail="Profile not found")

        # Block turning OFF when an active service is in progress
        if profile.is_available:
            r = await db.execute(
                select(Booking).where(
                    Booking.electrician_id == user.id,
                    Booking.status.in_([STATUS_ASSIGNED, STATUS_ACCEPTED, STATUS_STARTED]),
                )
            )
            if r.scalars().first():
                raise HTTPException(
                    status_code=400,
                    detail="Cannot turn off availability — you have a pending or active assignment",
                )

            # Check mid-slot violation: if the electrician turns off availability
            # while a BOOKED slot is currently active (i.e. started but not yet ended),
            # that is a violation. Slots are always SLOT_BOOKED when active.
            now = ist_now()
            r2 = await db.execute(
                select(TimeSlot).where(
                    TimeSlot.electrician_id == user.id,
                    TimeSlot.status == SLOT_BOOKED,
                    TimeSlot.start_time <= now,
                    TimeSlot.end_time >= now,
                )
            )
            ongoing_slot = r2.scalars().first()
            if ongoing_slot:
                from app.services.el_score_service import apply_el_event
                from app.models import ELScoreEvent
                await apply_el_event(db, user.id, ELScoreEvent.AVAILABILITY_MID_SLOT,
                                      notes="Turned off availability mid-slot")
                # Mark violation tracker (status finalized as FAILED after slot time completes)
                ongoing_slot.violated_mid_slot = True
                ongoing_slot.status_updated_at = now

        profile.is_available = not profile.is_available
        user.updated_at = ist_now()
        status_str = "available" if profile.is_available else "unavailable"
        await db.commit()
        return MessageOut(message=f"Availability updated — you are now {status_str}")
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=repr(e))


# ── Service Areas ─────────────────────────────────────────────────────

@router.get("/me/service-areas", response_model=List[ServiceAreaOut])
async def get_service_areas(
    user: User = Depends(require_electrician_login),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(select(ServiceArea).where(ServiceArea.electrician_id == user.id))
    return r.scalars().all()


@router.post("/me/service-areas", response_model=ServiceAreaOut, status_code=201)
async def add_service_area(
    data: ServiceAreaIn,
    user: User = Depends(require_electrician_login),
    db: AsyncSession = Depends(get_db),
):
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Your account is pending admin verification. You cannot add service areas yet.")
        
    r = await db.execute(
        select(ServiceArea).where(
            ServiceArea.electrician_id == user.id,
            ServiceArea.pincode == data.pincode,
        )
    )
    if r.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Pincode already in your service areas")

    # Add geocode data if available in constants
    from app.core.constants import KARIMNAGAR_PINCODES
    pin_data = KARIMNAGAR_PINCODES.get(data.pincode)
    
    area = ServiceArea(
        electrician_id=user.id,
        pincode=data.pincode,
        district=data.district,
        state=data.state,
        latitude=pin_data["lat"] if pin_data else None,
        longitude=pin_data["lng"] if pin_data else None,
        radius_km=5.0 # Default
    )
    db.add(area)
    await db.flush()
    await db.refresh(area)
    return area


@router.delete("/me/service-areas/{area_id}", response_model=MessageOut)
async def remove_service_area(
    area_id: str,
    user: User = Depends(require_electrician_login),
    db: AsyncSession = Depends(get_db),
):
    r = await db.execute(
        select(ServiceArea).where(
            ServiceArea.id == area_id, ServiceArea.electrician_id == user.id,
        )
    )
    area = r.scalar_one_or_none()
    if not area:
        raise HTTPException(status_code=404, detail="Service area not found")
    await db.delete(area)
    await db.commit()
    return MessageOut(message="Service area removed")


# ── Location (electrician GPS) ────────────────────────────────────────

@router.post("/me/location", response_model=MessageOut)
async def update_location(
    data: LocationUpdate,
    user: User = Depends(require_electrician),
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy.orm import joinedload
    r_up = await db.execute(
        select(User).options(joinedload(User.electrician_profile))
        .where(User.id == user.id)
    )
    user = r_up.scalar_one()
    profile = user.electrician_profile
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")

    profile.current_lat = data.latitude
    profile.current_lng = data.longitude
    profile.location_updated_at = ist_now()

    # Broadcast to WebSocket watchers for any active bookings
    from app.routers.websocket import broadcast_location
    import asyncio
    r = await db.execute(
        select(Booking).where(
            Booking.electrician_id == user.id,
            Booking.status.in_([STATUS_ACCEPTED, STATUS_STARTED]),
        )
    )
    active_bookings = r.scalars().all()
    for booking in active_bookings:
        asyncio.create_task(broadcast_location(
            booking.id, user.id, data.latitude, data.longitude,
        ))

    await db.commit()
    return MessageOut(message="Location updated")


@router.get("/electrician/{electrician_id}/location")
async def get_electrician_location(
    electrician_id: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns live location only if the requesting customer has an active booking."""
    r = await db.execute(
        select(Booking).where(
            Booking.customer_id == current_user.id,
            Booking.electrician_id == electrician_id,
            Booking.status.in_([STATUS_ACCEPTED, STATUS_STARTED]),
        )
    )
    if not r.scalars().first():
        raise HTTPException(
            status_code=403,
            detail="No active booking with this electrician",
        )
    
    from sqlalchemy.orm import joinedload
    r_up = await db.execute(
        select(User).options(joinedload(User.electrician_profile))
        .where(User.id == electrician_id)
    )
    elec = r_up.scalar_one_or_none()
    if not elec or not elec.electrician_profile:
        raise HTTPException(status_code=404, detail="Electrician not found")
    
    profile = elec.electrician_profile
    return {
        "electrician_id": elec.id,
        "name": elec.name,
        "latitude": profile.current_lat,
        "longitude": profile.current_lng,
        "location_updated_at": profile.location_updated_at,
    }



@router.post("/request-email-change", response_model=MessageOut)
async def request_email_change(
    data: EmailChangeRequest,
    bg: BackgroundTasks,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    email_clean = data.new_email.lower().strip()
    if email_clean == user.email:
        raise HTTPException(status_code=400, detail="New email must be different from current email.")
    
    # Check if email is already taken by another user
    r = await db.execute(select(User).where(User.email == email_clean))
    if r.scalars().first():
        raise HTTPException(status_code=400, detail="Email already registered")

    from app.core.security import generate_otp
    from app.services.notification_service import notify_otp
    from datetime import timedelta
    
    otp = generate_otp()
    user.new_email_temp = email_clean
    user.otp_code = otp
    user.otp_expires_at = ist_now() + timedelta(minutes=10)
    user.otp_attempts = 0
    await db.commit()
    
    # Send OTP to NEW email
    bg.add_task(notify_otp, email_clean, user.phone, otp, otp, "email change")
    return MessageOut(message="Verification code sent to your new email address.")


@router.post("/verify-email-change", response_model=MessageOut)
async def verify_email_change(
    data: EmailChangeVerify,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timedelta
    now = ist_now()
    if user.otp_blocked_until and user.otp_blocked_until > now:
        raise HTTPException(status_code=403, detail="Too many attempts. Blocked.")

    if not user.new_email_temp or user.new_email_temp != data.new_email.lower().strip():
        raise HTTPException(status_code=400, detail="Invalid email change request.")

    if not user.otp_code or user.otp_code != data.otp or (user.otp_expires_at and user.otp_expires_at < now):
        user.otp_attempts += 1
        if user.otp_attempts >= 3:
            user.otp_blocked_until = now + timedelta(minutes=30)
        await db.commit()
        raise HTTPException(status_code=400, detail="Invalid or expired verification code.")

    # Success
    user.email = user.new_email_temp
    user.new_email_temp = None
    user.otp_code = None
    user.otp_expires_at = None
    user.otp_attempts = 0
    await db.commit()
    return MessageOut(message="Email updated successfully. Please re-login for security.")


@router.delete("/me", response_model=MessageOut)
async def delete_my_account(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.is_active = False
    user.updated_at = ist_now()
    await db.commit()
    return MessageOut(message="Account deactivated successfully.")

