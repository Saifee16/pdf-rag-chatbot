from __future__ import annotations

import argparse
import json
import re
import tempfile
import time
from pathlib import Path

import pymupdf

from app.core.config import Settings
from app.core.exceptions import AppError
from app.services.chunking_service import TextChunker
from app.services.ocr_service import OCRService
from app.services.pdf_service import PDFTextExtractor

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "ocr_benchmark.json"


class FixtureOCR:
    """Deterministic local OCR adapter used when real Tesseract is not requested."""

    def __init__(self, outputs: dict[int, str]) -> None:
        self.outputs = outputs

    def extract_page(self, page, *, deadline: float, page_number: int) -> str:
        return self.outputs.get(page_number, "")


def _build_pdf(case: dict[str, object]) -> bytes:
    fixture_type = str(case["fixture_type"])
    source_text = str(case.get("source_text", ""))
    if fixture_type == "malformed_image_only":
        return b"%PDF-1.7\nmalformed synthetic fixture"

    if fixture_type == "native_text":
        document = pymupdf.open()
        page = document.new_page()
        page.insert_textbox(page.rect + (48, 48, -48, -48), source_text, fontsize=24)
        content = document.tobytes()
        document.close()
        return content

    source = pymupdf.open()
    source_page = source.new_page()
    if source_text and fixture_type != "blank_scanned":
        source_page.insert_textbox(source_page.rect + (48, 48, -48, -48), source_text, fontsize=24)
    image = source_page.get_pixmap(dpi=150, alpha=False).tobytes("png")
    source.close()

    scanned = pymupdf.open()
    if fixture_type == "mixed":
        native_page = scanned.new_page()
        native_page.insert_textbox(
            native_page.rect + (48, 48, -48, -48),
            "Native page: response within two business days.",
            fontsize=24,
        )
    scanned_page = scanned.new_page()
    scanned_page.insert_image(scanned_page.rect, stream=image)
    if fixture_type == "ocr_page_limit":
        second_page = scanned.new_page()
        second_page.insert_image(second_page.rect, stream=image)
    content = scanned.tobytes()
    scanned.close()
    return content


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _run_case(case: dict[str, object], *, real_ocr: bool) -> dict[str, object]:
    started = time.perf_counter()
    fixture_type = str(case["fixture_type"])
    source_text = str(case.get("source_text", ""))
    with tempfile.TemporaryDirectory(prefix="ocr-benchmark-") as directory:
        root = Path(directory)
        pdf_path = root / f"{case['id']}.pdf"
        pdf_path.write_bytes(_build_pdf(case))
        if real_ocr:
            settings = Settings(_env_file=None, STORAGE_DIR=root, OCR_DPI=200)
            ocr = OCRService(
                executable=settings.ocr_executable,
                languages=settings.ocr_languages,
                dpi=settings.ocr_dpi,
                timeout_seconds=settings.ocr_timeout_seconds,
                storage_dir=root,
            )
        else:
            outputs = {1: source_text}
            if fixture_type == "mixed":
                outputs = {2: source_text}
            ocr = FixtureOCR(outputs)

        extractor = PDFTextExtractor(
            max_pages=5,
            ocr_service=ocr,
            ocr_min_native_text_chars=32,
            ocr_max_pages=1 if fixture_type == "ocr_page_limit" else 5,
        )
        try:
            pages = extractor.extract(pdf_path)
            chunks = TextChunker(chunk_size=500, chunk_overlap=50).split(pages)
            query_tokens = _tokens(str(case.get("question", "")))
            ranked = sorted(
                chunks,
                key=lambda chunk: (-len(query_tokens & _tokens(chunk.text)), chunk.chunk_index),
            )
            expected_keywords = set(case.get("expected_keywords", []))
            expected_page = case.get("expected_page")
            returned = ranked[:3]
            matched = next(
                (chunk for chunk in returned if expected_keywords.issubset(_tokens(chunk.text))),
                None,
            )
            extraction_success = (
                bool(matched)
                if expected_keywords
                else (fixture_type == "blank_scanned" and not any(page.text for page in pages))
            )
            citation_accuracy = (
                float(matched is not None and matched.page_number == expected_page)
                if expected_page is not None
                else None
            )
            error_code = None
            result = {
                "id": case["id"],
                "fixture_type": fixture_type,
                "extraction_success": extraction_success,
                "retrieval_recall_at_3": float(matched is not None) if expected_keywords else None,
                "citation_page_accuracy": citation_accuracy,
                "page_count": len(pages),
                "chunk_count": len(chunks),
                "error_code": error_code,
            }
        except AppError as exc:
            result = {
                "id": case["id"],
                "fixture_type": fixture_type,
                "extraction_success": False,
                "retrieval_recall_at_3": None,
                "citation_page_accuracy": None,
                "page_count": 0,
                "chunk_count": 0,
                "error_code": exc.code,
            }
    result["ingestion_latency_ms"] = round((time.perf_counter() - started) * 1000, 3)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate safe synthetic OCR extraction and retrieval."
    )
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--real-ocr",
        action="store_true",
        help="Use the local Tesseract executable instead of the deterministic fixture adapter.",
    )
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    results = [_run_case(case, real_ocr=args.real_ocr) for case in fixture]
    scored = [item for item in results if item["retrieval_recall_at_3"] is not None]
    try:
        fixture_display = args.fixture.resolve().relative_to(Path.cwd().resolve()).as_posix()
    except ValueError:
        fixture_display = args.fixture.as_posix()
    report = {
        "fixture": fixture_display,
        "engine": "tesseract" if args.real_ocr else "deterministic_fixture_adapter",
        "query_count": len(fixture),
        "extraction_success_rate": round(
            sum(bool(item["extraction_success"]) for item in results) / len(results), 6
        ),
        "retrieval_recall_at_3": round(
            sum(float(item["retrieval_recall_at_3"]) for item in scored) / len(scored), 6
        ),
        "citation_page_accuracy": round(
            sum(float(item["citation_page_accuracy"]) for item in scored) / len(scored), 6
        ),
        "ocr_ingestion_latency_p50_ms": round(
            sorted(float(item["ingestion_latency_ms"]) for item in results)[len(results) // 2], 3
        ),
        "cases": results,
    }
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    main()
