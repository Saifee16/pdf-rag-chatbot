from typing import Literal

from pydantic import BaseModel, Field, model_validator


class RetrievalRequest(BaseModel):
    query: str = Field(min_length=1, max_length=10_000)
    document_ids: list[str] | None = None
    top_k: int | None = Field(default=None, ge=1, le=50)
    score_threshold: float | None = Field(default=None, ge=0.0, le=1.0)
    mode: Literal["dense", "hybrid", "hybrid_rerank"] | None = None

    @model_validator(mode="after")
    def reject_blank_document_ids(self) -> "RetrievalRequest":
        if self.document_ids and any(not value.strip() for value in self.document_ids):
            raise ValueError("document_ids cannot contain blank values")
        return self


class RetrievalHitData(BaseModel):
    rank: int
    chunk_id: str
    document_id: str
    filename: str
    page_number: int
    chunk_index: int
    score: float
    text: str


class RetrievalData(BaseModel):
    trace_id: str
    query: str
    count: int
    mode: Literal["dense", "hybrid", "hybrid_rerank"]
    hits: list[RetrievalHitData]
    retrieval_confidence: float = 0.0
    abstained: bool = False
    abstention_reason: str | None = None
