from functools import lru_cache

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.providers.base import ChatProvider, EmbeddingProvider
from app.providers.gateway import GatewayChatProvider
from app.providers.gemini import GeminiProvider
from app.providers.openai import OpenAIProvider


class ProviderRegistry:
    def __init__(self, settings: Settings) -> None:
        gemini = GeminiProvider(
            api_key=settings.gemini_api_key,
            chat_model=settings.chat_model,
            embedding_model=settings.embedding_model,
        )
        openai = OpenAIProvider(
            api_key=settings.openai_api_key,
            chat_model=settings.chat_model,
            embedding_model=settings.embedding_model,
            timeout_seconds=settings.provider_timeout_seconds,
        )
        gateway = GatewayChatProvider(
            base_url=settings.gateway_url,
            api_key=settings.gateway_api_key,
            model_alias=settings.gateway_model_alias,
            timeout_seconds=settings.provider_timeout_seconds,
        )

        self.chat_providers: dict[str, ChatProvider] = {
            "gemini": gemini,
            "openai": openai,
            "gateway": gateway,
        }
        self.embedding_providers: dict[str, EmbeddingProvider] = {
            "gemini": gemini,
            "openai": openai,
        }
        self.settings = settings

    def chat(self) -> ChatProvider:
        provider = self.chat_providers[self.settings.chat_provider]
        if not provider.configured:
            raise AppError(
                message=f"Chat provider '{self.settings.chat_provider}' is not configured.",
                code="CHAT_PROVIDER_NOT_CONFIGURED",
                status_code=503,
            )
        return provider

    def embeddings(self) -> EmbeddingProvider:
        provider = self.embedding_providers[self.settings.embedding_provider]
        if not provider.configured:
            raise AppError(
                message=f"Embedding provider '{self.settings.embedding_provider}' is not configured.",
                code="EMBEDDING_PROVIDER_NOT_CONFIGURED",
                status_code=503,
            )
        return provider


@lru_cache
def get_provider_registry() -> ProviderRegistry:
    return ProviderRegistry(get_settings())
