"""Shared synthetic fixture repo used by both eval scripts (run_qa_eval.py and
run_review_eval.py): a tiny calculator with a test file, built fresh as a local git
repo so ingestion can clone it like any other repo."""

import subprocess
from pathlib import Path

FIXTURE_FILES = {
    "calculator.py": (
        "def add(a, b):\n"
        "    return a + b\n"
        "\n\n"
        "def subtract(a, b):\n"
        "    return a - b\n"
        "\n\n"
        "def multiply(a, b):\n"
        "    return a * b\n"
        "\n\n"
        "def divide(a, b):\n"
        '    if b == 0:\n        raise ValueError("division by zero")\n'
        "    return a / b\n"
    ),
    "utils.py": 'def format_result(value):\n    return f"Result: {value}"\n',
    "main.py": (
        "from calculator import add, subtract, multiply, divide\n"
        "from utils import format_result\n"
        "\n\n"
        "def main():\n"
        "    total = add(1, 2)\n"
        "    total = subtract(total, 1)\n"
        "    total = multiply(total, 4)\n"
        "    total = divide(total, 2)\n"
        "    return format_result(total)\n"
    ),
    "test_calculator.py": (
        "from calculator import add, divide, multiply, subtract\n"
        "\n\n"
        "def test_add():\n"
        "    assert add(1, 2) == 3\n"
        "\n\n"
        "def test_subtract():\n"
        "    assert subtract(5, 2) == 3\n"
        "\n\n"
        "def test_multiply():\n"
        "    assert multiply(2, 3) == 6\n"
        "\n\n"
        "def test_divide_by_zero_raises():\n"
        "    try:\n"
        "        divide(1, 0)\n"
        "    except ValueError:\n"
        "        pass\n"
        "    else:\n"
        "        assert False\n"
    ),
}


def build_fixture_repo(tmp_dir: Path, name: str = "eval-fixture-repo") -> str:
    repo_dir = tmp_dir / name
    repo_dir.mkdir()
    for filename, content in FIXTURE_FILES.items():
        (repo_dir / filename).write_text(content)

    def run(*args: str) -> None:
        subprocess.run(["git", *args], cwd=repo_dir, check=True, capture_output=True, text=True)

    run("init", "-q")
    run("config", "user.email", "eval@example.com")
    run("config", "user.name", "Eval")
    run("add", ".")
    run("commit", "-q", "-m", "fixture")
    return str(repo_dir)
