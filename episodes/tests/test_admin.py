from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.models import Entity, EntityType, Episode


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
    def test_reprocess_action_shows_intermediate_page(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-2",
            status=Episode.Status.NEEDS_REVIEW,
        )
        mock_async.reset_mock()

        # First POST shows the intermediate page
        response = self.client.post(
            "/admin/episodes/episode/",
            {
                "action": "reprocess",
                "_selected_action": [episode.pk],
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Reprocess from step")
        self.assertContains(response, str(episode.pk))

    @patch("episodes.signals.async_task")
    def test_reprocess_action_executes(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-2b",
            status=Episode.Status.NEEDS_REVIEW,
        )
        mock_async.reset_mock()

        # Submit the intermediate page with from_step
        with patch("episodes.admin.async_task") as mock_admin_async:
            response = self.client.post(
                "/admin/episodes/episode/",
                {
                    "action": "reprocess",
                    "_selected_action": [episode.pk],
                    "episode_ids": [episode.pk],
                    "from_step": Episode.Status.SCRAPING,
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


class EntityTypeAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User

        cls.admin_user = User.objects.create_superuser(
            username="admin", password="testpass"
        )

    def setUp(self):
        self.client.login(username="admin", password="testpass")

    def test_add_form_has_wikidata_search(self):
        response = self.client.get("/admin/episodes/entitytype/add/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        self.assertIn("wikidata-search-input", content)
        self.assertIn("wikidata-search.js", content)

    def test_add_form_requires_wikidata_id(self):
        response = self.client.post("/admin/episodes/entitytype/add/", {
            "key": "test_type",
            "name": "Test Type",
            "wikidata_id": "",
            "description": "A test type.",
            "examples": "Example 1, Example 2",
            "is_active": "on",
            "entities-TOTAL_FORMS": "0",
            "entities-INITIAL_FORMS": "0",
            "entities-MIN_NUM_FORMS": "0",
            "entities-MAX_NUM_FORMS": "1000",
        })
        self.assertEqual(response.status_code, 200)
        # Should show validation error, not redirect
        content = response.content.decode()
        self.assertIn("Select an entity type from Wikidata", content)

    def test_add_form_succeeds_with_wikidata_id(self):
        response = self.client.post("/admin/episodes/entitytype/add/", {
            "key": "test_type",
            "name": "Test Type",
            "wikidata_id": "Q12345",
            "description": "A test type.",
            "examples": "Example 1, Example 2",
            "is_active": "on",
            "_save": "Save",
            # Inline management form data
            "entities-TOTAL_FORMS": "0",
            "entities-INITIAL_FORMS": "0",
            "entities-MIN_NUM_FORMS": "0",
            "entities-MAX_NUM_FORMS": "1000",
        })
        self.assertEqual(response.status_code, 302)
        et = EntityType.objects.get(key="test_type")
        self.assertEqual(et.wikidata_id, "Q12345")

    def test_edit_form_wikidata_id_readonly_with_link(self):
        et = EntityType.objects.create(
            key="readonly_test", name="Readonly Test",
            wikidata_id="Q99999", description="Test.",
        )
        response = self.client.get(f"/admin/episodes/entitytype/{et.pk}/change/")
        self.assertEqual(response.status_code, 200)
        content = response.content.decode()
        # wikidata_id should be displayed as a hyperlink, not an editable input
        self.assertNotIn('name="wikidata_id"', content)
        self.assertIn('https://www.wikidata.org/wiki/Q99999', content)
        self.assertIn('target="_blank"', content)

    def test_list_shows_wikidata_link(self):
        EntityType.objects.create(
            key="list_test", name="List Test",
            wikidata_id="Q11111", description="Test.",
        )
        response = self.client.get("/admin/episodes/entitytype/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.wikidata.org/wiki/Q11111")
        self.assertContains(response, 'target="_blank"')


class EntityAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User

        cls.admin_user = User.objects.create_superuser(
            username="admin", password="testpass"
        )

    def setUp(self):
        self.client.login(username="admin", password="testpass")

    @patch("episodes.signals.async_task")
    def test_list_shows_wikidata_link(self, _mock):
        et = EntityType.objects.create(
            key="ent_admin_list", name="Test Artist", wikidata_id="Q639669", description="Musician.",
        )
        Entity.objects.create(entity_type=et, name="Miles Davis", wikidata_id="Q93341")
        response = self.client.get("/admin/episodes/entity/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.wikidata.org/wiki/Q93341")
        self.assertContains(response, 'target="_blank"')

    @patch("episodes.signals.async_task")
    def test_detail_shows_wikidata_link(self, _mock):
        et = EntityType.objects.create(
            key="ent_admin_detail", name="Test Artist", wikidata_id="Q639669", description="Musician.",
        )
        entity = Entity.objects.create(entity_type=et, name="Miles Davis", wikidata_id="Q93341")
        response = self.client.get(f"/admin/episodes/entity/{entity.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.wikidata.org/wiki/Q93341")
        self.assertContains(response, 'target="_blank"')

    @patch("episodes.signals.async_task")
    def test_detail_no_wikidata_shows_dash(self, _mock):
        et = EntityType.objects.create(
            key="ent_admin_nodash", name="Test Artist", wikidata_id="Q639669", description="Musician.",
        )
        entity = Entity.objects.create(entity_type=et, name="Unknown Artist")
        response = self.client.get(f"/admin/episodes/entity/{entity.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "wikidata.org")


@override_settings(
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "wikidata": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
    RAGTIME_WIKIDATA_MIN_CHARS=3,
)
class WikidataViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User

        cls.admin_user = User.objects.create_superuser(
            username="admin", password="testpass"
        )

    def setUp(self):
        self.client.login(username="admin", password="testpass")

    def test_search_requires_min_chars(self):
        response = self.client.get("/episodes/wikidata/search/?q=ab")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["results"], [])

    @patch("episodes.views.search_entities")
    def test_search_returns_results(self, mock_search):
        mock_search.return_value = [
            {"qid": "Q639669", "label": "musician", "description": "person who plays music"},
        ]
        response = self.client.get("/episodes/wikidata/search/?q=musician")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["qid"], "Q639669")

    @patch("episodes.views.search_entities")
    def test_search_handles_api_error(self, mock_search):
        mock_search.side_effect = Exception("API down")
        response = self.client.get("/episodes/wikidata/search/?q=musician")
        self.assertEqual(response.status_code, 502)

    @patch("episodes.views.get_entity")
    def test_entity_detail(self, mock_get):
        mock_get.return_value = {
            "qid": "Q639669",
            "label": "musician",
            "description": "person who plays music",
            "aliases": ["music maker"],
        }
        response = self.client.get("/episodes/wikidata/entity/Q639669/")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["qid"], "Q639669")
        self.assertEqual(data["aliases"], ["music maker"])

    def test_search_requires_auth(self):
        self.client.logout()
        response = self.client.get("/episodes/wikidata/search/?q=musician")
        self.assertEqual(response.status_code, 302)  # redirect to login
