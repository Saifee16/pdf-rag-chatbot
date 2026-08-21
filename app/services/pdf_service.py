from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.core.exceptions import AppError


@dataclass(slots=True)
class PageText:
    page_number: int
    text: str


class PDFTextExtractor:
    def __init__(self, max_pages: int) -> None:
        self.max_pages = max_pages

    def extract(self, path: str | Path) -> list[PageText]:
        pages: list[PageText] = []
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
                    text = page.get_text("text", sort=True)
                    pages.append(PageText(page_number=index + 1, text=text))
        except AppError:
            raise
        except Exception as exc:
            raise AppError(
                message="The uploaded PDF could not be parsed.",
                code="PDF_PARSE_FAILED",
                status_code=400,
            ) from exc
        return pages
