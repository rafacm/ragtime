from unittest.mock import patch

from django.test import TestCase

from episodes.models import Episode


class SignalTests(TestCase):
    @patch("episodes.workflows.episode_queue")
    def test_creating_episode_enqueues_workflow(self, mock_queue):
        episode = Episode.objects.create(url="https://example.com/ep/signal-1")
        from episodes.workflows import process_episode

        mock_queue.enqueue.assert_called_once_with(process_episode, episode.pk)

    @patch("episodes.workflows.episode_queue")
    def test_creating_episode_marks_queued(self, mock_queue):
        episode = Episode.objects.create(url="https://example.com/ep/signal-1b")

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.QUEUED)

    @patch("episodes.workflows.episode_queue")
    def test_updating_episode_does_not_enqueue_workflow(self, mock_queue):
        episode = Episode.objects.create(url="https://example.com/ep/signal-2")
        mock_queue.reset_mock()

        episode.title = "Updated"
        episode.save()

        mock_queue.enqueue.assert_not_called()

    @patch("episodes.workflows.episode_queue")
    def test_status_change_does_not_enqueue_workflow(self, mock_queue):
        episode = Episode.objects.create(url="https://example.com/ep/signal-3")
        mock_queue.reset_mock()

        episode.status = Episode.Status.DOWNLOADING
        episode.save(update_fields=["status", "updated_at"])

        mock_queue.enqueue.assert_not_called()
