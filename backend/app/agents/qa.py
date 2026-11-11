import uuid
from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.embeddings import Embeddings
from langgraph.graph import END, StateGraph
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.agents.citations import build_citations, invalid_labels
from app.agents.schemas import (
    Citation,
    Confidence,
    LabeledChunkState,
    QAState,
    RewriteResult,
    VerifyResult,
)
from app.db.models import Chunk
from app.retrieval.graph import ExpandedChunk, expand_context
from app.retrieval.hybrid import RetrievedChunk, hybrid_search, merge_retrieved

RETRY_TOP_K_STEP = 4


def _retrieved_to_labeled(r: RetrievedChunk, label: str) -> LabeledChunkState:
    chunk = r.chunk
    return LabeledChunkState(
        label=label,
        chunk_id=str(chunk.id),
        file_path=chunk.file.path,
        symbol_name=chunk.symbol_name,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        source=chunk.source,
        reason="retrieved",
        sources=list(r.sources),
        score=r.score,
    )


def _expanded_to_labeled(e: ExpandedChunk, label: str) -> LabeledChunkState:
    chunk = e.chunk
    return LabeledChunkState(
        label=label,
        chunk_id=str(chunk.id),
        file_path=chunk.file.path,
        symbol_name=chunk.symbol_name,
        start_line=chunk.start_line,
        end_line=chunk.end_line,
        source=chunk.source,
        reason=e.reason,
        sources=["graph"],
        score=float(e.link_count),
    )


def _format_context(chunks: list[LabeledChunkState]) -> str:
    if not chunks:
        return "(no chunks retrieved)"
    blocks = []
    for c in chunks:
        header = f"[{c['label']}] {c['file_path']}:{c['start_line']}-{c['end_line']} ({c['symbol_name']})"
        blocks.append(f"{header}\n{c['source']}")
    return "\n\n".join(blocks)


def _rewrite_prompt(question: str) -> str:
    return (
        "Rewrite this question into a short, code-search-friendly query: prefer likely "
        "identifier names, filenames, and symbols over natural language phrasing. Keep it "
        f"on one line.\n\nQuestion: {question}"
    )


def _generate_prompt(question: str, context_block: str) -> str:
    return (
        "You answer questions about a codebase using ONLY the numbered chunks below. "
        "Cite every factual claim with its chunk label, e.g. [C1]. If the chunks don't "
        "contain enough information to answer, say so explicitly instead of guessing.\n\n"
        f"Context:\n{context_block}\n\nQuestion: {question}\n\nAnswer:"
    )


def _verify_prompt(question: str, answer: str, context_block: str) -> str:
    return (
        "You fact-check an answer against the source chunks it was generated from. Mark "
        "grounded=false if any claim in the answer is not supported by a cited chunk, or if "
        "the answer asserts something the chunks don't show. An honest 'insufficient context' "
        "answer with no unsupported claims is grounded=true.\n\n"
        f"Context:\n{context_block}\n\nQuestion: {question}\n\nAnswer:\n{answer}"
    )


def build_qa_graph(
    *,
    db: Session,
    repo_id: uuid.UUID,
    embeddings: Embeddings,
    chat_model: Any,
    verify_model: Any,
    max_expanded: int = 6,
    max_attempts: int = 2,
) -> Any:
    def rewrite_query(state: QAState) -> dict:
        result = chat_model.with_structured_output(RewriteResult).invoke(_rewrite_prompt(state["question"]))
        return {"rewritten_query": result.rewritten_query}

    def retrieve(state: QAState) -> dict:
        effective_top_k = state["top_k"] + state["attempts"] * RETRY_TOP_K_STEP
        original = hybrid_search(db, repo_id, state["question"], embeddings, top_k=effective_top_k)
        rewritten = hybrid_search(db, repo_id, state["rewritten_query"], embeddings, top_k=effective_top_k)
        merged = merge_retrieved([original, rewritten], top_k=effective_top_k)
        retrieved = [_retrieved_to_labeled(r, f"C{i + 1}") for i, r in enumerate(merged)]
        return {"retrieved": retrieved}

    def expand(state: QAState) -> dict:
        seed_ids = [uuid.UUID(c["chunk_id"]) for c in state["retrieved"]]
        seed_chunks = list(db.scalars(select(Chunk).where(Chunk.id.in_(seed_ids))).all()) if seed_ids else []
        extra = expand_context(db, repo_id, seed_chunks, max_extra=max_expanded)
        start = len(state["retrieved"]) + 1
        expanded = [_expanded_to_labeled(e, f"C{start + i}") for i, e in enumerate(extra)]
        return {"expanded": expanded}

    def generate(state: QAState) -> dict:
        context_block = _format_context(state["retrieved"] + state["expanded"])
        response = chat_model.invoke(_generate_prompt(state["question"], context_block))
        answer = response.content if hasattr(response, "content") else str(response)
        return {"answer": answer, "attempts": state["attempts"] + 1}

    def verify(state: QAState) -> dict:
        context_chunks = state["retrieved"] + state["expanded"]
        bad_labels = invalid_labels(state["answer"], context_chunks)
        context_block = _format_context(context_chunks)
        result = verify_model.with_structured_output(VerifyResult).invoke(
            _verify_prompt(state["question"], state["answer"], context_block)
        )
        grounded = result.grounded and not bad_labels and not result.unsupported_claims
        return {"grounded": grounded}

    def route_after_verify(state: QAState) -> Literal["retry", "finish"]:
        if state["grounded"]:
            return "finish"
        if state["attempts"] < max_attempts:
            return "retry"
        return "finish"

    graph = StateGraph(QAState)
    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("retrieve", retrieve)
    graph.add_node("expand", expand)
    graph.add_node("generate", generate)
    graph.add_node("verify", verify)

    graph.set_entry_point("rewrite_query")
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("retrieve", "expand")
    graph.add_edge("expand", "generate")
    graph.add_edge("generate", "verify")
    graph.add_conditional_edges("verify", route_after_verify, {"retry": "retrieve", "finish": END})

    return graph.compile()


@dataclass(slots=True)
class QAResult:
    answer: str
    citations: list[Citation]
    confidence: Confidence
    retrieved_count: int
    expanded_count: int
    attempts: int
    rewritten_query: str
    retrieved_debug: list[LabeledChunkState]
    expanded_debug: list[LabeledChunkState]


def run_qa(
    db: Session,
    repo_id: uuid.UUID,
    question: str,
    *,
    embeddings: Embeddings,
    chat_model: Any,
    verify_model: Any,
    top_k: int = 8,
    max_expanded: int = 6,
    max_attempts: int = 2,
) -> QAResult:
    app = build_qa_graph(
        db=db,
        repo_id=repo_id,
        embeddings=embeddings,
        chat_model=chat_model,
        verify_model=verify_model,
        max_expanded=max_expanded,
        max_attempts=max_attempts,
    )
    initial_state: QAState = {
        "question": question,
        "rewritten_query": "",
        "retrieved": [],
        "expanded": [],
        "answer": "",
        "citations": [],
        "grounded": False,
        "attempts": 0,
        "top_k": top_k,
    }
    final_state: QAState = app.invoke(initial_state)

    context_chunks = final_state["retrieved"] + final_state["expanded"]
    citations = build_citations(final_state["answer"], context_chunks)
    confidence: Confidence = "high" if final_state["grounded"] else "low"

    return QAResult(
        answer=final_state["answer"],
        citations=citations,
        confidence=confidence,
        retrieved_count=len(final_state["retrieved"]),
        expanded_count=len(final_state["expanded"]),
        attempts=final_state["attempts"],
        rewritten_query=final_state["rewritten_query"],
        retrieved_debug=final_state["retrieved"],
        expanded_debug=final_state["expanded"],
    )
