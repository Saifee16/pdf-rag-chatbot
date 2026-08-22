from pathlib import Path

import pymupdf
import pytest

from app.services.chunking_service import TextChunker
from app.services.pdf_service import PageText
from app.services.structured_extraction_service import (
    StructuredElement,
    StructuredExtractionService,
)


def _two_column_page() -> pymupdf.Document:
    document = pymupdf.open()
    page = document.new_page(width=600, height=700)
    for x, y, text in (
        (50, 120, "Left column first paragraph."),
        (50, 190, "Left column second paragraph."),
        (330, 120, "Right column first paragraph."),
        (330, 190, "Right column second paragraph."),
    ):
        page.insert_text((x, y), text, fontsize=12)
    return document


def _ruled_table_page(rows: list[list[str]]) -> pymupdf.Document:
    document = pymupdf.open()
    page = document.new_page(width=600, height=700)
    x0, y0, cell_width, cell_height = 50, 150, 140, 36
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
    return document


def test_two_column_reading_order_is_column_major() -> None:
    document = _two_column_page()
    try:
        page = document[0]
        result = StructuredExtractionService().extract_page(page, page_number=1)
    finally:
        document.close()

    ordered = [element.text for element in result.elements]
    assert ordered == [
        "Left column first paragraph.",
        "Left column second paragraph.",
        "Right column first paragraph.",
        "Right column second paragraph.",
    ]


def test_heading_section_context_and_table_deduplication() -> None:
    document = _ruled_table_page(
        [["Plan", "Price", "Storage"], ["Basic", "$10", "5 GB"], ["Pro", "$20", "20 GB"]]
    )
    page = document[0]
    page.insert_text((50, 80), "2. Service levels", fontsize=20)
    page.insert_text((50, 290), "Plans are billed monthly.", fontsize=12)
    try:
        result = StructuredExtractionService().extract_page(page, page_number=1)
    finally:
        document.close()

    tables = [element for element in result.elements if element.content_type == "table"]
    assert len(tables) == 1
    assert "| Plan | Price | Storage |" in tables[0].text
    assert "Basic" not in "\n".join(
        element.text for element in result.elements if element.content_type != "table"
    )
    prose = next(element for element in result.elements if "billed" in element.text)
    assert prose.section_title == "2. Service levels"
    assert "Section: 2. Service levels" in result.text
    chunks = TextChunker(chunk_size=500, chunk_overlap=20).split(
        [PageText(page_number=1, text=result.text, elements=result.elements)]
    )
    assert any("Section: 2. Service levels" in chunk.text for chunk in chunks)


def test_table_preserves_empty_cells() -> None:
    document = _ruled_table_page([["Key", "Value"], ["Retention", ""], ["Region", "EU"]])
    try:
        result = StructuredExtractionService().extract_page(document[0], page_number=1)
    finally:
        document.close()

    table = next(element for element in result.elements if element.content_type == "key_value")
    assert "| Retention |  |" in table.text
    assert "| Region | EU |" in table.text


def test_pathological_table_limit_falls_back_to_native_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = _ruled_table_page([["Plan", "Price"], ["Basic", "$10"], ["Pro", "$20"]])
    monkeypatch.setattr(StructuredExtractionService, "MAX_TABLE_ROWS", 2)
    try:
        result = StructuredExtractionService().extract_page(document[0], page_number=1)
    finally:
        document.close()

    assert not any(element.content_type in {"table", "key_value"} for element in result.elements)
    assert "Basic" in result.text
    assert "Pro" in result.text


def test_structured_chunk_keeps_heading_and_table_metadata() -> None:
    elements = [
        StructuredElement("2. Service levels", "heading", 0),
        StructuredElement(
            "Section: 2. Service levels\n| Plan | Price |\n| --- | --- |\n| Pro | $20 |",
            "key_value",
            1,
            section_title="2. Service levels",
            table_index=0,
        ),
    ]
    chunks = TextChunker(chunk_size=300, chunk_overlap=20).split(
        [PageText(page_number=4, text="", elements=elements)]
    )

    assert len(chunks) == 1
    assert chunks[0].page_number == 4
    assert chunks[0].section_title == "2. Service levels"
    assert chunks[0].content_type == "mixed"
    assert chunks[0].table_index == 0
    assert "| Pro | $20 |" in chunks[0].text


def test_plain_native_page_has_safe_structured_fallback(tmp_path: Path) -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "A simple native paragraph with no layout decoration.")
    path = tmp_path / "simple.pdf"
    path.write_bytes(document.tobytes())
    document.close()

    from app.services.pdf_service import PDFTextExtractor

    pages = PDFTextExtractor(max_pages=2, ocr_min_native_text_chars=10).extract(path)
    assert pages[0].extraction_method == "native"
    assert pages[0].elements
    assert pages[0].elements[0].content_type == "paragraph"
