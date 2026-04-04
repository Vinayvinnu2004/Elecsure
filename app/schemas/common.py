"""app/schemas/common.py"""

from typing import Generic, List, TypeVar, Optional
from pydantic import BaseModel

T = TypeVar("T")


class MessageOut(BaseModel):
    message: str
    success: bool = True


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    per_page: int
    pages: int
