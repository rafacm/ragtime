import logging

from django.db import transaction

from .models import Entity, EntityMention, Episode
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_resolution_provider

logger = logging.getLogger(__name__)

RESOLUTION_RESPONSE_SCHEMA = {
    "name": "resolution_result",
    "strict": True,
    "schema": {
        "type": "object",
        "properties": {
            "matches": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "extracted_name": {"type": "string"},
                        "canonical_name": {"type": "string"},
                        "matched_entity_id": {"type": ["integer", "null"]},
                    },
                    "required": [
                        "extracted_name",
                        "canonical_name",
                        "matched_entity_id",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["matches"],
        "additionalProperties": False,
    },
}


def _build_system_prompt(entity_type, existing_entities):
    candidates = "\n".join(
        f"- ID {e.pk}: {e.name}" for e in existing_entities
    )
    return (
        "You are an entity resolution expert specializing in jazz music.\n"
        f"You are resolving entities of type '{entity_type}'.\n\n"
        "Given a list of extracted entity names from a podcast episode and a list of "
        "existing canonical entities in the database, determine which extracted names "
        "match existing entities and which are new.\n\n"
        "Rules:\n"
        "- Consider spelling variants, language differences (German/English/etc.), "
        "abbreviations, and alternate names\n"
        "- Only match entities that clearly refer to the same real-world thing\n"
        "- For each extracted entity, return either the matched existing entity ID "
        "or null if it's new\n"
        "- For new entities, return the best canonical name (most commonly recognized "
        "form, e.g., 'Saxophone' over 'Saxophon')\n"
        "- For matched entities, canonical_name is ignored (the existing name is kept)\n\n"
        "Existing entities in the database:\n"
        f"{candidates}"
    )


def resolve_entities(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.RESOLVING:
        logger.warning(
            "Episode %s has status '%s', expected 'resolving'",
            episode_id,
            episode.status,
        )
        return

    start_step(episode, Episode.Status.RESOLVING)

    if not episode.entities_json:
        episode.error_message = "No entities to resolve"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.RESOLVING, "No entities to resolve")
        return

    try:
        provider = get_resolution_provider()

        with transaction.atomic():
            # Delete existing mentions for idempotent reprocessing
            EntityMention.objects.filter(episode=episode).delete()

            for entity_type, entities in episode.entities_json.items():
                if entities is None:
                    continue

                existing = list(
                    Entity.objects.filter(entity_type=entity_type)
                )

                if not existing:
                    # No existing entities — create all as new (no LLM call)
                    for extracted in entities:
                        entity = Entity.objects.create(
                            entity_type=entity_type,
                            name=extracted["name"],
                        )
                        EntityMention.objects.create(
                            entity=entity,
                            episode=episode,
                            context=extracted.get("context") or "",
                        )
                else:
                    # LLM resolution against existing entities
                    extracted_names = ", ".join(
                        e["name"] for e in entities
                    )
                    system_prompt = _build_system_prompt(
                        entity_type, existing
                    )
                    result = provider.structured_extract(
                        system_prompt=system_prompt,
                        user_content=f"Extracted entities to resolve: {extracted_names}",
                        response_schema=RESOLUTION_RESPONSE_SCHEMA,
                    )

                    # Build lookup for context by extracted name
                    context_by_name = {
                        e["name"]: e.get("context") or ""
                        for e in entities
                    }

                    existing_by_id = {e.pk: e for e in existing}

                    for match in result["matches"]:
                        matched_id = match["matched_entity_id"]
                        context = context_by_name.get(
                            match["extracted_name"], ""
                        )

                        if matched_id is not None and matched_id in existing_by_id:
                            entity = existing_by_id[matched_id]
                        else:
                            entity, _created = Entity.objects.get_or_create(
                                entity_type=entity_type,
                                name=match["canonical_name"],
                            )

                        EntityMention.objects.create(
                            entity=entity,
                            episode=episode,
                            context=context,
                        )

        complete_step(episode, Episode.Status.RESOLVING)
        episode.status = Episode.Status.EMBEDDING
        episode.save(update_fields=["status", "updated_at"])
    except Exception as exc:
        logger.exception("Failed to resolve entities for episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.RESOLVING, str(exc))
