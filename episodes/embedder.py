"""Embed pipeline step: generate vectors for chunks and upsert them to Qdrant.

Qdrant payload is intentionally slim — only what's needed for server-side
filtering. Everything else (episode metadata, chunk text, entity names,
MBIDs, Wikidata IDs) is fetched from Postgres at query time. See
``episodes.vector_store`` for the rationale.
"""

import logging
from collections import defaultdict

from .models import Episode, EntityMention
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_embedding_provider
from .telemetry import trace_step
from .vector_store import QdrantPoint, get_vector_store

logger = logging.getLogger(__name__)


def _build_payloads(episode, chunks):
    """Slim Qdrant payload — only fields used for filtering / FK lookup.

    Fields kept (server-side filterable):
    * ``chunk_id``  — FK back to Postgres for hydration at search time
    * ``episode_id`` — Scott's per-episode filter
    * ``language`` — future per-language filter
    * ``entity_ids`` — entity-faceted retrieval

    Everything else (titles, urls, text, entity names, etc.) lives in
    Postgres and is hydrated at search time. Editing them is a one-row
    Postgres UPDATE — no re-embedding, no Qdrant payload mutation.
    """
    mentions = (
        EntityMention.objects.filter(episode=episode)
        .values("chunk_id", "entity_id")
    )
    by_chunk: dict[int, list[int]] = defaultdict(list)
    for m in mentions:
        by_chunk[m["chunk_id"]].append(m["entity_id"])

    payloads = []
    for chunk in chunks:
        payloads.append(
            {
                "chunk_id": chunk.pk,
                "episode_id": episode.pk,
                "language": episode.language,
                "entity_ids": by_chunk.get(chunk.pk, []),
                "episode_title": episode.title,
            }
        )
    return payloads


@trace_step("embed")
def embed_episode(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.EMBEDDING:
        logger.warning(
            "Episode %s has status '%s', expected 'embedding'",
            episode_id,
            episode.status,
        )
        return

    start_step(episode, Episode.Status.EMBEDDING)

    chunks = list(episode.chunks.order_by("index"))

    try:
        store = get_vector_store()
        # ensure_collection is idempotent and called once at process startup
        # in apps.ready(); calling it again here is cheap insurance against
        # cold-start ordering issues with non-uvicorn entrypoints.
        store.ensure_collection()
        # Always wipe stale points first. Covers two cases: re-chunked
        # episodes (chunk PKs change), and re-runs into an empty chunk set
        # (would otherwise leave old points queryable for a Ready episode
        # that no longer has any chunks in Postgres).
        store.delete_by_episode(episode.pk)

        if chunks:
            provider = get_embedding_provider()
            texts = [c.text for c in chunks]
            vectors = provider.embed(texts)
            payloads = _build_payloads(episode, chunks)
            points = [
                QdrantPoint(id=c.pk, vector=v, payload=p)
                for c, v, p in zip(chunks, vectors, payloads, strict=True)
            ]
            store.upsert_points(points)
        else:
            logger.info(
                "Episode %s has no chunks; cleared prior Qdrant points",
                episode_id,
            )

        complete_step(episode, Episode.Status.EMBEDDING)
        episode.status = Episode.Status.READY
        episode.save(update_fields=["status", "updated_at"])
    except Exception as exc:
        logger.exception("Failed to embed episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.EMBEDDING, str(exc), exc=exc)
