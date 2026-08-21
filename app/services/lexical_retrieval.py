from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Document
from app.services.vector_store import VectorHit

TOKEN_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]*", re.IGNORECASE)


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(text)]


@dataclass(slots=True)
class LexicalHit:
    id: str
    score: float
    payload: dict[str, object]


class LexicalRetriever:
    """Small, provider-free lexical retriever over already-authorized chunks.

    PostgreSQL uses its indexed full-text expression. SQLite (used by tests and
    local quickstarts) uses deterministic token overlap as a portable fallback.
    Both paths are constrained to the document IDs resolved by RetrievalService.
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    def search(
        self,
        *,
        query: str,
        document_ids: list[str],
        limit: int,
    ) -> list[VectorHit]:
        if not document_ids or limit <= 0:
            return []

        bind = self.db.get_bind()
        if bind.dialect.name == "postgresql":
            return self._postgres_search(query, document_ids, limit)
        return self._portable_search(query, document_ids, limit)

    def _postgres_search(self, query: str, document_ids: list[str], limit: int) -> list[VectorHit]:
        vector = func.to_tsvector("simple", Chunk.text)
        ts_query = func.plainto_tsquery("simple", query)
        rank = func.ts_rank_cd(vector, ts_query)
        statement = (
            select(Chunk, Document.original_filename, rank.label("rank"))
            .join(Document, Document.id == Chunk.document_id)
            .where(
                Chunk.document_id.in_(document_ids),
                Document.status == "ready",
                vector.op("@@")(ts_query),
            )
            .order_by(desc(rank), Chunk.id)
            .limit(limit)
        )
        rows = self.db.execute(statement).all()
        return [self._to_hit(chunk, filename, float(score)) for chunk, filename, score in rows]

    def _portable_search(self, query: str, document_ids: list[str], limit: int) -> list[VectorHit]:
        statement = (
            select(Chunk, Document.original_filename)
            .join(Document, Document.id == Chunk.document_id)
            .where(Chunk.document_id.in_(document_ids), Document.status == "ready")
        )
        query_tokens = tokenize(query)
        if not query_tokens:
            return []
        query_set = set(query_tokens)
        scored: list[tuple[float, str, Chunk, str]] = []
        for chunk, filename in self.db.execute(statement).all():
            tokens = tokenize(chunk.text)
            if not tokens:
                continue
            counts = {token: tokens.count(token) for token in query_set}
            matched = sum(count > 0 for count in counts.values())
            if matched == 0:
                continue
            coverage = matched / len(query_set)
            frequency = sum(min(count, 3) for count in counts.values()) / max(len(tokens), 1)
            phrase_bonus = 1.0 if " ".join(query_tokens) in " ".join(tokens) else 0.0
            score = coverage + (0.25 * frequency) + (0.1 * phrase_bonus)
            scored.append((score, str(chunk.id), chunk, str(filename)))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [
            self._to_hit(chunk, filename, score) for score, _, chunk, filename in scored[:limit]
        ]

    @staticmethod
    def _to_hit(chunk: Chunk, filename: str, score: float) -> VectorHit:
        return VectorHit(
            id=str(chunk.id),
            score=score,
            payload={
                "document_id": str(chunk.document_id),
                "filename": filename,
                "page_number": int(chunk.page_number),
                "chunk_index": int(chunk.chunk_index),
                "text": chunk.text,
            },
        )


def as_vector_hits(hits: list[LexicalHit]) -> list[VectorHit]:
    return [VectorHit(id=hit.id, score=hit.score, payload=hit.payload) for hit in hits]
