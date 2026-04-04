"""app/routers/websocket.py — WebSocket for real-time electrician location tracking."""

import json
import logging
from typing import Dict, Set
from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.core.security import ist_now

router = APIRouter(tags=["WebSocket"])
logger = logging.getLogger(__name__)

# booking_id → set of WebSocket connections (customer watchers)
_watchers: Dict[str, Set[WebSocket]] = {}
# electrician_id → latest location
_locations: Dict[str, dict] = {}


class ConnectionManager:
    def __init__(self):
        self.active: Dict[str, Set[WebSocket]] = {}  # booking_id → sockets

    async def connect(self, booking_id: str, ws: WebSocket):
        await ws.accept()
        self.active.setdefault(booking_id, set()).add(ws)
        logger.info("WS connected for booking %s", booking_id)

    def disconnect(self, booking_id: str, ws: WebSocket):
        if booking_id in self.active:
            self.active[booking_id].discard(ws)
            if not self.active[booking_id]:
                del self.active[booking_id]

    async def broadcast(self, booking_id: str, data: dict):
        closed = set()
        for ws in self.active.get(booking_id, set()):
            try:
                await ws.send_json(data)
            except Exception:
                closed.add(ws)
        for ws in closed:
            self.disconnect(booking_id, ws)


manager = ConnectionManager()


@router.websocket("/ws/track/{booking_id}")
async def track_booking(
    websocket: WebSocket,
    booking_id: str,
    token: str = Query(...),
):
    """
    Customer connects here to watch electrician location in real-time.
    Electrician sends location updates via POST /api/v1/users/me/location,
    which are broadcast here.
    """
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=4001)
        return

    await manager.connect(booking_id, websocket)
    try:
        # Send cached location immediately if available
        # (electrician_id is stored in booking — client knows it)
        while True:
            data = await websocket.receive_text()
            # Client can send ping to keep alive
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(booking_id, websocket)
        logger.info("WS disconnected for booking %s", booking_id)


async def broadcast_location(booking_id: str, electrician_id: str, lat: float, lng: float):
    """Called by the location update endpoint to push to all watchers."""
    await manager.broadcast(booking_id, {
        "type": "location_update",
        "electrician_id": electrician_id,
        "latitude": lat,
        "longitude": lng,
        "timestamp": ist_now().isoformat(),
    })
