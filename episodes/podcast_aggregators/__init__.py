"""Podcast aggregator provider abstraction.

Implementations query third-party podcast aggregator APIs (Apple Podcasts
via the iTunes Search API, fyyd.de, podcastindex.org) for episode
candidates given a title + show name + optional GUID.

Used in two places:

* The Fetch Details agent calls a small set of keyless aggregators
  (iTunes, fyyd) directly via ``episodes/agents/fetch_details_tools.py``
  to cross-link between a publisher's canonical page and an aggregator
  page when extraction from the submitted URL alone is incomplete.
* The Download agent uses ``lookup_episode_candidates`` as a fallback
  when an episode page hides its audio URL behind interactive UI.
"""

from .base import EpisodeCandidate, PodcastAggregator
from .factory import lookup_episode_candidates

__all__ = ["EpisodeCandidate", "PodcastAggregator", "lookup_episode_candidates"]
