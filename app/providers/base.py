from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(slots=True)
class GeneratedAnswer:
    content: str
    provider: str
    model: str


class ChatProvider(ABC):
    name: str
    model: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
    ) -> GeneratedAnswer:
        """Generate an answer while keeping policy separate from user/document content."""
        raise NotImplementedError


class EmbeddingProvider(ABC):
    name: str
    model: str

    @property
    @abstractmethod
    def configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        raise NotImplementedError
