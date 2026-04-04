"""app/core/database.py — Async SQLAlchemy engine and session for MySQL."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase
from app.core.config import settings


engine = create_async_engine(
    settings.async_database_url,
    echo=False,                 # never echo — even in DEBUG, it's slow
    pool_pre_ping=False,        # OFF: causes DNS delay on Windows localhost
    pool_recycle=1800,          # recycle every 30 min (not 1 hour)
    pool_size=10,                # smaller pool — less overhead
    max_overflow=20,
    pool_timeout=10,            # fail fast if no connection in 10s
    connect_args={
        "connect_timeout": 5,   # MySQL connect timeout 5s max
    },
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncSession:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def warm_pool():
    """Pre-warm connection pool so first user request is instant."""
    try:
        async with AsyncSessionLocal() as session:
            from sqlalchemy import text
            await session.execute(text("SELECT 1"))
    except Exception:
        pass  # warmup failure is non-fatal
