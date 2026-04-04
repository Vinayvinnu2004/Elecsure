"""app/core/dependencies.py — FastAPI reusable auth dependencies."""

from fastapi import Depends, HTTPException, status, Cookie, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.database import get_db
from app.core.security import decode_token
from app.core.database import get_db
from app.core.security import decode_token
from app.models import User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)


async def get_current_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    # Try Bearer token first, then cookie (for HTML pages)
    if not token:
        token = request.cookies.get("access_token")

    creds_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise creds_exception

    payload = decode_token(token)
    if not payload:
        raise creds_exception

    user_id = payload.get("sub")
    if not user_id:
        raise creds_exception

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise creds_exception
    
    # user.role is now a string constant
    if not user.is_otp_verified and user.role != ROLE_ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="OTP verification required. Please verify your mobile/email.",
        )
    return user


async def get_optional_user(
    request: Request,
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User | None:
    try:
        return await get_current_user(request, token, db)
    except HTTPException:
        return None


async def require_customer(user: User = Depends(get_current_user)) -> User:
    if user.role not in (ROLE_CUSTOMER, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Customer access required")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Your account is pending admin verification. You can book services once verified.")
    return user


async def require_electrician(user: User = Depends(get_current_user)) -> User:
    if user.role not in (ROLE_ELECTRICIAN, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Electrician access required")
    if not user.is_verified:
        raise HTTPException(status_code=403, detail="Your profile is pending admin verification. You will start receiving orders once verified.")
    return user


async def require_electrician_login(user: User = Depends(get_current_user)) -> User:
    """Allows unverified electricians to still access profile/area management."""
    if user.role not in (ROLE_ELECTRICIAN, ROLE_ADMIN):
        raise HTTPException(status_code=403, detail="Electrician access required")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if user.role != ROLE_ADMIN:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

