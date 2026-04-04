"""
app/services/location_service.py — In-memory location tracking for real-time electrician updates.

Stores electrician locations in memory for fast access during active tracking sessions.
Structure: electrician_id -> {lat: float, lng: float, updated_at: datetime}
"""

from datetime import datetime
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class LocationService:
    def __init__(self):
        self._locations: Dict[str, Dict] = {}

    def update_location(self, electrician_id: str, lat: float, lng: float) -> None:
        """Update or set the location for an electrician."""
        self._locations[electrician_id] = {
            "lat": lat,
            "lng": lng,
            "updated_at": datetime.utcnow()
        }
        logger.info(f"Updated location for electrician {electrician_id}: {lat}, {lng}")

    def get_location(self, electrician_id: str) -> Optional[Dict]:
        """Get the current location for an electrician."""
        return self._locations.get(electrician_id)

    def remove_location(self, electrician_id: str) -> None:
        """Remove location data for an electrician (e.g., when offline)."""
        if electrician_id in self._locations:
            del self._locations[electrician_id]
            logger.info(f"Removed location for electrician {electrician_id}")

    def get_all_locations(self) -> Dict[str, Dict]:
        """Get all stored locations (for debugging/admin purposes)."""
        return self._locations.copy()

# Global instance
location_service = LocationService()