import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from episodes.models import Entity, EntityMention, Episode

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name):
    with open(_FIXTURES_DIR / name) as f:
        return json.load(f)


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

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.async_task"):
            return Episode.objects.create(**kwargs)

    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_new_entities(self, mock_factory):
        """No existing DB entities — all created as new, no LLM call."""
        from episodes.resolver import resolve_entities

        mock_provider = MagicMock()
        mock_factory.return_value = mock_provider

        episode = self._create_episode(
            url="https://example.com/ep/res-1",
            status=Episode.Status.RESOLVING,
            entities_json=self.SAMPLE_ENTITIES,
        )

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # No LLM call needed when no existing entities
        mock_provider.structured_extract.assert_not_called()

        # 59 entities from fixture (3 null types: album, recording_session, label)
        self.assertEqual(Entity.objects.count(), 59)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)

    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_matches_existing(self, mock_factory):
        """LLM matches extracted entity to existing — no duplicate created."""
        from episodes.resolver import resolve_entities

        # Pre-create an existing entity
        existing = Entity.objects.create(
            entity_type="artist", name="Miles Davis"
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
            "artist": [
                {"name": "Miles Davis", "context": "trumpet player"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-2",
            status=Episode.Status.RESOLVING,
            entities_json=entities_json,
        )

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # Still only 1 artist entity
        self.assertEqual(
            Entity.objects.filter(entity_type="artist").count(), 1
        )
        # But a mention was created
        mention = EntityMention.objects.get(episode=episode)
        self.assertEqual(mention.entity, existing)
        self.assertEqual(mention.context, "trumpet player")

    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_mixed(self, mock_factory):
        """Some matches, some new."""
        from episodes.resolver import resolve_entities

        existing = Entity.objects.create(
            entity_type="artist", name="Miles Davis"
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
            "artist": [
                {"name": "Miles Davis", "context": "trumpet"},
                {"name": "John Coltrane", "context": "saxophone"},
            ],
        }

        episode = self._create_episode(
            url="https://example.com/ep/res-3",
            status=Episode.Status.RESOLVING,
            entities_json=entities_json,
        )

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)

        # 2 artist entities: existing Miles + new Coltrane
        self.assertEqual(
            Entity.objects.filter(entity_type="artist").count(), 2
        )
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 2)

    @patch("episodes.resolver.get_resolution_provider")
    def test_resolve_canonical_name(self, mock_factory):
        """LLM returns canonical name different from extracted (e.g., Saxophon → Saxophone)."""
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
            entities_json=entities_json,
        )

        # First episode — no existing entities, so created directly with extracted name
        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        entity = Entity.objects.get(entity_type="instrument")
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
            entities_json={
                "instrument": [
                    {"name": "Saxophone", "context": "English spelling"},
                ],
            },
        )

        with patch("episodes.signals.async_task"):
            resolve_entities(episode2.pk)

        # Still only 1 instrument entity (matched)
        self.assertEqual(
            Entity.objects.filter(entity_type="instrument").count(), 1
        )
        # 2 mentions across 2 episodes
        self.assertEqual(EntityMention.objects.filter(entity=entity).count(), 2)

    @patch("episodes.resolver.get_resolution_provider")
    def test_null_types_skipped(self, mock_factory):
        """Entity types with null value are skipped."""
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
            entities_json=entities_json,
        )

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EMBEDDING)
        self.assertEqual(Entity.objects.count(), 0)
        self.assertEqual(EntityMention.objects.count(), 0)

    def test_missing_entities_json(self):
        """Null entities_json → FAILED."""
        from episodes.resolver import resolve_entities

        episode = self._create_episode(
            url="https://example.com/ep/res-6",
            status=Episode.Status.RESOLVING,
            entities_json=None,
        )

        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("No entities", episode.error_message)

    def test_wrong_status(self):
        """Not RESOLVING → no-op."""
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
        """LLM exception → FAILED."""
        from episodes.resolver import resolve_entities

        # Pre-create an existing entity so LLM call happens
        Entity.objects.create(entity_type="artist", name="Miles Davis")

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
            entities_json=entities_json,
        )

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
            entities_json=self.SAMPLE_ENTITIES,
        )

        # First run — no existing entities, creates all 59 as new (no LLM call)
        with patch("episodes.signals.async_task"):
            resolve_entities(episode.pk)

        self.assertEqual(Entity.objects.count(), 59)
        self.assertEqual(EntityMention.objects.filter(episode=episode).count(), 59)
        mock_provider.structured_extract.assert_not_called()

        # Build mock responses for second run: every entity matches its existing record
        def mock_structured_extract(system_prompt, user_content, response_schema):
            # Parse entity type from system prompt
            for entity_type, entities in self.SAMPLE_ENTITIES.items():
                if entities is None:
                    continue
                if f"type '{entity_type}'" in system_prompt:
                    existing = Entity.objects.filter(entity_type=entity_type)
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
