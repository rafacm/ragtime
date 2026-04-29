import logging

from dbos import DBOS  # noqa: F401  -- legacy patch target for tests
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .models import Episode

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Episode)
def queue_next_step(sender, instance, created, **kwargs):
    if created and instance.status == Episode.Status.PENDING:
        from .workflows import enqueue_episode

        # Move to QUEUED so the row visibly reflects "waiting for a worker
        # slot" before DBOS picks it up. queryset .update() bypasses the
        # post_save signal — no recursion.
        Episode.objects.filter(pk=instance.pk).update(status=Episode.Status.QUEUED)
        # ``enqueue_episode`` assigns a deterministic ``episode-<id>-run-<n>``
        # ID, so concurrent enqueues for the same episode are deduplicated
        # by DBOS rather than racing into two parallel workflows. Returns
        # None when DBOS isn't initialized (test env, management commands).
        enqueue_episode(instance.pk)
        return


@receiver(post_delete, sender=Episode)
def cleanup_qdrant_on_episode_delete(sender, instance, **kwargs):
    """Remove the episode's chunks from Qdrant when the Episode row is deleted.

    Postgres cascades on delete, but Qdrant is external. A stale Qdrant
    point is much better than a failing admin delete, so any error is
    logged and swallowed.
    """
    try:
        from .vector_store import get_vector_store

        get_vector_store().delete_by_episode(instance.pk)
    except Exception:
        logger.exception(
            "Failed to delete Qdrant points for episode %s", instance.pk
        )
