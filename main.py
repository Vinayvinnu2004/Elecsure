"""
main.py — ElecSure FastAPI application entry point.

Startup sequence:
  1. Create all database tables
  2. Seed admin user + service catalogue
  3. Start APScheduler background jobs
  4. Mount static files
  5. Register all API routers
  6. Register HTML page routes & Exceptions
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.core import config
from app.core.config import settings
from app.core.database import engine, Base
from app.core.exceptions import setup_exception_handlers
from app.routers import (
    auth, oauth, users, bookings, services, payments, 
    admin, chatbot, slots, location, earnings, pages
)
from app.routers.analytics import router as analytics_router
from app.routers.websocket import router as ws_router

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("elecsure")


# -- Lifespan (startup / shutdown) ------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    logger.info("ElecSure starting up...")

    # 1. Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ready")

    # 2. Warm the connection pool
    from app.core.database import warm_pool
    import time as _time
    _t0 = _time.time()
    await warm_pool()
    _elapsed = round((_time.time() - _t0) * 1000)
    logger.info("Connection pool warmed in %dms", _elapsed)

    # 3. Seed data
    from app.core.database import AsyncSessionLocal
    from app.services.seeder import run_all_seeds, ensure_payment_type_column, ensure_acknowledged_at_column
    async with AsyncSessionLocal() as db:
        await ensure_payment_type_column(db)
        await ensure_acknowledged_at_column(db)
        await run_all_seeds(db)

    # 4. Start scheduler
    from app.services.scheduler import start_scheduler
    start_scheduler()

    yield

    # --- SHUTDOWN ---
    logger.info("ElecSure shutting down...")
    from app.services.scheduler import stop_scheduler
    stop_scheduler()
    await engine.dispose()


# -- App ---------------------------------------------------------------

limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
app = FastAPI(
    title="ElecSure API",
    description="Production-ready home electrical services platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


# -- Middleware --------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Type"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS or ["*"]
)

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add production security headers (CSP, HSTS, etc)."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = "default-src 'self' https:; script-src 'self' 'unsafe-inline' https:; style-src 'self' 'unsafe-inline' https:; img-src 'self' data: https:; font-src 'self' https: font:; connect-src 'self' https:;"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

@app.middleware("http")
async def request_size_limit(request: Request, call_next):
    """Guard against large payloads."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:  # 10MB
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=413, content={"detail": "Payload too large"})
    return await call_next(request)

@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    """Log slow requests for diagnostics."""
    import time as _t
    start = _t.time()
    response = await call_next(request)
    elapsed = round((_t.time() - start) * 1000)
    if elapsed > 500 and request.url.path.startswith("/api"):
        logger.warning("SLOW API %s %s  %dms", request.method, request.url.path, elapsed)
    return response


# -- Static Files ------------------------------------------------------

app.mount("/static", StaticFiles(directory="static"), name="static")


# -- API & Page Routers ------------------------------------------------

app.include_router(pages.router)
app.include_router(auth.router)
app.include_router(oauth.router)
app.include_router(users.router)
app.include_router(bookings.router)
app.include_router(services.router)
app.include_router(payments.router)
app.include_router(admin.router)
app.include_router(chatbot.router)
app.include_router(slots.router)
app.include_router(location.router)
app.include_router(analytics_router)
app.include_router(ws_router)
app.include_router(earnings.router)


# -- Exceptions --------------------------------------------------------

setup_exception_handlers(app)


# -- Health check ------------------------------------------------------

@app.get("/api/health", tags=["Health"])
async def health_check():
    from app.core.security import ist_now
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": "1.0.0",
        "timestamp_ist": ist_now().isoformat(),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.DEBUG,
        log_level="info",
    )
