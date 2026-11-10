import hashlib

from langchain_core.embeddings import Embeddings

from app.config import get_settings


class FakeEmbeddings(Embeddings):
    """Deterministic, network-free embedding stub for tests."""

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or get_settings().EMBEDDING_DIM

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dim)]
