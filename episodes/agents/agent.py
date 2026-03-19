"""Pydantic AI agent for recovering from scraping and downloading failures."""

import asyncio
import logging
import os

from django.conf import settings
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from ..events import StepFailureEvent
from ..models import Episode
from . import tools
from .browser import recovery_browser
from .deps import RecoveryAgentResult, RecoveryDeps

logger = logging.getLogger(__name__)

SCRAPING_SYSTEM_PROMPT = """\
You are a recovery agent for the RAGtime podcast ingestion pipeline.

A scraping step failed — the system could not extract the audio URL from the
podcast episode page. Your job is to browse the page, find the audio file URL,
and return it.

Strategy:
1. Navigate to the episode page URL.
2. Look for audio links using find_audio_links.
3. If no links found, inspect the page content and try clicking play buttons
   or expanding hidden players.
4. Take screenshots for debugging when stuck.
5. Return the audio URL if found, or explain why recovery failed.

Episode URL: {episode_url}
Error: {error_message}
"""

DOWNLOADING_SYSTEM_PROMPT = """\
You are a recovery agent for the RAGtime podcast ingestion pipeline.

A download step failed — the system could not download the audio file.
Your job is to find an alternative download URL or download the file through
the browser.

Strategy:
1. Navigate to the episode page to find the audio URL.
2. Try find_audio_links to locate alternative audio URLs.
3. If you find a working URL, use download_file to save it.
4. Take screenshots for debugging when stuck.
5. Return the downloaded file path if successful, or explain why recovery failed.

Episode URL: {episode_url}
Audio URL that failed: {audio_url}
Error: {error_message}
HTTP status: {http_status}
"""


def _build_model():
    """Build the Pydantic AI model from settings."""
    model_str = getattr(settings, "RAGTIME_RECOVERY_AGENT_MODEL", "openai:gpt-4.1-mini")
    api_key = getattr(settings, "RAGTIME_RECOVERY_AGENT_API_KEY", "")

    # Parse provider prefix to determine which API key env var to set
    provider = model_str.split(":")[0] if ":" in model_str else "openai"

    # Set the API key in the environment for Pydantic AI's model constructor
    env_key_map = {
        "openai": "OPENAI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    env_var = env_key_map.get(provider)
    if api_key and env_var:
        os.environ[env_var] = api_key

    return model_str


def _build_agent() -> Agent[RecoveryDeps, RecoveryAgentResult]:
    """Create and configure the recovery agent."""
    from .. import observability

    model = _build_model()

    kwargs = dict(
        deps_type=RecoveryDeps,
        output_type=RecoveryAgentResult,
    )

    # Enable OTel instrumentation when Langfuse is active
    if observability.is_enabled():
        kwargs["instrument"] = True

    agent = Agent(model, **kwargs)

    # Register tools
    agent.tool(tools.navigate_to_url)
    agent.tool(tools.get_page_content)
    agent.tool(tools.find_audio_links)
    agent.tool(tools.click_element)
    agent.tool(tools.take_screenshot)
    agent.tool(tools.download_file)
    agent.tool(tools.extract_text_by_selector)

    return agent


def _get_system_prompt(deps: RecoveryDeps) -> str:
    """Select and format the system prompt based on the failure step."""
    if deps.step_name == "scraping":
        return SCRAPING_SYSTEM_PROMPT.format(
            episode_url=deps.episode_url,
            error_message=deps.error_message,
        )
    return DOWNLOADING_SYSTEM_PROMPT.format(
        episode_url=deps.episode_url,
        audio_url=deps.audio_url,
        error_message=deps.error_message,
        http_status=deps.http_status or "N/A",
    )


async def _run_agent_async(event: StepFailureEvent) -> RecoveryAgentResult:
    """Async implementation of agent recovery."""
    episode = await Episode.objects.aget(pk=event.episode_id)
    download_dir = str(settings.MEDIA_ROOT / "episodes")
    os.makedirs(download_dir, exist_ok=True)

    timeout = getattr(settings, "RAGTIME_RECOVERY_AGENT_TIMEOUT", 120)

    async with recovery_browser(download_dir) as page:
        deps = RecoveryDeps(
            episode_id=event.episode_id,
            episode_url=episode.url,
            audio_url=episode.audio_url or "",
            step_name=event.step_name,
            error_message=event.error_message,
            http_status=event.http_status,
            download_dir=download_dir,
            page=page,
            screenshots=[],
        )

        system_prompt = _get_system_prompt(deps)
        agent = _build_agent()

        result = await _run_with_langfuse(agent, system_prompt, deps, event)

        return result.output


async def _run_with_langfuse(agent, system_prompt, deps, event):
    """Run the agent, propagating Langfuse session/user attributes when enabled.

    Screenshots are attached inside the trace context so they appear as
    child events of the recovery trace.
    """
    from .. import observability

    run_kwargs = dict(
        user_prompt=system_prompt,
        deps=deps,
        usage_limits=UsageLimits(request_limit=15),
    )

    if observability.is_enabled():
        try:
            from langfuse import propagate_attributes

            session_id = (
                f"recovery-run-{event.processing_run_id}-episode-{event.episode_id}"
                f"-attempt-{event.attempt_number}"
            )
            user_id = f"episode-{event.episode_id}"
            metadata = {
                "episode_id": str(event.episode_id),
                "step_name": event.step_name,
                "error_type": event.error_type,
                "attempt_number": str(event.attempt_number),
            }

            with propagate_attributes(
                session_id=session_id, user_id=user_id, metadata=metadata
            ):
                result = await agent.run(**run_kwargs)
                _attach_screenshots(deps.screenshots, event.episode_id)
                return result
        except ImportError:
            pass

    return await agent.run(**run_kwargs)


def _attach_screenshots(screenshots: list[bytes], episode_id: int):
    """Attach screenshots as Langfuse events with media content.

    Must be called inside a ``propagate_attributes`` context so events
    are associated with the current trace.
    """
    if not screenshots:
        return

    try:
        import langfuse
        from langfuse.media import LangfuseMedia

        client = langfuse.get_client()
        for i, png in enumerate(screenshots):
            media = LangfuseMedia(
                content_bytes=png,
                content_type="image/png",
            )
            client.create_event(
                name=f"recovery-screenshot-{i}",
                input=media,
                metadata={
                    "episode_id": episode_id,
                    "screenshot_index": i,
                    "screenshot_size": len(png),
                },
            )
    except Exception:
        logger.debug("Failed to attach screenshots to Langfuse", exc_info=True)


def _flush_langfuse():
    """Flush buffered Langfuse/OTel traces so they reach the server."""
    from .. import observability

    if not observability.is_enabled():
        return
    try:
        import langfuse

        client = langfuse.get_client()
        client.flush()
    except Exception:
        logger.debug("Failed to flush Langfuse traces", exc_info=True)


def run_recovery_agent(event: StepFailureEvent) -> RecoveryAgentResult:
    """Run the recovery agent synchronously.

    Entry point called from ``AgentStrategy.attempt()``.
    Creates a new event loop if needed (Django Q2 workers may not have one).
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            # Already in an async context — create a new thread
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run, _run_agent_async(event)
                ).result()
        else:
            return asyncio.run(_run_agent_async(event))
    finally:
        _flush_langfuse()
