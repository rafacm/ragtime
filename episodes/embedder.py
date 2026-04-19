"""Embed pipeline step: generate vectors for chunks and upsert them to Qdrant."""

import logging
from collections import defaultdict

from .models import Episode, EntityMention
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_embedding_provider
from .telemetry import trace_step
from .vector_store import QdrantPoint, get_vector_store

logger = logging.getLogger(__name__)


def _build_payloads(episode, chunks):
    mentions = (
        EntityMention.objects.filter(episode=episode)
        .select_related("entity")
        .values("chunk_id", "entity_id", "entity__name")
    )
    by_chunk = defaultdict(list)
    for m in mentions:
        by_chunk[m["chunk_id"]].append(
            {"id": m["entity_id"], "name": m["entity__name"]}
        )

    published_iso = (
        episode.published_at.isoformat() if episode.published_at else None
    )

    payloads = []
    for chunk in chunks:
        ents = by_chunk.get(chunk.pk, [])
        payloads.append(
            {
                "chunk_id": chunk.pk,
                "chunk_index": chunk.index,
                "episode_id": episode.pk,
                "episode_title": episode.title,
                "episode_url": episode.url,
                "episode_published_at": published_iso,
                "episode_image_url": episode.image_url,
                "start_time": chunk.start_time,
                "end_time": chunk.end_time,
                "language": episode.language,
                "entity_ids": [e["id"] for e in ents],
                "entity_names": [e["name"] for e in ents],
                "text": chunk.text,
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
    if not chunks:
        logger.info("Episode %s has no chunks, skipping embed", episode_id)
        complete_step(episode, Episode.Status.EMBEDDING)
        episode.status = Episode.Status.READY
        episode.save(update_fields=["status", "updated_at"])
        return

    try:
        provider = get_embedding_provider()
        store = get_vector_store()
        store.ensure_collection()
        # Wipe stale points first — if the episode was re-chunked, old
        # chunk IDs would otherwise orphan in Qdrant.
        store.delete_by_episode(episode.pk)

        texts = [c.text for c in chunks]
        vectors = provider.embed(texts)
        payloads = _build_payloads(episode, chunks)

        points = [
            QdrantPoint(id=c.pk, vector=v, payload=p)
            for c, v, p in zip(chunks, vectors, payloads, strict=True)
        ]
        store.upsert_points(points)

        complete_step(episode, Episode.Status.EMBEDDING)
        episode.status = Episode.Status.READY
        episode.save(update_fields=["status", "updated_at"])
    except Exception as exc:
        logger.exception("Failed to embed episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.EMBEDDING, str(exc), exc=exc)
