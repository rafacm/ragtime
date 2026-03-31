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

    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_new_entities(self, mock_factory):
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

        # 59 entities from fixture (3 null types: album, recording_session, record_label)
        self.assertEqual(Entity.objects.count(), 59)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)

        # All mentions have chunk FK set
        for mention in EntityMention.objects.filter(episode=episode):
            self.assertIsNotNone(mention.chunk_id)

    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_matches_existing(self, mock_factory):
        """LLM matches extracted entity to existing — no duplicate created."""
        from episodes.resolver import resolve_entities

        # Pre-create an existing entity
        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
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

        # Still only 1 musician entity
        self.assertEqual(
            Entity.objects.filter(entity_type=musician_type).count(), 1
        )
        # Mention was created with chunk FK
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)
        self.assertEqual(mention.chunk, chunk)
        self.assertEqual(mention.context, "trumpet player")

    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_mixed(self, mock_factory):
        """Some matches, some new."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                },
                {
                    "extracted_name": "John Coltrane",
                    "canonical_name": "John Coltrane",
                    "matched_entity_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
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

        # 2 musician entities: existing Miles + new Coltrane
        self.assertEqual(
            Entity.objects.filter(entity_type=musician_type).count(), 2
        )
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 2)

    @patch("episodes.resolver.get_resolution_provider")
    def test_same_entity_in_multiple_chunks(self, mock_factory):
        """Same entity in multiple chunks creates multiple mentions."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_chunk1 = {
            "musician": [
                {"name": "Miles Davis", "context": "early career"},
            ],
        }
        entities_chunk2 = {
            "musician": [
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

    @patch("episodes.resolver.get_resolution_provider")
    def test_aggregation_one_resolution_call(self, mock_factory):
        """Multiple chunks with same entity type -> one resolution call with unique names."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                },
                {
                    "extracted_name": "John Coltrane",
                    "canonical_name": "John Coltrane",
                    "matched_entity_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_chunk1 = {
            "musician": [
                {"name": "Miles Davis", "context": "trumpet"},
            ],
        }
        entities_chunk2 = {
            "musician": [
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

        # Only 1 LLM call (one entity type: musician)
        self.assertEqual(mock_provider.structured_extract.call_count, 1)

        # Unique names sent to resolution
        call_kwargs = mock_provider.structured_extract.call_args[1]
        self.assertIn("Miles Davis", call_kwargs["user_content"])
        self.assertIn("John Coltrane", call_kwargs["user_content"])

        # 3 mentions total: Miles in chunk0, Miles in chunk1, Coltrane in chunk1
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 3)

    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_canonical_name(self, mock_factory):
        """LLM returns canonical name different from extracted (e.g., Saxophon -> Saxophone)."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "musical_instrument": [
                {"name": "Saxophon", "context": "German spelling"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-4",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        instrument_type = _get_entity_type("musical_instrument")

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
                },
            ],
        }

        episode2 = self._create_episode(
            url="https://example.com/ep/res-4b",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode2, index=0, entities_json={
            "musical_instrument": [
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

    @patch("episodes.resolver.get_resolution_provider")
    def test_null_types_skipped(self, mock_factory):
        """Entity types with null value are skipped — no provider call needed."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": None,
            "musical_group": None,
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

    @patch("episodes.resolver.get_resolution_provider")
    def test_unmatched_canonical_name_already_exists(self, mock_factory):
        """LLM returns matched_entity_id=None but canonical_name already exists -> reuse entity."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type, name="Django Reinhardt"
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Django Reinhardt",
                    "canonical_name": "Django Reinhardt",
                    "matched_entity_id": None,  # LLM didn't match
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
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
            Entity.objects.filter(entity_type=musician_type).count(), 1
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

    @patch("episodes.resolver.get_resolution_provider")
    def test_provider_error(self, mock_factory):
        """LLM exception -> FAILED."""
        from episodes.resolver import resolve_entities

        # Pre-create an existing entity so LLM call happens
        musician_type = _get_entity_type("musician")
        Entity.objects.create(entity_type=musician_type, name="Miles Davis")

        mock_provider = MagicMock()
        mock_provider.structured_extract.side_effect = Exception("API error")
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
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

    @patch("episodes.resolver.get_resolution_provider")
    def test_idempotent_reprocessing(self, mock_factory):
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

    @patch("episodes.resolver.get_resolution_provider")
    def test_unknown_entity_type_skipped(self, mock_factory):
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
    def test_new_entities_created_directly_without_llm(self, mock_factory):
        """No existing entities — all created directly, no LLM call needed."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
                {"name": "Miles Davis", "context": "trumpet"},
                {"name": "John Coltrane", "context": "saxophone"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-new-direct",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # Both entities created without wikidata_id (linking agent will fill later)
        self.assertEqual(Entity.objects.count(), 2)
        miles = Entity.objects.get(name="Miles Davis")
        self.assertEqual(miles.wikidata_id, "")
        coltrane = Entity.objects.get(name="John Coltrane")
        self.assertEqual(coltrane.wikidata_id, "")

        # No LLM call when no existing entities
        mock_provider.structured_extract.assert_not_called()

        # Both have mentions
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 2)

    @patch("episodes.resolver.get_resolution_provider")
    def test_llm_omitted_name_fallback_existing_entities(self, mock_factory):
        """LLM omits a name when existing entities present — fallback creates it."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        # LLM only returns Miles Davis, omits John Coltrane
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
                {"name": "Miles Davis", "context": "trumpet"},
                {"name": "John Coltrane", "context": "saxophone"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-fallback-exist",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # Miles matched, Coltrane created via fallback
        self.assertEqual(Entity.objects.filter(entity_type=musician_type).count(), 2)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 2)

    @patch("episodes.resolver.get_resolution_provider")
    def test_two_names_same_entity_same_chunk(self, mock_factory):
        """Two extracted names resolve to the same entity in the same chunk — no duplicate mention."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type, name="Miles Davis"
        )

        mock_provider = MagicMock()
        # LLM maps both "Miles" and "Miles Davis" to the same entity
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                },
                {
                    "extracted_name": "Miles",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        # Both names appear in the same chunk
        entities_json = {
            "musician": [
                {"name": "Miles Davis", "context": "trumpet legend"},
                {"name": "Miles", "context": "short form"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-dedup-mention",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # Only 1 entity, 1 mention (deduped by entity+chunk)
        self.assertEqual(Entity.objects.filter(entity_type=musician_type).count(), 1)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 1)
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)

    @patch("episodes.resolver.get_resolution_provider")
    def test_new_entity_created_without_wikidata_id(self, mock_factory):
        """New entities are created without wikidata_id — linking agent fills it later."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
                {"name": "Miles Davis", "context": "trumpet"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-no-wd",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.count(), 1)
        self.assertEqual(Entity.objects.first().wikidata_id, "")

    @patch("episodes.resolver.get_resolution_provider")
    def test_start_time_flows_to_mention(self, mock_factory):
        """start_time in entities_json flows through to EntityMention.start_time."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
                {"name": "Miles Davis", "context": "trumpet", "start_time": 5.0},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-ts1",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.start_time, 5.0)

    @patch("episodes.resolver.get_resolution_provider")
    def test_missing_start_time_is_none(self, mock_factory):
        """entities_json without start_time key results in None on EntityMention."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [
                {"name": "Miles Davis", "context": "trumpet"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-ts2",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        mention = EntityMention.objects.get(episode=episode)
        self.assertIsNone(mention.start_time)

    @patch("episodes.resolver.get_resolution_provider")
    def test_start_time_per_chunk(self, mock_factory):
        """Same entity in multiple chunks gets different start_time per mention."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_chunk1 = {
            "musician": [
                {"name": "Miles Davis", "context": "early", "start_time": 5.0},
            ],
        }
        entities_chunk2 = {
            "musician": [
                {"name": "Miles Davis", "context": "later", "start_time": 35.0},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-ts3",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_chunk1)
        self._create_chunk(episode, index=1, entities_json=entities_chunk2)

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        mentions = EntityMention.objects.filter(episode=episode).order_by("chunk__index")
        self.assertEqual(mentions.count(), 2)
        self.assertEqual(mentions[0].start_time, 5.0)
        self.assertEqual(mentions[1].start_time, 35.0)

