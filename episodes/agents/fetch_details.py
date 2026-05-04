"""Fetch Details Pydantic AI agent — investigator with cross-linking tools.

Single-loop agent: LLM gets system prompt + user message + 3 tools +
``output_type=FetchDetailsOutput``. The agent decides when to fetch
URLs, when to cross-link with Apple Podcasts / fyyd, and emits a
structured output describing what it did and what it found.

Module purity rule: imports only Pydantic AI, Pydantic, stdlib, and
sibling modules under ``episodes/agents/``. No Django, no DBOS, no
``episodes.models``. Tests can override the model with
``Agent.override(model=TestModel())``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, field_validator
from pydantic_ai import Agent

from . import fetch_details_tools as tools
from ._model import build_model
from .fetch_details_deps import FetchDetailsDeps

ISO_639_RE = re.compile(r"^[a-z]{2}$")
ISO_3166_RE = re.compile(r"^[a-z]{2}$")
URL_RE = re.compile(r"^https?://", re.IGNORECASE)


SYSTEM_PROMPT = """\
You are a podcast episode metadata investigator.

Inputs:
  - One URL submitted by a user. It may be the publisher's canonical
    episode page, or an aggregator's page (Apple Podcasts, Spotify, etc.).

Your goal:
  1. Fetch the submitted URL with fetch_url. This is always the first step.
  2. If the fetch failed, stop — emit outcome=unreachable. Do NOT try
     to recover by searching aggregators based on the URL alone.
  3. If the fetch succeeded, determine whether the page is a podcast
     episode page at all. If it isn't, emit outcome=not_a_podcast_episode.
  4. Extract metadata: title, show_name, description, language, country,
     image, published date, audio URL, audio format, GUID.
     For show_name, look at (in order of preference):
       - <meta property="og:site_name"> on the episode page
       - <meta name="application-name">
       - RSS/Atom <channel><title> when fetching the feed URL
       - JSON-LD structured data: PodcastEpisode → isPartOf.name (the
         parent PodcastSeries) or partOfSeries.name
       - The visible publisher / show title near the episode title
     show_name is the broadcast / podcast title (e.g. "Zeitzeichen",
     "This American Life") — NOT the publisher's company name and NOT
     the URL hostname. Leave blank when you can't pinpoint it.
  5. Classify source_kind (canonical | aggregator | unknown) and
     aggregator_provider when applicable.
  6. Cross-link ONLY when the submitted page is itself a podcast
     episode page (source_kind in {canonical, aggregator}) and you
     are recovering specific missing fields for THAT episode. An
     aggregator page (e.g. Apple Podcasts) often advertises a
     canonical URL — fetch it to recover audio_url; a canonical
     page missing audio can be found on Apple/fyyd by searching the
     episode title + show name read out of that page.
     NEVER cross-link from a non-podcast page (article, wiki,
     homepage, search result, etc.) by treating its subject as a
     query — that fabricates an unrelated episode and is forbidden.
  7. Produce a faithful structured report (what you tried, where each
     value came from, and your honest confidence).

Tools:
  - fetch_url(url): fetches and cleans HTML. Returns "FETCH_FAILED: ..."
    on network/HTTP error — that is a terminal signal for the
    submitted URL, not an invitation to retry elsewhere.
  - search_apple_podcasts(show, episode_title): iTunes Search API.
  - search_fyyd(show, episode_title): fyyd directory search.

Constraints:
  - Use tools only when they help. Redundant calls are a quality regression.
  - Do NOT guess audio URLs you didn't see in a tool result.
  - Do NOT fabricate search queries from URL path slugs, query params,
    or domain names. Apple/fyyd searches are valid only with a title
    (and optionally a show) you read out of a successfully fetched
    page that is itself a podcast episode page.
  - If the submitted URL is unreachable, the run is unreachable. Do
    not paper over it by inventing a match from another source.
  - If the submitted URL loads but is NOT a podcast episode page
    (article, wiki, homepage, etc.), the run is not_a_podcast_episode.
    Do not paper over it by searching aggregators for the page's
    subject and adopting an unrelated episode.
  - Use extraction_confidence=high ONLY when you have audio_url AND title
    AND a clear source_kind classification.
  - URLs returned must be absolute (http:// or https://).
  - language: ISO 639-1 (lowercase). country: ISO 3166-1 alpha-2 (lowercase).
  - audio_format: mp3 | m4a | aac | ogg | wav | opus.

Outcome decision rules:
  - ok: required fields filled, audio_url known, confidence high.
  - partial: required fields filled, audio_url missing or low confidence.
  - not_a_podcast_episode: page loaded, but it's clearly a homepage,
    article, wiki, search result, or non-episode page. All
    EpisodeDetails fields must be null/empty in this case — do not
    fill them from an aggregator search.
  - unreachable: fetch_url returned FETCH_FAILED for the submitted URL.
    All EpisodeDetails fields must be null/empty in this case.
  - extraction_failed: page loaded, seems like an episode, but title
    couldn't be confidently extracted.
"""


# Recognized aggregator providers — agent output is normalized at write
# time but the field is a free string so a new aggregator the agent
# names doesn't reject the whole structured output.
AGGREGATOR_WHITELIST = (
    "apple_podcasts", "spotify", "fyyd", "overcast", "pocketcasts",
)


class AttemptedSource(BaseModel):
    source: Literal["user_url", "itunes", "fyyd", "cross_link"]
    url_or_query: str
    outcome: Literal["ok", "no_results", "error", "skipped"]
    note: str = ""


class FetchDetailsReport(BaseModel):
    attempted_sources: list[AttemptedSource]
    discovered_canonical_url: bool = False
    discovered_audio_url: bool = False
    cross_linked: bool = False
    extraction_confidence: Literal["high", "medium", "low"] = "low"
    narrative: str = ""
    hints_for_next_step: str = ""


class ConciseMessage(BaseModel):
    outcome: Literal[
        "ok", "partial", "not_a_podcast_episode",
        "unreachable", "extraction_failed",
    ]
    summary: str

    @field_validator("summary", mode="before")
    @classmethod
    def _cap_summary(cls, value):
        if not isinstance(value, str):
            return value
        # Hard cap — the spec says ≤140 chars; trim quietly rather
        # than reject so a stray over-long summary doesn't fail the run.
        return value[:140]


class EpisodeDetails(BaseModel):
    """Episode-level facts extracted by the agent.

    All fields are optional — the agent returns ``None`` for any field
    it cannot confidently extract. URLs are plain ``str`` (not
    ``HttpUrl``) because pages often embed relative URLs that the agent
    cannot resolve; the validators below reject anything that isn't an
    absolute http(s) URL.
    """

    title: str | None = None
    show_name: str | None = None
    description: str | None = None
    published_at: date | None = None
    image_url: str | None = None
    audio_url: str | None = None
    audio_format: Literal["mp3", "m4a", "aac", "ogg", "wav", "opus"] | None = None
    language: str | None = None
    country: str | None = None
    guid: str | None = None
    canonical_url: str | None = None
    source_kind: Literal["canonical", "aggregator", "unknown"] = "unknown"
    aggregator_provider: str | None = None

    @field_validator("published_at", mode="before")
    @classmethod
    def _parse_iso_date(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    @field_validator("language", mode="before")
    @classmethod
    def _validate_language_code(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, str) and ISO_639_RE.match(value.lower()):
            return value.lower()
        return None

    @field_validator("country", mode="before")
    @classmethod
    def _validate_country_code(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, str) and ISO_3166_RE.match(value.lower()):
            return value.lower()
        return None

    @field_validator("image_url", "audio_url", "canonical_url", mode="before")
    @classmethod
    def _validate_absolute_url(cls, value):
        if value in (None, ""):
            return None
        if isinstance(value, str) and URL_RE.match(value):
            return value
        return None

    @field_validator("aggregator_provider", mode="before")
    @classmethod
    def _normalize_aggregator(cls, value):
        if value in (None, ""):
            return None
        if not isinstance(value, str):
            return None
        normalized = value.strip().lower().replace(" ", "_").replace("-", "_")
        # Apple's various brand spellings → canonical key.
        if normalized in ("apple", "itunes", "applepodcasts"):
            return "apple_podcasts"
        return normalized


class FetchDetailsOutput(BaseModel):
    """Wrapped agent output: the three things the orchestrator needs."""

    details: EpisodeDetails
    report: FetchDetailsReport
    concise: ConciseMessage


@lru_cache(maxsize=1)
def get_agent() -> Agent[FetchDetailsDeps, FetchDetailsOutput]:
    """Lazy + memoized agent factory.

    Reads ``RAGTIME_FETCH_DETAILS_*`` settings inside the lazy path so
    the module stays importable without Django configured. Tests that
    need a different model use ``Agent.override(model=TestModel())``
    on the returned agent.
    """
    from django.conf import settings

    model_string = getattr(
        settings, "RAGTIME_FETCH_DETAILS_MODEL", "openai:gpt-4.1-mini"
    )
    api_key = getattr(settings, "RAGTIME_FETCH_DETAILS_API_KEY", "")
    model = build_model(model_string, api_key)

    agent = Agent(
        model,
        deps_type=FetchDetailsDeps,
        output_type=FetchDetailsOutput,
        system_prompt=SYSTEM_PROMPT,
    )
    agent.tool(tools.fetch_url)
    agent.tool(tools.search_apple_podcasts)
    agent.tool(tools.search_fyyd)
    return agent


def get_model_string() -> str:
    """Return the configured model string (for ``FetchDetailsRun.model``)."""
    from django.conf import settings

    return getattr(
        settings, "RAGTIME_FETCH_DETAILS_MODEL", "openai:gpt-4.1-mini"
    )


async def run(submitted_url: str) -> tuple[FetchDetailsOutput, FetchDetailsDeps, dict | None]:
    """Run the agent against *submitted_url* and return its output + deps + usage.

    Returns the structured output, the deps object (carrying the full
    tool-call trace), and the Pydantic AI usage dict (or ``None`` if
    Pydantic AI didn't surface one).
    """
    agent = get_agent()
    deps = FetchDetailsDeps(submitted_url=submitted_url)
    user_msg = f"URL: {submitted_url}"
    result = await agent.run(user_msg, deps=deps)
    usage = _usage_dict(result)
    return result.output, deps, usage


def _usage_dict(result) -> dict | None:
    """Best-effort extraction of Pydantic AI usage as a JSON-serializable dict."""
    try:
        usage = result.usage()
    except Exception:
        return None
    if usage is None:
        return None
    # Pydantic AI's Usage exposes ``__dict__`` of token counters.
    if hasattr(usage, "model_dump"):
        try:
            return usage.model_dump()
        except Exception:
            pass
    try:
        return dict(usage.__dict__)
    except Exception:
        return None
