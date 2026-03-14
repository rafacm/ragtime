import logging
import os
import subprocess
import tempfile

from django.conf import settings
from django.core.files import File

from .models import Episode
from .processing import complete_step, fail_step, skip_step, start_step

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 60  # 1 minute


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

    start_step(episode, Episode.Status.DOWNLOADING)

    try:
        tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
        tmp_path = tmp.name
        tmp.close()

        subprocess.run(
            ["wget", "-q", "-O", tmp_path, episode.audio_url],
            check=True,
            timeout=DOWNLOAD_TIMEOUT,
        )

        # Save to FileField
        filename = f"{episode.pk}.mp3"
        with open(tmp_path, "rb") as f:
            episode.audio_file.save(filename, File(f), save=False)

        # Check file size against Whisper API limit
        file_size = episode.audio_file.size
        max_size = getattr(settings, "RAGTIME_MAX_AUDIO_SIZE", 25 * 1024 * 1024)

        if file_size <= max_size:
            complete_step(episode, Episode.Status.DOWNLOADING)
            skip_step(episode, Episode.Status.RESIZING)
            episode.status = Episode.Status.TRANSCRIBING
        else:
            complete_step(episode, Episode.Status.DOWNLOADING)
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
        fail_step(episode, Episode.Status.DOWNLOADING, str(exc))
    finally:
        try:
            os.unlink(tmp_path)
        except (OSError, UnboundLocalError):
            pass
