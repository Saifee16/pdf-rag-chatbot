import re
from dataclasses import dataclass

from app.services.pdf_service import PageText


@dataclass(slots=True)
class ChunkDraft:
    page_number: int
    chunk_index: int
    text: str
    start_char: int
    end_char: int


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
                        )
                    )
                    global_index += 1

                if end >= len(text):
                    break

                next_start = end - self.chunk_overlap
                start = next_start if next_start > start else end

        return drafts
