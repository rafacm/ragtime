"""Dependencies and result model for the download agent."""

import dataclasses
from datetime import date

from playwright.async_api import Page
from pydantic import BaseModel


@dataclasses.dataclass
class DownloadDeps:
    """Runtime dependencies injected into every tool call."""

    episode_id: int
    episode_url: str
    audio_url: str
    title: str
    show_name: str
    guid: str
    language: str
    download_dir: str
    page: Page
    screenshots: list[bytes]
    # Episode publication date (when fetch_details extracted one). Used
    # by the agent as a tiebreaker against ``IndexCandidate.published_at``
    # when ``show_name`` is degraded (e.g. fell back to URL host).
    published_at: date | None = None


class DownloadAgentResult(BaseModel):
    """Structured result returned by the download agent."""

    success: bool
    audio_url: str = ""
    downloaded_file: str = ""
    source: str = ""  # "agent" | "fyyd" | "podcastindex"
    message: str = ""
