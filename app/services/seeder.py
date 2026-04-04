"""app/services/seeder.py — Seed admin user + full service catalogue on startup."""

import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from app.core.config import settings
from app.core.security import hash_password, ist_now
from app.core.constants import SERVICES_TAXONOMY
from app.models import User, UserRole, Service

logger = logging.getLogger(__name__)

# Fixed admin UUID for consistency across recreations
ADMIN_UUID = "00000000-0000-4000-a000-000000000000"

PRICE_MAP = {
    "Electrical Appliance Repair": 599.0,
    "Wiring & Circuit Repairs": 499.0,
    "Lighting Services": 299.0,
    "Installations": 399.0,
    "Safety Checks & Inspections": 349.0,
    "Power Backup Services": 549.0,
    "Electrical Service Packages": 1499.0,
}
DURATION_MAP = {
    "Electrical Appliance Repair": 90,
    "Wiring & Circuit Repairs": 60,
    "Lighting Services": 45,
    "Installations": 60,
    "Safety Checks & Inspections": 60,
    "Power Backup Services": 90,
    "Electrical Service Packages": 180,
}


async def seed_admin(db: AsyncSession) -> None:
    r = await db.execute(select(User).where(User.email == settings.ADMIN_EMAIL.lower()))
    if r.scalar_one_or_none():
        return
    admin = User(
        id=ADMIN_UUID,  # Fixed hardcoded UUID for admin user
        name=settings.ADMIN_NAME,
        email=settings.ADMIN_EMAIL.lower(),
        phone="0000000000",
        hashed_password=hash_password(settings.ADMIN_PASSWORD),
        role=UserRole.ADMIN,
        is_active=True,
        is_verified=True,
        is_otp_verified=True,
        created_at=ist_now(),
        updated_at=ist_now(),
    )
    db.add(admin)
    await db.flush()
    logger.info("Admin created: %s (UUID=%s)", settings.ADMIN_EMAIL, ADMIN_UUID)


async def seed_services(db: AsyncSession) -> None:
    # Get all existing services to avoid duplicating or skipping
    r = await db.execute(select(Service.name))
    existing_services = {name for (name,) in r.fetchall()}

    now = ist_now()
    count = 0
    for category, cat_data in SERVICES_TAXONOMY.items():
        price = PRICE_MAP.get(category, 499.0)
        duration = DURATION_MAP.get(category, 60)
        subcategories = cat_data.get("subcategories", {})
        for subcat, services in subcategories.items():
            for name in services:
                if name not in existing_services:
                    db.add(Service(
                        category=category,
                        group=subcat,
                        name=name,
                        base_price=price,
                        duration_minutes=duration,
                        is_active=True,
                        created_at=now,
                    ))
                    existing_services.add(name)
                    count += 1

    if count > 0:
        await db.flush()
        logger.info("Services seeded: %d new services added", count)


async def run_all_seeds(db: AsyncSession) -> None:
    await ensure_otp_columns(db)
    await ensure_google_columns(db)
    await ensure_settings_columns(db)
    await ensure_timeslot_columns(db)
    await seed_admin(db)
    await seed_services(db)
    await db.commit()
    logger.info("Seeding complete")


async def ensure_payment_type_column(db) -> None:
    """Add payment_type column if it doesn't exist (runs once, skips after)."""
    try:
        # Check if column exists first — avoids slow ALTER TABLE on every restart
        result = await db.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'bookings' "
            "AND column_name = 'payment_type'"
        ))
        exists = result.scalar() or 0
        if not exists:
            await db.execute(text(
                "ALTER TABLE bookings ADD COLUMN payment_type VARCHAR(10) DEFAULT 'online'"
            ))
            await db.commit()
    except Exception:
        pass


async def ensure_acknowledged_at_column(db) -> None:
    """Add acknowledged_at column if it doesn't exist."""
    try:
        result = await db.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'bookings' "
            "AND column_name = 'acknowledged_at'"
        ))
        exists = result.scalar() or 0
        if not exists:
            # Add acknowledged_at column
            await db.execute(text(
                "ALTER TABLE bookings ADD COLUMN acknowledged_at DATETIME NULL"
            ))
            await db.commit()
            logger.info("Column 'acknowledged_at' added to 'bookings' table")
    except Exception as e:
        logger.error("Failed to add 'acknowledged_at' column: %s", e)


async def ensure_otp_columns(db: AsyncSession) -> None:
    """Add new security and notification columns to users table if they don't exist."""
    try:
        # List of columns to check/add
        cols = [
            ("is_otp_verified", "BOOLEAN DEFAULT FALSE"),
            ("otp_code", "VARCHAR(10)"),
            ("otp_expires_at", "DATETIME"),
            ("otp_attempts", "INT DEFAULT 0"),
            ("otp_blocked_until", "DATETIME"),
            ("last_promo_index", "INT DEFAULT -1"),
            ("otp_mobile_code", "VARCHAR(10)"),
        ]
        
        for col_name, col_def in cols:
            result = await db.execute(text(
                f"SELECT COUNT(*) FROM information_schema.columns "
                f"WHERE table_schema = DATABASE() "
                f"AND table_name = 'users' "
                f"AND column_name = '{col_name}'"
            ))
            if not (result.scalar() or 0):
                await db.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                logger.info("Added security column '%s' to 'users' table", col_name)
        
        await db.commit()
    except Exception as e:
        logger.error("ensure_otp_columns failed: %s", e)


async def ensure_google_columns(db: AsyncSession) -> None:
    """Add Google OAuth and security columns to users table if they don't exist."""
    try:
        cols = [
            ("google_id",      "VARCHAR(128) NULL"),
            ("auth_provider",  "VARCHAR(20) NOT NULL DEFAULT 'local'"),
            ("refresh_token",  "TEXT NULL"),
            ("new_email_temp", "VARCHAR(255) NULL"),
            ("failed_login_attempts", "INT DEFAULT 0"),
            ("login_blocked_until", "DATETIME NULL"),
            ("profile_photo", "VARCHAR(512) NULL"),
        ]

        for col_name, col_def in cols:
            result = await db.execute(text(
                f"SELECT COUNT(*) FROM information_schema.columns "
                f"WHERE table_schema = DATABASE() "
                f"AND table_name = 'users' "
                f"AND column_name = '{col_name}'"
            ))
            if not (result.scalar() or 0):
                await db.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                logger.info("Added security column '%s' to 'users' table", col_name)
        
        await db.commit()
    except Exception as e:
        logger.error("ensure_google_columns failed: %s", e)


async def ensure_settings_columns(db: AsyncSession) -> None:
    """Generic place for any other schema tweaks."""
    await ensure_earning_columns(db)


async def ensure_earning_columns(db: AsyncSession) -> None:
    """Add earnings tracking columns to users and bookings tables."""
    try:
        # 1. Update users table
        user_cols = [
            ("daily_earning", "FLOAT DEFAULT 0.0"),
            ("weekly_earning", "FLOAT DEFAULT 0.0"),
            ("total_lifetime_earning", "FLOAT DEFAULT 0.0"),
            ("commission_due", "FLOAT DEFAULT 0.0"),
        ]
        for col_name, col_def in user_cols:
            result = await db.execute(text(
                f"SELECT COUNT(*) FROM information_schema.columns "
                f"WHERE table_schema = DATABASE() "
                f"AND table_name = 'users' "
                f"AND column_name = '{col_name}'"
            ))
            if not (result.scalar() or 0):
                await db.execute(text(f"ALTER TABLE users ADD COLUMN {col_name} {col_def}"))
                logger.info("Added earnings column '%s' to 'users' table", col_name)

        # 2. Update bookings table
        result = await db.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'bookings' "
            "AND column_name = 'earning_calculated'"
        ))
        if not (result.scalar() or 0):
            await db.execute(text("ALTER TABLE bookings ADD COLUMN earning_calculated BOOLEAN DEFAULT FALSE"))
            logger.info("Added 'earning_calculated' column to 'bookings' table")

        await db.commit()
    except Exception as e:
        logger.error("ensure_earning_columns failed: %s", e)

async def ensure_timeslot_columns(db: AsyncSession) -> None:
    """Add violated_mid_slot column to time_slots table if it doesn't exist."""
    try:
        result = await db.execute(text(
            "SELECT COUNT(*) FROM information_schema.columns "
            "WHERE table_schema = DATABASE() "
            "AND table_name = 'time_slots' "
            "AND column_name = 'violated_mid_slot'"
        ))
        if not (result.scalar() or 0):
            await db.execute(text("ALTER TABLE time_slots ADD COLUMN violated_mid_slot BOOLEAN DEFAULT FALSE"))
            await db.commit()
            logger.info("Added 'violated_mid_slot' column to 'time_slots' table")
    except Exception as e:
        logger.error("ensure_timeslot_columns failed: %s", e)
