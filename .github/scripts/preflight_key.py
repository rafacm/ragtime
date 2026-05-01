#!/usr/bin/env python3
"""Verify the API key required by `AI_CHECK_MODEL` is set in the workflow env.

Runs once in the matrix-listing job so a single, actionable error is shown
rather than one Python traceback per matrix shard. Writes a Markdown
explanation to `$GITHUB_STEP_SUMMARY` and emits a `::error::` annotation, then
exits 1 if the required secret is missing. Exits 0 (with `::warning::`) when
the model uses a provider prefix this script doesn't know — LiteLLM will
validate at call time in that case.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROVIDER_TO_ENV_VAR: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "google": "GEMINI_API_KEY",
}


def main() -> int:
    model = os.environ.get("AI_CHECK_MODEL", "openai/gpt-4o-mini")
    if "/" not in model:
        print(
            f"::warning title=Cannot preflight AI_CHECK_MODEL::"
            f"AI_CHECK_MODEL='{model}' has no provider prefix; skipping preflight. "
            f"LiteLLM will validate at call time."
        )
        return 0

    provider = model.split("/", 1)[0].lower()
    key_name = PROVIDER_TO_ENV_VAR.get(provider)
    if not key_name:
        print(
            f"::warning title=Unknown provider in AI_CHECK_MODEL::"
            f"Provider prefix '{provider}' is not in the preflight table; skipping. "
            f"LiteLLM will validate at call time."
        )
        return 0

    if os.environ.get(key_name):
        print(f"{key_name} is set; provider preflight passed.")
        return 0

    summary = f"""# AI Checks: missing `{key_name}` repository secret

`AI_CHECK_MODEL` is set to `{model}`, which routes to the **{provider}** provider via LiteLLM. The required repository secret `{key_name}` is not set, so none of the per-rule AI checks can run.

## To fix

Add `{key_name}` as a **repository** secret (not an environment secret) under **Settings → Secrets and variables → Actions → New repository secret**, then re-run this workflow. See `doc/features/2026-05-01-ai-checks-action.md` for the full setup checklist (dedicated OpenAI Project, budget cap, key permissions).

## To switch providers

Change the repo variable `AI_CHECK_MODEL` (currently `{model}`) and add the matching repository secret. Supported prefixes: `openai/...`, `anthropic/...`, `gemini/...`.
"""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        Path(summary_path).write_text(summary)

    print(
        f"::error title=Missing {key_name} repository secret::"
        f"AI checks need the '{key_name}' repository secret because AI_CHECK_MODEL={model}. "
        f"Add it under Settings -> Secrets and variables -> Actions -> New repository secret "
        f"(not an environment secret), or change the AI_CHECK_MODEL repo variable "
        f"to a different provider."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
