from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings
from pydantic_ai.models.test import TestModel

from episodes.agents.fetch_details import EpisodeDetails, get_agent
from episodes.fetch_details_step import clean_html, fetch_episode_details
from episodes.models import Episode


class CleanHtmlTests(TestCase):
    def test_strips_script_tags(self):
        html = "<html><body><script>alert('x')</script><p>Hello</p></body></html>"
        result = clean_html(html)
        self.assertNotIn("script", result)
        self.assertIn("Hello", result)

    def test_strips_style_tags(self):
        html = "<html><body><style>body{color:red}</style><p>Hello</p></body></html>"
        result = clean_html(html)
        self.assertNotIn("style", result)
        self.assertIn("Hello", result)

    def test_strips_nav_and_footer(self):
        html = "<html><body><nav>Menu</nav><p>Content</p><footer>Foot</footer></body></html>"
        result = clean_html(html)
        self.assertNotIn("Menu", result)
        self.assertNotIn("Foot", result)
        self.assertIn("Content", result)

    def test_preserves_meta_tags(self):
        html = '<html><head><meta property="og:title" content="Ep 1"></head><body></body></html>'
        result = clean_html(html)
        self.assertIn("og:title", result)

    def test_preserves_audio_tags(self):
        html = '<html><body><audio><source src="episode.mp3"></audio></body></html>'
        result = clean_html(html)
        self.assertIn("episode.mp3", result)

    def test_truncates_long_html(self):
        html = "<p>" + "x" * 40_000 + "</p>"
        result = clean_html(html)
        self.assertLessEqual(len(result), 30_000)


@override_settings(
    RAGTIME_FETCH_DETAILS_API_KEY="test-key",
    RAGTIME_FETCH_DETAILS_MODEL="openai:gpt-4.1-mini",
)
class FetchEpisodeDetailsTests(TestCase):
    """Tests for ``fetch_episode_details`` with the agent's model overridden.

    Uses ``Agent.override(model=TestModel())`` from Pydantic AI's testing
    utilities — ``TestModel`` returns a deterministic structured payload
    matching the agent's ``output_type`` schema, so we exercise the full
    code path (validators, step orchestrator, save logic) without an LLM.
    """

    SAMPLE_HTML = """
    <html>
    <head>
        <meta property="og:title" content="Jazz Episode 1">
    </head>
    <body>
        <h1>Jazz Episode 1</h1>
        <p>A great episode about jazz.</p>
        <audio><source src="https://example.com/ep1.mp3"></audio>
    </body>
    </html>
    """

    def setUp(self):
        # Reset memoized agent instance — settings change per test class
        # via override_settings, but get_agent caches the first one.
        get_agent.cache_clear()

    def _create_episode(self, **kwargs):
        """Create episode without triggering post_save signal."""
        with patch("episodes.signals.DBOS"):
            return Episode.objects.create(**kwargs)

    def _override_agent(self, output: EpisodeDetails | None = None):
        """Return an Agent.override() context manager that returns *output*.

        ``TestModel(custom_output_args=...)`` short-circuits the LLM call
        and feeds the structured payload straight to the validator, so
        the agent returns the desired ``EpisodeDetails`` instance.
        """
        if output is None:
            output = EpisodeDetails(
                title="Jazz Episode 1",
                description="A great episode about jazz.",
                published_at=date(2026, 1, 15),
                image_url="https://example.com/image.jpg",
                language="en",
                audio_url="https://example.com/ep1.mp3",
            )
        agent = get_agent()
        return agent.override(
            model=TestModel(custom_output_args=output.model_dump(mode="json"))
        )

    @patch("episodes.fetch_details_step.fetch_html")
    def test_success_path(self, mock_fetch):
        mock_fetch.return_value = self.SAMPLE_HTML

        episode = self._create_episode(url="https://example.com/ep/1")
        with self._override_agent():
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)
        self.assertEqual(episode.title, "Jazz Episode 1")
        self.assertEqual(episode.audio_url, "https://example.com/ep1.mp3")
        self.assertEqual(episode.language, "en")
        self.assertEqual(episode.published_at, date(2026, 1, 15))
        self.assertNotEqual(episode.scraped_html, "")

    @patch("episodes.fetch_details_step.fetch_html")
    def test_title_only_advances_to_downloading(self, mock_fetch):
        """audio_url is no longer required — download owns URL discovery."""
        mock_fetch.return_value = self.SAMPLE_HTML

        episode = self._create_episode(url="https://example.com/ep/2")
        title_only = EpisodeDetails(
            title="Jazz Episode 1",
            description="A great episode about jazz.",
            language="en",
            audio_url=None,
        )
        with self._override_agent(title_only):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)
        self.assertEqual(episode.title, "Jazz Episode 1")
        self.assertEqual(episode.audio_url, "")  # Was null in response

    @patch("episodes.fetch_details_step.fetch_html")
    def test_missing_title_fails(self, mock_fetch):
        """title is the only required field — extraction without it fails."""
        mock_fetch.return_value = self.SAMPLE_HTML

        episode = self._create_episode(url="https://example.com/ep/2-no-title")
        incomplete = EpisodeDetails(
            title=None,
            description="A great episode about jazz.",
            language="en",
            audio_url="https://example.com/ep1.mp3",
        )
        with self._override_agent(incomplete):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertEqual(episode.title, "")
        self.assertIn("Incomplete metadata", episode.error_message)

    @patch("episodes.fetch_details_step.fetch_html")
    def test_extracts_guid(self, mock_fetch):
        """The agent's guid output flows into Episode.guid."""
        mock_fetch.return_value = self.SAMPLE_HTML

        episode = self._create_episode(url="https://example.com/ep/guid")
        with_guid = EpisodeDetails(
            title="Jazz Episode 1",
            description="A great episode about jazz.",
            language="en",
            audio_url="https://example.com/ep1.mp3",
            guid="urn:example:episode:abc123",
        )
        with self._override_agent(with_guid):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.guid, "urn:example:episode:abc123")

    @patch("episodes.fetch_details_step.fetch_html")
    def test_http_error_sets_failed(self, mock_fetch):
        mock_fetch.side_effect = Exception("Connection refused")

        episode = self._create_episode(url="https://example.com/ep/3")
        fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)

    def test_reprocess_with_user_filled_fields(self):
        """When user fills required fields and reprocesses, agent is skipped."""
        episode = self._create_episode(
            url="https://example.com/ep/4",
            title="Filled by user",
            audio_url="https://example.com/audio.mp3",
            scraped_html="<html>cached</html>",
            status=Episode.Status.FAILED,
        )

        # Override to a model that would raise if called — fast-path skip
        # must short-circuit before reaching the agent.
        with patch("episodes.fetch_details_step._run_agent_sync") as mock_run:
            fetch_episode_details(episode.pk)
            mock_run.assert_not_called()

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)

    @patch("episodes.fetch_details_step.fetch_html")
    def test_uses_cached_html_on_reprocess(self, mock_fetch):
        """When scraped_html is already stored, HTTP fetch is skipped."""
        episode = self._create_episode(
            url="https://example.com/ep/5",
            scraped_html="<html>cached</html>",
            status=Episode.Status.FAILED,
        )

        with self._override_agent():
            fetch_episode_details(episode.pk)

        mock_fetch.assert_not_called()
        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)

    @patch("episodes.fetch_details_step.fetch_html")
    def test_incomplete_metadata_does_not_overwrite_recovery_status(self, mock_fetch):
        """When recovery changes status during fail_step, the step must not overwrite it.

        Regression test: the step used to call fail_step() before episode.save(),
        so synchronous recovery could set status=TRANSCRIBING, only for the step's
        subsequent save() to overwrite it back to FAILED.
        """
        mock_fetch.return_value = self.SAMPLE_HTML

        episode = self._create_episode(url="https://example.com/ep/recovery")

        from episodes.processing import create_run

        create_run(episode)

        def fake_recovery(sender, event, pipeline_event, **kwargs):
            ep = Episode.objects.get(pk=event.episode_id)
            ep.status = Episode.Status.TRANSCRIBING
            ep.error_message = ""
            ep.save(update_fields=["status", "error_message", "updated_at"])

        from episodes.signals import step_failed

        step_failed.connect(fake_recovery)
        try:
            # Title omitted: with the relaxed REQUIRED_FIELDS=("title",)
            # contract, this is the only way to force the incomplete path.
            incomplete = EpisodeDetails(
                title=None,
                description="A great episode about jazz.",
                language="en",
                audio_url="https://example.com/ep1.mp3",
            )
            with self._override_agent(incomplete):
                fetch_episode_details(episode.pk)
        finally:
            step_failed.disconnect(fake_recovery)

        episode.refresh_from_db()
        self.assertEqual(
            episode.status,
            Episode.Status.TRANSCRIBING,
            "fetch_details_step save() must not overwrite recovery status back to FAILED",
        )

    def test_nonexistent_episode(self):
        # Should not raise, just log error
        fetch_episode_details(99999)


class EpisodeDetailsValidatorTests(TestCase):
    """Pure-Pydantic tests — no Django ORM, no agent run."""

    def test_parses_iso_date(self):
        d = EpisodeDetails(published_at="2026-01-15")
        self.assertEqual(d.published_at, date(2026, 1, 15))

    def test_invalid_date_becomes_none(self):
        d = EpisodeDetails(published_at="January 15, 2026")
        self.assertIsNone(d.published_at)

    def test_empty_date_becomes_none(self):
        self.assertIsNone(EpisodeDetails(published_at="").published_at)
        self.assertIsNone(EpisodeDetails(published_at=None).published_at)

    def test_iso_639_language_kept(self):
        self.assertEqual(EpisodeDetails(language="en").language, "en")
        self.assertEqual(EpisodeDetails(language="sv").language, "sv")

    def test_invalid_language_becomes_none(self):
        self.assertIsNone(EpisodeDetails(language="english").language)
        self.assertIsNone(EpisodeDetails(language="EN").language)
        self.assertIsNone(EpisodeDetails(language="").language)
