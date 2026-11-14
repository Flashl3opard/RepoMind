# RepoMind Dashboard

A Next.js (App Router) dashboard for [RepoMind](../README.md): manage ingested repos,
ask questions with citations, review PRs (live or in a diff-paste playground), and view
the context-mode benchmark results. All backend calls happen server-side (server
components, server actions, and the `gen:api` script) -- the dashboard's API key never
reaches the browser.

## Stack

Next.js 16 (App Router, Cache Components/PPR), React 19, TypeScript (strict), Tailwind
v4, hand-written shadcn/ui-style primitives, Recharts, pnpm. Types for backend calls are
generated from the FastAPI OpenAPI schema with `openapi-typescript`.

## Running it alongside the backend

```bash
# from backend/, with the DB up and migrated (see ../backend/README.md)
uv run uvicorn app.main:app --reload

# from frontend/
cp .env.example .env.local   # set BACKEND_URL and DASHBOARD_API_KEY to match the backend
pnpm install
pnpm gen:api                 # regenerate src/lib/api-types.ts from the running backend's schema
pnpm dev                     # http://localhost:3000
```

`DASHBOARD_API_KEY` must be set to the same value the backend's `DASHBOARD_API_KEY` env
var uses (see `backend/README.md`'s "Dashboard API" section) -- the backend fails
closed and returns `503` on every call if it doesn't have a key configured. For local
development without a key, set `DASHBOARD_AUTH_DISABLED=true` on the backend instead.

## Env vars (see `.env.example`)

| Variable             | Purpose                                                        |
|-----------------------|------------------------------------------------------------------|
| `BACKEND_URL`         | base URL of the RepoMind backend, e.g. `http://localhost:8000`  |
| `DASHBOARD_API_KEY`   | sent as `Authorization: Bearer ...` on every backend call; server-side only, never bundled for the browser |

## Pages

- `/` -- repos list, status badges, "Add repository" form (polls ingestion status).
- `/repos/[id]` -- commit/counts/status overview, links to Ask and Reviews.
- `/repos/[id]/ask` -- Q&A with citation chips (linking to the GitHub blob at the
  indexed commit), a low-confidence banner, and a debug view of retrieved chunks.
- `/repos/[id]/reviews` -- that repo's review runs, newest first, with risk badges.
- `/reviews/[runId]` -- one run's summary, risk level, and findings grouped by file.
- `/playground` -- paste a diff, pick a repo, run a dry-mode review, see findings.
- `/benchmark` -- chart + table from `GET /benchmark/latest`, with an empty state
  explaining how to generate results if none exist yet.

## Scripts

`pnpm dev` / `build` / `start`, `pnpm lint`, `pnpm typecheck`, `pnpm test` (Vitest),
`pnpm format` / `format:check` (Prettier), `pnpm gen:api` (regenerate API types; needs
the backend running at `BACKEND_URL`).

## Screenshots

_Not yet captured -- add dashboard screenshots here (Repos, Ask with citations, Review
detail, Benchmark chart) once the backend has some real ingested repos/reviews to show._

---

Bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).
