from unittest.mock import patch

from django.test import TestCase

from episodes.models import Episode


class SignalTests(TestCase):
    @patch("episodes.signals.DBOS")
    def test_creating_episode_starts_workflow(self, mock_dbos):
        episode = Episode.objects.create(url="https://example.com/ep/signal-1")
        from episodes.workflows import process_episode

        mock_dbos.start_workflow.assert_called_once_with(
            process_episode, episode.pk
        )

    @patch("episodes.signals.DBOS")
    def test_updating_episode_does_not_start_workflow(self, mock_dbos):
        episode = Episode.objects.create(url="https://example.com/ep/signal-2")
        mock_dbos.reset_mock()

        episode.title = "Updated"
        episode.save()

        mock_dbos.start_workflow.assert_not_called()

    @patch("episodes.signals.DBOS")
    def test_status_change_does_not_start_workflow(self, mock_dbos):
        episode = Episode.objects.create(url="https://example.com/ep/signal-3")
        mock_dbos.reset_mock()

        episode.status = Episode.Status.DOWNLOADING
        episode.save(update_fields=["status", "updated_at"])

        mock_dbos.start_workflow.assert_not_called()
