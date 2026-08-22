import hashlib

from app.core.config import Settings

STRUCTURED_EXTRACTION_VERSION = "layout-v1"


def index_fingerprint(settings: Settings) -> str:
    raw = "|".join(
        [
            STRUCTURED_EXTRACTION_VERSION,
            settings.embedding_provider,
            settings.embedding_model,
            str(settings.chunk_size),
            str(settings.chunk_overlap),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
