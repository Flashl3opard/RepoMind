import tree_sitter_python as tspython
from tree_sitter import Language, Node, Parser

from app.parsing.base import LanguageParser, ParsedChunk

PY_LANGUAGE = Language(tspython.language())


def _collect_import_names(node: Node) -> list[str]:
    names: list[str] = []
    for child in node.named_children:
        if child.type == "dotted_name":
            names.append(child.text.decode("utf-8"))
        elif child.type == "aliased_import":
            base = child.child_by_field_name("name")
            if base is not None:
                names.append(base.text.decode("utf-8"))
        elif child.type == "identifier":
            names.append(child.text.decode("utf-8"))
    return names


def _collect_from_import_names(node: Node) -> list[str]:
    module_node = node.child_by_field_name("module_name")
    module_text = module_node.text.decode("utf-8") if module_node is not None else ""
    names: list[str] = []
    for child in node.named_children:
        if child is module_node:
            continue
        if child.type == "wildcard_import":
            names.append(f"{module_text}.*" if module_text else "*")
        elif child.type == "dotted_name":
            names.append(f"{module_text}.{child.text.decode('utf-8')}" if module_text else child.text.decode("utf-8"))
        elif child.type == "aliased_import":
            base = child.child_by_field_name("name")
            if base is not None:
                base_text = base.text.decode("utf-8")
                names.append(f"{module_text}.{base_text}" if module_text else base_text)
    return names


def _extract_imports_and_calls(node: Node) -> tuple[list[str], list[str]]:
    imports: list[str] = []
    calls: list[str] = []
    stack = list(reversed(node.children))
    while stack:
        current = stack.pop()
        if current.type == "import_statement":
            imports.extend(_collect_import_names(current))
        elif current.type == "import_from_statement":
            imports.extend(_collect_from_import_names(current))
        elif current.type == "call":
            func_node = current.child_by_field_name("function")
            if func_node is not None:
                calls.append(func_node.text.decode("utf-8"))
        stack.extend(reversed(current.children))
    return imports, calls


class PythonParser(LanguageParser):
    language = "python"

    def __init__(self) -> None:
        self._parser = Parser(PY_LANGUAGE)

    def parse(self, source: str, file_path: str) -> list[ParsedChunk]:
        tree = self._parser.parse(source.encode("utf-8"))
        chunks: list[ParsedChunk] = []
        self._walk(tree.root_node, file_path, parent_symbol=None, parent_kind=None, chunks=chunks)
        return chunks

    def _walk(
        self,
        node: Node,
        file_path: str,
        parent_symbol: str | None,
        parent_kind: str | None,
        chunks: list[ParsedChunk],
    ) -> None:
        for child in node.children:
            if child.type == "function_definition":
                name_node = child.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "<anonymous>"
                kind = "method" if parent_kind == "class" else "function"
                chunks.append(self._build_chunk(child, file_path, name, kind, parent_symbol))
                self._walk(child, file_path, parent_symbol=name, parent_kind="function", chunks=chunks)
            elif child.type == "class_definition":
                name_node = child.child_by_field_name("name")
                name = name_node.text.decode("utf-8") if name_node else "<anonymous>"
                chunks.append(self._build_chunk(child, file_path, name, "class", parent_symbol))
                self._walk(child, file_path, parent_symbol=name, parent_kind="class", chunks=chunks)
            else:
                self._walk(child, file_path, parent_symbol, parent_kind, chunks)

    def _build_chunk(
        self, node: Node, file_path: str, name: str, kind: str, parent_symbol: str | None
    ) -> ParsedChunk:
        imports, calls = _extract_imports_and_calls(node)
        return ParsedChunk(
            file_path=file_path,
            symbol_name=name,
            kind=kind,
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            parent_symbol=parent_symbol,
            source=node.text.decode("utf-8"),
            imports=imports,
            calls=calls,
        )
