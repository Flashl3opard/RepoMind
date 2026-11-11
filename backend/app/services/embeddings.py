from collections.abc import Iterator
from dataclasses import dataclass
from itertools import islice

from langchain_core.embeddings import Embeddings

from app.config import EmbeddingProvider, Settings, get_settings


@dataclass(slots=True)
class _DimensionPinnedGoogleEmbeddings(Embeddings):
    """Google's embed calls take `output_dimensionality` per-call rather than at
    construction time; this pins it so every call matches `Settings.EMBEDDING_DIM`."""

    inner: Embeddings
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self.inner.embed_documents(texts, output_dimensionality=self.dim)  # type: ignore[call-arg]

    def embed_query(self, text: str) -> list[float]:
        return self.inner.embed_query(text, output_dimensionality=self.dim)  # type: ignore[call-arg]


def get_embeddings(settings: Settings | None = None) -> Embeddings:
    """Return a LangChain `Embeddings` client for whichever provider is configured,
    pinned to produce `Settings.EMBEDDING_DIM`-dimensional vectors so both providers
    stay compatible with the fixed-width `chunks.embedding` pgvector column."""
    settings = settings or get_settings()

    if settings.EMBEDDING_PROVIDER == EmbeddingProvider.OPENAI:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(
            model=settings.OPENAI_EMBEDDING_MODEL,
            api_key=settings.OPENAI_API_KEY,
            dimensions=settings.EMBEDDING_DIM,
        )

    if settings.EMBEDDING_PROVIDER == EmbeddingProvider.GOOGLE:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        google_embeddings = GoogleGenerativeAIEmbeddings(
            model=settings.GOOGLE_EMBEDDING_MODEL, google_api_key=settings.GOOGLE_API_KEY
        )
        return _DimensionPinnedGoogleEmbeddings(inner=google_embeddings, dim=settings.EMBEDDING_DIM)

    raise ValueError(f"Unsupported embedding provider: {settings.EMBEDDING_PROVIDER}")


def embed_texts_in_batches(embeddings: Embeddings, texts: list[str], batch_size: int) -> list[list[float]]:
    vectors: list[list[float]] = []
    for batch in _chunked(texts, batch_size):
        vectors.extend(embeddings.embed_documents(batch))
    return vectors


def _chunked(items: list[str], size: int) -> Iterator[list[str]]:
    it = iter(items)
    while batch := list(islice(it, size)):
        yield batch
