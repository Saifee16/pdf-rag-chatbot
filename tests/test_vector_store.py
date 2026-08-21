from qdrant_client import QdrantClient

from app.core.config import get_settings
from app.services.vector_store import QdrantVectorStore, VectorPoint


def in_memory_store() -> QdrantVectorStore:
    store = object.__new__(QdrantVectorStore)
    store.settings = get_settings()
    store.client = QdrantClient(":memory:")
    store.collection = "test_chunks"
    return store


def test_qdrant_store_upsert_search_and_delete() -> None:
    store = in_memory_store()
    store.ensure_collection(3)
    store.upsert(
        [
            VectorPoint(
                id="11111111-1111-1111-1111-111111111111",
                vector=[1.0, 0.0, 0.0],
                payload={"document_id": "doc-1", "text": "alpha"},
            ),
            VectorPoint(
                id="22222222-2222-2222-2222-222222222222",
                vector=[0.0, 1.0, 0.0],
                payload={"document_id": "doc-2", "text": "beta"},
            ),
        ]
    )

    hits = store.search(
        vector=[1.0, 0.0, 0.0],
        document_ids=["doc-1"],
        limit=5,
        score_threshold=0.0,
    )
    assert len(hits) == 1
    assert hits[0].payload["text"] == "alpha"

    store.delete_document("doc-1")
    assert (
        store.search(
            vector=[1.0, 0.0, 0.0],
            document_ids=["doc-1"],
            limit=5,
            score_threshold=0.0,
        )
        == []
    )


def test_qdrant_store_rejects_dimension_mismatch() -> None:
    store = in_memory_store()
    store.ensure_collection(3)
    try:
        store.ensure_collection(4)
    except ValueError as exc:
        assert "dimensions" in str(exc)
    else:
        raise AssertionError("Expected dimension mismatch")
