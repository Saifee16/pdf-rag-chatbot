from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Literal

import pymupdf

from app.core.exceptions import AppError
from app.services.ocr_service import OCRPermanentError, OCRService, OCRTransientError


@dataclass(slots=True)
class PageText:
    page_number: int
    text: str
    extraction_method: Literal["native", "ocr", "empty"] = "native"


class PDFTextExtractor:
    def __init__(
        self,
        max_pages: int,
        *,
        ocr_service: OCRService | None = None,
        ocr_min_native_text_chars: int = 32,
        ocr_max_pages: int = 50,
        ocr_document_timeout_seconds: float = 900.0,
    ) -> None:
        self.max_pages = max_pages
        self.ocr_service = ocr_service
        self.ocr_min_native_text_chars = ocr_min_native_text_chars
        self.ocr_max_pages = ocr_max_pages
        self.ocr_document_timeout_seconds = ocr_document_timeout_seconds

    def extract(self, path: str | Path) -> list[PageText]:
        pages: list[PageText] = []
        deadline = monotonic() + self.ocr_document_timeout_seconds
        ocr_pages = 0
        try:
            with pymupdf.open(path) as document:
                if document.is_encrypted:
                    raise AppError(
                        message="Password-protected PDFs are not supported.",
                        code="PDF_ENCRYPTED",
                        status_code=400,
                    )
                if document.page_count > self.max_pages:
                    raise AppError(
                        message="PDF exceeds the configured page limit.",
                        code="PDF_TOO_MANY_PAGES",
                        status_code=400,
                    )
                for index, page in enumerate(document):
                    native_text = page.get_text("text", sort=True)
                    if len(native_text.strip()) >= self.ocr_min_native_text_chars:
                        pages.append(
                            PageText(
                                page_number=index + 1,
                                text=native_text,
                                extraction_method="native",
                            )
                        )
                        continue

                    if self.ocr_service is None:
                        pages.append(
                            PageText(
                                page_number=index + 1,
                                text=native_text,
                                extraction_method="native" if native_text.strip() else "empty",
                            )
                        )
                        continue

                    if ocr_pages >= self.ocr_max_pages:
                        raise AppError(
                            message="The PDF exceeds the configured OCR page limit.",
                            code="OCR_TOO_MANY_PAGES",
                            status_code=400,
                        )
                    try:
                        text = self.ocr_service.extract_page(
                            page,
                            deadline=deadline,
                            page_number=index + 1,
                        )
                    except OCRTransientError:
                        raise
                    except OCRPermanentError as exc:
                        raise AppError(
                            message="The scanned PDF could not be processed by local OCR.",
                            code="OCR_FAILED",
                            status_code=400,
                        ) from exc
                    ocr_pages += 1
                    pages.append(
                        PageText(
                            page_number=index + 1,
                            text=text,
                            extraction_method="ocr" if text else "empty",
                        )
                    )
        except AppError:
            raise
        except OCRTransientError:
            raise
        except Exception as exc:
            raise AppError(
                message="The uploaded PDF could not be parsed.",
                code="PDF_PARSE_FAILED",
                status_code=400,
            ) from exc
        return pages
