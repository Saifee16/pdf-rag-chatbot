import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from fastapi import UploadFile, status

from app.core.config import Settings
from app.core.exceptions import AppError


@dataclass(slots=True)
class StoredFile:
    path: Path
    size_bytes: int
    sha256: str


class LocalStorageService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.storage_dir = self.settings.storage_dir.resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    async def save_pdf(self, upload: UploadFile, document_id: str) -> StoredFile:
        import hashlib

        filename = upload.filename or ""
        if not filename.lower().endswith(".pdf"):
            raise AppError(
                message="Only .pdf files are accepted.",
                code="PDF_EXTENSION_REQUIRED",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        allowed_content_types = {"application/pdf", "application/octet-stream"}
        if upload.content_type and upload.content_type not in allowed_content_types:
            raise AppError(
                message="Only PDF uploads are accepted.",
                code="PDF_CONTENT_TYPE_INVALID",
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            )

        target = self.storage_dir / f"{document_id}.pdf"
        hasher = hashlib.sha256()
        total = 0
        first_bytes = b""
        temporary_path: Path | None = None

        try:
            with tempfile.NamedTemporaryFile(
                mode="wb", dir=self.storage_dir, prefix=".upload-", suffix=".tmp", delete=False
            ) as handle:
                temporary_path = Path(handle.name)
                while True:
                    chunk = await upload.read(1024 * 1024)
                    if not chunk:
                        break
                    if not first_bytes:
                        first_bytes = chunk[:5]
                    total += len(chunk)
                    if total > self.settings.max_pdf_size_bytes:
                        raise AppError(
                            message=f"PDF exceeds the {self.settings.max_pdf_size_mb} MB limit.",
                            code="PDF_TOO_LARGE",
                            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        )
                    hasher.update(chunk)
                    handle.write(chunk)

            if first_bytes != b"%PDF-":
                raise AppError(
                    message="The uploaded file does not contain a valid PDF signature.",
                    code="PDF_SIGNATURE_INVALID",
                    status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                )
            if total == 0:
                raise AppError(
                    message="The uploaded PDF is empty.",
                    code="PDF_EMPTY",
                    status_code=status.HTTP_400_BAD_REQUEST,
                )
            os.replace(temporary_path, target)
            temporary_path = None
        except Exception:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            raise
        finally:
            await upload.close()

        return StoredFile(path=target, size_bytes=total, sha256=hasher.hexdigest())

    def delete(self, path: str | Path) -> None:
        candidate = Path(path).resolve()
        if candidate.parent != self.storage_dir or candidate.suffix.lower() != ".pdf":
            return
        candidate.unlink(missing_ok=True)
