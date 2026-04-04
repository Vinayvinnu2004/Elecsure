import asyncio
import logging
from sqlalchemy import text
from app.core.database import engine, Base
from app.models import *

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("migration")

async def force_reset():
    try:
        async with engine.begin() as conn:
            logger.info("Disabling foreign key checks globally for this session...")
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            
            # Retrieve list of all tables natively from MySQL
            logger.info("Fetching existing tables...")
            result = await conn.execute(text("SHOW TABLES;"))
            tables = [row[0] for row in result.fetchall()]
            
            logger.info(f"Targeting tables for deletion: {tables}")
            # Drop each individually
            for table in tables:
                await conn.execute(text(f"DROP TABLE IF EXISTS `{table}`;"))
                
            logger.info("Rebuilding schemas from metadata...")
            # Recreate cleanly
            await conn.run_sync(Base.metadata.create_all)
            
            logger.info("Re-enabling foreign key checks...")
            await conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            
        logger.info("Complete! All tables recreated seamlessly.")
    except Exception as e:
        logger.error(f"Error forcefully resetting database: {e}")
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(force_reset())
