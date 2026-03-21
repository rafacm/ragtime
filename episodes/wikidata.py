"""Wikidata API client for entity lookup and candidate matching."""

import hashlib
import logging
import threading
import time
import urllib.parse

import httpx
from django.conf import settings
from django.core.cache import caches

logger = logging.getLogger(__name__)

WIKIDATA_API_URL = "https://www.wikidata.org/w/api.php"


class _TokenBucket:
    """Simple token bucket rate limiter (thread-safe)."""

    def __init__(self, rate: float, capacity: int):
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self):
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self._capacity,
                    self._tokens + (now - self._last) * self._rate,
                )
                if self._tokens >= 1:
                    self._tokens -= 1
                    self._last = now
                    return
                sleep_time = (1 - self._tokens) / self._rate
            time.sleep(sleep_time)


_rate_limiter = _TokenBucket(rate=5, capacity=10)


def _get_cache():
    return caches["wikidata"]


def _get_user_agent():
    return getattr(
        settings,
        "RAGTIME_WIKIDATA_USER_AGENT",
        "RAGtime/0.1 (https://github.com/rafacm/ragtime)",
    )


def _make_request(params: dict) -> dict:
    """Make a request to the Wikidata API with caching and rate limiting."""
    cache = _get_cache()
    normalized = urllib.parse.urlencode(sorted(params.items()))
    cache_key = f"wikidata:{hashlib.sha256(normalized.encode()).hexdigest()}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    ttl = getattr(settings, "RAGTIME_WIKIDATA_CACHE_TTL", 604800)

    _rate_limiter.acquire()
    try:
        response = httpx.get(
            WIKIDATA_API_URL,
            params=params,
            headers={"User-Agent": _get_user_agent()},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()
        cache.set(cache_key, data, ttl)
        return data
    except httpx.HTTPError:
        logger.exception("Wikidata API request failed")
        raise


def search_entities(
    query: str, language: str = "en", limit: int = 5
) -> list[dict]:
    """Search Wikidata via wbsearchentities API.

    Returns: [{qid, label, description}]
    """
    params = {
        "action": "wbsearchentities",
        "search": query,
        "language": language,
        "limit": limit,
        "format": "json",
    }
    data = _make_request(params)
    return [
        {
            "qid": item["id"],
            "label": item.get("label", ""),
            "description": item.get("description", ""),
        }
        for item in data.get("search", [])
    ]


def get_entity(qid: str) -> dict:
    """Fetch entity details via wbgetentities API.

    Returns: {qid, label, description, aliases, claims}
    """
    params = {
        "action": "wbgetentities",
        "ids": qid,
        "format": "json",
        "props": "labels|descriptions|aliases|claims",
        "languages": "en",
    }
    data = _make_request(params)
    entity_data = data.get("entities", {}).get(qid, {})

    label = ""
    if "labels" in entity_data and "en" in entity_data["labels"]:
        label = entity_data["labels"]["en"]["value"]

    description = ""
    if "descriptions" in entity_data and "en" in entity_data["descriptions"]:
        description = entity_data["descriptions"]["en"]["value"]

    aliases = []
    if "aliases" in entity_data and "en" in entity_data["aliases"]:
        aliases = [a["value"] for a in entity_data["aliases"]["en"]]

    return {
        "qid": qid,
        "label": label,
        "description": description,
        "aliases": aliases,
        "claims": entity_data.get("claims", {}),
    }


def _is_instance_of(claims: dict, class_qid: str) -> bool:
    """Check if entity's P31 (instance of) claims include the given class Q-ID."""
    p31_claims = claims.get("P31", [])
    for claim in p31_claims:
        mainsnak = claim.get("mainsnak", {})
        datavalue = mainsnak.get("datavalue", {})
        value = datavalue.get("value", {})
        if value.get("id") == class_qid:
            return True
    return False


def find_candidates(
    name: str, entity_type_qid: str, language: str = "en"
) -> list[dict]:
    """Search Wikidata for candidates matching name, filtered by entity type class.

    Uses wbsearchentities + wbgetentities to verify P31 (instance of) claims.
    Returns: [{qid, label, description}] ranked by relevance.
    """
    if not entity_type_qid:
        return []

    results = search_entities(name, language=language, limit=10)
    if not results:
        return []

    # Fetch full entity details to check P31 claims
    candidates = []
    for result in results:
        try:
            entity_data = get_entity(result["qid"])
        except httpx.HTTPError:
            continue

        if _is_instance_of(entity_data["claims"], entity_type_qid):
            candidates.append({
                "qid": result["qid"],
                "label": entity_data["label"],
                "description": entity_data["description"],
            })

    return candidates[:5]
