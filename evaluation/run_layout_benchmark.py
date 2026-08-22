from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path
from typing import Any

import pymupdf

from app.services.chunking_service import TextChunker
from app.services.pdf_service import PageText, PDFTextExtractor
from app.services.structured_extraction_service import (
    StructuredElement,
    StructuredExtractionService,
    StructuredPage,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "layout_benchmark.json"


class FixtureOCR:
    def __init__(self, outputs: dict[int, str]) -> None:
        self.outputs = outputs

    def extract_page(self, page, *, deadline: float, page_number: int) -> str:
        return self.outputs.get(page_number, "")


class PlainExtractionService:
    """Cycle-4-compatible native fallback used for the before comparison."""

    def extract_page(
        self, page: pymupdf.Page, *, page_number: int, native_text: str | None = None
    ) -> StructuredPage:
        text = native_text if native_text is not None else page.get_text("text", sort=True)
        text = text.strip()
        elements = [StructuredElement(text, "paragraph", 0)] if text else []
        return StructuredPage(page_number, text, elements, "native" if text else "empty")


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


def _draw_table(page: pymupdf.Page, rows: list[list[str]], *, y0: float = 180) -> None:
    x0, cell_width, cell_height = 50, 140, 36
    width = max(len(row) for row in rows)
    for column in range(width + 1):
        page.draw_line(
            (x0 + column * cell_width, y0),
            (x0 + column * cell_width, y0 + len(rows) * cell_height),
        )
    for row in range(len(rows) + 1):
        page.draw_line(
            (x0, y0 + row * cell_height),
            (x0 + width * cell_width, y0 + row * cell_height),
        )
    for row_index, row in enumerate(rows):
        for column_index, value in enumerate(row):
            if value:
                page.insert_text(
                    (x0 + column_index * cell_width + 8, y0 + row_index * cell_height + 24),
                    value,
                    fontsize=12,
                )


def _build_pdf(case: dict[str, Any]) -> bytes:
    kind = str(case["kind"])
    document = pymupdf.open()
    if kind == "simple":
        page = document.new_page()
        page.insert_text(
            (72, 72),
            "Response policy: respond within two business days.",
            fontsize=14,
        )
    elif kind == "two_column":
        page = document.new_page(width=600, height=700)
        for x, y, text in (
            (50, 120, "Left one: intake details."),
            (330, 120, "Right one: escalation contact."),
            (50, 190, "Left two: normal response."),
            (330, 190, "Right two: manager approval."),
        ):
            page.insert_text((x, y), text, fontsize=12)
    elif kind == "heading":
        page = document.new_page()
        page.insert_text((60, 70), str(case["heading"]), fontsize=20)
        page.insert_text(
            (60, 130),
            "Records under this retention section remain available for seven years.",
            fontsize=13,
        )
    elif kind in {"table", "key_value", "empty_cell", "table_limit"}:
        page = document.new_page(width=600, height=700)
        _draw_table(page, case["rows"])
    elif kind == "table_prose":
        page = document.new_page(width=600, height=700)
        page.insert_text((50, 110), "Plans are billed monthly.", fontsize=13)
        _draw_table(page, case["rows"], y0=180)
        page.insert_text((50, 360), "Contact support after reviewing the plans.", fontsize=13)
    elif kind == "repeated_headings":
        for page_number in (1, 2):
            page = document.new_page()
            page.insert_text((60, 70), str(case["heading"]), fontsize=20)
            page.insert_text(
                (60, 130),
                f"Page {['one', 'two'][page_number - 1]} controls describe deterministic safeguards.",
                fontsize=13,
            )
    elif kind == "mixed":
        page = document.new_page()
        page.insert_text((60, 70), "Native introduction.", fontsize=18)
        source = pymupdf.open()
        source_page = source.new_page()
        source_page.insert_text((60, 70), str(case["ocr_text"]), fontsize=18)
        image = source_page.get_pixmap(dpi=150, alpha=False).tobytes("png")
        source.close()
        scanned_page = document.new_page()
        scanned_page.insert_image(scanned_page.rect, stream=image)
    else:
        raise ValueError(f"Unsupported benchmark case kind: {kind}")
    content = document.tobytes()
    document.close()
    return content


def _extract(
    pdf_bytes: bytes,
    case: dict[str, Any],
    *,
    layout_aware: bool,
) -> tuple[list[PageText], float]:
    started = time.perf_counter()
    with pymupdf.open(stream=pdf_bytes, filetype="pdf") as document:
        ocr_outputs = {2: str(case.get("ocr_text", ""))} if case["kind"] == "mixed" else {}
        extractor = PDFTextExtractor(
            max_pages=10,
            ocr_service=FixtureOCR(ocr_outputs) if ocr_outputs else None,
            ocr_min_native_text_chars=32,
            structured_extractor=(
                StructuredExtractionService() if layout_aware else PlainExtractionService()
            ),
        )
        # PDFTextExtractor accepts a path for production safety. The benchmark
        # keeps its synthetic bytes in memory and applies the same page policy.
        pages: list[PageText] = []
        for index, page in enumerate(document):
            native_text = page.get_text("text", sort=True)
            if len(native_text.strip()) >= extractor.ocr_min_native_text_chars:
                structured = extractor.structured_extractor.extract_page(
                    page, page_number=index + 1, native_text=native_text
                )
                pages.append(
                    PageText(
                        page_number=index + 1,
                        text=structured.text or native_text,
                        extraction_method="native",
                        elements=structured.elements,
                    )
                )
                continue
            if extractor.ocr_service is not None:
                text = extractor.ocr_service.extract_page(
                    page, deadline=time.monotonic() + 60, page_number=index + 1
                )
                structured = StructuredExtractionService.ocr_page(index + 1, text)
                pages.append(
                    PageText(
                        page_number=index + 1,
                        text=text,
                        extraction_method="ocr" if text else "empty",
                        elements=structured.elements,
                    )
                )
            else:
                pages.append(
                    PageText(
                        page_number=index + 1,
                        text=native_text,
                        extraction_method="native" if native_text.strip() else "empty",
                    )
                )
    return pages, round((time.perf_counter() - started) * 1000, 3)


def _score(pages: list[PageText], case: dict[str, Any], *, top_k: int) -> dict[str, Any]:
    chunks = TextChunker(chunk_size=500, chunk_overlap=50).split(pages)
    query_tokens = _tokens(str(case["question"]))
    ranked = sorted(
        chunks,
        key=lambda chunk: (-len(query_tokens & _tokens(chunk.text)), chunk.chunk_index),
    )
    expected = _tokens(" ".join(str(term) for term in case["expected_terms"]))
    returned = ranked[:top_k]
    matched = next((chunk for chunk in returned if expected <= _tokens(chunk.text)), None)
    elements = [element for page in pages for element in page.elements]
    kind = str(case["kind"])
    structure = 0.0
    if kind in {"table", "table_prose", "key_value", "empty_cell", "table_limit"}:
        structure = float(
            any(element.content_type in {"table", "key_value"} for element in elements)
        )
    elif kind == "heading" or kind == "repeated_headings":
        structure = float(any(element.content_type == "heading" for element in elements))
    elif kind == "two_column":
        labels = [
            "left one",
            "left two",
            "right one",
            "right two",
        ]
        order = " ".join(element.text.lower() for element in elements)
        structure = float(
            all(
                order.find(label) < order.find(next_label)
                for label, next_label in zip(labels, labels[1:], strict=False)
            )
        )
    else:
        structure = float(bool(elements))
    expected_page = int(case["expected_page"])
    return {
        "extraction_success": bool(matched),
        "structured_content_preservation": round(structure, 6),
        "retrieval_recall_at_3": float(matched is not None),
        "citation_page_accuracy": float(
            matched is not None and matched.page_number == expected_page
        ),
        "table_answer_retrieval_accuracy": float(
            matched is not None
            and str(case["kind"])
            in {"table", "table_prose", "key_value", "empty_cell", "table_limit"}
        ),
        "chunk_count": len(chunks),
        "element_count": len(elements),
    }


def validate_fixture(fixture: dict[str, Any]) -> None:
    required = {
        "simple",
        "two_column",
        "heading",
        "table",
        "table_prose",
        "key_value",
        "repeated_headings",
        "mixed",
        "empty_cell",
        "table_limit",
    }
    kinds = {str(case["kind"]) for case in fixture["cases"]}
    missing = required - kinds
    if missing:
        raise ValueError(f"layout fixture missing cases: {sorted(missing)}")


def evaluate_fixture(fixture: dict[str, Any]) -> dict[str, Any]:
    validate_fixture(fixture)
    top_k = int(fixture["top_k"])
    scenarios: list[dict[str, Any]] = []
    for case in fixture["cases"]:
        pdf_bytes = _build_pdf(case)
        old_pages, old_latency = _extract(pdf_bytes, case, layout_aware=False)
        new_pages, new_latency = _extract(pdf_bytes, case, layout_aware=True)
        scenarios.append(
            {
                "id": case["id"],
                "kind": case["kind"],
                "old_extraction": _score(old_pages, case, top_k=top_k),
                "layout_aware_extraction": _score(new_pages, case, top_k=top_k),
                "old_ingestion_latency_ms": old_latency,
                "layout_ingestion_latency_ms": new_latency,
            }
        )
    return {
        "fixture_version": fixture["version"],
        "query_count": len(scenarios),
        "top_k": top_k,
        "scenarios": scenarios,
    }


def check_regression(report: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for scenario in report["scenarios"]:
        old = scenario["old_extraction"]
        new = scenario["layout_aware_extraction"]
        if new["retrieval_recall_at_3"] < old["retrieval_recall_at_3"]:
            errors.append(f"{scenario['id']}: layout retrieval recall regressed")
        if new["citation_page_accuracy"] < old["citation_page_accuracy"]:
            errors.append(f"{scenario['id']}: layout citation accuracy regressed")
    for kind in {"two_column", "table", "table_prose", "key_value", "heading"}:
        scenario = next(item for item in report["scenarios"] if item["kind"] == kind)
        if (
            scenario["layout_aware_extraction"]["structured_content_preservation"]
            <= scenario["old_extraction"]["structured_content_preservation"]
        ):
            errors.append(f"{scenario['id']}: structure did not improve")
    return errors


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate deterministic PDF layout extraction quality."
    )
    parser.add_argument("--fixture", type=Path, default=FIXTURE_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-regression", action="store_true")
    args = parser.parse_args()
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    report = evaluate_fixture(fixture)
    serialized = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")
    if args.check_regression:
        failures = check_regression(report)
        if failures:
            raise SystemExit("Layout extraction regression failed:\n" + "\n".join(failures))
        print("layout extraction regression: PASS")


if __name__ == "__main__":
    main()
