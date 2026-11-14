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

    # PR reviewer (app/review/)
    GITHUB_TOKEN: str | None = None
    GITHUB_TIMEOUT_SECONDS: float = 15.0
    REVIEW_LLM_TIMEOUT_SECONDS: float = 30.0
    REVIEW_MAX_FILES: int = 30
    REVIEW_MAX_DIFF_BYTES: int = 300_000
    REVIEW_MAX_DIFF_TOKENS: int = 20_000
    REVIEW_MAX_CONTEXT_TOKENS: int = 6_000
    REVIEW_MAX_FINDINGS_PER_FILE: int = 5
    REVIEW_MAX_EXPANDED_PER_SYMBOL: int = 6
    REVIEW_RETRIEVAL_TOP_K: int = 6
    # ?debug=true on POST /repos/{id}/review only returns its extra detail when this
    # is enabled -- off by default so internal pipeline state isn't exposed publicly.
    REVIEW_DEBUG_ENABLED: bool = False

    # "full": impact analysis + graph expansion + hybrid retrieval, as above.
    # "diff_only": the reviewer sees only the diff and the changed symbols -- no
    # callers/callees/tests, no retrieval. Used for the context-mode ablation
    # (evals/bench/); breaking_change findings become structurally unavailable in this
    # mode, since the verify gate requires real caller evidence.
    REVIEW_CONTEXT_MODE: str = "full"

    # GitHub App (app/github_app/)
    GITHUB_APP_ID: str | None = None
    GITHUB_APP_PRIVATE_KEY: str | None = None  # PEM contents, or a path to a PEM file
    GITHUB_WEBHOOK_SECRET: str | None = None
    GITHUB_REVIEW_FORKS: bool = False
    GITHUB_MAX_INLINE_COMMENTS: int = 10
    GITHUB_RATE_LIMIT_CAPACITY: int = 5
    GITHUB_RATE_LIMIT_REFILL_PER_MINUTE: float = 5.0
    # Runs the whole pipeline and logs the would-be review instead of posting it.
    # Defaults to true: posting to a real PR is a one-way, visible action.
    REVIEW_DRY_RUN: bool = True

    # Dashboard API (app/api/dashboard.py) + auth applied to every route except
    # /webhooks/github and /health (see app/api/dashboard_auth.py). When unset, only
    # requests from localhost are allowed and a warning is logged at startup -- meant
    # for local dev, never for a publicly reachable deployment.
    DASHBOARD_API_KEY: str | None = None
    # Comma-separated list of allowed CORS origins. Empty by default: the frontend
    # calls this API server-side, so no browser origin needs to be allowed at all.
    CORS_ALLOWED_ORIGINS: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
