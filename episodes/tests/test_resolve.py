import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml
from django.test import TestCase, override_settings

from episodes.models import Chunk, Entity, EntityMention, EntityType, Episode

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_YAML_PATH = Path(__file__).resolve().parent.parent / "initial_entity_types.yaml"


def _load_fixture(name):
    with open(_FIXTURES_DIR / name) as f:
        return json.load(f)


def _seed_entity_types():
    """Create EntityType rows from the YAML seed file."""
    with open(_YAML_PATH) as f:
        for et in yaml.safe_load(f):
            EntityType.objects.update_or_create(
                key=et["key"],
                defaults={
                    "name": et["name"],
                    "wikidata_id": et.get("wikidata_id", ""),
                    "description": et.get("description", ""),
                    "examples": et.get("examples", []),
                },
            )


def _get_entity_type(key):
    return EntityType.objects.get(key=key)


@override_settings(
    RAGTIME_RESOLUTION_PROVIDER="openai",
    RAGTIME_RESOLUTION_API_KEY="test-key",
    RAGTIME_RESOLUTION_MODEL="gpt-4.1-mini",
)
class ResolveEntitiesTests(TestCase):
    """Tests for the resolve_entities task function."""

    SAMPLE_ENTITIES = _load_fixture(
        "wdr-giant-steps-django-reinhardt-episode-extracted-entities.json"
    )

    def setUp(self):
        _seed_entity_types()

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.async_task"):
            return Episode.objects.create(**kwargs)

    def _create_chunk(self, episode, index=0, entities_json=None, text="chunk text"):
        return Chunk.objects.create(
            episode=episode,
            index=index,
            text=text,
            start_time=index * 30.0,
            end_time=(index + 1) * 30.0,
            segment_start=index * 10,
            segment_end=(index + 1) * 10,
            entities_json=entities_json,
        )

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_new_entities(self, mock_factory, _mock_wd):
        """No existing DB entities — all created as new, no LLM call."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/res-1",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=self.SAMPLE_ENTITIES)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # No LLM call needed when no existing entities and no Wikidata candidates
        mock_provider.structured_extract.assert_not_called()

        # 59 entities from fixture (3 null types: album, recording_session, label)
        self.assertEqual(Entity.objects.count(), 59)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)

        # All mentions have chunk FK set
        for mention in EntityMention.objects.filter(episode=episode):
            self.assertIsNotNone(mention.chunk_id)

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_matches_existing(self, mock_factory, _mock_wd):
        """LLM matches extracted entity to existing — no duplicate created."""
        from episodes.resolver import resolve_entities

        # Pre-create an existing entity
        artist_type = _get_entity_type("artist")
        existing = Entity.objects.create(
            entity_type=artist_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                    "wikidata_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": [
                {"name": "Miles Davis", "context": "trumpet player"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-2",
            status=Episode.Status.RESOLVING,
        )
        chunk = self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # Still only 1 artist entity
        self.assertEqual(
            Entity.objects.filter(entity_type=artist_type).count(), 1
        )
        # Mention was created with chunk FK
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)
        self.assertEqual(mention.chunk, chunk)
        self.assertEqual(mention.context, "trumpet player")

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_mixed(self, mock_factory, _mock_wd):
        """Some matches, some new."""
        from episodes.resolver import resolve_entities

        artist_type = _get_entity_type("artist")
        existing = Entity.objects.create(
            entity_type=artist_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                    "wikidata_id": None,
                },
                {
                    "extracted_name": "John Coltrane",
                    "canonical_name": "John Coltrane",
                    "matched_entity_id": None,
                    "wikidata_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": [
                {"name": "Miles Davis", "context": "trumpet"},
                {"name": "John Coltrane", "context": "saxophone"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-3",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # 2 artist entities: existing Miles + new Coltrane
        self.assertEqual(
            Entity.objects.filter(entity_type=artist_type).count(), 2
        )
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 2)

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_same_entity_in_multiple_chunks(self, mock_factory, _mock_wd):
        """Same entity in multiple chunks creates multiple mentions."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_chunk1 = {
            "artist": [
                {"name": "Miles Davis", "context": "early career"},
            ],
        }
        entities_chunk2 = {
            "artist": [
                {"name": "Miles Davis", "context": "later work"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-multi",
            status=Episode.Status.RESOLVING,
        )
        chunk1 = self._create_chunk(episode, index=0, entities_json=entities_chunk1)
        chunk2 = self._create_chunk(episode, index=1, entities_json=entities_chunk2)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # 1 entity, but 2 mentions (one per chunk)
        self.assertEqual(Entity.objects.count(), 1)
        mentions = EntityMention.objects.filter(episode=episode).order_by("chunk__index")
        self.assertEqual(mentions.count(), 2)
        self.assertEqual(mentions[0].chunk, chunk1)
        self.assertEqual(mentions[0].context, "early career")
        self.assertEqual(mentions[1].chunk, chunk2)
        self.assertEqual(mentions[1].context, "later work")

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_aggregation_one_resolution_call(self, mock_factory, _mock_wd):
        """Multiple chunks with same entity type -> one resolution call with unique names."""
        from episodes.resolver import resolve_entities

        artist_type = _get_entity_type("artist")
        existing = Entity.objects.create(
            entity_type=artist_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                    "wikidata_id": None,
                },
                {
                    "extracted_name": "John Coltrane",
                    "canonical_name": "John Coltrane",
                    "matched_entity_id": None,
                    "wikidata_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_chunk1 = {
            "artist": [
                {"name": "Miles Davis", "context": "trumpet"},
            ],
        }
        entities_chunk2 = {
            "artist": [
                {"name": "Miles Davis", "context": "bandleader"},
                {"name": "John Coltrane", "context": "saxophone"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-agg",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_chunk1)
        self._create_chunk(episode, index=1, entities_json=entities_chunk2)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        # Only 1 LLM call (one entity type: artist)
        self.assertEqual(mock_provider.structured_extract.call_count, 1)

        # Unique names sent to resolution
        call_kwargs = mock_provider.structured_extract.call_args[1]
        self.assertIn("Miles Davis", call_kwargs["user_content"])
        self.assertIn("John Coltrane", call_kwargs["user_content"])

        # 3 mentions total: Miles in chunk0, Miles in chunk1, Coltrane in chunk1
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 3)

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_canonical_name(self, mock_factory, _mock_wd):
        """LLM returns canonical name different from extracted (e.g., Saxophon -> Saxophone)."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "instrument": [
                {"name": "Saxophon", "context": "German spelling"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-4",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        instrument_type = _get_entity_type("instrument")

        # First episode — no existing entities, so created directly with extracted name
        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        entity = Entity.objects.get(entity_type=instrument_type)
        self.assertEqual(entity.name, "Saxophon")

        # Second episode with existing entity — LLM resolves to canonical name
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Saxophone",
                    "canonical_name": "Saxophone",
                    "matched_entity_id": entity.pk,
                    "wikidata_id": None,
                },
            ],
        }

        episode2 = self._create_episode(
            url="https://example.com/ep/res-4b",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode2, index=0, entities_json={
            "instrument": [
                {"name": "Saxophone", "context": "English spelling"},
            ],
        })

        with patch("episodes.signals.async_task"):
            resolve_entities(episode2.pk)

        # Still only 1 instrument entity (matched)
        self.assertEqual(
            Entity.objects.filter(entity_type=instrument_type).count(), 1
        )
        # 2 mentions across 2 episodes
        self.assertEqual(EntityMention.objects.filter(entity=entity).count(), 2)

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_null_types_skipped(self, mock_factory, _mock_wd):
        """Entity types with null value are skipped — no provider call needed."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": None,
            "band": None,
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-5",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.count(), 0)
        self.assertEqual(EntityMention.objects.count(), 0)
        # All-null dict should early-return without calling the provider
        mock_factory.assert_not_called()

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_unmatched_canonical_name_already_exists(self, mock_factory, _mock_wd):
        """LLM returns matched_entity_id=None but canonical_name already exists -> reuse entity."""
        from episodes.resolver import resolve_entities

        artist_type = _get_entity_type("artist")
        existing = Entity.objects.create(
            entity_type=artist_type, name="Django Reinhardt"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Django Reinhardt",
                    "canonical_name": "Django Reinhardt",
                    "matched_entity_id": None,  # LLM didn't match
                    "wikidata_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": [
                {"name": "Django Reinhardt", "context": "jazz guitarist"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-dup",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # Should reuse existing entity, not crash
        self.assertEqual(
            Entity.objects.filter(entity_type=artist_type).count(), 1
        )
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)

    def test_no_entities_in_any_chunk_succeeds(self):
        """No entities in any chunk -> success (transition to EMBEDDING)."""
        from episodes.resolver import resolve_entities

        episode = self._create_episode(
            url="https://example.com/ep/res-empty",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=None)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

    def test_wrong_status(self):
        """Not RESOLVING -> no-op."""
        from episodes.resolver import resolve_entities

        episode = self._create_episode(
            url="https://example.com/ep/res-7",
            status=Episode.Status.PENDING,
        )

        resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.PENDING)

    def test_nonexistent_episode(self):
        """No crash on nonexistent episode."""
        from episodes.resolver import resolve_entities

        resolve_entities(99999)  # should not raise

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_provider_error(self, mock_factory, _mock_wd):
        """LLM exception -> FAILED."""
        from episodes.resolver import resolve_entities

        # Pre-create an existing entity so LLM call happens
        artist_type = _get_entity_type("artist")
        Entity.objects.create(entity_type=artist_type, name="Miles Davis")

        mock_provider = MagicMock()
        mock_provider.structured_extract.side_effect = Exception("API error")
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": [
                {"name": "Miles Davis", "context": "trumpet"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-8",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("API error", episode.error_message)

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_idempotent_reprocessing(self, mock_factory, _mock_wd):
        """Running twice with full fixture doesn't create duplicate entities or mentions."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/res-9",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=self.SAMPLE_ENTITIES)

        # First run — no existing entities, creates all 59 as new (no LLM call)
        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        self.assertEqual(Entity.objects.count(), 59)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)
        mock_provider.structured_extract.assert_not_called()

        # Build mock responses for second run: every entity matches its existing record
        def mock_structured_extract(system_prompt, user_content, response_schema):
            for entity_type_key, entities in self.SAMPLE_ENTITIES.items():
                if entities is None:
                    continue
                if f"type '{entity_type_key}'" in system_prompt:
                    et = _get_entity_type(entity_type_key)
                    existing = Entity.objects.filter(entity_type=et)
                    existing_by_name = {e.name: e.pk for e in existing}
                    matches = []
                    for extracted in entities:
                        name = extracted["name"]
                        matches.append({
                            "extracted_name": name,
                            "canonical_name": name,
                            "matched_entity_id": existing_by_name.get(name),
                            "wikidata_id": None,
                        })
                    return {"matches": matches}
            return {"matches": []}

        mock_provider.structured_extract.side_effect = mock_structured_extract

        # Reset status and run again
        episode.status = Episode.Status.RESOLVING
        with patch("episodes.signals.async_task"):
            episode.save(update_fields=["status", "updated_at"])
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # 11 LLM calls — one per non-null entity type
        non_null_types = sum(1 for v in self.SAMPLE_ENTITIES.values() if v is not None)
        self.assertEqual(mock_provider.structured_extract.call_count, non_null_types)

        # Still 59 entities (all matched, no new ones created)
        self.assertEqual(Entity.objects.count(), 59)
        # Still 59 mentions (old ones deleted, new ones created)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_unknown_entity_type_skipped(self, mock_factory, _mock_wd):
        """Entity types not in DB are skipped with a warning."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "nonexistent_type": [
                {"name": "Something", "context": "test"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-unknown",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.count(), 0)

    @patch("episodes.resolver.get_resolution_provider")
    def test_wikidata_candidates_used_in_resolution(self, mock_factory):
        """Wikidata candidates are passed to the LLM and wikidata_id is saved."""
        from episodes.resolver import resolve_entities

        artist_type = _get_entity_type("artist")
        existing = Entity.objects.create(
            entity_type=artist_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                    "wikidata_id": "Q93341",
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": [
                {"name": "Miles Davis", "context": "trumpet"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-wd",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        wikidata_candidates = {
            "Miles Davis": [
                {"qid": "Q93341", "label": "Miles Davis", "description": "American jazz trumpeter"},
            ],
        }

        with patch("episodes.resolver._fetch_wikidata_candidates", return_value=wikidata_candidates):
            with patch("episodes.signals.async_task"):
                resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # Entity should have wikidata_id set
        existing.refresh_from_db()
        self.assertEqual(existing.wikidata_id, "Q93341")

        # Wikidata candidates should appear in the system prompt
        call_kwargs = mock_provider.structured_extract.call_args[1]
        self.assertIn("Q93341", call_kwargs["system_prompt"])
        self.assertIn("American jazz trumpeter", call_kwargs["system_prompt"])

    @patch("episodes.resolver.get_resolution_provider")
    def test_wikidata_id_match_existing_entity(self, mock_factory):
        """Entity with matching wikidata_id in DB is reused."""
        from episodes.resolver import resolve_entities

        artist_type = _get_entity_type("artist")
        existing = Entity.objects.create(
            entity_type=artist_type, name="Miles Davis", wikidata_id="Q93341"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "M. Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": None,  # LLM didn't match by ID
                    "wikidata_id": "Q93341",  # But matched by Wikidata
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": [
                {"name": "M. Davis", "context": "trumpet"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-wd-match",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.resolver._fetch_wikidata_candidates", return_value={}):
            with patch("episodes.signals.async_task"):
                resolve_entities(episode.pk)

        # Should match existing entity by wikidata_id
        self.assertEqual(Entity.objects.filter(entity_type=artist_type).count(), 1)
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)

    @patch("episodes.resolver.get_resolution_provider")
    def test_wikidata_new_entities_with_candidates(self, mock_factory):
        """New entities with Wikidata candidates get wikidata_id assigned via LLM."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": None,
                    "wikidata_id": "Q93341",
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": [
                {"name": "Miles Davis", "context": "trumpet"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-wd-new",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        wikidata_candidates = {
            "Miles Davis": [
                {"qid": "Q93341", "label": "Miles Davis", "description": "jazz trumpeter"},
            ],
        }

        with patch("episodes.resolver._fetch_wikidata_candidates", return_value=wikidata_candidates):
            with patch("episodes.signals.async_task"):
                resolve_entities(episode.pk)

        # Entity created with wikidata_id
        entity = Entity.objects.get(name="Miles Davis")
        self.assertEqual(entity.wikidata_id, "Q93341")

    @patch("episodes.resolver._fetch_wikidata_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_wikidata_fallback_on_failure(self, mock_factory, _mock_wd):
        """Wikidata failure doesn't break resolution — falls back to no candidates."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "artist": [
                {"name": "Miles Davis", "context": "trumpet"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-wd-fail",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.count(), 1)
        # No wikidata_id since no candidates
        self.assertEqual(Entity.objects.first().wikidata_id, "")
