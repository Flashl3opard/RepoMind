from fastapi import FastAPI

from app.api.routes import router as repos_router

app = FastAPI(title="RepoMind API")
app.include_router(repos_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
