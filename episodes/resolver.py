"""Foreground entity resolution — MusicBrainz-first.

Replaces the pre-MusicBrainz flow that called the Wikidata API for every
extracted entity (rate-limited globally to 5 req/s, slow). Now:

* Candidates come from the local MusicBrainz database (sub-millisecond,
  parallel-safe across episodes).
* Resolution still uses the LLM for fuzzy matching against existing DB
  entities and for canonical-name decisions.
* Wikidata enrichment is enqueued for new entities and runs in the
  background (see ``episodes/enrichment.py``).

Race-safety: ``Entity.objects.create`` is replaced with ``get_or_create``
everywhere, and a transaction-scoped Postgres advisory lock per
``(entity_type, name)`` serializes parallel resolvers' decisions on the
same name.
"""

import logging
import re
from collections import defaultdict

from django.db import IntegrityError, connection, transaction

from .models import Chunk, Entity, EntityMention, EntityType, Episode
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_resolution_provider
from .telemetry import trace_step

logger = logging.getLogger(__name__)

_MBID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


def _sanitize_mbid(value: str) -> str:
    """Extract a UUID-formatted MBID from a possibly-noisy LLM response."""
    if not value:
        return ""
    m = _MBID_RE.search(value)
    return m.group(0).lower() if m else ""


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
                        "musicbrainz_id": {"type": ["string", "null"]},
                    },
                    "required": [
                        "extracted_name",
                        "canonical_name",
                        "matched_entity_id",
                        "musicbrainz_id",
                    ],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["matches"],
        "additionalProperties": False,
    },
}


def _fetch_musicbrainz_candidates(names, entity_type):
    """Return ``{name: [Candidate, ...]}`` for MB-eligible types, ``{}`` otherwise."""
    if not entity_type.musicbrainz_table:
        return {}
    from . import musicbrainz

    candidates_by_name: dict[str, list] = {}
    for name in names:
        candidates = musicbrainz.find_candidates(name, entity_type)
        if candidates:
            candidates_by_name[name] = candidates
    return candidates_by_name


def _build_system_prompt(entity_type_name, existing_entities, mb_candidates=None):
    db_candidates = "\n".join(
        f"- ID {e.pk}: {e.name}"
        + (f" [mb:{e.musicbrainz_id}]" if e.musicbrainz_id else "")
        for e in existing_entities
    )

    mb_section = ""
    if mb_candidates:
        lines = []
        for name, candidates in mb_candidates.items():
            cand_strs = ", ".join(
                f"{c.mbid} ({c.name}: {c.disambiguation or c.type})"
                if (c.disambiguation or c.type)
                else f"{c.mbid} ({c.name})"
                for c in candidates
            )
            lines.append(f'- "{name}": {cand_strs}')
        mb_section = (
            "\n\nMusicBrainz candidates (pick the best match by mbid, or return null):\n"
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
        "- For musicbrainz_id: pick the MBID (UUID) from the MusicBrainz candidates that "
        "best matches the entity, or return null if none match or no candidates are "
        "available\n\n"
        "Existing entities in the database:\n"
        f"{db_candidates}"
        f"{mb_section}"
    )


def _aggregate_entities_from_chunks(chunks):
    """Aggregate to ``{type_key: {name: [(chunk, context, start_time), ...]}}``."""
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
                start_time = entity.get("start_time")
                aggregated[type_key][name].append((chunk, context, start_time))
    return aggregated


def _collect_mentions(name, entity, names_dict, episode, seen):
    mentions = []
    for chunk, context, start_time in names_dict.get(name, []):
        key = (entity.pk, chunk.pk)
        if key in seen:
            continue
        seen.add(key)
        mentions.append(
            EntityMention(
                entity=entity,
                episode=episode,
                chunk=chunk,
                context=context,
                start_time=start_time,
            )
        )
    return mentions


def _acquire_name_locks(entity_type_id: int, names) -> None:
    """Take Postgres txn-scoped advisory locks on each (entity_type, name) pair.

    Names are sorted to enforce a global lock-acquisition order, eliminating
    deadlock risk between resolvers that share names. Locks release at txn end.
    """
    if not names:
        return
    keys = [f"{entity_type_id}:{n}" for n in sorted(names)]
    with connection.cursor() as cur:
        for key in keys:
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (key,),
            )


def _get_or_create_entity(entity_type, name, mbid: str = ""):
    """Race-safe ``get_or_create`` with ``IntegrityError`` fallback.

    The advisory lock above usually serializes us; this fallback covers
    the rare cases where the lock isn't held (tests on a fresh DB without
    advisory_lock support, hash collisions).
    """
    defaults = {"musicbrainz_id": mbid} if mbid else {}
    try:
        entity, created = Entity.objects.get_or_create(
            entity_type=entity_type, name=name, defaults=defaults
        )
    except IntegrityError:
        entity = Entity.objects.get(entity_type=entity_type, name=name)
        created = False
    if mbid and not entity.musicbrainz_id:
        entity.musicbrainz_id = mbid
        entity.save(update_fields=["musicbrainz_id", "updated_at"])
    return entity, created


def _enqueue_enrichment(entity_ids) -> None:
    if not entity_ids:
        return
    try:
        from .enrichment import enqueue_entities

        enqueue_entities(entity_ids)
    except Exception:
        logger.exception("Failed to enqueue Wikidata enrichment")


@trace_step("resolve_entities")
def resolve_entities(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.RESOLVING:
        logger.warning(
            "Episode %s has status '%s', expected 'resolving'",
            episode_id, episode.status,
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

    # Entities to enqueue for background Wikidata enrichment after the
    # transaction commits. Includes:
    #   - newly-created Entity rows
    #   - pre-existing Entity rows touched by this resolve that are still
    #     wikidata_status=PENDING. Without this, an existing entity can
    #     gain its musicbrainz_id from the LLM but never reach the
    #     enrichment queue, leaving it pending until someone manually runs
    #     `manage.py enrich_entities`.
    entities_to_enrich: set[int] = set()

    from .enrichment import MAX_ATTEMPTS

    def _maybe_enqueue(entity: Entity) -> None:
        if (
            not entity.wikidata_id
            and entity.wikidata_status == Entity.WikidataStatus.PENDING
            and entity.wikidata_attempts < MAX_ATTEMPTS
        ):
            entities_to_enrich.add(entity.pk)

    try:
        provider = get_resolution_provider()

        with transaction.atomic():
            EntityMention.objects.filter(episode=episode).delete()

            for entity_type_key, names_dict in aggregated.items():
                try:
                    entity_type = EntityType.objects.get(key=entity_type_key)
                except EntityType.DoesNotExist:
                    logger.warning(
                        "Unknown entity type '%s' in episode %s — skipping",
                        entity_type_key, episode_id,
                    )
                    continue

                unique_names = list(names_dict.keys())
                _acquire_name_locks(entity_type.pk, unique_names)
                existing = list(Entity.objects.filter(entity_type=entity_type))
                mb_candidates = _fetch_musicbrainz_candidates(unique_names, entity_type)

                if not existing and not mb_candidates:
                    # Trivial path — no LLM call, each name becomes a new Entity
                    # with no MBID. Wikidata enrichment will be attempted in the
                    # background.
                    all_mentions = []
                    seen_mentions: set[tuple[int, int]] = set()
                    for name in unique_names:
                        entity, _created = _get_or_create_entity(entity_type, name)
                        _maybe_enqueue(entity)
                        all_mentions.extend(
                            _collect_mentions(
                                name, entity, names_dict, episode, seen_mentions
                            )
                        )
                    EntityMention.objects.bulk_create(all_mentions)
                    continue

                system_prompt = _build_system_prompt(
                    entity_type_key, existing, mb_candidates
                )
                extracted_names = ", ".join(unique_names)
                result = provider.structured_extract(
                    system_prompt=system_prompt,
                    user_content=f"Extracted entities to resolve: {extracted_names}",
                    response_schema=RESOLUTION_RESPONSE_SCHEMA,
                )

                existing_by_id = {e.pk: e for e in existing}
                existing_by_mbid = {
                    e.musicbrainz_id: e for e in existing if e.musicbrainz_id
                }
                all_mentions = []
                handled_names = set()
                seen_mentions = set()

                for match in result["matches"]:
                    extracted_name = match["extracted_name"]
                    handled_names.add(extracted_name)
                    mbid = _sanitize_mbid(match.get("musicbrainz_id") or "")
                    matched_id = match["matched_entity_id"]
                    canonical_name = match.get("canonical_name") or extracted_name

                    if mbid and mbid in existing_by_mbid:
                        entity = existing_by_mbid[mbid]
                    elif matched_id is not None and matched_id in existing_by_id:
                        entity = existing_by_id[matched_id]
                        if mbid and not entity.musicbrainz_id:
                            entity.musicbrainz_id = mbid
                            entity.save(
                                update_fields=["musicbrainz_id", "updated_at"]
                            )
                            existing_by_mbid[mbid] = entity
                    else:
                        entity, _created = _get_or_create_entity(
                            entity_type, canonical_name, mbid
                        )
                        if entity.musicbrainz_id:
                            existing_by_mbid[entity.musicbrainz_id] = entity
                        existing_by_id[entity.pk] = entity

                    _maybe_enqueue(entity)
                    all_mentions.extend(
                        _collect_mentions(
                            extracted_name, entity, names_dict, episode, seen_mentions
                        )
                    )

                # Fallback for any names the LLM omitted from its response.
                for name in unique_names:
                    if name in handled_names:
                        continue
                    logger.warning(
                        "LLM omitted '%s' from resolution — creating without musicbrainz_id",
                        name,
                    )
                    entity, _created = _get_or_create_entity(entity_type, name)
                    _maybe_enqueue(entity)
                    all_mentions.extend(
                        _collect_mentions(
                            name, entity, names_dict, episode, seen_mentions
                        )
                    )

                EntityMention.objects.bulk_create(all_mentions)

        complete_step(episode, Episode.Status.RESOLVING)
        episode.status = Episode.Status.EMBEDDING
        episode.save(update_fields=["status", "updated_at"])
    except Exception as exc:
        logger.exception("Failed to resolve entities for episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.RESOLVING, str(exc), exc=exc)
        return

    # Outside the transaction so DBOS only sees committed entities.
    _enqueue_enrichment(sorted(entities_to_enrich))
