# Convenience targets for the full stack. No `make` on Windows (without MSYS/WSL)?
# See the root README's "Makefile targets" section for the plain-command equivalents.

.PHONY: up down test lint seed bench

up:
	docker compose up --build

down:
	docker compose down

test:
	cd backend && uv run pytest
	cd frontend && pnpm test

lint:
	cd backend && uv run ruff check .
	cd frontend && pnpm format:check && pnpm lint && pnpm typecheck

# make seed [REPO_URL=https://github.com/owner/repo] [BACKEND_URL=http://localhost:8000]
seed:
	cd backend && uv run python scripts/seed_demo.py \
		$(if $(REPO_URL),--repo-url $(REPO_URL)) \
		$(if $(BACKEND_URL),--backend-url $(BACKEND_URL))

# make bench REPO=/path/to/local/repo CASES_DIR=evals/bench/cases/<repo-name>
bench:
ifndef REPO
	$(error REPO is required, e.g. make bench REPO=/path/to/repo CASES_DIR=evals/bench/cases/repo)
endif
ifndef CASES_DIR
	$(error CASES_DIR is required, e.g. make bench REPO=/path/to/repo CASES_DIR=evals/bench/cases/repo)
endif
	cd backend && uv run python -m evals.bench.run --repo $(REPO) --cases-dir $(CASES_DIR)
