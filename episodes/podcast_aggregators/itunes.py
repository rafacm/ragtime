"""Apple Podcasts (iTunes Search API) client.

The iTunes Search API is keyless and free. It exposes a single search
endpoint at ``https://itunes.apple.com/search`` filterable by
``entity=podcastEpisode``. Results carry the audio enclosure URL
(``episodeUrl``) plus podcast / episode metadata.

Used in two places:

* ``search_apple_podcasts`` tool of the Fetch Details agent —
  cross-link a publisher canonical page to its Apple Podcasts entry
  (and vice versa) when extraction is incomplete.
* ``lookup_episode_candidates`` fan-out for the Download agent when
  ``apple_podcasts`` (alias ``itunes``) is in
  ``RAGTIME_PODCAST_AGGREGATORS``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .base import EpisodeCandidate, PodcastAggregator

logger = logging.getLogger(__name__)

API_URL = "https://itunes.apple.com/search"
TIMEOUT = 10.0
USER_AGENT = "RAGtime/0.1 (podcast aggregator lookup)"


class ItunesAggregator(PodcastAggregator):
    name = "apple_podcasts"

    def search(
        self,
        title: str,
        show_name: str = "",
        guid: str = "",
    ) -> list[EpisodeCandidate]:
        # iTunes does not expose a GUID search — title (+ show name when
        # available) is the most useful query term.
        term = " ".join(p for p in (show_name, title) if p).strip()
        if not term:
            return []

        try:
            response = httpx.get(
                API_URL,
                params={
                    "term": term,
                    "entity": "podcastEpisode",
                    "limit": 10,
                    "media": "podcast",
                },
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=TIMEOUT,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("iTunes search failed for %r: %s", term, exc)
            return []

        return [c for c in (self._candidate(item) for item in self._iter(payload)) if c]

    def _iter(self, payload: Any) -> list[dict]:
        if not isinstance(payload, dict):
            return []
        results = payload.get("results") or []
        if isinstance(results, list):
            return [item for item in results if isinstance(item, dict)]
        return []

    def _candidate(self, item: dict) -> EpisodeCandidate | None:
        audio_url = item.get("episodeUrl") or ""
        if not audio_url:
            return None
        duration_ms = item.get("trackTimeMillis")
        duration_seconds: int | None = None
        if isinstance(duration_ms, int) and duration_ms > 0:
            duration_seconds = duration_ms // 1000
        return EpisodeCandidate(
            audio_url=audio_url,
            title=item.get("trackName") or "",
            show_name=item.get("collectionName") or "",
            duration_seconds=duration_seconds,
            source_index=self.name,
        )
