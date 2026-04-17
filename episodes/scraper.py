import logging

import httpx
from bs4 import BeautifulSoup

from .models import Episode
from .telemetry import trace_step
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_scraping_provider

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

SCRAPE_SYSTEM_PROMPT = """\
You are a metadata extractor for podcast episode web pages.
Given the cleaned HTML of a podcast episode page, extract the following fields.

Rules:
- For URLs (image_url, audio_url): return absolute URLs. If the HTML contains \
relative URLs, you cannot resolve them, so return them as-is.
- For audio_url: look for links to .mp3 files in <audio>, <source>, or <a> tags. \
Also check <meta> tags and embedded player markup.
- For published_at: return in YYYY-MM-DD format.
- For language: return an ISO 639-1 code (e.g. "en", "es", "de", "sv").
- Check <meta> tags (og:title, og:description, og:image, etc.) first, \
then fall back to page content.
- Return null for any field you cannot confidently determine.
"""

SCRAPE_RESPONSE_SCHEMA = {
    "name": "episode_metadata",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "title": {"type": ["string", "null"]},
            "description": {"type": ["string", "null"]},
            "published_at": {"type": ["string", "null"]},
            "image_url": {"type": ["string", "null"]},
            "language": {"type": ["string", "null"]},
            "audio_url": {"type": ["string", "null"]},
        },
        "required": [
            "title",
            "description",
            "published_at",
            "image_url",
            "language",
            "audio_url",
        ],
        "additionalProperties": False,
    },
}

REQUIRED_FIELDS = ("title", "audio_url")


def fetch_html(url: str) -> str:
    response = httpx.get(
        url,
        follow_redirects=True,
        timeout=30,
        headers={"User-Agent": "RAGtime/0.1 (podcast metadata scraper)"},
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


@trace_step("scrape_episode")
def scrape_episode(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    episode.status = Episode.Status.SCRAPING
    episode.save(update_fields=["status", "updated_at"])
    start_step(episode, Episode.Status.SCRAPING)

    try:
        # Fetch and clean HTML if not already stored
        if not episode.scraped_html:
            raw_html = fetch_html(episode.url)
            episode.scraped_html = clean_html(raw_html)
            episode.save(update_fields=["scraped_html", "updated_at"])

        # If user already filled all required fields (reprocess after needs_review)
        if _has_required_fields(episode):
            complete_step(episode, Episode.Status.SCRAPING)
            episode.status = Episode.Status.DOWNLOADING
            episode.save(update_fields=["status", "updated_at"])
            return

        # Extract metadata via LLM
        provider = get_scraping_provider()
        result = provider.structured_extract(
            system_prompt=SCRAPE_SYSTEM_PROMPT,
            user_content=episode.scraped_html,
            response_schema=SCRAPE_RESPONSE_SCHEMA,
        )

        # Apply extracted fields (only update empty fields)
        for field in ("title", "description", "image_url", "language", "audio_url"):
            value = result.get(field)
            if value and not getattr(episode, field):
                setattr(episode, field, value)

        if result.get("published_at") and not episode.published_at:
            episode.published_at = result["published_at"]

        # Check completeness
        update_fields = [
            "status", "error_message",
            "title", "description", "image_url",
            "language", "audio_url", "published_at", "updated_at",
        ]
        if _has_required_fields(episode):
            complete_step(episode, Episode.Status.SCRAPING)
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
                episode, Episode.Status.SCRAPING,
                str(incomplete_exc),
                exc=incomplete_exc,
            )
            logger.warning(
                "Episode %s: incomplete metadata after scraping", episode_id
            )

    except Exception as exc:
        logger.exception("Failed to scrape episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.SCRAPING, str(exc), exc=exc)
