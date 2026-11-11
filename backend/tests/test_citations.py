from app.agents.citations import build_citations, extract_cited_labels, invalid_labels
from app.agents.schemas import LabeledChunkState


def _chunk(label: str, file_path: str = "app/main.py", symbol: str = "foo") -> LabeledChunkState:
    return LabeledChunkState(
        label=label,
        chunk_id="00000000-0000-0000-0000-000000000000",
        file_path=file_path,
        symbol_name=symbol,
        start_line=1,
        end_line=5,
        source="def foo(): ...",
        reason="retrieved",
        sources=["vector"],
        score=1.0,
    )


def test_extract_cited_labels_dedupes_and_preserves_order():
    answer = "See [C2] and [C1], also [C2] again."
    assert extract_cited_labels(answer) == ["C2", "C1"]


def test_extract_cited_labels_empty_when_no_citations():
    assert extract_cited_labels("No citations here.") == []


def test_build_citations_maps_known_labels():
    chunks = [_chunk("C1", "app/a.py", "foo"), _chunk("C2", "app/b.py", "bar")]
    answer = "foo does X [C1]. bar does Y [C2]."
    citations = build_citations(answer, chunks)
    assert [c["label"] for c in citations] == ["C1", "C2"]
    assert citations[0]["file_path"] == "app/a.py"
    assert citations[1]["symbol_name"] == "bar"


def test_build_citations_strips_invented_labels():
    chunks = [_chunk("C1")]
    answer = "foo does X [C1], and also somehow [C99] is relevant."
    citations = build_citations(answer, chunks)
    assert [c["label"] for c in citations] == ["C1"]


def test_build_citations_empty_when_all_labels_invented():
    chunks = [_chunk("C1")]
    answer = "This references only [C7] which doesn't exist."
    assert build_citations(answer, chunks) == []


def test_invalid_labels_reports_only_unknown_ones():
    chunks = [_chunk("C1"), _chunk("C2")]
    answer = "Mentions [C1], [C2], and a fabricated [C5]."
    assert invalid_labels(answer, chunks) == ["C5"]


def test_invalid_labels_empty_when_all_valid():
    chunks = [_chunk("C1")]
    assert invalid_labels("Only [C1] here.", chunks) == []
