"""app/schemas/earnings.py - Earnings schemas."""

from pydantic import BaseModel
from datetime import datetime
from typing import List, Optional

class EarningsSummary(BaseModel):
    daily_earning: float
    weekly_earning: float
    total_lifetime_earning: float
    commission_due: float
    is_restricted: bool = False
    restriction_message: Optional[str] = None

class WeeklyReportOut(BaseModel):
    id: str
    total_earned: float
    commission_due: float
    week_start: datetime
    week_end: datetime
    created_at: datetime

    model_config = {"from_attributes": True}
