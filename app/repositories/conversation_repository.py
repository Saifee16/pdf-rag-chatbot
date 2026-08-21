from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.db.models import Conversation, Message, utc_now


class ConversationRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create(self, title: str | None = None) -> Conversation:
        conversation = Conversation(title=title)
        self.db.add(conversation)
        self.db.commit()
        self.db.refresh(conversation)
        return conversation

    def get(self, conversation_id: str, *, with_messages: bool = False) -> Conversation | None:
        statement = select(Conversation).where(Conversation.id == conversation_id)
        if with_messages:
            statement = statement.options(selectinload(Conversation.messages))
        return self.db.scalar(statement)

    def list(self) -> list[Conversation]:
        return list(self.db.scalars(select(Conversation).order_by(Conversation.updated_at.desc())))

    def add_message(
        self,
        conversation: Conversation,
        *,
        role: str,
        content: str,
        citations: list[dict[str, object]] | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            role=role,
            content=content,
            citations_json=citations or [],
        )
        self.db.add(message)
        conversation.updated_at = utc_now()
        self.db.commit()
        self.db.refresh(message)
        return message

    def recent_messages(self, conversation_id: str, limit: int) -> list[Message]:
        if limit <= 0:
            return []
        statement = (
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        return list(reversed(list(self.db.scalars(statement))))

    def delete(self, conversation: Conversation) -> None:
        self.db.delete(conversation)
        self.db.commit()
