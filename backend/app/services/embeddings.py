from collections.abc import Iterator
from itertools import islice

from langchain_core.embeddings import Embeddings

from app.config import EmbeddingProvider, Settings, get_settings


def get_embeddings(settings: Settings | None = None) -> Embeddings:
    """Return a LangChain `Embeddings` client for whichever provider is configured."""
    settings = settings or get_settings()

    if settings.EMBEDDING_PROVIDER == EmbeddingProvider.OPENAI:
        from langchain_openai import OpenAIEmbeddings

        return OpenAIEmbeddings(model=settings.OPENAI_EMBEDDING_MODEL, api_key=settings.OPENAI_API_KEY)

    if settings.EMBEDDING_PROVIDER == EmbeddingProvider.GOOGLE:
        from langchain_google_genai import GoogleGenerativeAIEmbeddings

        return GoogleGenerativeAIEmbeddings(
            model=settings.GOOGLE_EMBEDDING_MODEL, google_api_key=settings.GOOGLE_API_KEY
        )

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
