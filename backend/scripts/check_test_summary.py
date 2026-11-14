"""Parses a pytest text run's summary line, writes a short table to the GitHub Actions
job summary, and fails if either the run itself failed or the skipped-test count
exceeds MAX_ALLOWED_SKIPPED_TESTS.

With a real Postgres service container reachable (see tests/conftest.py's db_session
fixture), every test that currently skips for lacking one should run; a growing
skipped count without a corresponding change to that fixture usually means the
service container isn't actually being reached (a bad DATABASE_URL/TEST_DATABASE_URL,
or the health check not gating the test step), not that more tests chose to skip for
a good reason. This can also be run locally against a pytest output file for a quick
check outside CI (GITHUB_STEP_SUMMARY is then optional -- the summary table is
printed to stdout either way).

Usage: uv run python scripts/check_test_summary.py <pytest-output.txt> <exit-code>
"""

import os
import re
import sys


def count(text: str, word: str) -> int:
    # pytest pluralizes "error"/"warning" ("1 error" vs "2 errors") but not
    # "passed"/"failed"/"skipped" -- the optional trailing "s" covers both.
    match = re.search(rf"(\d+) {word}s?\b", text)
    return int(match.group(1)) if match else 0


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: check_test_summary.py <pytest-output.txt> <pytest-exit-code>", file=sys.stderr)
        return 2
    output_path, exit_code_arg = sys.argv[1], sys.argv[2]
    pytest_exit_code = int(exit_code_arg)
    threshold = int(os.environ.get("MAX_ALLOWED_SKIPPED_TESTS", "3"))

    with open(output_path, encoding="utf-8", errors="replace") as f:
        text = f.read()

    passed = count(text, "passed")
    skipped = count(text, "skipped")
    failed = count(text, "failed")
    errors = count(text, "error")

    over_budget = skipped > threshold
    summary_lines = [
        "### Backend test results",
        "",
        "| passed | skipped | failed | errors | skipped budget |",
        "|---|---|---|---|---|",
        f"| {passed} | {skipped} | {failed} | {errors} | {threshold} |",
        "",
    ]
    if pytest_exit_code != 0:
        summary_lines.append(f"**pytest exited with code {pytest_exit_code}.**")
    if over_budget:
        summary_lines.append(
            f"**FAILING: {skipped} skipped tests exceeds the allowed threshold of {threshold}.** "
            "This usually means the Postgres service container isn't actually being reached by "
            "the test run -- check DATABASE_URL/TEST_DATABASE_URL and the service health check, "
            "not just that more tests started skipping for a legitimate reason."
        )
    elif pytest_exit_code == 0:
        summary_lines.append(f"Skipped count ({skipped}) is within the allowed budget ({threshold}).")

    summary = "\n".join(summary_lines) + "\n"
    print(summary)

    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(summary)

    if pytest_exit_code != 0:
        return pytest_exit_code
    if over_budget:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
