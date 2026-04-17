"""Agent recovery for pipeline failures.

Uses Pydantic AI + Playwright to recover from scraping and downloading
failures by browsing podcast pages to find audio URLs and download files.
"""

from .agent import run_recovery_agent

__all__ = ["run_recovery_agent"]
