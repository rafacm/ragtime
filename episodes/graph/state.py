"""State schema for the LangGraph ingestion pipeline."""

from typing import TypedDict


class EpisodeState(TypedDict, total=False):
    """State passed between graph nodes.

    Nodes read the episode from the DB, do their work, and update
    these fields to inform routing decisions.
    """

    episode_id: int
    status: str           # episode status after the last node ran
    failed_step: str      # which step failed (for recovery routing)
    error: str            # error message from the failed step
    recovery_result: str  # "success" | "failed" | "" (for recovery node output)
    start_from: str       # override entry routing — force start from this step
