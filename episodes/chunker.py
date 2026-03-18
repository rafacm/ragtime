import logging

from .models import Chunk, Episode
from .processing import complete_step, fail_step, start_step

logger = logging.getLogger(__name__)

CHUNK_TARGET_WORDS = 150
CHUNK_OVERLAP_SEGMENTS = 1


def chunk_transcript(transcript_json, target_words=CHUNK_TARGET_WORDS, overlap_segments=CHUNK_OVERLAP_SEGMENTS):
    """Split Whisper transcript JSON into chunks by segment boundaries.

    Pure function — no DB access. Returns a list of chunk dicts.
    """
    segments = transcript_json.get("segments", [])
    if not segments:
        return []

    chunks = []
    current_segments = []
    current_word_count = 0

    for segment in segments:
        seg_words = len(segment["text"].split())

        if current_segments and current_word_count + seg_words > target_words:
            # Save current chunk
            chunks.append(_build_chunk(current_segments, len(chunks)))

            # Start new chunk with overlap
            overlap = current_segments[-overlap_segments:] if overlap_segments > 0 else []
            current_segments = list(overlap)
            current_word_count = sum(len(s["text"].split()) for s in current_segments)

        current_segments.append(segment)
        current_word_count += seg_words

    # Last chunk
    if current_segments:
        chunks.append(_build_chunk(current_segments, len(chunks)))

    return chunks


def _build_chunk(segments, index):
    return {
        "index": index,
        "text": " ".join(s["text"].strip() for s in segments),
        "start_time": segments[0]["start"],
        "end_time": segments[-1]["end"],
        "segment_start": segments[0]["id"],
        "segment_end": segments[-1]["id"],
    }


def chunk_episode(episode_id):
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.CHUNKING:
        logger.warning(
            "Episode %s has status '%s', expected 'chunking'",
            episode_id,
            episode.status,
        )
        return

    start_step(episode, Episode.Status.CHUNKING)

    if not episode.transcript_json or "segments" not in episode.transcript_json:
        episode.error_message = "No transcript segments to chunk"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.CHUNKING, "No transcript segments to chunk")
        return

    try:
        # Delete existing chunks (re-processing support)
        episode.chunks.all().delete()

        chunk_dicts = chunk_transcript(episode.transcript_json)
        Chunk.objects.bulk_create([
            Chunk(episode=episode, **cd) for cd in chunk_dicts
        ])

        complete_step(episode, Episode.Status.CHUNKING)
        episode.status = Episode.Status.EXTRACTING
        episode.save(update_fields=["status", "updated_at"])
    except Exception as exc:
        logger.exception("Failed to chunk episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.CHUNKING, str(exc), exc=exc)
