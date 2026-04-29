import json

from django import forms
from django.conf import settings
from django.contrib import admin
from django.db.models import Count
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import (
    PIPELINE_STEPS,
    Chunk,
    Entity,
    EntityMention,
    EntityType,
    Episode,
    FetchDetailsRun,
)


def _dbos_field(record, name, default=None):
    """Read *name* from a DBOS record (TypedDict or attribute object).

    DBOS's Python SDK returns ``list_workflows`` / ``list_workflow_steps``
    rows as dicts (TypedDicts) — ``getattr`` silently fails on those.
    Fall back to attribute access for forward compatibility in case a
    future DBOS version switches to dataclasses.
    """
    if isinstance(record, dict):
        return record.get(name, default)
    return getattr(record, name, default)


def _decode_dbos_payload(value):
    """Render a DBOS step output / error payload as a readable string.

    DBOS stores per-step ``output`` and ``error`` as pickle bytes,
    base64-encoded for transport. The Python API leaves them in
    that wire form when the listing call reads from the system DB
    rather than reconstructing the objects.

    This helper:
    1. Returns ``None`` / ``""`` for empty values unchanged.
    2. Tries ``base64 → pickle.loads`` when the string looks like a
       pickle stream (starts with ``gAS`` — the b64 prefix for the
       pickle protocol 4 magic ``\\x80\\x04\\x95``).
    3. Falls back to the raw string when decoding fails (so a
       future DBOS version that already returns native objects
       still renders).

    Pickle is unsafe on untrusted input; here the bytes were
    written by this same process into a database we own — same
    trust boundary as DBOS itself.
    """
    import base64
    import pickle

    if value in (None, ""):
        return value
    if not isinstance(value, str):
        return str(value)
    if not value.startswith("gAS"):
        return value
    try:
        obj = pickle.loads(base64.b64decode(value))
    except Exception:
        return value
    return str(obj)


def _epoch_ms_to_datetime(value):
    """Convert a DBOS epoch-ms timestamp into a ``datetime`` (or ``None``)."""
    if value is None:
        return None
    try:
        from datetime import datetime, timezone

        return datetime.fromtimestamp(int(value) / 1000, tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _step_rows_for_workflow(workflow_id: str) -> list[dict]:
    """Return the per-step rows for a single workflow, or ``[]`` on error."""
    try:
        from dbos import DBOS

        steps = DBOS.list_workflow_steps(workflow_id) or []
    except Exception:
        return []

    rows = []
    for step in steps:
        rows.append({
            "function_name": _dbos_field(step, "function_name", ""),
            "step_id": _dbos_field(step, "function_id", None),
            "output": _decode_dbos_payload(_dbos_field(step, "output", None)),
            "error": _decode_dbos_payload(_dbos_field(step, "error", None)),
            "started_at": _epoch_ms_to_datetime(
                _dbos_field(step, "started_at_epoch_ms")
            ),
            "completed_at": _epoch_ms_to_datetime(
                _dbos_field(step, "completed_at_epoch_ms")
            ),
        })
    return rows


def _dbos_workflow_runs(episode_id: int) -> list[dict]:
    """Return every DBOS workflow recorded for *episode_id*, newest first.

    Each entry includes the workflow's ID, status, timestamps, and the
    full list of steps under that run. Mirrors the old
    ``ProcessingRunInlineForEpisode`` + ``ProcessingStepInline`` UX so
    the admin can see *every* attempt instead of only the most recent.

    Returns ``[]`` when DBOS isn't running, no workflow exists, or
    anything raises — admin must keep loading even when the queue is
    offline.
    """
    try:
        from dbos import DBOS
    except ImportError:
        return []

    try:
        workflows = DBOS.list_workflows() or []
    except Exception:
        return []

    prefix = f"episode-{episode_id}-"
    candidates = [
        wf for wf in workflows
        if (_dbos_field(wf, "workflow_id", "") or "").startswith(prefix)
    ]
    if not candidates:
        return []

    candidates.sort(
        key=lambda wf: _dbos_field(wf, "created_at", 0) or 0,
        reverse=True,
    )

    runs = []
    for wf in candidates:
        workflow_id = _dbos_field(wf, "workflow_id", "")
        runs.append({
            "workflow_id": workflow_id,
            "status": _dbos_field(wf, "status", ""),
            "name": _dbos_field(wf, "name", ""),
            "queue_name": _dbos_field(wf, "queue_name", ""),
            "recovery_attempts": _dbos_field(wf, "recovery_attempts", 0),
            "created_at": _epoch_ms_to_datetime(_dbos_field(wf, "created_at")),
            "updated_at": _epoch_ms_to_datetime(_dbos_field(wf, "updated_at")),
            "steps": _step_rows_for_workflow(workflow_id),
        })
    return runs


def _dbos_workflow_steps(episode_id: int) -> list[dict]:
    """Return per-step rows for the most recent workflow of *episode_id*.

    Kept as a thin convenience wrapper over ``_dbos_workflow_runs``
    for any caller that only wants the latest run's steps. Returns
    ``[]`` when there are no workflows.
    """
    runs = _dbos_workflow_runs(episode_id)
    if not runs:
        return []
    return runs[0]["steps"]


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


class FetchDetailsRunInlineForEpisode(admin.TabularInline):
    model = FetchDetailsRun
    extra = 0
    classes = ("collapse",)
    verbose_name_plural = "Fetch Details runs"
    fields = (
        "run_index",
        "outcome",
        "concise_summary",
        "extraction_confidence",
        "model",
        "started_at",
    )
    readonly_fields = (
        "run_index",
        "outcome",
        "concise_summary",
        "extraction_confidence",
        "model",
        "started_at",
    )
    show_change_link = True
    ordering = ("-run_index",)

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Summary")
    def concise_summary(self, obj):
        if not obj or not obj.output_json:
            return "—"
        concise = (obj.output_json or {}).get("concise") or {}
        return concise.get("summary") or "—"

    @admin.display(description="Confidence")
    def extraction_confidence(self, obj):
        if not obj or not obj.output_json:
            return "—"
        report = (obj.output_json or {}).get("report") or {}
        return report.get("extraction_confidence") or "—"


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("title", "url", "language", "formatted_duration", "status", "created_at", "updated_at")
    list_filter = ("status", "language", "source_kind", "aggregator_provider")
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
        "dbos_steps_link",
        "latest_fetch_details_run_summary",
    )
    actions = ["reprocess"]

    METADATA_FIELDS = (
        "title",
        "description",
        "published_at",
        "image_url",
        "language",
        "audio_url",
        "audio_format",
        "guid",
        "country",
    )

    SOURCE_FIELDS = (
        "canonical_url",
        "source_kind",
        "aggregator_provider",
    )

    def get_inlines(self, request, obj=None):
        if obj is None:
            return []
        inlines = []
        if obj.fetch_details_runs.exists():
            inlines.append(FetchDetailsRunInlineForEpisode)
        if obj.chunks.exists():
            inlines.append(ChunkInlineForEpisode)
        if obj.entity_mentions.exists():
            inlines.append(EntityMentionInlineForEpisode)
        return inlines

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if obj is None:
            # Creating a new episode — only url is editable
            readonly += list(self.METADATA_FIELDS) + list(self.SOURCE_FIELDS) + ["status"]
        elif obj.status == Episode.Status.FAILED:
            # FAILED — metadata editable so admin can fix and reprocess
            readonly += ["status"]
        else:
            # All other statuses — everything read-only except url
            readonly += list(self.METADATA_FIELDS) + list(self.SOURCE_FIELDS) + ["status"]
        return readonly

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            return [(None, {"fields": ("url",)})]
        main_fields = ["url", "status", "dbos_steps_link"]
        if obj.status == Episode.Status.FAILED and obj.error_message:
            main_fields.append("error_message")
        fieldsets = [
            (None, {"fields": main_fields}),
        ]
        if obj.fetch_details_runs.exists():
            fieldsets.append((
                "Latest Fetch Details run",
                {"fields": ("latest_fetch_details_run_summary",)},
            ))
        fieldsets += [
            (
                "Source",
                {"fields": self.SOURCE_FIELDS},
            ),
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
                "Timestamps",
                {
                    "classes": ("collapse",),
                    "fields": ("created_at", "updated_at"),
                },
            ),
        ]
        return fieldsets

    @admin.display(description="Latest run")
    def latest_fetch_details_run_summary(self, obj):
        if not obj or not obj.pk:
            return "—"
        run = (
            obj.fetch_details_runs.order_by("-run_index").first()
        )
        if run is None:
            return "—"
        output = run.output_json or {}
        concise = output.get("concise") or {}
        report = output.get("report") or {}

        change_url = reverse(
            "admin:episodes_fetchdetailsrun_change", args=[run.pk]
        )

        outcome = run.outcome or "—"
        summary = concise.get("summary") or "—"
        narrative = report.get("narrative") or ""
        hints = report.get("hints_for_next_step") or ""
        confidence = report.get("extraction_confidence") or "—"

        # Compose with format_html for safe escaping; narrative blocks
        # rendered into <pre> so line breaks survive without raw HTML.
        return format_html(
            (
                '<div style="line-height:1.5">'
                '<div><strong>Run #{0}</strong> · '
                '<a href="{1}">view details</a></div>'
                '<div><strong>Outcome:</strong> {2}</div>'
                '<div><strong>Confidence:</strong> {3}</div>'
                '<div><strong>Summary:</strong> {4}</div>'
                '<div style="margin-top:0.5em"><strong>Narrative:</strong>'
                '<pre style="white-space:pre-wrap;margin:0">{5}</pre></div>'
                '<div style="margin-top:0.5em"><strong>Hints for next step:</strong>'
                '<pre style="white-space:pre-wrap;margin:0">{6}</pre></div>'
                '</div>'
            ),
            run.run_index,
            change_url,
            outcome,
            confidence,
            summary,
            narrative,
            hints,
        )

    @admin.display(description="DBOS workflows")
    def dbos_steps_link(self, obj):
        if not obj or not obj.pk:
            return "—"
        url = reverse("admin:episodes_episode_dbos_steps", args=[obj.pk])
        return format_html('<a href="{}">View workflow runs</a>', url)

    @admin.display(description="Duration", ordering="duration")
    def formatted_duration(self, obj):
        if obj.duration is None:
            return "\u2014"
        hours, remainder = divmod(obj.duration, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"

    def get_urls(self):
        urls = super().get_urls()
        custom = [
            path(
                "<int:episode_id>/dbos-steps/",
                self.admin_site.admin_view(self.dbos_steps_view),
                name="episodes_episode_dbos_steps",
            ),
        ]
        return custom + urls

    def dbos_steps_view(self, request, episode_id: int):
        """Render every DBOS workflow run for *episode_id* with its steps.

        Replaces the old ProcessingRun / PipelineEvent admin pages \u2014
        each ``episode-<id>-run-<n>`` workflow is shown as its own
        section with a per-step table, newest run first.
        """
        episode = Episode.objects.get(pk=episode_id)
        runs = _dbos_workflow_runs(episode_id)
        context = {
            **self.admin_site.each_context(request),
            "title": f"DBOS workflow runs \u2014 {episode}",
            "episode": episode,
            "runs": runs,
            "opts": self.model._meta,
        }
        return TemplateResponse(
            request, "admin/episodes/episode/dbos_steps.html", context,
        )

    @admin.action(description="Reprocess selected episodes\u2026")
    def reprocess(self, request, queryset):
        if "from_step" in request.POST:
            return self._execute_reprocess(request, queryset)
        return self._show_reprocess_page(request, queryset)

    def _get_last_failed_step(self, episode):
        # ProcessingRun/Step were dropped — we no longer record per-step
        # status. Default the reprocess form to "fetching_details"; the
        # admin can choose any pipeline step from the dropdown.
        if episode.status == Episode.Status.FAILED:
            return Episode.Status.FETCHING_DETAILS
        return None

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
        from .workflows import enqueue_episode

        from_step = request.POST["from_step"]
        episode_ids = request.POST.getlist("episode_ids")
        episodes = Episode.objects.filter(pk__in=episode_ids)

        count = 0
        for episode in episodes:
            episode.status = Episode.Status.QUEUED
            episode.error_message = ""
            episode.save(update_fields=["status", "error_message", "updated_at"])
            # ``enqueue_episode`` computes the next ``run-<n>`` suffix so the
            # admin trace view's ``episode-<id>-`` prefix filter resolves to
            # the freshly-enqueued workflow.
            enqueue_episode(episode.pk, from_step)
            count += 1

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


def _pretty_json(value) -> str:
    """Render a JSON value as a pre-formatted, indented string."""
    if value in (None, ""):
        return "—"
    try:
        return json.dumps(value, indent=2, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


@admin.register(FetchDetailsRun)
class FetchDetailsRunAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "episode_link",
        "run_index",
        "outcome",
        "model",
        "started_at",
    )
    list_filter = ("outcome", "model")
    search_fields = (
        "episode__title", "episode__url", "dbos_workflow_id",
    )
    readonly_fields = (
        "episode_link",
        "run_index",
        "outcome",
        "model",
        "started_at",
        "finished_at",
        "dbos_workflow_id_link",
        "concise_block",
        "report_block",
        "details_block",
        "tool_calls_block",
        "output_json_pretty",
        "usage_json_pretty",
        "error_message",
    )
    fieldsets = (
        (None, {
            "fields": (
                "episode_link",
                "run_index",
                "outcome",
                "model",
                "started_at",
                "finished_at",
                "dbos_workflow_id_link",
                "error_message",
            ),
        }),
        ("Concise", {"fields": ("concise_block",)}),
        ("Report", {"fields": ("report_block",)}),
        ("Details", {"fields": ("details_block",)}),
        ("Tool calls", {
            "classes": ("collapse",),
            "fields": ("tool_calls_block",),
        }),
        ("Raw payloads", {
            "classes": ("collapse",),
            "fields": ("output_json_pretty", "usage_json_pretty"),
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Episode")
    def episode_link(self, obj):
        if not obj or not obj.episode_id:
            return "—"
        url = reverse("admin:episodes_episode_change", args=[obj.episode_id])
        return format_html('<a href="{}">{}</a>', url, obj.episode)

    @admin.display(description="DBOS workflow")
    def dbos_workflow_id_link(self, obj):
        if not obj or not obj.dbos_workflow_id:
            return "—"
        episode_id = obj.episode_id
        if episode_id:
            url = reverse(
                "admin:episodes_episode_dbos_steps", args=[episode_id]
            )
            return format_html(
                '<a href="{}">{}</a>', url, obj.dbos_workflow_id,
            )
        return obj.dbos_workflow_id

    @admin.display(description="Concise message")
    def concise_block(self, obj):
        if not obj or not obj.output_json:
            return "—"
        concise = (obj.output_json or {}).get("concise") or {}
        return format_html(
            '<div><strong>Outcome:</strong> {}</div>'
            '<div><strong>Summary:</strong> {}</div>',
            concise.get("outcome") or "—",
            concise.get("summary") or "—",
        )

    @admin.display(description="Report")
    def report_block(self, obj):
        if not obj or not obj.output_json:
            return "—"
        report = (obj.output_json or {}).get("report") or {}
        attempted = report.get("attempted_sources") or []
        attempted_lines = format_html_join_lines(
            "{} · {} · {} · {}",
            (
                (
                    a.get("source", "?"),
                    a.get("url_or_query", ""),
                    a.get("outcome", "?"),
                    a.get("note", ""),
                )
                for a in attempted
            ),
        )
        return format_html(
            (
                '<div><strong>Confidence:</strong> {}</div>'
                '<div><strong>Discovered canonical_url:</strong> {}</div>'
                '<div><strong>Discovered audio_url:</strong> {}</div>'
                '<div><strong>Cross-linked:</strong> {}</div>'
                '<div style="margin-top:0.5em"><strong>Narrative:</strong>'
                '<pre style="white-space:pre-wrap;margin:0">{}</pre></div>'
                '<div style="margin-top:0.5em"><strong>Hints for next step:</strong>'
                '<pre style="white-space:pre-wrap;margin:0">{}</pre></div>'
                '<div style="margin-top:0.5em"><strong>Attempted sources:</strong>'
                '<pre style="white-space:pre-wrap;margin:0">{}</pre></div>'
            ),
            report.get("extraction_confidence") or "—",
            "yes" if report.get("discovered_canonical_url") else "no",
            "yes" if report.get("discovered_audio_url") else "no",
            "yes" if report.get("cross_linked") else "no",
            report.get("narrative") or "",
            report.get("hints_for_next_step") or "",
            attempted_lines or "—",
        )

    @admin.display(description="Episode details")
    def details_block(self, obj):
        if not obj or not obj.output_json:
            return "—"
        details = (obj.output_json or {}).get("details") or {}
        return format_html(
            '<pre style="white-space:pre-wrap;margin:0">{}</pre>',
            _pretty_json(details),
        )

    @admin.display(description="Tool calls")
    def tool_calls_block(self, obj):
        if not obj or not obj.tool_calls_json:
            return "—"
        return format_html(
            '<pre style="white-space:pre-wrap;margin:0">{}</pre>',
            _pretty_json(obj.tool_calls_json),
        )

    @admin.display(description="output_json")
    def output_json_pretty(self, obj):
        return format_html(
            '<pre style="white-space:pre-wrap;margin:0">{}</pre>',
            _pretty_json(obj.output_json) if obj else "—",
        )

    @admin.display(description="usage_json")
    def usage_json_pretty(self, obj):
        return format_html(
            '<pre style="white-space:pre-wrap;margin:0">{}</pre>',
            _pretty_json(obj.usage_json) if obj else "—",
        )


def format_html_join_lines(format_string, args_iter) -> str:
    """``format_html_join`` analogue that emits one safe line per record."""
    lines = [format_html(format_string, *args) for args in args_iter]
    return mark_safe("\n".join(lines)) if lines else ""


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


