"""OpenTelemetry observability layer for LLM calls and pipeline steps.

When ``RAGTIME_OTEL_ENABLED`` is true, pipeline steps and provider calls
are traced via the OpenTelemetry SDK.  Traces are exported to any
OTLP-compatible backend (Langfuse, Sentry, Jaeger, etc.) configured via
``RAGTIME_OTEL_EXPORTER`` and ``RAGTIME_OTEL_ENDPOINT``.

When disabled (the default) there is zero overhead — OTel is never imported.
"""

import functools
import logging
import sys

from django.conf import settings

logger = logging.getLogger(__name__)

_tracer = None


def setup():
    """Initialize the OTel TracerProvider at startup.

    Called from ``EpisodesConfig.ready()``.  Configures the exporter based
    on ``RAGTIME_OTEL_EXPORTER`` and registers the TracerProvider globally.
    No-op when disabled or during tests.
    """
    if not is_enabled():
        return

    try:
        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider

        service_name = getattr(
            settings, "RAGTIME_OTEL_SERVICE_NAME", "ragtime"
        )
        resource = Resource.create({"service.name": service_name})
        provider = TracerProvider(resource=resource)

        exporter = _build_exporter()
        if exporter is not None:
            from opentelemetry.sdk.trace.export import BatchSpanProcessor

            provider.add_span_processor(BatchSpanProcessor(exporter))

        trace.set_tracer_provider(provider)
        logger.debug(
            "OTel TracerProvider initialized (exporter=%s)",
            getattr(settings, "RAGTIME_OTEL_EXPORTER", "otlp"),
        )
    except ImportError:
        logger.warning(
            "OTel enabled but opentelemetry-sdk not installed — "
            "install with: uv sync --extra observability"
        )
    except Exception:
        logger.warning("Failed to initialize OTel TracerProvider", exc_info=True)


def _build_exporter():
    """Build the configured span exporter, or None for 'none'/'console'."""
    exporter_type = getattr(
        settings, "RAGTIME_OTEL_EXPORTER", "otlp"
    ).lower()

    if exporter_type == "none":
        return None

    if exporter_type == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()

    # Default: OTLP HTTP exporter
    endpoint = getattr(
        settings, "RAGTIME_OTEL_ENDPOINT", "http://localhost:4318"
    )
    headers_str = getattr(settings, "RAGTIME_OTEL_HEADERS", "")
    headers = {}
    if headers_str:
        for pair in headers_str.split(","):
            if "=" in pair:
                k, _, v = pair.partition("=")
                headers[k.strip()] = v.strip()

    from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
        OTLPSpanExporter,
    )

    return OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces", headers=headers)


def is_enabled():
    """Return True when OTel tracing is enabled.

    Disabled during test runs and when ``RAGTIME_OTEL_ENABLED`` is false.
    """
    if "test" in sys.argv:
        return False
    return getattr(settings, "RAGTIME_OTEL_ENABLED", False)


def get_tracer(name="ragtime"):
    """Return an OTel Tracer, or a no-op tracer when disabled."""
    global _tracer
    if _tracer is not None:
        return _tracer

    if not is_enabled():
        from opentelemetry import trace

        return trace.get_tracer(name)

    from opentelemetry import trace

    _tracer = trace.get_tracer(name)
    return _tracer


def trace_step(name):
    """Decorator factory that wraps a pipeline step with OTel tracing.

    The decorated function must accept ``episode_id`` as its first argument.
    Creates a span named *name* with episode metadata as attributes.

    Returns a no-op passthrough when OTel is disabled.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(episode_id, *args, **kwargs):
            if not is_enabled():
                return func(episode_id, *args, **kwargs)

            from .models import Episode, ProcessingRun

            tracer = get_tracer()

            run = (
                ProcessingRun.objects.filter(
                    episode_id=episode_id,
                    status=ProcessingRun.Status.RUNNING,
                )
                .order_by("-started_at")
                .first()
            )

            if run:
                ts = run.started_at.strftime("%Y-%m-%d-%H-%M")
                session_id = (
                    f"processing-run-{run.pk}-episode-{episode_id}-{ts}"
                )
            else:
                session_id = f"episode-{episode_id}"

            try:
                episode = Episode.objects.get(pk=episode_id)
            except Episode.DoesNotExist:
                episode = None

            attributes = {
                "ragtime.step.name": name,
                "ragtime.episode.id": str(episode_id),
                "ragtime.session.id": session_id,
            }
            if episode and episode.title:
                attributes["ragtime.episode.title"] = episode.title

            with tracer.start_as_current_span(name, attributes=attributes):
                result = func(episode_id, *args, **kwargs)

                if episode:
                    episode.refresh_from_db(fields=["status"])
                    return {
                        "status": episode.status,
                        "episode_id": episode_id,
                    }
                return {"status": "unknown", "episode_id": episode_id}

        return wrapper

    return decorator


def trace_provider(func):
    """Decorator that wraps a provider method with its own OTel span.

    Creates a child span under the current step trace.  No-op when
    OTel is disabled.  Designed for instance methods (skips ``self``
    when capturing arguments).
    """

    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if not is_enabled():
            return func(self, *args, **kwargs)

        tracer = get_tracer()
        with tracer.start_as_current_span(func.__name__):
            return func(self, *args, **kwargs)

    return wrapper


def record_llm_input(*args, **kwargs):
    """Record LLM call input as a span event.

    Two calling conventions:

    **Chat-style** (positional args)::

        record_llm_input(system_prompt, user_content, response_schema=schema)

    **Dict-style** (keyword args only)::

        record_llm_input(audio_file="ep.mp3", model="whisper-1", ...)

    No-op when OTel is disabled.
    """
    # Validate calling convention regardless of enabled state
    if args:
        if len(args) != 2:
            raise TypeError(
                "record_llm_input() chat-style expects exactly 2 positional "
                "arguments: system_prompt, user_content"
            )
        allowed_kwargs = {"response_schema"}
        unexpected_kwargs = set(kwargs) - allowed_kwargs
        if unexpected_kwargs:
            raise TypeError(
                "record_llm_input() chat-style does not accept keyword "
                f"arguments: {', '.join(sorted(unexpected_kwargs))}"
            )

    if not is_enabled():
        return

    from opentelemetry import trace

    span = trace.get_current_span()
    if not span.is_recording():
        return

    if args:
        system_prompt, user_content = args
        event_attrs = {
            "llm.input.system": system_prompt,
            "llm.input.user": (
                user_content[:2000]
                if isinstance(user_content, str)
                else str(user_content)[:2000]
            ),
        }
        response_schema = kwargs.get("response_schema")
        if response_schema is not None:
            event_attrs["llm.input.response_schema"] = str(response_schema)
    else:
        event_attrs = {
            f"llm.input.{k}": str(v)[:2000] for k, v in kwargs.items()
        }

    span.add_event("llm.input", attributes=event_attrs)


def record_llm_output(output):
    """Record LLM call output as a span event.

    No-op when OTel is disabled.
    """
    if not is_enabled():
        return

    from opentelemetry import trace

    span = trace.get_current_span()
    if not span.is_recording():
        return

    span.add_event(
        "llm.output",
        attributes={"llm.output.value": str(output)[:4000]},
    )
