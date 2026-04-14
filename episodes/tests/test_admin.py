import importlib.util
import unittest
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from django.utils import timezone

from episodes.models import Entity, EntityType, Episode, PipelineEvent, ProcessingRun, ProcessingStep, RecoveryAttempt

_has_recovery_deps = (
    importlib.util.find_spec("pydantic_ai") is not None
    and importlib.util.find_spec("playwright") is not None
)


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

    def test_detail_page_loads(self):
        episode = Episode.objects.create(url="https://example.com/ep/admin-1")
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        self.assertEqual(response.status_code, 200)

    @patch("episodes.admin.threading")
    def test_create_episode_auto_starts_pipeline(self, mock_threading):
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                "/admin/episodes/episode/add/",
                {"url": "https://example.com/ep/auto-ingest"},
                follow=True,
            )
        self.assertEqual(response.status_code, 200)
        episode = Episode.objects.get(url="https://example.com/ep/auto-ingest")
        self.assertEqual(episode.status, Episode.Status.PENDING)
        # on_commit callback starts the pipeline thread
        mock_threading.Thread.assert_called_once()
        call_kwargs = mock_threading.Thread.call_args
        self.assertEqual(call_kwargs.kwargs.get("target").__name__, "_run_pipeline_task")
        self.assertEqual(call_kwargs.kwargs.get("args"), (episode.pk,))
        mock_threading.Thread.return_value.start.assert_called_once()

    def test_reprocess_action_shows_intermediate_page(self):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-2",
            status=Episode.Status.FAILED,
        )

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

    @patch("episodes.admin.threading")
    def test_reprocess_action_executes(self, mock_threading):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-2b",
            status=Episode.Status.FAILED,
        )

        # Submit the intermediate page with from_step
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
        mock_threading.Thread.assert_called_once()
        mock_threading.Thread.return_value.start.assert_called_once()

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.SCRAPING)

    def test_metadata_fields_readonly_when_failed(self):
        episode = Episode.objects.create(
            url="https://example.com/ep/admin-3",
            status=Episode.Status.FAILED,
        )
        response = self.client.get(f"/admin/episodes/episode/{episode.pk}/change/")
        content = response.content.decode()
        # title field should be readonly (no editable input)
        self.assertNotIn('name="title"', content)

    def test_metadata_fields_editable_when_awaiting_human(self):
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

    def test_list_shows_wikidata_link(self):
        et = EntityType.objects.create(
            key="ent_admin_list", name="Test Artist", wikidata_id="Q639669", description="Musician.",
        )
        Entity.objects.create(entity_type=et, name="Miles Davis", wikidata_id="Q93341")
        response = self.client.get("/admin/episodes/entity/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.wikidata.org/wiki/Q93341")
        self.assertContains(response, 'target="_blank"')

    def test_detail_shows_wikidata_link(self):
        et = EntityType.objects.create(
            key="ent_admin_detail", name="Test Artist", wikidata_id="Q639669", description="Musician.",
        )
        entity = Entity.objects.create(entity_type=et, name="Miles Davis", wikidata_id="Q93341")
        response = self.client.get(f"/admin/episodes/entity/{entity.pk}/change/")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "https://www.wikidata.org/wiki/Q93341")
        self.assertContains(response, 'target="_blank"')

    def test_detail_no_wikidata_shows_dash(self):
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

    @patch("episodes.admin.threading")
    def test_retry_queues_task_and_resolves_attempt(self, mock_threading):
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

        mock_threading.Thread.assert_called_once()
        mock_threading.Thread.return_value.start.assert_called_once()

    @patch("episodes.admin.threading")
    def test_retry_skips_non_awaiting_attempts(self, mock_threading):
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
        mock_threading.Thread.assert_not_called()


@unittest.skipUnless(_has_recovery_deps, "pydantic-ai not installed")
class RunAgentRecoveryTaskTests(TestCase):
    @patch("episodes.agents.run_recovery_agent")
    def test_success_creates_resolved_attempt_and_resumes(self, mock_agent):
        from episodes.admin import _run_agent_recovery_task
        from episodes.agents.deps import RecoveryAgentResult

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
            _run_agent_recovery_task(episode.pk, pe.pk)

        mock_resume.assert_called_once()
        new_attempt = RecoveryAttempt.objects.filter(
            episode=episode, strategy="agent"
        ).first()
        self.assertIsNotNone(new_attempt)
        self.assertTrue(new_attempt.success)

    @patch("episodes.agents.run_recovery_agent")
    def test_failure_creates_awaiting_human_attempt(self, mock_agent):
        from episodes.admin import _run_agent_recovery_task
        from episodes.agents.deps import RecoveryAgentResult

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

        _run_agent_recovery_task(episode.pk, pe.pk)

        new_attempt = RecoveryAttempt.objects.filter(
            episode=episode, strategy="agent"
        ).first()
        self.assertIsNotNone(new_attempt)
        self.assertFalse(new_attempt.success)
        self.assertEqual(new_attempt.status, RecoveryAttempt.Status.AWAITING_HUMAN)

    @patch("episodes.agents.run_recovery_agent", side_effect=RuntimeError("Crash"))
    def test_exception_creates_awaiting_human_attempt(self, _):
        from episodes.admin import _run_agent_recovery_task

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

        _run_agent_recovery_task(episode.pk, pe.pk)

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
