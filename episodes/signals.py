from django.db.models.signals import post_save
from django.dispatch import receiver
from django_q.tasks import async_task

from .models import Episode


@receiver(post_save, sender=Episode)
def queue_scrape_on_create(sender, instance, created, **kwargs):
    if created and instance.status == Episode.Status.PENDING:
        async_task("episodes.scraper.scrape_episode", instance.pk)
