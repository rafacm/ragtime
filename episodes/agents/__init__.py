"""Agent recovery for pipeline failures.

Uses Pydantic AI + Playwright to recover from scraping and downloading
failures by browsing podcast pages to find audio URLs and download files.

Requires the ``recovery`` optional dependency group::

    uv sync --extra recovery
"""

try:
    from .agent import run_recovery_agent
except ImportError:
    def run_recovery_agent(event):
        raise RuntimeError(
            "Recovery agent requires pydantic-ai and playwright. "
            "Install with: uv sync --extra recovery"
        )

__all__ = ["run_recovery_agent"]
