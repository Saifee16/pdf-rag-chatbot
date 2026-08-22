from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.dependencies import get_retrieval_service
from app.schemas.common import SuccessResponse
from app.schemas.retrieval import RetrievalData, RetrievalHitData, RetrievalRequest
from app.services.retrieval_service import RetrievalService

router = APIRouter()


@router.post("/retrieval/search", response_model=SuccessResponse[RetrievalData])
def retrieval_search(
    payload: RetrievalRequest,
    request: Request,
    service: Annotated[RetrievalService, Depends(get_retrieval_service)],
) -> SuccessResponse[RetrievalData]:
    result = service.retrieve(
        query=payload.query,
        document_ids=payload.document_ids,
        top_k=payload.top_k,
        score_threshold=payload.score_threshold,
        mode=payload.mode,
    )
    hits = [
        RetrievalHitData(
            rank=index,
            chunk_id=hit.id,
            document_id=str(hit.payload.get("document_id", "")),
            filename=str(hit.payload.get("filename", "")),
            page_number=int(hit.payload.get("page_number", 0)),
            chunk_index=int(hit.payload.get("chunk_index", 0)),
            score=round(hit.score, 6),
            text=str(hit.payload.get("text", "")),
        )
        for index, hit in enumerate(result.hits, start=1)
    ]
    return SuccessResponse(
        request_id=request.state.request_id,
        data=RetrievalData(
            trace_id=result.trace_id,
            query=payload.query,
            count=len(hits),
            mode=result.mode,
            hits=hits,
            retrieval_confidence=result.confidence,
            abstained=result.abstained,
            abstention_reason=result.abstention_reason,
        ),
    )
