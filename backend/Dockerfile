FROM python:3.12-slim

# git: app/services/cloner.py shells out to `git clone` to ingest repos.
# ca-certificates: outbound HTTPS (GitHub API, embedding/chat providers).
RUN apt-get update \
    && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev

EXPOSE 8000

# Migrations run on every start, not just the first -- alembic upgrade head is a
# no-op once the schema is current, so this is safe on every container restart.
CMD ["sh", "-c", "uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000"]
