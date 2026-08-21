import time
from dataclasses import dataclass

from fastapi import status
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AppError
from app.providers.base import EmbeddingProvider
from app.repositories.document_repository import DocumentRepository
from app.repositories.retrieval_repository import RetrievalRepository
from app.services.index_config import index_fingerprint
from app.services.vector_store import QdrantVectorStore, VectorHit


@dataclass(slots=True)
class RetrievalResult:
    trace_id: str
    hits: list[VectorHit]


class RetrievalService:
    def __init__(
        self,
        *,
        db: Session,
        settings: Settings,
        embedding_provider: EmbeddingProvider,
        vector_store: QdrantVectorStore,
    ) -> None:
        self.settings = settings
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.documents = DocumentRepository(db)
        self.traces = RetrievalRepository(db)

    def retrieve(
        self,
        *,
        query: str,
        document_ids: list[str] | None,
        top_k: int | None,
        score_threshold: float | None,
        conversation_id: str | None = None,
    ) -> RetrievalResult:
        started = time.perf_counter()
        fingerprint = index_fingerprint(self.settings)
        selected_ids = self._resolve_document_ids(document_ids, fingerprint)

        if not selected_ids:
            trace = self.traces.add(
                conversation_id=conversation_id,
                query=query,
                top_k=top_k or self.settings.retrieval_top_k,
                document_ids=[],
                results=[],
                latency_ms=round((time.perf_counter() - started) * 1000, 2),
            )
            return RetrievalResult(trace_id=trace.id, hits=[])

        vector = self.embedding_provider.embed_query(query)
        resolved_top_k = top_k or self.settings.retrieval_top_k
        threshold = (
            score_threshold
            if score_threshold is not None
            else self.settings.retrieval_score_threshold
        )
        hits = self.vector_store.search(
            vector=vector,
            document_ids=selected_ids,
            limit=resolved_top_k,
            score_threshold=threshold,
        )
        results_json = [
            {
                "chunk_id": hit.id,
                "document_id": str(hit.payload.get("document_id", "")),
                "filename": str(hit.payload.get("filename", "")),
                "page_number": int(hit.payload.get("page_number", 0)),
                "chunk_index": int(hit.payload.get("chunk_index", 0)),
                "score": hit.score,
            }
            for hit in hits
        ]
        trace = self.traces.add(
            conversation_id=conversation_id,
            query=query,
            top_k=resolved_top_k,
            document_ids=selected_ids,
            results=results_json,
            latency_ms=round((time.perf_counter() - started) * 1000, 2),
        )
        return RetrievalResult(trace_id=trace.id, hits=hits)

    def _resolve_document_ids(self, document_ids: list[str] | None, fingerprint: str) -> list[str]:
        if document_ids:
            documents = self.documents.selected_ready(document_ids)
            found = {document.id for document in documents}
            missing = sorted(set(document_ids) - found)
            if missing:
                raise AppError(
                    message=f"Documents are missing or not ready: {', '.join(missing)}",
                    code="DOCUMENTS_NOT_READY",
                    status_code=status.HTTP_409_CONFLICT,
                )
            stale = [
                document.id for document in documents if document.index_fingerprint != fingerprint
            ]
            if stale:
                raise AppError(
                    message=(
                        "Selected documents were indexed with a different embedding/chunk configuration. "
                        f"Reindex them first: {', '.join(stale)}"
                    ),
                    code="INDEX_CONFIGURATION_MISMATCH",
                    status_code=status.HTTP_409_CONFLICT,
                )
            return [document.id for document in documents]

        return [document.id for document in self.documents.ready_for_fingerprint(fingerprint)]
