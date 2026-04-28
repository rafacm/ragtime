"""Factory + fan-out for configured podcast indexes.

``RAGTIME_PODCAST_INDEXES`` is a comma-separated, ordered list of
provider names. Empty string disables index lookup entirely. Each
configured provider is queried in order; their results are merged
(preserving order, deduplicated by ``audio_url``).
"""

from __future__ import annotations

import logging
from typing import Iterable

from django.conf import settings

from .base import EpisodeCandidate, PodcastIndex
from .fyyd import FyydIndex
from .podcastindex import PodcastIndexOrg

logger = logging.getLogger(__name__)


def _build(name: str) -> PodcastIndex | None:
    name = name.strip().lower()
    if not name:
        return None
    if name == "fyyd":
        return FyydIndex(api_key=getattr(settings, "RAGTIME_FYYD_API_KEY", ""))
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
    logger.warning("Unknown podcast index provider: %s", name)
    return None


def get_configured_indexes() -> list[PodcastIndex]:
    """Return the configured podcast indexes in order."""
    raw = getattr(settings, "RAGTIME_PODCAST_INDEXES", "") or ""
    names: Iterable[str] = (n for n in raw.split(",") if n.strip())
    indexes = []
    for name in names:
        provider = _build(name)
        if provider is not None:
            indexes.append(provider)
    return indexes


def lookup_episode_candidates(
    title: str,
    show_name: str = "",
    guid: str = "",
) -> list[EpisodeCandidate]:
    """Fan out across all configured indexes, return merged candidates.

    Results preserve provider order and dedupe by ``audio_url`` —
    multiple indexes commonly return the same enclosure URL.
    """
    indexes = get_configured_indexes()
    if not indexes:
        return []

    seen_urls: set[str] = set()
    merged: list[EpisodeCandidate] = []
    for index in indexes:
        try:
            for candidate in index.search(title=title, show_name=show_name, guid=guid):
                if candidate.audio_url in seen_urls:
                    continue
                seen_urls.add(candidate.audio_url)
                merged.append(candidate)
        except Exception:
            logger.exception("Index %s raised during search", index.name)
    return merged
