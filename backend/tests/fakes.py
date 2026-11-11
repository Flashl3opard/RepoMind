import hashlib
from dataclasses import dataclass, field
from typing import Any

from langchain_core.embeddings import Embeddings
from langchain_core.messages import AIMessage

from app.config import get_settings


class FakeEmbeddings(Embeddings):
    """Deterministic, network-free embedding stub for tests."""

    def __init__(self, dim: int | None = None) -> None:
        self.dim = dim or get_settings().EMBEDDING_DIM

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        return [digest[i % len(digest)] / 255.0 for i in range(self.dim)]


@dataclass
class _FakeStructuredRunnable:
    queue: list[Any]
    schema_name: str

    def invoke(self, *args: Any, **kwargs: Any) -> Any:
        if not self.queue:
            raise AssertionError(f"FakeChatModel: no more scripted {self.schema_name} outputs")
        return self.queue.pop(0)


@dataclass
class FakeChatModel:
    """Deterministic scripted chat model for LangGraph node tests.

    Only implements the two call shapes app/agents/qa.py actually uses:
    `.with_structured_output(Schema).invoke(prompt)` for rewrite/verify, and a plain
    `.invoke(prompt)` returning an AIMessage for generate. Each queue is consumed in
    the order the test supplies it; invoking past the end of a queue raises, which
    surfaces a mis-scripted test immediately instead of hanging or guessing.
    """

    structured_outputs: dict[str, list[Any]] = field(default_factory=dict)
    text_outputs: list[str] = field(default_factory=list)

    def with_structured_output(self, schema: type) -> _FakeStructuredRunnable:
        queue = self.structured_outputs.setdefault(schema.__name__, [])
        return _FakeStructuredRunnable(queue, schema.__name__)

    def invoke(self, *args: Any, **kwargs: Any) -> AIMessage:
        if not self.text_outputs:
            raise AssertionError("FakeChatModel: no more scripted text outputs")
        return AIMessage(content=self.text_outputs.pop(0))
