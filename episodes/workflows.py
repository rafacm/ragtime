"""DBOS durable workflows for the episode ingestion pipeline.

One ``@DBOS.step()`` per pipeline phase — ``dbos workflow steps <id>``
mirrors ``PIPELINE_STEPS`` exactly. Each phase wraps the existing
module-level function and returns a structured dataclass on success;
failures propagate up and DBOS records the exception class + args.

DBOS owns the source of truth for workflow state. The ``Episode``
row carries the user-facing status / error_message; everything else
the deleted ``ProcessingRun`` / ``ProcessingStep`` / ``PipelineEvent``
tables tracked is now in the DBOS workflow log.
"""

from __future__ import annotations

import dataclasses
import logging

from dbos import DBOS, Queue, SetWorkflowID
from django.conf import settings

from . import (
    chunker,
    downloader,
    embedder,
    extractor,
    fetch_details_step,
    resolver,
    summarizer,
    transcriber,
)
from .models import PIPELINE_STEPS, Episode

logger = logging.getLogger(__name__)

# Pipeline-wide concurrency cap. Episodes beyond this limit sit in DBOS's
# queue table with ``Episode.Status.QUEUED`` until a worker frees a slot.
episode_queue = Queue(
    "episode_pipeline",
    concurrency=settings.RAGTIME_EPISODE_CONCURRENCY,
)


@dataclasses.dataclass(frozen=True)
class StepOutput:
    """Default success payload for steps without richer detail.

    DBOS persists this verbatim — visible via ``dbos workflow steps``.
    """

    episode_id: int
    step_name: str


@dataclasses.dataclass(frozen=True)
class ResolveStepOutput(StepOutput):
    """``resolve_step`` payload — carries the IDs to enqueue for enrichment.

    The Wikidata-enrichment workflow can't be enqueued from inside a
    step (DBOS keys the operation log on the step's ``function_id``,
    so only the first enqueue per ``(step, target_func)`` pair runs;
    every subsequent call returns the first call's handle without
    actually enqueueing). The step therefore returns the IDs and
    ``process_episode`` (workflow context) does the enqueue.
    """

    entity_ids_to_enrich: tuple[int, ...] = ()


class StepFailed(Exception):
    """Base class for pipeline-step failures recorded by DBOS.

    Step modules currently report failure by setting
    ``Episode.status = FAILED`` and returning normally — they do not
    raise. Each step wrapper below refreshes the episode after the
    legacy call returns and raises a typed subclass so DBOS records
    the actual outcome instead of treating the failed run as success.
    """

    step_name: str = ""

    def __init__(self, episode_id: int, error_message: str):
        self.episode_id = episode_id
        self.error_message = error_message
        super().__init__(
            f"{self.step_name or 'pipeline_step'} failed for episode {episode_id}: "
            f"{error_message}"
        )

    def __reduce__(self):
        # Pickle as a plain ``RuntimeError`` carrying the formatted
        # message. Two reasons:
        #
        # 1. **Cross-process portability.** DBOS persists step errors
        #    as base64-encoded pickle bytes. The standalone ``dbos
        #    workflow steps`` CLI (and DBOS Conductor) run outside the
        #    Django process and can't import ``episodes.workflows`` —
        #    unpickling a typed ``StepFailed`` subclass there raises
        #    ``ModuleNotFoundError`` and the CLI prints "exception
        #    object could not be deserialized". ``RuntimeError`` lives
        #    in the stdlib, so any Python process can rehydrate it.
        # 2. **Default ``Exception.__reduce__`` round-trip is broken**
        #    for our two-arg ``__init__`` signature (``self.args`` only
        #    carries the formatted message); a plain ``RuntimeError``
        #    payload sidesteps that entirely.
        #
        # Worker-side semantics are unchanged: in the process that
        # raises, ``except StepFailed`` / ``except FetchDetailsFailed``
        # still match. The typed shape only collapses at pickle time,
        # which is when we cross the process boundary anyway. No
        # caller currently catches by typed subclass (verified with
        # grep) — the typed hierarchy exists for log readability, not
        # control flow.
        return (RuntimeError, (str(self),))


class FetchDetailsFailed(StepFailed):
    step_name = "fetching_details"


class DownloadStepFailed(StepFailed):
    step_name = "downloading"


class TranscribeFailed(StepFailed):
    step_name = "transcribing"


class SummarizeFailed(StepFailed):
    step_name = "summarizing"


class ChunkFailed(StepFailed):
    step_name = "chunking"


class ExtractFailed(StepFailed):
    step_name = "extracting"


class ResolveFailed(StepFailed):
    step_name = "resolving"


class EmbedFailed(StepFailed):
    step_name = "embedding"


def _raise_if_failed(episode_id: int, exc_cls: type[StepFailed]) -> None:
    """Refresh the episode and raise *exc_cls* when its status is FAILED.

    The step modules signal failure by writing ``status = FAILED``
    rather than raising, so DBOS would otherwise see a successful
    return. Reading the row back here translates that signal into an
    exception DBOS records verbatim.
    """
    episode = Episode.objects.only("status", "error_message").get(pk=episode_id)
    if episode.status == Episode.Status.FAILED:
        raise exc_cls(episode_id, episode.error_message)


@DBOS.workflow()
def process_episode(episode_id: int, from_step: str = "") -> None:
    """Run the full episode ingestion pipeline with durable checkpointing.

    Pipeline-step results are captured in the workflow body so background
    follow-up work (currently: Wikidata enrichment for the entities
    ``resolve_step`` touched) can be enqueued from workflow context
    instead of from inside a step. ``Queue.enqueue`` calls inside a step
    are deduplicated against the step's ``function_id`` and silently
    return the first call's handle — so enqueueing inside a step would
    only ever start a single follow-up workflow regardless of how many
    times we called it.
    """
    _bootstrap_status(episode_id, from_step)

    skipping = bool(from_step)
    entity_ids_to_enrich: tuple[int, ...] = ()

    for step_name, step_fn in _PIPELINE_DISPATCH:
        if skipping:
            if step_name == from_step:
                skipping = False
            else:
                continue
        result = step_fn(episode_id)
        if step_name == Episode.Status.RESOLVING and isinstance(result, ResolveStepOutput):
            entity_ids_to_enrich = result.entity_ids_to_enrich

    if entity_ids_to_enrich:
        from .enrichment import enrich_entity_wikidata, wikidata_queue

        for entity_id in entity_ids_to_enrich:
            try:
                wikidata_queue.enqueue(enrich_entity_wikidata, entity_id)
            except Exception:
                logger.exception(
                    "Failed to enqueue Wikidata enrichment for entity %s",
                    entity_id,
                )


@DBOS.step()
def _bootstrap_status(episode_id: int, from_step: str) -> StepOutput:
    """Move QUEUED → first-pipeline-step (or *from_step*) once a worker picks up."""
    episode = Episode.objects.get(pk=episode_id)
    target_status = from_step or PIPELINE_STEPS[0]
    if episode.status == Episode.Status.QUEUED:
        episode.status = target_status
        episode.save(update_fields=["status", "updated_at"])
    return StepOutput(episode_id=episode_id, step_name=target_status)


@DBOS.step()
def fetch_details_step_(episode_id: int) -> StepOutput:
    # Read the workflow ID inside the step wrapper so the orchestrator
    # itself stays DBOS-import-free; persisted on FetchDetailsRun for
    # cross-reference forensics with ``dbos workflow steps``.
    workflow_id = ""
    try:
        workflow_id = DBOS.workflow_id or ""
    except Exception:
        pass
    fetch_details_step.fetch_episode_details(episode_id, workflow_id)
    _raise_if_failed(episode_id, FetchDetailsFailed)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.FETCHING_DETAILS)


@DBOS.step()
def download_step(episode_id: int) -> StepOutput:
    downloader.download_episode(episode_id)
    _raise_if_failed(episode_id, DownloadStepFailed)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.DOWNLOADING)


@DBOS.step()
def transcribe_step(episode_id: int) -> StepOutput:
    transcriber.transcribe_episode(episode_id)
    _raise_if_failed(episode_id, TranscribeFailed)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.TRANSCRIBING)


@DBOS.step()
def summarize_step(episode_id: int) -> StepOutput:
    summarizer.summarize_episode(episode_id)
    _raise_if_failed(episode_id, SummarizeFailed)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.SUMMARIZING)


@DBOS.step()
def chunk_step(episode_id: int) -> StepOutput:
    chunker.chunk_episode(episode_id)
    _raise_if_failed(episode_id, ChunkFailed)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.CHUNKING)


@DBOS.step()
def extract_step(episode_id: int) -> StepOutput:
    extractor.extract_entities(episode_id)
    _raise_if_failed(episode_id, ExtractFailed)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.EXTRACTING)


@DBOS.step()
def resolve_step(episode_id: int) -> ResolveStepOutput:
    entity_ids = resolver.resolve_entities(episode_id)
    _raise_if_failed(episode_id, ResolveFailed)
    return ResolveStepOutput(
        episode_id=episode_id,
        step_name=Episode.Status.RESOLVING,
        entity_ids_to_enrich=tuple(entity_ids or ()),
    )


@DBOS.step()
def embed_step(episode_id: int) -> StepOutput:
    embedder.embed_episode(episode_id)
    _raise_if_failed(episode_id, EmbedFailed)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.EMBEDDING)


_PIPELINE_DISPATCH = [
    (Episode.Status.FETCHING_DETAILS, fetch_details_step_),
    (Episode.Status.DOWNLOADING, download_step),
    (Episode.Status.TRANSCRIBING, transcribe_step),
    (Episode.Status.SUMMARIZING, summarize_step),
    (Episode.Status.CHUNKING, chunk_step),
    (Episode.Status.EXTRACTING, extract_step),
    (Episode.Status.RESOLVING, resolve_step),
    (Episode.Status.EMBEDDING, embed_step),
]


_WORKFLOW_ID_PREFIX = "episode-"


def workflow_id_for(episode_id: int, attempt: int = 1) -> str:
    """Deterministic DBOS workflow ID — DBOS rejects duplicates.

    Replaces the ``unique_running_run_per_episode`` partial index that
    the deleted ``ProcessingRun`` table used to enforce.
    """
    return f"{_WORKFLOW_ID_PREFIX}{episode_id}-run-{attempt}"


def next_attempt(episode_id: int) -> int:
    """Return the next ``run-<n>`` suffix for *episode_id*.

    Walks ``DBOS.list_workflows()`` looking for IDs that start with
    ``episode-<id>-run-`` and returns ``max(n) + 1`` (or ``1`` if
    there are no prior runs and / or DBOS isn't running).
    """
    prefix = f"{_WORKFLOW_ID_PREFIX}{episode_id}-run-"
    try:
        workflows = DBOS.list_workflows() or []
    except Exception:
        return 1

    max_n = 0
    for wf in workflows:
        wid = getattr(wf, "workflow_id", "")
        if not wid.startswith(prefix):
            continue
        try:
            n = int(wid[len(prefix):])
        except ValueError:
            continue
        if n > max_n:
            max_n = n
    return max_n + 1


def enqueue_episode(episode_id: int, from_step: str = "") -> str | None:
    """Enqueue ``process_episode`` with a deterministic workflow ID.

    Returns the workflow ID assigned (so admin views can link to it),
    or ``None`` if DBOS isn't running. Re-enqueueing the same
    ``(episode_id, attempt)`` pair is a no-op — DBOS dedups on
    workflow ID, replacing the dropped
    ``unique_running_run_per_episode`` constraint.
    """
    from dbos._error import DBOSException

    workflow_id = workflow_id_for(episode_id, next_attempt(episode_id))
    try:
        with SetWorkflowID(workflow_id):
            episode_queue.enqueue(process_episode, episode_id, from_step)
    except DBOSException:
        logger.debug(
            "DBOS not initialized; skipping enqueue for episode %s", episode_id
        )
        return None
    return workflow_id
