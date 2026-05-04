"""podcastindex.org client.

Authenticated via the documented ``Auth-Key`` / ``Auth-Date`` /
``Authorization`` (sha1) header trio. We try GUID lookup first when one
is provided — podcastindex supports it directly — and fall back to
term search.
"""

from __future__ import annotations

import hashlib
import logging
import time
from datetime import date, datetime, timezone
from typing import Any

import httpx

from .base import EpisodeCandidate, PodcastAggregator

logger = logging.getLogger(__name__)

API_BASE = "https://api.podcastindex.org/api/1.0"
TIMEOUT = 10.0
USER_AGENT = "RAGtime/0.1 (podcast aggregator lookup)"


class PodcastIndexOrg(PodcastAggregator):
    name = "podcastindex"

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret

    def _headers(self) -> dict[str, str]:
        ts = str(int(time.time()))
        digest = hashlib.sha1(
            (self.api_key + self.api_secret + ts).encode("utf-8")
        ).hexdigest()
        return {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            "X-Auth-Key": self.api_key,
            "X-Auth-Date": ts,
            "Authorization": digest,
        }

    def search(
        self,
        title: str,
        show_name: str = "",
        guid: str = "",
    ) -> list[EpisodeCandidate]:
        if guid:
            results = self._search_by_guid(guid)
            if results:
                return results
        term = " ".join(p for p in (show_name, title) if p).strip()
        if not term:
            return []
        return self._search_by_term(term)

    def _search_by_guid(self, guid: str) -> list[EpisodeCandidate]:
        try:
            response = httpx.get(
                f"{API_BASE}/episodes/byguid",
                params={"guid": guid},
                headers=self._headers(),
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("podcastindex guid lookup failed for %r: %s", guid, exc)
            return []
        return self._candidates_from_payload(payload, key="episode")

    def _search_by_term(self, term: str) -> list[EpisodeCandidate]:
        try:
            response = httpx.get(
                f"{API_BASE}/search/byterm",
                params={"q": term, "max": 10, "fulltext": ""},
                headers=self._headers(),
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("podcastindex term search failed for %r: %s", term, exc)
            return []
        return self._candidates_from_payload(payload, key="feeds")

    def _candidates_from_payload(self, payload: Any, key: str) -> list[EpisodeCandidate]:
        if not isinstance(payload, dict):
            return []
        items = payload.get(key) or payload.get("items") or []
        if isinstance(items, dict):
            items = [items]
        if not isinstance(items, list):
            return []
        results = []
        for item in items:
            if not isinstance(item, dict):
                continue
            audio_url = item.get("enclosureUrl") or item.get("url") or ""
            if not audio_url:
                continue
            duration = item.get("duration")
            if not isinstance(duration, int):
                duration = None
            published_at = _parse_date_published(item.get("datePublished"))
            results.append(
                EpisodeCandidate(
                    audio_url=audio_url,
                    title=item.get("title") or "",
                    show_name=item.get("feedTitle") or item.get("title") or "",
                    duration_seconds=duration,
                    source_index=self.name,
                    published_at=published_at,
                )
            )
        return results


def _parse_date_published(raw: Any) -> date | None:
    """Parse podcastindex's ``datePublished`` (Unix epoch seconds) to ``date``.

    Returns ``None`` on missing / unparseable input — never raises.
    """
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):  # bool is a subclass of int; reject explicitly.
        logger.warning("podcastindex datePublished is bool: %r", raw)
        return None
    if isinstance(raw, (int, float)):
        try:
            return datetime.fromtimestamp(raw, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            logger.warning("podcastindex datePublished out of range: %r", raw)
            return None
    if isinstance(raw, str):
        try:
            return datetime.fromtimestamp(int(raw), tz=timezone.utc).date()
        except (TypeError, ValueError):
            logger.warning("podcastindex datePublished not numeric: %r", raw)
            return None
    logger.warning(
        "podcastindex datePublished has unexpected type %s: %r", type(raw), raw,
    )
    return None
