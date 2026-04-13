"""Conditional edge functions for the LangGraph ingestion pipeline.

Each function inspects the graph state and returns the name of the
next node to execute, or END to terminate.
"""

from langgraph.graph import END

from ..models import Episode
from .state import EpisodeState


def _has_data(episode, field):
    """Check if an episode field has meaningful data."""
    value = getattr(episode, field, None)
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return bool(value)


def route_entry(state: EpisodeState) -> str:
    """Determine which step to start from based on existing episode data.

    This enables resume-from-failure and skip-already-done behavior.
    """
    episode = Episode.objects.get(pk=state["episode_id"])

    if episode.status == Episode.Status.READY:
        return END

    # Walk forward through steps, skipping any with existing data
    if not _has_data(episode, "scraped_html") or not _has_data(episode, "audio_url"):
        return "scrape"

    if not episode.audio_file:
        return "download"

    if not _has_data(episode, "transcript"):
        return "transcribe"

    if not _has_data(episode, "summary_generated"):
        return "summarize"

    if not episode.chunks.exists():
        return "chunk"

    has_entities = episode.chunks.filter(
        entities_json__isnull=False
    ).exists()
    if not has_entities:
        return "extract"

    if not episode.entity_mentions.exists():
        return "resolve"

    # Everything exists up to resolve — run embed
    return "embed"


def after_step(state: EpisodeState) -> str:
    """Generic routing after any step: continue or handle failure."""
    if state.get("status") == Episode.Status.FAILED:
        failed_step = state.get("failed_step", "")
        # Only scraping and downloading support agent recovery
        if failed_step in (Episode.Status.SCRAPING, Episode.Status.DOWNLOADING):
            return "recovery"
        return END
    return "continue"


def after_recovery(state: EpisodeState) -> str:
    """Route after recovery: retry from the step recovery resumed to, or give up."""
    if state.get("recovery_result") != "success":
        return END

    # Recovery succeeded — the resume module already set the episode status.
    # Route back through the entry router to pick up from the right step.
    return "route"
