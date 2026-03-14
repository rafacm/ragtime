from pathlib import Path

import yaml
from django.core.management.base import BaseCommand

from episodes.models import EntityType

YAML_PATH = Path(__file__).resolve().parent.parent.parent / "initial_entity_types.yaml"


class Command(BaseCommand):
    help = "Load entity types from initial_entity_types.yaml into the database."

    def handle(self, *args, **options):
        with open(YAML_PATH) as f:
            entity_types = yaml.safe_load(f)

        created = 0
        updated = 0
        for et in entity_types:
            _, was_created = EntityType.objects.update_or_create(
                key=et["key"],
                defaults={
                    "name": et["name"],
                    "description": et.get("description", ""),
                    "examples": et.get("examples", []),
                },
            )
            if was_created:
                created += 1
            else:
                updated += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Done: {created} created, {updated} updated "
                f"({len(entity_types)} total)."
            )
        )
