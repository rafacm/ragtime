from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from episodes.models import Entity, EntityType, Episode, PipelineEvent, ProcessingRun, ProcessingStep, RecoveryAttempt


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
                    "from_step": Episode.Status.SCRAPING,
                },
                follow=True,
            )
            self.assertEqual(response.status_code, 200)
            from episodes.workflows import process_episode

            mock_queue.enqueue.assert_called_once_with(
                process_episode, episode.pk, Episode.Status.SCRAPING
            )

        # Reprocess sets status to QUEUED — the workflow's create_run_step
        # transitions QUEUED -> from_step when a worker picks it up.
        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.QUEUED)

    @patch("episodes.signals.DBOS")
    def test_reprocess_skips_episode_with_active_run(self, mock_async):
        """Reprocessing an episode that already has a RUNNING ProcessingRun
        must skip it (not enqueue a duplicate workflow that would later
        fail the partial unique constraint)."""
        from episodes.models import ProcessingRun

        episode = Episode.objects.create(
            url="https://example.com/ep/admin-active",
            status=Episode.Status.SCRAPING,
            title="Active Episode",
        )
        # An in-flight run.
        ProcessingRun.objects.create(
            episode=episode, status=ProcessingRun.Status.RUNNING
        )

        with patch("episodes.workflows.episode_queue") as mock_queue:
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
        # Workflow was NOT enqueued.
        mock_queue.enqueue.assert_not_called()
        # Status was NOT overwritten — the in-flight run keeps its status.
        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SCRAPING)
        # The user sees a warning naming the skipped episode.
        self.assertContains(response, "Active Episode")

    @patch("episodes.signals.DBOS")
    def test_metadata_fields_readonly_when_failed(self, mock_async):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-3",
            status=Episode.Status.FAILED,
        )
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        content = response.content.decode()
        # title field should be readonly (no editable input)
        self.assertNotIn('name="title"', content)

    @patch("episodes.signals.DBOS")
    def test_metadata_fields_editable_when_awaiting_human(self, mock_async):
        from episodes.models import PipelineEvent, ProcessingRun, ProcessingStep, RecoveryAttempt

        episode = Episode.objects.create(
            url="https://example.com/ep/admin-4",
            status=Episode.Status.FAILED,
        )
        run = ProcessingRun.objects.create(episode=episode, status=ProcessingRun.Status.FAILED)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.FAILED
        )
        pe = PipelineEvent.objects.create(
            episode=episode, processing_step=step,
            event_type=PipelineEvent.EventType.FAILED, step_name="scraping",
        )
        RecoveryAttempt.objects.create(
            episode=episode, pipeline_event=pe,
            strategy="human", status=RecoveryAttempt.Status.AWAITING_HUMAN,
        )
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        content = response.content.decode()
        # title field should be editable when awaiting human
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


class RecoveryAttemptAdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth.models import User

        cls.admin_user = User.objects.create_superuser(
            username="admin", password="testpass"
        )

    def setUp(self):
        self.client.login(username="admin", password="testpass")

    def _make_awaiting_attempt(self, episode_url="https://example.com/rec/admin-1"):
        episode = Episode.objects.create(url=episode_url, status=Episode.Status.FAILED)
        run = ProcessingRun.objects.create(episode=episode, status=ProcessingRun.Status.FAILED)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.FAILED
        )
        pe = PipelineEvent.objects.create(
            episode=episode, processing_step=step,
            event_type=PipelineEvent.EventType.FAILED, step_name="scraping",
            error_type="http", error_message="403 Forbidden", http_status=403,
            exception_class="httpx.HTTPStatusError",
        )
        attempt = RecoveryAttempt.objects.create(
            episode=episode, pipeline_event=pe,
            strategy="human", status=RecoveryAttempt.Status.AWAITING_HUMAN,
        )
        return attempt

    @patch("episodes.signals.DBOS")
    @patch("episodes.admin.DBOS")
    def test_retry_queues_task_and_resolves_attempt(self, mock_admin_async, _):
        attempt = self._make_awaiting_attempt()

        response = self.client.post(
            "/admin/episodes/recoveryattempt/",
            {
                "action": "retry_agent_recovery",
                "_selected_action": [attempt.pk],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)

        attempt.refresh_from_db()
        self.assertEqual(attempt.status, RecoveryAttempt.Status.RESOLVED)
        self.assertEqual(attempt.resolved_by, "human:admin-retry")
        self.assertIsNotNone(attempt.resolved_at)

        from episodes.workflows import run_agent_recovery

        mock_admin_async.start_workflow.assert_called_once_with(
            run_agent_recovery,
            attempt.episode_id,
            attempt.pipeline_event_id,
        )

    @patch("episodes.signals.DBOS")
    @patch("episodes.admin.DBOS")
    def test_retry_skips_non_awaiting_attempts(self, mock_admin_async, _):
        attempt = self._make_awaiting_attempt(
            episode_url="https://example.com/rec/admin-2"
        )
        attempt.status = RecoveryAttempt.Status.ATTEMPTED
        attempt.save(update_fields=["status"])

        response = self.client.post(
            "/admin/episodes/recoveryattempt/",
            {
                "action": "retry_agent_recovery",
                "_selected_action": [attempt.pk],
            },
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        mock_admin_async.start_workflow.assert_not_called()


class RunAgentRecoveryTaskTests(TestCase):
    @patch("episodes.signals.DBOS")
    @patch("episodes.agents.run_recovery_agent")
    def test_success_creates_resolved_attempt_and_resumes(self, mock_agent, _):
        from episodes.agents.deps import RecoveryAgentResult
        from episodes.workflows import execute_agent_recovery

        mock_agent.return_value = RecoveryAgentResult(
            success=True,
            audio_url="https://cdn.example.com/found.mp3",
            message="Found audio via browser",
        )

        episode = Episode.objects.create(
            url="https://example.com/task/1", status=Episode.Status.FAILED
        )
        run = ProcessingRun.objects.create(episode=episode, status=ProcessingRun.Status.FAILED)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.FAILED
        )
        pe = PipelineEvent.objects.create(
            episode=episode, processing_step=step,
            event_type=PipelineEvent.EventType.FAILED, step_name="scraping",
            error_type="http", error_message="403 Forbidden",
        )

        with patch("episodes.agents.resume.resume_pipeline") as mock_resume:
            execute_agent_recovery(episode.pk, pe.pk)

        mock_resume.assert_called_once()
        new_attempt = RecoveryAttempt.objects.filter(
            episode=episode, strategy="agent"
        ).first()
        self.assertIsNotNone(new_attempt)
        self.assertTrue(new_attempt.success)

    @patch("episodes.signals.DBOS")
    @patch("episodes.agents.run_recovery_agent")
    def test_failure_creates_awaiting_human_attempt(self, mock_agent, _):
        from episodes.agents.deps import RecoveryAgentResult
        from episodes.workflows import execute_agent_recovery

        mock_agent.return_value = RecoveryAgentResult(
            success=False,
            message="Could not find audio",
        )

        episode = Episode.objects.create(
            url="https://example.com/task/2", status=Episode.Status.FAILED
        )
        run = ProcessingRun.objects.create(episode=episode, status=ProcessingRun.Status.FAILED)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.FAILED
        )
        pe = PipelineEvent.objects.create(
            episode=episode, processing_step=step,
            event_type=PipelineEvent.EventType.FAILED, step_name="scraping",
            error_type="http", error_message="403 Forbidden",
        )

        execute_agent_recovery(episode.pk, pe.pk)

        new_attempt = RecoveryAttempt.objects.filter(
            episode=episode, strategy="agent"
        ).first()
        self.assertIsNotNone(new_attempt)
        self.assertFalse(new_attempt.success)
        self.assertEqual(new_attempt.status, RecoveryAttempt.Status.AWAITING_HUMAN)

    @patch("episodes.signals.DBOS")
    @patch("episodes.agents.run_recovery_agent", side_effect=RuntimeError("Crash"))
    def test_exception_creates_awaiting_human_attempt(self, _, __):
        from episodes.workflows import execute_agent_recovery

        episode = Episode.objects.create(
            url="https://example.com/task/3", status=Episode.Status.FAILED
        )
        run = ProcessingRun.objects.create(episode=episode, status=ProcessingRun.Status.FAILED)
        step = ProcessingStep.objects.create(
            run=run, step_name="scraping", status=ProcessingStep.Status.FAILED
        )
        pe = PipelineEvent.objects.create(
            episode=episode, processing_step=step,
            event_type=PipelineEvent.EventType.FAILED, step_name="scraping",
            error_type="http", error_message="403 Forbidden",
        )

        execute_agent_recovery(episode.pk, pe.pk)

        new_attempt = RecoveryAttempt.objects.filter(
            episode=episode, strategy="agent"
        ).first()
        self.assertIsNotNone(new_attempt)
        self.assertFalse(new_attempt.success)
        self.assertIn("Agent error", new_attempt.message)


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
