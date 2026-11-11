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
   outside a changed hunk, drops findings citing a `[Cn]` label that doesn't exist,
   requires a `breaking_change` finding to land on a symbol the signature/removal
   detector actually flagged *and* cite real caller evidence, dedupes near-identical
   findings, and caps findings per file.
7. **summarize** — risk level (`low`/`medium`/`high`) and the summary text are both
   computed in code from the verified findings, not asked from the LLM.

Add `?debug=true` (only honored when `REVIEW_DEBUG_ENABLED=true`) to also get
per-symbol change detection and the full labeled context the LLM was shown.

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
- Every DB-backed suite needs a real Postgres+pgvector reachable at `TEST_DATABASE_URL`
  (defaults to `DATABASE_URL`'s value); they `pytest.skip()` cleanly if one isn't
  running, e.g. via `docker compose up -d db`.

## Layout

```
app/
  config.py            pydantic-settings config
  main.py               FastAPI app, startup embedding-dimension check
  api/                  routes + request/response schemas
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
  services/
    cloner.py            shallow git clone -> (path, commit_sha)
    embeddings.py        LangChain embeddings factory, dimension-pinned, + batching
    ingestion.py          clone -> parse -> embed -> persist orchestrator
alembic/                 migrations
evals/
  fixture_repo.py          shared synthetic repo for both eval scripts
  qa_questions.yaml + run_qa_eval.py            Q&A eval seed
  review_cases/*.diff + *.yaml + run_review_eval.py   PR-review eval seed
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
