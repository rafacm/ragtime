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

RECOVERY_SYSTEM_PROMPT = """\
You are a recovery agent for the RAGtime podcast ingestion pipeline.
A pipeline step failed while processing a podcast episode. Your job is to
browse the episode page, find the audio file URL, and download it if needed.

Context:
- Episode URL: {episode_url}
- Failed step: {step_name}
- Error: {error_message}
- Known audio URL: {audio_url}
- HTTP status: {http_status}

IMPORTANT: Take a screenshot after EVERY action you perform (navigation, click,
download attempt, etc.). This is critical for debugging and observability.

Strategy:
1. Navigate to the episode page URL first (this sets cookies and session state).
2. If an audio URL is already known, navigate to it directly — the browser
   cookies from step 1 often make the download work.
3. If no audio URL is known, or the known URL fails, use find_audio_links to
   locate audio URLs on the page.
4. Audio downloads are sometimes hidden behind UI elements labeled
   "Information", "More information", or "Download". Try clicking these
   to reveal audio players or download links.
5. If you find a working URL, use download_file to save it.
6. Return the audio URL and/or downloaded file path if successful, or explain
   why recovery failed.
"""

LANGUAGE_SECTION = """
Language: {language_name}
The episode page is in {language_name}. UI labels like "Information",
"More information", "Download", or similar words will appear in {language_name}.
Use the translate_text tool to translate these labels if the page is not in English.
"""


def _build_model():
    """Build a Pydantic AI model from settings.

    Passes the API key directly to the provider constructor instead of
    mutating ``os.environ``, so credentials don't leak to other tasks
    in long-lived Django Q workers.
    """
    from pydantic_ai.providers.openai import OpenAIProvider

    model_str = getattr(settings, "RAGTIME_RECOVERY_AGENT_MODEL", "openai:gpt-4.1-mini")
    api_key = getattr(settings, "RAGTIME_RECOVERY_AGENT_API_KEY", "")

    if not api_key:
        # No explicit key — let Pydantic AI resolve from its own env vars
        return model_str

    provider_name = model_str.split(":")[0] if ":" in model_str else "openai"
    model_name = model_str.split(":", 1)[1] if ":" in model_str else model_str

    if provider_name == "openai":
        from pydantic_ai.models.openai import OpenAIResponsesModel

        return OpenAIResponsesModel(model_name, provider=OpenAIProvider(api_key=api_key))

    # For other providers, fall back to env var (they may not be installed)
    env_key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    env_var = env_key_map.get(provider_name)
    if env_var:
        _prev = os.environ.get(env_var)
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
    agent.tool(tools.translate_text)

    return agent


def _get_system_prompt(deps: RecoveryDeps) -> str:
    """Format the unified recovery system prompt."""
    from ..languages import ISO_639_LANGUAGE_NAMES

    prompt = RECOVERY_SYSTEM_PROMPT.format(
        episode_url=deps.episode_url,
        step_name=deps.step_name,
        error_message=deps.error_message,
        audio_url=deps.audio_url or "N/A",
        http_status=deps.http_status or "N/A",
    )

    language_name = ISO_639_LANGUAGE_NAMES.get(deps.language, "")
    if language_name:
        prompt += LANGUAGE_SECTION.format(language_name=language_name)

    return prompt


async def _run_agent_async(event: StepFailureEvent) -> RecoveryAgentResult:
    """Async implementation of agent recovery."""
    import tempfile

    episode = await Episode.objects.aget(pk=event.episode_id)
    timeout = getattr(settings, "RAGTIME_RECOVERY_AGENT_TIMEOUT", 120)

    with tempfile.TemporaryDirectory(prefix="ragtime-recovery-") as download_dir:
        async with recovery_browser(download_dir) as page:
            deps = RecoveryDeps(
                episode_id=event.episode_id,
                episode_url=episode.url,
                audio_url=episode.audio_url or "",
                language=episode.language or "",
                step_name=event.step_name,
                error_message=event.error_message,
                http_status=event.http_status,
                download_dir=download_dir,
                page=page,
                screenshots=[],
            )

            system_prompt = _get_system_prompt(deps)
            agent = _build_agent()

            result = await asyncio.wait_for(
                _run_with_langfuse(agent, system_prompt, deps, event),
                timeout=timeout,
            )

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
