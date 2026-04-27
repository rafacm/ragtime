import json
from pathlib import Path
from types import SimpleNamespace
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
                    "musicbrainz_table": et.get("musicbrainz_table", ""),
                    "musicbrainz_filter": et.get("musicbrainz_filter") or {},
                    "description": et.get("description", ""),
                    "examples": et.get("examples", []),
                },
            )


def _get_entity_type(key):
    return EntityType.objects.get(key=key)


def _mb_candidate(mbid, name="X", disambiguation="", type_="Person"):
    """Build a fake MB Candidate object for prompt construction."""
    return SimpleNamespace(
        mbid=mbid,
        name=name,
        disambiguation=disambiguation,
        type=type_,
    )


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
        # Patch enrichment enqueue across all tests so we don't actually try
        # to enqueue DBOS workflows from inside a test transaction.
        patcher = patch("episodes.resolver._enqueue_enrichment")
        self._mock_enqueue = patcher.start()
        self.addCleanup(patcher.stop)

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.DBOS"):
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

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_new_entities(self, mock_factory, _mock_mb):
        """No existing DB entities — all created as new, no LLM call."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/res-1",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=self.SAMPLE_ENTITIES)

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # No LLM call needed when no existing entities and no MB candidates
        mock_provider.structured_extract.assert_not_called()

        self.assertEqual(Entity.objects.count(), 59)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)
        for mention in EntityMention.objects.filter(episode=episode):
            self.assertIsNotNone(mention.chunk_id)

        # All new entities are pending Wikidata enrichment.
        for entity in Entity.objects.all():
            self.assertEqual(entity.wikidata_status, Entity.WikidataStatus.PENDING)
            self.assertEqual(entity.wikidata_id, "")
            self.assertEqual(entity.musicbrainz_id, "")

        # Enrichment was enqueued for the new entities.
        self.assertTrue(self._mock_enqueue.called)
        enqueued_ids = self._mock_enqueue.call_args[0][0]
        self.assertEqual(len(enqueued_ids), 59)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_matches_existing(self, mock_factory, _mock_mb):
        """LLM matches extracted entity to existing — no duplicate created."""
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
                    "musicbrainz_id": None,
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

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        self.assertEqual(
            Entity.objects.filter(entity_type=musician_type).count(), 1
        )
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)
        self.assertEqual(mention.chunk, chunk)
        self.assertEqual(mention.context, "trumpet player")

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_mixed(self, mock_factory, _mock_mb):
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
                    "musicbrainz_id": None,
                },
                {
                    "extracted_name": "John Coltrane",
                    "canonical_name": "John Coltrane",
                    "matched_entity_id": None,
                    "musicbrainz_id": None,
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

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(
            Entity.objects.filter(entity_type=musician_type).count(), 2
        )
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 2)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_same_entity_in_multiple_chunks(self, mock_factory, _mock_mb):
        """Same entity in multiple chunks creates multiple mentions."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_chunk1 = {
            "musician": [{"name": "Miles Davis", "context": "early career"}],
        }
        entities_chunk2 = {
            "musician": [{"name": "Miles Davis", "context": "later work"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-multi",
            status=Episode.Status.RESOLVING,
        )
        chunk1 = self._create_chunk(episode, index=0, entities_json=entities_chunk1)
        chunk2 = self._create_chunk(episode, index=1, entities_json=entities_chunk2)

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.count(), 1)
        mentions = EntityMention.objects.filter(episode=episode).order_by("chunk__index")
        self.assertEqual(mentions.count(), 2)
        self.assertEqual(mentions[0].chunk, chunk1)
        self.assertEqual(mentions[0].context, "early career")
        self.assertEqual(mentions[1].chunk, chunk2)
        self.assertEqual(mentions[1].context, "later work")

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_aggregation_one_resolution_call(self, mock_factory, _mock_mb):
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
                    "musicbrainz_id": None,
                },
                {
                    "extracted_name": "John Coltrane",
                    "canonical_name": "John Coltrane",
                    "matched_entity_id": None,
                    "musicbrainz_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/res-agg",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json={
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        })
        self._create_chunk(episode, index=1, entities_json={
            "musician": [
                {"name": "Miles Davis", "context": "bandleader"},
                {"name": "John Coltrane", "context": "saxophone"},
            ],
        })

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        # Only 1 LLM call.
        self.assertEqual(mock_provider.structured_extract.call_count, 1)
        call_kwargs = mock_provider.structured_extract.call_args[1]
        self.assertIn("Miles Davis", call_kwargs["user_content"])
        self.assertIn("John Coltrane", call_kwargs["user_content"])
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 3)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_null_types_skipped(self, mock_factory, _mock_mb):
        """Entity types with null value are skipped — no provider call needed."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {"musician": None, "musical_group": None}

        episode = self._create_episode(
            url="https://example.com/ep/res-5",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.count(), 0)
        self.assertEqual(EntityMention.objects.count(), 0)
        mock_factory.assert_not_called()

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_unmatched_canonical_name_already_exists(self, mock_factory, _mock_mb):
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
                    "matched_entity_id": None,
                    "musicbrainz_id": None,
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

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
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

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

    def test_wrong_status(self):
        """Not RESOLVING -> no-op."""
        from episodes.resolver import resolve_entities

        episode = self._create_episode(
            url="https://example.com/ep/res-7",
            status=Episode.Status.QUEUED,
        )

        resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.QUEUED)

    def test_nonexistent_episode(self):
        """No crash on nonexistent episode."""
        from episodes.resolver import resolve_entities

        resolve_entities(99999)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_provider_error(self, mock_factory, _mock_mb):
        """LLM exception -> FAILED."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        Entity.objects.create(entity_type=musician_type, name="Miles Davis")

        mock_provider = MagicMock()
        mock_provider.structured_extract.side_effect = Exception("API error")
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-8",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("API error", episode.error_message)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_idempotent_reprocessing(self, mock_factory, _mock_mb):
        """Running twice with full fixture doesn't create duplicate entities or mentions."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/res-9",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=self.SAMPLE_ENTITIES)

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        self.assertEqual(Entity.objects.count(), 59)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)
        mock_provider.structured_extract.assert_not_called()

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
                            "musicbrainz_id": None,
                        })
                    return {"matches": matches}
            return {"matches": []}

        mock_provider.structured_extract.side_effect = mock_structured_extract

        episode.status = Episode.Status.RESOLVING
        with patch("episodes.signals.DBOS"):
            episode.save(update_fields=["status", "updated_at"])
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        non_null_types = sum(1 for v in self.SAMPLE_ENTITIES.values() if v is not None)
        self.assertEqual(mock_provider.structured_extract.call_count, non_null_types)

        self.assertEqual(Entity.objects.count(), 59)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_unknown_entity_type_skipped(self, mock_factory, _mock_mb):
        """Entity types not in DB are skipped with a warning."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "nonexistent_type": [{"name": "Something", "context": "test"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-unknown",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.count(), 0)

    @patch("episodes.resolver.get_resolution_provider")
    def test_mb_candidates_used_in_resolution(self, mock_factory):
        """MB candidates are passed to the LLM and musicbrainz_id is saved."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type, name="Miles Davis"
        )

        mbid = "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                    "musicbrainz_id": mbid,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-mb",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        mb_candidates = {
            "Miles Davis": [
                _mb_candidate(mbid, name="Miles Davis", disambiguation="Jazz trumpeter"),
            ],
        }

        with patch(
            "episodes.resolver._fetch_musicbrainz_candidates",
            return_value=mb_candidates,
        ):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        existing.refresh_from_db()
        self.assertEqual(existing.musicbrainz_id, mbid)
        # foreground does NOT touch wikidata_id
        self.assertEqual(existing.wikidata_id, "")

        call_kwargs = mock_provider.structured_extract.call_args[1]
        self.assertIn(mbid, call_kwargs["system_prompt"])
        self.assertIn("Jazz trumpeter", call_kwargs["system_prompt"])

    @patch("episodes.resolver.get_resolution_provider")
    def test_mbid_match_existing_entity(self, mock_factory):
        """Entity with matching musicbrainz_id in DB is reused."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        mbid = "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"
        existing = Entity.objects.create(
            entity_type=musician_type, name="Miles Davis", musicbrainz_id=mbid
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "M. Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": None,
                    "musicbrainz_id": mbid,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [{"name": "M. Davis", "context": "trumpet"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-mb-match",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={}):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        self.assertEqual(Entity.objects.filter(entity_type=musician_type).count(), 1)
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)

    @patch("episodes.resolver.get_resolution_provider")
    def test_mb_new_entity_gets_mbid(self, mock_factory):
        """New entities with MB candidates get musicbrainz_id assigned via LLM."""
        from episodes.resolver import resolve_entities

        mbid = "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": None,
                    "musicbrainz_id": mbid,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-mb-new",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        mb_candidates = {
            "Miles Davis": [_mb_candidate(mbid, name="Miles Davis", type_="Person")],
        }

        with patch(
            "episodes.resolver._fetch_musicbrainz_candidates", return_value=mb_candidates
        ):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        entity = Entity.objects.get(name="Miles Davis")
        self.assertEqual(entity.musicbrainz_id, mbid)

    @patch("episodes.resolver.get_resolution_provider")
    def test_llm_omitted_name_fallback_existing_entities(self, mock_factory):
        """LLM omits a name when existing entities present — fallback creates it."""
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
                    "musicbrainz_id": None,
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

        with patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={}):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.filter(entity_type=musician_type).count(), 2)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 2)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_two_names_same_entity_same_chunk(self, mock_factory, _mock_mb):
        """Two extracted names resolve to the same entity in the same chunk — no duplicate mention."""
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
                    "musicbrainz_id": None,
                },
                {
                    "extracted_name": "Miles",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                    "musicbrainz_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

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

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.filter(entity_type=musician_type).count(), 1)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 1)
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_start_time_flows_to_mention(self, mock_factory, _mock_mb):
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

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.start_time, 5.0)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_missing_start_time_is_none(self, mock_factory, _mock_mb):
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-ts2",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        mention = EntityMention.objects.get(episode=episode)
        self.assertIsNone(mention.start_time)

    @patch("episodes.resolver.get_resolution_provider")
    def test_noisy_mbid_is_sanitized(self, mock_factory):
        """LLM returns malformed MBID — extracted UUID, no DB error."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        mbid = "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": None,
                    "musicbrainz_id": (
                        f"https://musicbrainz.org/artist/{mbid} (jazz trumpeter)"
                    ),
                },
            ],
        }
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-mbid-noisy",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        mb_candidates = {"Miles Davis": [_mb_candidate(mbid, name="Miles Davis")]}
        with patch(
            "episodes.resolver._fetch_musicbrainz_candidates", return_value=mb_candidates
        ):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        entity = Entity.objects.get(entity_type=musician_type, name="Miles Davis")
        self.assertEqual(entity.musicbrainz_id, mbid)

    @patch("episodes.resolver.get_resolution_provider")
    def test_existing_entity_gaining_mbid_is_enqueued_for_enrichment(self, mock_factory):
        """A pre-existing PENDING entity that gets an MBID this run must be
        enqueued for background Wikidata enrichment — otherwise it sits in
        PENDING forever unless someone manually backfills."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type, name="Miles Davis"
        )
        # Sanity: starts PENDING with no MBID, no Wikidata ID.
        self.assertEqual(existing.wikidata_status, Entity.WikidataStatus.PENDING)
        self.assertEqual(existing.musicbrainz_id, "")

        mbid = "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                    "musicbrainz_id": mbid,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/upgrade-existing",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json={
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        })

        with patch(
            "episodes.resolver._fetch_musicbrainz_candidates",
            return_value={"Miles Davis": [_mb_candidate(mbid, name="Miles Davis")]},
        ):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        existing.refresh_from_db()
        self.assertEqual(existing.musicbrainz_id, mbid)

        # The entity must have been enqueued for enrichment despite not
        # being newly created.
        self.assertTrue(self._mock_enqueue.called)
        enqueued_ids = self._mock_enqueue.call_args[0][0]
        self.assertIn(existing.pk, enqueued_ids)

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_existing_resolved_entity_not_enqueued(self, mock_factory, _mock_mb):
        """Entities that already have wikidata_id are never re-enqueued."""
        from episodes.resolver import resolve_entities

        musician_type = _get_entity_type("musician")
        existing = Entity.objects.create(
            entity_type=musician_type,
            name="Miles Davis",
            wikidata_id="Q93341",
            wikidata_status=Entity.WikidataStatus.RESOLVED,
        )

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Miles Davis",
                    "canonical_name": "Miles Davis",
                    "matched_entity_id": existing.pk,
                    "musicbrainz_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/already-enriched",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json={
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        })

        with patch("episodes.signals.DBOS"):
            resolve_entities(episode.pk)

        # Either not called at all (empty set short-circuits in
        # _enqueue_enrichment) OR called with an empty list.
        if self._mock_enqueue.called:
            self.assertEqual(self._mock_enqueue.call_args[0][0], [])

    @patch("episodes.resolver.get_resolution_provider")
    def test_safety_net_assigns_sole_mb_candidate_when_llm_omits_mbid(self, mock_factory):
        """If MB returns exactly one candidate with a matching name and the LLM
        forgets to include the MBID, the resolver still assigns it. Regression
        for the live-run case where 'Quintette du Hot Club de France' had a
        single perfect MB match (`ee55e4e8…`) but the LLM returned null."""
        from episodes.resolver import resolve_entities

        mbid = "ee55e4e8-807d-49b1-8470-d1c0898ed7cb"
        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Quintette du Hot Club de France",
                    "canonical_name": "Quintette du Hot Club de France",
                    "matched_entity_id": None,
                    "musicbrainz_id": None,  # LLM omitted it
                },
            ],
        }
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/safety-net",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json={
            "musical_group": [{"name": "Quintette du Hot Club de France", "context": "Django's group"}],
        })

        # Sole MB candidate with the same name.
        mb_candidates = {
            "Quintette du Hot Club de France": [
                _mb_candidate(mbid, name="Quintette du Hot Club de France", type_="Group"),
            ],
        }

        with patch(
            "episodes.resolver._fetch_musicbrainz_candidates",
            return_value=mb_candidates,
        ):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        e = Entity.objects.get(name="Quintette du Hot Club de France")
        self.assertEqual(e.musicbrainz_id, mbid)

    @patch("episodes.resolver.get_resolution_provider")
    def test_safety_net_skipped_when_llm_changes_canonical_name(self, mock_factory):
        """If the LLM returns a different canonical_name, that's a signal it
        identified a different entity than the MB candidate suggests — do not
        auto-assign the MBID."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "John Smith",
                    "canonical_name": "Other John",  # LLM rebadged the entity
                    "matched_entity_id": None,
                    "musicbrainz_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/safety-net-skip",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json={
            "musician": [{"name": "John Smith", "context": "vocalist"}],
        })

        mb_candidates = {
            "John Smith": [_mb_candidate("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", name="John Smith")],
        }

        with patch(
            "episodes.resolver._fetch_musicbrainz_candidates", return_value=mb_candidates
        ):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        # Entity created with the LLM's canonical_name, no MBID.
        e = Entity.objects.get(name="Other John")
        self.assertEqual(e.musicbrainz_id, "")

    @patch("episodes.resolver.get_resolution_provider")
    def test_safety_net_skipped_when_multiple_mb_candidates(self, mock_factory):
        """When MB returns multiple candidates, the LLM is the only arbiter.
        If the LLM returns null, do NOT pick one arbitrarily."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_provider.structured_extract.return_value = {
            "matches": [
                {
                    "extracted_name": "Django Reinhardt",
                    "canonical_name": "Django Reinhardt",
                    "matched_entity_id": None,
                    "musicbrainz_id": None,
                },
            ],
        }
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/safety-net-multi",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json={
            "musician": [{"name": "Django Reinhardt", "context": "guitar"}],
        })

        mb_candidates = {
            "Django Reinhardt": [
                _mb_candidate("650bf385-6f6d-4992-a3b9-779d144920a4", name="Django Reinhardt", disambiguation="French jazz guitarist"),
                _mb_candidate("96f23107-8200-4618-88c1-501f1692d492", name="Django Reinhardt", disambiguation="German singer"),
            ],
        }

        with patch(
            "episodes.resolver._fetch_musicbrainz_candidates", return_value=mb_candidates
        ):
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)

        e = Entity.objects.get(name="Django Reinhardt")
        self.assertEqual(e.musicbrainz_id, "")

    @patch("episodes.resolver._fetch_musicbrainz_candidates", return_value={})
    @patch("episodes.resolver.get_resolution_provider")
    def test_foreground_does_not_call_wikidata(self, mock_factory, _mock_mb):
        """Foreground resolution must never hit the Wikidata API."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        entities_json = {
            "musician": [{"name": "Miles Davis", "context": "trumpet"}],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-no-wd",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0, entities_json=entities_json)

        with patch("episodes.wikidata.find_candidates") as mock_wd:
            with patch("episodes.signals.DBOS"):
                resolve_entities(episode.pk)
            mock_wd.assert_not_called()


class SanitizeMbidTests(TestCase):
    """Unit tests for _sanitize_mbid."""

    def test_bare_mbid(self):
        from episodes.resolver import _sanitize_mbid
        self.assertEqual(
            _sanitize_mbid("11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"),
            "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3",
        )

    def test_full_url(self):
        from episodes.resolver import _sanitize_mbid
        self.assertEqual(
            _sanitize_mbid(
                "https://musicbrainz.org/artist/11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3"
            ),
            "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3",
        )

    def test_uppercase_normalized(self):
        from episodes.resolver import _sanitize_mbid
        self.assertEqual(
            _sanitize_mbid("11D7CBA4-0BCD-4B94-A30A-C1D5E80F86A3"),
            "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3",
        )

    def test_trailing_garbage(self):
        from episodes.resolver import _sanitize_mbid
        self.assertEqual(
            _sanitize_mbid(
                "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3 explanation: this is Miles"
            ),
            "11d7cba4-0bcd-4b94-a30a-c1d5e80f86a3",
        )

    def test_empty_string(self):
        from episodes.resolver import _sanitize_mbid
        self.assertEqual(_sanitize_mbid(""), "")

    def test_no_match(self):
        from episodes.resolver import _sanitize_mbid
        self.assertEqual(_sanitize_mbid("not a uuid"), "")
