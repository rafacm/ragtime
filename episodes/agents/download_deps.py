"""Dependencies and result model for the download agent."""

import dataclasses

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


class DownloadAgentResult(BaseModel):
    """Structured result returned by the download agent."""

    success: bool
    audio_url: str = ""
    downloaded_file: str = ""
    source: str = ""  # "agent" | "fyyd" | "podcastindex"
    message: str = ""
