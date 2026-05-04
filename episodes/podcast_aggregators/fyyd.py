"""fyyd.de podcast-aggregator client.

fyyd's read API is open (no key required). An optional API key only
raises rate limits, so it is plumbed through but not enforced.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

import httpx

from .base import EpisodeCandidate, PodcastAggregator

logger = logging.getLogger(__name__)

API_BASE = "https://api.fyyd.de/0.2"
TIMEOUT = 10.0
USER_AGENT = "RAGtime/0.1 (podcast aggregator lookup)"


class FyydAggregator(PodcastAggregator):
    name = "fyyd"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def search(
        self,
        title: str,
        show_name: str = "",
        guid: str = "",
    ) -> list[EpisodeCandidate]:
        # fyyd does not expose a GUID search; title (+ show name when
        # available) is the most useful query term.
        term = " ".join(p for p in (show_name, title) if p).strip()
        if not term:
            return []

        try:
            response = httpx.get(
                f"{API_BASE}/search/episode",
                params={"term": term, "count": 10},
                headers=self._headers(),
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("fyyd search failed for %r: %s", term, exc)
            return []

        return [
            self._candidate(item)
            for item in self._iter_episodes(payload)
            if self._candidate(item) is not None
        ]

    def _iter_episodes(self, payload: Any) -> list[dict]:
        if not isinstance(payload, dict):
            return []
        data = payload.get("data") or []
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        return []

    def _candidate(self, item: dict) -> EpisodeCandidate | None:
        audio_url = item.get("enclosure") or ""
        if not audio_url:
            return None
        podcast = item.get("podcast") or {}
        show_name = ""
        if isinstance(podcast, dict):
            show_name = podcast.get("title") or ""
        duration = item.get("duration")
        if not isinstance(duration, int):
            duration = None
        published_at = _parse_pubdate(item.get("pubdate"))
        return EpisodeCandidate(
            audio_url=audio_url,
            title=item.get("title") or "",
            show_name=show_name,
            duration_seconds=duration,
            source_index=self.name,
            published_at=published_at,
        )


def _parse_pubdate(raw: Any) -> date | None:
    """Parse fyyd's ``pubdate`` field to a ``date``.

    fyyd documents the value as ISO 8601 (e.g. ``"2024-08-30 04:00:00"``).
    Returns ``None`` on missing / unparseable input — never raises, so
    a single broken row doesn't drop a candidate.
    """
    if not raw:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    if not isinstance(raw, str):
        logger.warning("fyyd pubdate has unexpected type %s: %r", type(raw), raw)
        return None
    text = raw.strip()
    if not text:
        return None
    # Try a few likely shapes: "YYYY-MM-DD HH:MM:SS", ISO 8601 with T,
    # bare "YYYY-MM-DD".
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(text[: len(fmt) + 4], fmt).date()
        except ValueError:
            continue
    # Last resort: ``fromisoformat`` (handles offsets, fractional seconds, etc.)
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date()
    except ValueError:
        logger.warning("fyyd pubdate could not be parsed: %r", raw)
        return None
