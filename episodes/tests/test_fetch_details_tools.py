"""Tests for the three keyless tools in ``episodes/agents/fetch_details_tools.py``.

Each tool is exercised with mocked HTTP so the test suite stays
hermetic — ``fetch_url`` patches ``httpx.get``; the iTunes / fyyd
tools patch the underlying aggregator's ``search`` (those clients
already have direct HTTP coverage in
``test_podcast_aggregators.py``).
"""

from unittest.mock import patch

import httpx
from django.test import SimpleTestCase
from pydantic_ai import RunContext

from episodes.agents.fetch_details_deps import FetchDetailsDeps
from episodes.agents.fetch_details_tools import (
    fetch_url,
    search_apple_podcasts,
    search_fyyd,
)
from episodes.podcast_aggregators.base import EpisodeCandidate


class _FakeResponse:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("GET", "https://example"),
                response=httpx.Response(self.status_code),
            )


def _ctx(deps):
    """Build a minimal RunContext for tool calls.

    Pydantic AI's ``RunContext`` is a dataclass that can be instantiated
    directly — we only need the ``deps`` attribute for these tools.
    """
    # ``RunContext`` requires ``model``, ``usage``, ``prompt`` etc.,
    # but the tool bodies only read ``ctx.deps``. We construct via
    # ``object.__new__`` to bypass the strict dataclass init.
    ctx = object.__new__(RunContext)
    ctx.deps = deps  # type: ignore[attr-defined]
    return ctx


class FetchUrlTests(SimpleTestCase):
    async def test_returns_cleaned_html_and_records_trace(self):
        deps = FetchDetailsDeps(submitted_url="https://example.com/ep/1")
        html = (
            "<html><body><script>x</script>"
            "<p>Hello episode</p>"
            "<audio><source src='https://cdn.example/1.mp3'></audio>"
            "</body></html>"
        )
        with patch(
            "episodes.agents.fetch_details_tools.httpx.get"
        ) as get:
            get.return_value = _FakeResponse(html)
            result = await fetch_url(_ctx(deps), "https://example.com/ep/1")

        self.assertNotIn("<script", result)
        self.assertIn("Hello episode", result)
        self.assertIn("https://cdn.example/1.mp3", result)
        self.assertEqual(len(deps.tool_calls), 1)
        trace = deps.tool_calls[0]
        self.assertEqual(trace["tool"], "fetch_url")
        self.assertTrue(trace["ok"])
        self.assertEqual(trace["input"]["url"], "https://example.com/ep/1")

    async def test_fetch_failed_returns_marker(self):
        deps = FetchDetailsDeps(submitted_url="https://example.com/ep/1")
        with patch(
            "episodes.agents.fetch_details_tools.httpx.get"
        ) as get:
            get.side_effect = httpx.ConnectError("no route")
            result = await fetch_url(_ctx(deps), "https://example.com/ep/1")
        self.assertTrue(result.startswith("FETCH_FAILED:"))
        self.assertEqual(len(deps.tool_calls), 1)
        self.assertFalse(deps.tool_calls[0]["ok"])

    async def test_html_truncated_to_max(self):
        deps = FetchDetailsDeps(submitted_url="https://example.com/ep/1")
        long_html = "<html><body>" + ("x" * 60_000) + "</body></html>"
        with patch(
            "episodes.agents.fetch_details_tools.httpx.get"
        ) as get:
            get.return_value = _FakeResponse(long_html)
            result = await fetch_url(_ctx(deps), "https://example.com/ep/1")
        self.assertLessEqual(len(result), 30_000)


class SearchApplePodcastsTests(SimpleTestCase):
    async def test_returns_candidates_and_records_trace(self):
        deps = FetchDetailsDeps(submitted_url="https://example.com/ep/1")
        candidates = [
            EpisodeCandidate(
                audio_url="https://cdn.example/one.mp3",
                title="Episode One",
                show_name="Show",
                duration_seconds=1800,
                source_index="apple_podcasts",
            ),
            EpisodeCandidate(
                audio_url="https://cdn.example/two.mp3",
                title="Episode Two",
                show_name="Show",
                source_index="apple_podcasts",
            ),
        ]
        with patch(
            "episodes.podcast_aggregators.itunes.ItunesAggregator.search",
            return_value=candidates,
        ):
            results = await search_apple_podcasts(
                _ctx(deps), show="Show", episode_title="Episode One",
            )
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0].audio_url, "https://cdn.example/one.mp3")
        self.assertEqual(results[0].duration_seconds, 1800)
        self.assertEqual(len(deps.tool_calls), 1)
        trace = deps.tool_calls[0]
        self.assertEqual(trace["tool"], "search_apple_podcasts")
        self.assertEqual(trace["result_count"], 2)


class SearchFyydTests(SimpleTestCase):
    async def test_returns_candidates_and_records_trace(self):
        deps = FetchDetailsDeps(submitted_url="https://example.com/ep/1")
        candidates = [
            EpisodeCandidate(
                audio_url="https://cdn.example/one.mp3",
                title="Episode One",
                show_name="Show",
                duration_seconds=900,
                source_index="fyyd",
            ),
        ]
        with patch(
            "episodes.podcast_aggregators.fyyd.FyydAggregator.search",
            return_value=candidates,
        ):
            results = await search_fyyd(
                _ctx(deps), show="Show", episode_title="Episode One",
            )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].audio_url, "https://cdn.example/one.mp3")
        self.assertEqual(len(deps.tool_calls), 1)
        self.assertEqual(deps.tool_calls[0]["tool"], "search_fyyd")
