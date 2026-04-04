import os
import sys
import asyncio
from datetime import datetime

sys.path.append(os.getcwd())

from app.core.database import AsyncSessionLocal
from app.models.booking import Booking, TimeSlot, SLOT_BOOKED, SLOT_AVAILABLE
from sqlalchemy import select

async def cleanup():
    db = AsyncSessionLocal()
    # Find all BOOKED slots
    r = await db.execute(select(TimeSlot).where(TimeSlot.status == SLOT_BOOKED))
    slots = r.scalars().all()
    
    fixed_count = 0
    for s in slots:
        # Check if any active booking exists for this slot
        # Active means NOT CANCELLED
        r_b = await db.execute(select(Booking).where(Booking.time_slot_id == s.id, Booking.status != 'CANCELLED'))
        b = r_b.scalar_one_or_none()
        if not b:
            print(f"Repairing orphared slot {s.id} (Elec ID: {s.electrician_id}) -> AVAILABLE")
            s.status = SLOT_AVAILABLE
            fixed_count += 1
            
    if fixed_count > 0:
        await db.commit()
    print(f"Cleanup complete. Fixed {fixed_count} slots.")
    await db.close()

if __name__ == "__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(cleanup())
    loop.close()
