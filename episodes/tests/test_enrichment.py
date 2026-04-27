"""Tests for the background Wikidata enrichment workflow.

The DBOS workflow + step decorators allow direct synchronous invocation
when DBOS itself isn't running, so tests call the underlying functions
without spinning up the durable runtime.
"""

from unittest.mock import MagicMock, patch

from django.test import TestCase

from episodes import enrichment
from episodes.models import Entity, EntityType


def _seed_artist_type(**overrides):
    defaults = {
        "key": "musician",
        "name": "Musician",
        "wikidata_id": "Q639669",
        "musicbrainz_table": "artist",
        "musicbrainz_filter": {"artist_type": "Person"},
        "description": "person",
        "examples": [],
    }
    defaults.update(overrides)
    et, _ = EntityType.objects.update_or_create(
        key=defaults["key"], defaults={k: v for k, v in defaults.items() if k != "key"}
    )
    return et


class EnrichEntityWikidataTests(TestCase):
    def setUp(self):
        self.musician = _seed_artist_type()

    def _make_entity(self, **kwargs):
        defaults = {"entity_type": self.musician, "name": "Miles Davis"}
        defaults.update(kwargs)
        return Entity.objects.create(**defaults)

    def test_short_circuits_if_already_resolved(self):
        entity = self._make_entity(wikidata_id="Q93341")
        with patch("episodes.enrichment.musicbrainz") as mock_mb, patch(
            "episodes.wikidata.find_candidates"
        ) as mock_wd:
            enrichment.enrich_entity_wikidata_impl(entity.pk)
            mock_mb.get_wikidata_qid.assert_not_called()
            mock_wd.assert_not_called()
        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_attempts, 0)

    def test_short_circuits_when_attempts_exhausted(self):
        entity = self._make_entity(wikidata_attempts=enrichment.MAX_ATTEMPTS)
        with patch("episodes.enrichment.musicbrainz") as mock_mb:
            enrichment.enrich_entity_wikidata_impl(entity.pk)
            mock_mb.get_wikidata_qid.assert_not_called()

    def test_resolves_via_mb_link(self):
        mbid = "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"
        entity = self._make_entity(musicbrainz_id=mbid)
        with patch.object(enrichment.musicbrainz, "get_wikidata_qid", return_value="Q93341"):
            enrichment.enrich_entity_wikidata_impl(entity.pk)
        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_id, "Q93341")
        self.assertEqual(entity.wikidata_status, Entity.WikidataStatus.RESOLVED)
        self.assertEqual(entity.wikidata_attempts, 1)
        self.assertIsNotNone(entity.wikidata_last_attempted_at)

    def test_falls_back_to_wikidata_search_when_mb_link_missing(self):
        mbid = "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"
        entity = self._make_entity(musicbrainz_id=mbid)

        with patch.object(enrichment.musicbrainz, "get_wikidata_qid", return_value=None):
            with patch(
                "episodes.wikidata.find_candidates",
                return_value=[{"qid": "Q93341", "label": "Miles Davis", "description": "trumpet"}],
            ):
                enrichment.enrich_entity_wikidata_impl(entity.pk)

        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_id, "Q93341")
        self.assertEqual(entity.wikidata_status, Entity.WikidataStatus.RESOLVED)

    def test_no_mbid_uses_wikidata_search_directly(self):
        entity = self._make_entity()  # no MBID

        with patch(
            "episodes.wikidata.find_candidates",
            return_value=[{"qid": "Q93341", "label": "Miles Davis", "description": "x"}],
        ):
            enrichment.enrich_entity_wikidata_impl(entity.pk)

        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_id, "Q93341")

    def test_multiple_wikidata_candidates_calls_llm_picker(self):
        entity = self._make_entity()

        candidates = [
            {"qid": "Q1", "label": "Miles Davis", "description": "trumpet"},
            {"qid": "Q2", "label": "Miles Davis Jr.", "description": "saxophone"},
        ]

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {"qid": "Q1"}

        with patch("episodes.wikidata.find_candidates", return_value=candidates):
            with patch(
                "episodes.providers.factory.get_resolution_provider",
                return_value=mock_provider,
            ):
                enrichment.enrich_entity_wikidata_impl(entity.pk)

        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_id, "Q1")
        # Picker prompt referenced both candidates.
        call_kwargs = mock_provider.structured_extract.call_args[1]
        self.assertIn("Q1", call_kwargs["system_prompt"])
        self.assertIn("Q2", call_kwargs["system_prompt"])

    def test_no_candidates_marks_status_after_max_attempts(self):
        entity = self._make_entity(wikidata_attempts=enrichment.MAX_ATTEMPTS - 1)
        with patch.object(enrichment.musicbrainz, "get_wikidata_qid", return_value=None):
            with patch("episodes.wikidata.find_candidates", return_value=[]):
                enrichment.enrich_entity_wikidata_impl(entity.pk)
        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_id, "")
        self.assertEqual(entity.wikidata_status, Entity.WikidataStatus.NOT_FOUND)
        self.assertEqual(entity.wikidata_attempts, enrichment.MAX_ATTEMPTS)

    def test_no_candidates_keeps_pending_below_max_attempts(self):
        entity = self._make_entity()
        with patch.object(enrichment.musicbrainz, "get_wikidata_qid", return_value=None):
            with patch("episodes.wikidata.find_candidates", return_value=[]):
                enrichment.enrich_entity_wikidata_impl(entity.pk)
        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_status, Entity.WikidataStatus.PENDING)
        self.assertEqual(entity.wikidata_attempts, 1)

    def test_no_entity_type_wikidata_id_skips_search(self):
        type_no_qid, _ = EntityType.objects.update_or_create(
            key="recording_session",
            defaults={"name": "Recording Session", "wikidata_id": ""},
        )
        entity = Entity.objects.create(
            entity_type=type_no_qid, name="Some Session"
        )

        with patch("episodes.wikidata.find_candidates") as mock_wd:
            enrichment.enrich_entity_wikidata_impl(entity.pk)
            mock_wd.assert_not_called()

        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_status, Entity.WikidataStatus.PENDING)
        self.assertEqual(entity.wikidata_attempts, 1)

    def test_wikidata_search_error_treated_as_no_candidates(self):
        entity = self._make_entity()
        with patch("episodes.wikidata.find_candidates", side_effect=RuntimeError("boom")):
            enrichment.enrich_entity_wikidata_impl(entity.pk)
        entity.refresh_from_db()
        self.assertEqual(entity.wikidata_status, Entity.WikidataStatus.PENDING)
        self.assertEqual(entity.wikidata_attempts, 1)

    def test_nonexistent_entity_is_a_no_op(self):
        # Should not raise
        enrichment.enrich_entity_wikidata_impl(999_999)


class EnqueueEntitiesTests(TestCase):
    """enqueue_entities should hand each id off to the DBOS queue."""

    def test_enqueues_each_id(self):
        with patch.object(enrichment.wikidata_queue, "enqueue") as mock_enq:
            enrichment.enqueue_entities([1, 2, 3])
        self.assertEqual(mock_enq.call_count, 3)

    def test_swallows_individual_enqueue_errors(self):
        with patch.object(
            enrichment.wikidata_queue, "enqueue", side_effect=RuntimeError("boom")
        ):
            # No exception raised.
            enrichment.enqueue_entities([1, 2])
