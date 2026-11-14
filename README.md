# RepoMind

A monorepo for ingesting public git repositories, parsing their source with Tree-sitter,
embedding code chunks, answering natural-language questions about a codebase with
exact file/line citations via a hybrid-retrieval + graph-expansion LangGraph agent, and
reviewing pull requests cross-file (either on demand or automatically via a GitHub App
webhook) with findings backed by real caller/callee/test evidence.

## Structure

```
backend/            FastAPI ingestion + API service (Python 3.12, uv, ruff, pytest)
frontend/            Next.js dashboard: repos, Q&A, PR reviews, benchmark results
docker-compose.yml   Postgres 16 + pgvector (+ an optional, not-started-by-default frontend service)
```

See [backend/README.md](backend/README.md) for backend setup, running the API, and
tests, and [frontend/README.md](frontend/README.md) for the dashboard.

## Quickstart

```bash
docker compose up -d db
cd backend
uv sync
cp .env.example .env   # add OPENAI_API_KEY or GOOGLE_API_KEY
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

### Dashboard (optional, in a second terminal)

```bash
cd frontend
cp .env.example .env.local   # BACKEND_URL + DASHBOARD_API_KEY, matching the backend's
pnpm install
pnpm gen:api                 # generate API types from the running backend's OpenAPI schema
pnpm dev                     # http://localhost:3000
```
