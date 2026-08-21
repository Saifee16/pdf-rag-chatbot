import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.db.database import engine
from app.main import app


@pytest.mark.anyio
async def test_health_returns_request_and_security_headers(client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/health",
        headers={"X-Request-ID": "contract-test-request"},
    )

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "contract-test-request"
    assert float(response.headers["X-Response-Time-Ms"]) >= 0
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert response.headers["Referrer-Policy"] == "no-referrer"


def test_openapi_contains_exact_public_api_contract() -> None:
    expected = {
        ("GET", "/api/v1/health"),
        ("GET", "/api/v1/ready"),
        ("GET", "/api/v1/index/info"),
        ("POST", "/api/v1/documents"),
        ("GET", "/api/v1/documents"),
        ("GET", "/api/v1/documents/{document_id}"),
        ("POST", "/api/v1/documents/{document_id}/reindex"),
        ("DELETE", "/api/v1/documents/{document_id}"),
        ("POST", "/api/v1/retrieval/search"),
        ("POST", "/api/v1/chat"),
        ("GET", "/api/v1/conversations"),
        ("GET", "/api/v1/conversations/{conversation_id}"),
        ("DELETE", "/api/v1/conversations/{conversation_id}"),
    }
    schema = app.openapi()
    actual = {
        (method.upper(), path)
        for path, operations in schema["paths"].items()
        for method in operations
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }

    assert actual == expected


def test_application_sqlite_engine_enables_foreign_keys() -> None:
    with engine.connect() as connection:
        enabled = connection.execute(text("PRAGMA foreign_keys")).scalar_one()

    assert enabled == 1
