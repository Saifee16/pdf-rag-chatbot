import re
from dataclasses import dataclass
from typing import Literal

from app.services.pdf_service import PageText
from app.services.structured_extraction_service import StructuredElement

ChunkContentType = Literal["text", "heading", "table", "key_value", "mixed", "ocr"]
ChunkExtractionMethod = Literal["native", "ocr", "mixed"]


@dataclass(slots=True)
class ChunkDraft:
    page_number: int
    chunk_index: int
    text: str
    start_char: int
    end_char: int
    section_title: str | None = None
    content_type: ChunkContentType = "text"
    table_index: int | None = None
    extraction_method: ChunkExtractionMethod = "native"


class TextChunker:
    def __init__(self, *, chunk_size: int, chunk_overlap: int) -> None:
        if chunk_overlap >= chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap

    @staticmethod
    def normalize(text: str) -> str:
        text = text.replace("\x00", " ")
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def split(self, pages: list[PageText]) -> list[ChunkDraft]:
        drafts: list[ChunkDraft] = []
        global_index = 0

        for page in pages:
            if page.elements:
                structured_drafts = self._split_structured_page(page, global_index)
                drafts.extend(structured_drafts)
                global_index += len(structured_drafts)
                continue

            text = self.normalize(page.text)
            if not text:
                continue

            start = 0
            while start < len(text):
                hard_end = min(start + self.chunk_size, len(text))
                end = hard_end

                if hard_end < len(text):
                    split_window = text[start:hard_end]
                    paragraph = split_window.rfind("\n\n")
                    sentence = max(
                        split_window.rfind(". "),
                        split_window.rfind("? "),
                        split_window.rfind("! "),
                    )
                    preferred = max(paragraph, sentence)
                    if preferred >= int(self.chunk_size * 0.6):
                        end = start + preferred + (2 if paragraph == preferred else 1)

                chunk_text = text[start:end].strip()
                if chunk_text:
                    drafts.append(
                        ChunkDraft(
                            page_number=page.page_number,
                            chunk_index=global_index,
                            text=chunk_text,
                            start_char=start,
                            end_char=end,
                            extraction_method=(
                                "ocr" if page.extraction_method == "ocr" else "native"
                            ),
                        )
                    )
                    global_index += 1

                if end >= len(text):
                    break

                next_start = end - self.chunk_overlap
                start = next_start if next_start > start else end

        return drafts

    def _split_structured_page(self, page: PageText, start_index: int) -> list[ChunkDraft]:
        segments: list[tuple[str, StructuredElement, int, int]] = []
        cursor = 0
        for element in page.elements:
            text = self.normalize(element.text)
            if element.section_title and element.content_type != "heading":
                prefix = f"Section: {self.normalize(element.section_title)}"
                if not text.startswith(prefix):
                    text = f"{prefix}\n{text}"
            if not text:
                continue
            pieces = self._element_pieces(text, element)
            for piece in pieces:
                start = cursor
                cursor += len(piece)
                segments.append((piece, element, start, cursor))
                cursor += 2

        drafts: list[ChunkDraft] = []
        buffer: list[tuple[str, StructuredElement, int, int]] = []
        buffer_length = 0

        def flush() -> None:
            nonlocal buffer, buffer_length
            if not buffer:
                return
            text = "\n\n".join(item[0] for item in buffer).strip()
            first = buffer[0]
            last = buffer[-1]
            drafts.append(
                ChunkDraft(
                    page_number=page.page_number,
                    chunk_index=start_index + len(drafts),
                    text=text,
                    start_char=first[2],
                    end_char=last[3],
                    section_title=self._section_for_buffer(buffer),
                    content_type=self._content_type_for_buffer(buffer),
                    table_index=self._table_index_for_buffer(buffer),
                    extraction_method=self._method_for_buffer(buffer, page),
                )
            )
            buffer = []
            buffer_length = 0

        for segment in segments:
            text, element, _, _ = segment
            is_heading = element.content_type == "heading"
            is_table = element.content_type in {"table", "key_value"}
            separator = 2 if buffer else 0
            would_fit = buffer_length + separator + len(text) <= self.chunk_size
            if is_heading and buffer:
                flush()
                would_fit = True
            if is_table and buffer and not would_fit:
                flush()
                would_fit = True
            if not would_fit:
                flush()
            buffer.append(segment)
            buffer_length += (2 if len(buffer) > 1 else 0) + len(text)
            if is_table:
                flush()
        flush()
        return drafts

    def _element_pieces(self, text: str, element: StructuredElement) -> list[str]:
        if len(text) <= self.chunk_size or element.content_type not in {"table", "key_value"}:
            if len(text) <= self.chunk_size:
                return [text]
            return self._split_long_text(text)

        lines = text.splitlines()
        if len(lines) < 3:
            return self._split_long_text(text)
        header = lines[:2]
        pieces: list[str] = []
        current = header[:]
        for line in lines[2:]:
            candidate = "\n".join(current + [line])
            if len(candidate) > self.chunk_size and len(current) > 2:
                pieces.append("\n".join(current))
                current = header[:] + [line]
            else:
                current.append(line)
        if len(current) > 2 or not pieces:
            pieces.append("\n".join(current))
        return pieces

    def _split_long_text(self, text: str) -> list[str]:
        pieces: list[str] = []
        start = 0
        while start < len(text):
            hard_end = min(start + self.chunk_size, len(text))
            end = hard_end
            if hard_end < len(text):
                window = text[start:hard_end]
                paragraph = window.rfind("\n\n")
                sentence = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
                preferred = max(paragraph, sentence)
                if preferred >= int(self.chunk_size * 0.6):
                    end = start + preferred + (2 if paragraph == preferred else 1)
            pieces.append(text[start:end].strip())
            if end >= len(text):
                break
            next_start = end - self.chunk_overlap
            start = next_start if next_start > start else end
        return [piece for piece in pieces if piece]

    @staticmethod
    def _section_for_buffer(buffer: list[tuple[str, StructuredElement, int, int]]) -> str | None:
        for _, element, _, _ in buffer:
            if element.content_type == "heading":
                return element.text
            if element.section_title:
                return element.section_title
        return None

    @staticmethod
    def _content_type_for_buffer(
        buffer: list[tuple[str, StructuredElement, int, int]],
    ) -> ChunkContentType:
        content_types = {element.content_type for _, element, _, _ in buffer}
        if len(content_types) == 1:
            only = next(iter(content_types))
            return only if only in {"heading", "table", "key_value", "ocr"} else "text"
        return "mixed"

    @staticmethod
    def _table_index_for_buffer(
        buffer: list[tuple[str, StructuredElement, int, int]],
    ) -> int | None:
        indexes = {
            element.table_index for _, element, _, _ in buffer if element.table_index is not None
        }
        return min(indexes) if indexes else None

    @staticmethod
    def _method_for_buffer(
        buffer: list[tuple[str, StructuredElement, int, int]], page: PageText
    ) -> ChunkExtractionMethod:
        methods = {element.extraction_method for _, element, _, _ in buffer}
        if page.extraction_method == "ocr" or methods == {"ocr"}:
            return "ocr"
        return "native" if methods <= {"native"} else "mixed"
