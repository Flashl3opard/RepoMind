from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router as repos_router
from app.config import get_settings
from app.db.session import engine
from app.db.startup_checks import assert_embedding_dimension_matches_db


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    assert_embedding_dimension_matches_db(engine, get_settings().EMBEDDING_DIM)
    yield


app = FastAPI(title="RepoMind API", lifespan=lifespan)
app.include_router(repos_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
