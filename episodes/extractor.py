import logging
from pathlib import Path

import yaml

from .languages import ISO_639_LANGUAGE_NAMES, ISO_639_RE
from .models import Episode
from .processing import complete_step, fail_step, start_step
from .providers.factory import get_extraction_provider

logger = logging.getLogger(__name__)

_ENTITY_TYPES_PATH = Path(__file__).parent / "entity_types.yaml"

with open(_ENTITY_TYPES_PATH) as _f:
    ENTITY_TYPES: list[dict] = yaml.safe_load(_f)

_BASE_SYSTEM_PROMPT = (
    "You are an expert entity extractor specializing in jazz music podcasts.\n"
    "Given a podcast transcript, extract all mentioned entities organized by type.\n\n"
    "Entity types to extract:\n"
)

for _et in ENTITY_TYPES:
    _BASE_SYSTEM_PROMPT += f"- {_et['name']}: {_et['description']} Examples: {_et['examples']}\n"

_BASE_SYSTEM_PROMPT += (
    "\nRules:\n"
    "- Extract entities exactly as they appear in the transcript\n"
    "- For each entity, include a \"name\" field and an optional \"context\" field "
    "with a brief note about how it was mentioned\n"
    "- If no entities of a given type are found, return null for that type\n"
    "- Entity type keys must be in English (snake_case), but entity names should "
    "preserve the original language from the transcript"
)

_FALLBACK_INSTRUCTION = (
    "Extract entity names as they appear in the transcript."
)


def build_system_prompt(language: str) -> str:
    if language and ISO_639_RE.match(language):
        lang_name = ISO_639_LANGUAGE_NAMES.get(language, language)
        return (
            f"{_BASE_SYSTEM_PROMPT}\n"
            f"The transcript is in {lang_name}. "
            "Extract entity names as they appear in the transcript."
        )
    return f"{_BASE_SYSTEM_PROMPT}\n{_FALLBACK_INSTRUCTION}"


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
    for et in ENTITY_TYPES:
        key = et["key"]
        properties[key] = {
            "type": ["array", "null"],
            "items": entity_item_schema,
        }
        required.append(key)

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

    if not episode.transcript:
        episode.error_message = "No transcript to extract entities from"
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.EXTRACTING, "No transcript to extract entities from")
        return

    try:
        provider = get_extraction_provider()
        system_prompt = build_system_prompt(episode.language)
        schema = build_response_schema()
        entities = provider.structured_extract(
            system_prompt=system_prompt,
            user_content=episode.transcript,
            response_schema=schema,
        )

        episode.entities_json = entities
        complete_step(episode, Episode.Status.EXTRACTING)
        episode.status = Episode.Status.RESOLVING
        episode.save(
            update_fields=["status", "entities_json", "updated_at"]
        )
    except Exception as exc:
        logger.exception("Failed to extract entities for episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.EXTRACTING, str(exc))
