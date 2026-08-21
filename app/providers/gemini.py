from fastapi import status
from google import genai
from google.genai import types

from app.core.exceptions import AppError
from app.core.logging import get_logger
from app.providers.base import ChatProvider, EmbeddingProvider, GeneratedAnswer

logger = get_logger(__name__)


class GeminiProvider(ChatProvider, EmbeddingProvider):
    name = "gemini"

    def __init__(
        self,
        *,
        api_key: str,
        chat_model: str,
        embedding_model: str,
    ) -> None:
        self.api_key = api_key
        self.model = chat_model
        self.embedding_model = embedding_model
        self.client = genai.Client(api_key=api_key) if api_key else None

    @property
    def configured(self) -> bool:
        return self.client is not None

    def _require_client(self) -> genai.Client:
        if self.client is None:
            raise AppError(
                message="Gemini is not configured.",
                code="GEMINI_NOT_CONFIGURED",
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
            response = self._require_client().interactions.create(
                model=self.model,
                input=prompt,
                system_instruction=system_instruction,
                store=False,
            )
        except AppError:
            raise
        except Exception as exc:
            logger.exception("Gemini generation failed")
            raise AppError(
                message="Gemini generation failed.",
                code="GEMINI_GENERATION_FAILED",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        return GeneratedAnswer(
            content=response.output_text,
            provider=self.name,
            model=self.model,
        )

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        try:
            response = self._require_client().models.embed_content(
                model=self.embedding_model,
                contents=texts,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_DOCUMENT"),
            )
        except AppError:
            raise
        except Exception as exc:
            logger.exception("Gemini document embedding failed")
            raise AppError(
                message="Gemini document embedding failed.",
                code="GEMINI_EMBEDDING_FAILED",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        return [list(item.values) for item in response.embeddings]

    def embed_query(self, text: str) -> list[float]:
        try:
            response = self._require_client().models.embed_content(
                model=self.embedding_model,
                contents=text,
                config=types.EmbedContentConfig(task_type="RETRIEVAL_QUERY"),
            )
        except AppError:
            raise
        except Exception as exc:
            logger.exception("Gemini query embedding failed")
            raise AppError(
                message="Gemini query embedding failed.",
                code="GEMINI_EMBEDDING_FAILED",
                status_code=status.HTTP_502_BAD_GATEWAY,
            ) from exc

        return list(response.embeddings[0].values)
