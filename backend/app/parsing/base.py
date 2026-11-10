from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass(slots=True)
class ParsedChunk:
    file_path: str
    symbol_name: str
    kind: str  # "function" | "method" | "class"
    start_line: int
    end_line: int
    parent_symbol: str | None
    source: str
    imports: list[str] = field(default_factory=list)
    calls: list[str] = field(default_factory=list)


class LanguageParser(ABC):
    language: str

    @abstractmethod
    def parse(self, source: str, file_path: str) -> list[ParsedChunk]:
        """Parse source text into function/class/method chunks."""
        raise NotImplementedError
