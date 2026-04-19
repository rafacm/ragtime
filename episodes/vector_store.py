"""Qdrant vector store client for episode chunks."""

import logging
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

logger = logging.getLogger(__name__)

DISTANCE = qm.Distance.COSINE
UPSERT_BATCH_SIZE = 128


@dataclass(frozen=True)
class QdrantPoint:
    id: int
    vector: list[float]
    payload: dict


@lru_cache(maxsize=1)
def detect_embedding_dim() -> int:
    """Probe the configured embedding provider to learn its vector dim.

    Runs one embedding call on a short token and returns the length of the
    returned vector. Cached for the lifetime of the process so the probe
    never costs more than a single API call. A provider/model swap needs a
    process restart (or a manual `detect_embedding_dim.cache_clear()`) to
    take effect — matches the cadence of every other env-var change.
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
        """Create collection if missing; verify dim against the live model."""
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

        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=qm.VectorParams(size=expected_dim, distance=DISTANCE),
        )
        for field, schema in (
            ("episode_id", qm.PayloadSchemaType.INTEGER),
            ("language", qm.PayloadSchemaType.KEYWORD),
            ("entity_ids", qm.PayloadSchemaType.INTEGER),
        ):
            self.client.create_payload_index(
                self.collection, field_name=field, field_schema=schema
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


@lru_cache(maxsize=1)
def get_vector_store() -> QdrantVectorStore:
    return QdrantVectorStore.from_settings()
