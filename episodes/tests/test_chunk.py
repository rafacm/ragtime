import json
from pathlib import Path

from django.test import TestCase

from episodes.chunker import chunk_transcript
from episodes.models import Chunk, Episode

FIXTURES_DIR = Path(__file__).parent / "fixtures"

JOHN_COLTRANE_FIXTURE = (
    FIXTURES_DIR
    / "wdr-giant-steps-john-coltrane-episode-openai-whisper-transcript-response.json"
)


class ChunkTranscriptTests(TestCase):
    """Tests for the chunk_transcript pure function."""

    @classmethod
    def setUpTestData(cls):
        with open(JOHN_COLTRANE_FIXTURE) as f:
            cls.transcript_json = json.load(f)

    def test_chunk_transcript_basic(self):
        chunks = chunk_transcript(self.transcript_json)
        self.assertGreater(len(chunks), 1)

        for i, chunk in enumerate(chunks):
            self.assertEqual(chunk["index"], i)
            self.assertTrue(len(chunk["text"]) > 0)

        # Timestamps monotonically increasing
        for i in range(1, len(chunks)):
            self.assertGreaterEqual(
                chunks[i]["start_time"], chunks[i - 1]["start_time"]
            )

    def test_chunk_transcript_overlap(self):
        chunks = chunk_transcript(self.transcript_json, overlap_segments=1)
        self.assertGreater(len(chunks), 2)

        for i in range(1, len(chunks)):
            self.assertEqual(
                chunks[i]["segment_start"], chunks[i - 1]["segment_end"]
            )

    def test_chunk_transcript_empty_segments(self):
        result = chunk_transcript({"segments": []})
        self.assertEqual(result, [])

    def test_chunk_transcript_single_segment(self):
        single = {
            "segments": [
                {"id": 0, "text": "Hello world", "start": 0.0, "end": 1.0}
            ]
        }
        chunks = chunk_transcript(single)
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["index"], 0)
        self.assertEqual(chunks[0]["segment_start"], 0)
        self.assertEqual(chunks[0]["segment_end"], 0)


class ChunkEpisodeTests(TestCase):
    """Tests for the chunk_episode pipeline task."""

    @classmethod
    def setUpTestData(cls):
        with open(JOHN_COLTRANE_FIXTURE) as f:
            cls.transcript_json = json.load(f)

    def _create_episode(self, **kwargs):
        return Episode.objects.create(**kwargs)

    def test_chunk_episode_success(self):
        from episodes.chunker import chunk_episode

        episode = self._create_episode(
            url="https://example.com/ep/chunk-1",
            status=Episode.Status.CHUNKING,
            transcript_json=self.transcript_json,
        )

        chunk_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EXTRACTING)
        self.assertGreater(episode.chunks.count(), 0)

    def test_chunk_episode_no_transcript(self):
        from episodes.chunker import chunk_episode

        episode = self._create_episode(
            url="https://example.com/ep/chunk-2",
            status=Episode.Status.CHUNKING,
            transcript_json=None,
        )

        chunk_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.FAILED)
        self.assertIn("No transcript segments", episode.error_message)

    def test_chunk_episode_wrong_status(self):
        from episodes.chunker import chunk_episode

        episode = self._create_episode(
            url="https://example.com/ep/chunk-3",
            status=Episode.Status.PENDING,
        )

        chunk_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.PENDING)

    def test_chunk_episode_reprocessing(self):
        from episodes.chunker import chunk_episode

        episode = self._create_episode(
            url="https://example.com/ep/chunk-4",
            status=Episode.Status.CHUNKING,
            transcript_json=self.transcript_json,
        )

        # Create old chunks
        Chunk.objects.create(
            episode=episode,
            index=0,
            text="old chunk",
            start_time=0.0,
            end_time=1.0,
            segment_start=0,
            segment_end=0,
        )

        chunk_episode(episode.pk)

        episode.refresh_from_db()
        self.assertEqual(episode.status, Episode.Status.EXTRACTING)
        # Old chunk should be gone, replaced by new ones
        self.assertFalse(
            episode.chunks.filter(text="old chunk").exists()
        )
        self.assertGreater(episode.chunks.count(), 0)
