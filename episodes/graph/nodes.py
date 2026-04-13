"""Graph nodes wrapping existing pipeline step functions.

Each node calls the existing step function (which handles all DB
updates, status transitions, and processing helpers), then reads
the episode's current status from the DB to update the graph state.
"""

import logging

from ..models import Episode
from .state import EpisodeState

logger = logging.getLogger(__name__)


def _refresh_state(state: EpisodeState, expected_next: str) -> EpisodeState:
    """Read the episode status from DB and update state accordingly."""
    episode = Episode.objects.get(pk=state["episode_id"])
    new_state: EpisodeState = {"status": episode.status}

    if episode.status == Episode.Status.FAILED:
        new_state["error"] = episode.error_message
    else:
        new_state["error"] = ""
        new_state["failed_step"] = ""

    return new_state


def scrape_node(state: EpisodeState) -> EpisodeState:
    """Run the scraping step."""
    from ..scraper import scrape_episode

    episode = Episode.objects.get(pk=state["episode_id"])

    # Set status to SCRAPING if not already (e.g., first run from PENDING)
    if episode.status == Episode.Status.PENDING:
        episode.status = Episode.Status.SCRAPING
        episode.save(update_fields=["status", "updated_at"])

    scrape_episode(state["episode_id"])
    result = _refresh_state(state, Episode.Status.DOWNLOADING)

    if result.get("status") == Episode.Status.FAILED:
        result["failed_step"] = Episode.Status.SCRAPING
    return result


def download_node(state: EpisodeState) -> EpisodeState:
    """Run the download step."""
    from ..downloader import download_episode

    download_episode(state["episode_id"])
    result = _refresh_state(state, Episode.Status.TRANSCRIBING)

    if result.get("status") == Episode.Status.FAILED:
        result["failed_step"] = Episode.Status.DOWNLOADING
    return result


def transcribe_node(state: EpisodeState) -> EpisodeState:
    """Run the transcription step."""
    from ..transcriber import transcribe_episode

    transcribe_episode(state["episode_id"])
    result = _refresh_state(state, Episode.Status.SUMMARIZING)

    if result.get("status") == Episode.Status.FAILED:
        result["failed_step"] = Episode.Status.TRANSCRIBING
    return result


def summarize_node(state: EpisodeState) -> EpisodeState:
    """Run the summarization step."""
    from ..summarizer import summarize_episode

    summarize_episode(state["episode_id"])
    result = _refresh_state(state, Episode.Status.CHUNKING)

    if result.get("status") == Episode.Status.FAILED:
        result["failed_step"] = Episode.Status.SUMMARIZING
    return result


def chunk_node(state: EpisodeState) -> EpisodeState:
    """Run the chunking step."""
    from ..chunker import chunk_episode

    chunk_episode(state["episode_id"])
    result = _refresh_state(state, Episode.Status.EXTRACTING)

    if result.get("status") == Episode.Status.FAILED:
        result["failed_step"] = Episode.Status.CHUNKING
    return result


def extract_node(state: EpisodeState) -> EpisodeState:
    """Run the entity extraction step."""
    from ..extractor import extract_entities

    extract_entities(state["episode_id"])
    result = _refresh_state(state, Episode.Status.RESOLVING)

    if result.get("status") == Episode.Status.FAILED:
        result["failed_step"] = Episode.Status.EXTRACTING
    return result


def resolve_node(state: EpisodeState) -> EpisodeState:
    """Run the entity resolution step."""
    from ..resolver import resolve_entities

    resolve_entities(state["episode_id"])
    result = _refresh_state(state, Episode.Status.EMBEDDING)

    if result.get("status") == Episode.Status.FAILED:
        result["failed_step"] = Episode.Status.RESOLVING
    return result


def embed_node(state: EpisodeState) -> EpisodeState:
    """Run the embedding step (placeholder — marks episode as READY)."""
    episode = Episode.objects.get(pk=state["episode_id"])

    from ..processing import complete_step, start_step

    start_step(episode, Episode.Status.EMBEDDING)

    # TODO: implement actual embedding logic
    complete_step(episode, Episode.Status.EMBEDDING)
    episode.status = Episode.Status.READY
    episode.save(update_fields=["status", "updated_at"])

    return {"status": Episode.Status.READY, "error": ""}


def recovery_node(state: EpisodeState) -> EpisodeState:
    """Attempt recovery for a failed step using the recovery chain."""
    from ..recovery import get_recovery_chain, handle_step_failure_from_graph

    episode = Episode.objects.get(pk=state["episode_id"])
    failed_step = state.get("failed_step", "")

    success = handle_step_failure_from_graph(episode, failed_step)

    if success:
        # Recovery succeeded — read the new status from DB
        episode.refresh_from_db(fields=["status"])
        return {
            "status": episode.status,
            "recovery_result": "success",
            "error": "",
        }
    else:
        return {
            "status": Episode.Status.FAILED,
            "recovery_result": "failed",
            "error": state.get("error", ""),
        }
