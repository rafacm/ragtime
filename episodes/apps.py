from django.apps import AppConfig


class EpisodesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'episodes'

    def ready(self):
        import episodes.signals  # noqa: F401

        from .observability import setup as setup_observability
        from .recovery import handle_step_failure
        from .signals import step_completed, step_failed

        step_failed.connect(handle_step_failure, dispatch_uid="recovery_step_failed")

        try:
            from .agents.linker import handle_resolve_completed

            step_completed.connect(
                handle_resolve_completed,
                dispatch_uid="linking_resolve_completed",
            )
        except Exception:
            pass

        setup_observability()
