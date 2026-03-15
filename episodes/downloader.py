import logging
import os
import subprocess
import tempfile

from django.core.files import File
from mutagen.mp3 import MP3

from .models import Episode
from .processing import complete_step, fail_step, start_step

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

        # Extract duration from downloaded MP3
        audio = MP3(episode.audio_file.path)
        episode.duration = int(audio.info.length)

        complete_step(episode, Episode.Status.DOWNLOADING)
        episode.status = Episode.Status.TRANSCRIBING
        episode.save(update_fields=["status", "audio_file", "duration", "updated_at"])

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
