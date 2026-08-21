from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_conversation_service
from app.schemas.chat import ConversationData, ConversationListData, DeleteConversationData
from app.schemas.common import SuccessResponse
from app.services.conversation_service import ConversationService

router = APIRouter()


@router.get("/conversations", response_model=SuccessResponse[ConversationListData])
def list_conversations(
    request: Request,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> SuccessResponse[ConversationListData]:
    conversations = service.list()
    return SuccessResponse(
        request_id=request.state.request_id,
        data=ConversationListData(count=len(conversations), conversations=conversations),
    )


@router.get(
    "/conversations/{conversation_id}",
    response_model=SuccessResponse[ConversationData],
)
def get_conversation(
    conversation_id: str,
    request: Request,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> SuccessResponse[ConversationData]:
    return SuccessResponse(
        request_id=request.state.request_id,
        data=service.get(conversation_id),
    )


@router.delete(
    "/conversations/{conversation_id}",
    response_model=SuccessResponse[DeleteConversationData],
)
def delete_conversation(
    conversation_id: str,
    request: Request,
    service: Annotated[ConversationService, Depends(get_conversation_service)],
) -> SuccessResponse[DeleteConversationData]:
    service.delete(conversation_id)
    return SuccessResponse(
        request_id=request.state.request_id,
        data=DeleteConversationData(conversation_id=conversation_id, deleted=True),
    )
