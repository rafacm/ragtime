"""Podcast index provider abstraction.

Implementations query third-party podcast index APIs (fyyd.de,
podcastindex.org) for episode candidates given a title + show name +
optional GUID. Used as a fallback by the download agent when an
episode page hides its audio URL behind interactive UI.
"""

from .base import EpisodeCandidate, PodcastIndex
from .factory import lookup_episode_candidates

__all__ = ["EpisodeCandidate", "PodcastIndex", "lookup_episode_candidates"]
