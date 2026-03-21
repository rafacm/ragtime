import copy
import logging

from .languages import ISO_639_LANGUAGE_NAMES, ISO_639_RE
from .models import Chunk, EntityType, Episode
from .observability import observe_step
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_extraction_provider
from .timestamps import filter_words_for_chunk, find_entity_start_time

logger = logging.getLogger(__name__)

_BASE_SYSTEM_PROMPT = (
    "You are an expert entity extractor specializing in jazz music podcasts.\n"
    "Given a transcript excerpt, extract all mentioned entities organized by type.\n\n"
    "Entity types to extract:\n"
)

_FALLBACK_INSTRUCTION = (
    "Extract entity names as they appear in the transcript."
)


def _get_active_entity_types():
    return list(EntityType.objects.filter(is_active=True))


def build_system_prompt(language: str) -> str:
    prompt = _BASE_SYSTEM_PROMPT
    for et in _get_active_entity_types():
        examples = ", ".join(et.examples) if et.examples else ""
        prompt += f"- {et.name}: {et.description} Examples: {examples}\n"

    prompt += (
        "\nRules:\n"
        "- Extract entities exactly as they appear in the transcript\n"
        "- For each entity, include a \"name\" field and an optional \"context\" field "
        "with a brief note about how it was mentioned\n"
        "- If no entities of a given type are found, return null for that type\n"
        "- Entity type keys must be in English (snake_case), but entity names should "
        "preserve the original language from the transcript"
    )

    if language and ISO_639_RE.match(language):
        lang_name = ISO_639_LANGUAGE_NAMES.get(language, language)
        return (
            f"{prompt}\n"
            f"The transcript is in {lang_name}. "
            "Extract entity names as they appear in the transcript."
        )
    return f"{prompt}\n{_FALLBACK_INSTRUCTION}"


def build_response_schema() -> dict:
    entity_item_schema = {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "context": {"type": ["string", "null"]},
        },
        "required": ["name", "context"],
        "additionalProperties": False,
    }

    properties = {}
    required = []
    for et in _get_active_entity_types():
        properties[et.key] = {
            "type": ["array", "null"],
            "items": entity_item_schema,
        }
        required.append(et.key)

    return {
        "name": "episode_entities",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


def _annotate_timestamps(entities_json, chunk_words, chunk_start, has_words):
    """Add ``start_time`` to each entity dict in *entities_json*, in-place.

    *chunk_words* should be pre-filtered to the chunk's time range.
    *has_words* indicates whether the episode has word-level timestamps at all.
    When the episode has no word timestamps, falls back to ``chunk_start``.
    When words exist but none fall in this chunk's range, sets ``None``.
    """
    for _type_key, entities in entities_json.items():
        if entities is None:
            continue
        for entity in entities:
            if chunk_words:
                entity["start_time"] = find_entity_start_time(
                    entity["name"], chunk_words,
                )
            elif has_words:
                entity["start_time"] = None
            else:
                entity["start_time"] = chunk_start


@observe_step("extract_entities")
def extract_entities(episode_id: int) -> None:
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.EXTRACTING:
        logger.warning(
            "Episode %s has status '%s', expected 'extracting'",
            episode_id,
            episode.status,
        )
        return

    start_step(episode, Episode.Status.EXTRACTING)

    chunks = list(episode.chunks.order_by("index"))
    if not chunks:
        episode.error_message = "No chunks to extract entities from"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.EXTRACTING, "No chunks to extract entities from")
        return

    try:
        provider = get_extraction_provider()
        system_prompt = build_system_prompt(episode.language)
        schema = build_response_schema()
        transcript_json = episode.transcript_json or {}
        words = transcript_json.get("words", [])
        has_words = "words" in transcript_json

        for chunk in chunks:
            entities = copy.deepcopy(provider.structured_extract(
                system_prompt=system_prompt,
                user_content=chunk.text,
                response_schema=schema,
            ))
            chunk_words = filter_words_for_chunk(words, chunk.start_time, chunk.end_time)
            _annotate_timestamps(entities, chunk_words, chunk.start_time, has_words)
            chunk.entities_json = entities

        Chunk.objects.bulk_update(chunks, ["entities_json"])

        complete_step(episode, Episode.Status.EXTRACTING)
        episode.entities_json = None
        episode.status = Episode.Status.RESOLVING
        episode.save(update_fields=["status", "entities_json", "updated_at"])
    except Exception as exc:
        logger.exception("Failed to extract entities for episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.EXTRACTING, str(exc), exc=exc)
