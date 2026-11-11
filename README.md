# RepoMind

A monorepo for ingesting public git repositories, parsing their source with Tree-sitter,
embedding code chunks, and answering natural-language questions about a codebase with
exact file/line citations via a hybrid-retrieval + graph-expansion LangGraph agent.

## Structure

```
backend/            FastAPI ingestion + API service (Python 3.12, uv, ruff, pytest)
frontend/            placeholder — not scaffolded yet
docker-compose.yml   Postgres 16 + pgvector
```

See [backend/README.md](backend/README.md) for backend setup, running the API, and tests.

## Quickstart

```bash
docker compose up -d db
cd backend
uv sync
cp .env.example .env   # add OPENAI_API_KEY or GOOGLE_API_KEY
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```
