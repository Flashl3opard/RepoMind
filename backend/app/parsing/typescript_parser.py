import tree_sitter_typescript as tsts
from tree_sitter import Language, Node, Parser

from app.parsing.base import LanguageParser, ParsedChunk

TS_LANGUAGE = Language(tsts.language_typescript())
TSX_LANGUAGE = Language(tsts.language_tsx())

_FUNCTION_VALUE_TYPES = {"arrow_function", "function_expression", "function"}


def _extract_imports_and_calls(node: Node) -> tuple[list[str], list[str]]:
    imports: list[str] = []
    calls: list[str] = []
    stack = list(reversed(node.children))
    while stack:
        current = stack.pop()
        if current.type == "import_statement":
            source_node = current.child_by_field_name("source")
            if source_node is not None:
                imports.append(source_node.text.decode("utf-8").strip("'\""))
        elif current.type == "call_expression":
            func_node = current.child_by_field_name("function")
            if func_node is not None:
                calls.append(func_node.text.decode("utf-8"))
        stack.extend(reversed(current.children))
    return imports, calls


class TypeScriptParser(LanguageParser):
    def __init__(self, tsx: bool = False) -> None:
        self.language = "tsx" if tsx else "typescript"
        self._parser = Parser(TSX_LANGUAGE if tsx else TS_LANGUAGE)

    def parse(self, source: str, file_path: str) -> list[ParsedChunk]:
        tree = self._parser.parse(source.encode("utf-8"))
        chunks: list[ParsedChunk] = []
        self._walk(tree.root_node, file_path, parent_symbol=None, chunks=chunks)
        return chunks

    def _walk(
        self,
        node: Node,
        file_path: str,
        parent_symbol: str | None,
        chunks: list[ParsedChunk],
    ) -> None:
        for child in node.children:
            if child.type == "function_declaration":
                name = self._name_of(child) or "<anonymous>"
                chunks.append(self._build_chunk(child, file_path, name, "function", parent_symbol))
                self._walk(child, file_path, name, chunks)
            elif child.type == "class_declaration":
                name = self._name_of(child) or "<anonymous>"
                chunks.append(self._build_chunk(child, file_path, name, "class", parent_symbol))
                self._walk(child, file_path, name, chunks)
            elif child.type == "method_definition":
                name = self._name_of(child) or "<anonymous>"
                chunks.append(self._build_chunk(child, file_path, name, "method", parent_symbol))
                self._walk(child, file_path, name, chunks)
            elif child.type == "variable_declarator":
                name_node = child.child_by_field_name("name")
                value_node = child.child_by_field_name("value")
                if (
                    name_node is not None
                    and value_node is not None
                    and value_node.type in _FUNCTION_VALUE_TYPES
                ):
                    name = name_node.text.decode("utf-8")
                    chunks.append(self._build_chunk(child, file_path, name, "function", parent_symbol))
                    self._walk(value_node, file_path, name, chunks)
                else:
                    self._walk(child, file_path, parent_symbol, chunks)
            else:
                self._walk(child, file_path, parent_symbol, chunks)

    @staticmethod
    def _name_of(node: Node) -> str | None:
        name_node = node.child_by_field_name("name")
        return name_node.text.decode("utf-8") if name_node is not None else None

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
