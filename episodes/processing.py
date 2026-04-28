"""Pipeline-step bookkeeping shims (no-ops after the DBOS state migration).

The ``ProcessingRun`` / ``ProcessingStep`` / ``PipelineEvent`` tables
that used to back these helpers were dropped — DBOS owns workflow
state now, and step functions own ``Episode.status`` transitions.

These stubs remain so step modules don't have to be rewritten; each
function is a no-op. Future cleanup will inline the few remaining
callers and delete this module.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def create_run(episode, resume_from: str = ""):  # noqa: D401 — legacy shim
    """No-op (used to be ``ProcessingRun`` factory)."""
    return None


def get_active_run(episode):
    return None


def start_step(episode, step_name) -> None:
    return None


def complete_step(episode, step_name) -> None:
    return None


def fail_step(episode, step_name, error_message: str = "", exc: Exception | None = None) -> None:
    return None


def skip_step(episode, step_name) -> None:
    return None
