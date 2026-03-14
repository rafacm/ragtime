import logging
import shutil
import subprocess
import tempfile

from django.conf import settings
from django.core.files import File

from .models import Episode
from .processing import complete_step, fail_step, start_step

logger = logging.getLogger(__name__)

FFMPEG_TIMEOUT = 600  # 10 minutes


def resize_episode(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.RESIZING:
        logger.warning(
            "Episode %s has status '%s', expected 'resizing'",
            episode_id,
            episode.status,
        )
        return

    start_step(episode, Episode.Status.RESIZING)

    if not episode.audio_file:
        episode.error_message = "No audio file to resize"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.RESIZING, "No audio file to resize")
        return

    output_path = None
    try:
        # Check ffmpeg is available
        if not shutil.which("ffmpeg"):
            episode.error_message = "ffmpeg is not installed or not on PATH"
            episode.status = Episode.Status.FAILED
            episode.save(update_fields=["status", "error_message", "updated_at"])
            fail_step(episode, Episode.Status.RESIZING, episode.error_message)
            return

        input_path = episode.audio_file.path

        # Create temp file for resized output
        with tempfile.NamedTemporaryFile(
            suffix=".mp3", delete=False
        ) as tmp:
            output_path = tmp.name

        # Downsample: mono, 22050Hz, 64kbps
        result = subprocess.run(
            [
                "ffmpeg",
                "-i", input_path,
                "-ac", "1",
                "-ar", "22050",
                "-b:a", "64k",
                "-y",
                output_path,
            ],
            capture_output=True,
            timeout=FFMPEG_TIMEOUT,
        )

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            episode.error_message = f"ffmpeg failed (exit {result.returncode}): {stderr[:500]}"
            episode.status = Episode.Status.FAILED
            episode.save(update_fields=["status", "error_message", "updated_at"])
            fail_step(episode, Episode.Status.RESIZING, episode.error_message)
            return

        # Check output size
        import os

        output_size = os.path.getsize(output_path)
        max_size = getattr(settings, "RAGTIME_MAX_AUDIO_SIZE", 25 * 1024 * 1024)

        if output_size > max_size:
            episode.error_message = (
                f"Audio file exceeds 25MB after resizing "
                f"({output_size / (1024 * 1024):.1f}MB)"
            )
            episode.status = Episode.Status.FAILED
            episode.save(update_fields=["status", "error_message", "updated_at"])
            fail_step(episode, Episode.Status.RESIZING, episode.error_message)
            return

        # Replace original file with resized version
        filename = f"{episode.pk}.mp3"
        with open(output_path, "rb") as f:
            episode.audio_file.save(filename, File(f), save=False)

        complete_step(episode, Episode.Status.RESIZING)
        episode.status = Episode.Status.TRANSCRIBING
        episode.save(update_fields=["status", "audio_file", "updated_at"])

        logger.info(
            "Episode %s resized: %.1fMB → %.1fMB",
            episode_id,
            os.path.getsize(input_path) / (1024 * 1024) if os.path.exists(input_path) else 0,
            output_size / (1024 * 1024),
        )

    except subprocess.TimeoutExpired:
        logger.exception("ffmpeg timed out for episode %s", episode_id)
        episode.error_message = "ffmpeg timed out during audio resize"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.RESIZING, episode.error_message)

    except Exception as exc:
        logger.exception("Failed to resize episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.RESIZING, str(exc))

    finally:
        import os

        if output_path:
            try:
                os.unlink(output_path)
            except OSError:
                pass
