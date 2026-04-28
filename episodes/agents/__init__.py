"""Pydantic AI agents used by the episodes pipeline.

- ``recovery``-prefixed modules: transitional recovery agent (Playwright-driven
  browser automation) that handles fetch-details and download failures.
  Slated for deletion once ``fetch_details`` and ``download`` step-agents
  absorb its capabilities.
"""

from .recovery import run_recovery_agent

__all__ = ["run_recovery_agent"]
