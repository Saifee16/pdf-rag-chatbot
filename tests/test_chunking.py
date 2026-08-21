from app.services.chunking_service import TextChunker
from app.services.pdf_service import PageText


def test_chunker_preserves_page_numbers_and_overlap() -> None:
    text = "A" * 700 + ". " + "B" * 700 + ". " + "C" * 700
    chunker = TextChunker(chunk_size=1000, chunk_overlap=100)
    chunks = chunker.split([PageText(page_number=3, text=text)])

    assert len(chunks) >= 2
    assert all(chunk.page_number == 3 for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[1].start_char < chunks[0].end_char


def test_chunker_normalizes_nulls_and_blank_pages() -> None:
    chunker = TextChunker(chunk_size=300, chunk_overlap=20)
    chunks = chunker.split(
        [
            PageText(page_number=1, text="   \n\n\n"),
            PageText(page_number=2, text="Hello\x00   world"),
        ]
    )

    assert len(chunks) == 1
    assert chunks[0].text == "Hello world"


def test_chunker_rejects_overlap_equal_to_size() -> None:
    try:
        TextChunker(chunk_size=200, chunk_overlap=200)
    except ValueError as exc:
        assert "smaller" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
