"""app/core/exceptions.py — Global exception handlers for user-friendly error responses."""

import logging
from fastapi import Request, HTTPException, FastAPI
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError

logger = logging.getLogger("elecsure")

FIELD_LABELS = {
    "name": "Full Name",
    "email": "Email Address",
    "phone": "Mobile Number",
    "alternate_phone": "Alternate Phone",
    "password": "Password",
    "confirm_password": "Confirm Password",
    "new_password": "New Password",
    "old_password": "Current Password",
    "pincode": "Pincode",
    "address": "Address",
    "problem_description": "Problem Description",
    "skills": "Skills",
    "primary_skill": "Primary Skill",
    "experience_years": "Experience Years",
    "toolkit": "Toolkit",
    "rating": "Rating",
    "preferred_date": "Preferred Date",
    "service_id": "Service",
}

STRIP_PREFIXES = [
    "Value error, ",
    "value error, ",
    "String should match pattern",
    "String should have at least",
    "Input should be",
    "ensure this value",
    "field required",
]

def setup_exception_handlers(app: FastAPI):
    
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(request: Request, exc: RequestValidationError):
        """Convert Pydantic/FastAPI validation errors into clean, user-friendly messages."""
        errors = []
        seen = set()
        for error in exc.errors():
            raw_msg: str = error.get("msg", "Invalid input")
            clean_msg = raw_msg
            for prefix in STRIP_PREFIXES:
                if clean_msg.lower().startswith(prefix.lower()):
                    clean_msg = clean_msg[len(prefix):]
                    break
            clean_msg = clean_msg[0].upper() + clean_msg[1:] if clean_msg else raw_msg
            locs = [str(loc) for loc in error.get("loc", []) if loc not in ("body", "query")]
            field_key = locs[-1] if locs else ""
            field_label = FIELD_LABELS.get(field_key, field_key.replace("_", " ").title())
            error_type = error.get("type", "")

            if error_type == "missing" or error_type == "string_too_short":
                clean_msg = f"{field_label} is required"
            elif error_type == "value_error" and "email" in field_key.lower():
                clean_msg = "Please enter a valid email address"
            elif error_type == "int_parsing":
                clean_msg = f"{field_label} must be a number"
            elif error_type == "datetime_parsing":
                clean_msg = f"{field_label} must be a valid date/time"

            if clean_msg not in seen:
                seen.add(clean_msg)
                errors.append(clean_msg)

        final_message = " | ".join(errors) if errors else "Please check your input and try again"
        return JSONResponse(status_code=422, content={"detail": final_message})

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        """Always return JSON for API routes, and JSON (for dash) for page routes."""
        if request.url.path.startswith("/api"):
            return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(404)
    async def not_found_handler(request: Request, exc):
        if request.url.path.startswith("/api"):
            return JSONResponse(status_code=404, content={"detail": "Endpoint not found"})
        return JSONResponse(status_code=404, content={"detail": "Page not found"})

    @app.exception_handler(500)
    async def internal_error_handler(request: Request, exc: Exception):
        """Catch-all: always return clean JSON, never raw Python error HTML."""
        logger.error("Unhandled error on %s: %s", request.url.path, exc, exc_info=True)
        return JSONResponse(
            status_code=500,
            content={"detail": "Something went wrong on our end. Please try again or contact support."},
        )
