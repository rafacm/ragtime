"""Fetch Details Pydantic AI agent.

Single structured-output LLM call. No tools yet — this is the SDK swap
that puts the agent shape in place so a follow-up PR can attach browser
tools (URL discovery on interactive pages) absorbed from the recovery
agent.

Module purity rule: imports only Pydantic AI, Pydantic, stdlib, and
``agents/_model.py`` — no Django, no DBOS, no ``episodes.models``. This
keeps the agent bootable from a bare interpreter for unit/eval tests:

    from episodes.agents.fetch_details import run, EpisodeDetails

Tests can override the model with ``Agent.override(model=TestModel())``.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from functools import lru_cache

from pydantic import BaseModel, field_validator
from pydantic_ai import Agent

from ._model import build_model

ISO_639_RE = re.compile(r"^[a-z]{2}$")


SYSTEM_PROMPT = """\
You are a metadata extractor for podcast episode web pages.
Given the cleaned HTML of a podcast episode page, extract the following fields.

Rules:
- For URLs (image_url, audio_url): return absolute URLs. If the HTML contains \
relative URLs, you cannot resolve them, so return them as-is.
- For audio_url: look for links to .mp3 files in <audio>, <source>, or <a> tags. \
Also check <meta> tags and embedded player markup.
- For published_at: return in YYYY-MM-DD format.
- For language: return an ISO 639-1 code (e.g. "en", "es", "de", "sv").
- For guid: return the episode's RSS-feed-style identifier when one is present \
in the HTML — look for ``urn:`` URIs, ``itunes:episodeGuid``, ``<guid>`` tags, \
or ``data-guid``/``data-episode-id`` attributes. This is a hint for podcast \
index lookups, so any stable per-episode identifier is acceptable. Return null \
when none is visible.
- Check <meta> tags (og:title, og:description, og:image, etc.) first, \
then fall back to page content.
- Return null for any field you cannot confidently determine.
"""


class EpisodeDetails(BaseModel):
    """Structured output of the fetch_details agent.

    All fields are optional — the agent returns ``None`` for any field
    it cannot confidently extract. URLs are plain ``str`` (not
    ``HttpUrl``) because pages often embed relative URLs that the agent
    cannot resolve; the step orchestrator decides what to do with them.
    """

    title: str | None = None
    description: str | None = None
    published_at: date | None = None
    image_url: str | None = None
    language: str | None = None
    audio_url: str | None = None
    guid: str | None = None

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
        if isinstance(value, str) and ISO_639_RE.match(value):
            return value
        return None


@lru_cache(maxsize=1)
def get_agent() -> Agent[None, EpisodeDetails]:
    """Lazy + memoized agent factory.

    Reads the ``RAGTIME_FETCH_DETAILS_*`` settings inside the lazy path
    so the module stays importable without Django configured. Tests
    that need a different model use ``Agent.override(model=TestModel())``
    on the returned agent.
    """
    from django.conf import settings

    model_string = getattr(
        settings, "RAGTIME_FETCH_DETAILS_MODEL", "openai:gpt-4.1-mini"
    )
    api_key = getattr(settings, "RAGTIME_FETCH_DETAILS_API_KEY", "")
    model = build_model(model_string, api_key)

    return Agent(
        model,
        output_type=EpisodeDetails,
        system_prompt=SYSTEM_PROMPT,
    )


async def run(html: str) -> EpisodeDetails:
    """Run the agent against *html* and return the structured output."""
    agent = get_agent()
    result = await agent.run(html)
    return result.output
