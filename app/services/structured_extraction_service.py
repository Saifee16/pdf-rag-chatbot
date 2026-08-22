from __future__ import annotations

import re
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from typing import Literal

import pymupdf

ElementType = Literal["heading", "paragraph", "table", "key_value", "ocr"]


@dataclass(slots=True, frozen=True)
class StructuredElement:
    """A bounded, retrieval-friendly page element.

    Coordinates are intentionally kept internal to the extraction layer. The
    public metadata is the stable content type, reading order, section label,
    and optional table number needed by chunking and citations.
    """

    text: str
    content_type: ElementType
    reading_order: int
    section_title: str | None = None
    table_index: int | None = None
    extraction_method: Literal["native", "ocr"] = "native"
    bbox: tuple[float, float, float, float] | None = None


@dataclass(slots=True, frozen=True)
class StructuredPage:
    page_number: int
    text: str
    elements: list[StructuredElement]
    extraction_method: Literal["native", "ocr", "empty"] = "native"


class StructuredExtractionService:
    """Deterministic layout extraction built on PyMuPDF's native APIs.

    This is deliberately a small heuristic layer, not a general document-AI
    system. It handles common one/two-column pages and machine-generated ruled
    tables, then falls back to native text blocks when structure is uncertain.
    """

    MAX_TABLES_PER_PAGE = 8
    MAX_TABLE_ROWS = 200
    MAX_TABLE_COLUMNS = 50
    MAX_TABLE_CELLS = 2_000
    MAX_TABLE_TEXT_CHARS = 100_000
    MAX_PAGE_TEXT_CHARS = 1_000_000
    MAX_BLOCKS_PER_PAGE = 2_000
    MAX_DRAWINGS_PER_PAGE = 10_000
    _NUMBERED_HEADING = re.compile(r"^(?:\d+(?:\.\d+)*[.)]?|[A-Z][.)])\s+\S+")

    def extract_page(
        self,
        page: pymupdf.Page,
        *,
        page_number: int,
        native_text: str | None = None,
    ) -> StructuredPage:
        """Extract one native page, preserving safe structure when available."""

        plain_text = native_text if native_text is not None else page.get_text("text", sort=True)
        blocks = self._text_blocks(page)
        if not blocks:
            text = self._normalize_text(plain_text)
            elements = (
                [
                    StructuredElement(
                        text=text,
                        content_type="paragraph",
                        reading_order=0,
                    )
                ]
                if text
                else []
            )
            return StructuredPage(page_number, text, elements, "native" if text else "empty")

        tables = self._extract_tables(page)
        accepted_tables = [table for table in tables if table is not None]
        table_bboxes = [table[0] for table in accepted_tables]
        table_elements = [table[1] for table in accepted_tables]
        body_blocks = [
            block
            for block in blocks
            if not self._strongly_overlaps_table(block["bbox"], table_bboxes)
        ]
        ordered_blocks = self._reading_order(body_blocks, page.rect.width)
        body_elements = self._classify_blocks(ordered_blocks)

        elements: list[StructuredElement] = []
        section_title: str | None = None
        table_by_top = sorted(
            zip(table_bboxes, table_elements, strict=True), key=lambda item: item[0][1]
        )
        body_index = 0
        table_index = 0
        while body_index < len(body_elements) or table_index < len(table_by_top):
            next_body = body_elements[body_index] if body_index < len(body_elements) else None
            next_table = table_by_top[table_index] if table_index < len(table_by_top) else None
            if next_table is not None and (
                next_body is None or next_table[0][1] <= float(next_body.bbox[1])
            ):
                element = next_table[1]
                elements.append(
                    StructuredElement(
                        text=element.text,
                        content_type=element.content_type,
                        reading_order=len(elements),
                        section_title=section_title,
                        table_index=table_index,
                        extraction_method="native",
                        bbox=element.bbox,
                    )
                )
                table_index += 1
                continue

            if next_body is None:
                break
            if next_body.content_type == "heading":
                section_title = next_body.text
            elements.append(
                StructuredElement(
                    text=next_body.text,
                    content_type=next_body.content_type,
                    reading_order=len(elements),
                    section_title=section_title if next_body.content_type != "heading" else None,
                    extraction_method="native",
                    bbox=next_body.bbox,
                )
            )
            body_index += 1

        if not elements and plain_text.strip():
            elements = [
                StructuredElement(
                    text=self._normalize_text(plain_text),
                    content_type="paragraph",
                    reading_order=0,
                )
            ]
        combined = self._combine_elements(elements)
        if not combined and plain_text.strip():
            combined = self._normalize_text(plain_text)
        return StructuredPage(page_number, combined[: self.MAX_PAGE_TEXT_CHARS], elements, "native")

    @staticmethod
    def ocr_page(page_number: int, text: str) -> StructuredPage:
        normalized = StructuredExtractionService._normalize_text(text)
        elements = (
            [
                StructuredElement(
                    text=normalized,
                    content_type="ocr",
                    reading_order=0,
                    extraction_method="ocr",
                )
            ]
            if normalized
            else []
        )
        return StructuredPage(
            page_number,
            normalized,
            elements,
            "ocr" if normalized else "empty",
        )

    def _text_blocks(self, page: pymupdf.Page) -> list[dict[str, object]]:
        try:
            raw = page.get_text("dict", sort=False)
        except Exception:
            return []
        blocks: list[dict[str, object]] = []
        page_width = float(page.rect.width)
        for raw_block in raw.get("blocks", [])[: self.MAX_BLOCKS_PER_PAGE]:
            if raw_block.get("type", 0) != 0:
                continue
            lines = raw_block.get("lines", [])
            split_lines = self._block_has_column_gap(lines, page_width)
            if split_lines:
                for line in lines:
                    for spans in self._line_span_groups(line, page_width):
                        block = self._block_from_spans(spans)
                        if block is not None:
                            blocks.append(block)
                continue
            parts: list[str] = []
            fonts: list[tuple[float, str]] = []
            for line in lines:
                spans = line.get("spans", [])
                line_text = "".join(str(span.get("text", "")) for span in spans).strip()
                if line_text:
                    parts.append(line_text)
                for span in spans:
                    text = str(span.get("text", "")).strip()
                    if text:
                        fonts.append((float(span.get("size", 0.0)), str(span.get("font", ""))))
            text = self._normalize_text("\n".join(parts))
            bbox = tuple(float(value) for value in raw_block.get("bbox", (0, 0, 0, 0)))
            if text and len(bbox) == 4:
                blocks.append({"text": text, "bbox": bbox, "fonts": fonts})
        return blocks

    @staticmethod
    def _block_has_column_gap(lines: list[dict[str, object]], page_width: float) -> bool:
        for index, left in enumerate(lines):
            left_bbox = left.get("bbox", (0, 0, 0, 0))
            for right in lines[index + 1 :]:
                right_bbox = right.get("bbox", (0, 0, 0, 0))
                if abs(float(left_bbox[1]) - float(right_bbox[1])) > 2.0:
                    continue
                first, second = sorted((left_bbox, right_bbox), key=lambda bbox: float(bbox[0]))
                if float(second[0]) - float(first[2]) > max(40.0, page_width * 0.15):
                    return True
        return any(
            StructuredExtractionService._line_has_column_gap(line, page_width) for line in lines
        )

    @staticmethod
    def _line_has_column_gap(line: dict[str, object], page_width: float) -> bool:
        spans = sorted(
            line.get("spans", []), key=lambda span: float(span.get("bbox", (0, 0, 0, 0))[0])
        )
        for left, right in zip(spans, spans[1:], strict=False):
            left_bbox = left.get("bbox", (0, 0, 0, 0))
            right_bbox = right.get("bbox", (0, 0, 0, 0))
            if float(right_bbox[0]) - float(left_bbox[2]) > max(40.0, page_width * 0.15):
                return True
        return False

    @classmethod
    def _line_span_groups(
        cls, line: dict[str, object], page_width: float
    ) -> list[list[dict[str, object]]]:
        spans = sorted(
            line.get("spans", []), key=lambda span: float(span.get("bbox", (0, 0, 0, 0))[0])
        )
        groups: list[list[dict[str, object]]] = []
        for span in spans:
            if not groups:
                groups.append([span])
                continue
            previous = groups[-1][-1]
            previous_bbox = previous.get("bbox", (0, 0, 0, 0))
            current_bbox = span.get("bbox", (0, 0, 0, 0))
            gap = float(current_bbox[0]) - float(previous_bbox[2])
            if gap > max(40.0, page_width * 0.15):
                groups.append([span])
            else:
                groups[-1].append(span)
        return groups

    @classmethod
    def _block_from_spans(cls, spans: list[dict[str, object]]) -> dict[str, object] | None:
        parts = [str(span.get("text", "")).strip() for span in spans]
        text = cls._normalize_text("".join(parts))
        if not text:
            return None
        boxes = [tuple(float(value) for value in span.get("bbox", (0, 0, 0, 0))) for span in spans]
        return {
            "text": text,
            "bbox": (
                min(box[0] for box in boxes),
                min(box[1] for box in boxes),
                max(box[2] for box in boxes),
                max(box[3] for box in boxes),
            ),
            "fonts": [(float(span.get("size", 0.0)), str(span.get("font", ""))) for span in spans],
        }

    def _extract_tables(
        self, page: pymupdf.Page
    ) -> list[tuple[tuple[float, float, float, float], StructuredElement] | None]:
        """Extract ruled tables first; return no table on unsafe/uncertain output."""

        try:
            drawings = page.get_drawings()
        except Exception:
            drawings = []
        if not drawings or len(drawings) > self.MAX_DRAWINGS_PER_PAGE:
            return []
        try:
            # PyMuPDF 1.28 emits an advisory to stdout when table analysis is
            # first used. Keep benchmark/API output machine-readable.
            with redirect_stdout(StringIO()):
                finder = page.find_tables(strategy="lines")
        except Exception:
            return []
        extracted: list[tuple[tuple[float, float, float, float], StructuredElement] | None] = []
        for index, table in enumerate(finder.tables[: self.MAX_TABLES_PER_PAGE]):
            rows = table.extract()
            normalized_rows = self._normalize_table_rows(rows)
            if not self._table_within_limits(normalized_rows):
                continue
            text = self._table_text(normalized_rows)
            if not text:
                continue
            content_type: ElementType = "key_value" if len(normalized_rows[0]) == 2 else "table"
            extracted.append(
                (
                    tuple(float(value) for value in table.bbox),
                    StructuredElement(
                        text=text,
                        content_type=content_type,
                        reading_order=index,
                        table_index=index,
                        bbox=tuple(float(value) for value in table.bbox),
                    ),
                )
            )
        return extracted

    @staticmethod
    def _normalize_table_rows(rows: list[list[object]]) -> list[list[str]]:
        normalized: list[list[str]] = []
        width = max((len(row) for row in rows), default=0)
        for row in rows:
            values = [StructuredExtractionService._normalize_text(str(cell or "")) for cell in row]
            normalized.append(values + [""] * (width - len(values)))
        return normalized

    @classmethod
    def _table_within_limits(cls, rows: list[list[str]]) -> bool:
        if not rows:
            return False
        row_count = len(rows)
        column_count = max(len(row) for row in rows)
        cell_count = row_count * column_count
        text_length = sum(len(cell) for row in rows for cell in row)
        return (
            row_count <= cls.MAX_TABLE_ROWS
            and column_count <= cls.MAX_TABLE_COLUMNS
            and cell_count <= cls.MAX_TABLE_CELLS
            and text_length <= cls.MAX_TABLE_TEXT_CHARS
        )

    @staticmethod
    def _table_text(rows: list[list[str]]) -> str:
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        padded = [row + [""] * (width - len(row)) for row in rows]
        header = padded[0]
        lines = [
            "| "
            + " | ".join(StructuredExtractionService._escape_cell(cell) for cell in header)
            + " |",
            "| " + " | ".join("---" for _ in range(width)) + " |",
        ]
        lines.extend(
            "| " + " | ".join(StructuredExtractionService._escape_cell(cell) for cell in row) + " |"
            for row in padded[1:]
        )
        return "\n".join(lines)

    @staticmethod
    def _escape_cell(value: str) -> str:
        return value.replace("|", r"\|").replace("\n", " ")

    @staticmethod
    def _strongly_overlaps_table(
        bbox: tuple[float, float, float, float],
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> bool:
        for table in table_bboxes:
            x0 = max(bbox[0], table[0])
            y0 = max(bbox[1], table[1])
            x1 = min(bbox[2], table[2])
            y1 = min(bbox[3], table[3])
            if x1 <= x0 or y1 <= y0:
                continue
            intersection = (x1 - x0) * (y1 - y0)
            block_area = max((bbox[2] - bbox[0]) * (bbox[3] - bbox[1]), 1.0)
            center_inside = (
                table[0] <= (bbox[0] + bbox[2]) / 2 <= table[2]
                and table[1] <= (bbox[1] + bbox[3]) / 2 <= table[3]
            )
            if center_inside or intersection / block_area >= 0.5:
                return True
        return False

    @staticmethod
    def _reading_order(
        blocks: list[dict[str, object]], page_width: float
    ) -> list[dict[str, object]]:
        if len(blocks) < 3:
            return sorted(
                blocks, key=lambda block: (float(block["bbox"][1]), float(block["bbox"][0]))
            )
        midpoint = page_width / 2.0
        left = [block for block in blocks if float(block["bbox"][0]) < midpoint]
        right = [block for block in blocks if float(block["bbox"][0]) >= midpoint]
        if len(left) < 2 or len(right) < 2:
            return sorted(
                blocks, key=lambda block: (float(block["bbox"][1]), float(block["bbox"][0]))
            )
        spanning = [
            block
            for block in blocks
            if float(block["bbox"][2]) - float(block["bbox"][0]) >= page_width * 0.65
        ]
        columns = [block for block in blocks if block not in spanning]
        left = [block for block in columns if float(block["bbox"][0]) < midpoint]
        right = [block for block in columns if float(block["bbox"][0]) >= midpoint]
        if len(left) < 2 or len(right) < 2:
            return sorted(
                blocks, key=lambda block: (float(block["bbox"][1]), float(block["bbox"][0]))
            )
        return (
            sorted(spanning, key=lambda block: (float(block["bbox"][1]), float(block["bbox"][0])))
            + sorted(left, key=lambda block: (float(block["bbox"][1]), float(block["bbox"][0])))
            + sorted(right, key=lambda block: (float(block["bbox"][1]), float(block["bbox"][0])))
        )

    @classmethod
    def _classify_blocks(cls, blocks: list[dict[str, object]]) -> list[StructuredElement]:
        sizes = [size for block in blocks for size, _ in block["fonts"]]
        # The smallest repeated body size is a safer baseline than the median:
        # short pages often contain one title and one paragraph only.
        baseline = min(sizes) if sizes else 0.0
        elements: list[StructuredElement] = []
        for index, block in enumerate(blocks):
            text = str(block["text"])
            fonts = block["fonts"]
            max_size = max((size for size, _ in fonts), default=0.0)
            bold = any("bold" in font.lower() or "black" in font.lower() for _, font in fonts)
            isolated = len(text) <= 140 and text.count("\n") <= 2
            numbered = bool(cls._NUMBERED_HEADING.match(text))
            is_heading = isolated and (
                numbered or bold or (baseline > 0 and max_size >= baseline * 1.25)
            )
            elements.append(
                StructuredElement(
                    text=text,
                    content_type="heading" if is_heading else "paragraph",
                    reading_order=index,
                    bbox=tuple(float(value) for value in block["bbox"]),
                )
            )
        return elements

    @staticmethod
    def _combine_elements(elements: list[StructuredElement]) -> str:
        parts: list[str] = []
        for element in elements:
            text = element.text
            if element.content_type != "heading" and element.section_title:
                text = f"Section: {element.section_title}\n{text}"
            parts.append(text)
        return "\n\n".join(parts).strip()

    @staticmethod
    def _normalize_text(text: str) -> str:
        text = text.replace("\x00", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
