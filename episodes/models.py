from django.db import models
from django.utils import timezone


class Episode(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        SCRAPING = "scraping"
        NEEDS_REVIEW = "needs_review"
        DOWNLOADING = "downloading"
        TRANSCRIBING = "transcribing"
        SUMMARIZING = "summarizing"
        CHUNKING = "chunking"
        EXTRACTING = "extracting"
        RESOLVING = "resolving"
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
    duration = models.PositiveIntegerField(null=True, blank=True)

    # Stored cleaned HTML for debugging/re-processing
    scraped_html = models.TextField(blank=True, default="")

    # Transcription (populated by transcriber)
    transcript = models.TextField(blank=True, default="")
    transcript_json = models.JSONField(blank=True, null=True)

    # LLM-generated summary (populated by summarizer)
    summary_generated = models.TextField(blank=True, default="")

    # LLM-extracted entities (populated by extractor)
    entities_json = models.JSONField(blank=True, null=True)

    # Error message (populated on failure)
    error_message = models.TextField(blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title or self.url


class EntityType(models.Model):
    key = models.CharField(
        max_length=30,
        unique=True,
        help_text="Unique snake_case identifier, e.g. recording_session",
    )
    name = models.CharField(
        max_length=100,
        help_text="Human-readable label, e.g. Recording Session",
    )
    description = models.TextField(
        help_text="What this entity type represents, e.g. A specific date/time/place of a recording.",
    )
    examples = models.JSONField(
        default=list,
        help_text="Example entities of this type, e.g. The Blackhawk Sessions, 1959 Sessions",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Entity(models.Model):
    entity_type = models.ForeignKey(
        EntityType, on_delete=models.PROTECT, related_name="entities"
    )
    name = models.CharField(max_length=500)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entity_type", "name"],
                name="unique_entity_type_name",
            ),
        ]
        verbose_name_plural = "entities"

    def __str__(self):
        return f"{self.name} ({self.entity_type})"


class EntityMention(models.Model):
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="mentions"
    )
    episode = models.ForeignKey(
        Episode, on_delete=models.CASCADE, related_name="entity_mentions"
    )
    chunk = models.ForeignKey(
        "Chunk", on_delete=models.CASCADE, related_name="entity_mentions"
    )
    context = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["entity", "chunk"],
                name="unique_entity_chunk",
            ),
        ]

    def __str__(self):
        return f"{self.entity.name} in {self.episode}"


class Chunk(models.Model):
    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="chunks")
    index = models.PositiveIntegerField()
    text = models.TextField()
    start_time = models.FloatField()
    end_time = models.FloatField()
    segment_start = models.PositiveIntegerField()
    segment_end = models.PositiveIntegerField()
    entities_json = models.JSONField(blank=True, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["episode", "index"],
                name="unique_episode_chunk_index",
            ),
        ]
        ordering = ["index"]

    def __str__(self):
        return f"Chunk {self.index} of {self.episode}"


PIPELINE_STEPS = [
    Episode.Status.SCRAPING,
    Episode.Status.DOWNLOADING,
    Episode.Status.TRANSCRIBING,
    Episode.Status.SUMMARIZING,
    Episode.Status.CHUNKING,
    Episode.Status.EXTRACTING,
    Episode.Status.RESOLVING,
    Episode.Status.EMBEDDING,
]


class ProcessingRun(models.Model):
    class Status(models.TextChoices):
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"

    episode = models.ForeignKey(
        Episode, on_delete=models.CASCADE, related_name="processing_runs"
    )
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.RUNNING,
    )
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    resumed_from_step = models.CharField(max_length=20, blank=True, default="")

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return str(self.pk)


class ProcessingStep(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        RUNNING = "running"
        COMPLETED = "completed"
        FAILED = "failed"
        SKIPPED = "skipped"

    run = models.ForeignKey(
        ProcessingRun, on_delete=models.CASCADE, related_name="steps"
    )
    step_name = models.CharField(max_length=20)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True, default="")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "step_name"],
                name="unique_run_step_name",
            ),
        ]
        ordering = ["pk"]

    def __str__(self):
        return f"{self.step_name} ({self.status})"
