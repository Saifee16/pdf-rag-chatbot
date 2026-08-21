import pytest
from httpx import AsyncClient

from app.core.config import get_settings


@pytest.mark.anyio
async def test_protected_route_requires_api_key_when_enabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "api_keys", "secret-key")

    unauthorized = await client.get("/api/v1/documents")
    assert unauthorized.status_code == 401
    assert unauthorized.json()["error"]["code"] == "INVALID_API_KEY"

    authorized = await client.get("/api/v1/documents", headers={"X-API-Key": "secret-key"})
    assert authorized.status_code == 200


@pytest.mark.anyio
async def test_health_remains_public_when_auth_enabled(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "api_auth_enabled", True)
    monkeypatch.setattr(settings, "api_keys", "secret-key")

    response = await client.get("/api/v1/health")
    assert response.status_code == 200


@pytest.mark.anyio
async def test_invalid_request_id_is_replaced(client: AsyncClient) -> None:
    response = await client.get("/api/v1/health", headers={"X-Request-ID": "invalid id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "invalid id"
