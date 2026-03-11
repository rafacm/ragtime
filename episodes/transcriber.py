import logging

from .models import Episode
from .providers.factory import get_transcription_provider

logger = logging.getLogger(__name__)


def transcribe_episode(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.TRANSCRIBING:
        logger.warning(
            "Episode %s has status '%s', expected 'transcribing'",
            episode_id,
            episode.status,
        )
        return

    if not episode.audio_file:
        episode.error_message = "No audio file to transcribe"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        return

    try:
        provider = get_transcription_provider()
        language = episode.language or None
        result = provider.transcribe(episode.audio_file.path, language=language)

        episode.transcript_json = result
        episode.transcript = result.get("text", "")
        episode.status = Episode.Status.SUMMARIZING
        episode.save(
            update_fields=[
                "status",
                "transcript",
                "transcript_json",
                "updated_at",
            ]
        )
    except Exception as exc:
        logger.exception("Failed to transcribe episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
