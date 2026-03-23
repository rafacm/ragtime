"""Resume pipeline after successful agent recovery."""

import logging
import os

from django.core.files import File
from mutagen.mp3 import MP3

from ..events import StepFailureEvent
from ..models import Episode
from ..processing import create_run
from .deps import RecoveryAgentResult

logger = logging.getLogger(__name__)


def resume_pipeline(event: StepFailureEvent, result: RecoveryAgentResult) -> bool:
    """Resume the pipeline after a successful recovery.

    For scraping recovery: sets the audio URL and resumes from downloading,
    or from transcribing if the agent also downloaded the file.
    For download recovery: saves the file, extracts duration, resumes from transcribing.

    Returns True if the pipeline was actually resumed, False otherwise.
    """
    episode = Episode.objects.get(pk=event.episode_id)

    if event.step_name == "scraping":
        return _resume_from_scraping(episode, result)
    elif event.step_name == "downloading":
        return _resume_from_downloading(episode, result)
    else:
        logger.error("Cannot resume from step: %s", event.step_name)
        return False


def _save_audio_file(episode: Episode, filepath: str) -> None:
    """Save a downloaded MP3 file to the episode and extract its duration."""
    filename = f"{episode.pk}.mp3"
    with open(filepath, "rb") as f:
        episode.audio_file.save(filename, File(f), save=False)

    audio = MP3(episode.audio_file.path)
    episode.duration = int(audio.info.length)


def _resume_from_scraping(episode: Episode, result: RecoveryAgentResult) -> bool:
    """Set audio URL and restart pipeline from downloading (or transcribing)."""
    if not result.audio_url:
        logger.error(
            "Scraping recovery for episode %s returned empty audio_url", episode.pk
        )
        return False

    episode.audio_url = result.audio_url
    episode.error_message = ""

    # When the agent also downloaded the file, skip the download step entirely.
    # On failure, fall through to the DOWNLOADING resume path below.
    if result.downloaded_file and os.path.isfile(result.downloaded_file):
        try:
            _save_audio_file(episode, result.downloaded_file)

            create_run(episode, resume_from=Episode.Status.TRANSCRIBING)

            episode.status = Episode.Status.TRANSCRIBING
            episode.save(
                update_fields=[
                    "audio_url", "audio_file", "duration",
                    "status", "error_message", "updated_at",
                ]
            )

            logger.info(
                "Scraping recovery succeeded for episode %s — audio_url=%s, "
                "file already downloaded, resuming from transcribing",
                episode.pk,
                result.audio_url,
            )
            # Clean up temp file only after successful save
            try:
                os.unlink(result.downloaded_file)
            except OSError:
                pass
            return True
        except Exception:
            logger.warning(
                "Failed to save downloaded file for episode %s, "
                "falling back to downloading",
                episode.pk,
                exc_info=True,
            )

    # No downloaded file — resume from downloading (wget will fetch the URL).
    create_run(episode, resume_from=Episode.Status.DOWNLOADING)

    episode.status = Episode.Status.DOWNLOADING
    episode.save(update_fields=["audio_url", "status", "error_message", "updated_at"])

    logger.info(
        "Scraping recovery succeeded for episode %s — audio_url=%s, resuming from downloading",
        episode.pk,
        result.audio_url,
    )
    return True


def _resume_from_downloading(episode: Episode, result: RecoveryAgentResult) -> bool:
    """Save downloaded file, extract duration, restart from transcribing."""
    if not result.downloaded_file:
        logger.error(
            "Download recovery for episode %s returned empty downloaded_file",
            episode.pk,
        )
        return False

    filepath = result.downloaded_file

    try:
        _save_audio_file(episode, filepath)
        episode.error_message = ""

        # Create run BEFORE saving status to avoid race with post_save signal
        create_run(episode, resume_from=Episode.Status.TRANSCRIBING)

        episode.status = Episode.Status.TRANSCRIBING
        episode.save(
            update_fields=["audio_file", "duration", "status", "error_message", "updated_at"]
        )

        logger.info(
            "Download recovery succeeded for episode %s — file=%s, duration=%ss, resuming from transcribing",
            episode.pk,
            f"{episode.pk}.mp3",
            episode.duration,
        )
        return True
    finally:
        # Clean up the temp file from the agent download
        try:
            os.unlink(filepath)
        except OSError:
            pass
