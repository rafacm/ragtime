"""Dependencies and result model for the recovery agent."""

import dataclasses

from playwright.async_api import Page
from pydantic import BaseModel


@dataclasses.dataclass
class RecoveryDeps:
    """Runtime dependencies injected into every tool call."""

    episode_id: int
    episode_url: str
    audio_url: str
    step_name: str
    error_message: str
    http_status: int | None
    download_dir: str
    page: Page
    screenshots: list[bytes]


class RecoveryAgentResult(BaseModel):
    """Structured result returned by the recovery agent."""

    success: bool
    audio_url: str = ""
    downloaded_file: str = ""
    message: str = ""
