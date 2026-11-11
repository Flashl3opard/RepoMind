from app.review.impact import is_test_file


def test_python_test_prefix_file():
    assert is_test_file("tests/test_calculator.py")
    assert is_test_file("test_calculator.py")


def test_python_test_suffix_file():
    assert is_test_file("tests/calculator_test.py")


def test_typescript_test_and_spec_files():
    assert is_test_file("src/calculator.test.ts")
    assert is_test_file("src/calculator.spec.tsx")


def test_non_test_python_file_is_not_a_test_file():
    assert not is_test_file("app/services/calculator.py")
    assert not is_test_file("calculator.py")


def test_file_with_test_in_the_middle_of_the_name_is_not_a_test_file():
    assert not is_test_file("app/attestation.py")
    assert not is_test_file("contest_winner.py")


def test_windows_style_backslashes_are_handled():
    assert is_test_file("tests\\test_calculator.py")
