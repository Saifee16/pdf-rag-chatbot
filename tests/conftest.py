import os
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

os.environ.update(
    {
        "APP_ENV": "local",
        "APP_DEBUG": "false",
        "DATABASE_URL": "sqlite:///./test-placeholder.db",
        "REDIS_URL": "redis://localhost:6379/15",
        "QDRANT_URL": "http://localhost:6333",
        "CHAT_PROVIDER": "gemini",
        "EMBEDDING_PROVIDER": "gemini",
        "CHAT_MODEL": "fake-chat-v1",
        "EMBEDDING_MODEL": "fake-embedding-v1",
        "GEMINI_API_KEY": "test-key",
        "API_AUTH_ENABLED": "false",
        "CELERY_TASK_ALWAYS_EAGER": "true",
        "RAG_SYSTEM_PROMPT_PATH": str(
            Path(__file__).resolve().parents[1] / "prompts" / "rag_system.txt"
        ),
    }
)

import pymupdf
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import get_settings
from app.db.base import Base
from app.db.database import get_db
from app.dependencies import get_storage_service, get_vector_store
from app.main import app
from app.providers.registry import get_provider_registry
from app.services.storage_service import LocalStorageService
from app.services.task_dispatcher import get_task_dispatcher
from tests.fakes import FakeRegistry, FakeTaskDispatcher, FakeVectorStore


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def db_session() -> Iterator[Session]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestingSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = TestingSession()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)
        engine.dispose()


@pytest.fixture
def fake_registry() -> FakeRegistry:
    return FakeRegistry()


@pytest.fixture
def fake_vector_store() -> FakeVectorStore:
    return FakeVectorStore()


@pytest.fixture
def fake_dispatcher() -> FakeTaskDispatcher:
    return FakeTaskDispatcher(document_ids=[])


@pytest.fixture
def pdf_bytes() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text(
        (72, 72),
        "Revenue policy: qualified leads receive a response within two business days. "
        "The RAG system cites source pages.",
    )
    content = document.tobytes()
    document.close()
    return content


@pytest.fixture
async def client(
    tmp_path: Path,
    db_session: Session,
    fake_registry: FakeRegistry,
    fake_vector_store: FakeVectorStore,
    fake_dispatcher: FakeTaskDispatcher,
) -> AsyncIterator[AsyncClient]:
    settings = get_settings()
    storage = LocalStorageService(settings.model_copy(update={"storage_dir": tmp_path / "uploads"}))

    def override_db() -> Iterator[Session]:
        yield db_session

    app.dependency_overrides[get_db] = override_db
    app.dependency_overrides[get_provider_registry] = lambda: fake_registry
    app.dependency_overrides[get_vector_store] = lambda: fake_vector_store
    app.dependency_overrides[get_storage_service] = lambda: storage
    app.dependency_overrides[get_task_dispatcher] = lambda: fake_dispatcher

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client

    app.dependency_overrides.clear()
