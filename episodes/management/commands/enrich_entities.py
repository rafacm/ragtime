"""Backfill Wikidata IDs for entities still in PENDING status.

Resolution always queues newly-created entities through
``episodes.enrichment.enqueue_entities``. This command exists for the case
where you want to retry pending entities that were missed (e.g. before the
enrichment worker was running, or after extending MAX_ATTEMPTS).
"""

from django.core.management.base import BaseCommand

from episodes.enrichment import MAX_ATTEMPTS, enqueue_entities
from episodes.models import Entity


class Command(BaseCommand):
    help = "Enqueue background Wikidata enrichment for entities in PENDING status."

    def add_arguments(self, parser):
        parser.add_argument(
            "--retry-failed",
            action="store_true",
            help="Also enqueue entities that exhausted retries (status=failed/not_found).",
        )
        parser.add_argument(
            "--limit",
            type=int,
            default=None,
            help="Cap how many entities are enqueued in this run.",
        )

    def handle(self, *args, **options):
        qs = Entity.objects.filter(wikidata_id="")
        if options["retry_failed"]:
            qs = qs.filter(
                wikidata_status__in=[
                    Entity.WikidataStatus.PENDING,
                    Entity.WikidataStatus.FAILED,
                    Entity.WikidataStatus.NOT_FOUND,
                ]
            )
        else:
            qs = qs.filter(
                wikidata_status=Entity.WikidataStatus.PENDING,
                wikidata_attempts__lt=MAX_ATTEMPTS,
            )

        if options["limit"]:
            qs = qs[: options["limit"]]

        ids = list(qs.values_list("pk", flat=True))
        enqueue_entities(ids)
        self.stdout.write(
            self.style.SUCCESS(
                f"Enqueued {len(ids)} entit{'y' if len(ids) == 1 else 'ies'} for Wikidata enrichment."
            )
        )
