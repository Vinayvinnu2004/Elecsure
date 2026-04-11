"""app/core/config.py — Application settings with full validation."""

from functools import lru_cache
from pydantic import field_validator, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False
    )

    # App
    APP_NAME: str = "ElecSure"
    DEBUG: bool = False
    BASE_URL: str = "http://localhost:8000"
    TIMEZONE: str = "Asia/Kolkata"  # IST
    ALLOWED_HOSTS: list[str] = ["*"]
    ALLOWED_ORIGINS: list[str] = ["http://localhost:8000", "http://127.0.0.1:8000"]

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Database — use 127.0.0.1 not localhost (avoids Windows IPv6 DNS lookup delay)
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 3306
    DB_USER: str = "root"
    DB_PASSWORD: str = ""
    DB_NAME: str = "elecsure"
    DATABASE_URL: str = ""

    # Admin
    ADMIN_EMAIL: str = "admin@elecsure.com"
    ADMIN_PASSWORD: str = "Admin@123456"
    ADMIN_NAME: str = "ElecSure Admin"

    # Stripe
    STRIPE_SECRET_KEY: str = ""
    STRIPE_PUBLISHABLE_KEY: str = ""
    STRIPE_WEBHOOK_SECRET: str = ""

    # SMTP
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "noreply@elecsure.com"
    EMAIL_FROM_NAME: str = "ElecSure"

    # Twilio
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_PHONE_NUMBER: str = ""
    SUPPORT_PHONE: str = "+91-1800-XXX-XXXX"


    # OTP Settings
    OTP_EXPIRY_MINUTES: int = 10
    OTP_MAX_ATTEMPTS: int = 5
    OTP_EMAIL_LINK_ENABLED: bool = True

    # AI Keys
    GROQ_API_KEY: str | None = None

    # Google Maps
    GOOGLE_MAPS_API_KEY: str = ""

    # Google OAuth 2.0
    GOOGLE_CLIENT_ID: str = ""
    GOOGLE_CLIENT_SECRET: str = ""
    GOOGLE_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/google/callback"

    # Business rules
    COMMISSION_RATE: float = 0.20          # 20% platform commission
    ASSIGNMENT_TIMEOUT_MINUTES: int = 10   # reassign if not accepted in 10 min
    FALLBACK_CHECK_INTERVAL_SECONDS: int = 60

    @field_validator("SECRET_KEY")
    @classmethod
    def validate_secret_key(cls, v: str) -> str:
        if not v or len(v) < 32:
            raise ValueError("SECRET_KEY must be at least 32 characters.")
        return v

    @computed_field
   @computed_field
@property
def async_database_url(self) -> str:
    """Build database URL with proper handling of environment variables."""
    # Detailed logging for debugging
    print(f"DEBUG: Raw DATABASE_URL = '{self.DATABASE_URL}'")
    print(f"DEBUG: Raw DATABASE_URL repr = {repr(self.DATABASE_URL)}")
    
    # Strip whitespace from DATABASE_URL
    db_url = self.DATABASE_URL.strip() if self.DATABASE_URL else ""
    
    print(f"DEBUG: Stripped DATABASE_URL = '{db_url}'")
    print(f"DEBUG: Starts with mysql+aiomysql:// ? {db_url.startswith('mysql+aiomysql://')}")
    print(f"DEBUG: DB_HOST = {self.DB_HOST}")
    print(f"DEBUG: DB_PORT = {self.DB_PORT}")
    
    # Prefer DATABASE_URL if it's a proper MySQL connection string
    if db_url and db_url.startswith("mysql+aiomysql://"):
        print(f"✅ USING DATABASE_URL")
        return db_url
    
    # Otherwise, build from individual components
    print(f"⚠️ FALLING BACK TO DB_HOST/PORT")
    url = (
        f"mysql+aiomysql://{self.DB_USER}:{self.DB_PASSWORD}"
        f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}?charset=utf8mb4"
    )
    return url.replace("@localhost:", "@127.0.0.1:")
@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
