from django.db import models


class Episode(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        DOWNLOADING = "downloading"
        TRANSCRIBING = "transcribing"
        SUMMARIZING = "summarizing"
        EXTRACTING = "extracting"
        DEDUPLICATING = "deduplicating"
        EMBEDDING = "embedding"
        READY = "ready"
        FAILED = "failed"

    url = models.URLField(unique=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.url
