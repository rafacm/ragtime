"""Search Wikidata for entity candidates from the command line."""

from django.core.management.base import BaseCommand

from episodes.models import EntityType
from episodes.wikidata import find_candidates, search_entities


class Command(BaseCommand):
    help = "Search Wikidata for entity candidates"

    def add_arguments(self, parser):
        parser.add_argument(
            "query",
            nargs="?",
            help="Entity name to search for",
        )
        parser.add_argument(
            "--type",
            dest="entity_type",
            help="Filter by entity type key (e.g. artist, album)",
        )

    def handle(self, *args, **options):
        query = options["query"]
        entity_type_key = options["entity_type"]

        if not query:
            self.stderr.write(self.style.ERROR("Please provide a search query."))
            return

        if entity_type_key:
            try:
                entity_type = EntityType.objects.get(key=entity_type_key)
            except EntityType.DoesNotExist:
                self.stderr.write(
                    self.style.ERROR(f"Unknown entity type: {entity_type_key}")
                )
                return

            if not entity_type.wikidata_id:
                self.stderr.write(
                    self.style.WARNING(
                        f"Entity type '{entity_type_key}' has no Wikidata class Q-ID"
                    )
                )
                return

            self.stdout.write(
                f"\nSearching Wikidata for '{query}' "
                f"(type: {entity_type.name}, class: {entity_type.wikidata_id})\n"
            )
            results = find_candidates(query, entity_type.wikidata_id)
        else:
            self.stdout.write(f"\nSearching Wikidata for '{query}'\n")
            results = search_entities(query)

        if not results:
            self.stdout.write(self.style.WARNING("No results found."))
            return

        self.stdout.write(f"\nFound {len(results)} result(s):\n")
        for result in results:
            qid = result["qid"]
            label = result["label"]
            description = result.get("description", "")
            if description:
                self.stdout.write(f"  {qid}: {label} — {description}")
            else:
                self.stdout.write(f"  {qid}: {label}")
        self.stdout.write("")
