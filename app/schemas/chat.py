from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=10_000)
    conversation_id: str | None = None
    document_ids: list[str] | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    mode: Literal["dense", "hybrid", "hybrid_rerank"] | None = None

    @model_validator(mode="after")
    def reject_blank_document_ids(self) -> "ChatRequest":
        if self.document_ids and any(not value.strip() for value in self.document_ids):
            raise ValueError("document_ids cannot contain blank values")
        return self


class CitationData(BaseModel):
    citation_number: int
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    score: float
    excerpt: str


class ChatData(BaseModel):
    conversation_id: str
    message_id: str
    answer: str
    citations: list[CitationData]
    retrieval_trace_id: str
    provider: str
    model: str
    retrieved_chunk_count: int


class MessageData(BaseModel):
    id: str
    role: str
    content: str
    citations: list[CitationData]
    created_at: datetime


class ConversationData(BaseModel):
    id: str
    title: str | None
    created_at: datetime
    updated_at: datetime
    messages: list[MessageData] = []


class ConversationListData(BaseModel):
    count: int
    conversations: list[ConversationData]


class DeleteConversationData(BaseModel):
    conversation_id: str
    deleted: bool
