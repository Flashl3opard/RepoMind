# RepoMind Backend

FastAPI service that clones a public git repository, parses its source with Tree-sitter,
embeds each function/class/method chunk, and persists everything (chunks + a symbol graph)
into Postgres/pgvector so it can later be searched semantically and via full-text search.

## Stack

- Python 3.12, [uv](https://docs.astral.sh/uv/) for dependency management
- FastAPI + Uvicorn
- SQLAlchemy 2.0 + Alembic
- Postgres 16 + [pgvector](https://github.com/pgvector/pgvector)
- Tree-sitter (Python & TypeScript grammars)
- LangChain embeddings (OpenAI or Google, switchable via env)
- ruff (lint) + pytest (tests)

## Setup

```bash
cd backend
uv sync                       # creates .venv and installs deps (+ dev group)
cp .env.example .env           # fill in OPENAI_API_KEY / GOOGLE_API_KEY as needed
```

Start Postgres (from the repo root):

```bash
docker compose up -d db
```

Run migrations:

```bash
uv run alembic upgrade head
```

## Run the API

```bash
uv run uvicorn app.main:app --reload
```

- `POST /repos` with `{"url": "https://github.com/owner/repo"}` — starts ingestion as a
  background task, returns `{"id": ..., "status": "pending"}` (HTTP 202).
- `GET /repos/{id}` — returns status, last ingested commit SHA, file/chunk counts, and
  `error_message` if ingestion failed.

Ingestion is idempotent per `(repository, commit_sha)`: re-POSTing the same repo at the
same HEAD commit is a no-op rather than duplicating rows.

## Configuration (env vars, see `.env.example`)

| Variable             | Purpose                                              |
|-----------------------|-------------------------------------------------------|
| `DATABASE_URL`        | SQLAlchemy URL, e.g. `postgresql+psycopg://...`      |
| `EMBEDDING_PROVIDER`  | `openai` or `google`                                  |
| `OPENAI_API_KEY`      | required if provider is `openai`                      |
| `GOOGLE_API_KEY`      | required if provider is `google`                      |

The `chunks.embedding` pgvector column has a fixed dimension (`Settings.EMBEDDING_DIM`,
default 1536 for `text-embedding-3-small`). Switching to a provider/model with a different
dimension requires a new Alembic migration that alters that column's type.

## Tests

```bash
uv run pytest
uv run ruff check .
```

- `tests/test_parser_python.py`, `tests/test_parser_typescript.py` — pure unit tests
  against small fixture files in `tests/fixtures/`, no DB or network needed.
- `tests/test_ingestion_integration.py` — exercises the full clone → parse → embed →
  persist pipeline against a tiny local git repo fixture, using a `FakeEmbeddings` stub
  (no API keys needed). It needs a real Postgres+pgvector reachable at
  `TEST_DATABASE_URL` (defaults to `DATABASE_URL`'s value); it `pytest.skip()`s cleanly if
  one isn't running, e.g. via `docker compose up -d db`.

## Layout

```
app/
  config.py            pydantic-settings config
  main.py               FastAPI app
  api/                  routes + request/response schemas
  db/                    SQLAlchemy models, session, declarative base
  parsing/               Tree-sitter based chunk extraction (Python, TypeScript)
  services/
    cloner.py            shallow git clone -> (path, commit_sha)
    embeddings.py        LangChain embeddings factory + batching
    ingestion.py          clone -> parse -> embed -> persist orchestrator
alembic/                 migrations
tests/
```

## Known limitations / things to revisit

- The TypeScript parser covers `function` declarations, `class` + `method_definition`,
  and `const x = (...) => ...` / function-expression assignments. It does not yet handle
  every ES2022+ shape (e.g. decorators-as-expressions, object-literal method shorthand).
- Import/call extraction is per-chunk (only what's lexically inside that function/class
  node), not whole-file; module-level imports outside any function/class aren't attached
  to a chunk, matching how chunks are defined in this version.
- `SymbolEdge.target_symbol` stores the raw identifier/attribute path text (e.g.
  `os.path.join`) rather than a resolved, fully-qualified symbol — resolving edges across
  files is a reasonable next step once cross-file linking is needed.
- The embedding batch loop embeds all extracted chunks for a repo in one ingestion run;
  very large repos may want streaming/chunked commits instead of one transaction per file.
