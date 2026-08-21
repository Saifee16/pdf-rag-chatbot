from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.database import get_db
from app.providers.registry import ProviderRegistry, get_provider_registry
from app.services.conversation_service import ConversationService
from app.services.rag_service import RAGService
from app.services.retrieval_service import RetrievalService
from app.services.storage_service import LocalStorageService
from app.services.vector_store import QdrantVectorStore


@lru_cache
def get_storage_service() -> LocalStorageService:
    return LocalStorageService(get_settings())


@lru_cache
def get_vector_store() -> QdrantVectorStore:
    return QdrantVectorStore(get_settings())


def get_retrieval_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
    vector_store: Annotated[QdrantVectorStore, Depends(get_vector_store)],
) -> RetrievalService:
    return RetrievalService(
        db=db,
        settings=settings,
        embedding_provider=registry.embeddings(),
        vector_store=vector_store,
    )


def get_rag_service(
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
    retrieval_service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> RAGService:
    return RAGService(
        db=db,
        settings=settings,
        chat_provider=registry.chat(),
        retrieval_service=retrieval_service,
    )


def get_conversation_service(
    db: Annotated[Session, Depends(get_db)],
) -> ConversationService:
    return ConversationService(db)
