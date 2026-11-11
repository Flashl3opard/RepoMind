from enum import StrEnum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class EmbeddingProvider(StrEnum):
    OPENAI = "openai"
    GOOGLE = "google"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_URL: str = "postgresql+psycopg://repomind:repomind@localhost:5432/repomind"

    EMBEDDING_PROVIDER: EmbeddingProvider = EmbeddingProvider.OPENAI
    OPENAI_API_KEY: str | None = None
    GOOGLE_API_KEY: str | None = None

    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    GOOGLE_EMBEDDING_MODEL: str = "models/text-embedding-004"

    # Dimension of the `chunks.embedding` pgvector column. Must match whichever
    # provider/model is active; changing providers to a different dimension
    # requires a migration that alters the column.
    EMBEDDING_DIM: int = 1536
    EMBEDDING_BATCH_SIZE: int = 64

    CLONE_WORKDIR: str | None = None  # defaults to the OS temp dir when unset
    SUPPORTED_EXTENSIONS: tuple[str, ...] = (".py", ".ts", ".tsx")

    # Chat models for the Q&A agent (app/agents/qa.py), passed to
    # `langchain.chat_models.init_chat_model` as "<provider>:<model>".
    CHAT_PROVIDER: str = "openai"
    CHAT_MODEL: str = "gpt-4o-mini"
    VERIFY_MODEL: str = "gpt-4o-mini"

    QA_DEFAULT_TOP_K: int = 8
    QA_MAX_EXPANDED_CHUNKS: int = 6
    QA_MAX_ATTEMPTS: int = 2


@lru_cache
def get_settings() -> Settings:
    return Settings()
