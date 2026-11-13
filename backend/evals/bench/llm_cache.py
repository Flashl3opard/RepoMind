"""Disk-backed cache for the one LLM call app/review/graph.py's review_node makes
(`chat_model.with_structured_output(LLMReviewOutput).invoke(prompt)`), keyed by
(case_id, mode, model, hash(prompt)) so benchmark reruns are free unless the prompt
or model actually changed.
"""

import hashlib
from pathlib import Path
from typing import Any


class _CachedStructuredRunnable:
    def __init__(self, inner_runnable: Any, schema: type, cache_dir: Path, cache_key_prefix: str) -> None:
        self._inner_runnable = inner_runnable
        self._schema = schema
        self._cache_dir = cache_dir
        self._cache_key_prefix = cache_key_prefix

    def invoke(self, prompt: str) -> Any:
        prompt_hash = hashlib.sha256(prompt.encode("utf-8")).hexdigest()[:16]
        cache_path = self._cache_dir / f"{self._cache_key_prefix}__{prompt_hash}.json"

        if cache_path.exists():
            return self._schema.model_validate_json(cache_path.read_text())

        result = self._inner_runnable.invoke(prompt)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(result.model_dump_json())
        return result


class CachingChatModel:
    """Wraps a real chat model's `with_structured_output(...).invoke(prompt)` call
    with an on-disk cache. Only implements what review_node actually uses."""

    def __init__(self, inner: Any, cache_dir: Path, case_id: str, mode: str, model_name: str) -> None:
        self._inner = inner
        self._cache_dir = cache_dir
        safe_case_id = case_id.replace("/", "_")
        self._cache_key_prefix = f"{safe_case_id}__{mode}__{model_name}"

    def with_structured_output(self, schema: type) -> _CachedStructuredRunnable:
        return _CachedStructuredRunnable(self._inner.with_structured_output(schema), schema, self._cache_dir, self._cache_key_prefix)
