from django.contrib import admin
from django.db.models import Count
from django.template.response import TemplateResponse
from django.utils.html import format_html
from django_q.tasks import async_task

from .models import (
    PIPELINE_STEPS,
    Entity,
    EntityMention,
    Episode,
    ProcessingRun,
    ProcessingStep,
)
from .processing import create_run


class EntityMentionInlineForEpisode(admin.TabularInline):
    model = EntityMention
    extra = 0
    readonly_fields = ("entity", "context", "created_at")

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class EntityMentionInlineForEntity(admin.TabularInline):
    model = EntityMention
    extra = 0
    readonly_fields = ("episode", "context", "created_at")

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
    list_display = ("url", "title", "language", "status", "created_at")
    list_filter = ("status", "language")
    readonly_fields = (
        "created_at",
        "updated_at",
        "audio_file",
        "error_message",
        "transcript",
        "transcript_json",
        "summary_generated",
        "entities_json",
    )
    actions = ["reprocess"]
    inlines = [EntityMentionInlineForEpisode, ProcessingRunInlineForEpisode]

    METADATA_FIELDS = (
        "title",
        "description",
        "published_at",
        "image_url",
        "language",
        "audio_url",
    )

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
            fieldsets.append(("Files", {"fields": ("audio_file",)}))
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


@admin.register(Entity)
class EntityAdmin(admin.ModelAdmin):
    list_display = ("name", "entity_type", "mention_count", "created_at")
    list_filter = ("entity_type",)
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
    list_display = ("entity", "episode", "short_context", "created_at")
    list_filter = ("entity__entity_type",)
    search_fields = ("entity__name", "episode__title")
    readonly_fields = ("entity", "episode", "context", "created_at")

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
    list_display = ("episode_run", "status", "started_at", "finished_at", "resumed_from_step")
    list_filter = ("status",)
    readonly_fields = (
        "episode", "status", "started_at", "finished_at", "resumed_from_step",
    )
    inlines = [ProcessingStepInline]

    @admin.display(description="Episode (Run)", ordering="episode__title")
    def episode_run(self, obj):
        return f"{obj.episode} ({obj.pk})"

    def has_add_permission(self, request):
        return False
