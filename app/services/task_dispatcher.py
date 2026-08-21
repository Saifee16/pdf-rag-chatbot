from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class DispatchedTask:
    id: str


class TaskDispatcher(Protocol):
    def enqueue_ingestion(self, document_id: str) -> DispatchedTask: ...


class CeleryTaskDispatcher:
    def enqueue_ingestion(self, document_id: str) -> DispatchedTask:
        from app.tasks.document_tasks import ingest_document

        result = ingest_document.delay(document_id)
        return DispatchedTask(id=result.id)


def get_task_dispatcher() -> TaskDispatcher:
    return CeleryTaskDispatcher()
