from __future__ import annotations

import subprocess
from pathlib import Path

import pymupdf
import pytest
from fastapi import status

from app.core.config import Settings
from app.core.exceptions import AppError
from app.db.models import Document
from app.repositories.document_repository import DocumentRepository
from app.services.ingestion_service import IngestionService
from app.services.ocr_service import OCRPermanentError, OCRService, OCRTransientError
from app.services.pdf_service import PDFTextExtractor
from app.services.retrieval_service import RetrievalService
from tests.fakes import FakeEmbeddingProvider, FakeVectorStore


def _native_pdf(text: str, *, pages: int = 1) -> bytes:
    document = pymupdf.open()
    for _ in range(pages):
        page = document.new_page()
        page.insert_textbox(page.rect + (48, 48, -48, -48), text, fontsize=18)
    content = document.tobytes()
    document.close()
    return content


def _image_pdf(texts: list[str | None]) -> bytes:
    source = pymupdf.open()
    pixmaps: list[bytes] = []
    for text in texts:
        source_page = source.new_page()
        if text:
            source_page.insert_textbox(source_page.rect + (48, 48, -48, -48), text, fontsize=18)
        pixmaps.append(source_page.get_pixmap(dpi=150, alpha=False).tobytes("png"))
    source.close()

    scanned = pymupdf.open()
    for image in pixmaps:
        page = scanned.new_page()
        page.insert_image(page.rect, stream=image)
    content = scanned.tobytes()
    scanned.close()
    return content


class FakeOCR:
    def __init__(self, outputs: dict[int, str]) -> None:
        self.outputs = outputs
        self.calls: list[int] = []

    def extract_page(self, page: pymupdf.Page, *, deadline: float, page_number: int) -> str:
        self.calls.append(page_number)
        return self.outputs.get(page_number, "")


def test_native_pdf_uses_existing_extraction_without_ocr(tmp_path: Path) -> None:
    path = tmp_path / "native.pdf"
    path.write_bytes(_native_pdf("Native policy text is intentionally long enough."))
    ocr = FakeOCR({1: "should not be used"})

    pages = PDFTextExtractor(
        max_pages=5,
        ocr_service=ocr,  # type: ignore[arg-type]
        ocr_min_native_text_chars=16,
    ).extract(path)

    assert pages[0].text.startswith("Native policy")
    assert pages[0].extraction_method == "native"
    assert ocr.calls == []


def test_image_only_pdf_uses_page_ocr_and_preserves_page_number(tmp_path: Path) -> None:
    path = tmp_path / "scanned.pdf"
    path.write_bytes(_image_pdf(["Scanned retention policy: keep records for 90 days."]))
    ocr = FakeOCR({1: "Scanned retention policy: keep records for 90 days."})

    pages = PDFTextExtractor(
        max_pages=5,
        ocr_service=ocr,  # type: ignore[arg-type]
        ocr_min_native_text_chars=16,
    ).extract(path)

    assert pages[0].page_number == 1
    assert pages[0].extraction_method == "ocr"
    assert "90 days" in pages[0].text
    assert ocr.calls == [1]


def test_mixed_pdf_ocr_only_processes_inadequate_pages(tmp_path: Path) -> None:
    native = _native_pdf("Native page: response within two business days.")
    native_document = pymupdf.open(stream=native, filetype="pdf")
    native_page = native_document[0]
    native_pixmap = native_page.get_pixmap(dpi=150, alpha=False).tobytes("png")
    native_document.close()

    mixed = pymupdf.open()
    page_one = mixed.new_page()
    page_one.insert_textbox(
        page_one.rect + (48, 48, -48, -48),
        "Native page: response within two business days.",
        fontsize=18,
    )
    page_two = mixed.new_page()
    page_two.insert_image(page_two.rect, stream=native_pixmap)
    path = tmp_path / "mixed.pdf"
    path.write_bytes(mixed.tobytes())
    mixed.close()
    ocr = FakeOCR({2: "Scanned page: escalation requires manager approval."})

    pages = PDFTextExtractor(
        max_pages=5,
        ocr_service=ocr,  # type: ignore[arg-type]
        ocr_min_native_text_chars=16,
    ).extract(path)

    assert [page.extraction_method for page in pages] == ["native", "ocr"]
    assert "manager approval" in pages[1].text
    assert ocr.calls == [2]


def test_blank_scanned_page_is_safe_empty_page(tmp_path: Path) -> None:
    path = tmp_path / "blank-scan.pdf"
    path.write_bytes(_image_pdf([None]))
    ocr = FakeOCR({1: ""})

    pages = PDFTextExtractor(max_pages=5, ocr_service=ocr).extract(path)  # type: ignore[arg-type]

    assert pages[0].page_number == 1
    assert pages[0].text == ""
    assert pages[0].extraction_method == "empty"


def test_malformed_pdf_fails_without_ocr_output(tmp_path: Path) -> None:
    path = tmp_path / "malformed.pdf"
    path.write_bytes(b"%PDF-1.7\nnot a valid document")

    with pytest.raises(AppError) as error:
        PDFTextExtractor(max_pages=5).extract(path)

    assert error.value.code == "PDF_PARSE_FAILED"
    assert "not a valid" not in error.value.message


def test_ocr_page_limit_is_a_permanent_document_failure(tmp_path: Path) -> None:
    path = tmp_path / "too-many-scanned-pages.pdf"
    path.write_bytes(_image_pdf([None, None]))
    ocr = FakeOCR({1: "page one"})

    with pytest.raises(AppError) as error:
        PDFTextExtractor(
            max_pages=5,
            ocr_service=ocr,  # type: ignore[arg-type]
            ocr_max_pages=1,
        ).extract(path)

    assert error.value.code == "OCR_TOO_MANY_PAGES"
    assert error.value.status_code == status.HTTP_400_BAD_REQUEST
    assert ocr.calls == [1]


def test_ocr_service_uses_safe_subprocess_and_cleans_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = pymupdf.open(stream=_image_pdf(["Synthetic OCR page"]), filetype="pdf")
    page = document[0]
    calls: list[dict[str, object]] = []

    monkeypatch.setattr("app.services.ocr_service.shutil.which", lambda _: "tesseract")

    def fake_run(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return subprocess.CompletedProcess(command, 0, stdout="Synthetic OCR output", stderr="")

    monkeypatch.setattr("app.services.ocr_service.subprocess.run", fake_run)
    service = OCRService(
        executable="tesseract",
        languages="eng",
        dpi=150,
        timeout_seconds=5,
        storage_dir=tmp_path,
    )

    assert service.extract_page(page, deadline=10**12, page_number=1) == "Synthetic OCR output"
    assert calls[0]["shell"] is False
    assert calls[0]["timeout"] == 5
    assert "-l" in calls[0]["command"]
    assert list(tmp_path.glob(".ocr-*")) == []
    document.close()


def test_ocr_timeout_is_retryable_and_cleans_temp_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = pymupdf.open(stream=_image_pdf(["Synthetic OCR page"]), filetype="pdf")
    page = document[0]
    monkeypatch.setattr("app.services.ocr_service.shutil.which", lambda _: "tesseract")

    def timeout_run(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr("app.services.ocr_service.subprocess.run", timeout_run)
    service = OCRService(
        executable="tesseract",
        languages="eng",
        dpi=150,
        timeout_seconds=5,
        storage_dir=tmp_path,
    )

    with pytest.raises(OCRTransientError):
        service.extract_page(page, deadline=10**12, page_number=1)
    assert list(tmp_path.glob(".ocr-*")) == []
    document.close()


def test_ocr_engine_failure_is_permanent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    document = pymupdf.open(stream=_image_pdf(["Synthetic OCR page"]), filetype="pdf")
    page = document[0]
    monkeypatch.setattr("app.services.ocr_service.shutil.which", lambda _: "tesseract")
    monkeypatch.setattr(
        "app.services.ocr_service.subprocess.run",
        lambda command, **kwargs: subprocess.CompletedProcess(
            command, 1, stdout="", stderr="engine failed"
        ),
    )
    service = OCRService(
        executable="tesseract",
        languages="eng",
        dpi=150,
        timeout_seconds=5,
        storage_dir=tmp_path,
    )

    with pytest.raises(OCRPermanentError):
        service.extract_page(page, deadline=10**12, page_number=1)
    document.close()


def test_image_only_ingestion_creates_retrievable_page_chunk(
    tmp_path: Path, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FakeIngestionOCR(FakeOCR):
        pass

    monkeypatch.setattr(
        "app.services.ingestion_service.OCRService",
        lambda **_: FakeIngestionOCR({1: "Scanned answer exists on page one."}),
    )
    path = tmp_path / "scanned.pdf"
    path.write_bytes(_image_pdf(["Scanned answer exists on page one."]))
    document = DocumentRepository(db_session).add(
        Document(
            original_filename="scanned.pdf",
            stored_path=str(path),
            sha256="c" * 64,
            size_bytes=path.stat().st_size,
            status="pending",
        )
    )
    settings = Settings(
        _env_file=None,
        OCR_ENABLED=True,
        STORAGE_DIR=tmp_path / "runtime",
        CHUNK_SIZE=300,
        CHUNK_OVERLAP=50,
    )
    vector_store = FakeVectorStore()

    IngestionService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
    ).ingest(document.id)

    refreshed = DocumentRepository(db_session).get(document.id)
    assert refreshed is not None
    assert refreshed.status == "ready"
    assert refreshed.page_count == 1
    assert refreshed.chunk_count == 1
    assert vector_store.points
    assert next(iter(vector_store.points.values())).payload["page_number"] == 1


def test_ocr_chunk_runs_through_dense_retrieval_and_abstention_contract(
    tmp_path: Path, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "app.services.ingestion_service.OCRService",
        lambda **_: FakeOCR({1: "Scanned answer exists on page one."}),
    )
    path = tmp_path / "retrieval-scanned.pdf"
    path.write_bytes(_image_pdf(["Scanned answer exists on page one."]))
    document = DocumentRepository(db_session).add(
        Document(
            original_filename="retrieval-scanned.pdf",
            stored_path=str(path),
            sha256="d" * 64,
            size_bytes=path.stat().st_size,
            status="pending",
        )
    )
    settings = Settings(
        _env_file=None,
        OCR_ENABLED=True,
        STORAGE_DIR=tmp_path / "runtime",
        RETRIEVAL_SCORE_THRESHOLD=0.0,
        RETRIEVAL_ABSTENTION_ENABLED=False,
    )
    vector_store = FakeVectorStore()
    ingestion = IngestionService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,
    )
    ingestion.ingest(document.id)

    result = RetrievalService(
        db=db_session,
        settings=settings,
        embedding_provider=FakeEmbeddingProvider(),
        vector_store=vector_store,  # type: ignore[arg-type]
    ).retrieve(
        query="What scanned answer exists?",
        document_ids=[document.id],
        top_k=3,
        score_threshold=0.0,
        mode="dense",
    )

    assert result.abstained is False
    assert result.hits
    assert result.hits[0].payload["page_number"] == 1


def test_transient_ocr_failure_is_retryable_before_vectors_are_written(
    tmp_path: Path, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TransientOCR(FakeOCR):
        def extract_page(self, page, *, deadline: float, page_number: int) -> str:
            raise OCRTransientError("synthetic timeout")

    monkeypatch.setattr(
        "app.services.ingestion_service.OCRService",
        lambda **_: TransientOCR({}),
    )
    path = tmp_path / "retryable-scan.pdf"
    path.write_bytes(_image_pdf(["Retryable OCR page"]))
    document = DocumentRepository(db_session).add(
        Document(
            original_filename="retryable-scan.pdf",
            stored_path=str(path),
            sha256="e" * 64,
            size_bytes=path.stat().st_size,
            status="pending",
        )
    )
    settings = Settings(_env_file=None, OCR_ENABLED=True, STORAGE_DIR=tmp_path / "runtime")
    vector_store = FakeVectorStore()

    with pytest.raises(RuntimeError, match="Transient local OCR failure"):
        IngestionService(
            db=db_session,
            settings=settings,
            embedding_provider=FakeEmbeddingProvider(),
            vector_store=vector_store,
        ).ingest(document.id)

    assert vector_store.points == {}


def test_vector_state_is_removed_when_upsert_fails_after_partial_write(
    tmp_path: Path, db_session, monkeypatch: pytest.MonkeyPatch
) -> None:
    class PartialFailureVectorStore(FakeVectorStore):
        def upsert(self, points):
            self.points[points[0].id] = points[0]
            raise RuntimeError("synthetic vector failure")

    monkeypatch.setattr(
        "app.services.ingestion_service.OCRService",
        lambda **_: FakeOCR({1: "Scanned page survives extraction."}),
    )
    path = tmp_path / "partial-vector-scan.pdf"
    path.write_bytes(_image_pdf(["Scanned page survives extraction."]))
    document = DocumentRepository(db_session).add(
        Document(
            original_filename="partial-vector-scan.pdf",
            stored_path=str(path),
            sha256="f" * 64,
            size_bytes=path.stat().st_size,
            status="pending",
        )
    )
    settings = Settings(_env_file=None, OCR_ENABLED=True, STORAGE_DIR=tmp_path / "runtime")
    vector_store = PartialFailureVectorStore()

    with pytest.raises(RuntimeError, match="synthetic vector failure"):
        IngestionService(
            db=db_session,
            settings=settings,
            embedding_provider=FakeEmbeddingProvider(),
            vector_store=vector_store,
        ).ingest(document.id)

    assert vector_store.points == {}
