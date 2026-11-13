"""Pure, deterministic source-level mutations for the PR-review benchmark generator.

Each mutator takes a function's own source text (a complete, syntactically valid
single-line-signature `def ...:` block -- see `_split_signature`) and returns a
mutated version, or None if that mutation doesn't apply to this function's shape
(e.g. change_return_shape needs exactly one simple return statement). No I/O.
"""

import re

_SIGNATURE_LINE_RE = re.compile(r"^(\s*def\s+\w+\s*\()(.*)(\)\s*(?:->[^:]*)?:\s*)$")
_ASSIGN_RE = re.compile(r"^\s*([A-Za-z_]\w*)\s*=\s*[^=]")


def _split_signature(source: str) -> tuple[str, str, str, str] | None:
    """(text before the param list, the param list itself, text from ")" to the
    trailing ":", the rest of the source after the signature line) -- or None if the
    signature doesn't fit on a single line (out of scope for these mutators)."""
    first_line, sep, rest = source.partition("\n")
    match = _SIGNATURE_LINE_RE.match(first_line)
    if match is None:
        return None
    return match.group(1), match.group(2), match.group(3), (rest if sep else "")


def add_required_param(source: str, new_name: str = "extra_param") -> str | None:
    """Breaking: callers using positional args at the old arity now fail."""
    parts = _split_signature(source)
    if parts is None:
        return None
    before, params, after, rest = parts
    new_params = f"{params}, {new_name}" if params.strip() else new_name
    return _join(before, new_params, after, rest)


def add_optional_param(source: str, new_name: str = "extra") -> str | None:
    """Safe: a new parameter with a default never breaks an existing caller."""
    parts = _split_signature(source)
    if parts is None:
        return None
    before, params, after, rest = parts
    new_params = f"{params}, {new_name}=None" if params.strip() else f"{new_name}=None"
    return _join(before, new_params, after, rest)


def rename_function(source: str, new_name: str) -> str | None:
    """Breaking (when callers aren't updated in the same change): the old name
    disappears entirely."""
    if _split_signature(source) is None:
        return None
    first_line, sep, rest = source.partition("\n")
    new_first_line = re.sub(r"(def\s+)\w+(\s*\()", rf"\1{new_name}\2", first_line, count=1)
    return new_first_line + sep + rest


def change_return_shape(source: str) -> str | None:
    """Breaking: wraps a simple single-return function's value in a tuple, changing
    what callers unpack. None if the function doesn't have exactly one plain
    `return <expr>` (e.g. no return, multiple returns, or already a composite)."""
    lines = source.splitlines()
    return_indices = [i for i, line in enumerate(lines) if re.match(r"^\s*return\s+\S", line)]
    if len(return_indices) != 1:
        return None
    idx = return_indices[0]
    match = re.match(r"^(\s*return\s+)(.+)$", lines[idx])
    if match is None:
        return None
    indent_and_kw, expr = match.groups()
    expr = expr.strip()
    if expr.startswith(("(", "{", "[")):
        return None
    lines[idx] = f"{indent_and_kw}({expr},)"
    return "\n".join(lines)


def remove_function_body() -> str:
    """Breaking: the whole function is gone. The generator deletes the chunk's line
    span from the file directly; this exists just to name the mutation uniformly."""
    return ""


def add_docstring(source: str, text: str = "Added for the benchmark.") -> str | None:
    """Safe: a new docstring changes nothing about the signature or behavior."""
    parts = _split_signature(source)
    if parts is None:
        return None
    before, params, after, rest = parts
    body_lines = rest.splitlines()
    if not body_lines:
        return None
    indent_match = re.match(r"^(\s*)", body_lines[0])
    indent = indent_match.group(1) if indent_match else ""
    docstring_line = f'{indent}"""{text}"""'
    new_rest = "\n".join([docstring_line, *body_lines])
    return _join(before, params, after, new_rest)


def rename_local_variable(source: str, suffix: str = "_renamed") -> str | None:
    """Safe: renames the first simple local assignment target found (never a
    parameter) throughout the function body. None if no such local is found."""
    parts = _split_signature(source)
    if parts is None:
        return None
    before, params, after, rest = parts
    param_names = {p.split(":")[0].split("=")[0].strip().lstrip("*") for p in params.split(",") if p.strip()}

    for line in rest.splitlines():
        match = _ASSIGN_RE.match(line)
        if match and match.group(1) not in param_names:
            local_name = match.group(1)
            new_name = f"{local_name}{suffix}"
            new_rest = re.sub(rf"\b{re.escape(local_name)}\b", new_name, rest)
            return _join(before, params, after, new_rest)
    return None


def _join(before: str, params: str, after: str, rest: str) -> str:
    signature_line = f"{before}{params}{after}"
    return f"{signature_line}\n{rest}" if rest else signature_line
