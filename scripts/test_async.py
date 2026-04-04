import os
import sys
import asyncio
from datetime import datetime, timedelta

async def check():
    print("Asyncio working.")

if __name__ == "__main__":
    asyncio.run(check())
