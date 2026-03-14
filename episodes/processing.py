from django.utils import timezone

from .models import PIPELINE_STEPS, ProcessingRun, ProcessingStep


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
    """Mark a step as COMPLETED. If it's the last step, mark the run COMPLETED."""
    run = get_active_run(episode)
    if run is None:
        return
    now = timezone.now()
    ProcessingStep.objects.filter(run=run, step_name=step_name).update(
        status=ProcessingStep.Status.COMPLETED,
        finished_at=now,
    )
    # Check if all steps are done (COMPLETED or SKIPPED)
    remaining = run.steps.exclude(
        status__in=[ProcessingStep.Status.COMPLETED, ProcessingStep.Status.SKIPPED]
    ).exists()
    if not remaining:
        run.status = ProcessingRun.Status.COMPLETED
        run.finished_at = now
        run.save(update_fields=["status", "finished_at"])


def fail_step(episode, step_name, error_message=""):
    """Mark a step as FAILED, mark the run as FAILED."""
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


def skip_step(episode, step_name):
    """Mark a step as SKIPPED."""
    run = get_active_run(episode)
    if run is None:
        return
    ProcessingStep.objects.filter(run=run, step_name=step_name).update(
        status=ProcessingStep.Status.SKIPPED,
    )
