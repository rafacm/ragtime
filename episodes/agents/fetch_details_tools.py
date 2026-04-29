"""Three keyless tools for the fetch_details investigator agent.

* ``fetch_url(url)`` — httpx + BeautifulSoup, returns cleaned HTML
  bounded to a fixed character cap so the LLM context stays small.
* ``search_apple_podcasts(show, episode_title)`` — iTunes Search API,
  reuses :class:`episodes.podcast_aggregators.itunes.ItunesAggregator`.
* ``search_fyyd(show, episode_title)`` — fyyd.de search, reuses
  :class:`episodes.podcast_aggregators.fyyd.FyydAggregator`.

Module purity rule: agent + tools may import Pydantic AI / Pydantic /
stdlib / ``episodes/podcast_aggregators/`` (sibling sub-package) only.
No Django, no DBOS, no ``episodes.models`` — keeps the agent bootable
from a bare interpreter for unit/eval tests.

Each tool appends a structured trace entry to ``ctx.deps.tool_calls``
so the orchestrator can persist the full trace to ``FetchDetailsRun``
without re-walking Pydantic AI's run messages.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup
from pydantic import BaseModel
from pydantic_ai import RunContext

from .fetch_details_deps import FetchDetailsDeps

logger = logging.getLogger(__name__)

# Cap returned HTML at ~30 KB — same budget as the previous single-call
# extractor used. Larger pages are truncated; the agent can ask for a
# different URL if it needs more.
MAX_HTML_LENGTH = 30_000
# How much of the cleaned HTML we record to ``tool_calls`` — the full
# output goes to the LLM, the excerpt is what the admin sees.
TRACE_HTML_EXCERPT = 5_000

FETCH_TIMEOUT = 30.0
USER_AGENT = "RAGtime/0.1 (podcast metadata fetcher)"

TAGS_TO_STRIP = (
    "script", "style", "noscript", "iframe", "svg", "canvas",
    "nav", "footer",
)


class ItunesEpisodeCandidate(BaseModel):
    """One candidate returned by ``search_apple_podcasts``."""

    audio_url: str = ""
    title: str = ""
    show_name: str = ""
    duration_seconds: int | None = None
    episode_page_url: str = ""


class FyydEpisodeCandidate(BaseModel):
    """One candidate returned by ``search_fyyd``."""

    audio_url: str = ""
    title: str = ""
    show_name: str = ""
    duration_seconds: int | None = None


def _clean_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(TAGS_TO_STRIP):
        tag.decompose()
    text = str(soup)
    if len(text) > MAX_HTML_LENGTH:
        text = text[:MAX_HTML_LENGTH]
    return text


def _record(deps: FetchDetailsDeps, tool: str, **fields: Any) -> None:
    deps.tool_calls.append({"tool": tool, **fields})


async def fetch_url(ctx: RunContext[FetchDetailsDeps], url: str) -> str:
    """Fetch *url* and return cleaned HTML (capped at ~30 KB).

    Returns ``"FETCH_FAILED: <reason>"`` on network/HTTP error so the
    LLM gets a usable signal without raising into the agent loop.
    Use this on the submitted URL first; you may also call it with a
    cross-linked URL discovered via the search tools.
    """
    deps = ctx.deps

    def _sync_fetch() -> tuple[bool, str]:
        try:
            response = httpx.get(
                url,
                follow_redirects=True,
                timeout=FETCH_TIMEOUT,
                headers={"User-Agent": USER_AGENT},
            )
            response.raise_for_status()
            return True, _clean_html(response.text)
        except httpx.HTTPError as exc:
            return False, f"FETCH_FAILED: {exc}"

    ok, body = await asyncio.to_thread(_sync_fetch)
    _record(
        deps,
        "fetch_url",
        input={"url": url},
        ok=ok,
        output_excerpt=body[:TRACE_HTML_EXCERPT],
    )
    return body


async def search_apple_podcasts(
    ctx: RunContext[FetchDetailsDeps],
    show: str = "",
    episode_title: str = "",
) -> list[ItunesEpisodeCandidate]:
    """Search Apple Podcasts (iTunes Search API) for episode candidates.

    Returns up to 10 candidates. Each candidate exposes the audio
    enclosure URL plus the show name and episode title — combine with
    a ``fetch_url`` call to confirm a cross-link to a publisher's
    canonical page when needed.
    """
    from ..podcast_aggregators.itunes import ItunesAggregator

    deps = ctx.deps

    candidates = await asyncio.to_thread(
        ItunesAggregator().search,
        episode_title,
        show,
    )
    out = [
        ItunesEpisodeCandidate(
            audio_url=c.audio_url,
            title=c.title,
            show_name=c.show_name,
            duration_seconds=c.duration_seconds,
            episode_page_url=c.episode_page_url,
        )
        for c in candidates
    ]
    _record(
        deps,
        "search_apple_podcasts",
        input={"show": show, "episode_title": episode_title},
        ok=True,
        output_excerpt=[c.model_dump() for c in out[:3]],
        result_count=len(out),
    )
    return out


async def search_fyyd(
    ctx: RunContext[FetchDetailsDeps],
    show: str = "",
    episode_title: str = "",
) -> list[FyydEpisodeCandidate]:
    """Search fyyd.de for episode candidates by show + episode title.

    Returns up to 10 candidates. Useful when iTunes returns no match
    or when the show is European/German — fyyd's coverage skews that
    way. Network failures return an empty list rather than raising.
    """
    from ..podcast_aggregators.fyyd import FyydAggregator

    deps = ctx.deps

    candidates = await asyncio.to_thread(
        FyydAggregator().search,
        episode_title,
        show,
    )
    out = [
        FyydEpisodeCandidate(
            audio_url=c.audio_url,
            title=c.title,
            show_name=c.show_name,
            duration_seconds=c.duration_seconds,
        )
        for c in candidates
    ]
    _record(
        deps,
        "search_fyyd",
        input={"show": show, "episode_title": episode_title},
        ok=True,
        output_excerpt=[c.model_dump() for c in out[:3]],
        result_count=len(out),
    )
    return out
