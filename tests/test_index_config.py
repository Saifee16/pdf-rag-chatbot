from app.core.config import get_settings
from app.services.index_config import index_fingerprint


def test_index_fingerprint_is_deterministic() -> None:
    settings = get_settings()
    assert index_fingerprint(settings) == index_fingerprint(settings)


def test_index_fingerprint_changes_when_chunking_changes() -> None:
    settings = get_settings()
    changed = settings.model_copy(update={"chunk_size": settings.chunk_size + 1})
    assert index_fingerprint(settings) != index_fingerprint(changed)
