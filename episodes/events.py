"""Step-level event dataclasses (legacy shape).

Kept as light-weight value objects so a few callers (telemetry,
fetch_details_step's regression test) keep importing them. With
``ProcessingRun`` / ``ProcessingStep`` / ``PipelineEvent`` deleted,
these are no longer persisted — they exist only as in-memory
event objects.

The ``classify_error`` helper lives on for ``StepFailureEvent``-style
construction in tests.
"""

import dataclasses
import json
import subprocess
from datetime import datetime


@dataclasses.dataclass(frozen=True)
class StepCompletedEvent:
    episode_id: int
    step_name: str
    duration_seconds: float
    timestamp: datetime


@dataclasses.dataclass(frozen=True)
class StepFailureEvent:
    episode_id: int
    step_name: str
    error_type: str
    error_message: str
    http_status: int | None
    exception_class: str
    timestamp: datetime


def classify_error(exc: Exception) -> tuple[str, int | None]:
    """Classify an exception into ``(error_type, http_status|None)``."""
    import httpx

    if isinstance(exc, httpx.HTTPStatusError):
        return ("http", exc.response.status_code)
    if isinstance(exc, httpx.TimeoutException):
        return ("timeout", None)
    if isinstance(exc, (subprocess.CalledProcessError, subprocess.TimeoutExpired)):
        return ("subprocess", None)

    try:
        import openai

        if isinstance(exc, openai.APIError):
            return ("provider", None)
    except ImportError:
        pass

    if isinstance(exc, (KeyError, ValueError, json.JSONDecodeError)):
        return ("validation", None)

    return ("system", None)
