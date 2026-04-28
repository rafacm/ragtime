"""Decoupled recovery layer for pipeline failures.

Walks a configurable strategy chain (agent -> human) when a pipeline
step fails. Each strategy decides whether it can handle the failure and
either resolves it or escalates to the next strategy.
"""

import dataclasses
import logging
from abc import ABC, abstractmethod

from django.conf import settings

from .events import StepFailureEvent
from .models import RecoveryAttempt

logger = logging.getLogger(__name__)

MAX_RECOVERY_ATTEMPTS = 5


@dataclasses.dataclass
class RecoveryResult:
    success: bool
    message: str
    should_escalate: bool


class RecoveryStrategy(ABC):
    name: str

    @abstractmethod
    def can_handle(self, event: StepFailureEvent) -> bool: ...

    @abstractmethod
    def attempt(self, event: StepFailureEvent) -> RecoveryResult: ...


class AgentStrategy(RecoveryStrategy):
    """AI agent that uses Playwright to recover from fetch-details and downloading failures."""

    name = "agent"

    def can_handle(self, event: StepFailureEvent) -> bool:
        enabled = getattr(settings, "RAGTIME_RECOVERY_AGENT_ENABLED", False)
        if not enabled:
            return False
        return event.step_name in ("fetching_details", "downloading")

    def attempt(self, event: StepFailureEvent) -> RecoveryResult:
        try:
            from .agents import run_recovery_agent

            result = run_recovery_agent(event)
            if result.success:
                from .agents.recovery_resume import resume_pipeline

                resumed = resume_pipeline(event, result)
                if resumed:
                    return RecoveryResult(
                        success=True,
                        message=result.message,
                        should_escalate=False,
                    )
                return RecoveryResult(
                    success=False,
                    message="Agent reported success but pipeline could not resume",
                    should_escalate=True,
                )
            return RecoveryResult(
                success=False,
                message=result.message or "Agent could not recover",
                should_escalate=True,
            )
        except Exception as exc:
            logger.exception(
                "Agent recovery failed for episode %s", event.episode_id
            )
            return RecoveryResult(
                success=False,
                message=f"Agent error: {exc}",
                should_escalate=True,
            )


class HumanEscalationStrategy(RecoveryStrategy):
    """Final fallback — marks the failure as awaiting human intervention."""

    name = "human"

    def can_handle(self, event: StepFailureEvent) -> bool:
        return True

    def attempt(self, event: StepFailureEvent) -> RecoveryResult:
        return RecoveryResult(
            success=False,
            message=f"Escalated to human: {event.error_type} error in {event.step_name}",
            should_escalate=False,
        )


STRATEGY_REGISTRY = {
    "agent": AgentStrategy,
    "human": HumanEscalationStrategy,
}


def get_recovery_chain():
    """Build the recovery strategy chain from settings."""
    chain_names = getattr(settings, "RAGTIME_RECOVERY_CHAIN", ["agent", "human"])
    chain = []
    for name in chain_names:
        cls = STRATEGY_REGISTRY.get(name)
        if cls:
            chain.append(cls())
        else:
            logger.warning("Unknown recovery strategy: %s", name)
    return chain


def handle_step_failure(sender, event, pipeline_event, **kwargs):
    """Signal handler that walks the recovery chain on step failure.

    Connected to ``step_failed`` in ``apps.py:ready()``.
    """
    # Infinite loop prevention
    total_attempts = RecoveryAttempt.objects.filter(
        episode_id=event.episode_id,
        pipeline_event__step_name=event.step_name,
    ).count()
    if total_attempts >= MAX_RECOVERY_ATTEMPTS:
        logger.warning(
            "Max recovery attempts (%d) reached for episode %s step %s — no further recovery",
            MAX_RECOVERY_ATTEMPTS,
            event.episode_id,
            event.step_name,
        )
        return

    chain = get_recovery_chain()
    for strategy in chain:
        if not strategy.can_handle(event):
            continue

        result = strategy.attempt(event)

        status = RecoveryAttempt.Status.ATTEMPTED
        if not result.success and not result.should_escalate:
            status = RecoveryAttempt.Status.AWAITING_HUMAN

        RecoveryAttempt.objects.create(
            episode_id=event.episode_id,
            pipeline_event=pipeline_event,
            strategy=strategy.name,
            status=status,
            success=result.success,
            message=result.message,
        )

        if result.success or not result.should_escalate:
            return
