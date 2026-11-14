# Real-PR holdout cases

Everything under `evals/bench/cases/` is generated and gitignored *except this
directory* -- `cases/real/` is hand-curated and committed, so the benchmark always
has at least one group of cases that weren't synthetically mutated.

`bench/run.py` includes every case directory here automatically, in addition to
whatever `--cases-dir` points at, and reports them as their own group (via
`mutation_type: "real"` in each case's `expected.yaml`, same as any other mutation
type in the per-mutation-type breakdown).

## Adding one by hand

1. Pick a real, already-merged pull request against the repo you're benchmarking
   (the same one passed as `--repo`) that you've actually read and understand --
   **do not fabricate a case**. A good candidate either:
   - genuinely changed a function's behavior or signature in a way that broke (or
     would have broken) a caller, or
   - is a plausible-looking but safe change that a naive reviewer might flag anyway
     (a negative case).
2. Create `evals/bench/cases/real/<short-descriptive-id>/`.
3. Save the PR's unified diff as `pr.diff` in that directory (`gh pr diff <number>
   > pr.diff`, or copy it from the GitHub UI).
4. Write `expected.yaml` with the same schema `generate.py` produces:
   ```yaml
   mutation_type: "real"
   changed_symbol: <the function/method name the diff actually changes>
   changed_file: <path, relative to the repo root>
   expected_caller_files: [<files that call changed_symbol, if any>]
   is_negative: <true if this change should NOT be flagged as breaking, else false>
   ```
5. Run the benchmark (`uv run python -m evals.bench.run --repo ... --cases-dir ...`)
   and sanity-check the `real` row in the resulting `results/latest.md` -- a case that
   never gets hit in `full` mode either is worth a second look before trusting it.

Keep this small and genuinely curated. A handful of real, well-understood cases is
worth far more here than many loosely-checked ones -- the entire point of this group
is to catch anything the synthetic mutations' narrow candidate selection (see
`generate.py`'s `_is_simple_candidate`) might be missing.
