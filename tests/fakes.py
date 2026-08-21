import math
import re
from dataclasses import dataclass

from app.providers.base import ChatProvider, EmbeddingProvider, GeneratedAnswer
from app.services.task_dispatcher import DispatchedTask
from app.services.vector_store import VectorHit, VectorPoint


def text_vector(text: str, dimensions: int = 12) -> list[float]:
    vector = [0.0] * dimensions
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        bucket = sum(word.encode("utf-8")) % dimensions
        vector[bucket] += 1.0
    magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / magnitude for value in vector]


class FakeEmbeddingProvider(EmbeddingProvider):
    name = "fake-embeddings"
    model = "fake-embedding-v1"

    @property
    def configured(self) -> bool:
        return True

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [text_vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return text_vector(text)


class FakeChatProvider(ChatProvider):
    name = "fake-chat"
    model = "fake-chat-v1"

    @property
    def configured(self) -> bool:
        return True

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
    ) -> GeneratedAnswer:
        assert "untrusted source data" in system_instruction
        if "<document_context" in prompt:
            content = "The retrieved document provides the grounded answer [1]."
        else:
            content = "The provided documents do not contain enough information."
        return GeneratedAnswer(content=content, provider=self.name, model=self.model)


class FakeRegistry:
    def __init__(self) -> None:
        self.chat_provider = FakeChatProvider()
        self.embedding_provider = FakeEmbeddingProvider()
        self.chat_providers = {"gemini": self.chat_provider}
        self.embedding_providers = {"gemini": self.embedding_provider}

    def chat(self) -> ChatProvider:
        return self.chat_provider

    def embeddings(self) -> EmbeddingProvider:
        return self.embedding_provider


class FakeVectorStore:
    def __init__(self) -> None:
        self.points: dict[str, VectorPoint] = {}
        self.dimensions: int | None = None

    def ready(self) -> bool:
        return True

    def collection_exists(self) -> bool:
        return self.dimensions is not None

    def ensure_collection(self, dimensions: int) -> None:
        if self.dimensions is not None and self.dimensions != dimensions:
            raise ValueError("dimension mismatch")
        self.dimensions = dimensions

    def upsert(self, points: list[VectorPoint]) -> None:
        for point in points:
            self.points[point.id] = point

    def delete_document(self, document_id: str) -> None:
        self.points = {
            point_id: point
            for point_id, point in self.points.items()
            if point.payload.get("document_id") != document_id
        }

    def search(
        self,
        *,
        vector: list[float],
        document_ids: list[str],
        limit: int,
        score_threshold: float,
    ) -> list[VectorHit]:
        hits: list[VectorHit] = []
        for point in self.points.values():
            if document_ids and point.payload.get("document_id") not in document_ids:
                continue
            score = sum(left * right for left, right in zip(vector, point.vector, strict=True))
            if score >= score_threshold:
                hits.append(VectorHit(id=point.id, score=score, payload=point.payload))
        return sorted(hits, key=lambda item: item.score, reverse=True)[:limit]


@dataclass
class FakeTaskDispatcher:
    document_ids: list[str]

    def enqueue_ingestion(self, document_id: str) -> DispatchedTask:
        self.document_ids.append(document_id)
        return DispatchedTask(id=f"task-{document_id}")
