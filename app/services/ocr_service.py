from __future__ import annotations

import math
import re
import shutil
import subprocess  # nosec B404
import tempfile
from pathlib import Path
from time import monotonic

import pymupdf


class OCRTransientError(RuntimeError):
    """An OCR operation may succeed if the worker retries it."""


class OCRPermanentError(RuntimeError):
    """The document or local OCR configuration cannot be processed safely."""


class OCRService:
    """Run a local Tesseract process against one rendered PDF page at a time.

    The service deliberately accepts a PyMuPDF page rather than a user-provided
    path. It renders into a collision-safe temporary directory below the
    configured runtime storage directory and never sends document bytes over a
    network boundary.
    """

    MAX_IMAGE_PIXELS = 20_000_000
    MAX_OUTPUT_CHARS = 500_000
    _LANGUAGE_PATTERN = re.compile(r"^[A-Za-z0-9_+\-]+$")

    def __init__(
        self,
        *,
        executable: str,
        languages: str,
        dpi: int,
        timeout_seconds: float,
        storage_dir: Path,
    ) -> None:
        executable = executable.strip()
        if not executable or "\x00" in executable:
            raise ValueError("OCR executable must be a non-empty safe command name or path")
        self.executable = executable
        self.languages = self._normalize_languages(languages)
        self.dpi = dpi
        self.timeout_seconds = timeout_seconds
        self.storage_dir = storage_dir.resolve()
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def extract_page(self, page: pymupdf.Page, *, deadline: float, page_number: int) -> str:
        """Render and OCR one page, enforcing image, timeout, and output limits."""

        remaining = deadline - monotonic()
        if remaining <= 0:
            raise OCRTransientError("OCR document time limit exceeded")

        width, height = self._expected_dimensions(page)
        if width * height > self.MAX_IMAGE_PIXELS:
            raise OCRPermanentError("PDF page image dimensions exceed the OCR safety limit")

        try:
            pixmap = page.get_pixmap(dpi=self.dpi, alpha=False)
        except Exception as exc:
            raise OCRPermanentError("PDF page could not be rendered for OCR") from exc
        if pixmap.width * pixmap.height > self.MAX_IMAGE_PIXELS:
            raise OCRPermanentError("PDF page image dimensions exceed the OCR safety limit")

        executable = self._resolve_executable()
        timeout = min(self.timeout_seconds, remaining)
        try:
            with tempfile.TemporaryDirectory(prefix=".ocr-", dir=self.storage_dir) as directory:
                image_path = Path(directory) / f"page-{page_number}.png"
                pixmap.save(str(image_path))
                command = [
                    executable,
                    str(image_path),
                    "stdout",
                    "--dpi",
                    str(self.dpi),
                    "--psm",
                    "6",
                    "-l",
                    self.languages,
                ]
                try:
                    # The executable and all arguments are validated; shell execution is disabled.
                    result = subprocess.run(  # nosec B603
                        command,
                        check=False,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.DEVNULL,
                        text=True,
                        timeout=timeout,
                        shell=False,
                    )
                except subprocess.TimeoutExpired as exc:
                    raise OCRTransientError("OCR page time limit exceeded") from exc
                except OSError as exc:
                    raise OCRPermanentError("Local OCR executable could not be started") from exc
        except OCRTransientError:
            raise
        except OCRPermanentError:
            raise
        except Exception as exc:
            raise OCRPermanentError("OCR temporary-file processing failed") from exc

        if result.returncode != 0:
            raise OCRPermanentError("Local OCR failed to process the PDF page")
        if len(result.stdout) > self.MAX_OUTPUT_CHARS:
            raise OCRPermanentError("OCR output exceeds the configured safety limit")
        return self._normalize(result.stdout)

    def _resolve_executable(self) -> str:
        candidate = Path(self.executable)
        resolved = (
            str(candidate.resolve())
            if candidate.parent != Path(".")
            else shutil.which(self.executable)
        )
        if not resolved:
            raise OCRPermanentError("Local OCR executable is unavailable")
        return resolved

    def _expected_dimensions(self, page: pymupdf.Page) -> tuple[int, int]:
        rect = page.rect
        scale = self.dpi / 72.0
        width = math.ceil(max(0.0, float(rect.width)) * scale)
        height = math.ceil(max(0.0, float(rect.height)) * scale)
        if width <= 0 or height <= 0:
            raise OCRPermanentError("PDF page has invalid image dimensions")
        return width, height

    @classmethod
    def _normalize_languages(cls, languages: str) -> str:
        values = [item.strip() for item in languages.split(",") if item.strip()]
        if not values or any(not cls._LANGUAGE_PATTERN.fullmatch(item) for item in values):
            raise ValueError("OCR_LANGUAGES must contain safe language identifiers")
        return "+".join(values)

    @staticmethod
    def _normalize(text: str) -> str:
        return re.sub(r"\s+", " ", text.replace("\x00", " ")).strip()
