from django.db import IntegrityError
from django.test import TestCase

from episodes.models import Episode


class EpisodeModelTests(TestCase):
    def test_default_status_is_pending(self):
        episode = Episode.objects.create(url="https://example.com/episode/1")
        self.assertEqual(episode.status, Episode.Status.PENDING)

    def test_url_uniqueness(self):
        Episode.objects.create(url="https://example.com/episode/1")
        with self.assertRaises(IntegrityError):
            Episode.objects.create(url="https://example.com/episode/1")

    def test_str_returns_title_when_set(self):
        episode = Episode(url="https://example.com/ep/1", title="My Episode")
        self.assertEqual(str(episode), "My Episode")

    def test_str_returns_url_when_no_title(self):
        episode = Episode(url="https://example.com/ep/1")
        self.assertEqual(str(episode), "https://example.com/ep/1")

    def test_new_statuses_exist(self):
        self.assertEqual(Episode.Status.SCRAPING, "scraping")
        self.assertEqual(Episode.Status.DOWNLOADING, "downloading")

    def test_metadata_fields_blank_by_default(self):
        episode = Episode.objects.create(url="https://example.com/ep/1")
        self.assertEqual(episode.title, "")
        self.assertEqual(episode.description, "")
        self.assertIsNone(episode.published_at)
        self.assertEqual(episode.image_url, "")
        self.assertEqual(episode.language, "")
        self.assertEqual(episode.audio_url, "")
        self.assertEqual(episode.scraped_html, "")
