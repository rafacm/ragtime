"""Shape + validator tests for the fetch_details investigator agent.

Uses Pydantic AI's ``TestModel`` so the agent's full code path
(prompt → output validators → wrapped output schema) is exercised
without an LLM call.
"""

from datetime import date

from django.test import SimpleTestCase, override_settings

from episodes.agents.fetch_details import (
    AGGREGATOR_WHITELIST,
    ConciseMessage,
    EpisodeDetails,
    FetchDetailsOutput,
    FetchDetailsReport,
    get_agent,
)


def _output_payload(**details_overrides):
    """Build a structured payload matching ``FetchDetailsOutput``."""
    base_details = {
        "title": "Jazz Episode 1",
        "description": "A great episode about jazz.",
        "published_at": "2026-01-15",
        "image_url": "https://example.com/image.jpg",
        "audio_url": "https://example.com/ep1.mp3",
        "audio_format": "mp3",
        "language": "en",
        "country": "us",
        "guid": "urn:example:abc",
        "canonical_url": "https://example.com/ep/1",
        "source_kind": "canonical",
        "aggregator_provider": None,
    }
    base_details.update(details_overrides)
    return {
        "details": base_details,
        "report": {
            "attempted_sources": [
                {
                    "source": "user_url",
                    "url_or_query": "https://example.com/ep/1",
                    "outcome": "ok",
                    "note": "",
                }
            ],
            "discovered_canonical_url": True,
            "discovered_audio_url": True,
            "cross_linked": False,
            "extraction_confidence": "high",
            "narrative": "Loaded canonical page and extracted all required fields.",
            "hints_for_next_step": "",
        },
        "concise": {
            "outcome": "ok",
            "summary": "Canonical page extracted cleanly.",
        },
    }


@override_settings(
    RAGTIME_FETCH_DETAILS_API_KEY="test-key",
    RAGTIME_FETCH_DETAILS_MODEL="openai:gpt-4.1-mini",
)
class AgentOutputShapeTests(SimpleTestCase):
    """The agent must produce a valid ``FetchDetailsOutput`` for every outcome."""

    def setUp(self):
        get_agent.cache_clear()

    async def _run_with_payload(self, payload):
        from pydantic_ai.models.test import TestModel

        agent = get_agent()
        # `custom_output_args` short-circuits the LLM and feeds the
        # payload straight to the structured-output validator.
        with agent.override(model=TestModel(custom_output_args=payload)):
            from episodes.agents.fetch_details import run

            return await run("https://example.com/ep/1")

    async def test_ok_outcome_path(self):
        output, deps, _ = await self._run_with_payload(_output_payload())
        self.assertIsInstance(output, FetchDetailsOutput)
        self.assertEqual(output.concise.outcome, "ok")
        self.assertEqual(output.details.title, "Jazz Episode 1")
        self.assertEqual(output.details.published_at, date(2026, 1, 15))
        self.assertEqual(output.details.audio_format, "mp3")
        self.assertEqual(output.details.country, "us")
        self.assertEqual(output.details.source_kind, "canonical")
        # The deps object accumulates tool-call traces — empty here
        # since TestModel didn't issue any.
        self.assertIsInstance(deps.tool_calls, list)

    async def test_partial_outcome_path(self):
        payload = _output_payload(audio_url=None, audio_format=None)
        payload["report"]["discovered_audio_url"] = False
        payload["report"]["extraction_confidence"] = "medium"
        payload["concise"] = {
            "outcome": "partial",
            "summary": "Title found but audio URL is hidden behind JS.",
        }
        output, _, _ = await self._run_with_payload(payload)
        self.assertEqual(output.concise.outcome, "partial")
        self.assertIsNone(output.details.audio_url)

    async def test_not_a_podcast_episode_path(self):
        payload = _output_payload(
            title=None, audio_url=None, audio_format=None, guid=None,
            canonical_url=None, source_kind="unknown",
        )
        payload["concise"] = {
            "outcome": "not_a_podcast_episode",
            "summary": "Page is a homepage, not an episode.",
        }
        output, _, _ = await self._run_with_payload(payload)
        self.assertEqual(output.concise.outcome, "not_a_podcast_episode")

    async def test_unreachable_path(self):
        payload = _output_payload(
            title=None, audio_url=None, audio_format=None, guid=None,
            canonical_url=None, source_kind="unknown",
        )
        payload["concise"] = {
            "outcome": "unreachable",
            "summary": "fetch_url returned 503 for the submitted URL.",
        }
        output, _, _ = await self._run_with_payload(payload)
        self.assertEqual(output.concise.outcome, "unreachable")

    async def test_extraction_failed_path(self):
        payload = _output_payload(
            title=None, audio_url=None, audio_format=None,
            canonical_url=None, source_kind="unknown",
        )
        payload["concise"] = {
            "outcome": "extraction_failed",
            "summary": "Page loads but title is buried in dynamic markup.",
        }
        output, _, _ = await self._run_with_payload(payload)
        self.assertEqual(output.concise.outcome, "extraction_failed")


class EpisodeDetailsValidatorTests(SimpleTestCase):
    """Pure-Pydantic tests — no agent run, no Django ORM."""

    def test_parses_iso_date(self):
        d = EpisodeDetails(published_at="2026-01-15")
        self.assertEqual(d.published_at, date(2026, 1, 15))

    def test_invalid_date_becomes_none(self):
        d = EpisodeDetails(published_at="January 15, 2026")
        self.assertIsNone(d.published_at)

    def test_iso_639_language_kept(self):
        self.assertEqual(EpisodeDetails(language="en").language, "en")
        self.assertEqual(EpisodeDetails(language="EN").language, "en")
        self.assertIsNone(EpisodeDetails(language="english").language)

    def test_iso_3166_country_kept(self):
        self.assertEqual(EpisodeDetails(country="us").country, "us")
        self.assertEqual(EpisodeDetails(country="US").country, "us")
        self.assertIsNone(EpisodeDetails(country="usa").country)

    def test_url_validators_reject_relative(self):
        d = EpisodeDetails(
            audio_url="/audio/1.mp3",
            image_url="image.jpg",
            canonical_url="//cdn.example/ep",
        )
        self.assertIsNone(d.audio_url)
        self.assertIsNone(d.image_url)
        self.assertIsNone(d.canonical_url)

    def test_url_validators_accept_absolute(self):
        d = EpisodeDetails(
            audio_url="https://example.com/audio.mp3",
            image_url="http://example.com/img.jpg",
            canonical_url="https://example.com/ep",
        )
        self.assertEqual(d.audio_url, "https://example.com/audio.mp3")
        self.assertEqual(d.image_url, "http://example.com/img.jpg")
        self.assertEqual(d.canonical_url, "https://example.com/ep")

    def test_aggregator_provider_normalized(self):
        for raw, expected in (
            ("Apple", "apple_podcasts"),
            ("apple-podcasts", "apple_podcasts"),
            ("ITunes", "apple_podcasts"),
            ("Spotify", "spotify"),
        ):
            self.assertEqual(
                EpisodeDetails(aggregator_provider=raw).aggregator_provider,
                expected,
                msg=raw,
            )

    def test_aggregator_whitelist_documents_known_keys(self):
        # Sanity check the whitelist hasn't drifted away from the
        # normalize helper's expectations.
        self.assertIn("apple_podcasts", AGGREGATOR_WHITELIST)
        self.assertIn("fyyd", AGGREGATOR_WHITELIST)


class ConciseMessageTests(SimpleTestCase):
    def test_summary_capped_at_140(self):
        long = "x" * 200
        c = ConciseMessage(outcome="ok", summary=long)
        self.assertEqual(len(c.summary), 140)


class FetchDetailsReportDefaultsTest(SimpleTestCase):
    def test_minimal_report_defaults(self):
        # Ensure the report works with just the required attempted_sources;
        # downstream code reads booleans/strings without a KeyError.
        r = FetchDetailsReport(attempted_sources=[])
        self.assertFalse(r.discovered_audio_url)
        self.assertFalse(r.cross_linked)
        self.assertEqual(r.extraction_confidence, "low")
        self.assertEqual(r.narrative, "")
