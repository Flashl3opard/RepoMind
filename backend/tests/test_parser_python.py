from pathlib import Path

from app.parsing.python_parser import PythonParser

FIXTURE = Path(__file__).parent / "fixtures" / "python" / "sample.py"


def test_parses_functions_classes_and_methods():
    parser = PythonParser()
    chunks = parser.parse(FIXTURE.read_text(), "sample.py")

    by_name = {c.symbol_name: c for c in chunks}
    assert set(by_name) == {
        "top_level_function",
        "lazy_loader",
        "Greeter",
        "__init__",
        "greet",
        "helper",
    }

    for chunk in chunks:
        assert chunk.file_path == "sample.py"
        assert chunk.start_line <= chunk.end_line


def test_top_level_function_calls_are_captured():
    parser = PythonParser()
    chunks = parser.parse(FIXTURE.read_text(), "sample.py")
    by_name = {c.symbol_name: c for c in chunks}

    top = by_name["top_level_function"]
    assert top.kind == "function"
    assert top.parent_symbol is None
    assert top.imports == []
    assert top.calls == ["os.path.join", "dd"]


def test_local_import_inside_function_is_captured():
    parser = PythonParser()
    chunks = parser.parse(FIXTURE.read_text(), "sample.py")
    by_name = {c.symbol_name: c for c in chunks}

    lazy = by_name["lazy_loader"]
    assert lazy.imports == ["json"]
    assert lazy.calls == ["json.dumps"]


def test_class_and_methods_have_correct_kind_and_parent():
    parser = PythonParser()
    chunks = parser.parse(FIXTURE.read_text(), "sample.py")
    by_name = {c.symbol_name: c for c in chunks}

    assert by_name["Greeter"].kind == "class"
    assert by_name["Greeter"].parent_symbol is None

    assert by_name["__init__"].kind == "method"
    assert by_name["__init__"].parent_symbol == "Greeter"

    assert by_name["greet"].kind == "method"
    assert by_name["greet"].parent_symbol == "Greeter"
    assert by_name["greet"].calls == ["helper"]

    assert by_name["helper"].kind == "function"
    assert by_name["helper"].parent_symbol is None
