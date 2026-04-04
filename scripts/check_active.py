import os
import sys
import asyncio
from datetime import datetime

sys.path.append(os.getcwd())

from app.core.database import AsyncSessionLocal
from app.models.booking import Booking
from sqlalchemy import select, or_

async def check():
    db = AsyncSessionLocal()
    eid = '42de5f6c-d53c-42fe-bb16-8060721fc873'
    # Check for ones that make him "busy"
    r = await db.execute(select(Booking).where(Booking.electrician_id == eid, Booking.status.in_(['ASSIGNED', 'ACCEPTED', 'STARTED'])))
    active = r.scalars().all()
    
    with open("active_elec_bookings.txt", "w", encoding="utf-8") as f:
        f.write(f"ACTIVE BOOKINGS FOR {eid}:\n")
        for b in active:
            f.write(f" - ID: {b.id} | STATUS: {b.status}\n")
            
    await db.close()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(check())
    loop.close()
