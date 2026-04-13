"""Tests for the LangGraph pipeline orchestration."""

from unittest.mock import patch

from django.test import TestCase

from episodes.graph.edges import after_recovery, after_step, route_entry
from episodes.graph.state import EpisodeState
from episodes.models import Chunk, Episode
from episodes.processing import create_run


class RouteEntryTest(TestCase):
    """Tests for route_entry() — determines which step to start from."""

    def test_starts_from_scrape_for_new_episode(self):
        episode = Episode.objects.create(url="https://example.com/route/1")
        state: EpisodeState = {"episode_id": episode.pk, "start_from": ""}
        self.assertEqual(route_entry(state), "scrape")

    def test_starts_from_download_when_scraped(self):
        episode = Episode.objects.create(
            url="https://example.com/route/2",
            scraped_html="<html>data</html>",
            audio_url="https://example.com/audio.mp3",
        )
        state: EpisodeState = {"episode_id": episode.pk, "start_from": ""}
        self.assertEqual(route_entry(state), "download")

    def test_starts_from_transcribe_when_audio_exists(self):
        episode = Episode.objects.create(
            url="https://example.com/route/3",
            scraped_html="<html>data</html>",
            audio_url="https://example.com/audio.mp3",
        )
        episode.audio_file.name = "episodes/3.mp3"
        episode.save(update_fields=["audio_file"])
        state: EpisodeState = {"episode_id": episode.pk, "start_from": ""}
        self.assertEqual(route_entry(state), "transcribe")

    def test_skips_to_summarize_when_transcript_exists(self):
        episode = Episode.objects.create(
            url="https://example.com/route/4",
            scraped_html="<html>data</html>",
            audio_url="https://example.com/audio.mp3",
            transcript="Some transcript text",
        )
        episode.audio_file.name = "episodes/4.mp3"
        episode.save(update_fields=["audio_file"])
        state: EpisodeState = {"episode_id": episode.pk, "start_from": ""}
        self.assertEqual(route_entry(state), "summarize")

    def test_start_from_overrides_data_based_routing(self):
        """When start_from is set, it forces the start step."""
        episode = Episode.objects.create(
            url="https://example.com/route/5",
            scraped_html="<html>data</html>",
            audio_url="https://example.com/audio.mp3",
            transcript="transcript",
            summary_generated="summary",
        )
        episode.audio_file.name = "episodes/5.mp3"
        episode.save(update_fields=["audio_file"])
        # Without start_from, would skip to "chunk"
        state: EpisodeState = {"episode_id": episode.pk, "start_from": ""}
        self.assertEqual(route_entry(state), "chunk")
        # With start_from, forces "scrape"
        state["start_from"] = Episode.Status.SCRAPING
        self.assertEqual(route_entry(state), "scrape")

    def test_returns_end_for_ready_episode(self):
        from langgraph.graph import END

        episode = Episode.objects.create(
            url="https://example.com/route/6",
            status=Episode.Status.READY,
        )
        state: EpisodeState = {"episode_id": episode.pk, "start_from": ""}
        self.assertEqual(route_entry(state), END)


class AfterStepTest(TestCase):
    """Tests for after_step() — routes after each pipeline step."""

    def test_continue_on_success(self):
        state: EpisodeState = {"status": Episode.Status.DOWNLOADING}
        self.assertEqual(after_step(state), "continue")

    def test_recovery_on_failure(self):
        state: EpisodeState = {
            "status": Episode.Status.FAILED,
            "failed_step": Episode.Status.SCRAPING,
        }
        self.assertEqual(after_step(state), "recovery")

    def test_recovery_on_any_step_failure(self):
        """All failures route to recovery, not just scraping/downloading."""
        for step in [
            Episode.Status.SUMMARIZING,
            Episode.Status.EXTRACTING,
            Episode.Status.RESOLVING,
            Episode.Status.EMBEDDING,
        ]:
            state: EpisodeState = {"status": Episode.Status.FAILED, "failed_step": step}
            self.assertEqual(
                after_step(state), "recovery",
                f"Step {step} failure should route to recovery",
            )


class AfterRecoveryTest(TestCase):
    """Tests for after_recovery() — routes after recovery attempt."""

    def test_route_back_on_success(self):
        state: EpisodeState = {"recovery_result": "success"}
        self.assertEqual(after_recovery(state), "route")

    def test_end_on_failure(self):
        from langgraph.graph import END

        state: EpisodeState = {"recovery_result": "failed"}
        self.assertEqual(after_recovery(state), END)


class PipelineGraphTest(TestCase):
    """Integration tests for the compiled pipeline graph."""

    def test_graph_has_expected_nodes(self):
        from episodes.graph.pipeline import pipeline

        nodes = list(pipeline.get_graph().nodes.keys())
        for expected in [
            "route", "scrape", "download", "transcribe", "summarize",
            "chunk", "extract", "resolve", "embed", "recovery",
        ]:
            self.assertIn(expected, nodes)

    @patch("episodes.scraper.fetch_html")
    @patch("episodes.scraper.get_scraping_provider")
    def test_graph_runs_scrape_on_new_episode(self, mock_provider_factory, mock_fetch):
        """A new episode should start from scrape and fail if scraping fails."""
        mock_fetch.side_effect = Exception("Connection refused")
        episode = Episode.objects.create(url="https://example.com/graph/1")
        create_run(episode)

        from episodes.graph.pipeline import pipeline

        result = pipeline.invoke({
            "episode_id": episode.pk,
            "status": episode.status,
            "failed_step": "",
            "error": "",
            "recovery_result": "",
            "start_from": "",
        })

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertEqual(result["status"], Episode.Status.FAILED)
