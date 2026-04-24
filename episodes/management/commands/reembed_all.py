"""Re-embed all READY episodes so Qdrant payloads pick up schema changes.

Useful after extending ``episodes.embedder._build_payloads`` — for example
when a new payload field is added and the existing corpus needs to be
updated without re-running the full pipeline.
"""

from django.core.management.base import BaseCommand, CommandError

from episodes.embedder import embed_episode
from episodes.models import Episode


class Command(BaseCommand):
    help = "Re-embed all READY episodes by re-upserting their Qdrant points."

    def handle(self, *args, **options):
        episode_ids = list(
            Episode.objects.filter(status=Episode.Status.READY)
            .order_by("id")
            .values_list("id", flat=True)
        )
        total = len(episode_ids)
        if total == 0:
            self.stdout.write("No READY episodes to re-embed.")
            return

        self.stdout.write(f"Re-embedding {total} episode(s)...")
        for idx, episode_id in enumerate(episode_ids, start=1):
            episode = Episode.objects.get(pk=episode_id)
            # Only touch episodes still READY at execution time — avoids
            # racing against an in-flight embed from another process.
            if episode.status != Episode.Status.READY:
                self.stdout.write(
                    f"[{idx}/{total}] skip {episode_id}: status={episode.status}"
                )
                continue

            # embed_episode() guards on status == EMBEDDING. Flip, run,
            # let the step set it back to READY on success.
            episode.status = Episode.Status.EMBEDDING
            episode.save(update_fields=["status", "updated_at"])
            self.stdout.write(f"[{idx}/{total}] re-embedding episode {episode_id}...")
            embed_episode(episode_id)
            episode.refresh_from_db()
            if episode.status == Episode.Status.FAILED:
                raise CommandError(
                    f"Episode {episode_id} failed to re-embed: {episode.error_message}"
                )

        self.stdout.write(self.style.SUCCESS(f"Re-embedded {total} episode(s)."))
