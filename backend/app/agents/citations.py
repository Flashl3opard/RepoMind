import re

from app.agents.schemas import Citation, LabeledChunkState

_LABEL_RE = re.compile(r"\[C(\d+)\]")


def extract_cited_labels(answer: str) -> list[str]:
    """[Cn] labels referenced in `answer`, in first-seen order, deduplicated."""
    seen: set[str] = set()
    labels: list[str] = []
    for match in _LABEL_RE.findall(answer):
        label = f"C{match}"
        if label not in seen:
            seen.add(label)
            labels.append(label)
    return labels


def build_citations(answer: str, context_chunks: list[LabeledChunkState]) -> list[Citation]:
    """Map every [Cn] label cited in `answer` back to its source location.

    Labels the model invented (not present in `context_chunks`) are silently dropped."""
    by_label = {c["label"]: c for c in context_chunks}
    citations: list[Citation] = []
    for label in extract_cited_labels(answer):
        chunk = by_label.get(label)
        if chunk is None:
            continue
        citations.append(
            Citation(
                label=label,
                file_path=chunk["file_path"],
                start_line=chunk["start_line"],
                end_line=chunk["end_line"],
                symbol_name=chunk["symbol_name"],
            )
        )
    return citations


def invalid_labels(answer: str, context_chunks: list[LabeledChunkState]) -> list[str]:
    """Labels cited in `answer` that don't correspond to any shown chunk."""
    valid = {c["label"] for c in context_chunks}
    return [label for label in extract_cited_labels(answer) if label not in valid]
