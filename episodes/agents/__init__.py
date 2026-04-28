"""Pydantic AI agents used by the episodes pipeline.

Two agents share this package:

* ``fetch_details`` — single structured-output LLM call that turns a
  cleaned episode HTML page into ``EpisodeDetails``.
* ``download`` — Playwright-driven browser agent with podcast-index
  lookup tooling, used as the fallback when the cheap ``wget`` path
  on a known ``audio_url`` fails.

This package intentionally re-exports nothing. Importing
``episodes.agents.fetch_details`` must not pull in the download agent
(which depends on Django + Playwright) — that would break the agent's
"bootable in a bare interpreter for unit/eval tests" contract. Callers
import the agent they need by full path:

    from episodes.agents.fetch_details import run, EpisodeDetails
    from episodes.agents.download import run_download_agent
"""
