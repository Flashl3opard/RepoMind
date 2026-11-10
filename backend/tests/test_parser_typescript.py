from pathlib import Path

from app.parsing.typescript_parser import TypeScriptParser

FIXTURE = Path(__file__).parent / "fixtures" / "typescript" / "sample.ts"


def test_parses_functions_classes_and_methods():
    parser = TypeScriptParser()
    chunks = parser.parse(FIXTURE.read_text(), "sample.ts")

    by_name = {c.symbol_name: c for c in chunks}
    assert set(by_name) == {
        "topLevelFunction",
        "Greeter",
        "constructor",
        "greet",
        "arrowHelper",
        "helper",
    }

    for chunk in chunks:
        assert chunk.file_path == "sample.ts"
        assert chunk.start_line <= chunk.end_line


def test_top_level_function_calls_are_captured():
    parser = TypeScriptParser()
    chunks = parser.parse(FIXTURE.read_text(), "sample.ts")
    by_name = {c.symbol_name: c for c in chunks}

    top = by_name["topLevelFunction"]
    assert top.kind == "function"
    assert top.parent_symbol is None
    assert top.imports == []
    assert top.calls == ["path.join", "useState"]


def test_class_and_methods_have_correct_kind_and_parent():
    parser = TypeScriptParser()
    chunks = parser.parse(FIXTURE.read_text(), "sample.ts")
    by_name = {c.symbol_name: c for c in chunks}

    assert by_name["Greeter"].kind == "class"
    assert by_name["Greeter"].parent_symbol is None

    assert by_name["constructor"].kind == "method"
    assert by_name["constructor"].parent_symbol == "Greeter"
    assert by_name["constructor"].calls == []

    assert by_name["greet"].kind == "method"
    assert by_name["greet"].parent_symbol == "Greeter"
    assert by_name["greet"].calls == ["helper"]


def test_arrow_function_assigned_to_const_is_captured():
    parser = TypeScriptParser()
    chunks = parser.parse(FIXTURE.read_text(), "sample.ts")
    by_name = {c.symbol_name: c for c in chunks}

    arrow = by_name["arrowHelper"]
    assert arrow.kind == "function"
    assert arrow.parent_symbol is None
    assert arrow.calls == ["helper"]
