from django import forms
from django.conf import settings
from django.contrib import admin
from django.db.models import Count
from django.template.response import TemplateResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html
from dbos import DBOS

from .models import (
    PIPELINE_STEPS,
    Chunk,
    Entity,
    EntityMention,
    EntityType,
    Episode,
    PipelineEvent,
    ProcessingRun,
    ProcessingStep,
    RecoveryAttempt,
)


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
    fields = ("entity", "context", "start_time", "created_at")
    readonly_fields = ("entity", "context", "start_time", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntityMentionInlineForEpisode(admin.TabularInline):
    model = EntityMention
    extra = 0
    readonly_fields = ("entity", "chunk", "context", "start_time", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntityMentionInlineForEntity(admin.TabularInline):
    model = EntityMention
    extra = 0
    readonly_fields = ("episode", "chunk", "context", "start_time", "created_at")

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


class PipelineEventInlineForEpisode(admin.TabularInline):
    model = PipelineEvent
    extra = 0
    readonly_fields = ("event_type_display", "step_name", "error_type", "error_message", "created_at")
    fields = ("event_type_display", "step_name", "error_type", "error_message", "created_at")
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Event type")
    def event_type_display(self, obj):
        if obj.event_type == PipelineEvent.EventType.COMPLETED:
            return format_html('<span style="color: green;">{}</span>', obj.event_type)
        return format_html('<span style="color: red;">{}</span>', obj.event_type)


class RecoveryAttemptInlineForEpisode(admin.TabularInline):
    model = RecoveryAttempt
    extra = 0
    readonly_fields = ("strategy", "status", "success", "message", "created_at", "resolved_at", "resolved_by")
    fields = ("strategy", "status", "success", "message", "created_at", "resolved_at", "resolved_by")

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
        inlines = [ProcessingRunInlineForEpisode, PipelineEventInlineForEpisode]
        if obj.recovery_attempts.exists():
            inlines.append(RecoveryAttemptInlineForEpisode)
        if obj.chunks.exists():
            inlines.insert(0, ChunkInlineForEpisode)
        if obj.entity_mentions.exists():
            inlines.append(EntityMentionInlineForEpisode)
        return inlines

    def _awaiting_human(self, obj):
        """True when the episode has an unresolved AWAITING_HUMAN recovery attempt."""
        return obj.recovery_attempts.filter(
            status=RecoveryAttempt.Status.AWAITING_HUMAN
        ).exists()

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None:
            # Creating a new episode — only url is editable
            readonly += list(self.METADATA_FIELDS) + ["status", "scraped_html"]
        elif obj.status == Episode.Status.FAILED and self._awaiting_human(obj):
            # Awaiting human — metadata editable so admin can fix and reprocess
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
        default_step = Episode.Status.FETCHING_DETAILS
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
        from django.contrib import messages
        from dbos._error import DBOSException

        from .models import ProcessingRun
        from .workflows import episode_queue, process_episode

        from_step = request.POST["from_step"]
        episode_ids = request.POST.getlist("episode_ids")
        episodes = Episode.objects.filter(pk__in=episode_ids)

        count = 0
        skipped_titles = []
        for episode in episodes:
            # Skip episodes that already have an active workflow. Without
            # this guard, the second enqueue would create a workflow that
            # later fails create_run() against the partial unique
            # constraint — but only after we've already set status=QUEUED,
            # confusingly overwriting the in-flight run's status.
            if ProcessingRun.objects.filter(
                episode=episode, status=ProcessingRun.Status.RUNNING
            ).exists():
                skipped_titles.append(episode.title or episode.url)
                continue

            # Resolve any AWAITING_HUMAN recovery attempts
            episode.recovery_attempts.filter(
                status=RecoveryAttempt.Status.AWAITING_HUMAN
            ).update(
                status=RecoveryAttempt.Status.RESOLVED,
                resolved_at=timezone.now(),
                resolved_by="human:admin",
            )

            episode.status = Episode.Status.QUEUED
            episode.error_message = ""
            episode.save(update_fields=["status", "error_message", "updated_at"])
            try:
                episode_queue.enqueue(process_episode, episode.pk, from_step)
            except DBOSException:
                logger.debug(
                    "DBOS not initialized; skipping enqueue for episode %s",
                    episode.pk,
                )
            count += 1

        if skipped_titles:
            self.message_user(
                request,
                f"Skipped {len(skipped_titles)} episode(s) with an active "
                f"processing run: {', '.join(skipped_titles[:5])}"
                + (" …" if len(skipped_titles) > 5 else ""),
                level=messages.WARNING,
            )

        self.message_user(
            request,
            f"Queued {count} episode(s) for reprocessing from '{from_step}'.",
        )


@admin.register(Chunk)
class ChunkAdmin(admin.ModelAdmin):
    list_display = ("episode_link", "index", "formatted_time_range", "short_text", "has_entities")
    list_filter = ("episode",)
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
        return f"{fmt(obj.start_time)} \u2013 {fmt(obj.end_time)}"

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


class EntityInlineForEntityType(admin.TabularInline):
    model = Entity
    extra = 0
    fields = ("name", "wikidata_id", "created_at")
    readonly_fields = ("name", "wikidata_id", "created_at")
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


class WikidataSearchWidget(forms.TextInput):
    """A text input that renders the Wikidata search box above it."""

    template_name = "admin/episodes/entitytype/wikidata_search_widget.html"

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["is_wikidata_search"] = True
        return context


class EntityTypeForm(forms.ModelForm):
    examples = CommaSeparatedListField(
        help_text="Comma-separated list of examples, e.g. Miles Davis, Alice Coltrane",
    )

    class Meta:
        model = EntityType
        fields = "__all__"

    def clean_wikidata_id(self):
        value = self.cleaned_data.get("wikidata_id", "")
        if not value and not self.instance.pk:
            min_chars = getattr(settings, "RAGTIME_WIKIDATA_MIN_CHARS", 3)
            raise forms.ValidationError(
                f"Select an entity type from Wikidata. "
                f"Type at least {min_chars} characters in the search box above."
            )
        return value


@admin.register(EntityType)
class EntityTypeAdmin(admin.ModelAdmin):
    form = EntityTypeForm
    list_display = ("name", "key", "wikidata_link", "is_active", "entity_count")
    list_filter = ("is_active",)
    search_fields = ("name", "key")
    inlines = [EntityInlineForEntityType]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("wikidata_id", "key", "name", "description", "examples", "is_active")
        return ("key", "name", "wikidata_id_display", "description", "examples", "is_active", "created_at", "updated_at")

    def get_readonly_fields(self, request, obj=None):
        if obj is not None:
            return ("key", "wikidata_id_display", "created_at", "updated_at")
        return ()

    @admin.display(description="Wikidata ID")
    def wikidata_link(self, obj):
        if obj.wikidata_id:
            return format_html(
                '<a href="https://www.wikidata.org/wiki/{}" target="_blank" rel="noopener">{}</a>',
                obj.wikidata_id,
                obj.wikidata_id,
            )
        return "\u2014"

    @admin.display(description="Wikidata ID")
    def wikidata_id_display(self, obj):
        if obj.wikidata_id:
            return format_html(
                '<a href="https://www.wikidata.org/wiki/{}" target="_blank" rel="noopener">{}</a>',
                obj.wikidata_id,
                obj.wikidata_id,
            )
        return "\u2014"

    def get_form(self, request, obj=None, **kwargs):
        if obj is None:
            kwargs["widgets"] = {
                "wikidata_id": WikidataSearchWidget(
                    attrs={"readonly": "readonly", "class": "vTextField"}
                ),
            }
        return super().get_form(request, obj, **kwargs)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["wikidata_debounce_ms"] = getattr(
            settings, "RAGTIME_WIKIDATA_DEBOUNCE_MS", 300
        )
        extra_context["wikidata_min_chars"] = getattr(
            settings, "RAGTIME_WIKIDATA_MIN_CHARS", 3
        )
        return super().change_view(request, object_id, form_url, extra_context)

    def add_view(self, request, form_url="", extra_context=None):
        extra_context = extra_context or {}
        extra_context["wikidata_debounce_ms"] = getattr(
            settings, "RAGTIME_WIKIDATA_DEBOUNCE_MS", 300
        )
        extra_context["wikidata_min_chars"] = getattr(
            settings, "RAGTIME_WIKIDATA_MIN_CHARS", 3
        )
        return super().add_view(request, form_url, extra_context)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        return qs.annotate(_entity_count=Count("entities"))

    @admin.display(description="Entities", ordering="_entity_count")
    def entity_count(self, obj):
        return obj._entity_count


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "entity_type",
        "musicbrainz_link",
        "wikidata_link",
        "wikidata_status",
        "mention_count",
        "created_at",
    )
    list_filter = ("entity_type__name", "wikidata_status")
    search_fields = ("name", "musicbrainz_id", "wikidata_id")
    readonly_fields = (
        "entity_type",
        "name",
        "musicbrainz_id_display",
        "wikidata_id_display",
        "wikidata_status",
        "wikidata_attempts",
        "wikidata_last_attempted_at",
        "created_at",
        "updated_at",
    )
    inlines = [EntityMentionInlineForEntity]

    def get_fieldsets(self, request, obj=None):
        return [
            (
                None,
                {
                    "fields": (
                        "entity_type",
                        "name",
                        "musicbrainz_id_display",
                        "wikidata_id_display",
                    )
                },
            ),
            (
                "Wikidata enrichment",
                {
                    "classes": ("collapse",),
                    "fields": (
                        "wikidata_status",
                        "wikidata_attempts",
                        "wikidata_last_attempted_at",
                    ),
                },
            ),
            (
                "Timestamps",
                {"classes": ("collapse",), "fields": ("created_at", "updated_at")},
            ),
        ]

    @admin.display(description="MusicBrainz ID", ordering="musicbrainz_id")
    def musicbrainz_link(self, obj):
        if obj.musicbrainz_id:
            short = obj.musicbrainz_id[:8]
            return format_html(
                '<a href="https://musicbrainz.org/{}/{}" target="_blank" '
                'rel="noopener" title="{}">{}\u2026</a>',
                self._mb_path(obj),
                obj.musicbrainz_id,
                obj.musicbrainz_id,
                short,
            )
        return "\u2014"

    @admin.display(description="MusicBrainz ID")
    def musicbrainz_id_display(self, obj):
        if obj.musicbrainz_id:
            return format_html(
                '<a href="https://musicbrainz.org/{}/{}" target="_blank" rel="noopener">{}</a>',
                self._mb_path(obj),
                obj.musicbrainz_id,
                obj.musicbrainz_id,
            )
        return "\u2014"

    @staticmethod
    def _mb_path(obj):
        # Map our musicbrainz_table to MusicBrainz.org's URL path segment.
        # Most match 1:1; release_group is the standout exception.
        table = obj.entity_type.musicbrainz_table
        return {
            "release_group": "release-group",
        }.get(table, table or "artist")

    @admin.display(description="Wikidata ID", ordering="wikidata_id")
    def wikidata_link(self, obj):
        if obj.wikidata_id:
            return format_html(
                '<a href="https://www.wikidata.org/wiki/{}" target="_blank" rel="noopener">{}</a>',
                obj.wikidata_id,
                obj.wikidata_id,
            )
        return "\u2014"

    @admin.display(description="Wikidata ID")
    def wikidata_id_display(self, obj):
        if obj.wikidata_id:
            return format_html(
                '<a href="https://www.wikidata.org/wiki/{}" target="_blank" rel="noopener">{}</a>',
                obj.wikidata_id,
                obj.wikidata_id,
            )
        return "\u2014"

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
    list_display = ("entity", "episode_link", "chunk_link", "short_context", "start_time", "created_at")
    list_filter = ("entity__entity_type__name",)
    search_fields = ("entity__name", "episode__title")
    readonly_fields = ("entity", "episode", "chunk", "context", "start_time", "created_at")

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


class NeedsHumanActionFilter(admin.SimpleListFilter):
    title = "needs human action"
    parameter_name = "needs_human"

    def lookups(self, request, model_admin):
        return [("yes", "Yes")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(status=RecoveryAttempt.Status.AWAITING_HUMAN)
        return queryset


@admin.register(PipelineEvent)
class PipelineEventAdmin(admin.ModelAdmin):
    list_display = ("episode", "event_type_display", "step_name", "error_type", "created_at")
    list_filter = ("event_type", "step_name", "error_type")
    readonly_fields = (
        "episode", "processing_step", "event_type", "step_name",
        "error_type", "error_message", "http_status", "exception_class",
        "context", "created_at",
    )

    @admin.display(description="Event type")
    def event_type_display(self, obj):
        if obj.event_type == PipelineEvent.EventType.COMPLETED:
            return format_html('<span style="color: green;">{}</span>', obj.event_type)
        return format_html('<span style="color: red;">{}</span>', obj.event_type)

    def has_add_permission(self, request):
        return False


@admin.register(RecoveryAttempt)
class RecoveryAttemptAdmin(admin.ModelAdmin):
    list_display = ("episode", "strategy", "status", "success", "created_at", "resolved_at")
    list_filter = (NeedsHumanActionFilter, "strategy", "status")
    readonly_fields = (
        "episode", "pipeline_event", "strategy", "status", "success",
        "message", "created_at", "resolved_at", "resolved_by",
    )
    actions = ["retry_agent_recovery"]

    @admin.action(description="Retry with recovery agent")
    def retry_agent_recovery(self, request, queryset):
        awaiting = queryset.filter(status=RecoveryAttempt.Status.AWAITING_HUMAN)
        if not awaiting.exists():
            from django.contrib import messages

            self.message_user(
                request,
                "No selected attempts are awaiting human action.",
                level=messages.WARNING,
            )
            return

        count = 0
        for attempt in awaiting.select_related("pipeline_event", "episode"):
            pe = attempt.pipeline_event
            attempt.status = RecoveryAttempt.Status.RESOLVED
            attempt.resolved_at = timezone.now()
            attempt.resolved_by = "human:admin-retry"
            attempt.save(update_fields=["status", "resolved_at", "resolved_by"])

            from .workflows import run_agent_recovery

            DBOS.start_workflow(
                run_agent_recovery,
                attempt.episode_id,
                pe.pk,
            )
            count += 1

        self.message_user(
            request,
            f"Queued agent recovery for {count} attempt(s).",
        )

    def has_add_permission(self, request):
        return False


