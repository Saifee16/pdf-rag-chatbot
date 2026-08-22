from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, computed_field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="PDF RAG Chatbot", alias="APP_NAME")
    app_env: Literal["local", "development", "staging", "production"] = Field(
        default="local", alias="APP_ENV"
    )
    app_debug: bool = Field(default=True, alias="APP_DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")
    docs_enabled: bool = Field(default=True, alias="DOCS_ENABLED")
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="INFO", alias="LOG_LEVEL"
    )

    database_url: str = Field(default="sqlite:///./rag.db", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: str = Field(default="", alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="pdf_chunks", alias="QDRANT_COLLECTION")

    storage_dir: Path = Field(default=Path("./data/uploads"), alias="STORAGE_DIR")
    max_pdf_size_mb: int = Field(default=25, ge=1, le=500, alias="MAX_PDF_SIZE_MB")
    max_pdf_pages: int = Field(default=5_000, ge=1, le=100_000, alias="MAX_PDF_PAGES")

    chunk_size: int = Field(default=1200, ge=200, le=10_000, alias="CHUNK_SIZE")
    chunk_overlap: int = Field(default=200, ge=0, le=5000, alias="CHUNK_OVERLAP")
    embedding_batch_size: int = Field(default=32, ge=1, le=256, alias="EMBEDDING_BATCH_SIZE")
    retrieval_top_k: int = Field(default=5, ge=1, le=50, alias="RETRIEVAL_TOP_K")
    retrieval_score_threshold: float = Field(
        default=0.35, ge=0.0, le=1.0, alias="RETRIEVAL_SCORE_THRESHOLD"
    )
    retrieval_abstention_enabled: bool = Field(default=True, alias="RETRIEVAL_ABSTENTION_ENABLED")
    retrieval_confidence_threshold: float = Field(
        default=0.50, ge=0.0, le=1.0, alias="RETRIEVAL_CONFIDENCE_THRESHOLD"
    )
    retrieval_mode: Literal["dense", "hybrid", "hybrid_rerank"] = Field(
        default="hybrid", alias="RETRIEVAL_MODE"
    )
    hybrid_dense_candidates: int = Field(default=20, ge=1, le=200, alias="HYBRID_DENSE_CANDIDATES")
    hybrid_lexical_candidates: int = Field(
        default=20, ge=1, le=200, alias="HYBRID_LEXICAL_CANDIDATES"
    )
    retrieval_rrf_k: int = Field(default=60, ge=1, le=1000, alias="RETRIEVAL_RRF_K")
    reranker_provider: Literal["none", "deterministic"] = Field(
        default="deterministic", alias="RERANKER_PROVIDER"
    )
    rerank_candidates: int = Field(default=20, ge=1, le=200, alias="RERANK_CANDIDATES")
    conversation_history_messages: int = Field(
        default=6, ge=0, le=50, alias="CONVERSATION_HISTORY_MESSAGES"
    )

    chat_provider: Literal["gemini", "openai", "gateway"] = Field(
        default="gemini", alias="CHAT_PROVIDER"
    )
    embedding_provider: Literal["gemini", "openai"] = Field(
        default="gemini", alias="EMBEDDING_PROVIDER"
    )
    chat_model: str = Field(default="gemini-3.5-flash", alias="CHAT_MODEL")
    embedding_model: str = Field(default="gemini-embedding-001", alias="EMBEDDING_MODEL")
    gemini_api_key: str = Field(default="", alias="GEMINI_API_KEY")
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    gateway_url: str = Field(default="http://localhost:8001", alias="GATEWAY_URL")
    gateway_api_key: str = Field(default="", alias="GATEWAY_API_KEY")
    gateway_model_alias: str = Field(default="fast", alias="GATEWAY_MODEL_ALIAS")
    provider_timeout_seconds: float = Field(
        default=60.0, ge=1.0, le=600.0, alias="PROVIDER_TIMEOUT_SECONDS"
    )

    api_auth_enabled: bool = Field(default=False, alias="API_AUTH_ENABLED")
    api_keys: str = Field(default="", alias="API_KEYS")
    cors_origins: str = Field(default="", alias="CORS_ORIGINS")
    allowed_hosts: str = Field(default="*", alias="ALLOWED_HOSTS")

    celery_task_always_eager: bool = Field(default=False, alias="CELERY_TASK_ALWAYS_EAGER")
    rag_system_prompt_path: Path = Field(
        default=Path("./prompts/rag_system.txt"), alias="RAG_SYSTEM_PROMPT_PATH"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    @model_validator(mode="after")
    def validate_chunking_configuration(self) -> Self:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")
        return self

    @model_validator(mode="after")
    def validate_production_security(self) -> Self:
        if self.app_env != "production":
            return self

        unsafe_settings: list[str] = []

        if self.app_debug:
            unsafe_settings.append("APP_DEBUG must be false")
        if not self.api_auth_enabled:
            unsafe_settings.append("API_AUTH_ENABLED must be true")
        if not self.parsed_api_keys:
            unsafe_settings.append("API_KEYS must contain at least one key")
        if "*" in self.parsed_allowed_hosts:
            unsafe_settings.append("ALLOWED_HOSTS must not contain '*'")

        if unsafe_settings:
            details = "; ".join(unsafe_settings)
            raise ValueError(f"Unsafe production configuration: {details}")

        return self

    @computed_field
    @property
    def max_pdf_size_bytes(self) -> int:
        return self.max_pdf_size_mb * 1024 * 1024

    @property
    def parsed_api_keys(self) -> tuple[str, ...]:
        return tuple(item.strip() for item in self.api_keys.split(",") if item.strip())

    @property
    def parsed_cors_origins(self) -> list[str]:
        return [item.strip() for item in self.cors_origins.split(",") if item.strip()]

    @property
    def parsed_allowed_hosts(self) -> list[str]:
        values = [item.strip() for item in self.allowed_hosts.split(",") if item.strip()]
        return values or ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
