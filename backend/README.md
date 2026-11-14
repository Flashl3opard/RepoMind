# RepoMind Backend

FastAPI service that clones a public git repository, parses its source with Tree-sitter,
embeds each function/class/method chunk, and persists everything (chunks + a symbol graph)
into Postgres/pgvector. On top of that it answers natural-language questions about the
repo with a hybrid-retrieval + graph-expansion LangGraph agent, citing exact
`file_path:start_line-end_line` locations for every claim, and reviews a pull request
against that index -- cross-file, with callers/callees/tests as evidence -- without
ever writing anything from the PR back into the database.

## Stack

- Python 3.12, [uv](https://docs.astral.sh/uv/) for dependency management
- FastAPI + Uvicorn
- SQLAlchemy 2.0 + Alembic
- Postgres 16 + [pgvector](https://github.com/pgvector/pgvector)
- Tree-sitter (Python & TypeScript grammars)
- LangChain embeddings + chat models (OpenAI or Google, switchable via env) and LangGraph
  for the Q&A agent
- ruff (lint) + pytest (tests)

## Setup

For the whole stack (db + backend + frontend) in one command, see the root
[README's Quickstart](../README.md#quickstart-one-command) (`docker compose up
--build`, then optionally `uv run python scripts/seed_demo.py` to populate it with a
sample ingested repo, Q&A, and review). The rest of this section is for running the
backend directly against a local Python/uv install instead.

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
- `POST /repos/{id}/ask` with `{"question": "..."}` — answers a question about the repo.
  Returns 409 if that repo's ingestion isn't `completed` yet.
- `POST /repos/{id}/review` with `{"pr_url": "https://github.com/owner/repo/pull/N"}`
  or `{"diff": "<unified diff text>"}` (exactly one) — reviews that PR against the
  repo's indexed base branch. Returns 409 if ingestion isn't `completed`, 404/429/502
  for GitHub lookup problems, 422 for bad input, 413 if the diff is too large.

Ingestion is idempotent per `(repository, commit_sha)`: re-POSTing the same repo at the
same HEAD commit is a no-op rather than duplicating rows.

### Asking a question

```bash
# 1. ingest a repo and wait for GET /repos/{id} to report status "completed"
curl -s -X POST localhost:8000/repos -H 'content-type: application/json' \
  -d '{"url": "https://github.com/owner/repo"}'

# 2. ask about it
curl -s -X POST localhost:8000/repos/<id>/ask -H 'content-type: application/json' \
  -d '{"question": "How does the ingestion orchestrator handle a failed clone?"}'
```

Response shape:

```json
{
  "answer": "... cites [C1], [C2] ...",
  "citations": [
    {"label": "C1", "file_path": "app/services/ingestion.py", "start_line": 40, "end_line": 55, "symbol_name": "ingest_repository"}
  ],
  "confidence": "high",
  "retrieved_count": 8,
  "expanded_count": 3
}
```

Add `?debug=true` to also get the rewritten search query, the per-chunk retrieval
provenance (`vector` / `keyword` / graph `callee_of:<symbol>` / `caller_of:<symbol>`),
and how many generate/verify attempts the agent needed.

## Configuration (env vars, see `.env.example`)

| Variable             | Purpose                                              |
|-----------------------|-------------------------------------------------------|
| `DATABASE_URL`        | SQLAlchemy URL, e.g. `postgresql+psycopg://...`      |
| `EMBEDDING_PROVIDER`  | `openai` or `google`                                  |
| `OPENAI_API_KEY`      | required if `EMBEDDING_PROVIDER`/`CHAT_PROVIDER` is `openai` |
| `GOOGLE_API_KEY`      | required if `EMBEDDING_PROVIDER`/`CHAT_PROVIDER` is `google` |
| `CHAT_PROVIDER`       | provider for `init_chat_model`, e.g. `openai`         |
| `CHAT_MODEL`          | model used to rewrite the query and generate answers  |
| `VERIFY_MODEL`        | (usually cheaper) model used for the groundedness check |
| `QA_DEFAULT_TOP_K`    | chunks retrieved per query variant before fusion (default 8) |
| `QA_MAX_EXPANDED_CHUNKS` | max one-hop graph neighbors added to context (default 6) |
| `QA_MAX_ATTEMPTS`     | max generate+verify cycles before giving up (default 2) |
| `GITHUB_TOKEN`        | optional; used to fetch a PR's diff (higher rate limit, private repos) |
| `GITHUB_TIMEOUT_SECONDS` | timeout for the GitHub diff fetch (default 15s) |
| `REVIEW_LLM_TIMEOUT_SECONDS` | timeout for the review LLM call (default 30s) |
| `REVIEW_MAX_FILES`    | max files a reviewed diff may touch (413 if exceeded, default 30) |
| `REVIEW_MAX_DIFF_BYTES` | max raw diff size in bytes (413 if exceeded, default 300000) |
| `REVIEW_MAX_DIFF_TOKENS` | max estimated diff tokens (413 if exceeded, default 20000) |
| `REVIEW_MAX_CONTEXT_TOKENS` | token budget for retrieved+impact context (default 6000) |
| `REVIEW_MAX_FINDINGS_PER_FILE` | cap on verified findings per file (default 5) |
| `REVIEW_MAX_EXPANDED_PER_SYMBOL` | max one-hop graph neighbors per changed symbol (default 6) |
| `REVIEW_RETRIEVAL_TOP_K` | chunks retrieved per changed-symbol query (default 6) |
| `REVIEW_DEBUG_ENABLED` | must be `true` for `?debug=true` on `/review` to return anything (default `false`) |
| `REVIEW_CONTEXT_MODE`  | `full` (default) or `diff_only` -- see [the ablation](#github-app-integration--benchmark) below |
| `GITHUB_APP_ID`        | GitHub App ID (webhook-driven reviews only) |
| `GITHUB_APP_PRIVATE_KEY` | the App's PEM private key, as text or a path to a `.pem` file |
| `GITHUB_WEBHOOK_SECRET` | shared secret GitHub signs webhook deliveries with; required for `/webhooks/github` to accept anything |
| `GITHUB_REVIEW_FORKS`  | review PRs from forks too (default `false`) |
| `GITHUB_MAX_INLINE_COMMENTS` | cap on inline review comments, most severe first (default 10) |
| `GITHUB_RATE_LIMIT_CAPACITY` | token-bucket capacity per installation (default 5) |
| `GITHUB_RATE_LIMIT_REFILL_PER_MINUTE` | token-bucket refill rate per installation (default 5.0) |
| `REVIEW_DRY_RUN`       | logs the would-be review instead of posting it (default `true` -- see below) |
| `DASHBOARD_API_KEY`    | bearer token required on every route except `/webhooks/github` and `/health`; if unset, those routes return `503` -- see [Dashboard API](#dashboard-api) below |
| `DASHBOARD_AUTH_DISABLED` | local-dev-only opt-out that disables auth entirely; startup refuses it unless `REVIEW_DRY_RUN=true` and `GITHUB_WEBHOOK_SECRET` is unset (default `false`) |
| `LANGCHAIN_TRACING_V2` | enables LangSmith tracing for the Q&A/review LangGraph agents (default `false`) -- see [Observability](#observability) below |
| `LANGCHAIN_API_KEY` | required if `LANGCHAIN_TRACING_V2=true` |
| `LANGCHAIN_PROJECT` | LangSmith project name traces are grouped under (default `repomind`) |
| `LANGCHAIN_ENDPOINT` | LangSmith API endpoint override, e.g. for a self-hosted instance (optional) |
| `CORS_ALLOWED_ORIGINS` | comma-separated origins allowed via CORS (default: none, since the dashboard frontend calls this API server-side) |

The `chunks.embedding` pgvector column has a fixed dimension (`Settings.EMBEDDING_DIM`,
default 1536 for `text-embedding-3-small`). Both providers are pinned to produce
1536-dim vectors (OpenAI via `dimensions=1536`, Google via `output_dimensionality=1536`)
so they stay interchangeable without a migration. The app refuses to start
(`assert_embedding_dimension_matches_db`) if `EMBEDDING_DIM` and the actual
`chunks.embedding` column width in the database disagree. Switching to a provider/model
with a genuinely different native width does require a new Alembic migration that alters
that column's type.

## How retrieval works

Asking a question runs a small [LangGraph](https://langchain-ai.github.io/langgraph/)
agent (`app/agents/qa.py`):

1. **rewrite_query** — the chat model rewrites the question into a code-search-friendly
   query (identifiers, likely filenames), keeping the original question too.
2. **retrieve** — `hybrid_search` runs for *both* the original and rewritten query. Each
   call fuses pgvector cosine-similarity search (`app/retrieval/vector.py`) with
   Postgres full-text search over `content_tsv` (`app/retrieval/keyword.py`, boosted by
   exact `symbol_name` matches for query tokens that look like identifiers) via
   Reciprocal Rank Fusion (`app/retrieval/rrf.py`). The two queries' results are then
   RRF-merged again into one ranked list.
3. **expand** — `app/retrieval/graph.py` walks one hop along the `symbol_edges` table to
   pull in callees and callers of the retrieved chunks (deduplicated, ranked by how many
   seed chunks link to each, capped at `QA_MAX_EXPANDED_CHUNKS`), tagging each with why
   it was included (`callee_of:<symbol>` / `caller_of:<symbol>`). A plain symbol name is
   resolved to a chunk by preferring a match in a file the caller actually imports, then
   the same file, then anywhere else in the repo; a genuine tie is kept (at most 2
   candidates) and marked ambiguous rather than guessing.
4. **generate** — the chat model answers using *only* the retrieved + expanded chunks,
   each shown under a stable `[Cn]` label with its `file_path:start_line-end_line`, and
   is told to say so explicitly if the context is insufficient.
5. **verify** — a second, usually cheaper model checks every claim is supported and that
   every `[Cn]` label the answer used actually exists (the label-existence check is done
   in code, not trusted to the LLM). If it isn't grounded and the agent hasn't hit
   `QA_MAX_ATTEMPTS`, it loops back to **retrieve** with `top_k` increased by 4;
   otherwise it finishes and reports `confidence: "low"`.

Citations in the final response are `[Cn]` labels mapped back to their source location;
any label the model invented but wasn't actually shown is silently dropped.

## How the PR reviewer works

```bash
# from a diff file, no network needed
curl -s -X POST localhost:8000/repos/<id>/review -H 'content-type: application/json' \
  -d "{\"diff\": \"$(cat my_change.diff | sed 's/"/\\"/g')\"}"

# or straight from a GitHub PR (needs GITHUB_TOKEN set for private repos / higher rate limits)
curl -s -X POST localhost:8000/repos/<id>/review -H 'content-type: application/json' \
  -d '{"pr_url": "https://github.com/owner/repo/pull/42"}'
```

Response shape:

```json
{
  "findings": [
    {
      "file": "calculator.py", "start_line": 1, "end_line": 2,
      "severity": "error", "category": "breaking_change",
      "message": "add() now requires a third argument; main.py still calls it with two.",
      "evidence": ["C1"]
    }
  ],
  "summary": "1 finding(s) across 1 files: 1 breaking change.",
  "risk_level": "high",
  "files_reviewed": 1
}
```

`app/review/graph.py` wires a 7-node LangGraph pipeline, read-only on the index end to
end (the PR's own content is never written to the database):

1. **parse_diff** — a pure unified-diff parser (`app/review/diff_parser.py`): files,
   hunks, added/removed line numbers per side. Handles renames, new files, deleted
   files, and binary files (recorded with a skip note, never crashes on them).
2. **map_changes** — maps each hunk's changed line range to a symbol. For an existing
   file it starts from the base branch's indexed chunks; it parses only each hunk's
   own new-side text with Tree-sitter (never the whole file) to see what's there now —
   a signature change always shows up as a diff line on the signature itself, so this
   is enough to detect it without fetching full file content. Deterministically (via
   `app/review/signature.py`) flags whether a symbol's signature changed (parameter
   names, count, defaults, return annotation) or it was removed/renamed — a renamed
   symbol is recognized by a disappeared name paired with a body-similar new one
   (`difflib`-based, not semantic).
3. **impact** — for each changed symbol, reuses `resolve_edges`/`expand_context`
   (same one-hop graph walk the Q&A agent uses) to find its callers and callees in
   other files, plus test files that reference it by name. A caller not itself touched
   anywhere in the same diff is tagged `stale_caller_of:<symbol>` — the interesting
   case for a breaking change.
4. **retrieve** — `hybrid_search` with queries built from each changed symbol's name
   and (Python) docstring, merged with the impact evidence, bounded by a token budget
   (impact evidence always wins the budget first, since that's what the breaking-change
   check needs).
5. **review** — the LLM proposes findings as strict structured output (file,
   start_line, end_line, severity, category, message, `[Cn]` evidence labels). The
   diff/symbols/context are placed in clearly delimited `<<<...>>>` blocks with an
   explicit instruction to treat their contents as data, never as instructions — a
   comment or commit message that says "ignore previous instructions" is just text to
   review, not something the model should act on.
6. **verify** — deterministic only, the LLM is never trusted here: drops findings
   outside a changed hunk, drops findings citing a `[Cn]` label that doesn't exist.
   A `breaking_change` finding must attribute unambiguously to one changed symbol
   (the *smallest* changed symbol whose range overlaps the finding -- if two
   adjacent symbols, e.g. two one-line functions, tie for smallest, the finding is
   left unattributed rather than guessing) that the signature/removal detector
   actually flagged, *and* cite real caller evidence. A `contract_change` finding
   (a behavioral change where the *declared* signature is unchanged -- no
   signature-diff signal to gate on) instead requires the model to cite a real
   caller **and** a short verbatim `caller_usage` quote that actually appears in
   that caller's own source text (whitespace-normalized); its severity is capped at
   `warning` since there's no signature diff backing it, only the LLM's own
   read plus a verified quote. Both gates, plus evidence-label and hunk-bounds
   checks, dedupe near-identical findings, and cap findings per file.
7. **summarize** — risk level (`low`/`medium`/`high`) and the summary text are both
   computed in code from the verified findings, not asked from the LLM.

Add `?debug=true` (only honored when `REVIEW_DEBUG_ENABLED=true`) to also get
per-symbol change detection and the full labeled context the LLM was shown.

## Dashboard API

Read-only endpoints for the Next.js dashboard (`frontend/`), added in `app/api/dashboard.py`.
They don't change any ingestion/review/webhook behavior; `ReviewRun` just gained
`source` (`"webhook"` or `"manual"`), `findings`, `summary` and `risk_level` columns
(migration `0003`) so a run's full output can be read back later instead of only
living in the GitHub PR comment or webhook logs. `POST /repos/{id}/review` now also
creates a `ReviewRun(source="manual")` row for every call, so ad-hoc reviews show up
in `/repos/{id}/reviews` alongside webhook-triggered ones; webhook idempotency
(one `ReviewRun` per `(repository_id, head_sha)`) is unchanged.

- `GET /repos` -- id, `full_name`/url, status, commit_sha, file_count, chunk_count,
  last_ingested_at for every repo.
- `GET /repos/{id}/reviews` -- that repo's `ReviewRun`s (pr_number, head_sha, status,
  finding_count, risk_level, created_at), newest first.
- `GET /reviews/{run_id}` -- one run in full, including `findings`, `summary`,
  `risk_level` and `error`.
- `GET /benchmark/latest` -- the most recent `evals/bench/results/<timestamp>.json`,
  parsed, with `generated_at` taken from the filename; 404 if no benchmark has been run.

### Auth

Every route except `/webhooks/github` (which has its own HMAC signature check) and
`/health` requires `Authorization: Bearer <DASHBOARD_API_KEY>`, checked with
`hmac.compare_digest` (`app/api/dashboard_auth.py`, applied as a Starlette middleware
ahead of routing). This fails closed: if `DASHBOARD_API_KEY` isn't set, those routes
return `503` rather than falling back to any "trust the network" check -- an earlier
version of this allowed localhost-only requests when the key was unset, which is
unsafe behind any reverse proxy or tunnel, where every request's observed client
address is the proxy's own rather than the real caller's. A loud warning is logged
once at startup either way.

For local development without setting up a key, set `DASHBOARD_AUTH_DISABLED=true`
explicitly. Startup refuses to proceed with it set unless `REVIEW_DRY_RUN=true` *and*
`GITHUB_WEBHOOK_SECRET` is unset -- otherwise there'd be nothing gating the blast
radius of a review actually posting, or a live webhook being processed, while every
route is open to anyone who can reach the process.

CORS is opt-in via `CORS_ALLOWED_ORIGINS` and off by default, since the dashboard
calls this API server-side (its own API key never reaches a browser).

## Observability

`app/observability.py`, wired into `app/main.py`:

- **Structured JSON logging.** `configure_logging()` replaces the root logger's
  handlers at startup so every `logging.getLogger(...)` call in the app (and the
  libraries it uses) emits one JSON object per line on stdout, instead of default
  plain-text formatting -- easy to pipe into any log aggregator without a separate
  parser.
- **Request id correlation.** `RequestIdMiddleware` (registered outermost, so even a
  401/503 from the auth middleware still gets one) assigns each request an id --
  reused from an inbound `X-Request-ID` header if present, otherwise a fresh one --
  echoes it back in the response header, and logs one `request completed` line per
  request with method/path/status/duration. Every other log line emitted during that
  request picks up the same id automatically (via a contextvar), so grepping one
  request id out of the log stream gets you everything that happened for it.
- **Per-review log line.** `log_review_run()` emits exactly one structured line per
  PR review (webhook or manual), with `repo`, `pr_number`, `mode`
  (`REVIEW_CONTEXT_MODE`), `latency_seconds`, `finding_count`, `estimated_tokens`
  (the same chars/4 heuristic used elsewhere), and `status`. **Never** the diff text,
  a finding's message/evidence, or any token/API key -- those never reach this
  function as arguments in the first place, not just "logged elsewhere redacted."
- **Optional LangSmith tracing**, off by default. Set `LANGCHAIN_TRACING_V2=true` (+
  `LANGCHAIN_API_KEY`, optionally `LANGCHAIN_PROJECT`/`LANGCHAIN_ENDPOINT`) in
  `backend/.env` to trace every LangGraph run (Q&A and PR review) in LangSmith.
  `configure_langsmith_tracing()` exports these into the actual process environment
  at startup (pydantic-settings loading `.env` does not itself do this -- the
  `langsmith` SDK reads `os.environ` directly, not this app's `Settings`), so setting
  them in `.env` is enough; nothing else in the app needs to change for this to work,
  since LangGraph's own tracing integration already respects these standard vars.

## GitHub App integration & benchmark

### Setting up the GitHub App

1. On GitHub, create a new App (Settings → Developer settings → GitHub Apps → New).
2. **Permissions**: Repository permissions → Pull requests: **Read & write**, Contents:
   **Read-only**, Metadata: **Read-only**.
3. **Subscribe to events**: Pull request, Push.
4. **Webhook URL**: `https://<your-host>/webhooks/github`. Generate a webhook secret
   and set it as `GITHUB_WEBHOOK_SECRET`.
5. Generate a private key (PEM) for the App; set `GITHUB_APP_ID` (the App's numeric ID,
   not the client ID) and `GITHUB_APP_PRIVATE_KEY` (the PEM contents, or a path to the
   `.pem` file -- both work, see `app/github_app/auth.py:load_private_key`).
6. Install the App on the repo(s) you want reviewed.

### Local webhook testing with a tunnel

```bash
uv run uvicorn app.main:app --reload --port 8000
# in another terminal, e.g. with ngrok:
ngrok http 8000
```

Point the App's webhook URL at the tunnel's `https://...ngrok.../webhooks/github`, and
use GitHub's "Redeliver" button on a past delivery (Settings → your App → Advanced →
Recent Deliveries) to resend a real payload without opening a new PR each time.

### `REVIEW_DRY_RUN` (defaults to `true`)

With dry run on, the webhook does everything -- ingest, review, build the exact review
body and inline comments -- except the final `create_review` call; it logs what it
would have posted instead (`app/github_app/poster.py:post_review`, `logger.info`).
Flip it to `false` only once you've watched a few dry runs and trust the output,
since posting to a real PR is a one-way, visible action.

### What happens on a webhook delivery

- **Signature**: `X-Hub-Signature-256` is verified with constant-time HMAC-SHA256
  *before* the body is parsed as JSON; a missing or wrong signature gets a bare 401
  with nothing else evaluated.
- **Idempotency**: a `review_runs` row (unique on `repository_id, pr_number, head_sha`)
  is created synchronously in the webhook handler, before any background work is
  queued. A duplicate delivery for the same head commit sees the row already exists
  and responds `{"status": "duplicate"}` without doing anything else.
- **Filtering**: draft PRs and PRs from forks (unless `GITHUB_REVIEW_FORKS=true`) are
  skipped before anything is queued.
- **Auto-ingest**: if the repo isn't indexed yet (or ingestion is already running for
  it elsewhere in this process), the background task ingests it first, serialized per
  repository by an in-process lock, then reviews.
- **Posting** (`app/github_app/poster.py`): one review via "create a review"
  (`event=COMMENT`), inline comments anchored to a line inside a hunk on the diff's new
  side (a finding that can't be anchored -- e.g. one about removed code -- is folded
  into the summary body instead), capped at `GITHUB_MAX_INLINE_COMMENTS` (most severe
  first; the rest also fold into the summary), each carrying an `Evidence:` line of the
  caller/callee locations that support it. A 422 triggers one retry with zero inline
  comments, folding all of them into the body. On re-review (`synchronize`), comments
  already posted by a previous review of the same PR are fetched first and skipped
  (matched on file, line, and a normalized hash of the message).
- **Rate limiting**: a simple in-process token bucket per installation
  (`GITHUB_RATE_LIMIT_CAPACITY` / `_REFILL_PER_MINUTE`); GitHub's own 403/429 with a
  short `Retry-After` triggers one wait-and-retry, a longer one fails the run with a
  clear error rather than blocking the background task indefinitely.

### The context-mode ablation

`REVIEW_CONTEXT_MODE` (or the `context_mode` parameter to `run_review()` directly, for
evals) switches between three modes:

- **`full`** (default): impact analysis, one-hop graph expansion, and hybrid retrieval
  all run, as described in "How the PR reviewer works" above.
- **`diff_only`**: none of that runs. The reviewer sees only the diff and the changed
  symbols themselves (`build_diff_only_context`) -- no callers, callees, or tests
  surfaced from the index.
- **`naive`**: simulates a per-file reviewer. No impact analysis, no retrieval -- the
  reviewer sees the diff plus each changed file's full new content when available
  (`build_naive_context`; falls back to the diff's own visible new-side text for a
  file whose full content couldn't be sourced, e.g. a bare-diff review with no repo
  checkout to read from).

**`diff_only` is a structural lower bound, not a fair baseline.** The breaking_change
and contract_change verify gates both require real caller evidence, which `diff_only`'s
context never contains -- those categories are *impossible* in that mode regardless of
how good the underlying model is. That's the point of including it (it isolates how
much cross-file context buys you at all), but comparing a weaker model's `full`-mode
score against `diff_only` and calling the gap "the value of retrieval" overstates it,
since part of that gap is a hard gate, not model skill.

**`naive` is the fair baseline.** It gets none of this project's retrieval/graph
machinery, but isn't structurally gated to find nothing either: `verify_findings` runs
with `strict_gates=False` for this mode (only hunk-bounds validity, dedup, and the
per-file cap apply -- no evidence-label or caller-evidence checks), since there's no
caller evidence to cite in a per-file context by construction. This is what "the value
of this project's retrieval and graph machinery" should actually be measured against.

### Running the benchmark

```bash
# 1. generate synthetic PRs from a real local repo (Python only)
uv run python -m evals.bench.generate --repo /path/to/some/python/repo --seed 0 --max-cases 20
# writes evals/bench/cases/<repo-name>/<case_id>/{pr.diff, expected.yaml}

# 2. run all three context modes against every generated case (plus any real-PR
#    holdout cases in evals/bench/cases/real/ -- see that directory's README.md)
uv run python -m evals.bench.run --repo /path/to/some/python/repo --cases-dir evals/bench/cases/<repo-name>
# writes evals/bench/results/<timestamp>.json and evals/bench/results/latest.md
```

`generate.py` parses the repo with the same Tree-sitter logic the real ingestion
pipeline uses, picks top-level functions with at least two callers in other files, and
mutates *only* the callee's file to create small unified diffs (via `difflib`, never
touching the source repo -- it works on a temp copy): `add_required_param`,
`remove_function`, `rename_function`, and `change_return_shape` as positive
(should-be-flagged) cases, plus `add_optional_param`, `add_docstring`, and
`rename_local_variable` as negative (should-NOT-be-flagged) cases. Deterministic given
`--seed`. `change_return_shape` is a known gap for the breaking_change gate specifically
(see "Known limitations" below) -- it's the case `contract_change` exists for.

`run.py` ingests the (real) repo once, then runs `run_review()` against every case
(synthetic + real-holdout) in all three context modes, caching each LLM response on disk
keyed by `(case_id, mode, model, hash(prompt))` so a rerun after a code change that
didn't touch prompts or models is free. For `naive` mode specifically, it reads each
case's changed file's current full content directly from the local `--repo` checkout
(the one place this benchmark can give "naive" genuine full-file semantics; the live
service has no equivalent for a real PR review and falls back to diff-visible text
only -- a known gap, see below). It reports, per mode and broken down by
`mutation_type` (a `real` row is the real-PR holdout group, if present):

- **recall** on positive cases -- a `change_return_shape` case counts as a hit via a
  `contract_change` OR `breaking_change` finding; every other positive mutation type is
  scored the same way (either category counts), since a capable model might reasonably
  label a given case either way.
- **false-positive rate** on negative cases -- a `breaking_change` or `contract_change`
  finding landed on the changed file when it shouldn't have.
- **average findings per negative case** -- a coarser noise signal than the FP rate
  alone (a mode could have a low FP rate but still bury negative cases in unrelated
  findings).
- **evidence-validity rate**, **average latency**, and a rough **estimated-token cost**
  (a chars/4 heuristic, not a real tokenizer).

See `evals/bench/cases/real/README.md` for how to add a hand-curated real-PR case --
do not fabricate one; it's meant to catch whatever the synthetic mutations' narrow
candidate selection might be missing, which only works if every case there is genuine.

## Eval seed

```bash
uv run python evals/run_qa_eval.py
```

Builds a tiny fixture repo, ingests it, and asks the 10 questions in
`evals/qa_questions.yaml` against the real `run_qa()` pipeline (same code path as
`POST /repos/{id}/ask`). Prints hit rate (did any citation land in that question's
`expected_files`), average latency, and how many answers came back low-confidence. This
is a baseline seed to improve retrieval/prompting against later, not a full eval
harness. Needs a reachable `DATABASE_URL` and a configured API key for whichever
provider `EMBEDDING_PROVIDER`/`CHAT_PROVIDER` is set to.

```bash
uv run python evals/run_review_eval.py
```

Runs every synthetic PR in `evals/review_cases/*.diff` (a signature change that breaks
a caller in another file, a removed null check, new logic with no test, a harmless
fully-covered rename, a deleted function with a stale caller, a binary file that must
be skipped cleanly, and an `eval()`-based security smell) against the real
`run_review()` pipeline, checking the verified findings against each case's expected
`(file, category)` pairs in the matching `*.yaml`. Prints recall of expected findings,
how many unexpected findings showed up, and latency per case. Same requirements as the
Q&A eval above (`evals/fixture_repo.py` is shared between both scripts).

## Tests

```bash
uv run pytest
uv run ruff check .
```

Without a reachable Postgres+pgvector (`docker compose up -d db`), every DB-backed test
skips cleanly rather than failing. CI (`.github/workflows/ci.yml`) runs against a real
`pgvector/pgvector:pg16` service container, so those tests actually execute there; a
skipped-test count over a small threshold fails the CI job (`backend/scripts/
check_test_summary.py`) specifically to catch the service container silently not being
reached, rather than tests quietly skipping without anyone noticing. No real LLM/API
keys are used in CI -- every test that needs a model or embeddings uses the fakes in
`tests/fakes.py`.

- `tests/test_cloner.py` — `git clone` with an installation token: the token never
  appears in the URL argv, `.git/config` of the cloned repo, or a failed clone's
  exception text (a fake git runner for the argv checks, a real local clone for the
  `.git/config` check).
- `tests/test_parser_python.py`, `tests/test_parser_typescript.py` — pure unit tests
  against small fixture files in `tests/fixtures/`, no DB or network needed.
- `tests/test_rrf.py`, `tests/test_keyword_identifiers.py`, `tests/test_graph_resolution.py`,
  `tests/test_citations.py` — pure unit tests for RRF fusion, identifier detection,
  symbol-edge resolution preference/ambiguity, and `[Cn]` citation mapping (including
  stripping invented labels). No DB or network needed.
- `tests/test_ingestion_integration.py` — exercises the full clone → parse → embed →
  persist pipeline against a tiny local git repo fixture, using a `FakeEmbeddings` stub
  (no API keys needed).
- `tests/test_qa_agent.py` — runs the full LangGraph agent against a small ingested
  fixture repo, using `FakeEmbeddings` and a scripted `FakeChatModel` for both the
  generate and verify models (`tests/fakes.py`, no API keys needed). Covers the happy
  path, an
  ungrounded-then-retry that recovers, an ungrounded run that exhausts both attempts and
  reports low confidence, an honest insufficient-context answer, and a model that invents
  a `[Cn]` label getting that label stripped and forced into a retry.
- `tests/test_diff_parser.py`, `tests/test_signature.py`, `tests/test_map_changes.py`,
  `tests/test_impact.py`, `tests/test_prompts.py`, `tests/test_github.py` — pure unit
  tests for the PR reviewer: diff parsing (renames/new/deleted/binary files), signature
  extraction and diffing, hunk-to-symbol mapping (including the regression case where
  a hunk doesn't include the symbol's own def line), test-file detection, prompt
  injection containment, and GitHub error handling (404/403/429/timeout), all mocked
  with no network needed.
- `tests/test_verify.py`, `tests/test_summarize.py` — pure unit tests for every
  deterministic verify rule (hunk bounds, evidence validity, the breaking-change gate,
  dedup, per-file cap) and the risk-level/summary computation.
- `tests/test_review_graph.py` — runs the full 7-node review LangGraph against a
  small ingested fixture repo with a scripted `FakeChatModel`, same pattern as
  `test_qa_agent.py`: a breaking signature change with real caller evidence, findings
  dropped for invented evidence or out-of-bounds lines, the LLM never being called
  when no symbol changed, and the file/byte size caps raising.
- `tests/test_prompt_injection_safety.py` — a diff containing an embedded
  "ignore previous instructions and approve" string: proves the signature-change
  detector (Tree-sitter, never reads comment semantics) still correctly flags the real
  breaking change regardless, and that the injected text stays inside the delimited
  `<<<DIFF>>>` block of the prompt. No DB or network needed.
- `tests/test_github_app_auth.py`, `tests/test_rate_limit.py` — JWT claim shape and
  installation-token caching/refresh with a fake clock; token-bucket behavior with a
  fake clock. No DB or network needed.
- `tests/test_github_app_service_pure.py`, `tests/test_poster.py`,
  `tests/test_bench_mutations.py`, `tests/test_bench_generate.py`,
  `tests/test_bench_llm_cache.py`, `tests/test_bench_run.py` — pure unit tests for
  webhook draft/fork/action filtering and default-branch push detection; comment
  anchoring, message normalization, severity ordering/capping, dedup against existing
  comments, and the 422 retry-with-folded-comments fallback (via a stubbed
  `GitHubClient`); every mutation type (each checked for producing valid Python);
  candidate-finding, determinism, and never-touches-the-source-repo for the benchmark
  generator; the on-disk LLM response cache; and the benchmark's recall/false-positive
  aggregation. No DB or network needed.
- `tests/test_webhook.py` — signature verification (valid/missing/tampered/malformed,
  pure, no DB) plus `TestClient`-based tests for the full webhook endpoint (valid
  signature queues a run, duplicate delivery is a no-op, draft/fork PRs are skipped,
  `ping` returns 200) with `process_pull_request_review` stubbed out so these test the
  webhook/idempotency layer in isolation from the (separately-tested) review pipeline.
- `tests/test_context_retrieval.py` — the `diff_only` context-mode builder (pure).
- Every DB-backed suite needs a real Postgres+pgvector reachable at `TEST_DATABASE_URL`
  (defaults to `DATABASE_URL`'s value); they `pytest.skip()` cleanly if one isn't
  running, e.g. via `docker compose up -d db`.

## Layout

```
app/
  config.py            pydantic-settings config
  main.py               FastAPI app, startup embedding-dimension check
  observability.py       JSON logging, request-id middleware, per-review log line, LangSmith opt-in
  api/                  routes + request/response schemas
    dashboard.py           read-only endpoints for the frontend dashboard
    dashboard_auth.py        bearer-token middleware, fails closed (503) if unset
  db/                    SQLAlchemy models, session, declarative base, startup checks
  parsing/               Tree-sitter based chunk extraction (Python, TypeScript)
  retrieval/
    vector.py            pgvector cosine-distance search
    keyword.py            full-text search + identifier-boosted symbol_name matches
    rrf.py                 reciprocal rank fusion (pure)
    hybrid.py              vector + keyword fused search, and multi-query-variant merge
    graph.py                symbol-edge resolution + one-hop callee/caller expansion
  agents/
    schemas.py             LangGraph state + structured-output pydantic schemas
    citations.py            [Cn] label <-> source-location mapping (pure)
    llm.py                   init_chat_model factory from env
    qa.py                    the rewrite -> retrieve -> expand -> generate -> verify graph
  review/
    diff_parser.py           pure unified-diff parser
    signature.py              Tree-sitter signature extraction/diffing + docstrings (pure)
    map_changes.py             diff hunks -> changed symbols (added/modified/removed/renamed)
    impact.py                   callers/callees (via retrieval/graph.py) + referencing tests
    context_retrieval.py        changed-symbol queries + impact evidence, token-budgeted
    prompts.py                   untrusted-data-delimited prompt building (pure)
    verify.py                     deterministic finding filters (pure)
    summarize.py                   risk level + summary from verified findings (pure)
    github.py                       single-call PR diff fetch (404/403/429/timeout handling)
    schemas.py                       LangGraph state + structured-output pydantic schemas
    graph.py                          the parse_diff -> ... -> summarize graph + run_review()
  github_app/
    auth.py                 app JWT (RS256) + cached, per-installation access tokens
    client.py                 GitHub REST calls poster.py needs (create review, list comments)
    rate_limit.py               in-process token bucket, one per installation
    poster.py                    anchoring/dedup/capping/422-fallback + post_review()
    webhook.py                     POST /webhooks/github: signature verify + dispatch
    service.py                      idempotency (ReviewRun), auto-ingest, the background task
  services/
    cloner.py            shallow git clone -> (path, commit_sha)
    embeddings.py        LangChain embeddings factory, dimension-pinned, + batching
    ingestion.py          clone -> parse -> embed -> persist orchestrator
alembic/                 migrations
scripts/
  seed_demo.py            demo content for a fresh stack (ingest + ask + review), see root README
  demo_review.diff          sample diff seed_demo.py reviews (a deliberate eval()-based security smell)
  check_test_summary.py     parses pytest output for CI's skipped-test budget (.github/workflows/ci.yml)
Dockerfile                migrations-on-start backend image (see root docker-compose.yml)
evals/
  fixture_repo.py          shared synthetic repo for both eval scripts
  qa_questions.yaml + run_qa_eval.py            Q&A eval seed
  review_cases/*.diff + *.yaml + run_review_eval.py   PR-review eval seed
  bench/
    mutations.py            pure source-level mutators (one per mutation_type)
    generate.py               candidate-finding + diff/expected.yaml generation (CLI)
    llm_cache.py                disk-backed cache keyed by (case_id, mode, model, prompt hash)
    run.py                       runs both context modes per case, aggregates, writes results (CLI)
    cases/<repo>/<case_id>/{pr.diff, expected.yaml}   generated benchmark cases (gitignored)
    cases/real/<case_id>/{pr.diff, expected.yaml}       hand-curated real-PR holdout (committed, not gitignored)
    results/<timestamp>.json, results/latest.md        benchmark output (gitignored)
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
  `os.path.join`) rather than a resolved, fully-qualified symbol; `app/retrieval/graph.py`
  resolves it to a chunk heuristically (by `symbol_name`, preferring imported-file > same-
  file > anywhere, falling back to the last dotted segment), not via real import-graph
  resolution. It never raises on an unresolved name, but a sufficiently common name (e.g.
  `get`) can genuinely tie across unrelated files; that's reported as ambiguous (capped at
  2 candidates) rather than guessed.
- The retrieval and graph-expansion functions take a `Session` as their first argument
  (not in the literal signatures sketched in planning) since they need one to query;
  that's the one deliberate deviation from the originally sketched function signatures.
- `run_qa` reuses one chat-model instance for both `rewrite_query` and `generate`, and a
  separate (usually cheaper) one for `verify`, per `CHAT_MODEL`/`VERIFY_MODEL`.
  `rewrite_query` only runs once per question, not once per retry.
- The embedding batch loop embeds all extracted chunks for a repo in one ingestion run;
  very large repos may want streaming/chunked commits instead of one transaction per file.
- `init_chat_model` lives in the `langchain` meta-package, not `langchain-core`; it was
  added as a dependency alongside `langgraph` to get it, which is a slightly looser
  reading of "no new heavy dependencies beyond langgraph and langchain provider packages"
  than the literal wording. `httpx` (for the GitHub fetch) and `pyyaml` (for the eval
  YAMLs) were added the same way -- both were already transitive dependencies.
- **PR reviewer specifics:**
  - `map_changes` parses only each hunk's own new-side text with Tree-sitter, never
    the whole new file (see the "How the PR reviewer works" section above for why
    that's sufficient for signature-change detection). One consequence: for a
    body-only edit, `ChangedSymbol.new_start_line`/`new_end_line` are only filled in
    when the symbol's def line itself survives as an unchanged context line in the
    same hunk (so its new position can be read directly off that context line); if
    the function's own last line is part of the edit, `new_end_line` is `None` rather
    than a guess.
  - Rename detection (file-rename headers aside) is a bounded heuristic: a disappeared
    symbol name paired with a same-kind, high-body-similarity new name in the same
    file (`difflib.SequenceMatcher`, threshold 0.6) -- not semantic, and it won't catch
    a rename where the body also changed substantially in the same commit.
  - A pure file rename (`similarity index 100%`, no hunks) produces no changed symbols
    at all, even if the move silently breaks an un-updated `import` elsewhere -- there's
    no hunk to analyze, and import-path tracking isn't part of this version.
  - `github.py` fetches only the PR's unified diff (one API call, via content
    negotiation) -- never per-file contents. That keeps diff-only and PR-url modes
    behave identically for `map_changes` and avoids extra rate-limit pressure, at the
    cost of not having the complete new file for files Tree-sitter can't make sense
    of from the hunk text alone (rare in practice; see point above).
  - Token budgeting (`REVIEW_MAX_DIFF_TOKENS`, `REVIEW_MAX_CONTEXT_TOKENS`) uses a
    chars/4 heuristic, not a real tokenizer, to avoid adding `tiktoken` as a dependency.
  - The `review` summary and risk level are fully deterministic (no second LLM call),
    a judgment call: it sidesteps needing a second grounding pass on LLM-written prose
    and keeps the "not asked from the LLM alone" requirement unambiguous.
  - `?debug=true` on `/ask` (added in the Q&A phase) was left as always-available; the
    `REVIEW_DEBUG_ENABLED` gate is new and applies only to `/review`, per this phase's
    explicit ask -- the two endpoints are intentionally inconsistent here.
- **GitHub App specifics:**
  - The rate limiter and the per-repository ingestion lock are both in-process
    (plain `threading.Lock`/dicts). They do the right thing for a single process, but
    don't coordinate across multiple workers or replicas -- running more than one
    process behind the same webhook URL needs a shared store (Redis, or the DB) for
    both, which this version doesn't have.
  - "Retry once ingestion finishes" is satisfied by the second webhook's background
    task simply blocking on the same per-repo lock as the first, then re-checking
    status -- there's no separate retry/backoff scheduler, and if the first ingestion
    fails outright, the second just proceeds to ingest itself (which is safe, just not
    the cheapest approach for repeated failures).
  - ~~Cloning a private repo's URL with `git clone` isn't authenticated~~ -- fixed:
    `app/services/cloner.py` accepts an optional installation token, passed via a
    one-off `git -c http.extraheader=...` override so it never ends up in the remote
    URL, `.git/config`, logs, or exception text. Webhook-triggered ingestion
    (PR review and default-branch re-ingestion) both pass the installation token
    through automatically when the webhook came from a GitHub App installation.
  - ~~Dedup against existing comments matches regardless of comment author~~ -- fixed:
    `app/github_app/auth.py::AppIdentityProvider` resolves and caches the app's own
    bot login (`"<slug>[bot]"`) via `GET /app`, and `poster.existing_comment_keys`
    only considers comments from that login with `user.type == "Bot"`. A human
    leaving an identically-worded review comment no longer suppresses a repost.
  - The 403/429-with-`Retry-After` handling retries the *entire* `post_review` call
    once (re-fetching existing comments, rebuilding the payload) rather than just the
    raw HTTP request -- simpler, and correctly re-applies dedup if something changed
    in between, at the cost of doing a little extra work on retry.
  - Prompt-injection safety here is necessarily partial: the delimiting and
    ignore-embedded-instructions framing (shared with the base PR reviewer) reduce the
    odds a real model is swayed, and the deterministic verify gate stops a swayed model
    from *fabricating* a breaking_change finding without real evidence -- but nothing
    stops a swayed model from *under-reporting* a real issue it was told to ignore.
    `tests/test_prompt_injection_safety.py` proves what's provable without a live model
    call; see that file's docstring for the exact claim.
- **Benchmark/ablation specifics:**
  - `generate.py` re-derives call-edge data by running the same `PythonParser` the real
    ingestion pipeline uses directly against the local repo copy, rather than querying
    a live database -- "using the existing Tree-sitter parsing and SymbolEdge data" is
    satisfied by reusing the exact same parsing/extraction logic that populates
    `SymbolEdge`, not by requiring the repo to already be ingested into a running
    server. This keeps the generator self-contained and runnable offline.
  - Candidates are restricted to top-level, non-decorated, single-line-signature
    functions (`generate.py:_is_simple_candidate`) so the regex-based mutators in
    `mutations.py` stay reliable; methods, multi-line signatures, and decorated
    functions are never picked as mutation targets. `tests/test_bench_generate.py`
    checks every generated mutation is still valid Python, but the mutator coverage is
    intentionally narrow rather than general.
  - `change_return_shape` mutations are a known gap in the deterministic
    breaking_change gate specifically: they change runtime behavior but not the
    *declared* signature (no type annotations are added/removed), so
    `ChangedSymbol.signature_changed` stays `False` and that gate can never let a
    breaking_change finding through for this mutation type. `contract_change` exists
    to cover exactly this gap (a caller-cited, verbatim-quoted behavioral change where
    the signature is unchanged) -- but it still depends on the model noticing the
    change and quoting real caller usage; it's a path to recall, not a guarantee of it.
  - `naive` mode's "full new content of changed files" is genuinely available only in
    the benchmark (`run.py` reads it off the local `--repo` checkout). The live
    service (webhook or manual review) has no persistent repo checkout at review time
    -- `ingest_repository` deletes its clone right after indexing -- so
    `REVIEW_CONTEXT_MODE=naive` against a real PR falls back to the diff's own
    visible new-side text per file instead of the true full file. That's still a
    meaningfully different (per-file, not per-symbol) context shape than `diff_only`,
    but it's a weaker "naive" than the one the benchmark measures. Fetching full file
    content from GitHub for live naive-mode reviews is a reasonable follow-up, not
    implemented in this version.
  - The "rough estimated token cost" is the same chars/4 heuristic used for the
    `REVIEW_MAX_*_TOKENS` caps, applied to the retrieved/impact context only (not the
    full rendered prompt or the model's output) -- a relative, cross-mode comparison
    signal, not a real cost figure.
