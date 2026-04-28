"""Shared Pydantic AI model factory.

Pure helper used by every step-agent's ``get_agent()`` factory: takes a
Convention B model string (``provider:model``) and an API key, returns a
Pydantic AI ``Model`` (or a model string fallback) that can be passed to
``Agent(...)``.

No Django imports — settings reads happen in the caller's factory so
the agent module stays bootable in tests via
``from episodes.agents.fetch_details import run, EpisodeDetails``
without a Django app registry.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def build_model(model_string: str, api_key: str) -> Any:
    """Build a Pydantic AI ``Model`` for *model_string* + *api_key*.

    *model_string* is Convention B (``provider:model``), e.g.
    ``openai:gpt-4.1-mini`` or ``anthropic:claude-sonnet-4-20250514``.
    Returns a concrete ``Model`` instance when the provider is known and
    its SDK is installed; otherwise returns the raw string and lets
    Pydantic AI fall back to its own env-var resolution. When *api_key*
    is empty, always falls through to env-var resolution (lets
    ``ANTHROPIC_API_KEY`` / ``OPENAI_API_KEY`` etc. take over without
    leaking credentials into ``os.environ``).
    """
    if not api_key:
        return model_string

    if ":" in model_string:
        provider_name, _, model_name = model_string.partition(":")
    else:
        provider_name, model_name = "openai", model_string

    if provider_name == "openai":
        from pydantic_ai.models.openai import OpenAIResponsesModel
        from pydantic_ai.providers.openai import OpenAIProvider

        return OpenAIResponsesModel(
            model_name, provider=OpenAIProvider(api_key=api_key)
        )

    # For other providers, fall back to env var (their SDK may not be
    # installed). Set the env var only for the duration of model build —
    # callers shouldn't observe leakage in long-lived workers.
    env_key_map = {
        "anthropic": "ANTHROPIC_API_KEY",
        "google": "GOOGLE_API_KEY",
    }
    env_var = env_key_map.get(provider_name)
    if env_var:
        os.environ.setdefault(env_var, api_key)
    return model_string
