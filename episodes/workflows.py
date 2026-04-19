"""DBOS durable workflows for the episode ingestion pipeline.

Replaces Django Q2 signal-driven dispatch with a single workflow that
sequences all pipeline steps, checkpointing after each one.
"""

import importlib
import logging

from dbos import DBOS

from .models import PIPELINE_STEPS, Episode, ProcessingRun, ProcessingStep
from .processing import create_run

logger = logging.getLogger(__name__)

STEP_FUNCTIONS = {
    Episode.Status.SCRAPING: "episodes.scraper.scrape_episode",
    Episode.Status.DOWNLOADING: "episodes.downloader.download_episode",
    Episode.Status.TRANSCRIBING: "episodes.transcriber.transcribe_episode",
    Episode.Status.SUMMARIZING: "episodes.summarizer.summarize_episode",
    Episode.Status.CHUNKING: "episodes.chunker.chunk_episode",
    Episode.Status.EXTRACTING: "episodes.extractor.extract_entities",
    Episode.Status.RESOLVING: "episodes.resolver.resolve_entities",
    Episode.Status.EMBEDDING: "episodes.embedder.embed_episode",
}


@DBOS.workflow()
def process_episode(episode_id: int, from_step: str = "") -> None:
    """Run the full episode ingestion pipeline with durable checkpointing."""
    run_id = create_run_step(episode_id, from_step)

    skipping = bool(from_step)
    for step_name in PIPELINE_STEPS:
        if skipping:
            if step_name == from_step:
                skipping = False
            else:
                continue

        execute_pipeline_step(episode_id, step_name)

        if not is_run_still_active(run_id):
            return

        if not did_step_complete(run_id, step_name):
            mark_run_failed(run_id, step_name)
            return


@DBOS.step()
def create_run_step(episode_id: int, from_step: str) -> int:
    episode = Episode.objects.get(pk=episode_id)
    return create_run(episode, resume_from=from_step).pk


@DBOS.step()
def execute_pipeline_step(episode_id: int, step_name: str) -> None:
    func_path = STEP_FUNCTIONS[step_name]
    module_path, func_name = func_path.rsplit(".", 1)
    module = importlib.import_module(module_path)
    func = getattr(module, func_name)
    func(episode_id)


@DBOS.step()
def is_run_still_active(run_id: int) -> bool:
    return ProcessingRun.objects.get(pk=run_id).status == ProcessingRun.Status.RUNNING


@DBOS.step()
def did_step_complete(run_id: int, step_name: str) -> bool:
    return (
        ProcessingStep.objects.filter(
            run_id=run_id, step_name=step_name, status=ProcessingStep.Status.COMPLETED
        ).exists()
    )


@DBOS.step()
def mark_run_failed(run_id: int, step_name: str) -> None:
    from django.utils import timezone

    run = ProcessingRun.objects.get(pk=run_id)
    run.status = ProcessingRun.Status.FAILED
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "finished_at"])
    logger.error(
        "Step %s returned without completing or failing — marking run %s as failed",
        step_name,
        run_id,
    )


@DBOS.workflow()
def run_agent_recovery(episode_id: int, pipeline_event_id: int) -> None:
    """Durable workflow for admin-triggered agent recovery retries."""
    execute_agent_recovery(episode_id, pipeline_event_id)


@DBOS.step()
def execute_agent_recovery(episode_id: int, pipeline_event_id: int) -> None:
    from django.utils import timezone

    from .events import StepFailureEvent
    from .models import PipelineEvent, RecoveryAttempt

    pe = PipelineEvent.objects.select_related("processing_step").get(
        pk=pipeline_event_id
    )
    episode = Episode.objects.get(pk=episode_id)

    attempt_number = (
        RecoveryAttempt.objects.filter(
            episode_id=episode_id,
            pipeline_event__step_name=pe.step_name,
        ).count()
        + 1
    )

    event = StepFailureEvent(
        episode_id=episode_id,
        step_name=pe.step_name,
        processing_run_id=pe.processing_step.run_id,
        processing_step_id=pe.processing_step_id,
        error_type=pe.error_type,
        error_message=pe.error_message,
        http_status=pe.http_status,
        exception_class=pe.exception_class,
        attempt_number=attempt_number,
        cached_data=pe.context.get("cached_data", {}),
        timestamp=timezone.now(),
    )

    try:
        from .agents import run_recovery_agent
        from .agents.resume import resume_pipeline

        result = run_recovery_agent(event)
        if result.success:
            resumed = resume_pipeline(event, result)
            if resumed:
                RecoveryAttempt.objects.create(
                    episode=episode,
                    pipeline_event=pe,
                    strategy="agent",
                    status=RecoveryAttempt.Status.ATTEMPTED,
                    success=True,
                    message=result.message,
                )
                logger.info(
                    "Admin-triggered agent recovery succeeded for episode %s",
                    episode_id,
                )
            else:
                RecoveryAttempt.objects.create(
                    episode=episode,
                    pipeline_event=pe,
                    strategy="agent",
                    status=RecoveryAttempt.Status.AWAITING_HUMAN,
                    success=False,
                    message="Agent reported success but pipeline could not resume",
                )
                logger.warning(
                    "Admin-triggered agent recovery: resume failed for episode %s",
                    episode_id,
                )
        else:
            RecoveryAttempt.objects.create(
                episode=episode,
                pipeline_event=pe,
                strategy="agent",
                status=RecoveryAttempt.Status.AWAITING_HUMAN,
                success=False,
                message=result.message or "Agent could not recover",
            )
            logger.info(
                "Admin-triggered agent recovery failed for episode %s", episode_id
            )
    except Exception as exc:
        RecoveryAttempt.objects.create(
            episode=episode,
            pipeline_event=pe,
            strategy="agent",
            status=RecoveryAttempt.Status.AWAITING_HUMAN,
            success=False,
            message=f"Agent error: {exc}",
        )
        logger.exception(
            "Admin-triggered agent recovery error for episode %s", episode_id
        )
