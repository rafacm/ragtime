import logging

from .languages import ISO_639_LANGUAGE_NAMES, ISO_639_RE
from .models import Episode
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_summarization_provider

logger = logging.getLogger(__name__)

_BASE_SYSTEM_PROMPT = (
    "You are an expert podcast summarizer specializing in jazz music. "
    "Given a transcript of a jazz podcast episode, write a concise summary that includes:\n"
    "- The key topics discussed\n"
    "- Artists, bands, albums, and musical works mentioned\n"
    "- Musical context, historical background, and stylistic connections\n\n"
    "Write in clear, flowing prose. Do not use bullet points or lists. "
    "Keep the summary to 2-4 paragraphs."
)

_FALLBACK_INSTRUCTION = (
    "Write the summary in the same language as the transcript."
)


def build_system_prompt(language: str) -> str:
    if language and ISO_639_RE.match(language):
        lang_name = ISO_639_LANGUAGE_NAMES.get(language, language)
        return f"{_BASE_SYSTEM_PROMPT}\nWrite the summary in {lang_name}."
    return f"{_BASE_SYSTEM_PROMPT}\n{_FALLBACK_INSTRUCTION}"


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

    start_step(episode, Episode.Status.SUMMARIZING)

    if not episode.transcript:
        episode.error_message = "No transcript to summarize"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.SUMMARIZING, "No transcript to summarize")
        return

    try:
        provider = get_summarization_provider()
        system_prompt = build_system_prompt(episode.language)
        summary = provider.generate(
            system_prompt=system_prompt,
            user_content=episode.transcript,
        )

        episode.summary_generated = summary
        complete_step(episode, Episode.Status.SUMMARIZING)
        episode.status = Episode.Status.CHUNKING
        episode.save(
            update_fields=["status", "summary_generated", "updated_at"]
        )
    except Exception as exc:
        logger.exception("Failed to summarize episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.SUMMARIZING, str(exc))
