"""app/routers/pages.py — HTML page routes for the ElecSure platform."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from app.core.config import settings

router = APIRouter(tags=["Pages"])
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
async def landing(request: Request):
    return templates.TemplateResponse("landing.html", {"request": request})

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("auth/login.html", {"request": request})

@router.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("auth/register.html", {"request": request})

@router.get("/social-register", response_class=HTMLResponse)
async def social_register_page(request: Request):
    return templates.TemplateResponse("auth/social_complete.html", {"request": request})

@router.get("/customer", response_class=HTMLResponse)
async def customer_dashboard(request: Request):
    return templates.TemplateResponse(
        "customer/dashboard.html",
        {"request": request, "stripe_pk": settings.STRIPE_PUBLISHABLE_KEY},
    )

@router.get("/customer/track", response_class=HTMLResponse)
async def customer_track_page(request: Request):
    return templates.TemplateResponse(
        "customer/track.html",
        {"request": request, "stripe_pk": settings.STRIPE_PUBLISHABLE_KEY},
    )

@router.get("/customer/track-electrician/{booking_id}", response_class=HTMLResponse)
async def track_electrician_page(request: Request, booking_id: str):
    return templates.TemplateResponse(
        "customer/track_electrician.html",
        {"request": request, "booking_id": booking_id, "stripe_pk": settings.STRIPE_PUBLISHABLE_KEY},
    )

@router.get("/customer/bookings/{booking_id}", response_class=HTMLResponse)
async def customer_booking_detail(request: Request, booking_id: int):
    return templates.TemplateResponse(
        "customer/dashboard.html",
        {"request": request, "stripe_pk": settings.STRIPE_PUBLISHABLE_KEY},
    )

@router.get("/electrician", response_class=HTMLResponse)
async def electrician_dashboard(request: Request):
    return templates.TemplateResponse("electrician/dashboard.html", {"request": request})

@router.get("/electrician/track", response_class=HTMLResponse)
async def electrician_track_page(request: Request):
    return templates.TemplateResponse("electrician/track.html", {"request": request})

@router.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    return templates.TemplateResponse("shared/profile_page.html", {"request": request})

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    return templates.TemplateResponse("admin/dashboard.html", {"request": request})

@router.get("/api/chatbot/config")
async def chatbot_config():
    """Return AI API keys to the chatbot frontend."""
    return {
        "groq_key": settings.GROQ_API_KEY or ""
    }


@router.get("/hybridaction/zybTrackerStatisticsAction")
async def dummy_tracker_silencer(request: Request):
    """Handles tracking pings from certain development tools (like HBuilderX)."""
    from fastapi.responses import PlainTextResponse
    callback = request.query_params.get("__callback__")
    if callback:
        return PlainTextResponse(f"{callback}({{}})")
    return {"status": "ok"}
