from unittest.mock import patch

from django.test import TestCase

from episodes.models import Episode


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

    @patch("episodes.signals.async_task")
    def test_detail_page_loads(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/admin-1")
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        self.assertEqual(response.status_code, 200)

    @patch("episodes.signals.async_task")
    def test_reprocess_action(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-2",
            status=Episode.Status.NEEDS_REVIEW,
        )
        mock_async.reset_mock()

        with patch("episodes.admin.async_task") as mock_admin_async:
            response = self.client.post(
                "/admin/episodes/episode/",
                {
                    "action": "reprocess",
                    "_selected_action": [episode.pk],
                },
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            mock_admin_async.assert_called_once_with(
                "episodes.scraper.scrape_episode", episode.pk
            )

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SCRAPING)

    @patch("episodes.signals.async_task")
    def test_metadata_fields_editable_in_needs_review(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-3",
            status=Episode.Status.NEEDS_REVIEW,
        )
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        content = response.content.decode()
        # title field should be an input (editable), not in readonly
        self.assertIn('name="title"', content)
