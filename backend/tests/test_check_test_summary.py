import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from check_test_summary import count, main  # noqa: E402


def test_count_extracts_passed():
    assert count("259 passed, 36 skipped in 12.3s", "passed") == 259


def test_count_extracts_skipped():
    assert count("259 passed, 36 skipped in 12.3s", "skipped") == 36


def test_count_returns_zero_when_word_absent():
    assert count("259 passed in 12.3s", "failed") == 0


def test_count_does_not_match_substring_words():
    # "error" must not match inside "errors" at a different count, and vice versa --
    # the \b boundary keeps these independent.
    assert count("1 passed, 2 errors in 1.0s", "error") == 2


def test_main_passes_within_budget(tmp_path, monkeypatch, capsys):
    output = tmp_path / "pytest-output.txt"
    output.write_text("259 passed, 2 skipped in 300s")
    monkeypatch.setenv("MAX_ALLOWED_SKIPPED_TESTS", "3")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)

    monkeypatch.setattr(sys, "argv", ["check_test_summary.py", str(output), "0"])
    assert main() == 0
    assert "within the allowed budget" in capsys.readouterr().out


def test_main_fails_when_skipped_exceeds_budget(tmp_path, monkeypatch, capsys):
    output = tmp_path / "pytest-output.txt"
    output.write_text("200 passed, 10 skipped in 300s")
    monkeypatch.setenv("MAX_ALLOWED_SKIPPED_TESTS", "3")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(sys, "argv", ["check_test_summary.py", str(output), "0"])

    assert main() == 1
    assert "exceeds the allowed threshold" in capsys.readouterr().out


def test_main_propagates_nonzero_pytest_exit_code_even_within_skip_budget(tmp_path, monkeypatch, capsys):
    output = tmp_path / "pytest-output.txt"
    output.write_text("5 failed, 254 passed, 1 skipped in 300s")
    monkeypatch.setenv("MAX_ALLOWED_SKIPPED_TESTS", "3")
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    monkeypatch.setattr(sys, "argv", ["check_test_summary.py", str(output), "1"])

    assert main() == 1
    assert "pytest exited with code 1" in capsys.readouterr().out


def test_main_writes_to_github_step_summary_file_when_set(tmp_path, monkeypatch):
    output = tmp_path / "pytest-output.txt"
    output.write_text("1 passed in 1.0s")
    summary_file = tmp_path / "step-summary.md"
    monkeypatch.setenv("MAX_ALLOWED_SKIPPED_TESTS", "3")
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary_file))
    monkeypatch.setattr(sys, "argv", ["check_test_summary.py", str(output), "0"])

    assert main() == 0
    assert "Backend test results" in summary_file.read_text()
