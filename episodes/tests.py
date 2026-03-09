from django.db import IntegrityError
from django.test import TestCase

from .models import Episode


class EpisodeModelTests(TestCase):
    def test_default_status_is_pending(self):
        episode = Episode.objects.create(url="https://example.com/episode/1")
        self.assertEqual(episode.status, Episode.Status.PENDING)

    def test_url_uniqueness(self):
        Episode.objects.create(url="https://example.com/episode/1")
        with self.assertRaises(IntegrityError):
            Episode.objects.create(url="https://example.com/episode/1")

    def test_str_returns_url(self):
        episode = Episode(url="https://example.com/episode/1")
        self.assertEqual(str(episode), "https://example.com/episode/1")


class EpisodeAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User

        cls.admin_user = User.objects.create_superuser(
            username="admin", password="testpass"
        )

    def setUp(self):
        self.client.login(username="admin", password="testpass")

    def test_changelist_loads(self):
        response = self.client.get("/admin/episodes/episode/")
        self.assertEqual(response.status_code, 200)

    def test_add_form_loads(self):
        response = self.client.get("/admin/episodes/episode/add/")
        self.assertEqual(response.status_code, 200)
