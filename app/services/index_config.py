import hashlib

from app.core.config import Settings


def index_fingerprint(settings: Settings) -> str:
    raw = "|".join(
        [
            settings.embedding_provider,
            settings.embedding_model,
            str(settings.chunk_size),
            str(settings.chunk_overlap),
        ]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
