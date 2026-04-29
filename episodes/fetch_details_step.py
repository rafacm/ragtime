"""Fetch Details pipeline step.

Orchestrates the Fetch Details investigator agent and persists a per-run
``FetchDetailsRun`` record. The agent owns metadata extraction and
cross-linking; this module owns the state machine: status transitions,
overwriting Episode fields with the agent's authoritative output, and
mapping the agent's structured ``concise.outcome`` onto pipeline status.

Authority model: the agent's output is authoritative — Episode columns
are overwritten directly, not merged. Re-running via the admin
``reprocess`` action will overwrite admin-edited values.

DBOS interface: this module is DBOS-agnostic. The
``@DBOS.step()`` wrapper in ``episodes/workflows.py`` reads
``DBOS.workflow_id`` and passes it in as ``dbos_workflow_id``; the
orchestrator records it onto the new ``FetchDetailsRun`` row for
forensics. The wrapper still uses the ``_raise_if_failed`` typed-
exception pattern at the end.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date

from django.db import transaction
from django.utils import timezone

from .agents import fetch_details as fetch_details_agent
from .models import Episode, FetchDetailsRun
from .telemetry import trace_step

logger = logging.getLogger(__name__)


_OUTCOME_TO_STATUS = {
    FetchDetailsRun.Outcome.OK: Episode.Status.DOWNLOADING,
    FetchDetailsRun.Outcome.PARTIAL: Episode.Status.DOWNLOADING,
    FetchDetailsRun.Outcome.NOT_A_PODCAST_EPISODE: Episode.Status.FAILED,
    FetchDetailsRun.Outcome.UNREACHABLE: Episode.Status.FAILED,
    FetchDetailsRun.Outcome.EXTRACTION_FAILED: Episode.Status.FAILED,
}


def _next_run_index(episode_id: int) -> int:
    last = (
        FetchDetailsRun.objects.filter(episode_id=episode_id)
        .order_by("-run_index")
        .values_list("run_index", flat=True)
        .first()
    )
    return (last or 0) + 1


def _run_agent_sync(submitted_url: str):
    """Run the async fetch_details agent from sync DBOS step context."""
    return asyncio.run(fetch_details_agent.run(submitted_url))


def _apply_details(episode: Episode, details) -> list[str]:
    """Overwrite Episode fields with the agent's authoritative output.

    Returns the list of field names that were touched, suitable for
    ``save(update_fields=...)``.
    """
    fields: list[str] = []

    def _set(name, value, *, allow_blank=False):
        # Replace empty strings the agent emits with our model defaults
        # (empty string), but honour ``None`` as "agent had no value".
        if value is None:
            return
        if isinstance(value, str) and not value and not allow_blank:
            return
        setattr(episode, name, value)
        fields.append(name)

    _set("title", details.title or "")
    _set("description", details.description or "")
    _set("image_url", details.image_url or "")
    _set("language", details.language or "")
    _set("audio_url", details.audio_url or "")
    _set("audio_format", details.audio_format or "")
    _set("country", details.country or "")
    _set("guid", details.guid or "")
    _set("canonical_url", details.canonical_url or "")
    _set("aggregator_provider", details.aggregator_provider or "")

    if details.published_at and isinstance(details.published_at, date):
        episode.published_at = details.published_at
        fields.append("published_at")

    # source_kind is a TextChoices field with a non-blank default —
    # always reflect the agent's classification.
    episode.source_kind = details.source_kind or Episode.SourceKind.UNKNOWN
    fields.append("source_kind")

    return fields


def _persist_run(
    *,
    episode_id: int,
    run_index: int,
    output_json: dict | None,
    tool_calls: list[dict],
    usage_json: dict | None,
    outcome: str,
    error_message: str,
    dbos_workflow_id: str,
    model: str,
) -> FetchDetailsRun:
    return FetchDetailsRun.objects.create(
        episode_id=episode_id,
        run_index=run_index,
        finished_at=timezone.now(),
        model=model,
        outcome=outcome or "",
        output_json=output_json,
        tool_calls_json=tool_calls,
        usage_json=usage_json,
        error_message=error_message,
        dbos_workflow_id=dbos_workflow_id or "",
    )


@trace_step("fetch_episode_details")
def fetch_episode_details(episode_id: int, dbos_workflow_id: str = "") -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    episode.status = Episode.Status.FETCHING_DETAILS
    episode.save(update_fields=["status", "updated_at"])

    run_index = _next_run_index(episode_id)
    model_string = fetch_details_agent.get_model_string()

    try:
        output, deps, usage = _run_agent_sync(episode.url)
    except Exception as exc:
        # Agent crashed before producing structured output — record a
        # row with no outcome, fail the episode, propagate so DBOS can
        # log the exception via _raise_if_failed.
        logger.exception("fetch_details agent crashed for episode %s", episode_id)
        with transaction.atomic():
            _persist_run(
                episode_id=episode_id,
                run_index=run_index,
                output_json=None,
                tool_calls=[],
                usage_json=None,
                outcome="",
                error_message=str(exc),
                dbos_workflow_id=dbos_workflow_id,
                model=model_string,
            )
            episode.status = Episode.Status.FAILED
            episode.error_message = str(exc)
            episode.save(update_fields=["status", "error_message", "updated_at"])
        return

    outcome_value = output.concise.outcome
    summary = output.concise.summary

    with transaction.atomic():
        details_fields = _apply_details(episode, output.details)

        new_status = _OUTCOME_TO_STATUS.get(outcome_value, Episode.Status.FAILED)
        episode.status = new_status
        if new_status == Episode.Status.FAILED:
            episode.error_message = summary or outcome_value
        else:
            episode.error_message = ""
        update_fields = list(set(
            details_fields + ["status", "error_message", "updated_at"]
        ))
        episode.save(update_fields=update_fields)

        _persist_run(
            episode_id=episode_id,
            run_index=run_index,
            output_json=output.model_dump(mode="json"),
            tool_calls=deps.tool_calls,
            usage_json=usage,
            outcome=outcome_value,
            error_message="",
            dbos_workflow_id=dbos_workflow_id,
            model=model_string,
        )

    if new_status == Episode.Status.FAILED:
        logger.warning(
            "Episode %s: fetch_details outcome=%s — %s",
            episode_id, outcome_value, summary,
        )
