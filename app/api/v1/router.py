from fastapi import APIRouter, Depends

from app.api.v1.endpoints import chat, conversations, documents, health, index, retrieval
from app.core.security import require_api_key

api_router = APIRouter()
api_router.include_router(health.router, tags=["Health"])

protected = [Depends(require_api_key)]
api_router.include_router(index.router, tags=["Index"], dependencies=protected)
api_router.include_router(documents.router, tags=["Documents"], dependencies=protected)
api_router.include_router(retrieval.router, tags=["Retrieval"], dependencies=protected)
api_router.include_router(chat.router, tags=["RAG Chat"], dependencies=protected)
api_router.include_router(conversations.router, tags=["Conversations"], dependencies=protected)
