from fastapi import status
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db.models import Conversation, Message
from app.repositories.conversation_repository import ConversationRepository
from app.schemas.chat import CitationData, ConversationData, MessageData


class ConversationService:
    def __init__(self, db: Session) -> None:
        self.repository = ConversationRepository(db)

    def get(self, conversation_id: str) -> ConversationData:
        conversation = self.repository.get(conversation_id, with_messages=True)
        if conversation is None:
            raise AppError(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        return self._to_data(conversation, include_messages=True)

    def list(self) -> list[ConversationData]:
        return [self._to_data(item, include_messages=False) for item in self.repository.list()]

    def delete(self, conversation_id: str) -> None:
        conversation = self.repository.get(conversation_id)
        if conversation is None:
            raise AppError(
                message="Conversation not found.",
                code="CONVERSATION_NOT_FOUND",
                status_code=status.HTTP_404_NOT_FOUND,
            )
        self.repository.delete(conversation)

    @staticmethod
    def _message_data(message: Message) -> MessageData:
        return MessageData(
            id=message.id,
            role=message.role,
            content=message.content,
            citations=[CitationData.model_validate(item) for item in message.citations_json],
            created_at=message.created_at,
        )

    def _to_data(self, conversation: Conversation, *, include_messages: bool) -> ConversationData:
        messages = (
            [
                self._message_data(message)
                for message in sorted(conversation.messages, key=lambda item: item.created_at)
            ]
            if include_messages
            else []
        )
        return ConversationData(
            id=conversation.id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=messages,
        )
