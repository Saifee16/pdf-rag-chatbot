from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_rag_service
from app.schemas.chat import ChatData, ChatRequest
from app.schemas.common import SuccessResponse
from app.services.rag_service import RAGService

router = APIRouter()


@router.post("/chat", response_model=SuccessResponse[ChatData])
def chat(
    payload: ChatRequest,
    request: Request,
    service: Annotated[RAGService, Depends(get_rag_service)],
) -> SuccessResponse[ChatData]:
    data = service.ask(
        question=payload.question,
        conversation_id=payload.conversation_id,
        document_ids=payload.document_ids,
        top_k=payload.top_k,
        score_threshold=payload.score_threshold,
    )
    return SuccessResponse(request_id=request.state.request_id, data=data)
