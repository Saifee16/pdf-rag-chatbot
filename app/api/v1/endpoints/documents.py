from pathlib import Path
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Depends, Request, UploadFile, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.db.database import get_db
from app.db.models import Document
from app.dependencies import get_storage_service, get_vector_store
from app.repositories.document_repository import DocumentRepository
from app.schemas.common import SuccessResponse
from app.schemas.document import (
    DeleteDocumentData,
    DocumentAcceptedData,
    DocumentData,
    DocumentListData,
    ReindexDocumentData,
)
from app.services.storage_service import LocalStorageService
from app.services.task_dispatcher import TaskDispatcher, get_task_dispatcher
from app.services.vector_store import QdrantVectorStore

router = APIRouter()


def to_document_data(document: Document) -> DocumentData:
    return DocumentData(
        id=document.id,
        original_filename=document.original_filename,
        sha256=document.sha256,
        size_bytes=document.size_bytes,
        status=document.status,
        page_count=document.page_count,
        chunk_count=document.chunk_count,
        embedding_provider=document.embedding_provider,
        embedding_model=document.embedding_model,
        index_fingerprint=document.index_fingerprint,
        error_message=document.error_message,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.post(
    "/documents",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessResponse[DocumentAcceptedData],
)
async def upload_document(
    request: Request,
    file: UploadFile,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalStorageService, Depends(get_storage_service)],
    dispatcher: Annotated[TaskDispatcher, Depends(get_task_dispatcher)],
) -> SuccessResponse[DocumentAcceptedData]:
    repository = DocumentRepository(db)
    document_id = str(uuid4())
    original_filename = Path(file.filename or f"{document_id}.pdf").name.replace("\x00", "")[:255]
    if not original_filename:
        original_filename = f"{document_id}.pdf"
    stored = await storage.save_pdf(file, document_id)
    duplicate = repository.get_by_sha256(stored.sha256)
    if duplicate is not None:
        storage.delete(stored.path)
        raise AppError(
            message=f"This PDF is already registered as document {duplicate.id}.",
            code="DOCUMENT_DUPLICATE",
            status_code=status.HTTP_409_CONFLICT,
        )

    try:
        document = repository.add(
            Document(
                id=document_id,
                original_filename=original_filename,
                stored_path=str(stored.path),
                sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                status="pending",
            )
        )
    except IntegrityError as exc:
        storage.delete(stored.path)
        duplicate = repository.get_by_sha256(stored.sha256)
        duplicate_detail = f" as document {duplicate.id}" if duplicate is not None else ""
        raise AppError(
            message=f"This PDF was already registered{duplicate_detail}.",
            code="DOCUMENT_DUPLICATE",
            status_code=status.HTTP_409_CONFLICT,
        ) from exc
    try:
        task = dispatcher.enqueue_ingestion(document.id)
    except Exception as exc:
        repository.mark_failed(document, "Could not enqueue ingestion task.")
        raise AppError(
            message="The document was stored but ingestion could not be queued.",
            code="INGESTION_QUEUE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc

    return SuccessResponse(
        request_id=request.state.request_id,
        data=DocumentAcceptedData(document=to_document_data(document), task_id=task.id),
    )


@router.get("/documents", response_model=SuccessResponse[DocumentListData])
def list_documents(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> SuccessResponse[DocumentListData]:
    documents = [to_document_data(item) for item in DocumentRepository(db).list()]
    return SuccessResponse(
        request_id=request.state.request_id,
        data=DocumentListData(count=len(documents), documents=documents),
    )


@router.get("/documents/{document_id}", response_model=SuccessResponse[DocumentData])
def get_document(
    document_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
) -> SuccessResponse[DocumentData]:
    document = DocumentRepository(db).get(document_id)
    if document is None:
        raise AppError("Document not found.", "DOCUMENT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    return SuccessResponse(request_id=request.state.request_id, data=to_document_data(document))


@router.post(
    "/documents/{document_id}/reindex",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SuccessResponse[ReindexDocumentData],
)
def reindex_document(
    document_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    dispatcher: Annotated[TaskDispatcher, Depends(get_task_dispatcher)],
) -> SuccessResponse[ReindexDocumentData]:
    repository = DocumentRepository(db)
    document = repository.get(document_id)
    if document is None:
        raise AppError("Document not found.", "DOCUMENT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    repository.mark_pending(document)
    try:
        task = dispatcher.enqueue_ingestion(document.id)
    except Exception as exc:
        repository.mark_failed(document, "Could not enqueue reindexing task.")
        raise AppError(
            message="Reindexing could not be queued.",
            code="INGESTION_QUEUE_UNAVAILABLE",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        ) from exc
    return SuccessResponse(
        request_id=request.state.request_id,
        data=ReindexDocumentData(document_id=document.id, task_id=task.id),
    )


@router.delete(
    "/documents/{document_id}",
    response_model=SuccessResponse[DeleteDocumentData],
)
def delete_document(
    document_id: str,
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    storage: Annotated[LocalStorageService, Depends(get_storage_service)],
    vector_store: Annotated[QdrantVectorStore, Depends(get_vector_store)],
) -> SuccessResponse[DeleteDocumentData]:
    repository = DocumentRepository(db)
    document = repository.get(document_id)
    if document is None:
        raise AppError("Document not found.", "DOCUMENT_NOT_FOUND", status.HTTP_404_NOT_FOUND)
    vector_store.delete_document(document.id)
    storage.delete(document.stored_path)
    repository.delete(document)
    return SuccessResponse(
        request_id=request.state.request_id,
        data=DeleteDocumentData(document_id=document_id, deleted=True),
    )
