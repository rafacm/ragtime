import logging
from collections import defaultdict

from django.db import transaction

from .models import Chunk, Entity, EntityMention, EntityType, Episode
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


def _build_system_prompt(entity_type_name, existing_entities):
    candidates = "\n".join(
        f"- ID {e.pk}: {e.name}" for e in existing_entities
    )
    return (
        "You are an entity resolution expert specializing in jazz music.\n"
        f"You are resolving entities of type '{entity_type_name}'.\n\n"
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


def _aggregate_entities_from_chunks(chunks):
    """Aggregate entities across chunks into {type_key: {name: [(chunk, context), ...]}}."""
    aggregated = defaultdict(lambda: defaultdict(list))
    for chunk in chunks:
        if not chunk.entities_json:
            continue
        for type_key, entities in chunk.entities_json.items():
            if entities is None:
                continue
            for entity in entities:
                name = entity["name"]
                context = entity.get("context") or ""
                aggregated[type_key][name].append((chunk, context))
    return aggregated


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

    chunks = list(episode.chunks.order_by("index"))
    has_any_entities = any(chunk.entities_json for chunk in chunks)

    if not chunks or not has_any_entities:
        complete_step(episode, Episode.Status.RESOLVING)
        episode.status = Episode.Status.EMBEDDING
        episode.save(update_fields=["status", "updated_at"])
        return

    try:
        provider = get_resolution_provider()
        aggregated = _aggregate_entities_from_chunks(chunks)

        with transaction.atomic():
            # Delete existing mentions for idempotent reprocessing
            EntityMention.objects.filter(episode=episode).delete()

            for entity_type_key, names_dict in aggregated.items():
                try:
                    entity_type = EntityType.objects.get(key=entity_type_key)
                except EntityType.DoesNotExist:
                    logger.warning(
                        "Unknown entity type '%s' in episode %s — skipping",
                        entity_type_key,
                        episode_id,
                    )
                    continue

                unique_names = list(names_dict.keys())
                existing = list(
                    Entity.objects.filter(entity_type=entity_type)
                )

                if not existing:
                    # No existing entities — create all as new (no LLM call)
                    for name in unique_names:
                        entity = Entity.objects.create(
                            entity_type=entity_type,
                            name=name,
                        )
                        mentions = [
                            EntityMention(
                                entity=entity,
                                episode=episode,
                                chunk=chunk,
                                context=context,
                            )
                            for chunk, context in names_dict[name]
                        ]
                        EntityMention.objects.bulk_create(
                            mentions, ignore_conflicts=True
                        )
                else:
                    # LLM resolution against existing entities
                    extracted_names = ", ".join(unique_names)
                    system_prompt = _build_system_prompt(
                        entity_type_key, existing
                    )
                    result = provider.structured_extract(
                        system_prompt=system_prompt,
                        user_content=f"Extracted entities to resolve: {extracted_names}",
                        response_schema=RESOLUTION_RESPONSE_SCHEMA,
                    )

                    existing_by_id = {e.pk: e for e in existing}

                    for match in result["matches"]:
                        matched_id = match["matched_entity_id"]
                        extracted_name = match["extracted_name"]

                        if matched_id is not None and matched_id in existing_by_id:
                            entity = existing_by_id[matched_id]
                        else:
                            entity, _created = Entity.objects.get_or_create(
                                entity_type=entity_type,
                                name=match["canonical_name"],
                            )

                        # Create mentions for every (chunk, context) where this name appeared
                        chunk_contexts = names_dict.get(extracted_name, [])
                        mentions = [
                            EntityMention(
                                entity=entity,
                                episode=episode,
                                chunk=chunk,
                                context=context,
                            )
                            for chunk, context in chunk_contexts
                        ]
                        EntityMention.objects.bulk_create(
                            mentions, ignore_conflicts=True
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
