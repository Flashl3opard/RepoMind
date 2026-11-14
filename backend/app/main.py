from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.dashboard import router as dashboard_router
from app.api.dashboard_auth import DashboardAuthMiddleware, validate_auth_config
from app.api.routes import router as repos_router
from app.config import get_settings
from app.db.session import engine
from app.db.startup_checks import assert_embedding_dimension_matches_db
from app.github_app.webhook import router as github_webhook_router
from app.observability import RequestIdMiddleware, configure_langsmith_tracing, configure_logging

configure_logging()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    assert_embedding_dimension_matches_db(engine, get_settings().EMBEDDING_DIM)
    validate_auth_config()
    configure_langsmith_tracing(get_settings())
    yield


app = FastAPI(title="RepoMind API", lifespan=lifespan)

_cors_origins = [o.strip() for o in get_settings().CORS_ALLOWED_ORIGINS.split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware, allow_origins=_cors_origins, allow_credentials=True, allow_methods=["*"], allow_headers=["*"]
    )

app.add_middleware(DashboardAuthMiddleware)
# Outermost: registered last so it wraps everything above, including the
# auth-rejection path -- every request gets a request id and a logged outcome.
app.add_middleware(RequestIdMiddleware)

app.include_router(repos_router)
app.include_router(dashboard_router)
app.include_router(github_webhook_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
