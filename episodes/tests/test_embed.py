from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings
from qdrant_client import QdrantClient

from episodes.models import Chunk, Entity, EntityMention, EntityType, Episode
from episodes.vector_store import QdrantVectorStore, detect_embedding_dim

TEST_DIM = 1536


def _vec(value=0.1):
    return [value] * TEST_DIM


@override_settings(
    RAGTIME_EMBEDDING_PROVIDER="openai",
    RAGTIME_EMBEDDING_API_KEY="test-key",
    RAGTIME_EMBEDDING_MODEL="text-embedding-3-small",
    RAGTIME_QDRANT_COLLECTION="ragtime_chunks_test",
)
class EmbedEpisodeTests(TestCase):
    def setUp(self):
        detect_embedding_dim.cache_clear()
        self._dim_patcher = patch(
            "episodes.vector_store.detect_embedding_dim",
            return_value=TEST_DIM,
        )
        self._dim_patcher.start()
        self.addCleanup(self._dim_patcher.stop)
        self.addCleanup(detect_embedding_dim.cache_clear)

        self.qdrant = QdrantClient(":memory:")
        self.store = QdrantVectorStore(self.qdrant, "ragtime_chunks_test")
        self.store.ensure_collection()

    def _create_episode(self, **kwargs):
        with patch("episodes.signals.async_task"):
            defaults = {
                "title": "Test Episode",
                "language": "en",
                "status": Episode.Status.EMBEDDING,
            }
            defaults.update(kwargs)
            return Episode.objects.create(**defaults)

    def _create_chunk(self, episode, index=0, text=None):
        return Chunk.objects.create(
            episode=episode,
            index=index,
            text=text or f"chunk {index} text",
            start_time=index * 30.0,
            end_time=(index + 1) * 30.0,
            segment_start=index * 10,
            segment_end=(index + 1) * 10,
        )

    def _run_embed(self, episode_id, vectors, store=None):
        mock_provider = MagicMock()
        mock_provider.embed.return_value = vectors
        store = store or self.store
        with (
            patch(
                "episodes.embedder.get_embedding_provider",
                return_value=mock_provider,
            ),
            patch(
                "episodes.embedder.get_vector_store",
                return_value=store,
            ),
        ):
            from episodes.embedder import embed_episode

            embed_episode(episode_id)
        return mock_provider

    def test_happy_path(self):
        episode = self._create_episode(url="https://example.com/ep/1")
        c0 = self._create_chunk(episode, index=0, text="first chunk")
        c1 = self._create_chunk(episode, index=1, text="second chunk")
        c2 = self._create_chunk(episode, index=2, text="third chunk")

        provider = self._run_embed(
            episode.pk, [_vec(0.1), _vec(0.2), _vec(0.3)]
        )

        provider.embed.assert_called_once_with(
            ["first chunk", "second chunk", "third chunk"]
        )
        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.READY)
        self.assertEqual(self.qdrant.count("ragtime_chunks_test").count, 3)

        records, _ = self.qdrant.scroll(
            "ragtime_chunks_test", limit=10, with_payload=True
        )
        payload_by_id = {r.id: r.payload for r in records}
        self.assertEqual(payload_by_id[c0.pk]["episode_id"], episode.pk)
        self.assertEqual(payload_by_id[c0.pk]["text"], "first chunk")
        self.assertEqual(payload_by_id[c1.pk]["chunk_index"], 1)
        self.assertEqual(payload_by_id[c2.pk]["language"], "en")
        self.assertEqual(payload_by_id[c0.pk]["start_time"], 0.0)
        self.assertEqual(payload_by_id[c2.pk]["entity_ids"], [])

    def test_entity_mentions_in_payload(self):
        episode = self._create_episode(url="https://example.com/ep/ents")
        chunk = self._create_chunk(episode, index=0, text="about miles")

        entity_type, _ = EntityType.objects.get_or_create(
            key="musician",
            defaults={"name": "Musician", "description": "A musician"},
        )
        miles = Entity.objects.create(
            entity_type=entity_type, name="Miles Davis"
        )
        coltrane = Entity.objects.create(
            entity_type=entity_type, name="John Coltrane"
        )
        EntityMention.objects.create(
            entity=miles, episode=episode, chunk=chunk, context="trumpet"
        )
        EntityMention.objects.create(
            entity=coltrane, episode=episode, chunk=chunk, context="sax"
        )

        self._run_embed(episode.pk, [_vec(0.1)])

        records, _ = self.qdrant.scroll(
            "ragtime_chunks_test", limit=10, with_payload=True
        )
        payload = records[0].payload
        self.assertEqual(
            sorted(payload["entity_ids"]), sorted([miles.pk, coltrane.pk])
        )
        self.assertEqual(
            sorted(payload["entity_names"]),
            sorted(["Miles Davis", "John Coltrane"]),
        )

    def test_no_chunks_goes_straight_to_ready(self):
        episode = self._create_episode(url="https://example.com/ep/empty")
        provider = self._run_embed(episode.pk, [])

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.READY)
        self.assertEqual(self.qdrant.count("ragtime_chunks_test").count, 0)
        # Provider.embed() is skipped when there's nothing to embed.
        provider.embed.assert_not_called()

    def test_reembed_to_zero_chunks_clears_prior_points(self):
        """Episode previously embedded, then re-chunked to empty: points drop."""
        episode = self._create_episode(url="https://example.com/ep/to-empty")
        self._create_chunk(episode, index=0, text="old one")
        self._create_chunk(episode, index=1, text="old two")
        self._run_embed(episode.pk, [_vec(0.1), _vec(0.2)])
        self.assertEqual(self.qdrant.count("ragtime_chunks_test").count, 2)

        # Re-chunk to empty, re-queue the embed step.
        Chunk.objects.filter(episode=episode).delete()
        episode.status = Episode.Status.EMBEDDING
        episode.save(update_fields=["status"])
        self._run_embed(episode.pk, [])

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.READY)
        # Prior points for this episode are gone — Scott can't retrieve
        # chunks that no longer exist in Postgres.
        self.assertEqual(self.qdrant.count("ragtime_chunks_test").count, 0)

    def test_idempotent_rerun(self):
        episode = self._create_episode(url="https://example.com/ep/rerun")
        self._create_chunk(episode, index=0)
        self._create_chunk(episode, index=1)

        self._run_embed(episode.pk, [_vec(0.1), _vec(0.2)])
        # Re-queue & re-run: status needs to be EMBEDDING again
        episode.status = Episode.Status.EMBEDDING
        episode.save(update_fields=["status"])
        self._run_embed(episode.pk, [_vec(0.3), _vec(0.4)])

        self.assertEqual(self.qdrant.count("ragtime_chunks_test").count, 2)
        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.READY)

    def test_reembed_after_rechunk_drops_stale_points(self):
        episode = self._create_episode(url="https://example.com/ep/rechunk")
        stale0 = self._create_chunk(episode, index=0)
        stale1 = self._create_chunk(episode, index=1)
        self._run_embed(episode.pk, [_vec(0.1), _vec(0.2)])

        stale_ids = {stale0.pk, stale1.pk}

        # Simulate re-chunking: drop old chunks, create new ones with fresh pks
        Chunk.objects.filter(episode=episode).delete()
        fresh = self._create_chunk(episode, index=0, text="fresh chunk")

        episode.status = Episode.Status.EMBEDDING
        episode.save(update_fields=["status"])
        self._run_embed(episode.pk, [_vec(0.9)])

        records, _ = self.qdrant.scroll(
            "ragtime_chunks_test", limit=10, with_payload=True
        )
        ids = {r.id for r in records}
        self.assertEqual(ids, {fresh.pk})
        self.assertFalse(ids & stale_ids)

    def test_wrong_status_is_noop(self):
        episode = self._create_episode(
            url="https://example.com/ep/wrong",
            status=Episode.Status.RESOLVING,
        )
        self._create_chunk(episode, index=0)
        self._run_embed(episode.pk, [_vec(0.1)])

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.RESOLVING)
        self.assertEqual(self.qdrant.count("ragtime_chunks_test").count, 0)

    def test_nonexistent_episode_does_not_raise(self):
        from episodes.embedder import embed_episode

        with (
            patch("episodes.embedder.get_embedding_provider"),
            patch("episodes.embedder.get_vector_store"),
        ):
            embed_episode(999999)

    def test_provider_failure_marks_failed(self):
        episode = self._create_episode(url="https://example.com/ep/pfail")
        self._create_chunk(episode, index=0)

        mock_provider = MagicMock()
        mock_provider.embed.side_effect = RuntimeError("openai is down")
        with (
            patch(
                "episodes.embedder.get_embedding_provider",
                return_value=mock_provider,
            ),
            patch(
                "episodes.embedder.get_vector_store", return_value=self.store
            ),
        ):
            from episodes.embedder import embed_episode

            embed_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("openai is down", episode.error_message)

    def test_qdrant_failure_marks_failed(self):
        episode = self._create_episode(url="https://example.com/ep/qfail")
        self._create_chunk(episode, index=0)

        broken_store = MagicMock()
        broken_store.ensure_collection.return_value = None
        broken_store.delete_by_episode.return_value = None
        broken_store.upsert_points.side_effect = RuntimeError("qdrant unreachable")

        mock_provider = MagicMock()
        mock_provider.embed.return_value = [_vec(0.1)]
        with (
            patch(
                "episodes.embedder.get_embedding_provider",
                return_value=mock_provider,
            ),
            patch(
                "episodes.embedder.get_vector_store", return_value=broken_store
            ),
        ):
            from episodes.embedder import embed_episode

            embed_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("qdrant unreachable", episode.error_message)

    def test_episode_delete_clears_qdrant_points(self):
        episode = self._create_episode(url="https://example.com/ep/del")
        self._create_chunk(episode, index=0)
        self._run_embed(episode.pk, [_vec(0.1)])
        self.assertEqual(self.qdrant.count("ragtime_chunks_test").count, 1)

        episode_pk = episode.pk
        with patch(
            "episodes.vector_store.get_vector_store", return_value=self.store
        ):
            episode.delete()

        # The post_delete signal should have cleared the point
        self.assertEqual(self.qdrant.count("ragtime_chunks_test").count, 0)
        # Sanity: no unexpected leftover in Postgres either
        self.assertFalse(Episode.objects.filter(pk=episode_pk).exists())

    def test_episode_delete_survives_qdrant_failure(self):
        episode = self._create_episode(url="https://example.com/ep/delfail")
        self._create_chunk(episode, index=0)

        broken_store = MagicMock()
        broken_store.delete_by_episode.side_effect = RuntimeError("qdrant down")

        episode_pk = episode.pk
        with patch(
            "episodes.vector_store.get_vector_store", return_value=broken_store
        ):
            episode.delete()  # must not raise

        self.assertFalse(Episode.objects.filter(pk=episode_pk).exists())


@override_settings(
    RAGTIME_EMBEDDING_PROVIDER="openai",
    RAGTIME_EMBEDDING_API_KEY="test-key",
    RAGTIME_EMBEDDING_MODEL="text-embedding-3-small",
    RAGTIME_QDRANT_COLLECTION="ragtime_chunks_test_dim",
)
class EnsureCollectionTests(TestCase):
    def setUp(self):
        detect_embedding_dim.cache_clear()
        self.addCleanup(detect_embedding_dim.cache_clear)

    def _patch_dim(self, dim):
        patcher = patch(
            "episodes.vector_store.detect_embedding_dim", return_value=dim
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_idempotent_create(self):
        self._patch_dim(TEST_DIM)
        qdrant = QdrantClient(":memory:")
        store = QdrantVectorStore(qdrant, "ragtime_chunks_test_dim")
        store.ensure_collection()
        store.ensure_collection()  # second call is a no-op
        info = qdrant.get_collection("ragtime_chunks_test_dim")
        self.assertEqual(info.config.params.vectors.size, TEST_DIM)

    def test_dim_mismatch_raises(self):
        self._patch_dim(TEST_DIM)
        from qdrant_client.http import models as qm

        qdrant = QdrantClient(":memory:")
        qdrant.create_collection(
            collection_name="ragtime_chunks_test_dim",
            vectors_config=qm.VectorParams(size=3072, distance=qm.Distance.COSINE),
        )
        store = QdrantVectorStore(qdrant, "ragtime_chunks_test_dim")
        with self.assertRaises(RuntimeError) as cm:
            store.ensure_collection()
        self.assertIn("3072", str(cm.exception))
        self.assertIn(str(TEST_DIM), str(cm.exception))
        # Mention the configured model so operators know what to check.
        self.assertIn("text-embedding-3-small", str(cm.exception))

    def test_create_respects_detected_dim(self):
        """A different model's dim flows through to the collection schema."""
        self._patch_dim(3072)  # text-embedding-3-large
        qdrant = QdrantClient(":memory:")
        store = QdrantVectorStore(qdrant, "ragtime_chunks_test_dim")
        store.ensure_collection()
        info = qdrant.get_collection("ragtime_chunks_test_dim")
        self.assertEqual(info.config.params.vectors.size, 3072)

    def test_detect_embedding_dim_probes_provider(self):
        """detect_embedding_dim() goes through the provider factory."""
        mock_provider = MagicMock()
        mock_provider.embed.return_value = [[0.0] * 2048]
        with patch(
            "episodes.providers.factory.get_embedding_provider",
            return_value=mock_provider,
        ):
            self.assertEqual(detect_embedding_dim(), 2048)
        mock_provider.embed.assert_called_once_with(["dim-probe"])

    def test_detect_embedding_dim_rejects_empty_response(self):
        mock_provider = MagicMock()
        mock_provider.embed.return_value = []
        with patch(
            "episodes.providers.factory.get_embedding_provider",
            return_value=mock_provider,
        ):
            with self.assertRaises(RuntimeError):
                detect_embedding_dim()


class OpenAIEmbeddingProviderTests(TestCase):
    def test_batching_preserves_order(self):
        from episodes.providers.openai import OpenAIEmbeddingProvider

        texts = [f"text-{i}" for i in range(300)]

        provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")

        calls = []

        def fake_create(model, input):
            calls.append(input)
            # fake one embedding per input; value = string length
            return MagicMock(
                data=[MagicMock(embedding=[len(t) * 1.0]) for t in input]
            )

        with patch.object(provider.client.embeddings, "create", side_effect=fake_create):
            out = provider.embed(texts)

        self.assertEqual(len(calls), 3)
        self.assertEqual(len(calls[0]), 128)
        self.assertEqual(len(calls[1]), 128)
        self.assertEqual(len(calls[2]), 44)
        self.assertEqual(len(out), 300)
        self.assertEqual(out[0], [len("text-0") * 1.0])
        self.assertEqual(out[-1], [len("text-299") * 1.0])

    def test_empty_input_short_circuits(self):
        from episodes.providers.openai import OpenAIEmbeddingProvider

        provider = OpenAIEmbeddingProvider(api_key="test", model="text-embedding-3-small")
        with patch.object(provider.client.embeddings, "create") as mock_create:
            self.assertEqual(provider.embed([]), [])
        mock_create.assert_not_called()
