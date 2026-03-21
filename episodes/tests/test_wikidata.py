from unittest.mock import MagicMock, patch

from django.core.cache import caches
from django.test import TestCase, override_settings


@override_settings(
    CACHES={
        "default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
        "wikidata": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"},
    },
    RAGTIME_WIKIDATA_USER_AGENT="RAGtime-test/0.1",
    RAGTIME_WIKIDATA_CACHE_TTL=60,
)
class WikidataClientTests(TestCase):
    """Tests for the Wikidata API client."""

    def setUp(self):
        caches["wikidata"].clear()

    def _mock_search_response(self, results):
        return {
            "search": [
                {"id": r["qid"], "label": r["label"], "description": r.get("description", "")}
                for r in results
            ]
        }

    def _mock_entity_response(self, qid, label, description, p31_ids=None):
        claims = {}
        if p31_ids:
            claims["P31"] = [
                {
                    "mainsnak": {
                        "datavalue": {
                            "value": {"id": pid}
                        }
                    }
                }
                for pid in p31_ids
            ]
        return {
            "entities": {
                qid: {
                    "labels": {"en": {"value": label}},
                    "descriptions": {"en": {"value": description}},
                    "aliases": {"en": [{"value": "alias1"}]},
                    "claims": claims,
                }
            }
        }

    @patch("episodes.wikidata.httpx.get")
    def test_search_entities(self, mock_get):
        from episodes.wikidata import search_entities

        mock_response = MagicMock()
        mock_response.json.return_value = self._mock_search_response([
            {"qid": "Q93341", "label": "Miles Davis", "description": "American jazz trumpeter"},
            {"qid": "Q55649041", "label": "Miles Davis", "description": "album"},
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        results = search_entities("Miles Davis")

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["qid"], "Q93341")
        self.assertEqual(results[0]["label"], "Miles Davis")
        self.assertIn("trumpeter", results[0]["description"])

    @patch("episodes.wikidata.httpx.get")
    def test_get_entity(self, mock_get):
        from episodes.wikidata import get_entity

        mock_response = MagicMock()
        mock_response.json.return_value = self._mock_entity_response(
            "Q93341", "Miles Davis", "American jazz trumpeter", ["Q639669"]
        )
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = get_entity("Q93341")

        self.assertEqual(result["qid"], "Q93341")
        self.assertEqual(result["label"], "Miles Davis")
        self.assertEqual(result["aliases"], ["alias1"])
        self.assertIn("P31", result["claims"])

    @patch("episodes.wikidata.httpx.get")
    def test_find_candidates_filters_by_p31(self, mock_get):
        from episodes.wikidata import find_candidates

        # First call: search
        search_response = MagicMock()
        search_response.json.return_value = self._mock_search_response([
            {"qid": "Q93341", "label": "Miles Davis", "description": "trumpeter"},
            {"qid": "Q55649041", "label": "Miles Davis", "description": "album"},
        ])
        search_response.raise_for_status = MagicMock()

        # Second call: get entity Q93341 (is musician Q639669)
        entity1_response = MagicMock()
        entity1_response.json.return_value = self._mock_entity_response(
            "Q93341", "Miles Davis", "American jazz trumpeter", ["Q639669"]
        )
        entity1_response.raise_for_status = MagicMock()

        # Third call: get entity Q55649041 (is album Q482994, not musician)
        entity2_response = MagicMock()
        entity2_response.json.return_value = self._mock_entity_response(
            "Q55649041", "Miles Davis", "album", ["Q482994"]
        )
        entity2_response.raise_for_status = MagicMock()

        mock_get.side_effect = [search_response, entity1_response, entity2_response]

        results = find_candidates("Miles Davis", "Q639669")

        # Only Q93341 should match (it's instance of musician Q639669)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["qid"], "Q93341")

    @patch("episodes.wikidata.httpx.get")
    def test_find_candidates_no_entity_type_qid(self, mock_get):
        from episodes.wikidata import find_candidates

        results = find_candidates("Miles Davis", "")
        self.assertEqual(results, [])
        mock_get.assert_not_called()

    @patch("episodes.wikidata.httpx.get")
    def test_caching(self, mock_get):
        from episodes.wikidata import search_entities

        mock_response = MagicMock()
        mock_response.json.return_value = self._mock_search_response([
            {"qid": "Q93341", "label": "Miles Davis", "description": "trumpeter"},
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # First call hits API
        results1 = search_entities("Miles Davis")
        self.assertEqual(mock_get.call_count, 1)

        # Second call uses cache
        results2 = search_entities("Miles Davis")
        self.assertEqual(mock_get.call_count, 1)  # No additional call
        self.assertEqual(results1, results2)

    @patch("episodes.wikidata.httpx.get")
    @patch("episodes.wikidata._rate_limiter")
    def test_rate_limiter_called_on_cache_miss(self, mock_limiter, mock_get):
        from episodes.wikidata import search_entities

        mock_response = MagicMock()
        mock_response.json.return_value = self._mock_search_response([
            {"qid": "Q93341", "label": "Miles Davis", "description": "trumpeter"},
        ])
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        # First call: cache miss — rate limiter should be called
        search_entities("Miles Davis")
        mock_limiter.acquire.assert_called_once()

        # Second call: cache hit — rate limiter should NOT be called again
        search_entities("Miles Davis")
        mock_limiter.acquire.assert_called_once()
