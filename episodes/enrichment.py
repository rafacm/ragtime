"""Background Wikidata enrichment for resolved entities.

Foreground resolution (``episodes/resolver.py``) only resolves to MusicBrainz
IDs (sub-ms local lookups). Wikidata IDs are enriched here, asynchronously,
through a singleton DBOS queue: throttled to one resolver at a time across
all worker processes so we never trip Wikidata's API rate limit.

Strategy per entity:

1. If the entity has a ``musicbrainz_id``, look up its Wikidata Q-ID via
   MusicBrainz external links (local DB, no network).
2. Otherwise (or if step 1 finds nothing), search Wikidata + LLM picker.
3. Persist ``Entity.wikidata_id`` and bookkeeping on success/failure.
4. Qdrant payloads do not need a parallel update — search-time hydration
   joins through ``EntityMention -> Entity`` and picks up the new value.

Implementation: business logic lives in plain functions (``*_impl`` /
helpers); DBOS decorators wrap them only for the production durable path.
This lets tests exercise the logic without launching DBOS.
"""

from __future__ import annotations

import logging

from dbos import DBOS, Queue
from django.utils import timezone

from . import musicbrainz
from .models import Entity

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3

# Singleton background queue. concurrency=1 across the whole cluster, so
# Wikidata's 5 req/s rate limit is never threatened — only one worker at a
# time is enriching.
wikidata_queue = Queue(
    "wikidata_enrichment",
    concurrency=1,
    worker_concurrency=1,
)


def enqueue_entities(entity_ids):
    """Enqueue ``enrich_entity_wikidata`` for each entity_id.

    Idempotent — the workflow short-circuits when the entity already has a
    wikidata_id or has exhausted its retry budget, so re-enqueuing the same
    id is safe.
    """
    for entity_id in entity_ids:
        try:
            wikidata_queue.enqueue(enrich_entity_wikidata, entity_id)
        except Exception:
            logger.exception(
                "Failed to enqueue Wikidata enrichment for entity %s", entity_id
            )


def enrich_entity_wikidata_impl(entity_id: int) -> None:
    """Plain (non-DBOS) implementation of the enrichment workflow."""
    entity = _fetch_entity(entity_id)
    if entity is None:
        return
    if entity.wikidata_id:
        return  # already enriched (idempotent)
    if entity.wikidata_attempts >= MAX_ATTEMPTS:
        logger.info(
            "Skipping entity %s — exceeded MAX_ATTEMPTS=%s", entity_id, MAX_ATTEMPTS
        )
        return

    qid = _resolve_wikidata(entity)
    _persist_outcome(entity_id, qid)


@DBOS.workflow()
def enrich_entity_wikidata(entity_id: int) -> None:
    """Resolve a single Entity's Wikidata Q-ID via MB link or Wikidata API."""
    enrich_entity_wikidata_impl(entity_id)


def _fetch_entity(entity_id: int) -> Entity | None:
    try:
        return Entity.objects.select_related("entity_type").get(pk=entity_id)
    except Entity.DoesNotExist:
        return None


def _resolve_wikidata(entity: Entity) -> str | None:
    """Try MB external link first, fall back to Wikidata search + LLM."""
    if entity.musicbrainz_id and entity.entity_type.musicbrainz_table:
        qid = musicbrainz.get_wikidata_qid(entity.musicbrainz_id, entity.entity_type)
        if qid:
            return qid

    if not entity.entity_type.wikidata_id:
        # No P31 class to filter Wikidata search by — skip the API call.
        return None

    try:
        from .wikidata import find_candidates
    except Exception:
        logger.warning("Wikidata client unavailable; cannot enrich entity %s", entity.pk)
        return None

    try:
        candidates = find_candidates(entity.name, entity.entity_type.wikidata_id)
    except Exception:
        logger.exception("Wikidata search failed for entity %s", entity.pk)
        return None

    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]["qid"]
    return _pick_with_llm(entity, candidates)


def _pick_with_llm(entity: Entity, candidates) -> str | None:
    try:
        from .providers.factory import get_resolution_provider
    except Exception:
        logger.exception("Resolution provider unavailable")
        return None

    schema = {
        "name": "wikidata_pick",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "qid": {"type": ["string", "null"]},
            },
            "required": ["qid"],
            "additionalProperties": False,
        },
    }
    candidate_lines = "\n".join(
        f"- {c['qid']}: {c['label']} ({c['description']})" for c in candidates
    )
    system_prompt = (
        f"Pick the Wikidata Q-ID best matching the entity '{entity.name}' "
        f"(type: {entity.entity_type.name}). Return null if none clearly match.\n\n"
        f"Candidates:\n{candidate_lines}"
    )
    try:
        result = get_resolution_provider().structured_extract(
            system_prompt=system_prompt,
            user_content=f"Entity: {entity.name}",
            response_schema=schema,
        )
    except Exception:
        logger.exception("LLM picker failed for entity %s", entity.pk)
        return None

    qid = (result or {}).get("qid")
    return qid or None


def _persist_outcome(entity_id: int, qid: str | None) -> None:
    try:
        entity = Entity.objects.get(pk=entity_id)
    except Entity.DoesNotExist:
        return

    entity.wikidata_attempts = entity.wikidata_attempts + 1
    entity.wikidata_last_attempted_at = timezone.now()
    if qid:
        entity.wikidata_id = qid
        entity.wikidata_status = Entity.WikidataStatus.RESOLVED
    elif entity.wikidata_attempts >= MAX_ATTEMPTS:
        entity.wikidata_status = Entity.WikidataStatus.NOT_FOUND
    # else: leave PENDING for natural retry via re-enqueue.
    entity.save(
        update_fields=[
            "wikidata_id",
            "wikidata_status",
            "wikidata_attempts",
            "wikidata_last_attempted_at",
            "updated_at",
        ]
    )
