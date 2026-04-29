"""Tests for the podcast aggregator provider abstraction."""

from unittest.mock import patch

import httpx
from django.test import SimpleTestCase, override_settings

from episodes.podcast_aggregators import EpisodeCandidate, lookup_episode_candidates
from episodes.podcast_aggregators.factory import get_configured_aggregators
from episodes.podcast_aggregators.fyyd import FyydAggregator
from episodes.podcast_aggregators.itunes import ItunesAggregator
from episodes.podcast_aggregators.podcastindex import PodcastIndexOrg


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "boom",
                request=httpx.Request("GET", "https://example"),
                response=httpx.Response(self.status_code),
            )

    def json(self):
        return self._payload


class FyydAggregatorTests(SimpleTestCase):
    def test_search_returns_candidates(self):
        payload = {
            "data": [
                {
                    "title": "Django Reinhardt",
                    "enclosure": "https://wdr.example/episode.mp3",
                    "duration": 1800,
                    "podcast": {"title": "Zeitzeichen"},
                },
                {
                    "title": "No enclosure",
                    "enclosure": "",
                },
            ]
        }
        with patch("episodes.podcast_aggregators.fyyd.httpx.get") as get:
            get.return_value = _FakeResponse(payload)
            results = FyydAggregator().search(
                title="Django Reinhardt", show_name="Zeitzeichen"
            )

        self.assertEqual(len(results), 1)
        c = results[0]
        self.assertEqual(c.audio_url, "https://wdr.example/episode.mp3")
        self.assertEqual(c.show_name, "Zeitzeichen")
        self.assertEqual(c.duration_seconds, 1800)
        self.assertEqual(c.source_index, "fyyd")

    def test_empty_term_returns_empty(self):
        # No title or show — fyyd cannot search.
        self.assertEqual(FyydAggregator().search(title="", show_name=""), [])

    def test_http_error_returns_empty(self):
        with patch("episodes.podcast_aggregators.fyyd.httpx.get") as get:
            get.side_effect = httpx.ConnectError("nope")
            self.assertEqual(FyydAggregator().search(title="x"), [])


class ItunesAggregatorTests(SimpleTestCase):
    def test_search_returns_candidates(self):
        payload = {
            "results": [
                {
                    "trackName": "Episode One",
                    "collectionName": "Show",
                    "episodeUrl": "https://cdn.example/one.mp3",
                    "trackTimeMillis": 1_800_000,
                    "trackViewUrl": "https://podcasts.apple.com/us/podcast/show/id1?i=1",
                },
                {
                    "trackName": "No URL",
                    "episodeUrl": "",
                },
            ]
        }
        with patch("episodes.podcast_aggregators.itunes.httpx.get") as get:
            get.return_value = _FakeResponse(payload)
            results = ItunesAggregator().search(title="Episode One", show_name="Show")

        self.assertEqual(len(results), 1)
        c = results[0]
        self.assertEqual(c.audio_url, "https://cdn.example/one.mp3")
        self.assertEqual(c.show_name, "Show")
        self.assertEqual(c.duration_seconds, 1800)
        self.assertEqual(c.source_index, "apple_podcasts")
        self.assertEqual(
            c.episode_page_url,
            "https://podcasts.apple.com/us/podcast/show/id1?i=1",
        )

    def test_empty_term_returns_empty(self):
        self.assertEqual(ItunesAggregator().search(title="", show_name=""), [])

    def test_http_error_returns_empty(self):
        with patch("episodes.podcast_aggregators.itunes.httpx.get") as get:
            get.side_effect = httpx.ConnectError("nope")
            self.assertEqual(ItunesAggregator().search(title="x"), [])


class PodcastIndexOrgTests(SimpleTestCase):
    def test_guid_lookup_first(self):
        guid_payload = {
            "episode": {
                "title": "Episode by GUID",
                "enclosureUrl": "https://example/by-guid.mp3",
                "feedTitle": "Show",
            }
        }
        with patch("episodes.podcast_aggregators.podcastindex.httpx.get") as get:
            get.return_value = _FakeResponse(guid_payload)
            results = PodcastIndexOrg("k", "s").search(
                title="t", show_name="Show", guid="urn:abc"
            )
        # GUID branch — only one HTTP call.
        self.assertEqual(get.call_count, 1)
        called_url = get.call_args[0][0]
        self.assertIn("/episodes/byguid", called_url)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].audio_url, "https://example/by-guid.mp3")

    def test_falls_back_to_term_search_when_guid_missing(self):
        with patch("episodes.podcast_aggregators.podcastindex.httpx.get") as get:
            get.return_value = _FakeResponse({"feeds": []})
            PodcastIndexOrg("k", "s").search(title="t", show_name="Show")
        called_url = get.call_args[0][0]
        self.assertIn("/search/byterm", called_url)


class FactoryTests(SimpleTestCase):
    @override_settings(RAGTIME_PODCAST_AGGREGATORS="")
    def test_disabled_returns_empty(self):
        self.assertEqual(get_configured_aggregators(), [])
        self.assertEqual(lookup_episode_candidates(title="x"), [])

    @override_settings(
        RAGTIME_PODCAST_AGGREGATORS="fyyd",
        RAGTIME_FYYD_API_KEY="",
    )
    def test_fyyd_built_without_key(self):
        aggregators = get_configured_aggregators()
        self.assertEqual(len(aggregators), 1)
        self.assertEqual(aggregators[0].name, "fyyd")

    @override_settings(RAGTIME_PODCAST_AGGREGATORS="apple_podcasts")
    def test_itunes_built(self):
        aggregators = get_configured_aggregators()
        self.assertEqual(len(aggregators), 1)
        self.assertEqual(aggregators[0].name, "apple_podcasts")

    @override_settings(RAGTIME_PODCAST_AGGREGATORS="itunes")
    def test_itunes_alias_built(self):
        aggregators = get_configured_aggregators()
        self.assertEqual(len(aggregators), 1)
        self.assertEqual(aggregators[0].name, "apple_podcasts")

    @override_settings(
        RAGTIME_PODCAST_AGGREGATORS="podcastindex",
        RAGTIME_PODCASTINDEX_API_KEY="",
        RAGTIME_PODCASTINDEX_API_SECRET="",
    )
    def test_podcastindex_skipped_without_credentials(self):
        # Missing key/secret — log warning and skip silently.
        self.assertEqual(get_configured_aggregators(), [])

    @override_settings(RAGTIME_PODCAST_AGGREGATORS="bogus")
    def test_unknown_provider_skipped(self):
        self.assertEqual(get_configured_aggregators(), [])

    @override_settings(
        RAGTIME_PODCAST_AGGREGATORS="fyyd,podcastindex",
        RAGTIME_PODCASTINDEX_API_KEY="k",
        RAGTIME_PODCASTINDEX_API_SECRET="s",
    )
    def test_dedupes_by_audio_url(self):
        shared = EpisodeCandidate(
            audio_url="https://shared/episode.mp3", source_index="fyyd"
        )
        unique = EpisodeCandidate(
            audio_url="https://only-pi/episode.mp3", source_index="podcastindex"
        )
        with patch.object(FyydAggregator, "search", return_value=[shared]), \
             patch.object(PodcastIndexOrg, "search", return_value=[shared, unique]):
            results = lookup_episode_candidates(title="t")

        urls = [c.audio_url for c in results]
        self.assertEqual(urls, ["https://shared/episode.mp3", "https://only-pi/episode.mp3"])
        # Order preserved: fyyd first because it appears first in the env list.
        self.assertEqual(results[0].source_index, "fyyd")

    @override_settings(RAGTIME_PODCAST_AGGREGATORS="fyyd")
    def test_provider_exception_is_swallowed(self):
        with patch.object(FyydAggregator, "search", side_effect=RuntimeError("crash")):
            self.assertEqual(lookup_episode_candidates(title="x"), [])
