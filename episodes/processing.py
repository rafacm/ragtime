import logging

from django.utils import timezone

from .models import PIPELINE_STEPS, Episode, PipelineEvent, ProcessingRun, ProcessingStep

logger = logging.getLogger(__name__)


def create_run(episode, resume_from=""):
    """Create a ProcessingRun with all ProcessingStep records.

    Steps before ``resume_from`` are pre-marked SKIPPED.
    """
    run = ProcessingRun.objects.create(
        episode=episode,
        resumed_from_step=resume_from,
    )

    skip = bool(resume_from)
    for step_name in PIPELINE_STEPS:
        if skip and step_name == resume_from:
            skip = False
        ProcessingStep.objects.create(
            run=run,
            step_name=step_name,
            status=(
                ProcessingStep.Status.SKIPPED if skip
                else ProcessingStep.Status.PENDING
            ),
        )

    return run


def get_active_run(episode):
    """Return the most recent RUNNING run for the episode, or None."""
    return (
        ProcessingRun.objects.filter(
            episode=episode, status=ProcessingRun.Status.RUNNING
        )
        .order_by("-started_at")
        .first()
    )


def start_step(episode, step_name):
    """Mark a step as RUNNING and set started_at."""
    run = get_active_run(episode)
    if run is None:
        return
    ProcessingStep.objects.filter(run=run, step_name=step_name).update(
        status=ProcessingStep.Status.RUNNING,
        started_at=timezone.now(),
    )


def complete_step(episode, step_name):
    """Mark a step as COMPLETED. If it's the last step, mark the run COMPLETED.

    Builds a StepCompletedEvent and sends the step_completed signal.
    Persists a PipelineEvent record for audit.
    """
    run = get_active_run(episode)
    if run is None:
        return
    now = timezone.now()
    ProcessingStep.objects.filter(run=run, step_name=step_name).update(
        status=ProcessingStep.Status.COMPLETED,
        finished_at=now,
    )

    # Build and send completion event
    try:
        step_obj = ProcessingStep.objects.get(run=run, step_name=step_name)
        from .events import build_completion_event
        from .signals import step_completed

        event = build_completion_event(episode, step_name, run, step_obj)
        PipelineEvent.objects.create(
            episode=episode,
            processing_step=step_obj,
            event_type=PipelineEvent.EventType.COMPLETED,
            step_name=step_name,
            context={"duration_seconds": event.duration_seconds},
        )
        step_completed.send(sender=Episode, event=event)
    except Exception:
        logger.exception("Failed to emit step_completed event for %s", step_name)

    # Check if all steps are done (COMPLETED or SKIPPED)
    remaining = run.steps.exclude(
        status__in=[ProcessingStep.Status.COMPLETED, ProcessingStep.Status.SKIPPED]
    ).exists()
    if not remaining:
        run.status = ProcessingRun.Status.COMPLETED
        run.finished_at = now
        run.save(update_fields=["status", "finished_at"])


def fail_step(episode, step_name, error_message="", exc=None):
    """Mark a step as FAILED, mark the run as FAILED.

    When *exc* is provided, builds a StepFailureEvent and sends the
    step_failed signal. Persists a PipelineEvent record for audit.
    """
    run = get_active_run(episode)
    if run is None:
        return
    now = timezone.now()
    ProcessingStep.objects.filter(run=run, step_name=step_name).update(
        status=ProcessingStep.Status.FAILED,
        finished_at=now,
        error_message=error_message,
    )
    run.status = ProcessingRun.Status.FAILED
    run.finished_at = now
    run.save(update_fields=["status", "finished_at"])

    if exc is not None:
        try:
            step_obj = ProcessingStep.objects.get(run=run, step_name=step_name)
            from .events import build_failure_event
            from .signals import step_failed

            event = build_failure_event(episode, step_name, run, step_obj, exc)
            pipeline_event = PipelineEvent.objects.create(
                episode=episode,
                processing_step=step_obj,
                event_type=PipelineEvent.EventType.FAILED,
                step_name=step_name,
                error_type=event.error_type,
                error_message=event.error_message,
                http_status=event.http_status,
                exception_class=event.exception_class,
                context={
                    "cached_data": event.cached_data,
                    "attempt_number": event.attempt_number,
                },
            )
            step_failed.send(sender=Episode, event=event, pipeline_event=pipeline_event)
        except Exception:
            logger.exception("Failed to emit step_failed event for %s", step_name)


def skip_step(episode, step_name):
    """Mark a step as SKIPPED."""
    run = get_active_run(episode)
    if run is None:
        return
    ProcessingStep.objects.filter(run=run, step_name=step_name).update(
        status=ProcessingStep.Status.SKIPPED,
    )
