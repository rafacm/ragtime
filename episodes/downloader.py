"""Download pipeline step.

Three-tier cascade:

1. **wget** — when ``episode.audio_url`` is set, fetch it directly.
   Sub-second on the happy path; no LLM cost.
2. **Download agent** — when wget fails (or no URL) the Pydantic AI
   download agent runs. Its tools include ``lookup_podcast_index``
   (fyyd / podcastindex.org), ``find_audio_links``, ``click_element``,
   ``intercept_audio_requests``, etc.
3. Failure — raises :class:`DownloadFailed` with structured detail.

The step records what happened by returning a typed ``DownloadResult``
on success and raising ``DownloadFailed`` on failure. DBOS records both
verbatim, replacing what the deleted ``PipelineEvent`` table used to
hold.
"""

from __future__ import annotations

import dataclasses
import logging
import os
import subprocess
import tempfile

from django.core.files import File
from mutagen.mp3 import MP3

from .models import Episode
from .processing import complete_step, fail_step, start_step

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 60  # 1 minute


@dataclasses.dataclass(frozen=True)
class DownloadResult:
    """Structured success result, persisted by DBOS as the step's output."""

    episode_id: int
    source: str  # "wget" | "fyyd" | "podcastindex" | "agent"
    audio_url: str
    bytes_downloaded: int


class DownloadFailed(Exception):
    """Structured failure raised when every tier of the cascade gives up.

    DBOS records the exception class + args verbatim — keeping the
    structured fields here means ``dbos workflow steps <id>`` shows
    why the step failed without a separate audit table.
    """

    def __init__(
        self,
        message: str,
        *,
        episode_id: int,
        sources_tried: list[str],
        wget_error: str = "",
        agent_message: str = "",
    ):
        self.episode_id = episode_id
        self.sources_tried = sources_tried
        self.wget_error = wget_error
        self.agent_message = agent_message
        super().__init__(
            message,
            {
                "episode_id": episode_id,
                "sources_tried": sources_tried,
                "wget_error": wget_error,
                "agent_message": agent_message,
            },
        )


def _wget(audio_url: str, dest_path: str) -> None:
    """Fetch *audio_url* into *dest_path* via wget. Raises on failure."""
    subprocess.run(
        ["wget", "-q", "-O", dest_path, audio_url],
        check=True,
        timeout=DOWNLOAD_TIMEOUT,
    )


def _save_audio(episode: Episode, src_path: str) -> int:
    """Attach the file at *src_path* to *episode* and extract duration."""
    filename = f"{episode.pk}.mp3"
    with open(src_path, "rb") as f:
        episode.audio_file.save(filename, File(f), save=False)

    audio = MP3(episode.audio_file.path)
    episode.duration = int(audio.info.length)
    return os.path.getsize(src_path)


def _show_name(episode: Episode) -> str:
    """Best-effort show name (no Show model — fall back to URL host)."""
    from urllib.parse import urlparse

    netloc = urlparse(episode.url).netloc
    return netloc or ""


def download_episode(episode_id: int) -> None:
    """Download the audio file for *episode_id*.

    Wraps the cascade in the legacy ``processing.start_step / complete_step
    / fail_step`` calls so the existing ``ProcessingRun`` / ``PipelineEvent``
    bookkeeping keeps working until the next commit drops it.
    """
    try:
        episode = Episode.objects.get(pk=episode_id)
    except Episode.DoesNotExist:
        logger.error("Episode %s does not exist", episode_id)
        return

    if episode.status != Episode.Status.DOWNLOADING:
        logger.warning(
            "Episode %s has status '%s', expected 'downloading'",
            episode_id,
            episode.status,
        )
        return

    start_step(episode, Episode.Status.DOWNLOADING)

    sources_tried: list[str] = []
    wget_error = ""
    tmp_path = ""

    try:
        # --- Tier 1: cheap path ---------------------------------------
        if episode.audio_url:
            sources_tried.append("wget")
            tmp = tempfile.NamedTemporaryFile(suffix=".mp3", delete=False)
            tmp_path = tmp.name
            tmp.close()
            try:
                _wget(episode.audio_url, tmp_path)
                size = _save_audio(episode, tmp_path)
                _complete(episode)
                logger.info(
                    "Downloaded episode %s via wget (%d bytes)", episode_id, size
                )
                return
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                wget_error = str(exc)
                logger.info(
                    "wget failed for episode %s (%s) — falling back to agent",
                    episode_id, exc,
                )
                _cleanup(tmp_path)
                tmp_path = ""

        # --- Tier 2: download agent -----------------------------------
        sources_tried.append("agent")
        from .agents.download import run_download_agent

        agent_result = run_download_agent(
            episode_id=episode_id,
            episode_url=episode.url,
            audio_url=episode.audio_url or "",
            title=episode.title or "",
            show_name=_show_name(episode),
            guid=episode.guid or "",
            language=episode.language or "",
        )

        if agent_result.success and agent_result.downloaded_file:
            tmp_path = agent_result.downloaded_file
            try:
                size = _save_audio(episode, tmp_path)
            finally:
                _cleanup(tmp_path)
                tmp_path = ""

            # Save the agent-discovered URL whenever it differs from the
            # currently-stored one — including overwriting a stale URL that
            # wget couldn't fetch. Without this, the next reprocess would
            # retry the bad URL and waste a wget hop before the agent runs.
            agent_audio_url_changed = bool(
                agent_result.audio_url
                and agent_result.audio_url != episode.audio_url
            )
            if agent_audio_url_changed:
                episode.audio_url = agent_result.audio_url

            _complete(episode, agent_audio_url=agent_audio_url_changed)
            logger.info(
                "Downloaded episode %s via agent (source=%s, %d bytes)",
                episode_id,
                agent_result.source or "agent",
                size,
            )
            return

        # --- Tier 3: failure ------------------------------------------
        message = agent_result.message or "Download agent could not recover audio"
        failure = DownloadFailed(
            message,
            episode_id=episode_id,
            sources_tried=sources_tried,
            wget_error=wget_error,
            agent_message=agent_result.message,
        )
        episode.error_message = str(failure)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.DOWNLOADING, str(failure), exc=failure)
        return

    except Exception as exc:
        logger.exception("Failed to download episode %s", episode_id)
        episode.error_message = str(exc)
        episode.status = Episode.Status.FAILED
        episode.save(update_fields=["status", "error_message", "updated_at"])
        fail_step(episode, Episode.Status.DOWNLOADING, str(exc), exc=exc)
        return
    finally:
        if tmp_path:
            _cleanup(tmp_path)


def _complete(episode: Episode, *, agent_audio_url: bool = False) -> None:
    """Common save+complete tail for both cheap path and agent path."""
    complete_step(episode, Episode.Status.DOWNLOADING)
    episode.status = Episode.Status.TRANSCRIBING
    fields = ["status", "audio_file", "duration", "updated_at"]
    if agent_audio_url:
        fields.append("audio_url")
    episode.save(update_fields=fields)


def _cleanup(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass
