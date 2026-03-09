import logging
import tempfile

import httpx
from django.conf import settings
from django.core.files import File

from .models import Episode

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 600  # 10 minutes for large audio files
CHUNK_SIZE = 64 * 1024  # 64KB chunks


def download_episode(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.DOWNLOADING:
        logger.warning(
            "Episode %s has status '%s', expected 'downloading'",
            episode_id,
            episode.status,
        )
        return

    try:
        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
            with httpx.stream(
                "GET",
                episode.audio_url,
                follow_redirects=True,
                timeout=DOWNLOAD_TIMEOUT,
                headers={"User-Agent": "RAGtime/0.1 (podcast audio downloader)"},
            ) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(chunk_size=CHUNK_SIZE):
                    tmp.write(chunk)
            tmp_path = tmp.name

        # Save to FileField
        filename = f"{episode.pk}.mp3"
        with open(tmp_path, "rb") as f:
            episode.audio_file.save(filename, File(f), save=False)

        # Check file size against Whisper API limit
        file_size = episode.audio_file.size
        max_size = getattr(settings, "RAGTIME_MAX_AUDIO_SIZE", 25 * 1024 * 1024)

        if file_size <= max_size:
            episode.status = Episode.Status.TRANSCRIBING
        else:
            episode.status = Episode.Status.RESIZING
            logger.info(
                "Episode %s audio is %.1fMB, queuing resize",
                episode_id,
                file_size / (1024 * 1024),
            )

        episode.save(update_fields=["status", "audio_file", "updated_at"])

    except Exception as exc:
        logger.exception("Failed to download episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
    finally:
        import os

        try:
            os.unlink(tmp_path)
        except (OSError, UnboundLocalError):
            pass
