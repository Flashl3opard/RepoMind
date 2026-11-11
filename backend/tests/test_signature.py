from app.review.signature import diff_signatures, extract_docstring, extract_signatures


def test_extract_python_signature_basic():
    sigs = extract_signatures("def add(a, b):\n    return a + b\n", "python")
    assert "add" in sigs
    assert [p.name for p in sigs["add"].params] == ["a", "b"]
    assert sigs["add"].return_annotation is None


def test_extract_python_signature_with_types_defaults_and_variadic():
    src = 'def f(a: int, b=2, c: str = "x", *args, **kwargs) -> bool:\n    return True\n'
    sig = extract_signatures(src, "python")["f"]
    assert [p.name for p in sig.params] == ["a", "b", "c", "args", "kwargs"]
    assert sig.params[0].annotation == "int"
    assert sig.params[1].has_default and sig.params[1].default_text == "2"
    assert sig.params[2].has_default and sig.params[2].annotation == "str"
    assert sig.params[3].is_variadic
    assert sig.params[4].is_variadic
    assert sig.return_annotation == "bool"


def test_extract_python_signature_from_fragment_still_works():
    # a hunk's new-side text rarely parses as a fully valid standalone file
    fragment = "    def method(self, x, y=1):\n        return x + y\n"
    sigs = extract_signatures(fragment, "python")
    assert "method" in sigs
    assert [p.name for p in sigs["method"].params] == ["self", "x", "y"]


def test_extract_typescript_function_declaration():
    src = "function foo(a: number, b = 2, c?: string, ...rest: any[]): number { return a; }"
    sig = extract_signatures(src, "typescript")["foo"]
    assert [p.name for p in sig.params] == ["a", "b", "c", "rest"]
    assert sig.params[0].annotation == "number"
    assert sig.params[1].has_default and sig.params[1].default_text == "2"
    assert sig.params[3].is_variadic
    assert sig.return_annotation == "number"


def test_extract_typescript_arrow_function_assigned_to_const():
    src = "const helper = (name: string): string => { return name; };"
    sig = extract_signatures(src, "typescript")["helper"]
    assert [p.name for p in sig.params] == ["name"]
    assert sig.return_annotation == "string"


def test_extract_typescript_method_definition():
    src = "class Greeter { greet(name: string) { return name; } }"
    sig = extract_signatures(src, "typescript")["greet"]
    assert [p.name for p in sig.params] == ["name"]


def test_unknown_language_returns_empty():
    assert extract_signatures("def foo(): pass", "rust") == {}


def test_diff_signatures_no_change():
    sigs = extract_signatures("def add(a, b):\n    return a + b\n", "python")
    assert diff_signatures(sigs["add"], sigs["add"]) == []


def test_diff_signatures_param_count_changed():
    old = extract_signatures("def f(a, b):\n    pass\n", "python")["f"]
    new = extract_signatures("def f(a, b, c):\n    pass\n", "python")["f"]
    changes = diff_signatures(old, new)
    assert any("parameter count changed from 2 to 3" in c for c in changes)
    assert any("new parameter 'c' added" in c for c in changes)


def test_diff_signatures_param_renamed():
    old = extract_signatures("def f(a, b):\n    pass\n", "python")["f"]
    new = extract_signatures("def f(a, x):\n    pass\n", "python")["f"]
    changes = diff_signatures(old, new)
    assert any("renamed from 'b' to 'x'" in c for c in changes)


def test_diff_signatures_default_added():
    old = extract_signatures("def f(a, b):\n    pass\n", "python")["f"]
    new = extract_signatures("def f(a, b=1):\n    pass\n", "python")["f"]
    changes = diff_signatures(old, new)
    assert any("gained a default value" in c for c in changes)


def test_diff_signatures_default_removed():
    old = extract_signatures("def f(a, b=1):\n    pass\n", "python")["f"]
    new = extract_signatures("def f(a, b):\n    pass\n", "python")["f"]
    changes = diff_signatures(old, new)
    assert any("lost its default value" in c for c in changes)


def test_diff_signatures_default_value_changed():
    old = extract_signatures("def f(a, b=1):\n    pass\n", "python")["f"]
    new = extract_signatures("def f(a, b=2):\n    pass\n", "python")["f"]
    changes = diff_signatures(old, new)
    assert any("default changed from '1' to '2'" in c for c in changes)


def test_diff_signatures_return_annotation_changed():
    old = extract_signatures("def f() -> int:\n    pass\n", "python")["f"]
    new = extract_signatures("def f() -> str:\n    pass\n", "python")["f"]
    changes = diff_signatures(old, new)
    assert any("return annotation changed from 'int' to 'str'" in c for c in changes)


def test_diff_signatures_param_removed_detail():
    old = extract_signatures("def f(a, b, c):\n    pass\n", "python")["f"]
    new = extract_signatures("def f(a, b):\n    pass\n", "python")["f"]
    changes = diff_signatures(old, new)
    assert any("parameter 'c' removed" in c for c in changes)


def test_extract_docstring_single_quoted():
    src = 'def f(a):\n    """Adds one to a."""\n    return a + 1\n'
    assert extract_docstring(src, "python") == "Adds one to a."


def test_extract_docstring_dedents_method_source():
    src = '    def method(self):\n        """Indented docstring."""\n        return 1\n'
    assert extract_docstring(src, "python") == "Indented docstring."


def test_extract_docstring_missing_returns_none():
    src = "def f(a):\n    return a + 1\n"
    assert extract_docstring(src, "python") is None


def test_extract_docstring_non_python_returns_none():
    assert extract_docstring("function f() { return 1; }", "typescript") is None
