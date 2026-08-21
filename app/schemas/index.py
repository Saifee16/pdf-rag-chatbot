from pydantic import BaseModel


class IndexInfoData(BaseModel):
    collection: str
    embedding_provider: str
    embedding_model: str
    chunk_size: int
    chunk_overlap: int
    index_fingerprint: str
