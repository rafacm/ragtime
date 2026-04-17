from django.apps import AppConfig


class EpisodesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'episodes'

    def ready(self):
        import episodes.signals  # noqa: F401

        from .recovery import handle_step_failure
        from .signals import step_failed
        from .telemetry import setup as setup_telemetry

        step_failed.connect(handle_step_failure, dispatch_uid="recovery_step_failed")
        setup_telemetry()
