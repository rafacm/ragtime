from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

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

    @patch("episodes.signals.DBOS")
    def test_detail_page_loads(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/admin-1")
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "View workflow steps")

    @patch("episodes.signals.DBOS")
    def test_dbos_steps_view_renders_when_dbos_unavailable(self, mock_async):
        """The DBOS-backed steps view must render even when DBOS is offline."""
        episode = Episode.objects.create(url="https://example.com/ep/admin-dbos-1")
        with patch("episodes.admin._dbos_workflow_steps", return_value=[]):
            response = self.client.get(
                f"/admin/episodes/episode/{episode.pk}/dbos-steps/"
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DBOS workflow steps")
        self.assertContains(response, "No DBOS workflow records")

    @patch("episodes.signals.DBOS")
    def test_dbos_steps_view_renders_step_rows(self, mock_async):
        episode = Episode.objects.create(url="https://example.com/ep/admin-dbos-2")
        steps = [
            {"function_name": "fetch_details_step_", "step_id": 1, "output": {"step_name": "fetching_details"}, "error": None},
            {"function_name": "download_step", "step_id": 2, "output": None, "error": "DownloadFailed: …"},
        ]
        with patch("episodes.admin._dbos_workflow_steps", return_value=steps):
            response = self.client.get(
                f"/admin/episodes/episode/{episode.pk}/dbos-steps/"
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "fetch_details_step_")
        self.assertContains(response, "download_step")
        self.assertContains(response, "DownloadFailed")

    def test_decode_dbos_payload_unpickles_step_output(self):
        """Pickled+b64-encoded payloads (DBOS wire format) are rendered as str()."""
        import base64
        import pickle

        from episodes.admin import _decode_dbos_payload
        from episodes.workflows import DownloadStepFailed, StepOutput

        out = StepOutput(episode_id=2, step_name="fetching_details")
        encoded = base64.b64encode(pickle.dumps(out)).decode("ascii")
        self.assertEqual(_decode_dbos_payload(encoded), str(out))

        # And for errors.
        err = DownloadStepFailed(episode_id=2, error_message="boom")
        encoded = base64.b64encode(pickle.dumps(err)).decode("ascii")
        decoded = _decode_dbos_payload(encoded)
        self.assertIn("downloading failed for episode 2", decoded)
        self.assertIn("boom", decoded)

    def test_decode_dbos_payload_passthrough_for_plain_values(self):
        from episodes.admin import _decode_dbos_payload

        self.assertIsNone(_decode_dbos_payload(None))
        self.assertEqual(_decode_dbos_payload(""), "")
        # Already-readable string — left alone.
        self.assertEqual(_decode_dbos_payload("hello"), "hello")
        # Looks pickle-ish but not valid b64/pickle — fall back to raw.
        self.assertEqual(_decode_dbos_payload("gASnotpickle"), "gASnotpickle")

    @patch("episodes.signals.DBOS")
    @patch("dbos.DBOS")
    def test_dbos_workflow_steps_handles_dict_records(self, mock_dbos, _signals):
        """``DBOS.list_workflows`` / ``list_workflow_steps`` return TypedDicts.

        Regression: an earlier version used ``getattr(record, ...)`` which
        silently returned the default for dicts, so the prefix filter never
        matched and the helper returned [] even when the workflow existed.
        """
        from episodes.admin import _dbos_workflow_steps

        episode = Episode.objects.create(url="https://example.com/ep/admin-dbos-3")

        mock_dbos.list_workflows.return_value = [
            {
                "workflow_id": f"episode-{episode.pk}-run-1",
                "created_at": 1_700_000_000_000,
                "status": "ERROR",
            },
            {  # Older deterministic-ID run for the same episode — shouldn't be picked.
                "workflow_id": f"episode-{episode.pk}-run-0",
                "created_at": 1_600_000_000_000,
                "status": "SUCCESS",
            },
            {  # Different episode — must be filtered out.
                "workflow_id": "episode-999-run-1",
                "created_at": 1_800_000_000_000,
                "status": "SUCCESS",
            },
        ]
        mock_dbos.list_workflow_steps.return_value = [
            {
                "function_id": 1,
                "function_name": "_bootstrap_status",
                "output": "ok",
                "error": None,
            },
            {
                "function_id": 2,
                "function_name": "download_step",
                "output": None,
                "error": "DownloadStepFailed: …",
            },
        ]

        rows = _dbos_workflow_steps(episode.pk)

        # Most-recent matching workflow chosen, steps unwrapped from dicts.
        mock_dbos.list_workflow_steps.assert_called_once_with(
            f"episode-{episode.pk}-run-1"
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["function_name"], "_bootstrap_status")
        self.assertEqual(rows[0]["step_id"], 1)
        self.assertEqual(rows[1]["function_name"], "download_step")
        self.assertIn("DownloadStepFailed", rows[1]["error"])

    @patch("episodes.signals.DBOS")
    def test_reprocess_action_shows_intermediate_page(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-2",
            status=Episode.Status.FAILED,
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

    @patch("episodes.signals.DBOS")
    def test_reprocess_action_executes(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-2b",
            status=Episode.Status.FAILED,
        )
        mock_async.reset_mock()

        # Submit the intermediate page with from_step
        with patch("episodes.workflows.episode_queue") as mock_queue:
            response = self.client.post(
                "/admin/episodes/episode/",
                {
                    "action": "reprocess",
                    "_selected_action": [episode.pk],
                    "episode_ids": [episode.pk],
                    "from_step": Episode.Status.FETCHING_DETAILS,
                },
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            from episodes.workflows import process_episode

            mock_queue.enqueue.assert_called_once_with(
                process_episode, episode.pk, Episode.Status.FETCHING_DETAILS
            )

        # Reprocess sets status to QUEUED — the workflow's create_run_step
        # transitions QUEUED -> from_step when a worker picks it up.
        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.QUEUED)

    @patch("episodes.signals.DBOS")
    def test_metadata_fields_editable_when_failed(self, mock_async):
        """When an episode is FAILED, the admin can edit metadata to fix and reprocess."""
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-3",
            status=Episode.Status.FAILED,
        )
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        content = response.content.decode()
        # title field should be editable when failed
        self.assertIn('name="title"', content)

    @patch("episodes.signals.DBOS")
    def test_metadata_fields_readonly_when_running(self, mock_async):
        """While an episode is mid-pipeline, metadata is read-only."""
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-4",
            status=Episode.Status.TRANSCRIBING,
        )
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        content = response.content.decode()
        # title field should be readonly mid-pipeline
        self.assertNotIn('name="title"', content)


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

    @patch("episodes.signals.DBOS")
    def test_list_shows_wikidata_link(self, _mock):
        et = EntityType.objects.create(
            key="ent_admin_list", name="Test Artist", wikidata_id="Q639669", description="Musician.",
        )
        Entity.objects.create(entity_type=et, name="Miles Davis", wikidata_id="Q93341")
        response = self.client.get("/admin/episodes/entity/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.wikidata.org/wiki/Q93341")
        self.assertContains(response, 'target="_blank"')

    @patch("episodes.signals.DBOS")
    def test_detail_shows_wikidata_link(self, _mock):
        et = EntityType.objects.create(
            key="ent_admin_detail", name="Test Artist", wikidata_id="Q639669", description="Musician.",
        )
        entity = Entity.objects.create(entity_type=et, name="Miles Davis", wikidata_id="Q93341")
        response = self.client.get(f"/admin/episodes/entity/{entity.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.wikidata.org/wiki/Q93341")
        self.assertContains(response, 'target="_blank"')

    @patch("episodes.signals.DBOS")
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
