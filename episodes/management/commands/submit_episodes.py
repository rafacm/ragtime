"""Submit one or many podcast-episode URLs for ingestion.

Each URL is created as an ``Episode`` row with ``status=PENDING``; the
``post_save`` signal sets it to ``QUEUED`` and enqueues a ``process_episode``
workflow on the ``episode_pipeline`` DBOS queue. Episodes already submitted
(matched by the unique ``url`` field) are skipped — re-running this command
is idempotent.

Three input modes are supported, in order of precedence:

* ``URL [URL ...]`` positional arguments
* ``--file PATH`` — one URL per line, blank lines and ``#`` comments ignored
* ``-`` as the file path reads from stdin

Examples::

    uv run python manage.py submit_episodes https://example.com/ep/1 https://example.com/ep/2
    uv run python manage.py submit_episodes --file urls.txt
    cat urls.txt | uv run python manage.py submit_episodes --file -
    uv run python manage.py submit_episodes --file urls.txt --dry-run
"""

from __future__ import annotations

import sys
from urllib.parse import urlparse

from django.core.management.base import BaseCommand, CommandError

from episodes.models import Episode


class Command(BaseCommand):
    help = "Submit one or more podcast-episode URLs for ingestion."

    def add_arguments(self, parser):
        parser.add_argument(
            "urls",
            nargs="*",
            help="Podcast-episode URLs to submit (mutually exclusive with --file).",
        )
        parser.add_argument(
            "--file",
            "-f",
            dest="file",
            help=(
                "Read URLs from a file (one per line, blank lines and lines "
                "starting with '#' are ignored). Use '-' to read from stdin."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print what would happen without creating any Episode rows.",
        )

    def handle(self, *args, **options):
        urls = self._collect_urls(options)
        if not urls:
            raise CommandError(
                "No URLs supplied. Pass URLs as arguments or use --file PATH."
            )

        existing = set(
            Episode.objects.filter(url__in=urls).values_list("url", flat=True)
        )
        new_urls = [u for u in urls if u not in existing]

        if options["dry_run"]:
            self.stdout.write(self.style.WARNING("[dry-run] no Episode rows will be created."))
            for u in new_urls:
                self.stdout.write(f"  + {u}")
            for u in existing:
                self.stdout.write(self.style.NOTICE(f"  ~ {u}  (already submitted, skip)"))
            self.stdout.write(
                f"\nWould submit {len(new_urls)} new episode(s); skip {len(existing)} duplicate(s)."
            )
            return

        created = 0
        for url in new_urls:
            Episode.objects.create(url=url)
            created += 1
            self.stdout.write(f"  + {url}")
        for url in existing:
            self.stdout.write(self.style.NOTICE(f"  ~ {url}  (already submitted, skipped)"))

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSubmitted {created} new episode(s); skipped {len(existing)} duplicate(s)."
            )
        )

    def _collect_urls(self, options) -> list[str]:
        if options["urls"] and options["file"]:
            raise CommandError(
                "Pass URLs either as positional arguments or via --file, not both."
            )
        if options["urls"]:
            raw = options["urls"]
        elif options["file"]:
            raw = self._read_file(options["file"])
        else:
            return []

        urls: list[str] = []
        seen: set[str] = set()
        for entry in raw:
            url = entry.strip()
            if not url or url.startswith("#"):
                continue
            self._validate_url(url)
            if url in seen:
                continue
            seen.add(url)
            urls.append(url)
        return urls

    def _read_file(self, path: str) -> list[str]:
        if path == "-":
            return sys.stdin.read().splitlines()
        try:
            with open(path) as f:
                return f.read().splitlines()
        except OSError as exc:
            raise CommandError(f"Could not read {path}: {exc}") from exc

    def _validate_url(self, url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise CommandError(f"Invalid URL: {url!r} (must be http:// or https://)")
