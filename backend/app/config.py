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
    # (evals/bench/); breaking_change/contract_change findings become structurally
    # unavailable in this mode, since those verify gates require real caller evidence
    # -- it's a structural lower bound, not a realistic baseline.
    # "naive": simulates a per-file reviewer -- the diff plus each changed file's
    # full new content (when available), no impact analysis, no retrieval, and the
    # caller-evidence gates are skipped entirely (there's no caller evidence to cite
    # in this mode by construction). This is the fair baseline for the ablation: what
    # a reviewer gets with zero of this project's retrieval/graph machinery, not
    # artificially gated to find nothing.
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
    # /webhooks/github and /health (see app/api/dashboard_auth.py). Fails closed: if
    # unset, protected routes return 503 rather than falling back to any
    # network-position check (a reverse proxy/tunnel makes every request look like it
    # came from localhost, so that was never a safe substitute for a real key).
    DASHBOARD_API_KEY: str | None = None
    # Explicit, loud local-dev opt-out of dashboard auth entirely. Refused at startup
    # (see app/api/dashboard_auth.py::validate_auth_config) unless REVIEW_DRY_RUN is
    # true and GITHUB_WEBHOOK_SECRET is unset, since those are the two ways this
    # process can take a real-world-visible action.
    DASHBOARD_AUTH_DISABLED: bool = False
    # Comma-separated list of allowed CORS origins. Empty by default: the frontend
    # calls this API server-side, so no browser origin needs to be allowed at all.
    CORS_ALLOWED_ORIGINS: str = ""

    # Optional LangSmith tracing (app/observability.py::configure_langsmith_tracing).
    # Off by default -- standard LangChain/LangGraph env vars, exported into the
    # actual process environment at startup only when this is true.
    LANGCHAIN_TRACING_V2: bool = False
    LANGCHAIN_API_KEY: str | None = None
    LANGCHAIN_PROJECT: str = "repomind"
    LANGCHAIN_ENDPOINT: str | None = None


@lru_cache
def get_settings() -> Settings:
    return Settings()
