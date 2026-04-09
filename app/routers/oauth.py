"""app/routers/oauth.py — Google OAuth flow with Dual Token support."""

import logging
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.config import settings
from app.core.database import get_db
from app.core.security import create_access_token, create_refresh_token, ist_now
from app.models import User, UserRole
from app.services.oauth_service import GoogleOAuthService

router = APIRouter(prefix="/api/v1/auth/google", tags=["OAuth"])
logger = logging.getLogger(__name__)

# -- Helpers ----------------------------------------------------------

def _set_jwt_cookies(response: Response, access: str, refresh: str):
    """Utility to set both access and refresh tokens in secure cookies."""
    response.set_cookie(
        key="access_token",
        value=access,
        httponly=True,
        max_age=30 * 60,  # 30 mins
        samesite="lax",
        secure=False,      # Set to True in HTTPS production
        path="/",
    )
    response.set_cookie(
        key="refresh_token",
        value=refresh,
        httponly=True,
        max_age=7 * 24 * 3600, # 7 days
        samesite="lax",
        secure=False,
        path="/",
    )

# -- Google OAuth Flow ------------------------------------------------

@router.get("/login")
async def google_login(role: str = "customer", mode: str = "login"):
    """Initiate Google OAuth2 flow by redirecting to Google Consent screen."""
    state = f"{mode}:{role}"
    auth_url = GoogleOAuthService.get_authorization_url(state=state)
    return RedirectResponse(url=auth_url)


@router.get("/callback")
async def google_callback(request: Request, response: Response, db: AsyncSession = Depends(get_db)):
    """Handle callback from Google, exchange code for user info, and login."""
    code = request.query_params.get("code")
    state = request.query_params.get("state", "login:customer")
    if not code:
        raise HTTPException(status_code=400, detail="Missing authorization code")
        
    mode, role = (state.split(":") + ["customer"])[:2]

    try:
        # 1. Exchange code for access token and get user info
        user_info = await GoogleOAuthService.get_user_info(code)
        email = user_info.get("email", "").lower()
        # Google userinfo v3 uses 'sub' as unique id (v2 used 'id')
        google_id = user_info.get("sub") or user_info.get("id")
        name = user_info.get("name", "Google User")
        picture = user_info.get("picture")

        if not email or not google_id:
            logger.error("Google OAuth returned incomplete profile: %s", user_info)
            return RedirectResponse(url=f"{settings.BASE_URL}/login?error=missing_profile")

        # 2. Check if user exists (by google_id first, then by email)
        r = await db.execute(select(User).where(User.google_id == google_id))
        user = r.scalar_one_or_none()

        if not user:
            r = await db.execute(select(User).where(User.email == email))
            user = r.scalar_one_or_none()

            if user:
                # Link existing local account to Google → upgrade to hybrid if they had a password
                user.google_id = google_id
                user.auth_provider = "hybrid" if user.has_password else "google"
                if picture and not user.profile_photo:
                    user.profile_photo = picture
            else:
                # User doesn't exist AND they tried to login with Google
                # Redirect to register page with pre-filled details to ensure required fields are collected
                import urllib.parse
                params = {
                    "email": email,
                    "name": name,
                    "google_id": google_id,
                    "mode": "social_register"
                }
                qs = urllib.parse.urlencode(params)
                logger.info("Social registration redirect for: %s", email)
                return RedirectResponse(url=f"{settings.BASE_URL}/social-register?{qs}")

        # 3. Generate Dual Tokens
        access_token = create_access_token(user.id, user.role)
        refresh_token = create_refresh_token(user.id)
        
        # 4. Update session-related fields
        user.last_login = ist_now()
        user.refresh_token = refresh_token
        await db.commit()

        # 5. Redirect with tokens based on role
        # Roles: customer -> /customer, electrician -> /electrician, admin -> /admin
        target_path = f"/{user.role}"
        frontend_url = f"{settings.BASE_URL}{target_path}?login_success=true"
        redirect_response = RedirectResponse(url=frontend_url)
        
        _set_jwt_cookies(redirect_response, access_token, refresh_token)
        
        logger.info("Google OAuth login successful: %s", email)
        return redirect_response

    except Exception as e:
        logger.error("Google OAuth error: %s", str(e))
        return RedirectResponse(url=f"{settings.BASE_URL}/login?error=oauth_failed")
