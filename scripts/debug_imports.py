import os
import sys

print("Python version:", sys.version)
print("CWD:", os.getcwd())

try:
    import asyncio
    print("Asyncio imported successfully")
except Exception as e:
    print("Asyncio import failed:", e)

try:
    from app.core.database import AsyncSessionLocal
    print("App core imported successfully")
except Exception as e:
    print("App core import failed:", e)
    import traceback
    traceback.print_exc()

if __name__ == "__main__":
    print("Finished.")
