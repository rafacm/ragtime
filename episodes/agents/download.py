"""Pydantic AI agent that drives the Download pipeline step.

Invoked by ``episodes.downloader`` as the fallback when the cheap
``wget`` path on the known ``audio_url`` fails (or no URL was
extracted by fetch-details). The agent has three classes of tools:

* podcast-index lookup — `lookup_podcast_index` fans out across
  fyyd / podcastindex.org and returns candidates with playable
  enclosure URLs.
* file fetch — `download_file` saves a known URL via the browser
  request context (shares cookies with any prior page navigation).
* Playwright browsing — navigation, find-audio-links, click,
  intercept-audio-requests, screenshot/visual analysis — for sites
  whose audio URL only appears after interaction.

The agent returns a structured ``DownloadAgentResult`` that
``download_episode`` translates into the step's
``DownloadResult`` / ``DownloadFailed``.
"""

import asyncio
import logging
import os
from datetime import date

from django.conf import settings
from pydantic_ai import Agent
from pydantic_ai.usage import UsageLimits

from . import download_tools as tools
from ._model import build_model
from .download_browser import download_browser
from .download_deps import DownloadAgentResult, DownloadDeps

logger = logging.getLogger(__name__)

DOWNLOAD_SYSTEM_PROMPT = """\
You are the download agent for the RAGtime podcast ingestion pipeline.
Your job is to obtain the audio file (MP3) for a podcast episode whose
publisher page does not yield an audio URL via a simple HTTP fetch.

Episode context:
- Episode URL: {episode_url}
- Title: {title}
- Show: {show_name}
- Published: {published_at}
- GUID hint: {guid}
- Known audio URL (failed wget): {audio_url}
- Language: {language}

Strategy (try in this order, escalate only if a step fails):

1. Call `lookup_podcast_index` with the title/show/guid hints.
   Podcast indexes (fyyd, podcastindex.org) often carry the
   publisher's RSS-feed enclosure URL even when the publisher's
   page hides it behind interactive UI.

   Picking the right candidate:
   - The episode's `Show` value above may be a publisher hostname
     rather than the broadcast title — for example
     `www.ardsounds.de` instead of `Zeitzeichen`. Detect this:
     when `Show` contains a `.` and no spaces, treat it as a
     hostname and do NOT require an exact string match against
     the candidate's `show_name`.
   - For hostname-shaped `Show` values, prefer matching candidates
     by `(title, published_at)` instead. A candidate is a strong
     match when its `title` is essentially the same as the
     episode `Title` (allowing for trailing punctuation, suffixes
     like `" | Podcast"`, etc.) AND its `published_at` is within
     ±1 day of the episode `Published` value.
   - For real show titles, an exact / fuzzy match on
     `show_name` plus a similar episode `title` is enough.
   - When `Published` is unknown, fall back to title similarity
     alone — do not reject a clear title match just because the
     date is missing on either side.

   When you find a strong match, call `download_file` on its
   `audio_url`. On success, return success with `source` set to
   the candidate's `source_index` (e.g. "fyyd").

2. If no index candidates look right, navigate to the episode
   page with `navigate_to_url`, then use `find_audio_links` to
   discover MP3 URLs in the rendered DOM. Try `download_file`
   on each viable URL. On success, return success with
   `source` = "agent".

3. Audio downloads are sometimes hidden behind clickable UI
   elements (3-dot menus, "Download" / "Information" buttons).
   Use `click_element`, `analyze_screenshot`, and
   `click_at_coordinates` to reveal them. Use
   `intercept_audio_requests` to capture streaming URLs that
   never appear in the static HTML.

4. Take a `take_screenshot` after each meaningful UI interaction
   so debugging traces have visual context.

Return success only when `download_file` succeeded. Otherwise
return success=False with a brief explanation in `message`.
"""

LANGUAGE_SECTION = """
Language: {language_name}
The episode page is in {language_name}. Before clicking elements by
text, use the `translate_text` tool to translate the labels you
expect to encounter ("Information", "More information", "Download")
into {language_name}, then use the translated strings in your
selectors.
"""

ENGLISH_LANGUAGE_SECTION = """
Language: English
Audio downloads are sometimes hidden behind UI elements labeled
"Information", "More information", or "Download". Use these labels
directly in your selectors.
"""


def _build_agent() -> Agent[DownloadDeps, DownloadAgentResult]:
    from .. import telemetry

    model_string = getattr(
        settings, "RAGTIME_DOWNLOAD_AGENT_MODEL", "openai:gpt-4.1-mini"
    )
    api_key = getattr(settings, "RAGTIME_DOWNLOAD_AGENT_API_KEY", "")
    model = build_model(model_string, api_key)

    kwargs = dict(
        deps_type=DownloadDeps,
        output_type=DownloadAgentResult,
    )
    if telemetry.is_enabled():
        kwargs["instrument"] = True

    agent = Agent(model, **kwargs)

    agent.tool(tools.lookup_podcast_index)
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


def _get_system_prompt(deps: DownloadDeps) -> str:
    from ..languages import ISO_639_LANGUAGE_NAMES, ISO_639_RE

    published_at_str = (
        deps.published_at.isoformat() if deps.published_at else "(unknown)"
    )
    prompt = DOWNLOAD_SYSTEM_PROMPT.format(
        episode_url=deps.episode_url,
        title=deps.title or "(unknown)",
        show_name=deps.show_name or "(unknown)",
        published_at=published_at_str,
        guid=deps.guid or "(none)",
        audio_url=deps.audio_url or "(none)",
        language=deps.language or "(unknown)",
    )

    if deps.language and ISO_639_RE.match(deps.language):
        if deps.language == "en":
            prompt += ENGLISH_LANGUAGE_SECTION
        else:
            language_name = ISO_639_LANGUAGE_NAMES.get(deps.language, deps.language)
            prompt += LANGUAGE_SECTION.format(language_name=language_name)

    return prompt


async def _run_agent_async(
    episode_id: int,
    episode_url: str,
    audio_url: str,
    title: str,
    show_name: str,
    guid: str,
    language: str,
    published_at: date | None = None,
) -> DownloadAgentResult:
    import shutil
    import tempfile

    timeout = getattr(settings, "RAGTIME_DOWNLOAD_AGENT_TIMEOUT", 120)

    with tempfile.TemporaryDirectory(prefix="ragtime-download-") as download_dir:
        async with download_browser(download_dir) as page:
            deps = DownloadDeps(
                episode_id=episode_id,
                episode_url=episode_url,
                audio_url=audio_url,
                title=title,
                show_name=show_name,
                guid=guid,
                language=language,
                download_dir=download_dir,
                page=page,
                screenshots=[],
                published_at=published_at,
            )

            system_prompt = _get_system_prompt(deps)
            agent = _build_agent()

            result = await asyncio.wait_for(
                _run_with_tracing(agent, system_prompt, deps, episode_id),
                timeout=timeout,
            )

            output = result.output

            # Move the downloaded file out of the temp dir before it's
            # cleaned up so the orchestrator can attach it to the episode.
            if output.downloaded_file and os.path.isfile(output.downloaded_file):
                try:
                    fd, stable_path = tempfile.mkstemp(
                        suffix=".mp3", prefix="ragtime-downloaded-"
                    )
                    os.close(fd)
                    os.unlink(stable_path)
                    shutil.move(output.downloaded_file, stable_path)
                    output.downloaded_file = stable_path
                except OSError:
                    logger.warning(
                        "Failed to persist downloaded file for episode %s; "
                        "orchestrator will fall back to audio_url",
                        episode_id,
                        exc_info=True,
                    )
                    output.downloaded_file = ""

            return output


async def _run_with_tracing(agent, system_prompt, deps, episode_id):
    """Run the agent with OTel tracing and optional Langfuse attributes."""
    from datetime import datetime

    from .. import telemetry

    run_kwargs = dict(
        user_prompt=system_prompt,
        deps=deps,
        usage_limits=UsageLimits(request_limit=30),
    )

    if telemetry.is_enabled():
        from opentelemetry.context import attach, detach
        from opentelemetry.context import Context as OTelContext

        token = attach(OTelContext())

        try:
            tracer = telemetry.get_tracer("ragtime.download")
            ts = datetime.now().strftime("%Y-%m-%d-%H-%M")
            session_id = f"download-episode-{episode_id}-{ts}"
            user_id = f"episode-{episode_id}"
            metadata = {"episode_id": str(episode_id)}

            attributes = {
                "ragtime.session.id": session_id,
                "ragtime.episode.id": str(episode_id),
                "ragtime.step.name": "downloading",
            }

            with tracer.start_as_current_span(
                "download_agent", attributes=attributes
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
                            _attach_screenshots(deps.screenshots, episode_id)
                            return result
                    except ImportError:
                        pass

                result = await agent.run(**run_kwargs)
                _attach_screenshots(deps.screenshots, episode_id)
                return result
        finally:
            detach(token)

    return await agent.run(**run_kwargs)


def _attach_screenshots(screenshots: list[bytes], episode_id: int):
    """Attach screenshots as OTel span events and Langfuse media."""
    if not screenshots:
        return

    from .. import telemetry

    if telemetry.is_enabled():
        from opentelemetry import trace

        span = trace.get_current_span()
        for i, png in enumerate(screenshots):
            span.add_event(
                f"download-screenshot-{i}",
                attributes={
                    "episode_id": episode_id,
                    "screenshot_index": i,
                    "screenshot_size": len(png),
                },
            )

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
                    name=f"download-screenshot-{i}",
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


def run_download_agent(
    episode_id: int,
    episode_url: str,
    audio_url: str = "",
    title: str = "",
    show_name: str = "",
    guid: str = "",
    language: str = "",
    published_at: date | None = None,
) -> DownloadAgentResult:
    """Run the download agent synchronously (entry point from the step)."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    try:
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(
                    asyncio.run,
                    _run_agent_async(
                        episode_id, episode_url, audio_url,
                        title, show_name, guid, language, published_at,
                    ),
                ).result()
        return asyncio.run(
            _run_agent_async(
                episode_id, episode_url, audio_url,
                title, show_name, guid, language, published_at,
            )
        )
    finally:
        _flush_traces()
