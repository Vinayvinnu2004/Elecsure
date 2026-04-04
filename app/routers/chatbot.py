"""app/routers/chatbot.py — AI chat endpoint with task execution and role-aware responses."""

from typing import List, Optional
from pydantic import BaseModel
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_current_user
from app.core.database import get_db
from app.models import User
from app.services.chatbot_service import get_ai_response
from app.core.config import settings

router = APIRouter(prefix="/api/v1/chat", tags=["Chatbot"])


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    message: str
    history: Optional[List[ChatMessage]] = None


class ChatResponse(BaseModel):
    reply: str
    support_phone: str
    action: Optional[str] = None
    action_data: Optional[dict] = None


@router.post("/", response_model=ChatResponse)
async def chat(
    data: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    history = [m.model_dump() for m in data.history] if data.history else []
    result = await get_ai_response(
        message=data.message,
        db=db,
        history=history,
        user_id=str(user.id),
        role=user.role,
    )
    return ChatResponse(
        reply=result["reply"],
        support_phone=settings.SUPPORT_PHONE,
        action=result.get("action"),
        action_data=result.get("action_data"),
    )


@router.post("/guest", response_model=ChatResponse)
async def guest_chat(data: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Public chat for unauthenticated visitors on landing page."""
    history = [m.model_dump() for m in data.history] if data.history else []
    result = await get_ai_response(message=data.message, db=db, history=history)
    return ChatResponse(
        reply=result["reply"],
        support_phone=settings.SUPPORT_PHONE,
    )
