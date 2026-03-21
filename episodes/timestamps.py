import re

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", text).lower()


def filter_words_for_chunk(
    words: list[dict] | None,
    chunk_start: float,
    chunk_end: float,
) -> list[dict]:
    """Return words within ``[chunk_start, chunk_end)``."""
    if not words:
        return []
    return [w for w in words if chunk_start <= w["start"] < chunk_end]


def find_entity_start_time(
    entity_name: str,
    words: list[dict] | None,
    chunk_start: float = 0.0,
    chunk_end: float = float("inf"),
) -> float | None:
    """Find the timestamp where *entity_name* first appears in *words*.

    Tries a full consecutive-token match first, then falls back to matching
    just the first token of the entity name.

    *words* may be the full episode word list (filtered internally) or a
    pre-filtered chunk slice. Pass ``chunk_start=0, chunk_end=inf`` to skip
    filtering when words are already scoped to a chunk.

    Returns the ``start`` value of the first matching word, or ``None``.
    """
    if not words or not entity_name:
        return None

    # Filter words to chunk time range
    filtered = filter_words_for_chunk(words, chunk_start, chunk_end)
    if not filtered:
        return None

    entity_tokens = _normalize(entity_name).split()
    if not entity_tokens:
        return None

    normalized = [_normalize(w["word"]) for w in filtered]
    n = len(entity_tokens)

    # Full match: sliding window over consecutive words
    for i in range(len(normalized) - n + 1):
        if normalized[i : i + n] == entity_tokens:
            return filtered[i]["start"]

    # Partial fallback: match first token only
    first_token = entity_tokens[0]
    for i, norm in enumerate(normalized):
        if norm == first_token:
            return filtered[i]["start"]

    return None
