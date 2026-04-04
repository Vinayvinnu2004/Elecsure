import asyncio
from sqlalchemy import text
from app.core.database import engine

async def check_cols():
    async with engine.connect() as conn:
        res = await conn.execute(text("DESCRIBE electrician_profiles"))
        for row in res:
            print(row)

if __name__ == "__main__":
    asyncio.run(check_cols())
