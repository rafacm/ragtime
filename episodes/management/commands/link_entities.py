"""Link pending entities to Wikidata Q-IDs via the linking agent."""

from django.core.management.base import BaseCommand

from episodes.models import Entity


class Command(BaseCommand):
    help = "Link pending entities to Wikidata Q-IDs using the linking agent"

    def add_arguments(self, parser):
        parser.add_argument(
            "--type",
            dest="entity_type",
            help="Only link entities of this type key (e.g. musician, album)",
        )
        parser.add_argument(
            "--retry",
            action="store_true",
            help="Reset failed entities to pending before linking",
        )

    def handle(self, *args, **options):
        entity_type_key = options["entity_type"]

        if options["retry"]:
            qs = Entity.objects.filter(linking_status=Entity.LinkingStatus.FAILED)
            if entity_type_key:
                qs = qs.filter(entity_type__key=entity_type_key)
            count = qs.update(linking_status=Entity.LinkingStatus.PENDING)
            self.stdout.write(f"Reset {count} failed entities to pending.")

        pending = Entity.objects.filter(linking_status=Entity.LinkingStatus.PENDING)
        if entity_type_key:
            pending = pending.filter(entity_type__key=entity_type_key)

        count = pending.count()
        if count == 0:
            self.stdout.write(self.style.SUCCESS("No pending entities to link."))
            return

        self.stdout.write(f"Linking {count} pending entities...")

        from episodes.agents.linker import run_linking_agent

        run_linking_agent()

        self.stdout.write(self.style.SUCCESS("Linking complete."))
