from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends

from ai_content_pipeline.api.deps import get_services
from ai_content_pipeline.models import ChatTurn
from ai_content_pipeline.services import Services

router = APIRouter(prefix="/api/v1/chat", tags=["RAG 智能客服"])


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    session_id: str | None = None


@router.post("", response_model=ChatTurn, summary="客服对话（多轮记忆 + Function Calling）")
def chat(req: ChatRequest, services: Services = Depends(get_services)) -> ChatTurn:
    return services.chat_engine.handle_message(req.session_id, req.message)

