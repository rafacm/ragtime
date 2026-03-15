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
                        "wikidata_id": {"type": ["string", "null"]},
                    },
                    "required": [
                        "extracted_name",
                        "canonical_name",
                        "matched_entity_id",
                        "wikidata_id",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["matches"],
        "additionalProperties": False,
    },
}


def _fetch_wikidata_candidates(names, entity_type):
    """Fetch Wikidata candidates for a list of entity names.

    Returns {name: [{qid, label, description}, ...]} or empty dict on failure.
    """
    try:
        from .wikidata import find_candidates
    except Exception:
        logger.warning("Could not import wikidata module — skipping candidate lookup")
        return {}

    entity_type_qid = entity_type.wikidata_id
    if not entity_type_qid:
        return {}

    candidates_by_name = {}
    for name in names:
        try:
            candidates = find_candidates(name, entity_type_qid)
            if candidates:
                candidates_by_name[name] = candidates
        except Exception:
            logger.warning(
                "Wikidata lookup failed for '%s' — continuing without candidates",
                name,
            )
    return candidates_by_name


def _build_system_prompt(entity_type_name, existing_entities, wikidata_candidates=None):
    db_candidates = "\n".join(
        f"- ID {e.pk}: {e.name}" + (f" [wikidata:{e.wikidata_id}]" if e.wikidata_id else "")
        for e in existing_entities
    )

    wikidata_section = ""
    if wikidata_candidates:
        lines = []
        for name, candidates in wikidata_candidates.items():
            candidate_strs = ", ".join(
                f"{c['qid']} ({c['label']}: {c['description']})" if c['description']
                else f"{c['qid']} ({c['label']})"
                for c in candidates
            )
            lines.append(f"- \"{name}\": {candidate_strs}")
        wikidata_section = (
            "\n\nWikidata candidates (pick the best match or return null for wikidata_id):\n"
            + "\n".join(lines)
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
        "- For matched entities, canonical_name is ignored (the existing name is kept)\n"
        "- For wikidata_id: pick the Q-ID from the Wikidata candidates that best matches "
        "the entity, or return null if none match or no candidates are available\n\n"
        "Existing entities in the database:\n"
        f"{db_candidates}"
        f"{wikidata_section}"
    )


def _aggregate_entities_from_chunks(chunks):
    """Aggregate entities across chunks into {type_key: {name: [(chunk, context), ...]}}.

    De-duplicates by (name, chunk) — keeps the first context seen per chunk.
    """
    aggregated = defaultdict(lambda: defaultdict(list))
    for chunk in chunks:
        if not chunk.entities_json:
            continue
        for type_key, entities in chunk.entities_json.items():
            if entities is None:
                continue
            seen_chunks = set()
            for entity in entities:
                name = entity["name"]
                if (name, chunk.pk) in seen_chunks:
                    continue
                seen_chunks.add((name, chunk.pk))
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
    aggregated = _aggregate_entities_from_chunks(chunks)

    if not aggregated:
        EntityMention.objects.filter(episode=episode).delete()
        complete_step(episode, Episode.Status.RESOLVING)
        episode.status = Episode.Status.EMBEDDING
        episode.save(update_fields=["status", "updated_at"])
        return

    try:
        provider = get_resolution_provider()

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
                    # No existing entities — fetch Wikidata candidates for new entities
                    wikidata_candidates = _fetch_wikidata_candidates(
                        unique_names, entity_type
                    )

                    if wikidata_candidates:
                        # Use LLM to pick best Wikidata Q-IDs for new entities
                        system_prompt = _build_system_prompt(
                            entity_type_key, [], wikidata_candidates
                        )
                        extracted_names = ", ".join(unique_names)
                        result = provider.structured_extract(
                            system_prompt=system_prompt,
                            user_content=f"Extracted entities to resolve: {extracted_names}",
                            response_schema=RESOLUTION_RESPONSE_SCHEMA,
                        )

                        all_mentions = []
                        for match in result["matches"]:
                            extracted_name = match["extracted_name"]
                            wikidata_id = match.get("wikidata_id") or ""
                            canonical_name = match.get("canonical_name") or extracted_name

                            entity, _created = Entity.objects.get_or_create(
                                entity_type=entity_type,
                                name=canonical_name,
                                defaults={"wikidata_id": wikidata_id},
                            )
                            if not _created and wikidata_id and not entity.wikidata_id:
                                entity.wikidata_id = wikidata_id
                                entity.save(update_fields=["wikidata_id", "updated_at"])

                            for chunk, context in names_dict.get(extracted_name, []):
                                all_mentions.append(EntityMention(
                                    entity=entity,
                                    episode=episode,
                                    chunk=chunk,
                                    context=context,
                                ))
                        EntityMention.objects.bulk_create(all_mentions)
                    else:
                        # No Wikidata candidates — create all as new (no LLM call)
                        all_mentions = []
                        for name in unique_names:
                            entity = Entity.objects.create(
                                entity_type=entity_type,
                                name=name,
                            )
                            for chunk, context in names_dict[name]:
                                all_mentions.append(EntityMention(
                                    entity=entity,
                                    episode=episode,
                                    chunk=chunk,
                                    context=context,
                                ))
                        EntityMention.objects.bulk_create(all_mentions)
                else:
                    # Fetch Wikidata candidates for resolution
                    wikidata_candidates = _fetch_wikidata_candidates(
                        unique_names, entity_type
                    )

                    # LLM resolution against existing entities
                    extracted_names = ", ".join(unique_names)
                    system_prompt = _build_system_prompt(
                        entity_type_key, existing, wikidata_candidates
                    )
                    result = provider.structured_extract(
                        system_prompt=system_prompt,
                        user_content=f"Extracted entities to resolve: {extracted_names}",
                        response_schema=RESOLUTION_RESPONSE_SCHEMA,
                    )

                    existing_by_id = {e.pk: e for e in existing}
                    all_mentions = []

                    for match in result["matches"]:
                        matched_id = match["matched_entity_id"]
                        extracted_name = match["extracted_name"]
                        wikidata_id = match.get("wikidata_id") or ""

                        if wikidata_id:
                            # Try to find existing entity by wikidata_id
                            wikidata_match = Entity.objects.filter(
                                entity_type=entity_type,
                                wikidata_id=wikidata_id,
                            ).first()
                            if wikidata_match:
                                entity = wikidata_match
                            elif matched_id is not None and matched_id in existing_by_id:
                                entity = existing_by_id[matched_id]
                                if not entity.wikidata_id:
                                    entity.wikidata_id = wikidata_id
                                    entity.save(update_fields=["wikidata_id", "updated_at"])
                            else:
                                entity, _created = Entity.objects.get_or_create(
                                    entity_type=entity_type,
                                    name=match["canonical_name"],
                                    defaults={"wikidata_id": wikidata_id},
                                )
                                if not _created and not entity.wikidata_id:
                                    entity.wikidata_id = wikidata_id
                                    entity.save(update_fields=["wikidata_id", "updated_at"])
                        elif matched_id is not None and matched_id in existing_by_id:
                            entity = existing_by_id[matched_id]
                        else:
                            entity, _created = Entity.objects.get_or_create(
                                entity_type=entity_type,
                                name=match["canonical_name"],
                            )

                        # Collect mentions for every (chunk, context) where this name appeared
                        for chunk, context in names_dict.get(extracted_name, []):
                            all_mentions.append(EntityMention(
                                entity=entity,
                                episode=episode,
                                chunk=chunk,
                                context=context,
                            ))
                    EntityMention.objects.bulk_create(all_mentions)

        complete_step(episode, Episode.Status.RESOLVING)
        episode.status = Episode.Status.EMBEDDING
        episode.save(update_fields=["status", "updated_at"])
    except Exception as exc:
        logger.exception("Failed to resolve entities for episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.RESOLVING, str(exc))
