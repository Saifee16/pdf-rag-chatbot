from celery import Task

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.db.database import SessionLocal
from app.providers.registry import get_provider_registry
from app.repositories.document_repository import DocumentRepository
from app.services.ingestion_service import IngestionService, PermanentIngestionError
from app.services.vector_store import QdrantVectorStore
from app.tasks.celery_app import celery_app

logger = get_logger(__name__)


@celery_app.task(bind=True, max_retries=3, name="documents.ingest")
def ingest_document(self: Task, document_id: str) -> None:
    setup_logging()
    settings = get_settings()
    db = SessionLocal()
    documents = DocumentRepository(db)

    try:
        registry = get_provider_registry()
        service = IngestionService(
            db=db,
            settings=settings,
            embedding_provider=registry.embeddings(),
            vector_store=QdrantVectorStore(settings),
        )
        service.ingest(document_id)
    except PermanentIngestionError as exc:
        document = documents.get(document_id)
        if document is not None:
            documents.mark_failed(document, str(exc))
        logger.warning("Permanent ingestion failure document=%s error=%s", document_id, exc)
        raise
    except Exception as exc:
        logger.exception("Retryable ingestion failure document=%s", document_id)
        if self.request.retries >= self.max_retries:
            document = documents.get(document_id)
            if document is not None:
                documents.mark_failed(
                    document,
                    "Ingestion failed after retries. Check worker logs using the document ID.",
                )
            raise
        countdown = min(60, 2**self.request.retries)
        raise self.retry(exc=exc, countdown=countdown) from exc
    finally:
        db.close()
