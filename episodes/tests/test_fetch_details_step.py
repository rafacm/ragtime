"""Tests for the ``fetch_details_step`` orchestrator.

The orchestrator persists a ``FetchDetailsRun`` per execution, applies
the agent's authoritative output to the Episode row, and maps the
agent's ``concise.outcome`` onto pipeline status. We exercise each of
the five outcome paths plus the agent-crash path.
"""

from datetime import date
from unittest.mock import patch

from django.test import TestCase, override_settings

from episodes.agents.fetch_details import (
    ConciseMessage,
    EpisodeDetails,
    FetchDetailsOutput,
    FetchDetailsReport,
    get_agent,
)
from episodes.agents.fetch_details_deps import FetchDetailsDeps
from episodes.fetch_details_step import fetch_episode_details
from episodes.models import Episode, FetchDetailsRun


def _output(
    *,
    outcome: str = "ok",
    summary: str = "Canonical page extracted cleanly.",
    title: str | None = "Jazz Episode 1",
    audio_url: str | None = "https://example.com/ep1.mp3",
    audio_format: str | None = "mp3",
    canonical_url: str | None = "https://example.com/ep/1",
    source_kind: str = "canonical",
    aggregator_provider: str | None = None,
    language: str | None = "en",
    country: str | None = "us",
    published_at: date | None = date(2026, 1, 15),
    confidence: str = "high",
    cross_linked: bool = False,
) -> FetchDetailsOutput:
    """Build a deterministic ``FetchDetailsOutput`` for a target outcome."""
    return FetchDetailsOutput(
        details=EpisodeDetails(
            title=title,
            description="A great episode about jazz.",
            published_at=published_at,
            image_url="https://example.com/image.jpg",
            audio_url=audio_url,
            audio_format=audio_format,
            language=language,
            country=country,
            guid="urn:example:abc",
            canonical_url=canonical_url,
            source_kind=source_kind,
            aggregator_provider=aggregator_provider,
        ),
        report=FetchDetailsReport(
            attempted_sources=[],
            discovered_canonical_url=bool(canonical_url),
            discovered_audio_url=bool(audio_url),
            cross_linked=cross_linked,
            extraction_confidence=confidence,
            narrative="…",
            hints_for_next_step="",
        ),
        concise=ConciseMessage(outcome=outcome, summary=summary),
    )


@override_settings(
    RAGTIME_FETCH_DETAILS_API_KEY="test-key",
    RAGTIME_FETCH_DETAILS_MODEL="openai:gpt-4.1-mini",
)
class FetchEpisodeDetailsTests(TestCase):
    def setUp(self):
        get_agent.cache_clear()

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.DBOS"):
            return Episode.objects.create(**kwargs)

    def _patch_run(self, output: FetchDetailsOutput, *, tool_calls=None, usage=None):
        """Patch the agent runner to return *output* without invoking an LLM."""
        deps = FetchDetailsDeps(submitted_url="")
        if tool_calls:
            deps.tool_calls.extend(tool_calls)

        async def _fake_run(submitted_url):
            deps.submitted_url = submitted_url
            return output, deps, usage

        return patch("episodes.fetch_details_step.fetch_details_agent.run", _fake_run)

    def test_ok_outcome_advances_to_downloading(self):
        episode = self._create_episode(url="https://example.com/ep/1")
        with self._patch_run(_output()):
            fetch_episode_details(episode.pk, dbos_workflow_id="wf-1")

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)
        self.assertEqual(episode.title, "Jazz Episode 1")
        self.assertEqual(episode.audio_url, "https://example.com/ep1.mp3")
        self.assertEqual(episode.audio_format, "mp3")
        self.assertEqual(episode.country, "us")
        self.assertEqual(episode.canonical_url, "https://example.com/ep/1")
        self.assertEqual(episode.source_kind, Episode.SourceKind.CANONICAL)
        self.assertEqual(episode.error_message, "")

        run = episode.fetch_details_runs.get()
        self.assertEqual(run.run_index, 1)
        self.assertEqual(run.outcome, FetchDetailsRun.Outcome.OK)
        self.assertEqual(run.dbos_workflow_id, "wf-1")
        self.assertEqual(run.model, "openai:gpt-4.1-mini")
        self.assertIsNotNone(run.output_json)
        self.assertIn("details", run.output_json)

    def test_partial_outcome_advances_to_downloading(self):
        episode = self._create_episode(url="https://example.com/ep/2")
        out = _output(
            outcome="partial",
            summary="Title found but audio is hidden.",
            audio_url=None,
            audio_format=None,
            confidence="medium",
        )
        with self._patch_run(out):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)
        self.assertEqual(episode.audio_url, "")
        run = episode.fetch_details_runs.get()
        self.assertEqual(run.outcome, FetchDetailsRun.Outcome.PARTIAL)

    def test_not_a_podcast_episode_fails(self):
        episode = self._create_episode(url="https://example.com/home")
        out = _output(
            outcome="not_a_podcast_episode",
            summary="Page is the show's homepage.",
            title=None, audio_url=None, audio_format=None,
            canonical_url=None, source_kind="unknown",
        )
        with self._patch_run(out):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("homepage", episode.error_message)
        run = episode.fetch_details_runs.get()
        self.assertEqual(
            run.outcome, FetchDetailsRun.Outcome.NOT_A_PODCAST_EPISODE,
        )

    def test_unreachable_fails(self):
        episode = self._create_episode(url="https://example.com/down")
        out = _output(
            outcome="unreachable",
            summary="503 from the host.",
            title=None, audio_url=None, audio_format=None,
            canonical_url=None, source_kind="unknown",
        )
        with self._patch_run(out):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        run = episode.fetch_details_runs.get()
        self.assertEqual(run.outcome, FetchDetailsRun.Outcome.UNREACHABLE)

    def test_extraction_failed_fails(self):
        episode = self._create_episode(url="https://example.com/dyn")
        out = _output(
            outcome="extraction_failed",
            summary="Title buried in dynamic markup.",
            title=None, audio_url=None, audio_format=None,
            canonical_url=None, source_kind="unknown",
        )
        with self._patch_run(out):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        run = episode.fetch_details_runs.get()
        self.assertEqual(run.outcome, FetchDetailsRun.Outcome.EXTRACTION_FAILED)

    def test_agent_crash_records_run_with_error(self):
        episode = self._create_episode(url="https://example.com/boom")

        async def _boom(_url):
            raise RuntimeError("kaboom")

        with patch("episodes.fetch_details_step.fetch_details_agent.run", _boom):
            fetch_episode_details(episode.pk, dbos_workflow_id="wf-crash")

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("kaboom", episode.error_message)

        run = episode.fetch_details_runs.get()
        self.assertEqual(run.outcome, "")
        self.assertIn("kaboom", run.error_message)
        self.assertEqual(run.dbos_workflow_id, "wf-crash")

    def test_run_index_increments_on_re_run(self):
        episode = self._create_episode(url="https://example.com/ep/repeat")
        with self._patch_run(_output()):
            fetch_episode_details(episode.pk)
            fetch_episode_details(episode.pk)

        indexes = list(
            episode.fetch_details_runs.order_by("run_index")
            .values_list("run_index", flat=True)
        )
        self.assertEqual(indexes, [1, 2])

    def test_authoritative_overwrite(self):
        """Agent output overwrites previously-stored Episode fields."""
        episode = self._create_episode(
            url="https://example.com/ep/overwrite",
            title="Stale title",
            audio_url="https://stale.example/old.mp3",
        )
        with self._patch_run(_output()):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.title, "Jazz Episode 1")
        self.assertEqual(episode.audio_url, "https://example.com/ep1.mp3")

    def test_partial_rerun_clears_audio_url_when_agent_returns_none(self):
        """A later ``partial`` run with audio_url=None must clear the prior URL.

        Otherwise the Download step receives a stale audio_url and
        downloads the wrong file.
        """
        episode = self._create_episode(url="https://example.com/ep/partial-clear")

        # Run 1 — full ok with an audio URL.
        with self._patch_run(_output()):
            fetch_episode_details(episode.pk)
        episode.refresh_from_db()
        self.assertEqual(episode.audio_url, "https://example.com/ep1.mp3")

        # Run 2 — partial, agent could not find an audio URL.
        partial = _output(
            outcome="partial",
            summary="Audio URL hidden behind JS.",
            audio_url=None,
            audio_format=None,
            confidence="medium",
        )
        with self._patch_run(partial):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.audio_url, "")
        self.assertEqual(episode.audio_format, "")
        # Status still advances on partial — the Download step decides.
        self.assertEqual(episode.status, Episode.Status.DOWNLOADING)

    def test_rerun_clears_published_at_when_agent_returns_none(self):
        """A later run with published_at=None must clear the prior date."""
        episode = self._create_episode(
            url="https://example.com/ep/date-clear",
            published_at=date(2025, 12, 1),
        )
        out = _output(published_at=None)
        with self._patch_run(out):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertIsNone(episode.published_at)

    def test_rerun_clears_aggregator_metadata(self):
        """source_kind / aggregator_provider follow the agent's latest call."""
        episode = self._create_episode(
            url="https://example.com/ep/source-flip",
            source_kind=Episode.SourceKind.AGGREGATOR,
            aggregator_provider="apple_podcasts",
            canonical_url="https://canonical.example/ep",
        )
        out = _output(
            source_kind="canonical",
            canonical_url=None,
            aggregator_provider=None,
        )
        with self._patch_run(out):
            fetch_episode_details(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.source_kind, Episode.SourceKind.CANONICAL)
        self.assertEqual(episode.aggregator_provider, "")
        self.assertEqual(episode.canonical_url, "")

    def test_tool_calls_persisted(self):
        episode = self._create_episode(url="https://example.com/ep/tools")
        traces = [
            {"tool": "fetch_url", "input": {"url": "https://example.com/ep/tools"}, "ok": True, "output_excerpt": "<html>…</html>"},
            {"tool": "search_apple_podcasts", "input": {"show": "Show", "episode_title": "Ep"}, "ok": True, "result_count": 0, "output_excerpt": []},
        ]
        with self._patch_run(_output(), tool_calls=traces):
            fetch_episode_details(episode.pk)

        run = episode.fetch_details_runs.get()
        self.assertEqual(len(run.tool_calls_json), 2)
        self.assertEqual(run.tool_calls_json[0]["tool"], "fetch_url")

    def test_nonexistent_episode_silent(self):
        # No Episode row, no FetchDetailsRun, no exception.
        fetch_episode_details(99_999)
        self.assertEqual(FetchDetailsRun.objects.count(), 0)
