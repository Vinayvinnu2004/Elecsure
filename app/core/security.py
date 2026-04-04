"""app/core/security.py — Auth utilities: JWT, password hashing, secure tokens."""

import secrets
from datetime import datetime, timedelta
from typing import Optional
import pytz

import jwt as _jwt
from jwt.exceptions import InvalidTokenError as JWTError
from passlib.context import CryptContext

from app.core.config import settings

IST = pytz.timezone(settings.TIMEZONE)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def ist_now() -> datetime:
    """Current datetime in IST (naive, stored in DB as IST)."""
    return datetime.now(IST).replace(tzinfo=None)


def hash_password(password: str) -> str:
    try:
        return pwd_context.hash(password)
    except Exception:
        import bcrypt as _bcrypt
        return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return pwd_context.verify(plain, hashed)
    except Exception:
        # passlib 1.7.4 + bcrypt >= 4.1 raises AttributeError on __about__
        # Fall back to direct bcrypt comparison if passlib crashes
        try:
            import bcrypt as _bcrypt
            return _bcrypt.checkpw(plain.encode(), hashed.encode())
        except Exception:
            return False


def create_access_token(user_id: str, role: str, expires_delta: Optional[timedelta] = None) -> str:
    expire = ist_now() + (expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))
    payload = {"sub": str(user_id), "role": role, "exp": expire, "type": "access"}
    return _jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    expire = ist_now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": str(user_id), "exp": expire, "type": "refresh"}
    return _jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    try:
        return _jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except (JWTError, Exception):
        return None


def generate_secure_token(length: int = 32) -> str:
    """URL-safe secure random token for email action links."""
    return secrets.token_urlsafe(length)


def generate_otp(length: int = 6) -> str:
    """Generate a digital OTP code."""
    return "".join(secrets.choice("0123456789") for _ in range(length))


def validate_password_strength(password: str) -> bool:
    """Ensure password has uppercase, lowercase, digit, special char, min 8 chars."""
    if len(password) < 8:
        return False
    has_upper = any(c.isupper() for c in password)
    has_lower = any(c.islower() for c in password)
    has_digit = any(c.isdigit() for c in password)
    has_special = any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in password)
    return all([has_upper, has_lower, has_digit, has_special])


def sanitize_html(text: str) -> str:
    """Basic HTML sanitization to strip tags (XSS prevention)."""
    if not text:
        return text
    import re
    # Remove everything between < and >
    clean = re.compile('<.*?>')
    return re.sub(clean, '', text)
