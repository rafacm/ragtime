import re

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(text: str) -> str:
    return _PUNCT_RE.sub("", text).lower()


def find_entity_start_time(
    entity_name: str,
    words: list[dict] | None,
    chunk_start: float,
    chunk_end: float,
) -> float | None:
    """Find the timestamp where *entity_name* first appears in *words*.

    Tries a full consecutive-token match first, then falls back to matching
    just the first token of the entity name.

    Returns the ``start`` value of the first matching word, or ``None``.
    """
    if not words or not entity_name:
        return None

    # Filter words to chunk time range
    filtered = [w for w in words if chunk_start <= w["start"] < chunk_end]
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
