from django.db import models
from django.utils import timezone


class Episode(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending"
        QUEUED = "queued"
        FETCHING_DETAILS = "fetching_details"
        DOWNLOADING = "downloading"
        TRANSCRIBING = "transcribing"
        SUMMARIZING = "summarizing"
        CHUNKING = "chunking"
        EXTRACTING = "extracting"
        RESOLVING = "resolving"
        EMBEDDING = "embedding"
        VERIFYING = "verifying"
        READY = "ready"
        FAILED = "failed"

    class SourceKind(models.TextChoices):
        CANONICAL = "canonical"
        AGGREGATOR = "aggregator"
        UNKNOWN = "unknown"

    url = models.URLField(unique=True)
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    # Metadata fields (populated by fetch_details step)
    title = models.CharField(max_length=500, blank=True, default="")
    description = models.TextField(blank=True, default="")
    published_at = models.DateField(null=True, blank=True)
    image_url = models.URLField(max_length=2000, blank=True, default="")
    language = models.CharField(max_length=10, blank=True, default="")
    audio_url = models.URLField(max_length=2000, blank=True, default="")
    audio_format = models.CharField(max_length=10, blank=True, default="")
    guid = models.CharField(max_length=500, blank=True, default="")
    country = models.CharField(max_length=2, blank=True, default="")

    # Source classification (populated by fetch_details agent)
    canonical_url = models.URLField(max_length=2000, blank=True, default="")
    source_kind = models.CharField(
        max_length=20,
        choices=SourceKind.choices,
        default=SourceKind.UNKNOWN,
        blank=True,
    )
    aggregator_provider = models.CharField(max_length=50, blank=True, default="")

    # Audio file (populated by downloader)
    audio_file = models.FileField(upload_to="episodes/", blank=True)
    duration = models.PositiveIntegerField(null=True, blank=True)

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
    wikidata_id = models.CharField(
        max_length=20,
        blank=True,
        default="",
        help_text="Wikidata class Q-ID, e.g. Q639669 for 'musician'",
    )
    description = models.TextField(
        help_text="What this entity type represents, e.g. A specific date/time/place of a recording.",
    )
    examples = models.JSONField(
        default=list,
        help_text="Example entities of this type, e.g. The Blackhawk Sessions, 1959 Sessions",
    )
    is_active = models.BooleanField(default=True)
    musicbrainz_table = models.CharField(
        max_length=64,
        blank=True,
        default="",
        help_text="MusicBrainz table to query for candidates (artist, release_group, label, place, work, area). Empty = no MB lookup.",
    )
    musicbrainz_filter = models.JSONField(
        default=dict,
        blank=True,
        help_text="Extra filter applied to MB candidates, e.g. {\"artist_type\": \"Person\"} or {\"area_type\": \"City\"}.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Entity(models.Model):
    class WikidataStatus(models.TextChoices):
        PENDING = "pending"
        RESOLVED = "resolved"
        NOT_FOUND = "not_found"
        FAILED = "failed"

    entity_type = models.ForeignKey(
        EntityType, on_delete=models.PROTECT, related_name="entities"
    )
    name = models.CharField(max_length=500)
    wikidata_id = models.CharField(
        max_length=20,
        blank=True,
        default="",
        db_index=True,
        help_text="Wikidata entity Q-ID, e.g. Q93341 for 'Miles Davis'",
    )
    musicbrainz_id = models.CharField(
        max_length=36,
        blank=True,
        default="",
        db_index=True,
        help_text="MusicBrainz entity gid (UUID).",
    )
    wikidata_status = models.CharField(
        max_length=20,
        choices=WikidataStatus.choices,
        default=WikidataStatus.PENDING,
        db_index=True,
    )
    wikidata_attempts = models.PositiveSmallIntegerField(default=0)
    wikidata_last_attempted_at = models.DateTimeField(null=True, blank=True)
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
    start_time = models.FloatField(null=True, blank=True)
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


class FetchDetailsRun(models.Model):
    """One execution of the Fetch Details agent for an episode.

    Persists the full agent trace so admins (and a future Scott UI) can
    see every cross-link, tool call, and structured output the agent
    produced. ``run_index`` increments per episode — successive
    re-runs land as new rows. The ``Episode`` row carries only the
    user-facing summary; everything richer lives here.
    """

    class Outcome(models.TextChoices):
        OK = "ok"
        PARTIAL = "partial"
        NOT_A_PODCAST_EPISODE = "not_a_podcast_episode"
        UNREACHABLE = "unreachable"
        EXTRACTION_FAILED = "extraction_failed"

    episode = models.ForeignKey(
        Episode, on_delete=models.CASCADE, related_name="fetch_details_runs"
    )
    run_index = models.PositiveIntegerField(
        help_text="1, 2, 3… per episode — increments on re-run.",
    )

    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    model = models.CharField(
        max_length=100,
        default="",
        help_text="Pydantic AI model string at run time (e.g. openai:gpt-4.1-mini).",
    )

    outcome = models.CharField(
        max_length=30,
        choices=Outcome.choices,
        blank=True,
        default="",
    )

    # Full structured agent output: { details, report, concise }.
    output_json = models.JSONField(null=True, blank=True)
    # Auto-captured tool calls from Pydantic AI run messages — separate
    # from the agent's self-narrated ``attempted_sources``.
    tool_calls_json = models.JSONField(default=list, blank=True)
    # Raw Pydantic AI usage dict; no extracted token columns this PR.
    usage_json = models.JSONField(null=True, blank=True)

    # Set only when the agent crashed before producing structured output.
    error_message = models.TextField(blank=True, default="")

    dbos_workflow_id = models.CharField(
        max_length=200,
        blank=True,
        default="",
        db_index=True,
        help_text="DBOS.workflow_id at orchestrator entry — cross-reference for forensics.",
    )

    class Meta:
        unique_together = [("episode", "run_index")]
        indexes = [
            models.Index(fields=["episode", "-run_index"]),
            models.Index(fields=["outcome"]),
            models.Index(fields=["-started_at"]),
        ]
        ordering = ["-started_at"]

    def __str__(self):
        outcome = self.outcome or "in_progress"
        return f"FetchDetailsRun #{self.run_index} of {self.episode_id} ({outcome})"


PIPELINE_STEPS = [
    Episode.Status.FETCHING_DETAILS,
    Episode.Status.DOWNLOADING,
    Episode.Status.TRANSCRIBING,
    Episode.Status.SUMMARIZING,
    Episode.Status.CHUNKING,
    Episode.Status.EXTRACTING,
    Episode.Status.RESOLVING,
    Episode.Status.EMBEDDING,
    Episode.Status.VERIFYING,
]


