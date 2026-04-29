"""Factory + fan-out for configured podcast aggregators.

``RAGTIME_PODCAST_AGGREGATORS`` is a comma-separated, ordered list of
provider names. Empty string disables aggregator lookup entirely. Each
configured provider is queried in order; their results are merged
(preserving order, deduplicated by ``audio_url``).
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings

from .base import EpisodeCandidate, PodcastAggregator
from .fyyd import FyydAggregator
from .itunes import ItunesAggregator
from .podcastindex import PodcastIndexOrg

logger = logging.getLogger(__name__)


def _build(name: str) -> PodcastAggregator | None:
    name = name.strip().lower()
    if not name:
        return None
    if name == "fyyd":
        return FyydAggregator(api_key=getattr(settings, "RAGTIME_FYYD_API_KEY", ""))
    if name in ("itunes", "apple", "apple_podcasts"):
        return ItunesAggregator()
    if name == "podcastindex":
        api_key = getattr(settings, "RAGTIME_PODCASTINDEX_API_KEY", "")
        api_secret = getattr(settings, "RAGTIME_PODCASTINDEX_API_SECRET", "")
        if not api_key or not api_secret:
            logger.warning(
                "podcastindex requested but RAGTIME_PODCASTINDEX_API_KEY/"
                "API_SECRET are unset — skipping."
            )
            return None
        return PodcastIndexOrg(api_key=api_key, api_secret=api_secret)
    logger.warning("Unknown podcast aggregator: %s", name)
    return None


def get_configured_aggregators() -> list[PodcastAggregator]:
    """Return the configured podcast aggregators in order."""
    raw = getattr(settings, "RAGTIME_PODCAST_AGGREGATORS", "") or ""
    names: Iterable[str] = (n for n in raw.split(",") if n.strip())
    aggregators = []
    for name in names:
        provider = _build(name)
        if provider is not None:
            aggregators.append(provider)
    return aggregators


def lookup_episode_candidates(
    title: str,
    show_name: str = "",
    guid: str = "",
) -> list[EpisodeCandidate]:
    """Fan out across all configured aggregators, return merged candidates.

    Results preserve provider order and dedupe by ``audio_url`` —
    multiple aggregators commonly return the same enclosure URL.
    """
    aggregators = get_configured_aggregators()
    if not aggregators:
        return []

    seen_urls: set[str] = set()
    merged: list[EpisodeCandidate] = []
    for aggregator in aggregators:
        try:
            for candidate in aggregator.search(
                title=title, show_name=show_name, guid=guid,
            ):
                if candidate.audio_url in seen_urls:
                    continue
                seen_urls.add(candidate.audio_url)
                merged.append(candidate)
        except Exception:
            logger.exception("Aggregator %s raised during search", aggregator.name)
    return merged
