"""
app/services/oauth_service.py — Google OAuth account linking service.

Implements the full account linking strategy:
  1. Look up by google_id (fastest — already linked)
  2. Look up by email (existing local account — link it)
  3. Neither found — create brand-new Google-only account

Invariants guaranteed by this service:
  - One row per email (no duplicates)
  - google_id is unique across the table
  - A local (email+password) account can be linked to Google by email
  - Once linked, google_id lookup is used on every subsequent login (O(1) indexed)
"""

import logging
import dataclasses
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.core.security import ist_now
from app.models import User, ROLE_CUSTOMER, ROLE_ELECTRICIAN, ROLE_ADMIN
logger = logging.getLogger(__name__)

from app.core.config import settings
import httpx

class GoogleOAuthService:
    @staticmethod
    def get_authorization_url(state: str = None) -> str:
        """
        Builds the Google OAuth2 authorization URL.
        'state' is used to pass through context (e.g. 'login:customer' or 'register:electrician').
        """
        params = {
            "client_id": settings.GOOGLE_CLIENT_ID,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "response_type": "code",
            "scope": "openid email profile",
            "access_type": "offline",
            "prompt": "select_account",
        }
        if state:
            params["state"] = state
        query = "&".join([f"{k}={v}" for k, v in params.items()])
        return f"https://accounts.google.com/o/oauth2/v2/auth?{query}"

    @staticmethod
    async def get_user_info(code: str) -> dict:
        token_url = "https://oauth2.googleapis.com/token"
        data = {
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient() as client:
            try:
                # 1. Exchange code for access token
                resp = await client.post(token_url, data=data)
                if not resp.is_success:
                    logger.error("OAuth token exchange failed: %s - %s", resp.status_code, resp.text)
                    resp.raise_for_status()
                tokens = resp.json()
                
                # 2. Get user profile
                info_url = "https://www.googleapis.com/oauth2/v3/userinfo"
                headers = {"Authorization": f"Bearer {tokens['access_token']}"}
                profile_resp = await client.get(info_url, headers=headers)
                if not profile_resp.is_success:
                    logger.error("OAuth profile fetch failed: %s - %s", profile_resp.status_code, profile_resp.text)
                    profile_resp.raise_for_status()
                return profile_resp.json()
            except httpx.ConnectError:
                logger.error("OAuth connection error (network/proxy?)")
                raise
            except Exception as e:
                logger.error("OAuth low-level error: %s", str(e))
                raise

# -- Value objects -----------------------------------------------------


@dataclasses.dataclass(frozen=True, slots=True)
class GoogleProfile:
    """
    Parsed, validated Google profile from the userinfo endpoint.
    Immutable — constructed once from raw API response, never mutated.
    """
    google_id: str       # Google 'sub' — stable, unique per Google account
    email: str           # already lowercased + stripped
    name: str
    picture: str
    email_verified: bool

    @classmethod
    def from_raw(cls, raw: dict) -> "GoogleProfile":
        """
        Parse and validate the raw dict returned by
        https://www.googleapis.com/oauth2/v3/userinfo
        Raises ValueError for any missing or invalid fields.
        """
        google_id = raw.get("sub", "").strip()
        email = raw.get("email", "").lower().strip()

        if not google_id:
            raise ValueError("Google profile missing 'sub' (user ID)")
        if not email:
            raise ValueError("Google profile missing email address")
        if not raw.get("email_verified", False):
            raise ValueError("Google email is not verified")

        return cls(
            google_id=google_id,
            email=email,
            name=(raw.get("name") or email.split("@")[0]).strip(),
            picture=raw.get("picture", ""),
            email_verified=True,
        )


@dataclasses.dataclass(frozen=True, slots=True)
class OAuthResult:
    """
    Outcome of process_google_login().
    The router uses this to set cookies and decide where to redirect.
    """
    user: User
    is_new: bool        # True  → user was just created (needs profile completion)
    was_linked: bool    # True  → existing local account was linked to Google


# ── Service ───────────────────────────────────────────────────────────


class OAuthAccountLinkingError(Exception):
    """
    Raised when the OAuth flow cannot proceed cleanly.
    The router catches this and redirects with an appropriate error code.
    """
    def __init__(self, message: str, error_code: str):
        super().__init__(message)
        self.error_code = error_code


async def process_google_login(
    db: AsyncSession,
    profile: GoogleProfile,
    role: str = "customer",
) -> OAuthResult:
    """
    Core account-linking logic.

    Decision tree
    ─────────────
    1. Query DB by google_id
       → Found: account already fully linked → log in directly

    2. Query DB by email
       a. Found + account is active:
          → Link google_id to the existing account (even if provider=email)
          → Mark is_otp_verified=True (Google verified the email)
          → Log in
       b. Found + account is inactive:
          → Raise OAuthAccountLinkingError (deactivated)

    3. Neither found:
       → Create new User with provider='google', no password
       → Return is_new=True so the router sends them to complete their profile

    All mutations are flushed but NOT committed here —
    commit responsibility stays with the caller (router).
    This keeps the service layer unit-testable without a real DB commit.
    """
    now = ist_now()

    # ── Step 1: look up by google_id ──────────────────────────────────
    result = await db.execute(
        select(User).where(User.google_id == profile.google_id)
    )
    user: Optional[User] = result.scalar_one_or_none()

    if user is not None:
        _assert_active(user, profile)
        _refresh_login_metadata(user, profile, now)
        await db.flush()
        logger.info(
            "OAuth login [google_id match]: user=%s email=%s",
            user.id, user.email,
        )
        return OAuthResult(user=user, is_new=False, was_linked=False)

    # ── Step 2: look up by email ──────────────────────────────────────
    result = await db.execute(
        select(User).where(User.email == profile.email)
    )
    user = result.scalar_one_or_none()

    if user is not None:
        _assert_active(user, profile)
        was_linked = _link_google_to_existing(user, profile, now)
        await db.flush()
        logger.info(
            "OAuth login [email match, link=%s]: user=%s provider=%s",
            was_linked, user.id, user.auth_provider,
        )
        return OAuthResult(user=user, is_new=False, was_linked=was_linked)

    # ── Step 3: brand-new Google user ─────────────────────────────────
    user = _create_google_user(profile, now, role)
    db.add(user)
    await db.flush()          # populate user.id
    logger.info(
        "OAuth login [new user created]: email=%s google_id=%s role=%s",
        profile.email, profile.google_id, role,
    )
    return OAuthResult(user=user, is_new=True, was_linked=False)


# ── Private helpers ───────────────────────────────────────────────────


def _assert_active(user: User, profile: GoogleProfile) -> None:
    """Raise if the account is deactivated so the router can redirect cleanly."""
    if not user.is_active:
        raise OAuthAccountLinkingError(
            f"Account {profile.email} is deactivated",
            error_code="account_deactivated",
        )


def _refresh_login_metadata(
    user: User,
    profile: GoogleProfile,
    now,
) -> None:
    """
    Update fields that should always be refreshed on every Google login,
    regardless of whether this is a new link or a repeat login.
    """
    user.last_login = now
    user.is_otp_verified = True      # Google verified the email
    user.is_otp_verified = True      # Google verified the email


def _link_google_to_existing(
    user: User,
    profile: GoogleProfile,
    now,
) -> bool:
    """
    Link a Google identity to an existing local account.
    Returns True if this is the first time linking (google_id was absent).
    Returns False if google_id was already stored (idempotent).
    """
    was_linked = False

    if not user.google_id:
        # First-time link: store google_id. 
        # If they had a password, they are now 'hybrid'.
        user.google_id = profile.google_id
        if user.hashed_password:
            user.auth_provider = "hybrid"
        was_linked = True
        logger.debug(
            "Linked google_id to existing account: user=%s provider=%s",
            user.id, user.auth_provider,
        )

    _refresh_login_metadata(user, profile, now)
    return was_linked


def _create_google_user(profile: GoogleProfile, now, role: str) -> User:
    """
    Build a new User record for a first-time Google sign-in.
    password is NULL — these users authenticate exclusively via Google.
    phone is blank — they will complete it on the next page.
    """
    return User(
        name=profile.name,
        email=profile.email,
        phone="",                   # filled in on the complete-profile page
        hashed_password=None,       # no password for OAuth-only accounts
        role=ROLE_ELECTRICIAN if role == "electrician" else ROLE_CUSTOMER,
        google_id=profile.google_id,
        auth_provider="google",
        is_active=True,
        is_verified=False,          # admin still needs to approve
        is_otp_verified=True,       # Google verified the email address
        last_login=now,
        created_at=now,
        updated_at=now,
    )
