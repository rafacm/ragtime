from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from django.test import TestCase, override_settings

from episodes.models import Entity, EntityType, Episode


_YAML_PATH = Path(__file__).resolve().parent.parent / "initial_entity_types.yaml"


def _seed_entity_types():
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


class LinkingStatusModelTests(TestCase):
    """Tests for the Entity.linking_status field."""

    def setUp(self):
        _seed_entity_types()

    def _create_entity(self, name, type_key="musician", **kwargs):
        et = EntityType.objects.get(key=type_key)
        return Entity.objects.create(entity_type=et, name=name, **kwargs)

    def test_default_linking_status_is_pending(self):
        entity = self._create_entity("Miles Davis")
        self.assertEqual(entity.linking_status, Entity.LinkingStatus.PENDING)

    def test_linked_status_with_wikidata_id(self):
        entity = self._create_entity(
            "Miles Davis",
            wikidata_id="Q93341",
            linking_status=Entity.LinkingStatus.LINKED,
        )
        self.assertEqual(entity.linking_status, Entity.LinkingStatus.LINKED)
        self.assertEqual(entity.wikidata_id, "Q93341")

    def test_skipped_status(self):
        entity = self._create_entity(
            "1959",
            type_key="year",
            linking_status=Entity.LinkingStatus.SKIPPED,
        )
        self.assertEqual(entity.linking_status, Entity.LinkingStatus.SKIPPED)

    def test_failed_status(self):
        entity = self._create_entity(
            "Unknown Artist",
            linking_status=Entity.LinkingStatus.FAILED,
        )
        self.assertEqual(entity.linking_status, Entity.LinkingStatus.FAILED)


@override_settings(
    RAGTIME_LINKING_AGENT_ENABLED=True,
    RAGTIME_LINKING_AGENT_MODEL="openai:gpt-4.1-mini",
    RAGTIME_LINKING_AGENT_API_KEY="test-key",
    RAGTIME_LINKING_AGENT_BATCH_SIZE=10,
)
class RunLinkingAgentTests(TestCase):
    """Tests for the run_linking_agent entry point."""

    def setUp(self):
        _seed_entity_types()

    def _create_entity(self, name, type_key="musician", **kwargs):
        et = EntityType.objects.get(key=type_key)
        return Entity.objects.create(entity_type=et, name=name, **kwargs)

    @override_settings(RAGTIME_LINKING_AGENT_ENABLED=False)
    def test_disabled_agent_is_noop(self):
        """When agent is disabled, run_linking_agent does nothing."""
        from episodes.agents.linker import run_linking_agent

        self._create_entity("Miles Davis")
        run_linking_agent()

        entity = Entity.objects.get(name="Miles Davis")
        self.assertEqual(entity.linking_status, Entity.LinkingStatus.PENDING)

    def test_no_pending_entities_is_noop(self):
        """No pending entities — nothing to do."""
        from episodes.agents.linker import run_linking_agent

        self._create_entity(
            "Miles Davis",
            wikidata_id="Q93341",
            linking_status=Entity.LinkingStatus.LINKED,
        )

        with patch("episodes.agents.linker._run_linking_agent_async") as mock_run:
            run_linking_agent()
            mock_run.assert_not_called()

    def test_entities_with_no_type_qid_are_skipped(self):
        """Entity types without a Wikidata class Q-ID are auto-skipped."""
        from episodes.agents.linker import run_linking_agent

        # Create an entity type with no wikidata_id
        et = EntityType.objects.create(
            key="test_notype", name="Test No Type", wikidata_id="",
            description="test", examples=[],
        )
        Entity.objects.create(entity_type=et, name="Something")

        with patch("episodes.agents.linker._run_linking_agent_async") as mock_run:
            run_linking_agent()

        entity = Entity.objects.get(name="Something")
        self.assertEqual(entity.linking_status, Entity.LinkingStatus.SKIPPED)

    def test_already_linked_not_reprocessed(self):
        """Already linked entities are not picked up by the agent."""
        from episodes.agents.linker import run_linking_agent

        self._create_entity(
            "Miles Davis",
            wikidata_id="Q93341",
            linking_status=Entity.LinkingStatus.LINKED,
        )

        with patch("episodes.agents.linker._run_linking_agent_async") as mock_run:
            run_linking_agent()
            mock_run.assert_not_called()


class HandleResolveCompletedTests(TestCase):
    """Tests for the signal handler that triggers the linking agent."""

    def setUp(self):
        _seed_entity_types()

    def _create_entity(self, name, type_key="musician", **kwargs):
        et = EntityType.objects.get(key=type_key)
        return Entity.objects.create(entity_type=et, name=name, **kwargs)

    @override_settings(RAGTIME_LINKING_AGENT_ENABLED=True)
    @patch("episodes.agents.linker.async_task")
    def test_triggers_on_resolving_complete(self, mock_async):
        """Linking agent is queued when resolve step completes with pending entities."""
        from episodes.agents.linker import handle_resolve_completed

        self._create_entity("Miles Davis")

        event = MagicMock()
        event.step_name = Episode.Status.RESOLVING

        handle_resolve_completed(sender=None, event=event)

        mock_async.assert_called_once_with(
            "episodes.agents.linker.run_linking_agent"
        )

    @override_settings(RAGTIME_LINKING_AGENT_ENABLED=True)
    @patch("episodes.agents.linker.async_task")
    def test_no_trigger_for_other_steps(self, mock_async):
        """Signal handler ignores non-RESOLVING steps."""
        from episodes.agents.linker import handle_resolve_completed

        self._create_entity("Miles Davis")

        event = MagicMock()
        event.step_name = Episode.Status.EXTRACTING

        handle_resolve_completed(sender=None, event=event)

        mock_async.assert_not_called()

    @override_settings(RAGTIME_LINKING_AGENT_ENABLED=True)
    @patch("episodes.agents.linker.async_task")
    def test_no_trigger_when_no_pending(self, mock_async):
        """No queued task when all entities are already linked."""
        from episodes.agents.linker import handle_resolve_completed

        self._create_entity(
            "Miles Davis",
            wikidata_id="Q93341",
            linking_status=Entity.LinkingStatus.LINKED,
        )

        event = MagicMock()
        event.step_name = Episode.Status.RESOLVING

        handle_resolve_completed(sender=None, event=event)

        mock_async.assert_not_called()

    @override_settings(RAGTIME_LINKING_AGENT_ENABLED=False)
    @patch("episodes.agents.linker.async_task")
    def test_no_trigger_when_disabled(self, mock_async):
        """No queued task when linking agent is disabled."""
        from episodes.agents.linker import handle_resolve_completed

        self._create_entity("Miles Davis")

        event = MagicMock()
        event.step_name = Episode.Status.RESOLVING

        handle_resolve_completed(sender=None, event=event)

        mock_async.assert_not_called()
