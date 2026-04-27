"""Qdrant vector store client for episode chunks.

Storage strategy: Qdrant holds vectors plus the **minimum** payload needed
for server-side filtering — ``chunk_id`` (FK back to Postgres),
``episode_id`` (Scott's per-episode filter), ``language``, and
``entity_ids`` (entity-faceted search).

Everything Scott displays — episode title, urls, timestamps, chunk text,
entity names, MBIDs, Wikidata IDs — is fetched from Postgres at search
time keyed on ``chunk_id``. This way:

* Edits to ``Episode.title`` or canonical entity names are visible
  immediately (no re-embedding).
* Background Wikidata enrichment updates ``Entity.wikidata_id`` in
  Postgres only — Qdrant never needs to be patched.
* The Qdrant collection stays small.
"""

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from functools import lru_cache

from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from qdrant_client.http.exceptions import UnexpectedResponse

logger = logging.getLogger(__name__)

DISTANCE = qm.Distance.COSINE
UPSERT_BATCH_SIZE = 128


@dataclass(frozen=True)
class QdrantPoint:
    id: int
    vector: list[float]
    payload: dict


@dataclass(frozen=True)
class ChunkSearchResult:
    chunk_id: int
    episode_id: int
    episode_title: str
    episode_url: str
    episode_audio_url: str
    episode_image_url: str
    start_time: float
    end_time: float
    language: str
    text: str
    score: float
    entity_ids: list[int] = field(default_factory=list)
    entity_names: list[str] = field(default_factory=list)
    musicbrainz_ids: list[str] = field(default_factory=list)
    wikidata_ids: list[str] = field(default_factory=list)


@lru_cache(maxsize=1)
def detect_embedding_dim() -> int:
    """Probe the configured embedding provider to learn its vector dim.

    Cached for the lifetime of the process. Provider/model swap requires a
    process restart (or ``detect_embedding_dim.cache_clear()``) — same
    cadence as every other env-var change.
    """
    from .providers.factory import get_embedding_provider

    provider = get_embedding_provider()
    vectors = provider.embed(["dim-probe"])
    if not vectors or not vectors[0]:
        raise RuntimeError(
            "Embedding provider returned an empty result for the dim probe"
        )
    dim = len(vectors[0])
    logger.debug(
        "Detected embedding dim %d for model %s",
        dim,
        settings.RAGTIME_EMBEDDING_MODEL,
    )
    return dim


class QdrantVectorStore:
    def __init__(self, client: QdrantClient, collection: str):
        self.client = client
        self.collection = collection

    @classmethod
    def from_settings(cls) -> "QdrantVectorStore":
        client = QdrantClient(
            host=settings.RAGTIME_QDRANT_HOST,
            port=settings.RAGTIME_QDRANT_PORT,
            api_key=settings.RAGTIME_QDRANT_API_KEY or None,
            https=settings.RAGTIME_QDRANT_HTTPS,
            prefer_grpc=False,
        )
        return cls(client, settings.RAGTIME_QDRANT_COLLECTION)

    def ensure_collection(self) -> None:
        """Create collection if missing; verify dim against the live model.

        409-tolerant: if a parallel worker creates the collection between
        our ``collection_exists()`` check and ``create_collection()``, we
        treat the conflict as success rather than crashing.
        """
        expected_dim = detect_embedding_dim()

        if self.client.collection_exists(self.collection):
            info = self.client.get_collection(self.collection)
            actual_dim = info.config.params.vectors.size
            if actual_dim != expected_dim:
                raise RuntimeError(
                    f"Qdrant collection '{self.collection}' has vector dim "
                    f"{actual_dim}, but the configured embedding model "
                    f"({settings.RAGTIME_EMBEDDING_MODEL}) produces "
                    f"{expected_dim}-dim vectors. Drop the collection (e.g. "
                    f"`uv run python manage.py dbreset`) or set "
                    f"RAGTIME_QDRANT_COLLECTION to a new name."
                )
            return

        try:
            self.client.create_collection(
                collection_name=self.collection,
                vectors_config=qm.VectorParams(size=expected_dim, distance=DISTANCE),
            )
        except UnexpectedResponse as exc:
            # 409 Conflict — another worker created it concurrently. Fine.
            if getattr(exc, "status_code", None) != 409:
                raise
            logger.debug(
                "Qdrant collection %r created concurrently — continuing",
                self.collection,
            )
            return

        for field_name, schema in (
            ("episode_id", qm.PayloadSchemaType.INTEGER),
            ("language", qm.PayloadSchemaType.KEYWORD),
            ("entity_ids", qm.PayloadSchemaType.INTEGER),
        ):
            self.client.create_payload_index(
                self.collection, field_name=field_name, field_schema=schema
            )

    def upsert_points(self, points: list[QdrantPoint]) -> None:
        for i in range(0, len(points), UPSERT_BATCH_SIZE):
            batch = points[i : i + UPSERT_BATCH_SIZE]
            self.client.upsert(
                collection_name=self.collection,
                points=[
                    qm.PointStruct(id=p.id, vector=p.vector, payload=p.payload)
                    for p in batch
                ],
                wait=True,
            )

    def delete_by_episode(self, episode_id: int) -> None:
        self.client.delete(
            collection_name=self.collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="episode_id",
                            match=qm.MatchValue(value=episode_id),
                        )
                    ]
                )
            ),
        )

    def search(
        self,
        query_vector: list[float],
        top_k: int,
        episode_id: int | None = None,
        score_threshold: float | None = None,
    ) -> list[ChunkSearchResult]:
        query_filter = None
        if episode_id is not None:
            query_filter = qm.Filter(
                must=[
                    qm.FieldCondition(
                        key="episode_id",
                        match=qm.MatchValue(value=episode_id),
                    )
                ]
            )

        hits = self.client.query_points(
            collection_name=self.collection,
            query=query_vector,
            limit=top_k,
            query_filter=query_filter,
            score_threshold=score_threshold,
            with_payload=True,
        ).points

        return _hydrate_hits(hits)


@lru_cache(maxsize=1)
def get_vector_store() -> QdrantVectorStore:
    return QdrantVectorStore.from_settings()


def search_chunks(
    query: str,
    top_k: int = 5,
    episode_id: int | None = None,
    score_threshold: float | None = None,
) -> list[ChunkSearchResult]:
    """Embed ``query`` with the configured provider and return top-k chunks."""
    from .providers.factory import get_embedding_provider

    vector = get_embedding_provider().embed([query])[0]
    return get_vector_store().search(
        query_vector=vector,
        top_k=top_k,
        episode_id=episode_id,
        score_threshold=score_threshold,
    )


def _hydrate_hits(hits) -> list[ChunkSearchResult]:
    """Build full ChunkSearchResult dataclasses from Qdrant hits + Postgres.

    Qdrant stores only ``chunk_id`` (and a few server-side filter fields).
    Everything else — episode metadata, chunk text, entity names + IDs —
    comes from a single Postgres query keyed on the returned chunk_ids.
    Results are re-ordered to match Qdrant's score order.
    """
    if not hits:
        return []

    chunk_ids = [int(h.payload.get("chunk_id", h.id)) for h in hits]
    score_by_id = {cid: float(h.score) for cid, h in zip(chunk_ids, hits)}
    lang_by_id = {
        cid: h.payload.get("language", "") for cid, h in zip(chunk_ids, hits)
    }

    from .models import Chunk, EntityMention

    chunks_by_id = {
        c.pk: c
        for c in Chunk.objects.select_related("episode").filter(pk__in=chunk_ids)
    }

    mentions_by_chunk: dict[int, list] = defaultdict(list)
    for mention in (
        EntityMention.objects.select_related("entity").filter(chunk_id__in=chunk_ids)
    ):
        mentions_by_chunk[mention.chunk_id].append(mention.entity)

    results: list[ChunkSearchResult] = []
    for cid in chunk_ids:
        chunk = chunks_by_id.get(cid)
        if chunk is None:
            # Qdrant point references a chunk that no longer exists in
            # Postgres (e.g. mid-reprocess). Skip it rather than 500.
            logger.warning("Qdrant returned chunk_id %s with no Postgres row", cid)
            continue
        episode = chunk.episode
        entities = mentions_by_chunk.get(cid, [])
        audio_url = episode.audio_url or (
            episode.audio_file.url if episode.audio_file else ""
        )
        results.append(
            ChunkSearchResult(
                chunk_id=cid,
                episode_id=episode.pk,
                episode_title=episode.title,
                episode_url=episode.url,
                episode_audio_url=audio_url,
                episode_image_url=episode.image_url,
                start_time=chunk.start_time,
                end_time=chunk.end_time,
                # Trust Qdrant's stored language for the *match*, but fall
                # back to the episode's language if absent.
                language=lang_by_id.get(cid) or episode.language,
                text=chunk.text,
                score=score_by_id[cid],
                entity_ids=[e.pk for e in entities],
                entity_names=[e.name for e in entities],
                musicbrainz_ids=[e.musicbrainz_id for e in entities if e.musicbrainz_id],
                wikidata_ids=[e.wikidata_id for e in entities if e.wikidata_id],
            )
        )
    return results
