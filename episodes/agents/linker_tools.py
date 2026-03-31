"""Wikidata lookup tools for the linking agent."""

import logging

from pydantic_ai import RunContext

from .linker_deps import LinkingDeps

logger = logging.getLogger(__name__)


async def search_wikidata(
    ctx: RunContext[LinkingDeps],
    entity_name: str,
    entity_type_qid: str,
) -> str:
    """Search Wikidata for candidates matching *entity_name* filtered by type.

    Returns a formatted list of candidates with Q-IDs and descriptions,
    or a message if no candidates were found.
    """
    from ..wikidata import find_candidates

    try:
        candidates = find_candidates(entity_name, entity_type_qid)
    except Exception as exc:
        return f"Wikidata search failed for '{entity_name}': {exc}"

    if not candidates:
        return f"No Wikidata candidates found for '{entity_name}' (type {entity_type_qid})."

    lines = [f"Wikidata candidates for '{entity_name}':"]
    for c in candidates:
        desc = f": {c['description']}" if c.get("description") else ""
        lines.append(f"  - {c['qid']} ({c['label']}{desc})")
    return "\n".join(lines)


async def link_entity(
    ctx: RunContext[LinkingDeps],
    entity_id: int,
    wikidata_qid: str,
    reason: str,
) -> str:
    """Link an entity to a Wikidata Q-ID.

    Sets the entity's wikidata_id and marks linking_status as 'linked'.
    Provide a brief *reason* explaining why this Q-ID is the best match.
    """
    from ..models import Entity

    try:
        entity = await Entity.objects.aget(pk=entity_id)
    except Entity.DoesNotExist:
        return f"Entity {entity_id} not found."

    entity.wikidata_id = wikidata_qid
    entity.linking_status = Entity.LinkingStatus.LINKED
    await entity.asave(update_fields=["wikidata_id", "linking_status", "updated_at"])

    ctx.deps.linked_count += 1
    logger.info(
        "Linked entity %d (%s) → %s: %s",
        entity_id, entity.name, wikidata_qid, reason,
    )
    return f"Linked '{entity.name}' → {wikidata_qid}."


async def mark_failed(
    ctx: RunContext[LinkingDeps],
    entity_id: int,
    reason: str,
) -> str:
    """Mark an entity as failed to link — no suitable Wikidata match exists.

    Provide a brief *reason* explaining why no candidate matched.
    """
    from ..models import Entity

    try:
        entity = await Entity.objects.aget(pk=entity_id)
    except Entity.DoesNotExist:
        return f"Entity {entity_id} not found."

    entity.linking_status = Entity.LinkingStatus.FAILED
    await entity.asave(update_fields=["linking_status", "updated_at"])

    ctx.deps.failed_count += 1
    logger.info(
        "Failed to link entity %d (%s): %s", entity_id, entity.name, reason,
    )
    return f"Marked '{entity.name}' as failed: {reason}."


async def skip_entity(
    ctx: RunContext[LinkingDeps],
    entity_id: int,
    reason: str,
) -> str:
    """Skip linking for an entity (e.g. entity type has no Wikidata class).

    Provide a brief *reason* explaining why linking was skipped.
    """
    from ..models import Entity

    try:
        entity = await Entity.objects.aget(pk=entity_id)
    except Entity.DoesNotExist:
        return f"Entity {entity_id} not found."

    entity.linking_status = Entity.LinkingStatus.SKIPPED
    await entity.asave(update_fields=["linking_status", "updated_at"])

    ctx.deps.skipped_count += 1
    logger.info(
        "Skipped linking entity %d (%s): %s", entity_id, entity.name, reason,
    )
    return f"Skipped '{entity.name}': {reason}."
