"""app/schemas/auth.py — Auth request/response schemas with friendly error messages."""

from typing import Optional
from pydantic import BaseModel, EmailStr, field_validator
from app.core.security import validate_password_strength


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: str  # Changed from int to str for UUID
    name: str
    refresh_token: Optional[str] = None


class RegisterCustomer(BaseModel):
    name: str
    email: EmailStr
    phone: str
    password: str
    confirm_password: str
    flat_no: Optional[str] = None
    landmark: Optional[str] = None
    village: Optional[str] = None
    district: Optional[str] = None
    state: Optional[str] = None
    pincode: Optional[str] = None
    full_address: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Please enter your full name")
        if len(v.strip()) < 2:
            raise ValueError("Name must be at least 2 characters")
        return v.strip()

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = v.replace("+", "").replace("-", "").replace(" ", "")
        if not digits.isdigit() or len(digits) < 10:
            raise ValueError("Please enter a valid 10-digit mobile number")
        return v

    @field_validator("password")
    @classmethod
    def validate_pwd(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter (A-Z)")
        if not any(c.islower() for c in v):
            raise ValueError("Password must contain at least one lowercase letter (a-z)")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one number (0-9)")
        if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in v):
            raise ValueError("Password must contain at least one special character (!@#$% etc.)")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "password" in info.data and v != info.data["password"]:
            raise ValueError("Passwords do not match — please re-enter")
        return v

    @field_validator("pincode")
    @classmethod
    def validate_pincode(cls, v: Optional[str]) -> Optional[str]:
        if v and (not v.strip().isdigit() or len(v.strip()) != 6):
            raise ValueError("Pincode must be exactly 6 digits")
        return v


class RegisterElectrician(RegisterCustomer):
    skills: str
    primary_skill: str
    experience_years: int  # non-ID integer
    toolkit: str = "none"
    alternate_phone: Optional[str] = None

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Please enter at least one skill")
        return v.strip()

    @field_validator("primary_skill")
    @classmethod
    def validate_primary_skill(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Please enter your primary skill")
        return v.strip()

    @field_validator("experience_years")
    @classmethod
    def validate_experience(cls, v: int) -> int:
        if v < 0 or v > 60:
            raise ValueError("Experience years must be between 0 and 60")
        return v

    @field_validator("toolkit")
    @classmethod
    def validate_toolkit(cls, v: str) -> str:
        allowed = {"basic", "advanced", "both", "none"}
        if v.lower() not in allowed:
            raise ValueError("Toolkit must be one of: basic, advanced, both, none")
        return v.lower()


class SocialRegisterCompletion(BaseModel):
    name: str
    email: EmailStr
    google_id: str
    phone: str
    flat_no: str
    landmark: str
    village: str
    pincode: str
    district: str = "Karimnagar"
    state: str = "Telangana"
    full_address: Optional[str] = None
    role: str = "customer"

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        digits = v.replace("+", "").replace("-", "").replace(" ", "")
        if not digits.isdigit() or len(digits) < 10:
            raise ValueError("Please enter a valid 10-digit mobile number")
        return v


class SocialRegisterElectricianCompletion(SocialRegisterCompletion):
    skills: str
    primary_skill: str
    experience_years: int
    toolkit: str = "none"
    alternate_phone: Optional[str] = None

    @field_validator("skills")
    @classmethod
    def validate_skills(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Please enter at least one skill")
        return v.strip()


class PasswordChangeRequest(BaseModel):
    old_password: Optional[str] = None
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def validate_pwd(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError("New password must be at least 8 characters long")
        if not any(c.isupper() for c in v):
            raise ValueError("New password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("New password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("New password must contain at least one number")
        if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in v):
            raise ValueError("New password must contain at least one special character")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match — please re-enter")
        return v


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match — please re-enter")
        return v


class OTPVerifyRequest(BaseModel):
    email: EmailStr
    code: str  # Email Code
    mobile_code: str | None = None  # Mobile Code


class ResetPasswordOTPRequest(BaseModel):
    email: EmailStr
    code: str
    new_password: str
    confirm_password: str

    @field_validator("new_password")
    @classmethod
    def validate_pwd(cls, v: str) -> str:
        if not v or len(v) < 8:
            raise ValueError("New password must be at least 8 characters long")
        if not any(c.isupper() for c in v):
            raise ValueError("New password must contain at least one uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("New password must contain at least one lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("New password must contain at least one number")
        if not any(c in "!@#$%^&*()_+-=[]{}|;':\",./<>?" for c in v):
            raise ValueError("New password must contain at least one special character")
        return v

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, v: str, info) -> str:
        if "new_password" in info.data and v != info.data["new_password"]:
            raise ValueError("Passwords do not match — please re-enter")
        return v
