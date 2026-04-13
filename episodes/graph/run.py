"""Entry point for running the ingestion pipeline graph."""

import logging

from ..models import Episode
from ..processing import create_run
from .state import EpisodeState

logger = logging.getLogger(__name__)


def run_pipeline(episode_id: int) -> EpisodeState:
    """Run the ingestion pipeline for an episode.

    Creates a ProcessingRun, builds the initial state, and invokes
    the compiled LangGraph pipeline.  The graph's entry router
    determines which step to start from based on existing episode data.

    Returns the final graph state.
    """
    episode = Episode.objects.get(pk=episode_id)

    # Create a processing run for audit trail
    create_run(episode)

    initial_state: EpisodeState = {
        "episode_id": episode_id,
        "status": episode.status,
        "failed_step": "",
        "error": "",
        "recovery_result": "",
    }

    from .pipeline import pipeline

    final_state = pipeline.invoke(initial_state)

    logger.info(
        "Pipeline completed for episode %s — final status: %s",
        episode_id,
        final_state.get("status", "unknown"),
    )

    return final_state
