"""Pydantic AI agent for recovering from fetch-details and downloading failures."""

import asyncio
import logging
import os

from django.conf import settings
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from ..events import StepFailureEvent
from ..models import Episode
from . import recovery_tools as tools
from ._model import build_model
from .recovery_browser import recovery_browser
from .recovery_deps import RecoveryAgentResult, RecoveryDeps

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
4. Audio downloads are sometimes hidden behind clickable UI elements.
   Try clicking buttons or links that might reveal audio players or
   download links.
5. If steps 3-4 fail, use visual analysis as a fallback:
   a. Use analyze_screenshot to visually inspect the page.
   b. Look for three-dot menus (⋮ or ⋯), play buttons, or audio players.
   c. Use click_at_coordinates to click on visually identified elements.
   d. Use intercept_audio_requests to capture audio URLs when clicking
      a play button — this catches streaming URLs that don't appear in HTML.
6. If you find a working URL, use download_file to save it.
7. Return the audio URL and/or downloaded file path if successful, or explain
   why recovery failed.
"""

LANGUAGE_SECTION = """
Language: {language_name}
The episode page is in {language_name}. Before trying to click any elements,
you MUST first use the translate_text tool to translate each of the following
English labels to {language_name}:
- "Information"
- "More information"
- "Download"

Then use the translated labels in your selectors to find and click elements.
Do NOT use the English words above directly — they will not match on the page.
"""

ENGLISH_LANGUAGE_SECTION = """
Language: English
The episode page is in English. Audio downloads are sometimes hidden behind
UI elements labeled "Information", "More information", or "Download".
Use these labels directly in your selectors to find and click elements.
"""


def _build_agent() -> Agent[RecoveryDeps, RecoveryAgentResult]:
    """Create and configure the recovery agent."""
    from .. import telemetry

    model_string = getattr(
        settings, "RAGTIME_RECOVERY_AGENT_MODEL", "openai:gpt-4.1-mini"
    )
    api_key = getattr(settings, "RAGTIME_RECOVERY_AGENT_API_KEY", "")
    model = build_model(model_string, api_key)

    kwargs = dict(
        deps_type=RecoveryDeps,
        output_type=RecoveryAgentResult,
    )

    # Enable OTel instrumentation when any collector is active
    if telemetry.is_enabled():
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
    agent.tool(tools.analyze_screenshot)
    agent.tool(tools.click_at_coordinates)
    agent.tool(tools.intercept_audio_requests)

    return agent


def _get_system_prompt(deps: RecoveryDeps) -> str:
    """Format the unified recovery system prompt."""
    from ..languages import ISO_639_LANGUAGE_NAMES, ISO_639_RE

    prompt = RECOVERY_SYSTEM_PROMPT.format(
        episode_url=deps.episode_url,
        step_name=deps.step_name,
        error_message=deps.error_message,
        audio_url=deps.audio_url or "N/A",
        http_status=deps.http_status or "N/A",
    )

    if deps.language and ISO_639_RE.match(deps.language):
        if deps.language == "en":
            prompt += ENGLISH_LANGUAGE_SECTION
        else:
            language_name = ISO_639_LANGUAGE_NAMES.get(deps.language, deps.language)
            prompt += LANGUAGE_SECTION.format(language_name=language_name)

    return prompt


async def _run_agent_async(event: StepFailureEvent) -> RecoveryAgentResult:
    """Async implementation of agent recovery."""
    import shutil
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
                _run_with_tracing(agent, system_prompt, deps, event),
                timeout=timeout,
            )

            output = result.output

            # Move downloaded file out of the temp dir before it's cleaned up,
            # so resume_pipeline() can still access it.  On failure, clear the
            # path so resume logic falls back to the audio_url-only path.
            if output.downloaded_file and os.path.isfile(output.downloaded_file):
                try:
                    fd, stable_path = tempfile.mkstemp(suffix=".mp3", prefix="ragtime-recovered-")
                    os.close(fd)
                    os.unlink(stable_path)
                    shutil.move(output.downloaded_file, stable_path)
                    output.downloaded_file = stable_path
                except OSError:
                    logger.warning(
                        "Failed to persist recovered file for episode %s, "
                        "resume will fall back to audio_url",
                        event.episode_id,
                        exc_info=True,
                    )
                    output.downloaded_file = ""

            return output


async def _run_with_tracing(agent, system_prompt, deps, event):
    """Run the agent with OTel tracing and optional Langfuse attributes.

    Detaches from the parent OTel context (e.g. the pipeline step trace)
    so the recovery agent gets its own independent trace.  Screenshots
    are attached inside the trace context so they appear as child events
    of the recovery trace.
    """
    from .. import telemetry

    run_kwargs = dict(
        user_prompt=system_prompt,
        deps=deps,
        usage_limits=UsageLimits(request_limit=30),
    )

    if telemetry.is_enabled():
        from opentelemetry.context import attach, detach
        from opentelemetry.context import Context as OTelContext

        # Detach from the parent trace (e.g. scrape_episode) so the
        # recovery agent creates its own root trace.
        token = attach(OTelContext())

        try:
            tracer = telemetry.get_tracer("ragtime.recovery")
            ts = event.timestamp.strftime("%Y-%m-%d-%H-%M")
            session_id = (
                f"recovery-run-{event.processing_run_id}-episode-{event.episode_id}"
                f"-attempt-{event.attempt_number}-{ts}"
            )
            user_id = f"episode-{event.episode_id}"
            metadata = {
                "episode_id": str(event.episode_id),
                "step_name": event.step_name,
                "error_type": event.error_type,
                "attempt_number": str(event.attempt_number),
            }

            attributes = {
                "ragtime.session.id": session_id,
                "ragtime.episode.id": str(event.episode_id),
                "ragtime.step.name": event.step_name,
                "ragtime.error.type": event.error_type,
                "ragtime.attempt.number": event.attempt_number,
            }

            with tracer.start_as_current_span(
                "recovery_agent", attributes=attributes
            ):
                if telemetry.is_langfuse_enabled():
                    try:
                        from langfuse import propagate_attributes

                        with propagate_attributes(
                            session_id=session_id,
                            user_id=user_id,
                            metadata=metadata,
                        ):
                            result = await agent.run(**run_kwargs)
                            _attach_screenshots(
                                deps.screenshots, event.episode_id
                            )
                            return result
                    except ImportError:
                        pass

                result = await agent.run(**run_kwargs)
                _attach_screenshots(deps.screenshots, event.episode_id)
                return result
        finally:
            detach(token)

    return await agent.run(**run_kwargs)


def _attach_screenshots(screenshots: list[bytes], episode_id: int):
    """Attach screenshots as OTel span events and optionally as Langfuse media.

    Must be called inside an active span context so events are associated
    with the current trace.
    """
    if not screenshots:
        return

    from .. import telemetry

    # Add OTel span events for all collectors (metadata only)
    if telemetry.is_enabled():
        from opentelemetry import trace

        span = trace.get_current_span()
        for i, png in enumerate(screenshots):
            span.add_event(
                f"recovery-screenshot-{i}",
                attributes={
                    "episode_id": episode_id,
                    "screenshot_index": i,
                    "screenshot_size": len(png),
                },
            )

    # Attach binary media to Langfuse if available
    if telemetry.is_langfuse_enabled():
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
            logger.debug(
                "Failed to attach screenshots to Langfuse", exc_info=True
            )


def _flush_traces():
    """Flush buffered OTel traces so they reach the collectors."""
    from .. import telemetry

    if not telemetry.is_enabled():
        return
    try:
        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush()
    except Exception:
        logger.debug("Failed to flush OTel traces", exc_info=True)


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
        _flush_traces()
