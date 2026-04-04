"""app/routers/auth.py — Authentication endpoints: register, OTP, login, logout, password."""

import logging
from fastapi import APIRouter, Depends, HTTPException, Response, Request, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.core.database import get_db
from app.core.dependencies import get_current_user
from app.core.security import decode_token, ist_now
from app.models import User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN
from app.schemas.auth import (
    LoginRequest, TokenResponse, RegisterCustomer, RegisterElectrician,
    PasswordChangeRequest,
)
from app.schemas.common import MessageOut
from app.services.auth_service import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["Auth"])
logger = logging.getLogger(__name__)


# ── Schemas ────────────────────────────────────────────────────────────

class OTPVerifyRequest(BaseModel):
    email: str
    code: str
    mobile_code: str | None = None


# ── Registration ───────────────────────────────────────────────────────

@router.post("/register/customer", status_code=201)
async def register_customer(
    data: RegisterCustomer,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = await AuthService.start_registration(db, data, ROLE_CUSTOMER, background_tasks)
    logger.info("Customer registration started: %s", email)
    return {"message": "OTP sent to your email and mobile. Please verify.", "email": email}


@router.post("/register/electrician", status_code=201)
async def register_electrician(
    data: RegisterElectrician,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    email = await AuthService.start_registration(db, data, ROLE_ELECTRICIAN, background_tasks)
    logger.info("Electrician registration started: %s", email)
    return {"message": "OTP sent to your email and mobile. Please verify.", "email": email}


# ── OTP Verify & Resend ────────────────────────────────────────────────

@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(
    data: OTPVerifyRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await AuthService.verify_otp(db, data.email, data.code)
    token_resp = await AuthService.build_token_response(db, user)
    await AuthService.set_auth_cookies(response, token_resp)
    logger.info("Account verified via OTP: %s", user.email)
    return token_resp


@router.post("/resend-otp", response_model=MessageOut)
async def resend_otp(
    background_tasks: BackgroundTasks,
    email: str,
    db: AsyncSession = Depends(get_db),
):
    await AuthService.resend_otp(db, email, background_tasks)
    return MessageOut(message="If the email exists, a new code has been sent.")


# ── Social (Google) Registration Completion ────────────────────────────

@router.post("/social-complete", response_model=TokenResponse)
async def social_complete(
    data: dict,
    response: Response,
    db: AsyncSession = Depends(get_db),
):
    user = await AuthService.social_complete(db, data)
    token_resp = await AuthService.build_token_response(db, user)
    await AuthService.set_auth_cookies(response, token_resp)
    logger.info("Social registration completed: %s", user.email)
    return token_resp


# ── Login ──────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, response: Response, db: AsyncSession = Depends(get_db)):
    user = await AuthService.login(db, data)
    token_resp = await AuthService.build_token_response(db, user)
    await AuthService.set_auth_cookies(response, token_resp)
    return token_resp


@router.post("/token", response_model=TokenResponse, include_in_schema=False)
async def token_login(
    form: OAuth2PasswordRequestForm = Depends(),
    response: Response = Response(),
    db: AsyncSession = Depends(get_db),
):
    """Swagger UI login support."""
    return await login(LoginRequest(email=form.username, password=form.password), response, db)


# ── Logout ─────────────────────────────────────────────────────────────

@router.post("/logout", response_model=MessageOut)
async def logout(
    response: Response,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user.refresh_token = None
    await db.commit()
    response.delete_cookie("access_token")
    response.delete_cookie("refresh_token")
    return MessageOut(message="Logged out successfully")


# ── Refresh Token ──────────────────────────────────────────────────────

@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    refresh = request.cookies.get("refresh_token")
    if not refresh:
        raise HTTPException(status_code=401, detail="Session expired. Please login again.")

    payload = decode_token(refresh)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid session. Please login again.")

    uid = payload.get("sub")
    r = await db.execute(select(User).where(User.id == uid, User.refresh_token == refresh))
    user = r.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Account unavailable or session revoked.")

    token_resp = await AuthService.build_token_response(db, user)
    await AuthService.set_auth_cookies(response, token_resp)
    return token_resp


# ── Change Password ────────────────────────────────────────────────────

@router.post("/change-password", response_model=MessageOut)
async def change_password(
    data: PasswordChangeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not user.has_password and not data.new_password:
        raise HTTPException(status_code=400, detail="New password is required")

    await AuthService.change_password(db, user, data.old_password, data.new_password)

    msg = "Password set successfully." if not user.has_password else "Password changed successfully"
    return MessageOut(message=msg)


# ── Me (Quick profile) ─────────────────────────────────────────────────

@router.get("/me")
async def get_me(user: User = Depends(get_current_user)):
    return {
        "id": user.id, "name": user.name,
        "email": user.email, "role": user.role,
        "is_verified": user.is_verified,
    }

