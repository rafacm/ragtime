import logging

from .models import Episode
from .providers.factory import get_summarization_provider

logger = logging.getLogger(__name__)

SUMMARIZE_SYSTEM_PROMPT = (
    "You are an expert podcast summarizer specializing in jazz music. "
    "Given a transcript of a jazz podcast episode, write a concise summary that includes:\n"
    "- The language the episode is in\n"
    "- The key topics discussed\n"
    "- Artists, bands, albums, and musical works mentioned\n"
    "- Musical context, historical background, and stylistic connections\n\n"
    "Write in clear, flowing prose. Do not use bullet points or lists. "
    "Keep the summary to 2-4 paragraphs."
)


def summarize_episode(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.SUMMARIZING:
        logger.warning(
            "Episode %s has status '%s', expected 'summarizing'",
            episode_id,
            episode.status,
        )
        return

    if not episode.transcript:
        episode.error_message = "No transcript to summarize"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        return

    try:
        provider = get_summarization_provider()
        summary = provider.generate(
            system_prompt=SUMMARIZE_SYSTEM_PROMPT,
            user_content=episode.transcript,
        )

        episode.summary_generated = summary
        episode.status = Episode.Status.EXTRACTING
        episode.save(
            update_fields=["status", "summary_generated", "updated_at"]
        )
    except Exception as exc:
        logger.exception("Failed to summarize episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
