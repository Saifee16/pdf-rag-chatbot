from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.core.config import Settings, get_settings
from app.schemas.common import SuccessResponse
from app.schemas.index import IndexInfoData
from app.services.index_config import index_fingerprint

router = APIRouter()


@router.get("/index/info", response_model=SuccessResponse[IndexInfoData])
def index_info(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SuccessResponse[IndexInfoData]:
    return SuccessResponse(
        request_id=request.state.request_id,
        data=IndexInfoData(
            collection=settings.qdrant_collection,
            embedding_provider=settings.embedding_provider,
            embedding_model=settings.embedding_model,
            chunk_size=settings.chunk_size,
            chunk_overlap=settings.chunk_overlap,
            index_fingerprint=index_fingerprint(settings),
        ),
    )
