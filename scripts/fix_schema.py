import asyncio
import logging
from sqlalchemy import text
from app.core.database import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

async def migrate():
    async with engine.begin() as conn:
        logger.info("Checking electrician_profiles table...")
        try:
            # Check if column exists first (MySQL)
            res = await conn.execute(text("SHOW COLUMNS FROM electrician_profiles LIKE 'is_restricted'"))
            if not res.fetchone():
                logger.info("Adding 'is_restricted' column...")
                await conn.execute(text("ALTER TABLE electrician_profiles ADD COLUMN is_restricted BOOLEAN DEFAULT FALSE"))
                logger.info("Column added successfully!")
            else:
                logger.info("Column 'is_restricted' already exists.")
        except Exception as e:
            logger.error(f"Error migrating: {e}")
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate())
