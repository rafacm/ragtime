"""Pydantic AI agent for linking entities to Wikidata Q-IDs.

Runs asynchronously after the resolve pipeline step completes.
Not a pipeline step itself — does not block episode processing.
"""

import asyncio
import logging
import os

from django.conf import settings
from django_q.tasks import async_task
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from ..models import Entity, EntityType, Episode
from . import linker_tools
from .linker_deps import LinkingAgentResult, LinkingDeps

logger = logging.getLogger(__name__)

LINKING_SYSTEM_PROMPT = """\
You are a Wikidata linking agent for the RAGtime jazz podcast pipeline.

Your job is to link entities (musicians, albums, venues, etc.) to their
Wikidata Q-IDs. For each entity below, use the search_wikidata tool to
find candidates, then either:
- Use link_entity to assign the best matching Q-ID
- Use mark_failed if no candidate is a good match
- Use skip_entity if the entity type has no Wikidata class Q-ID

Guidelines:
- Only link when confident the candidate refers to the same real-world entity
- Pay attention to entity type — a "Blue Note" venue is different from
  the "Blue Note" record label
- For musicians: match by name, instrument, and era when disambiguating
- For albums: match by name and artist when possible
- If multiple candidates are plausible, prefer the one whose description
  mentions jazz or music
- Process every entity in the batch — do not skip any

Entities to link:
{entities_text}
"""


def _build_model():
    """Build a Pydantic AI model from settings."""
    from pydantic_ai.providers.openai import OpenAIProvider

    model_str = getattr(settings, "RAGTIME_LINKING_AGENT_MODEL", "openai:gpt-4.1-mini")
    api_key = getattr(settings, "RAGTIME_LINKING_AGENT_API_KEY", "")

    if not api_key:
        return model_str

    provider_name = model_str.split(":")[0] if ":" in model_str else "openai"
    model_name = model_str.split(":", 1)[1] if ":" in model_str else model_str

    if provider_name == "openai":
        from pydantic_ai.models.openai import OpenAIResponsesModel

        return OpenAIResponsesModel(model_name, provider=OpenAIProvider(api_key=api_key))

    env_key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    env_var = env_key_map.get(provider_name)
    if env_var:
        os.environ[env_var] = api_key
    return model_str


def _build_agent() -> Agent[LinkingDeps, LinkingAgentResult]:
    """Create and configure the linking agent."""
    from .. import observability

    model = _build_model()

    kwargs = dict(
        deps_type=LinkingDeps,
        output_type=LinkingAgentResult,
    )

    if observability.is_enabled():
        kwargs["instrument"] = True

    agent = Agent(model, **kwargs)

    agent.tool(linker_tools.search_wikidata)
    agent.tool(linker_tools.link_entity)
    agent.tool(linker_tools.mark_failed)
    agent.tool(linker_tools.skip_entity)

    return agent


def _format_entities_for_prompt(entities) -> str:
    """Format a batch of entities for the system prompt."""
    lines = []
    for entity in entities:
        type_qid = entity.entity_type.wikidata_id or "none"
        lines.append(
            f"- ID {entity.pk}: \"{entity.name}\" "
            f"(type: {entity.entity_type.name}, type Q-ID: {type_qid})"
        )
    return "\n".join(lines)


async def _run_linking_agent_async(entities) -> LinkingAgentResult:
    """Run the linking agent on a batch of entities."""
    entities_text = _format_entities_for_prompt(entities)
    system_prompt = LINKING_SYSTEM_PROMPT.format(entities_text=entities_text)

    deps = LinkingDeps()
    agent = _build_agent()

    result = await agent.run(
        user_prompt=system_prompt,
        deps=deps,
        usage_limits=UsageLimits(request_limit=50),
    )

    output = result.output
    output.linked = deps.linked_count
    output.failed = deps.failed_count
    output.skipped = deps.skipped_count
    return output


def run_linking_agent() -> None:
    """Run the linking agent on all pending entities.

    Entry point called from Django Q2 async_task or management command.
    Processes entities in batches to avoid overwhelming the LLM context.
    """
    enabled = getattr(settings, "RAGTIME_LINKING_AGENT_ENABLED", True)
    if not enabled:
        logger.info("Linking agent is disabled — skipping")
        return

    batch_size = getattr(settings, "RAGTIME_LINKING_AGENT_BATCH_SIZE", 50)

    # Skip entity types that have no Wikidata class Q-ID
    skippable_types = EntityType.objects.filter(wikidata_id="")
    skipped = Entity.objects.filter(
        linking_status=Entity.LinkingStatus.PENDING,
        entity_type__in=skippable_types,
    ).update(linking_status=Entity.LinkingStatus.SKIPPED)
    if skipped:
        logger.info("Skipped %d entities with no Wikidata entity type class", skipped)

    pending = list(
        Entity.objects.filter(linking_status=Entity.LinkingStatus.PENDING)
        .select_related("entity_type")
        .order_by("entity_type__key", "name")[:batch_size]
    )

    if not pending:
        logger.info("No pending entities to link")
        return

    logger.info("Linking %d pending entities", len(pending))

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                result = pool.submit(
                    asyncio.run, _run_linking_agent_async(pending)
                ).result()
        else:
            result = asyncio.run(_run_linking_agent_async(pending))

        logger.info(
            "Linking agent completed: %d linked, %d failed, %d skipped — %s",
            result.linked, result.failed, result.skipped, result.message,
        )
    except Exception:
        logger.exception("Linking agent failed")
    finally:
        _flush_langfuse()

    # If there are more pending entities, queue another run
    remaining = Entity.objects.filter(
        linking_status=Entity.LinkingStatus.PENDING
    ).count()
    if remaining > 0:
        logger.info("Queuing another linking run for %d remaining entities", remaining)
        async_task("episodes.agents.linker.run_linking_agent")


def _flush_langfuse():
    """Flush buffered Langfuse/OTel traces."""
    from .. import observability

    if not observability.is_enabled():
        return
    try:
        import langfuse

        client = langfuse.get_client()
        client.flush()
    except Exception:
        logger.debug("Failed to flush Langfuse traces", exc_info=True)


def handle_resolve_completed(sender, event, **kwargs):
    """Signal handler: trigger linking agent after resolve step completes."""
    if event.step_name != Episode.Status.RESOLVING:
        return

    enabled = getattr(settings, "RAGTIME_LINKING_AGENT_ENABLED", True)
    if not enabled:
        return

    pending_count = Entity.objects.filter(
        linking_status=Entity.LinkingStatus.PENDING,
    ).count()
    if pending_count > 0:
        logger.info(
            "Resolve completed — queuing linking agent for %d pending entities",
            pending_count,
        )
        async_task("episodes.agents.linker.run_linking_agent")
