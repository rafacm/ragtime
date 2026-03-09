from django.db import models


class Episode(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        SCRAPING = "scraping"
        NEEDS_REVIEW = "needs_review"
        DOWNLOADING = "downloading"
        RESIZING = "resizing"
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

    # Metadata fields (populated by scraper)
    title = models.CharField(max_length=500, blank=True, default="")
    description = models.TextField(blank=True, default="")
    published_at = models.DateField(null=True, blank=True)
    image_url = models.URLField(max_length=2000, blank=True, default="")
    language = models.CharField(max_length=10, blank=True, default="")
    audio_url = models.URLField(max_length=2000, blank=True, default="")

    # Audio file (populated by downloader)
    audio_file = models.FileField(upload_to="episodes/", blank=True)

    # Stored cleaned HTML for debugging/re-processing
    scraped_html = models.TextField(blank=True, default="")

    # Error message (populated on failure)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title or self.url
