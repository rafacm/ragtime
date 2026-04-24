"""Tests for episodes JSON endpoints."""

from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from episodes.models import Episode


def _create_episode(**kwargs) -> Episode:
    defaults = {
        "url": "https://example.com/ep/1",
        "title": "Test Episode",
        "status": Episode.Status.READY,
    }
    defaults.update(kwargs)
    with patch("episodes.signals.DBOS"):
        return Episode.objects.create(**defaults)


class EpisodeListApiTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="alice", password="secret-pass"
        )

    def test_anonymous_redirects_to_login(self):
        response = self.client.get(reverse("episodes:api-episode-list"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accounts/login/", response["Location"])

    def test_returns_only_ready_episodes(self):
        _create_episode(url="https://example.com/ep/ready-1", title="Ready 1")
        _create_episode(url="https://example.com/ep/ready-2", title="Ready 2")
        _create_episode(
            url="https://example.com/ep/pending",
            title="Pending",
            status=Episode.Status.PENDING,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("episodes:api-episode-list"))
        self.assertEqual(response.status_code, 200)
        titles = [e["title"] for e in response.json()["episodes"]]
        self.assertEqual(sorted(titles), ["Ready 1", "Ready 2"])

    def test_orders_by_published_at_desc(self):
        _create_episode(
            url="https://example.com/ep/old",
            title="Old",
            published_at=date(2020, 1, 1),
        )
        _create_episode(
            url="https://example.com/ep/new",
            title="New",
            published_at=date(2024, 6, 1),
        )
        _create_episode(
            url="https://example.com/ep/no-date",
            title="No Date",
            published_at=None,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("episodes:api-episode-list"))
        titles = [e["title"] for e in response.json()["episodes"]]
        self.assertEqual(titles[0], "New")
        self.assertIn("Old", titles)

    def test_limit_param_honored(self):
        for i in range(5):
            _create_episode(
                url=f"https://example.com/ep/{i}",
                title=f"Ep {i}",
            )

        self.client.force_login(self.user)
        response = self.client.get(
            reverse("episodes:api-episode-list") + "?limit=2"
        )
        self.assertEqual(len(response.json()["episodes"]), 2)

    def test_serialized_fields_include_audio_url_and_image(self):
        _create_episode(
            url="https://example.com/ep/serialize",
            title="Fields",
            audio_url="https://cdn.example.com/audio.mp3",
            image_url="https://cdn.example.com/cover.jpg",
            duration=1234,
            published_at=date(2024, 1, 2),
            description="A description",
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("episodes:api-episode-list"))
        ep = response.json()["episodes"][0]
        self.assertEqual(ep["title"], "Fields")
        self.assertEqual(ep["audio_url"], "https://cdn.example.com/audio.mp3")
        self.assertEqual(ep["image_url"], "https://cdn.example.com/cover.jpg")
        self.assertEqual(ep["duration"], 1234)
        self.assertEqual(ep["published_at"], "2024-01-02")
        self.assertEqual(ep["description"], "A description")

    def test_audio_file_fallback_when_audio_url_empty(self):
        ep = _create_episode(
            url="https://example.com/ep/file-fallback",
            title="File Fallback",
            audio_url="",
        )
        ep.audio_file = SimpleUploadedFile(
            "fallback.mp3", b"\x00\x01", content_type="audio/mpeg"
        )
        ep.save()

        self.client.force_login(self.user)
        response = self.client.get(reverse("episodes:api-episode-list"))
        serialized = response.json()["episodes"][0]
        self.assertTrue(serialized["audio_url"])
        self.assertTrue(serialized["audio_url"].endswith(".mp3"))

    def test_description_truncated(self):
        _create_episode(
            url="https://example.com/ep/long-desc",
            title="Long",
            description="x" * 400,
        )

        self.client.force_login(self.user)
        response = self.client.get(reverse("episodes:api-episode-list"))
        desc = response.json()["episodes"][0]["description"]
        self.assertLess(len(desc), 400)
        self.assertTrue(desc.endswith("…"))

    def test_invalid_limit_rejected(self):
        self.client.force_login(self.user)
        response = self.client.get(
            reverse("episodes:api-episode-list") + "?limit=abc"
        )
        self.assertEqual(response.status_code, 400)
