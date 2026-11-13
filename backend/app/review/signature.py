"""Deterministic, Tree-sitter-based function/method signature extraction and diffing.

No DB, no LLM: used by map_changes to detect whether a changed symbol's signature
(parameter names, count, defaults, return annotation) changed between old and new text.
"""

import textwrap
from dataclasses import dataclass, field

from tree_sitter import Node, Parser

from app.parsing.python_parser import PY_LANGUAGE
from app.parsing.typescript_parser import TS_LANGUAGE, TSX_LANGUAGE

_FUNCTION_VALUE_TYPES = {"arrow_function", "function_expression", "function"}


@dataclass(slots=True)
class ParamInfo:
    name: str
    has_default: bool = False
    default_text: str | None = None
    annotation: str | None = None
    is_variadic: bool = False


@dataclass(slots=True)
class SignatureInfo:
    name: str
    params: list[ParamInfo] = field(default_factory=list)
    return_annotation: str | None = None


def _make_parser(language: str) -> Parser | None:
    if language == "python":
        return Parser(PY_LANGUAGE)
    if language == "typescript":
        return Parser(TS_LANGUAGE)
    if language == "tsx":
        return Parser(TSX_LANGUAGE)
    return None


def extract_signatures(source: str, language: str) -> dict[str, SignatureInfo]:
    """Best-effort: walk `source` (a full file OR just a fragment/hunk) and return every
    function/method/arrow-function signature found, keyed by name.

    Tree-sitter tolerates partial/invalid syntax around the edges, so a fragment that
    contains a clean `def foo(...):` or `function foo(...) {` line still yields that
    signature even if the surrounding text doesn't parse as a whole valid file."""
    parser = _make_parser(language)
    if parser is None:
        return {}
    tree = parser.parse(source.encode("utf-8"))
    signatures: dict[str, SignatureInfo] = {}
    if language == "python":
        _walk_python(tree.root_node, signatures)
    else:
        _walk_ts(tree.root_node, signatures)
    return signatures


def _walk_python(node: Node, out: dict[str, SignatureInfo]) -> None:
    for child in node.children:
        if child.type == "function_definition":
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                sig = _python_signature(child, name_node.text.decode("utf-8"))
                out[sig.name] = sig
        _walk_python(child, out)


def _python_signature(node: Node, name: str) -> SignatureInfo:
    params_node = node.child_by_field_name("parameters")
    params = _python_params(params_node) if params_node is not None else []
    return_node = node.child_by_field_name("return_type")
    return SignatureInfo(
        name=name,
        params=params,
        return_annotation=return_node.text.decode("utf-8") if return_node is not None else None,
    )


def _python_params(params_node: Node) -> list[ParamInfo]:
    params: list[ParamInfo] = []
    for child in params_node.named_children:
        if child.type == "identifier":
            params.append(ParamInfo(name=child.text.decode("utf-8")))
        elif child.type == "typed_parameter":
            name_node = child.named_children[0] if child.named_children else None
            type_node = child.child_by_field_name("type")
            if name_node is not None:
                params.append(
                    ParamInfo(
                        name=name_node.text.decode("utf-8"),
                        annotation=type_node.text.decode("utf-8") if type_node is not None else None,
                    )
                )
        elif child.type == "default_parameter":
            name_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")
            if name_node is not None:
                params.append(
                    ParamInfo(
                        name=name_node.text.decode("utf-8"),
                        has_default=True,
                        default_text=value_node.text.decode("utf-8") if value_node is not None else None,
                    )
                )
        elif child.type == "typed_default_parameter":
            name_node = child.child_by_field_name("name")
            type_node = child.child_by_field_name("type")
            value_node = child.child_by_field_name("value")
            if name_node is not None:
                params.append(
                    ParamInfo(
                        name=name_node.text.decode("utf-8"),
                        annotation=type_node.text.decode("utf-8") if type_node is not None else None,
                        has_default=True,
                        default_text=value_node.text.decode("utf-8") if value_node is not None else None,
                    )
                )
        elif child.type in ("list_splat_pattern", "dictionary_splat_pattern"):
            inner = child.named_children[0] if child.named_children else None
            params.append(
                ParamInfo(
                    name=inner.text.decode("utf-8") if inner is not None else child.text.decode("utf-8"),
                    is_variadic=True,
                )
            )
        # bare "*" / "/" separators (keyword-only / positional-only markers) carry no
        # name and are intentionally skipped -- they don't correspond to an argument.
    return params


def _clean_ts_type(node: Node | None) -> str | None:
    if node is None:
        return None
    text = node.text.decode("utf-8").strip()
    return text[1:].strip() if text.startswith(":") else text


def _walk_ts(node: Node, out: dict[str, SignatureInfo]) -> None:
    for child in node.children:
        if child.type in ("function_declaration", "method_definition"):
            name_node = child.child_by_field_name("name")
            if name_node is not None:
                sig = _ts_signature(child, name_node.text.decode("utf-8"))
                out[sig.name] = sig
            _walk_ts(child, out)
        elif child.type == "variable_declarator":
            name_node = child.child_by_field_name("name")
            value_node = child.child_by_field_name("value")
            if (
                name_node is not None
                and value_node is not None
                and value_node.type in _FUNCTION_VALUE_TYPES
            ):
                sig = _ts_signature(value_node, name_node.text.decode("utf-8"))
                out[sig.name] = sig
            _walk_ts(child, out)
        else:
            _walk_ts(child, out)


def _ts_signature(node: Node, name: str) -> SignatureInfo:
    params_node = node.child_by_field_name("parameters")
    params = _ts_params(params_node) if params_node is not None else []
    return_node = node.child_by_field_name("return_type")
    return SignatureInfo(name=name, params=params, return_annotation=_clean_ts_type(return_node))


def _ts_params(params_node: Node) -> list[ParamInfo]:
    params: list[ParamInfo] = []
    for child in params_node.named_children:
        if child.type in ("required_parameter", "optional_parameter"):
            pattern_node = child.child_by_field_name("pattern")
            type_node = child.child_by_field_name("type")
            value_node = child.child_by_field_name("value")
            is_variadic = pattern_node is not None and pattern_node.type == "rest_pattern"
            if is_variadic and pattern_node.named_children:
                name = pattern_node.named_children[0].text.decode("utf-8")
            elif pattern_node is not None:
                name = pattern_node.text.decode("utf-8")
            else:
                name = child.text.decode("utf-8")
            params.append(
                ParamInfo(
                    name=name,
                    annotation=_clean_ts_type(type_node),
                    has_default=value_node is not None,
                    default_text=value_node.text.decode("utf-8") if value_node is not None else None,
                    is_variadic=is_variadic,
                )
            )
        else:
            # Defensive fallback for a pattern not explicitly modeled above (e.g. a
            # destructured `{a, b}` parameter) -- still counts toward parameter count.
            params.append(ParamInfo(name=child.text.decode("utf-8")))
    return params


def diff_signatures(old: SignatureInfo, new: SignatureInfo) -> list[str]:
    """Human-readable list of what changed between two signatures of the same symbol.
    Empty list means no detectable signature change."""
    changes: list[str] = []

    if len(old.params) != len(new.params):
        changes.append(f"parameter count changed from {len(old.params)} to {len(new.params)}")

    for i, (old_param, new_param) in enumerate(zip(old.params, new.params, strict=False)):
        if old_param.name != new_param.name:
            changes.append(f"parameter {i + 1} renamed from '{old_param.name}' to '{new_param.name}'")
        if old_param.has_default != new_param.has_default:
            if new_param.has_default:
                changes.append(f"parameter '{new_param.name}' gained a default value")
            else:
                changes.append(f"parameter '{old_param.name}' lost its default value")
        elif old_param.has_default and old_param.default_text != new_param.default_text:
            changes.append(
                f"parameter '{new_param.name}' default changed from "
                f"{old_param.default_text!r} to {new_param.default_text!r}"
            )
        if old_param.annotation != new_param.annotation:
            changes.append(
                f"parameter '{new_param.name}' type annotation changed from "
                f"{old_param.annotation!r} to {new_param.annotation!r}"
            )
        if old_param.is_variadic != new_param.is_variadic:
            changes.append(f"parameter '{new_param.name}' variadic-ness changed")

    if len(new.params) > len(old.params):
        for extra in new.params[len(old.params) :]:
            # Whether the new parameter is required matters a lot for judging
            # whether this is actually a breaking change -- say so explicitly rather
            # than making the reader infer it from the raw source.
            requiredness = "optional, has a default" if extra.has_default else "required, no default"
            changes.append(f"new parameter '{extra.name}' added ({requiredness})")
    elif len(old.params) > len(new.params):
        for extra in old.params[len(new.params) :]:
            changes.append(f"parameter '{extra.name}' removed")

    if old.return_annotation != new.return_annotation:
        changes.append(
            f"return annotation changed from {old.return_annotation!r} to {new.return_annotation!r}"
        )

    return changes


def _find_first(node: Node, type_name: str) -> Node | None:
    if node.type == type_name:
        return node
    for child in node.children:
        found = _find_first(child, type_name)
        if found is not None:
            return found
    return None


def extract_docstring(source: str, language: str) -> str | None:
    """The first function/method found in `source`'s own docstring, if it has one.
    Python only for now -- TypeScript/JSDoc extraction is out of scope here."""
    if language != "python":
        return None
    parser = _make_parser(language)
    if parser is None:
        return None
    tree = parser.parse(textwrap.dedent(source).encode("utf-8"))
    func_node = _find_first(tree.root_node, "function_definition")
    if func_node is None:
        return None
    body = func_node.child_by_field_name("body")
    if body is None or not body.named_children:
        return None
    first_stmt = body.named_children[0]
    if first_stmt.type != "expression_statement" or not first_stmt.named_children:
        return None
    string_node = first_stmt.named_children[0]
    if string_node.type != "string":
        return None
    return string_node.text.decode("utf-8").strip("'\"").strip()
