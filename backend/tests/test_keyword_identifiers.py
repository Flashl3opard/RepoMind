from app.retrieval.keyword import extract_identifier_tokens, looks_like_identifier


def test_snake_case_is_identifier():
    assert looks_like_identifier("ingest_repository")


def test_camel_case_is_identifier():
    assert looks_like_identifier("ingestRepository")


def test_pascal_case_is_identifier():
    assert looks_like_identifier("RepositoryStatus")


def test_dotted_path_is_identifier():
    assert looks_like_identifier("app.services.ingestion")


def test_plain_english_word_is_not_identifier():
    assert not looks_like_identifier("repository")
    assert not looks_like_identifier("the")


def test_empty_string_is_not_identifier():
    assert not looks_like_identifier("")
    assert not looks_like_identifier("   ")


def test_extract_identifier_tokens_filters_and_dedupes():
    query = "how does ingest_repository work and what does ingest_repository call?"
    assert extract_identifier_tokens(query) == ["ingest_repository"]


def test_extract_identifier_tokens_handles_mixed_query():
    query = "what does the clone_repository function do, is it related to CloneError?"
    tokens = extract_identifier_tokens(query)
    assert "clone_repository" in tokens
    assert "CloneError" in tokens
    assert "the" not in tokens
    assert "function" not in tokens


def test_extract_identifier_tokens_empty_for_plain_english():
    assert extract_identifier_tokens("what does this repository do") == []
