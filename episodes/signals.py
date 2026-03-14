from django.db.models.signals import post_save
from django.dispatch import receiver
from django_q.tasks import async_task

from .models import Episode
from .processing import create_run


@receiver(post_save, sender=Episode)
def queue_next_step(sender, instance, created, **kwargs):
    if created and instance.status == Episode.Status.PENDING:
        create_run(instance)
        async_task("episodes.scraper.scrape_episode", instance.pk)
        return

    if created:
        return

    update_fields = kwargs.get("update_fields")
    if not update_fields or "status" not in update_fields:
        return

    if instance.status == Episode.Status.SCRAPING:
        async_task("episodes.scraper.scrape_episode", instance.pk)
    elif instance.status == Episode.Status.DOWNLOADING:
        async_task("episodes.downloader.download_episode", instance.pk)
    elif instance.status == Episode.Status.RESIZING:
        async_task("episodes.resizer.resize_episode", instance.pk)
    elif instance.status == Episode.Status.TRANSCRIBING:
        async_task("episodes.transcriber.transcribe_episode", instance.pk)
    elif instance.status == Episode.Status.SUMMARIZING:
        async_task("episodes.summarizer.summarize_episode", instance.pk)
    elif instance.status == Episode.Status.EXTRACTING:
        async_task("episodes.extractor.extract_entities", instance.pk)
    elif instance.status == Episode.Status.RESOLVING:
        async_task("episodes.resolver.resolve_entities", instance.pk)
