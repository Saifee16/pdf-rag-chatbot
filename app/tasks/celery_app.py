from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "pdf_rag_chatbot",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.document_tasks"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    task_track_started=True,
    task_ignore_result=True,
    task_store_errors_even_if_ignored=False,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_always_eager=settings.celery_task_always_eager,
    task_soft_time_limit=600,
    task_time_limit=660,
)
