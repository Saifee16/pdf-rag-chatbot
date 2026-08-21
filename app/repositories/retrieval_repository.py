from __future__ import annotations

from sqlalchemy.orm import Session

from app.db.models import RetrievalTrace


class RetrievalRepository:
    def __init__(self, db: Session) -> None:
        self.db = db

    def add(
        self,
        *,
        conversation_id: str | None,
        query: str,
        top_k: int,
        document_ids: list[str],
        results: list[dict[str, object]],
        latency_ms: float,
    ) -> RetrievalTrace:
        trace = RetrievalTrace(
            conversation_id=conversation_id,
            query=query,
            top_k=top_k,
            document_ids_json=document_ids,
            results_json=results,
            latency_ms=latency_ms,
        )
        self.db.add(trace)
        self.db.commit()
        self.db.refresh(trace)
        return trace
