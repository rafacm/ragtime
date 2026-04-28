"""Pydantic AI agents used by the episodes pipeline.

- ``recovery``-prefixed modules: transitional recovery agent (Playwright-driven
  browser automation) that handles fetch-details and download failures.
  Slated for deletion once ``fetch_details`` and ``download`` step-agents
  absorb its capabilities.

This package intentionally re-exports nothing. Importing
``episodes.agents.fetch_details`` must not pull in the recovery agent
(which depends on Django + Playwright) — that would break the agent's
"bootable in a bare interpreter for unit/eval tests" contract. Callers
import the agent they need by full path:

    from episodes.agents.fetch_details import run, EpisodeDetails
    from episodes.agents.recovery import run_recovery_agent
"""
