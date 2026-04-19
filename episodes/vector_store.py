"""Qdrant vector store client for episode chunks."""

import logging
from dataclasses import dataclass
from functools import lru_cache

from django.conf import settings
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 1536  # text-embedding-3-small
DISTANCE = qm.Distance.COSINE
UPSERT_BATCH_SIZE = 128


@dataclass(frozen=True)
class QdrantPoint:
    id: int
    vector: list[float]
    payload: dict


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
        """Create collection if missing; verify dim if it exists."""
        if self.client.collection_exists(self.collection):
            info = self.client.get_collection(self.collection)
            actual_dim = info.config.params.vectors.size
            if actual_dim != EMBEDDING_DIM:
                raise RuntimeError(
                    f"Qdrant collection '{self.collection}' has vector "
                    f"dim {actual_dim}, expected {EMBEDDING_DIM}. "
                    f"Did RAGTIME_EMBEDDING_MODEL change? "
                    f"Drop the collection or use a different name."
                )
            return

        self.client.create_collection(
            collection_name=self.collection,
            vectors_config=qm.VectorParams(size=EMBEDDING_DIM, distance=DISTANCE),
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
