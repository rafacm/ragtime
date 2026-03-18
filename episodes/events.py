"""Structured pipeline events for success and failure tracking.

Dataclasses that carry all context needed by the recovery layer and
admin audit trail. ``classify_error()`` maps raw exceptions to a
category + optional HTTP status code.
"""

import dataclasses
import json
import subprocess
from datetime import datetime


@dataclasses.dataclass(frozen=True)
class StepCompletedEvent:
    episode_id: int
    step_name: str
    processing_run_id: int
    processing_step_id: int
    duration_seconds: float
    timestamp: datetime


@dataclasses.dataclass(frozen=True)
class StepFailureEvent:
    episode_id: int
    step_name: str
    processing_run_id: int
    processing_step_id: int
    error_type: str
    error_message: str
    http_status: int | None
    exception_class: str
    attempt_number: int
    cached_data: dict
    timestamp: datetime


def classify_error(exc: Exception) -> tuple[str, int | None]:
    """Classify an exception into (error_type, http_status|None)."""
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return ("http", exc.response.status_code)
    if isinstance(exc, httpx.TimeoutException):
        return ("timeout", None)
    if isinstance(exc, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
        return ("subprocess", None)

    # Check for OpenAI errors (optional dependency)
    try:
        import openai

        if isinstance(exc, openai.APIError):
            return ("provider", None)
    except ImportError:
        pass

    if isinstance(exc, (KeyError, ValueError, json.JSONDecodeError)):
        return ("validation", None)

    return ("system", None)


def build_completion_event(episode, step_name, run, step_obj):
    """Build a StepCompletedEvent from pipeline state."""
    from django.utils import timezone

    now = timezone.now()
    duration = 0.0
    if step_obj.started_at:
        duration = (now - step_obj.started_at).total_seconds()

    return StepCompletedEvent(
        episode_id=episode.pk,
        step_name=step_name,
        processing_run_id=run.pk,
        processing_step_id=step_obj.pk,
        duration_seconds=duration,
        timestamp=now,
    )


def build_failure_event(episode, step_name, run, step_obj, exc):
    """Build a StepFailureEvent from pipeline state and exception."""
    from django.utils import timezone

    from .models import RecoveryAttempt

    error_type, http_status = classify_error(exc)
    now = timezone.now()

    attempt_number = RecoveryAttempt.objects.filter(
        episode=episode,
        pipeline_event__step_name=step_name,
    ).count() + 1

    cached_data = {}
    if hasattr(episode, "scraped_html") and episode.scraped_html:
        cached_data["scraped_html_length"] = len(episode.scraped_html)
    if hasattr(episode, "audio_url") and episode.audio_url:
        cached_data["audio_url"] = episode.audio_url

    return StepFailureEvent(
        episode_id=episode.pk,
        step_name=step_name,
        processing_run_id=run.pk,
        processing_step_id=step_obj.pk,
        error_type=error_type,
        error_message=str(exc),
        http_status=http_status,
        exception_class=f"{type(exc).__module__}.{type(exc).__qualname__}",
        attempt_number=attempt_number,
        cached_data=cached_data,
        timestamp=now,
    )
