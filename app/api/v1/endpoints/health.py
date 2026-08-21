from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from redis import Redis
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.db.database import get_db
from app.dependencies import get_vector_store
from app.providers.registry import ProviderRegistry, get_provider_registry
from app.schemas.common import SuccessResponse
from app.schemas.health import ComponentStatus, HealthData, ReadinessData
from app.services.vector_store import QdrantVectorStore

router = APIRouter()


@router.get("/health", response_model=SuccessResponse[HealthData])
def health(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SuccessResponse[HealthData]:
    return SuccessResponse(
        request_id=request.state.request_id,
        data=HealthData(app=settings.app_name, environment=settings.app_env),
    )


@router.get("/ready", response_model=SuccessResponse[ReadinessData])
def ready(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    registry: Annotated[ProviderRegistry, Depends(get_provider_registry)],
    vector_store: Annotated[QdrantVectorStore, Depends(get_vector_store)],
) -> SuccessResponse[ReadinessData]:
    components: list[ComponentStatus] = []

    try:
        db.execute(text("SELECT 1"))
        components.append(ComponentStatus(name="database", ready=True, detail="reachable"))
    except Exception as exc:
        components.append(ComponentStatus(name="database", ready=False, detail=type(exc).__name__))

    try:
        Redis.from_url(settings.redis_url, socket_connect_timeout=2).ping()
        components.append(ComponentStatus(name="redis", ready=True, detail="reachable"))
    except Exception as exc:
        components.append(ComponentStatus(name="redis", ready=False, detail=type(exc).__name__))

    try:
        vector_store.ready()
        components.append(ComponentStatus(name="qdrant", ready=True, detail="reachable"))
    except Exception as exc:
        components.append(ComponentStatus(name="qdrant", ready=False, detail=type(exc).__name__))

    chat = registry.chat_providers[settings.chat_provider]
    embedding = registry.embedding_providers[settings.embedding_provider]
    components.append(
        ComponentStatus(
            name="chat_provider",
            ready=chat.configured,
            detail=f"{settings.chat_provider}:{settings.chat_model}",
        )
    )
    components.append(
        ComponentStatus(
            name="embedding_provider",
            ready=embedding.configured,
            detail=f"{settings.embedding_provider}:{settings.embedding_model}",
        )
    )

    is_ready = all(component.ready for component in components)
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return SuccessResponse(
        request_id=request.state.request_id,
        data=ReadinessData(ready=is_ready, components=components),
    )
