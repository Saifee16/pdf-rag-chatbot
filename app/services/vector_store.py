from dataclasses import dataclass

from qdrant_client import QdrantClient, models

from app.core.config import Settings


@dataclass(slots=True)
class VectorPoint:
    id: str
    vector: list[float]
    payload: dict[str, object]


@dataclass(slots=True)
class VectorHit:
    id: str
    score: float
    payload: dict[str, object]


class QdrantVectorStore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        kwargs: dict[str, object] = {"url": settings.qdrant_url, "timeout": 30}
        if settings.qdrant_api_key:
            kwargs["api_key"] = settings.qdrant_api_key
        self.client = QdrantClient(**kwargs)
        self.collection = settings.qdrant_collection

    def ready(self) -> bool:
        self.client.get_collections()
        return True

    def collection_exists(self) -> bool:
        return self.client.collection_exists(self.collection)

    def ensure_collection(self, dimensions: int) -> None:
        if not self.collection_exists():
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=models.VectorParams(
                    size=dimensions, distance=models.Distance.COSINE
                ),
            )
            return

        info = self.client.get_collection(self.collection)
        vectors = info.config.params.vectors
        configured_size = getattr(vectors, "size", None)
        if configured_size is not None and configured_size != dimensions:
            raise ValueError(
                f"Qdrant collection expects {configured_size} dimensions but provider returned {dimensions}."
            )

    def upsert(self, points: list[VectorPoint]) -> None:
        if not points:
            return
        self.client.upsert(
            collection_name=self.collection,
            points=[
                models.PointStruct(id=point.id, vector=point.vector, payload=point.payload)
                for point in points
            ],
            wait=True,
        )

    def delete_document(self, document_id: str) -> None:
        if not self.collection_exists():
            return
        self.client.delete(
            collection_name=self.collection,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id", match=models.MatchValue(value=document_id)
                        )
                    ]
                )
            ),
            wait=True,
        )

    def search(
        self,
        *,
        vector: list[float],
        document_ids: list[str],
        limit: int,
        score_threshold: float,
    ) -> list[VectorHit]:
        if not self.collection_exists():
            return []

        query_filter = None
        if document_ids:
            query_filter = models.Filter(
                must=[
                    models.FieldCondition(
                        key="document_id", match=models.MatchAny(any=document_ids)
                    )
                ]
            )

        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
            with_payload=True,
        )
        return [
            VectorHit(id=str(point.id), score=float(point.score), payload=dict(point.payload or {}))
            for point in response.points
        ]
