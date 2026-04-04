import asyncio
import json
import requests
from sqlalchemy.orm import Session
from app.core.database import SessionLocal
from app.models.user import User

def test_routes():
    db = SessionLocal()
    user = db.query(User).filter(User.role == 'ELECTRICIAN').first()
    if not user:
        print("No electrician found.")
        return
    token = "test" # Wait, creating an access token requires app logic. Let's just create one.
    
    from app.core.security import create_access_token
    token = create_access_token({"sub": str(user.id), "role": user.role, "name": user.name})
    
    headers = {"Authorization": f"Bearer {token}"}
    
    res1 = requests.get('http://127.0.0.1:8000/api/v1/analytics/electrician', headers=headers)
    print("Analytics:", res1.status_code, res1.text[:200])

    res2 = requests.get('http://127.0.0.1:8000/api/v1/slots/me', headers=headers)
    print("Slots:", res2.status_code, res2.text[:200])

if __name__ == "__main__":
    test_routes()
