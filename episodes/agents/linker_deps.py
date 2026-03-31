"""Dependencies and result model for the linking agent."""

import dataclasses

from pydantic import BaseModel


@dataclasses.dataclass
class LinkingDeps:
    """Runtime dependencies injected into every tool call."""

    linked_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0


class LinkingAgentResult(BaseModel):
    """Structured result returned by the linking agent."""

    linked: int = 0
    failed: int = 0
    skipped: int = 0
    message: str = ""
