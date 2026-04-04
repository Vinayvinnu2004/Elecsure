import asyncio
from sqlalchemy import text
from app.core.database import engine

async def migrate_restriction_column():
    async with engine.begin() as conn:
        print("Checking ElectricianProfile schema...")
        try:
            await conn.execute(text("ALTER TABLE electrician_profiles ADD COLUMN is_restricted BOOLEAN DEFAULT FALSE;"))
            print("Successfully added 'is_restricted' to 'electrician_profiles'!")
        except Exception as e:
            if "Duplicate column name" in str(e):
                print("Column 'is_restricted' already exists.")
            else:
                print(f"Error: {e}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(migrate_restriction_column())
