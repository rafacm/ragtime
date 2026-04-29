"""Tests for the DBOS workflow wrappers.

The wrappers in ``episodes/workflows.py`` translate the legacy
"set Episode.status = FAILED and return" failure idiom into typed
exceptions so DBOS records the actual outcome instead of treating
failed runs as success.
"""

from unittest.mock import patch

from django.test import TestCase

from episodes.models import Episode
from episodes.workflows import (
    DownloadStepFailed,
    EmbedFailed,
    ExtractFailed,
    FetchDetailsFailed,
    ResolveStepOutput,
    StepFailed,
    StepOutput,
    _raise_if_failed,
    next_attempt,
    resolve_step,
    workflow_id_for,
)


class WorkflowIdHelpersTests(TestCase):
    def test_workflow_id_for_default_attempt(self):
        self.assertEqual(workflow_id_for(42), "episode-42-run-1")

    def test_workflow_id_for_explicit_attempt(self):
        self.assertEqual(workflow_id_for(42, 7), "episode-42-run-7")

    @patch("episodes.workflows.DBOS")
    def test_next_attempt_returns_one_when_dbos_unavailable(self, mock_dbos):
        mock_dbos.list_workflows.side_effect = RuntimeError("dbos not running")
        self.assertEqual(next_attempt(42), 1)

    @patch("episodes.workflows.DBOS")
    def test_next_attempt_returns_one_when_no_prior_runs(self, mock_dbos):
        mock_dbos.list_workflows.return_value = []
        self.assertEqual(next_attempt(42), 1)

    @patch("episodes.workflows.DBOS")
    def test_next_attempt_increments_past_highest_run(self, mock_dbos):
        class _Wf:
            def __init__(self, wid):
                self.workflow_id = wid

        mock_dbos.list_workflows.return_value = [
            _Wf("episode-42-run-1"),
            _Wf("episode-42-run-3"),  # gap is fine — pick max + 1
            _Wf("episode-99-run-7"),  # other episode — ignored
            _Wf("not-an-episode-id"),  # unrelated — ignored
        ]
        self.assertEqual(next_attempt(42), 4)


class RaiseIfFailedTests(TestCase):
    def _create_episode(self, **kwargs):
        with patch("episodes.signals.DBOS"):
            return Episode.objects.create(**kwargs)

    def test_no_raise_when_status_not_failed(self):
        episode = self._create_episode(
            url="https://example.com/wf/1",
            status=Episode.Status.DOWNLOADING,
        )
        # Must not raise.
        _raise_if_failed(episode.pk, FetchDetailsFailed)

    def test_raises_typed_exception_when_failed(self):
        episode = self._create_episode(
            url="https://example.com/wf/2",
            status=Episode.Status.FAILED,
            error_message="boom",
        )
        with self.assertRaises(FetchDetailsFailed) as ctx:
            _raise_if_failed(episode.pk, FetchDetailsFailed)
        self.assertEqual(ctx.exception.episode_id, episode.pk)
        self.assertEqual(ctx.exception.error_message, "boom")
        self.assertIn("boom", str(ctx.exception))

    def test_step_failed_classes_carry_step_name(self):
        # Each subclass identifies its phase; useful when the exception
        # surfaces in DBOS workflow traces.
        self.assertEqual(FetchDetailsFailed.step_name, "fetching_details")
        self.assertEqual(DownloadStepFailed.step_name, "downloading")
        self.assertEqual(ExtractFailed.step_name, "extracting")
        self.assertEqual(EmbedFailed.step_name, "embedding")
        # All inherit StepFailed.
        self.assertTrue(issubclass(FetchDetailsFailed, StepFailed))


class ResolveStepReturnsEnrichmentIdsTests(TestCase):
    """``resolve_step`` must hand the entity IDs up to the workflow.

    Calling ``Queue.enqueue`` from inside a step is silently deduped
    against the step's ``function_id``: only the first enqueue per
    ``(step, target_func)`` pair runs, regardless of how many times
    we call it. Wikidata enrichment therefore has to be enqueued from
    workflow context (``process_episode``), not from inside
    ``resolve_step`` itself. This test pins the contract.
    """

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.DBOS"):
            return Episode.objects.create(**kwargs)

    @patch("episodes.workflows.resolver.resolve_entities", return_value=[7, 11, 13])
    def test_returns_resolve_step_output_with_entity_ids(self, mock_resolver):
        episode = self._create_episode(
            url="https://example.com/wf/resolve-1",
            status=Episode.Status.RESOLVING,
        )
        result = resolve_step.__wrapped__(episode.pk)  # bypass DBOS decorator
        self.assertIsInstance(result, ResolveStepOutput)
        self.assertEqual(result.entity_ids_to_enrich, (7, 11, 13))
        # ResolveStepOutput is a StepOutput subclass — the workflow's
        # generic step-handling continues to work.
        self.assertIsInstance(result, StepOutput)
        mock_resolver.assert_called_once_with(episode.pk)

    @patch("episodes.workflows.resolver.resolve_entities", return_value=[])
    def test_empty_resolve_returns_empty_tuple(self, _mock):
        episode = self._create_episode(
            url="https://example.com/wf/resolve-2",
            status=Episode.Status.RESOLVING,
        )
        result = resolve_step.__wrapped__(episode.pk)
        self.assertEqual(result.entity_ids_to_enrich, ())
