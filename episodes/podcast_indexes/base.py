"""Podcast index ABC + shared dataclass."""

from __future__ import annotations

import dataclasses
from abc import ABC, abstractmethod


@dataclasses.dataclass(frozen=True)
class EpisodeCandidate:
    """A single episode match returned by a podcast index.

    ``audio_url`` is the only field strictly required for the download
    agent to act. ``source_index`` carries the provider name so the
    agent (and ``DownloadResult``) can record which index hit.
    """

    audio_url: str
    title: str = ""
    show_name: str = ""
    duration_seconds: int | None = None
    source_index: str = ""


class PodcastIndex(ABC):
    """A queryable podcast directory.

    Providers implement ``search`` to translate ``(title, show_name,
    guid)`` into zero or more :class:`EpisodeCandidate` objects.
    Network failures should be swallowed and returned as ``[]`` —
    the agent fans out across multiple indexes and a single
    provider's outage must not abort the cascade.
    """

    name: str

    @abstractmethod
    def search(
        self,
        title: str,
        show_name: str = "",
        guid: str = "",
    ) -> list[EpisodeCandidate]:
        """Return episode candidates matching the inputs."""
