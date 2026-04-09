"""app/services/auth_service.py — Auth logic: registration, OTP, login, password management."""

import json
import logging
import random
from typing import Optional, Dict, Any, Tuple
from datetime import timedelta
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from fastapi import HTTPException, status, BackgroundTasks, Response

from app.core.security import (
    hash_password, verify_password, create_access_token,
    create_refresh_token, ist_now,
)
from app.models import (User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN,
                        TOOLKIT_NONE, TOOLKIT_BASIC, TOOLKIT_ADVANCED, TOOLKIT_BOTH,
                        PendingUser, CustomerProfile, ElectricianProfile, ELScoreEvent)
from app.schemas.auth import (
    LoginRequest, TokenResponse, RegisterCustomer, RegisterElectrician,
)
from app.services.notification_service import notify_otp
from app.services.el_score_service import apply_el_event

logger = logging.getLogger(__name__)

class AuthService:
    @staticmethod
    def _gen_otp() -> str:
        return str(random.randint(100000, 999999))

    @staticmethod
    async def email_exists(db: AsyncSession, email: str) -> bool:
        r = await db.execute(select(User).where(User.email == email.lower()))
        return r.scalar_one_or_none() is not None

    @staticmethod
    async def build_token_response(db: AsyncSession, user: User) -> TokenResponse:
        access_token = create_access_token(user.id, user.role)
        refresh_token = create_refresh_token(user.id)
        user.refresh_token = refresh_token
        await db.commit()
        return TokenResponse(
            access_token=access_token, 
            refresh_token=refresh_token,
            token_type="bearer", 
            role=user.role, 
            user_id=user.id, 
            name=user.name,
        )

    @staticmethod
    async def set_auth_cookies(response: Response, token_resp: TokenResponse):
        response.set_cookie(key="access_token", value=token_resp.access_token, httponly=True, max_age=30*60, samesite="lax", path="/")
        response.set_cookie(key="refresh_token", value=token_resp.refresh_token, httponly=True, max_age=7*24*3600, samesite="lax", path="/")

    @staticmethod
    async def start_registration(db: AsyncSession, data: Any, role: str, background_tasks: BackgroundTasks) -> str:
        if await AuthService.email_exists(db, data.email):
            raise HTTPException(status_code=400, detail="Email already registered")

        email_otp, mobile_otp = AuthService._gen_otp(), AuthService._gen_otp()
        await db.execute(delete(PendingUser).where(PendingUser.email == data.email.lower()))
        
        pending = PendingUser(
            email=data.email.lower().strip(),
            phone=data.phone.strip(),
            role=role,
            user_data=data.model_dump_json(),
            otp_code=email_otp,
            otp_mobile_code=mobile_otp,
            otp_expires_at=ist_now() + timedelta(minutes=10),
            otp_attempts=0,
        )
        db.add(pending)
        await db.commit()

        background_tasks.add_task(notify_otp, pending.email, pending.phone, email_otp, mobile_otp, "registration")
        return pending.email

    @staticmethod
    async def verify_otp(db: AsyncSession, email: str, code: str) -> User:
        r = await db.execute(select(PendingUser).where(PendingUser.email == email.lower()))
        pending = r.scalar_one_or_none()
        if not pending:
            user_r = await db.execute(select(User).where(User.email == email.lower()))
            if user_r.scalar_one_or_none(): raise HTTPException(status_code=400, detail="Account already verified.")
            raise HTTPException(status_code=404, detail="Pending registration not found.")

        now = ist_now()
        if pending.otp_blocked_until and pending.otp_blocked_until > now:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

        if pending.otp_code != code:
            pending.otp_attempts += 1
            if pending.otp_attempts >= 5: pending.otp_blocked_until = now + timedelta(minutes=30)
            await db.commit()
            raise HTTPException(status_code=400, detail="Invalid email verification code.")

        if pending.otp_expires_at < now:
            raise HTTPException(status_code=400, detail="OTP has expired. Please request a new one.")

        # Create user logic
        user_data = json.loads(pending.user_data)
        user = User(
            name=user_data["name"].strip(), email=user_data["email"].lower().strip(),
            phone=user_data["phone"].strip(), hashed_password=hash_password(user_data["password"]),
            role=pending.role, is_active=True, is_verified=(pending.role == ROLE_CUSTOMER), is_otp_verified=True,
        )
        db.add(user)
        await db.flush() # get user.id

        if pending.role == ROLE_CUSTOMER:
            profile = CustomerProfile(
                user_id=user.id,
                **{k: user_data.get(k) for k in ("flat_no", "landmark", "village", "district", "state", "pincode", "full_address")}
            )
            db.add(profile)
        elif pending.role == ROLE_ELECTRICIAN:
            profile = ElectricianProfile(
                user_id=user.id,
                is_available=True, toolkit=user_data.get("toolkit", TOOLKIT_NONE), el_score=50.0,
                **{k: user_data.get(k) for k in ("skills", "primary_skill", "experience_years")}
            )
            # Also need to create a CustomerProfile for electricians if they want to book? 
            # Usually yes for complete profile separation.
            cust_profile = CustomerProfile(
                user_id=user.id,
                **{k: user_data.get(k) for k in ("flat_no", "landmark", "village", "district", "state", "pincode", "full_address")}
            )
            db.add(profile)
            db.add(cust_profile)
            await db.flush()
            if profile.toolkit in (TOOLKIT_ADVANCED, TOOLKIT_BOTH):
                await apply_el_event(db, user.id, ELScoreEvent.TOOLKIT_ADVANCED, notes="Registration bonus")
        
        await db.execute(delete(PendingUser).where(PendingUser.email == email.lower()))
        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def resend_otp(db: AsyncSession, email: str, background_tasks: BackgroundTasks) -> bool:
        r = await db.execute(select(PendingUser).where(PendingUser.email == email.lower()))
        pending = r.scalar_one_or_none()
        if not pending: return False

        now = ist_now()
        if (pending.otp_expires_at - now).total_seconds() > 540:
            raise HTTPException(status_code=429, detail="Please wait before requesting a new code.")

        email_otp, mobile_otp = AuthService._gen_otp(), AuthService._gen_otp()
        pending.otp_code, pending.otp_mobile_code = email_otp, mobile_otp
        pending.otp_expires_at, pending.otp_attempts, pending.otp_blocked_until = now + timedelta(minutes=10), 0, None
        await db.commit()
        background_tasks.add_task(notify_otp, pending.email, pending.phone, email_otp, mobile_otp, "registration")
        return True

    @staticmethod
    async def login(db: AsyncSession, data: LoginRequest) -> User:
        r = await db.execute(select(User).where(User.email == data.email.lower()))
        user = r.scalar_one_or_none()
        _invalid = HTTPException(status_code=401, detail="Invalid email or password")

        if not user or not user.is_active: 
            if user and not user.is_active: raise HTTPException(status_code=403, detail="Account deactivated")
            raise _invalid

        now = ist_now()
        if user.login_blocked_until and user.login_blocked_until > now:
            raise HTTPException(status_code=429, detail="Too many attempts. Try again later.")

        if user.auth_provider == "google" and not user.has_password:
            raise HTTPException(status_code=403, detail="Google-only user. Use Google login.")

        if not user.has_password or not verify_password(data.password, user.hashed_password):
            user.failed_login_attempts = (user.failed_login_attempts or 0) + 1
            if user.failed_login_attempts >= 5: user.login_blocked_until = now + timedelta(minutes=15)
            await db.commit()
            raise _invalid

        user.failed_login_attempts, user.login_blocked_until, user.last_login = 0, None, now
        await db.commit()
        return user

    @staticmethod
    async def social_complete(db: AsyncSession, data: dict) -> User:
        role = data.get("role", ROLE_CUSTOMER)
        email = data.get("email", "").lower()

        if await AuthService.email_exists(db, email):
            raise HTTPException(status_code=400, detail="User already registered.")

        user = User(
            name=data.get("name", "").strip(), email=email, phone=data.get("phone", "").strip(),
            google_id=data.get("google_id"), auth_provider="google", role=role,
            is_active=True, is_verified=(role == ROLE_CUSTOMER), is_otp_verified=True,
        )
        db.add(user)
        await db.flush()

        # Customer Profile
        cust_profile = CustomerProfile(
            user_id=user.id,
            **{k: data.get(k) for k in ("flat_no", "landmark", "village", "district", "state", "pincode")}
        )
        db.add(cust_profile)

        if role == ROLE_ELECTRICIAN:
            profile = ElectricianProfile(
                user_id=user.id,
                skills=data.get("skills", "").strip(),
                primary_skill=data.get("primary_skill", "").strip(),
                experience_years=int(data.get("experience_years", 0)),
                toolkit=data.get("toolkit", TOOLKIT_NONE),
                is_available=True
            )
            db.add(profile)

        await db.commit()
        await db.refresh(user)
        return user

    @staticmethod
    async def change_password(db: AsyncSession, user: User, old_password: Optional[str], new_password: str) -> bool:
        if not user.has_password:
            user.hashed_password = hash_password(new_password)
            if user.auth_provider == "google": user.auth_provider = "hybrid"
        else:
            if not old_password or not verify_password(old_password, user.hashed_password):
                raise HTTPException(status_code=400, detail="Current password is incorrect")
            user.hashed_password = hash_password(new_password)
        
        user.updated_at = ist_now()
        await db.commit()
        return True
