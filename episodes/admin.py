from django import forms
from django.contrib import admin
from django.db.models import Count
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils.html import format_html
from django_q.tasks import async_task

from .models import (
    PIPELINE_STEPS,
    Chunk,
    Entity,
    EntityMention,
    EntityType,
    Episode,
    ProcessingRun,
    ProcessingStep,
)
from .processing import create_run


class ChunkInlineForEpisode(admin.TabularInline):
    model = Chunk
    extra = 0
    classes = ("collapse",)
    verbose_name_plural = "Chunks"
    readonly_fields = ("index", "text", "start_time", "end_time", "segment_start", "segment_end")
    fields = ("index", "start_time", "end_time", "text")
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntityMentionInlineForChunk(admin.TabularInline):
    model = EntityMention
    extra = 0
    fields = ("entity", "context", "created_at")
    readonly_fields = ("entity", "context", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntityMentionInlineForEpisode(admin.TabularInline):
    model = EntityMention
    extra = 0
    readonly_fields = ("entity", "chunk", "context", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntityMentionInlineForEntity(admin.TabularInline):
    model = EntityMention
    extra = 0
    readonly_fields = ("episode", "chunk", "context", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ProcessingRunInlineForEpisode(admin.TabularInline):
    model = ProcessingRun
    extra = 0
    readonly_fields = ("status", "started_at", "finished_at", "resumed_from_step")
    fields = ("status", "started_at", "finished_at", "resumed_from_step")
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("title", "url", "language", "formatted_duration", "status", "created_at", "updated_at")
    list_filter = ("status", "language")
    readonly_fields = (
        "created_at",
        "updated_at",
        "audio_file",
        "duration",
        "error_message",
        "transcript",
        "transcript_json",
        "summary_generated",
        "entities_json",
    )
    actions = ["reprocess"]

    METADATA_FIELDS = (
        "title",
        "description",
        "published_at",
        "image_url",
        "language",
        "audio_url",
    )

    def get_inlines(self, request, obj=None):
        if obj is None:
            return []
        inlines = [ProcessingRunInlineForEpisode]
        if obj.chunks.exists():
            inlines.insert(0, ChunkInlineForEpisode)
        if obj.entity_mentions.exists():
            inlines.append(EntityMentionInlineForEpisode)
        return inlines

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None:
            # Creating a new episode — only url is editable
            readonly += list(self.METADATA_FIELDS) + ["status", "scraped_html"]
        elif obj.status == Episode.Status.NEEDS_REVIEW:
            # Needs review — metadata editable, status read-only
            readonly += ["status", "scraped_html"]
        else:
            # All other statuses — everything read-only except url
            readonly += list(self.METADATA_FIELDS) + ["status", "scraped_html"]
        return readonly

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return [(None, {"fields": ("url",)})]
        main_fields = ["url", "status"]
        if obj.status == Episode.Status.FAILED and obj.error_message:
            main_fields.append("error_message")
        fieldsets = [
            (None, {"fields": main_fields}),
            (
                "Metadata",
                {"fields": self.METADATA_FIELDS},
            ),
        ]
        if obj.audio_file:
            fieldsets.append(("Files", {"fields": ("audio_file", "duration")}))
        if obj.transcript:
            fieldsets.append(("Transcript", {"fields": ("transcript",)}))
        if obj.summary_generated:
            fieldsets.append(("Summary", {"fields": ("summary_generated",)}))
        if obj.entities_json:
            fieldsets.append((
                "Entities",
                {
                    "classes": ("collapse",),
                    "fields": ("entities_json",),
                },
            ))
        if obj.transcript_json:
            fieldsets.append((
                "Transcript JSON",
                {
                    "classes": ("collapse",),
                    "fields": ("transcript_json",),
                },
            ))
        fieldsets += [
            (
                "Debug",
                {
                    "classes": ("collapse",),
                    "fields": ("scraped_html",),
                },
            ),
            (
                "Timestamps",
                {
                    "classes": ("collapse",),
                    "fields": ("created_at", "updated_at"),
                },
            ),
        ]
        return fieldsets

    @admin.display(description="Duration", ordering="duration")
    def formatted_duration(self, obj):
        if obj.duration is None:
            return "\u2014"
        hours, remainder = divmod(obj.duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    @admin.action(description="Reprocess selected episodes\u2026")
    def reprocess(self, request, queryset):
        if "from_step" in request.POST:
            return self._execute_reprocess(request, queryset)
        return self._show_reprocess_page(request, queryset)

    def _get_last_failed_step(self, episode):
        last_run = episode.processing_runs.filter(
            status=ProcessingRun.Status.FAILED
        ).first()
        if not last_run:
            return None
        failed_step = last_run.steps.filter(
            status=ProcessingStep.Status.FAILED
        ).first()
        return failed_step.step_name if failed_step else None

    def _show_reprocess_page(self, request, queryset):
        episodes = list(queryset)
        # Annotate each episode with its last failed step for display
        default_step = Episode.Status.SCRAPING
        for ep in episodes:
            ep.last_failed_step = self._get_last_failed_step(ep)

        # If all selected episodes share the same failed step, default to it
        failed_steps = [ep.last_failed_step for ep in episodes if ep.last_failed_step]
        if failed_steps and len(set(failed_steps)) == 1:
            default_step = failed_steps[0]

        step_choices = [(s.value, s.label) for s in PIPELINE_STEPS]

        context = {
            **self.admin_site.each_context(request),
            "title": "Reprocess episodes",
            "episodes": episodes,
            "step_choices": step_choices,
            "default_step": default_step,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request,
            "admin/episodes/episode/reprocess.html",
            context,
        )

    def _execute_reprocess(self, request, queryset):
        from_step = request.POST["from_step"]
        episode_ids = request.POST.getlist("episode_ids")
        episodes = Episode.objects.filter(pk__in=episode_ids)

        count = 0
        for episode in episodes:
            resume_from = "" if from_step == Episode.Status.SCRAPING else from_step
            create_run(episode, resume_from=resume_from)
            episode.status = from_step
            episode.error_message = ""
            episode.save(update_fields=["status", "error_message", "updated_at"])
            # Scraping is the pipeline entry point — the scraper sets its own
            # status internally, so it can't be dispatched via the signal
            # (that would loop). All other steps are dispatched by the signal.
            if from_step == Episode.Status.SCRAPING:
                async_task("episodes.scraper.scrape_episode", episode.pk)
            count += 1

        self.message_user(
            request,
            f"Queued {count} episode(s) for reprocessing from '{from_step}'.",
        )


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("episode_link", "index", "formatted_time_range", "short_text", "has_entities")
    list_filter = ("episode__title",)
    search_fields = ("text", "episode__title")
    readonly_fields = (
        "episode", "index", "text", "start_time", "end_time",
        "segment_start", "segment_end", "entities_json",
    )

    def get_inlines(self, request, obj=None):
        if obj is not None and obj.entity_mentions.exists():
            return [EntityMentionInlineForChunk]
        return []

    def get_fieldsets(self, request, obj=None):
        fieldsets = [
            (None, {"fields": ("episode", "index", "start_time", "end_time")}),
            ("Content", {"fields": ("text",)}),
            ("Segments", {"classes": ("collapse",), "fields": ("segment_start", "segment_end")}),
        ]
        if obj and obj.entities_json:
            fieldsets.append((
                "Extracted Entities",
                {"classes": ("collapse",), "fields": ("entities_json",)},
            ))
        return fieldsets

    @admin.display(description="Episode", ordering="episode__title")
    def episode_link(self, obj):
        url = reverse("admin:episodes_episode_change", args=[obj.episode_id])
        return format_html('<a href="{}">{}</a>', url, obj.episode)

    @admin.display(description="Time range", ordering="start_time")
    def formatted_time_range(self, obj):
        def fmt(seconds):
            m, s = divmod(int(seconds), 60)
            return f"{m}:{s:02d}"
        return f"{fmt(obj.start_time)} – {fmt(obj.end_time)}"

    @admin.display(description="Text")
    def short_text(self, obj):
        if len(obj.text) > 100:
            return format_html("{}&hellip;", obj.text[:100])
        return obj.text

    @admin.display(description="Entities", boolean=True)
    def has_entities(self, obj):
        return bool(obj.entities_json)

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntityInlineForEntityType(admin.TabularInline):
    model = Entity
    extra = 0
    fields = ("name", "created_at")
    readonly_fields = ("name", "created_at")
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class CommaSeparatedListField(forms.CharField):
    widget = forms.TextInput(attrs={"class": "vLargeTextField"})

    def prepare_value(self, value):
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        return value or ""

    def clean(self, value):
        value = super().clean(value)
        if not value:
            return []
        return [item.strip() for item in value.split(",") if item.strip()]


class EntityTypeForm(forms.ModelForm):
    examples = CommaSeparatedListField(
        help_text="Comma-separated list of examples, e.g. Miles Davis, Alice Coltrane",
    )

    class Meta:
        model = EntityType
        fields = "__all__"


@admin.register(EntityType)
class EntityTypeAdmin(admin.ModelAdmin):
    form = EntityTypeForm
    list_display = ("name", "key", "is_active", "entity_count")
    list_filter = ("is_active",)
    search_fields = ("name", "key")
    fields = ("key", "name", "description", "examples", "is_active", "created_at", "updated_at")
    inlines = [EntityInlineForEntityType]

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return ("key", "created_at", "updated_at")
        return ("created_at", "updated_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_entity_count=Count("entities"))

    @admin.display(description="Entities", ordering="_entity_count")
    def entity_count(self, obj):
        return obj._entity_count


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("name", "entity_type", "mention_count", "created_at")
    list_filter = ("entity_type__name",)
    search_fields = ("name",)
    readonly_fields = ("entity_type", "name", "created_at", "updated_at")
    inlines = [EntityMentionInlineForEntity]

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_mention_count=Count("mentions"))

    @admin.display(description="Mentions", ordering="_mention_count")
    def mention_count(self, obj):
        return obj._mention_count

    def has_add_permission(self, request):
        return False


@admin.register(EntityMention)
class EntityMentionAdmin(admin.ModelAdmin):
    list_display = ("entity", "episode_link", "chunk_link", "short_context", "created_at")
    list_filter = ("entity__entity_type__name",)
    search_fields = ("entity__name", "episode__title")
    readonly_fields = ("entity", "episode", "chunk", "context", "created_at")

    @admin.display(description="Episode", ordering="episode__title")
    def episode_link(self, obj):
        url = reverse("admin:episodes_episode_change", args=[obj.episode_id])
        return format_html('<a href="{}">{}</a>', url, obj.episode)

    @admin.display(description="Chunk", ordering="chunk__index")
    def chunk_link(self, obj):
        url = reverse("admin:episodes_chunk_change", args=[obj.chunk_id])
        return format_html('<a href="{}">{}</a>', url, obj.chunk)

    @admin.display(description="Context")
    def short_context(self, obj):
        if len(obj.context) > 80:
            return format_html("{}&hellip;", obj.context[:80])
        return obj.context

    def has_add_permission(self, request):
        return False


class ProcessingStepInline(admin.TabularInline):
    model = ProcessingStep
    extra = 0
    readonly_fields = ("step_name", "status", "started_at", "finished_at", "error_message")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ProcessingRun)
class ProcessingRunAdmin(admin.ModelAdmin):
    list_display = ("episode_run", "status", "current_step", "started_at", "finished_at", "resumed_from_step")
    list_filter = ("status",)
    readonly_fields = (
        "episode", "status", "started_at", "finished_at", "resumed_from_step",
    )
    inlines = [ProcessingStepInline]

    @admin.display(description="Episode (Run)", ordering="episode__title")
    def episode_run(self, obj):
        return f"{obj.episode} ({obj.pk})"

    @admin.display(description="Current step")
    def current_step(self, obj):
        step = obj.steps.filter(status=ProcessingStep.Status.RUNNING).first()
        return step.step_name if step else "\u2014"

    def has_add_permission(self, request):
        return False
