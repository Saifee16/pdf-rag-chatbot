from datetime import datetime
from typing import Literal

from pydantic import BaseModel

DocumentStatus = Literal["pending", "processing", "ready", "failed"]


class DocumentData(BaseModel):
    id: str
    original_filename: str
    sha256: str
    size_bytes: int
    status: DocumentStatus
    page_count: int
    chunk_count: int
    embedding_provider: str | None
    embedding_model: str | None
    index_fingerprint: str | None
    error_message: str | None
    created_at: datetime
    updated_at: datetime


class DocumentListData(BaseModel):
    count: int
    documents: list[DocumentData]


class DocumentAcceptedData(BaseModel):
    document: DocumentData
    task_id: str


class DeleteDocumentData(BaseModel):
    document_id: str
    deleted: bool


class ReindexDocumentData(BaseModel):
    document_id: str
    task_id: str
    status: Literal["pending"] = "pending"
