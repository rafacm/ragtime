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

from dbos import DBOS, Queue
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


@DBOS.workflow()
def process_episode(episode_id: int, from_step: str = "") -> None:
    """Run the full episode ingestion pipeline with durable checkpointing."""
    _bootstrap_status(episode_id, from_step)

    skipping = bool(from_step)
    for step_name, step_fn in _PIPELINE_DISPATCH:
        if skipping:
            if step_name == from_step:
                skipping = False
            else:
                continue
        step_fn(episode_id)


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
    fetch_details_step.fetch_episode_details(episode_id)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.FETCHING_DETAILS)


@DBOS.step()
def download_step(episode_id: int) -> StepOutput:
    downloader.download_episode(episode_id)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.DOWNLOADING)


@DBOS.step()
def transcribe_step(episode_id: int) -> StepOutput:
    transcriber.transcribe_episode(episode_id)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.TRANSCRIBING)


@DBOS.step()
def summarize_step(episode_id: int) -> StepOutput:
    summarizer.summarize_episode(episode_id)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.SUMMARIZING)


@DBOS.step()
def chunk_step(episode_id: int) -> StepOutput:
    chunker.chunk_episode(episode_id)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.CHUNKING)


@DBOS.step()
def extract_step(episode_id: int) -> StepOutput:
    extractor.extract_entities(episode_id)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.EXTRACTING)


@DBOS.step()
def resolve_step(episode_id: int) -> StepOutput:
    resolver.resolve_entities(episode_id)
    return StepOutput(episode_id=episode_id, step_name=Episode.Status.RESOLVING)


@DBOS.step()
def embed_step(episode_id: int) -> StepOutput:
    embedder.embed_episode(episode_id)
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


def workflow_id_for(episode_id: int, attempt: int = 1) -> str:
    """Deterministic DBOS workflow ID — DBOS rejects duplicates.

    Replaces the ``unique_running_run_per_episode`` partial index that
    the deleted ``ProcessingRun`` table used to enforce.
    """
    return f"episode-{episode_id}-run-{attempt}"
