"""Fetch Details pipeline step (was: Scrape).

Owns: status transitions, HTML fetch + clean, fast-path skip when required
fields are pre-filled, empty-field-only merge of extracted metadata,
completeness check, error handling. Delegates the LLM call to the
``fetch_details`` Pydantic AI agent in ``episodes/agents/fetch_details.py``.
"""

import asyncio
import logging

import httpx
from bs4 import BeautifulSoup

from .agents import fetch_details as fetch_details_agent
from .models import Episode
from .processing import complete_step, fail_step, start_step
from .telemetry import trace_step

logger = logging.getLogger(__name__)

TAGS_TO_STRIP = [
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "canvas",
    "nav",
    "footer",
]

MAX_HTML_LENGTH = 30_000

# Step's "ready to advance" contract — independent of the agent's output
# contract. The step refuses to leave FETCHING_DETAILS without these fields.
# ``audio_url`` is intentionally NOT required: the download agent owns
# audio-URL discovery (cheap-path wget if present, otherwise
# podcast-index lookup or Playwright browsing) for cases where
# fetch-details could only recover a title.
REQUIRED_FIELDS = ("title",)


def fetch_html(url: str) -> str:
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": "RAGtime/0.1 (podcast metadata fetcher)"},
    )
    response.raise_for_status()
    return response.text


def clean_html(raw_html: str) -> str:
    soup = BeautifulSoup(raw_html, "html.parser")
    for tag in soup.find_all(TAGS_TO_STRIP):
        tag.decompose()
    text = str(soup)
    if len(text) > MAX_HTML_LENGTH:
        text = text[:MAX_HTML_LENGTH]
    return text


def _has_required_fields(episode: Episode) -> bool:
    return all(getattr(episode, f) for f in REQUIRED_FIELDS)


def _run_agent_sync(html: str) -> fetch_details_agent.EpisodeDetails:
    """Run the async fetch_details agent from sync DBOS step context.

    DBOS step bodies are sync. ``asyncio.run`` is fine here — each step
    body is its own short-lived call, and Pydantic AI's ``Agent.run``
    creates HTTP clients lazily per call.
    """
    return asyncio.run(fetch_details_agent.run(html))


@trace_step("fetch_episode_details")
def fetch_episode_details(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    episode.status = Episode.Status.FETCHING_DETAILS
    episode.save(update_fields=["status", "updated_at"])
    start_step(episode, Episode.Status.FETCHING_DETAILS)

    try:
        # Fetch and clean HTML if not already stored
        if not episode.scraped_html:
            raw_html = fetch_html(episode.url)
            episode.scraped_html = clean_html(raw_html)
            episode.save(update_fields=["scraped_html", "updated_at"])

        # If user already filled all required fields (reprocess after needs_review)
        if _has_required_fields(episode):
            complete_step(episode, Episode.Status.FETCHING_DETAILS)
            episode.status = Episode.Status.DOWNLOADING
            episode.save(update_fields=["status", "updated_at"])
            return

        # Extract metadata via the fetch_details agent
        details = _run_agent_sync(episode.scraped_html)

        # Apply extracted fields (only update empty fields)
        for field in ("title", "description", "image_url", "language", "audio_url", "guid"):
            value = getattr(details, field)
            if value and not getattr(episode, field):
                setattr(episode, field, value)

        if details.published_at and not episode.published_at:
            episode.published_at = details.published_at

        # Check completeness
        update_fields = [
            "status", "error_message",
            "title", "description", "image_url",
            "language", "audio_url", "guid", "published_at", "updated_at",
        ]
        if _has_required_fields(episode):
            complete_step(episode, Episode.Status.FETCHING_DETAILS)
            episode.status = Episode.Status.DOWNLOADING
            episode.save(update_fields=update_fields)
        else:
            incomplete_exc = ValueError("Incomplete metadata: missing required fields")
            episode.error_message = str(incomplete_exc)
            episode.status = Episode.Status.FAILED
            # Save BEFORE fail_step: recovery runs synchronously via signal
            # and may set a new status — saving after would overwrite it.
            episode.save(update_fields=update_fields)
            fail_step(
                episode, Episode.Status.FETCHING_DETAILS,
                str(incomplete_exc),
                exc=incomplete_exc,
            )
            logger.warning(
                "Episode %s: incomplete metadata after fetch_details", episode_id
            )

    except Exception as exc:
        logger.exception("Failed to fetch details for episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.FETCHING_DETAILS, str(exc), exc=exc)
