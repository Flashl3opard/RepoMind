import ast

from evals.bench.mutations import (
    add_docstring,
    add_optional_param,
    add_required_param,
    change_return_shape,
    rename_function,
    rename_local_variable,
)


def assert_valid_python(source: str) -> None:
    ast.parse(source)  # raises SyntaxError if invalid


def test_add_required_param_appends_to_existing_params():
    src = "def add(a, b):\n    return a + b"
    mutated = add_required_param(src, "c")
    assert mutated == "def add(a, b, c):\n    return a + b"
    assert_valid_python(mutated)


def test_add_required_param_handles_no_existing_params():
    src = "def f():\n    return 1"
    mutated = add_required_param(src, "x")
    assert mutated == "def f(x):\n    return 1"
    assert_valid_python(mutated)


def test_add_required_param_returns_none_for_multiline_signature():
    src = "def f(\n    a,\n    b,\n):\n    return a + b"
    assert add_required_param(src) is None


def test_add_optional_param_has_default_value():
    src = "def add(a, b):\n    return a + b"
    mutated = add_optional_param(src, "c")
    assert mutated == "def add(a, b, c=None):\n    return a + b"
    assert_valid_python(mutated)


def test_add_optional_param_handles_no_existing_params():
    src = "def f():\n    return 1"
    mutated = add_optional_param(src, "x")
    assert mutated == "def f(x=None):\n    return 1"
    assert_valid_python(mutated)


def test_rename_function_changes_only_the_name():
    src = "def add(a, b):\n    return a + b"
    mutated = rename_function(src, "plus")
    assert mutated == "def plus(a, b):\n    return a + b"
    assert_valid_python(mutated)


def test_rename_function_preserves_return_annotation():
    src = "def add(a, b) -> int:\n    return a + b"
    mutated = rename_function(src, "plus")
    assert mutated.startswith("def plus(a, b) -> int:")
    assert_valid_python(mutated)


def test_change_return_shape_wraps_simple_expression_in_tuple():
    src = "def get_value():\n    return 42"
    mutated = change_return_shape(src)
    assert mutated == "def get_value():\n    return (42,)"
    assert_valid_python(mutated)


def test_change_return_shape_none_for_already_composite_return():
    src = "def get_pair():\n    return (1, 2)"
    assert change_return_shape(src) is None


def test_change_return_shape_none_for_multiple_returns():
    src = "def f(x):\n    if x:\n        return 1\n    return 2"
    assert change_return_shape(src) is None


def test_change_return_shape_none_for_no_return():
    src = "def f():\n    pass"
    assert change_return_shape(src) is None


def test_add_docstring_inserts_as_first_body_line():
    src = "def f(a):\n    return a"
    mutated = add_docstring(src, "A docstring.")
    assert mutated == 'def f(a):\n    """A docstring."""\n    return a'
    assert_valid_python(mutated)


def test_add_docstring_matches_body_indentation():
    src = "def f(a):\n        return a"  # unusual 8-space indent
    mutated = add_docstring(src, "Doc.")
    lines = mutated.splitlines()
    assert lines[1] == '        """Doc."""'
    assert_valid_python(mutated)


def test_rename_local_variable_renames_assignment_and_usages():
    src = "def f(a):\n    total = a + 1\n    return total"
    mutated = rename_local_variable(src)
    assert "total_renamed" in mutated
    assert "total =" not in mutated.replace("total_renamed", "")
    assert_valid_python(mutated)


def test_rename_local_variable_never_touches_parameters():
    src = "def f(a, b):\n    return a + b"
    assert rename_local_variable(src) is None  # no local assignment to rename


def test_rename_local_variable_skips_parameter_named_assignment_targets():
    # "a" is a parameter, not a local -- must not be "renamed"
    src = "def f(a):\n    a = a + 1\n    return a"
    assert rename_local_variable(src) is None
