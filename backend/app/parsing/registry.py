from pathlib import Path

from app.parsing.base import LanguageParser
from app.parsing.python_parser import PythonParser
from app.parsing.typescript_parser import TypeScriptParser

_PARSERS_BY_EXTENSION: dict[str, LanguageParser] = {
    ".py": PythonParser(),
    ".ts": TypeScriptParser(tsx=False),
    ".tsx": TypeScriptParser(tsx=True),
}


def get_parser_for_path(path: str) -> LanguageParser | None:
    return _PARSERS_BY_EXTENSION.get(Path(path).suffix)
