"""Tests for the recovery layer."""

import importlib.util
import unittest
from unittest.mock import patch

from django.test import TestCase, override_settings

_has_recovery_deps = (
    importlib.util.find_spec("pydantic_ai") is not None
    and importlib.util.find_spec("playwright") is not None
)

from episodes.models import Episode, PipelineEvent, ProcessingRun, ProcessingStep, RecoveryAttempt
from episodes.recovery import (
    AgentStrategy,
    HumanEscalationStrategy,
    get_recovery_chain,
    handle_step_failure,
)


def _make_failure_event(**overrides):
    """Build a StepFailureEvent dataclass for testing."""
    from episodes.events import StepFailureEvent
    from django.utils import timezone

    defaults = {
        "episode_id": 1,
        "step_name": "scraping",
        "processing_run_id": 1,
        "processing_step_id": 1,
        "error_type": "http",
        "error_message": "403 Forbidden",
        "http_status": 403,
        "exception_class": "httpx.HTTPStatusError",
        "attempt_number": 1,
        "cached_data": {},
        "timestamp": timezone.now(),
    }
    defaults.update(overrides)
    return StepFailureEvent(**defaults)


class AgentStrategyTests(TestCase):
    @override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=False)
    def test_disabled_by_default(self):
        strategy = AgentStrategy()
        event = _make_failure_event(step_name="scraping")
        self.assertFalse(strategy.can_handle(event))

    @override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=True)
    def test_handles_scraping(self):
        strategy = AgentStrategy()
        event = _make_failure_event(step_name="scraping")
        self.assertTrue(strategy.can_handle(event))

    @override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=True)
    def test_handles_downloading(self):
        strategy = AgentStrategy()
        event = _make_failure_event(step_name="downloading")
        self.assertTrue(strategy.can_handle(event))

    @override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=True)
    def test_does_not_handle_transcribing(self):
        strategy = AgentStrategy()
        event = _make_failure_event(step_name="transcribing")
        self.assertFalse(strategy.can_handle(event))

    @unittest.skipUnless(_has_recovery_deps, "pydantic-ai not installed")
    @override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=True)
    @patch("episodes.agents.run_recovery_agent")
    def test_agent_success_calls_resume(self, mock_agent):
        """Successful agent recovery calls resume_pipeline."""
        from episodes.agents.deps import RecoveryAgentResult

        mock_agent.return_value = RecoveryAgentResult(
            success=True,
            audio_url="https://cdn.example.com/ep.mp3",
            message="Found it",
        )
        strategy = AgentStrategy()
        event = _make_failure_event(step_name="scraping")

        with patch("episodes.agents.resume.resume_pipeline") as mock_resume:
            result = strategy.attempt(event)

        self.assertTrue(result.success)
        self.assertFalse(result.should_escalate)
        mock_resume.assert_called_once()

    @unittest.skipUnless(_has_recovery_deps, "pydantic-ai not installed")
    @override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=True)
    @patch("episodes.agents.run_recovery_agent")
    def test_agent_failure_escalates(self, mock_agent):
        """When the agent fails, it escalates to the next strategy."""
        from episodes.agents.deps import RecoveryAgentResult

        mock_agent.return_value = RecoveryAgentResult(
            success=False,
            message="Could not find audio URL",
        )
        strategy = AgentStrategy()
        event = _make_failure_event(step_name="scraping")
        result = strategy.attempt(event)

        self.assertFalse(result.success)
        self.assertTrue(result.should_escalate)

    @unittest.skipUnless(_has_recovery_deps, "pydantic-ai not installed")
    @override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=True)
    @patch("episodes.agents.run_recovery_agent", side_effect=RuntimeError("Browser crashed"))
    def test_agent_exception_escalates(self, _mock_agent):
        """When the agent raises, it escalates with error message."""
        strategy = AgentStrategy()
        event = _make_failure_event(step_name="scraping")
        result = strategy.attempt(event)

        self.assertFalse(result.success)
        self.assertTrue(result.should_escalate)
        self.assertIn("Agent error", result.message)
        self.assertIn("Browser crashed", result.message)


class HumanEscalationStrategyTests(TestCase):
    def test_always_handles(self):
        strategy = HumanEscalationStrategy()
        event = _make_failure_event(step_name="transcribing")
        self.assertTrue(strategy.can_handle(event))

    def test_does_not_escalate(self):
        strategy = HumanEscalationStrategy()
        event = _make_failure_event(step_name="scraping")
        result = strategy.attempt(event)
        self.assertFalse(result.success)
        self.assertFalse(result.should_escalate)


class RecoveryChainTests(TestCase):
    @override_settings(RAGTIME_RECOVERY_CHAIN=["agent", "human"])
    def test_default_chain(self):
        chain = get_recovery_chain()
        self.assertEqual(len(chain), 2)
        self.assertIsInstance(chain[0], AgentStrategy)
        self.assertIsInstance(chain[1], HumanEscalationStrategy)

    @override_settings(RAGTIME_RECOVERY_CHAIN=["human"])
    def test_human_only_chain(self):
        chain = get_recovery_chain()
        self.assertEqual(len(chain), 1)
        self.assertIsInstance(chain[0], HumanEscalationStrategy)


@override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=False)
class HandleStepFailureTests(TestCase):
    def test_creates_awaiting_human_attempt(self):
        """Default chain (agent disabled) escalates directly to human."""
        episode = Episode.objects.create(url="https://example.com/rec/1")
        run = ProcessingRun.objects.create(episode=episode)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.FAILED
        )
        pipeline_event = PipelineEvent.objects.create(
            episode=episode,
            processing_step=step,
            event_type=PipelineEvent.EventType.FAILED,
            step_name="scraping",
            error_type="http",
            error_message="403 Forbidden",
        )

        event = _make_failure_event(episode_id=episode.pk)
        handle_step_failure(sender=Episode, event=event, pipeline_event=pipeline_event)

        attempt = RecoveryAttempt.objects.get(episode=episode)
        self.assertEqual(attempt.strategy, "human")
        self.assertEqual(attempt.status, RecoveryAttempt.Status.AWAITING_HUMAN)
        self.assertFalse(attempt.success)

    @unittest.skipUnless(_has_recovery_deps, "pydantic-ai not installed")
    @patch("episodes.agents.run_recovery_agent")
    @override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=True)
    def test_agent_escalates_to_human(self, mock_agent):
        """When agent is enabled but fails, it escalates to human."""
        from episodes.agents.deps import RecoveryAgentResult

        mock_agent.return_value = RecoveryAgentResult(
            success=False, message="Could not find audio"
        )

        episode = Episode.objects.create(url="https://example.com/rec/2")
        run = ProcessingRun.objects.create(episode=episode)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.FAILED
        )
        pipeline_event = PipelineEvent.objects.create(
            episode=episode,
            processing_step=step,
            event_type=PipelineEvent.EventType.FAILED,
            step_name="scraping",
            error_type="http",
            error_message="403 Forbidden",
        )

        event = _make_failure_event(episode_id=episode.pk)
        handle_step_failure(sender=Episode, event=event, pipeline_event=pipeline_event)

        attempts = RecoveryAttempt.objects.filter(episode=episode).order_by("created_at")
        self.assertEqual(attempts.count(), 2)
        self.assertEqual(attempts[0].strategy, "agent")
        self.assertEqual(attempts[1].strategy, "human")
        self.assertEqual(attempts[1].status, RecoveryAttempt.Status.AWAITING_HUMAN)

    def test_max_attempts_prevents_recovery(self):
        """After MAX_RECOVERY_ATTEMPTS, no further recovery is attempted."""
        episode = Episode.objects.create(url="https://example.com/rec/3")
        run = ProcessingRun.objects.create(episode=episode)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.FAILED
        )
        pipeline_event = PipelineEvent.objects.create(
            episode=episode,
            processing_step=step,
            event_type=PipelineEvent.EventType.FAILED,
            step_name="scraping",
        )

        # Create 5 existing attempts (the max)
        for i in range(5):
            RecoveryAttempt.objects.create(
                episode=episode,
                pipeline_event=pipeline_event,
                strategy="human",
                status=RecoveryAttempt.Status.AWAITING_HUMAN,
            )

        event = _make_failure_event(episode_id=episode.pk)
        handle_step_failure(sender=Episode, event=event, pipeline_event=pipeline_event)

        # No new attempts created
        self.assertEqual(RecoveryAttempt.objects.filter(episode=episode).count(), 5)


@override_settings(RAGTIME_RECOVERY_AGENT_ENABLED=False)
class IntegrationTests(TestCase):
    """Test that pipeline failures trigger recovery via signals."""

    def test_fail_step_with_exc_triggers_recovery(self):
        """fail_step with exc triggers recovery when handler is connected."""
        episode = Episode.objects.create(url="https://example.com/int/1")
        run = ProcessingRun.objects.create(episode=episode)
        ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.RUNNING
        )

        from episodes.processing import fail_step
        from episodes.recovery import handle_step_failure
        from episodes.signals import step_failed

        # Manually connect recovery handler (no longer auto-connected in apps.py)
        step_failed.connect(handle_step_failure)
        try:
            exc = RuntimeError("scrape failed")
            fail_step(episode, "scraping", str(exc), exc=exc)
        finally:
            step_failed.disconnect(handle_step_failure)

        # Should have a PipelineEvent and a RecoveryAttempt
        self.assertTrue(PipelineEvent.objects.filter(episode=episode).exists())
        attempt = RecoveryAttempt.objects.get(episode=episode)
        self.assertEqual(attempt.status, RecoveryAttempt.Status.AWAITING_HUMAN)
