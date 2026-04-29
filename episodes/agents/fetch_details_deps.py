"""Dependencies + tool-call recorder for the fetch_details agent.

The agent module itself is purely Pydantic AI / Pydantic / stdlib —
no Django or DBOS imports. This deps object is the only thing the
orchestrator hands in: per-call URL hints + a shared list the tools
append to so the orchestrator can persist the trace afterward.
"""

from __future__ import annotations

import dataclasses
from typing import Any


@dataclasses.dataclass
class FetchDetailsDeps:
    """Runtime context injected into every tool call."""

    submitted_url: str
    # Tools append a ``{"tool": ..., "input": ..., "output_excerpt": ...,
    # "ok": bool}`` dict on every call. The orchestrator persists the
    # final list to ``FetchDetailsRun.tool_calls_json``.
    tool_calls: list[dict[str, Any]] = dataclasses.field(default_factory=list)
