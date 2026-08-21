import pytest
from httpx import AsyncClient

from tests.fakes import FakeTaskDispatcher


@pytest.mark.anyio
async def test_upload_list_get_delete_document(
    client: AsyncClient,
    pdf_bytes: bytes,
    fake_dispatcher: FakeTaskDispatcher,
) -> None:
    upload = await client.post(
        "/api/v1/documents",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
    )
    assert upload.status_code == 202
    document = upload.json()["data"]["document"]
    document_id = document["id"]
    assert document["status"] == "pending"
    assert fake_dispatcher.document_ids == [document_id]

    listing = await client.get("/api/v1/documents")
    assert listing.status_code == 200
    assert listing.json()["data"]["count"] == 1

    fetched = await client.get(f"/api/v1/documents/{document_id}")
    assert fetched.status_code == 200
    assert fetched.json()["data"]["sha256"] == document["sha256"]

    deleted = await client.delete(f"/api/v1/documents/{document_id}")
    assert deleted.status_code == 200
    assert deleted.json()["data"]["deleted"] is True


@pytest.mark.anyio
async def test_duplicate_upload_is_rejected(client: AsyncClient, pdf_bytes: bytes) -> None:
    first = await client.post(
        "/api/v1/documents",
        files={"file": ("first.pdf", pdf_bytes, "application/pdf")},
    )
    assert first.status_code == 202

    duplicate = await client.post(
        "/api/v1/documents",
        files={"file": ("same.pdf", pdf_bytes, "application/pdf")},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "DOCUMENT_DUPLICATE"


@pytest.mark.anyio
async def test_upload_strips_path_from_original_filename(
    client: AsyncClient, pdf_bytes: bytes
) -> None:
    response = await client.post(
        "/api/v1/documents",
        files={"file": ("../../report.pdf", pdf_bytes, "application/pdf")},
    )

    assert response.status_code == 202
    assert response.json()["data"]["document"]["original_filename"] == "report.pdf"


@pytest.mark.anyio
async def test_get_missing_document_returns_404(client: AsyncClient) -> None:
    response = await client.get("/api/v1/documents/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


@pytest.mark.anyio
async def test_reindex_queues_document(
    client: AsyncClient,
    pdf_bytes: bytes,
    fake_dispatcher: FakeTaskDispatcher,
) -> None:
    uploaded = await client.post(
        "/api/v1/documents",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
    )
    document_id = uploaded.json()["data"]["document"]["id"]

    response = await client.post(f"/api/v1/documents/{document_id}/reindex")

    assert response.status_code == 202
    assert response.json()["data"]["status"] == "pending"
    assert fake_dispatcher.document_ids == [document_id, document_id]


@pytest.mark.anyio
async def test_reindex_queue_failure_marks_document_failed(
    client: AsyncClient,
    pdf_bytes: bytes,
    fake_dispatcher: FakeTaskDispatcher,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    uploaded = await client.post(
        "/api/v1/documents",
        files={"file": ("report.pdf", pdf_bytes, "application/pdf")},
    )
    document_id = uploaded.json()["data"]["document"]["id"]

    def fail_dispatch(document_id: str):
        raise RuntimeError(f"queue down for {document_id}")

    monkeypatch.setattr(fake_dispatcher, "enqueue_ingestion", fail_dispatch)

    response = await client.post(f"/api/v1/documents/{document_id}/reindex")

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "INGESTION_QUEUE_UNAVAILABLE"

    document = await client.get(f"/api/v1/documents/{document_id}")
    assert document.json()["data"]["status"] == "failed"
