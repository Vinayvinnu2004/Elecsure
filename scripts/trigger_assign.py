import os
import sys
import asyncio
from datetime import datetime

sys.path.append(os.getcwd())

from app.core.database import AsyncSessionLocal
from app.models.booking import Booking
from app.services.matching_service import assign_booking, _get_candidates

async def check():
    db = AsyncSessionLocal()
    bid = 'fbb4cbd9-39e8-48d7-b9ed-a824b250d4b0'
    r = await db.execute(select(Booking).options(joinedload(Booking.service)).where(Booking.id == bid))
    b = r.scalar_one_or_none()
    if not b: return
    
    with open("assignment_trigger.txt", "w", encoding="utf-8") as f:
        f.write(f"TRIGGERING ASSIGNMENT FOR {b.id}\n")
        f.write(f"SERVICE: {b.service.name}\n")
        f.write(f"PINCODE: {b.pincode}\n")
        
        ga, gb = await _get_candidates(db, b.service.name, b.pincode, b.time_slot_start, b.time_slot_end)
        f.write(f"ELIGIBLE CANDIDATES: GROUP A: {[e.name for e in ga]}, GROUP B: {[e.name for e in gb]}\n")
        
        if await assign_booking(db, b):
            f.write(f"SUCCESS: Assigned to {b.electrician_id}\n")
            await db.commit()
        else:
            f.write("FAILED: No candidate found by assign_booking\n")
            
    await db.close()

from sqlalchemy import select
from sqlalchemy.orm import joinedload
# I need to import the internal functions too? Or just use ga/gb check.

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check())
    loop.close()
