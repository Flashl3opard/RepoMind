from app.agents.qa import run_qa
from app.agents.schemas import RewriteResult, VerifyResult
from tests.fakes import FakeChatModel, FakeEmbeddings


def test_qa_agent_happy_path(db_session, ingested_repo):
    chat_model = FakeChatModel(
        structured_outputs={"RewriteResult": [RewriteResult(rewritten_query="main add subtract")]},
        text_outputs=["`main` calls `add` and then `subtract` to compute its result. [C1]"],
    )
    verify_model = FakeChatModel(structured_outputs={"VerifyResult": [VerifyResult(grounded=True)]})

    result = run_qa(
        db_session,
        ingested_repo.id,
        "What does main do?",
        embeddings=FakeEmbeddings(),
        chat_model=chat_model,
        verify_model=verify_model,
        top_k=8,
        max_expanded=6,
        max_attempts=2,
    )

    assert result.confidence == "high"
    assert result.attempts == 1
    assert result.retrieved_count > 0
    assert result.rewritten_query == "main add subtract"
    assert len(result.citations) == 1
    assert result.citations[0]["label"] == "C1"
    assert result.citations[0]["symbol_name"] in {c["symbol_name"] for c in result.retrieved_debug}


def test_qa_agent_ungrounded_then_retry_exhausts_attempts(db_session, ingested_repo):
    """Both attempts come back ungrounded; the agent must stop at max_attempts rather
    than looping forever, and report low confidence."""
    chat_model = FakeChatModel(
        structured_outputs={"RewriteResult": [RewriteResult(rewritten_query="main add subtract")]},
        text_outputs=[
            "main definitely calls a function named frobnicate. [C1]",
            "main still definitely calls frobnicate, I'm sure of it. [C1]",
        ],
    )
    verify_model = FakeChatModel(
        structured_outputs={
            "VerifyResult": [
                VerifyResult(grounded=False, unsupported_claims=["main calls frobnicate"]),
                VerifyResult(grounded=False, unsupported_claims=["main calls frobnicate"]),
            ]
        }
    )

    result = run_qa(
        db_session,
        ingested_repo.id,
        "What does main do?",
        embeddings=FakeEmbeddings(),
        chat_model=chat_model,
        verify_model=verify_model,
        top_k=4,
        max_expanded=6,
        max_attempts=2,
    )

    assert result.attempts == 2
    assert result.confidence == "low"
    assert result.answer == "main still definitely calls frobnicate, I'm sure of it. [C1]"


def test_qa_agent_ungrounded_then_retry_recovers(db_session, ingested_repo):
    """First attempt is ungrounded; the retry (with a wider top_k) comes back grounded."""
    chat_model = FakeChatModel(
        structured_outputs={"RewriteResult": [RewriteResult(rewritten_query="main add subtract")]},
        text_outputs=[
            "main calls a function named frobnicate. [C1]",
            "main calls add and subtract. [C1]",
        ],
    )
    verify_model = FakeChatModel(
        structured_outputs={
            "VerifyResult": [
                VerifyResult(grounded=False, unsupported_claims=["main calls frobnicate"]),
                VerifyResult(grounded=True),
            ]
        }
    )

    result = run_qa(
        db_session,
        ingested_repo.id,
        "What does main do?",
        embeddings=FakeEmbeddings(),
        chat_model=chat_model,
        verify_model=verify_model,
        top_k=4,
        max_expanded=6,
        max_attempts=2,
    )

    assert result.attempts == 2
    assert result.confidence == "high"
    assert result.answer == "main calls add and subtract. [C1]"


def test_qa_agent_insufficient_context_is_grounded_on_first_attempt(db_session, ingested_repo):
    """A model that honestly declines due to insufficient context, with no citations,
    should be treated as grounded (no claims to support) and not trigger a retry."""
    chat_model = FakeChatModel(
        structured_outputs={"RewriteResult": [RewriteResult(rewritten_query="database connection pool")]},
        text_outputs=["The provided context doesn't contain enough information to answer that."],
    )
    verify_model = FakeChatModel(structured_outputs={"VerifyResult": [VerifyResult(grounded=True)]})

    result = run_qa(
        db_session,
        ingested_repo.id,
        "How does the database connection pool get configured?",
        embeddings=FakeEmbeddings(),
        chat_model=chat_model,
        verify_model=verify_model,
        top_k=8,
        max_expanded=6,
        max_attempts=2,
    )

    assert result.attempts == 1
    assert result.confidence == "high"
    assert result.citations == []
    assert "doesn't contain enough information" in result.answer


def test_qa_agent_strips_invented_citation_label(db_session, ingested_repo):
    """A label the model invents (not among the shown chunks) must be dropped from the
    citations returned to the caller, and that alone should make verify's mechanical
    label check fail even if the LLM itself claims grounded=True."""
    chat_model = FakeChatModel(
        structured_outputs={"RewriteResult": [RewriteResult(rewritten_query="main add subtract")]},
        text_outputs=[
            "main calls add and subtract. [C1] It also logs via [C99].",
            "main calls add and subtract. [C1]",
        ],
    )
    verify_model = FakeChatModel(
        structured_outputs={
            "VerifyResult": [
                VerifyResult(grounded=True),  # LLM is fooled, but [C99] doesn't exist
                VerifyResult(grounded=True),
            ]
        }
    )

    result = run_qa(
        db_session,
        ingested_repo.id,
        "What does main do?",
        embeddings=FakeEmbeddings(),
        chat_model=chat_model,
        verify_model=verify_model,
        top_k=4,
        max_expanded=6,
        max_attempts=2,
    )

    assert result.attempts == 2  # the invented [C99] label forced a retry
    assert all(c["label"] != "C99" for c in result.citations)
