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
        self.assertContains(response, "View workflow runs")

    @patch("episodes.signals.DBOS")
    def test_dbos_steps_view_renders_when_dbos_unavailable(self, mock_async):
        """The DBOS-backed steps view must render even when DBOS is offline."""
        episode = Episode.objects.create(url="https://example.com/ep/admin-dbos-1")
        with patch("episodes.admin._dbos_workflow_runs", return_value=[]):
            response = self.client.get(
                f"/admin/episodes/episode/{episode.pk}/dbos-steps/"
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "DBOS workflow runs")
        self.assertContains(response, "No DBOS workflow records")

    @patch("episodes.signals.DBOS")
    def test_dbos_steps_view_renders_runs_with_their_steps(self, mock_async):
        """Each ``episode-<id>-run-<n>`` workflow renders as its own section."""
        episode = Episode.objects.create(url="https://example.com/ep/admin-dbos-2")
        runs = [
            {
                "workflow_id": f"episode-{episode.pk}-run-2",
                "status": "ERROR",
                "name": "process_episode",
                "queue_name": "episode_pipeline",
                "recovery_attempts": 1,
                "created_at": None,
                "updated_at": None,
                "steps": [
                    {
                        "function_name": "fetch_details_step_",
                        "step_id": 1,
                        "output": "StepOutput(step_name='fetching_details')",
                        "error": None,
                        "started_at": None,
                        "completed_at": None,
                    },
                    {
                        "function_name": "download_step",
                        "step_id": 2,
                        "output": None,
                        "error": "DownloadStepFailed: boom",
                        "started_at": None,
                        "completed_at": None,
                    },
                ],
            },
            {
                "workflow_id": f"episode-{episode.pk}-run-1",
                "status": "SUCCESS",
                "name": "process_episode",
                "queue_name": "episode_pipeline",
                "recovery_attempts": 0,
                "created_at": None,
                "updated_at": None,
                "steps": [],
            },
        ]
        with patch("episodes.admin._dbos_workflow_runs", return_value=runs):
            response = self.client.get(
                f"/admin/episodes/episode/{episode.pk}/dbos-steps/"
            )
        self.assertEqual(response.status_code, 200)
        # Both runs surfaced.
        self.assertContains(response, f"episode-{episode.pk}-run-1")
        self.assertContains(response, f"episode-{episode.pk}-run-2")
        # Status pills present.
        self.assertContains(response, "ERROR")
        self.assertContains(response, "SUCCESS")
        # Steps under run-2 rendered.
        self.assertContains(response, "fetch_details_step_")
        self.assertContains(response, "download_step")
        self.assertContains(response, "DownloadStepFailed")
        # Pluralisation in the header.
        self.assertContains(response, "2 runs recorded")

    def test_decode_dbos_payload_unpickles_step_output(self):
        """Pickled+b64-encoded payloads (DBOS wire format) are rendered as str()."""
        import base64
        import pickle

        from episodes.admin import _decode_dbos_payload
        from episodes.workflows import DownloadStepFailed, StepOutput

        out = StepOutput(episode_id=2, step_name="fetching_details")
        encoded = base64.b64encode(pickle.dumps(out)).decode("ascii")
        self.assertEqual(_decode_dbos_payload(encoded), str(out))

        # Errors pickle as plain ``RuntimeError`` (see
        # ``StepFailed.__reduce__``) carrying the formatted message —
        # so the CLI / Conductor can deserialize them without
        # importing ``episodes.workflows``. The string content is the
        # same as ``str(StepFailed(...))``.
        err = DownloadStepFailed(episode_id=2, error_message="boom")
        encoded = base64.b64encode(pickle.dumps(err)).decode("ascii")
        decoded = _decode_dbos_payload(encoded)
        self.assertIn("downloading failed for episode 2", decoded)
        self.assertIn("boom", decoded)

    def test_step_failed_pickle_round_trip_yields_runtime_error(self):
        """``StepFailed.__reduce__`` collapses to ``RuntimeError`` on the wire.

        Required for cross-process portability: the standalone ``dbos
        workflow steps`` CLI runs outside Django and can't import
        ``episodes.workflows``. Pickling as a stdlib ``RuntimeError``
        means any Python process can deserialize the step error.
        """
        import pickle

        from episodes.workflows import DownloadStepFailed, StepFailed

        err = DownloadStepFailed(episode_id=7, error_message="boom")
        # In-process raise still matches the typed hierarchy.
        self.assertIsInstance(err, StepFailed)

        rehydrated = pickle.loads(pickle.dumps(err))
        # On the wire it's a plain ``RuntimeError`` — portable across
        # processes that don't import ``episodes.workflows``.
        self.assertIs(type(rehydrated), RuntimeError)
        self.assertIn("downloading failed for episode 7", str(rehydrated))
        self.assertIn("boom", str(rehydrated))

    def test_decode_dbos_payload_passthrough_for_plain_values(self):
        from episodes.admin import _decode_dbos_payload

        self.assertIsNone(_decode_dbos_payload(None))
        self.assertEqual(_decode_dbos_payload(""), "")
        # Already-readable string — left alone.
        self.assertEqual(_decode_dbos_payload("hello"), "hello")
        # Looks pickle-ish but not valid b64/pickle — graceful
        # fallback for legacy rows whose typed-class wire format the
        # current process can no longer rehydrate.
        decoded = _decode_dbos_payload("gASnotpickle")
        self.assertIn("could not deserialize", decoded)
        self.assertIn("gASnotpickle", decoded)

    @patch("episodes.signals.DBOS")
    @patch("dbos.DBOS")
    def test_dbos_workflow_runs_returns_every_run_for_episode(
        self, mock_dbos, _signals
    ):
        """``_dbos_workflow_runs`` lists every ``episode-<id>-run-<n>`` workflow.

        Regression coverage:
        * dict records (TypedDicts) work via _dbos_field — earlier
          versions used ``getattr`` which silently returned the default;
        * other-episode workflows are filtered out;
        * the result is sorted newest-first;
        * each run carries its own ``steps`` list (not just the latest).
        """
        from episodes.admin import _dbos_workflow_runs

        episode = Episode.objects.create(url="https://example.com/ep/admin-dbos-3")

        mock_dbos.list_workflows.return_value = [
            {
                "workflow_id": f"episode-{episode.pk}-run-2",
                "created_at": 1_700_000_000_000,
                "status": "ERROR",
                "name": "process_episode",
                "queue_name": "episode_pipeline",
                "recovery_attempts": 0,
                "updated_at": 1_700_000_001_000,
            },
            {
                "workflow_id": f"episode-{episode.pk}-run-1",
                "created_at": 1_600_000_000_000,
                "status": "SUCCESS",
                "name": "process_episode",
                "queue_name": "episode_pipeline",
                "recovery_attempts": 0,
                "updated_at": 1_600_000_001_000,
            },
            {  # Different episode — must be filtered out.
                "workflow_id": "episode-999-run-1",
                "created_at": 1_800_000_000_000,
                "status": "SUCCESS",
                "name": "process_episode",
                "queue_name": "episode_pipeline",
                "recovery_attempts": 0,
                "updated_at": 1_800_000_001_000,
            },
        ]
        # Per-workflow step lookup — return a different list per workflow_id.
        def _steps(workflow_id):
            if workflow_id.endswith("-run-2"):
                return [
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
            if workflow_id.endswith("-run-1"):
                return [
                    {
                        "function_id": 1,
                        "function_name": "_bootstrap_status",
                        "output": "ok",
                        "error": None,
                    },
                ]
            return []

        mock_dbos.list_workflow_steps.side_effect = _steps

        runs = _dbos_workflow_runs(episode.pk)

        # Two runs for this episode; the run-999 workflow filtered out.
        self.assertEqual(len(runs), 2)
        # Newest-first ordering.
        self.assertEqual(runs[0]["workflow_id"], f"episode-{episode.pk}-run-2")
        self.assertEqual(runs[1]["workflow_id"], f"episode-{episode.pk}-run-1")
        # Per-run step lookup.
        self.assertEqual(len(runs[0]["steps"]), 2)
        self.assertEqual(runs[0]["steps"][1]["function_name"], "download_step")
        self.assertEqual(len(runs[1]["steps"]), 1)
        self.assertEqual(runs[1]["status"], "SUCCESS")

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
