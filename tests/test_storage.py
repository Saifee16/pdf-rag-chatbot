from io import BytesIO
from pathlib import Path

import pytest
from fastapi import UploadFile

from app.core.config import get_settings
from app.core.exceptions import AppError
from app.services.storage_service import LocalStorageService


@pytest.mark.anyio
async def test_storage_accepts_real_pdf(tmp_path: Path, pdf_bytes: bytes) -> None:
    settings = get_settings().model_copy(update={"storage_dir": tmp_path, "max_pdf_size_mb": 1})
    storage = LocalStorageService(settings)
    upload = UploadFile(
        filename="report.pdf", file=BytesIO(pdf_bytes), headers={"content-type": "application/pdf"}
    )

    result = await storage.save_pdf(upload, "doc-1")

    assert result.path.exists()
    assert result.size_bytes == len(pdf_bytes)
    assert len(result.sha256) == 64


@pytest.mark.anyio
async def test_storage_rejects_fake_pdf_signature(tmp_path: Path) -> None:
    storage = LocalStorageService(get_settings().model_copy(update={"storage_dir": tmp_path}))
    upload = UploadFile(
        filename="fake.pdf", file=BytesIO(b"not a pdf"), headers={"content-type": "application/pdf"}
    )

    with pytest.raises(AppError) as error:
        await storage.save_pdf(upload, "doc-2")

    assert error.value.code == "PDF_SIGNATURE_INVALID"
    assert not (tmp_path / "doc-2.pdf").exists()


@pytest.mark.anyio
async def test_storage_rejects_non_pdf_extension(tmp_path: Path) -> None:
    storage = LocalStorageService(get_settings().model_copy(update={"storage_dir": tmp_path}))
    upload = UploadFile(filename="notes.txt", file=BytesIO(b"%PDF-test"))

    with pytest.raises(AppError) as error:
        await storage.save_pdf(upload, "doc-3")

    assert error.value.code == "PDF_EXTENSION_REQUIRED"


@pytest.mark.anyio
async def test_storage_delete_refuses_paths_outside_controlled_storage(tmp_path: Path) -> None:
    storage = LocalStorageService(
        get_settings().model_copy(update={"storage_dir": tmp_path / "uploads"})
    )
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"test")

    storage.delete(outside)

    assert outside.exists()
