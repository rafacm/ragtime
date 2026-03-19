"""Resume pipeline after successful agent recovery."""

import logging

from django.core.files import File
from mutagen.mp3 import MP3

from ..events import StepFailureEvent
from ..models import Episode
from ..processing import create_run
from .deps import RecoveryAgentResult

logger = logging.getLogger(__name__)


def resume_pipeline(event: StepFailureEvent, result: RecoveryAgentResult):
    """Resume the pipeline after a successful recovery.

    For scraping recovery: sets the audio URL and resumes from downloading.
    For download recovery: saves the file, extracts duration, resumes from transcribing.
    """
    episode = Episode.objects.get(pk=event.episode_id)

    if event.step_name == "scraping":
        _resume_from_scraping(episode, result)
    elif event.step_name == "downloading":
        _resume_from_downloading(episode, result)
    else:
        logger.error("Cannot resume from step: %s", event.step_name)


def _resume_from_scraping(episode: Episode, result: RecoveryAgentResult):
    """Set audio URL and restart pipeline from downloading."""
    episode.audio_url = result.audio_url
    episode.status = Episode.Status.DOWNLOADING
    episode.error_message = ""
    episode.save(update_fields=["audio_url", "status", "error_message", "updated_at"])

    create_run(episode, resume_from=Episode.Status.DOWNLOADING)
    logger.info(
        "Scraping recovery succeeded for episode %s — audio_url=%s, resuming from downloading",
        episode.pk,
        result.audio_url,
    )


def _resume_from_downloading(episode: Episode, result: RecoveryAgentResult):
    """Save downloaded file, extract duration, restart from transcribing."""
    filepath = result.downloaded_file
    filename = f"{episode.pk}.mp3"

    with open(filepath, "rb") as f:
        episode.audio_file.save(filename, File(f), save=False)

    audio = MP3(episode.audio_file.path)
    episode.duration = int(audio.info.length)
    episode.status = Episode.Status.TRANSCRIBING
    episode.error_message = ""
    episode.save(
        update_fields=["audio_file", "duration", "status", "error_message", "updated_at"]
    )

    create_run(episode, resume_from=Episode.Status.TRANSCRIBING)
    logger.info(
        "Download recovery succeeded for episode %s — file=%s, duration=%ss, resuming from transcribing",
        episode.pk,
        filename,
        episode.duration,
    )
