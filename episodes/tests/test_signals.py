from unittest.mock import patch

from django.test import TestCase

from episodes.models import Episode


class SignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_creating_episode_queues_scrape(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/signal-1")
        mock_async.assert_called_once_with(
            "episodes.scraper.scrape_episode", episode.pk
        )

    @patch("episodes.signals.async_task")
    def test_updating_episode_does_not_requeue(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/signal-2")
        mock_async.reset_mock()

        episode.title = "Updated"
        episode.save()

        mock_async.assert_not_called()


class DownloadResizeSignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_status_change_to_downloading_queues_download(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-dl-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.DOWNLOADING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.downloader.download_episode", episode.pk
        )

    @patch("episodes.signals.async_task")
    def test_status_change_to_resizing_queues_resize(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-rs-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.RESIZING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.resizer.resize_episode", episode.pk
        )

    @patch("episodes.signals.async_task")
    def test_other_status_change_does_not_queue(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-other")
        mock_async.reset_mock()

        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_not_called()

    @patch("episodes.signals.async_task")
    def test_save_without_update_fields_does_not_queue(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-nuf")
        mock_async.reset_mock()

        episode.status = Episode.Status.DOWNLOADING
        episode.save()  # no update_fields

        mock_async.assert_not_called()


class TranscribeSignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_status_change_to_transcribing_queues_transcribe(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-tr-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.TRANSCRIBING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.transcriber.transcribe_episode", episode.pk
        )


class SummarizeSignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_status_change_to_summarizing_queues_summarize(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-sum-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.SUMMARIZING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.summarizer.summarize_episode", episode.pk
        )


class ExtractSignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_status_change_to_extracting_queues_extract(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-ext-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.EXTRACTING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.extractor.extract_entities", episode.pk
        )


class ResolveSignalTests(TestCase):
    @patch("episodes.signals.async_task")
    def test_status_change_to_resolving_queues_resolve(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/sig-res-1")
        mock_async.reset_mock()

        episode.status = Episode.Status.RESOLVING
        episode.save(update_fields=["status", "updated_at"])

        mock_async.assert_called_once_with(
            "episodes.resolver.resolve_entities", episode.pk
        )
