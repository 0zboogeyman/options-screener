from __future__ import annotations

from pydantic import BaseModel, Field
from typing import List, Optional


class SpreadLeg(BaseModel):
    K1: float
    K2: float
    premium: float
    max_profit: float
    max_loss: float
    odds: float
    pop: Optional[float] = None
    quality: str | None = None


class Bucket(BaseModel):
    leg_type: str  # CALL or PUT
    side: str  # DEBIT or CREDIT
    top: List[SpreadLeg]
    bottom: List[SpreadLeg]


class ScanResponse(BaseModel):
    asof_date: str
    base: str
    tenor: str
    buckets: List[Bucket]


class DatesResponse(BaseModel):
    dates: List[str]


class ExpiriesResponse(BaseModel):
    date: str
    base: str
    expiries: List[int]

