"""Submit a single podcast-episode URL for ingestion.

Creates an ``Episode`` row with ``status=PENDING``; the ``post_save`` signal
moves it to ``QUEUED`` and enqueues a ``process_episode`` workflow on the
``episode_pipeline`` DBOS queue.

Usage::

    uv run python manage.py submit_episode https://example.com/ep/1
"""

from __future__ import annotations

from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError

from episodes.models import Episode


class Command(BaseCommand):
    help = "Submit a single podcast-episode URL for ingestion."

    def add_arguments(self, parser):
        parser.add_argument("url", help="Podcast-episode URL to submit.")

    def handle(self, *args, **options):
        url = options["url"].strip()
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise CommandError(f"Invalid URL: {url!r} (must be http:// or https://)")

        episode, created = Episode.objects.get_or_create(url=url)
        if not created:
            self.stdout.write(
                self.style.NOTICE(
                    f"Episode {episode.pk} already exists for {url} "
                    f"(status={episode.status}); not re-enqueued."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"Submitted episode {episode.pk}: {url}")
        )
