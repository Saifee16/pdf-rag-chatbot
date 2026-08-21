from fastapi import status
from openai import OpenAI

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.providers.base import ChatProvider, EmbeddingProvider, GeneratedAnswer

logger = get_logger(__name__)


class OpenAIProvider(ChatProvider, EmbeddingProvider):
    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        chat_model: str,
        embedding_model: str,
        timeout_seconds: float,
    ) -> None:
        self.api_key = api_key
        self.model = chat_model
        self.embedding_model = embedding_model
        self.client = (
            OpenAI(api_key=api_key, timeout=timeout_seconds, max_retries=2) if api_key else None
        )

    @property
    def configured(self) -> bool:
        return self.client is not None

    def _require_client(self) -> OpenAI:
        if self.client is None:
            raise AppError(
                message="OpenAI is not configured.",
                code="OPENAI_NOT_CONFIGURED",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        return self.client

    def generate(
        self,
        *,
        system_instruction: str,
        prompt: str,
    ) -> GeneratedAnswer:
        try:
            response = self._require_client().responses.create(
                model=self.model,
                instructions=system_instruction,
                input=prompt,
                store=False,
            )
        except AppError:
            raise
        except Exception as exc:
            logger.exception("OpenAI generation failed")
            raise AppError(
                message="OpenAI generation failed.",
                code="OPENAI_GENERATION_FAILED",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        return GeneratedAnswer(
            content=response.output_text,
            provider=self.name,
            model=self.model,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self._require_client().embeddings.create(
                model=self.embedding_model,
                input=texts,
            )
        except AppError:
            raise
        except Exception as exc:
            logger.exception("OpenAI document embedding failed")
            raise AppError(
                message="OpenAI document embedding failed.",
                code="OPENAI_EMBEDDING_FAILED",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        return [list(item.embedding) for item in response.data]

    def embed_query(self, text: str) -> list[float]:
        try:
            response = self._require_client().embeddings.create(
                model=self.embedding_model,
                input=[text],
            )
        except AppError:
            raise
        except Exception as exc:
            logger.exception("OpenAI query embedding failed")
            raise AppError(
                message="OpenAI query embedding failed.",
                code="OPENAI_EMBEDDING_FAILED",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        return list(response.data[0].embedding)
