import re
import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import Chunk

_SNAKE_CASE = re.compile(r"^[a-z0-9]+(_[a-z0-9]+)+$")
_CAMEL_CASE = re.compile(r"^[a-z][a-z0-9]*([A-Z][a-z0-9]*)+$")
_PASCAL_CASE = re.compile(r"^[A-Z][a-z0-9]*([A-Z][a-z0-9]*)+$")
_DOTTED_PATH = re.compile(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)+$")
_TOKEN_RE = re.compile(r"[A-Za-z_][\w.]*")


def looks_like_identifier(token: str) -> bool:
    """True for snake_case, camelCase, PascalCase, or dotted.path tokens."""
    token = token.strip()
    if not token:
        return False
    return bool(
        _SNAKE_CASE.match(token)
        or _CAMEL_CASE.match(token)
        or _PASCAL_CASE.match(token)
        or _DOTTED_PATH.match(token)
    )


def extract_identifier_tokens(query_text: str) -> list[str]:
    seen: set[str] = set()
    tokens: list[str] = []
    for token in _TOKEN_RE.findall(query_text):
        if looks_like_identifier(token) and token not in seen:
            seen.add(token)
            tokens.append(token)
    return tokens


def keyword_search(db: Session, repo_id: uuid.UUID, query_text: str, k: int = 8) -> list[uuid.UUID]:
    """Rank chunk ids by full-text match against `content_tsv`, with an exact
    `symbol_name` boost for any query token that looks like an identifier."""
    identifier_tokens = extract_identifier_tokens(query_text)

    boosted_ids: list[uuid.UUID] = []
    if identifier_tokens:
        boosted_ids = list(
            db.scalars(
                select(Chunk.id)
                .where(Chunk.repository_id == repo_id, Chunk.symbol_name.in_(identifier_tokens))
                .order_by(Chunk.symbol_name)
            ).all()
        )

    tsquery = func.websearch_to_tsquery("english", query_text)
    rank = func.ts_rank(Chunk.content_tsv, tsquery)
    ranked_ids = list(
        db.scalars(
            select(Chunk.id)
            .where(Chunk.repository_id == repo_id, Chunk.content_tsv.op("@@")(tsquery))
            .order_by(rank.desc())
            .limit(k)
        ).all()
    )

    merged: list[uuid.UUID] = []
    for chunk_id in (*boosted_ids, *ranked_ids):
        if chunk_id not in merged:
            merged.append(chunk_id)
    return merged[:k]
