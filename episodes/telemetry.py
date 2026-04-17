"""OpenTelemetry telemetry layer for LLM calls and pipeline steps.

Pipeline steps and provider calls are traced via the OpenTelemetry SDK.
Traces are exported to any combination of collectors configured via
``RAGTIME_OTEL_COLLECTORS``: ``console``, ``jaeger``, or ``langfuse``.

When no collectors are configured (the default), the OTel API provides a
no-op tracer with zero overhead.
"""

import functools
import logging
import os
import sys

from django.conf import settings

logger = logging.getLogger(__name__)

_tracers: dict[str, object] = {}


def setup():
    """Initialize the OTel TracerProvider at startup.

    Called from ``EpisodesConfig.ready()``.  Configures one span processor
    per collector in ``RAGTIME_OTEL_COLLECTORS`` and registers the
    TracerProvider globally.  No-op when no collectors are configured or
    during test runs.
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

        for collector in _configured_collectors():
            processor = _build_processor(collector)
            if processor is not None:
                provider.add_span_processor(processor)

        trace.set_tracer_provider(provider)

        # Langfuse registers its own SpanProcessor on the active
        # TracerProvider when get_client() is called.  Must happen
        # after set_tracer_provider().
        if is_langfuse_enabled():
            _setup_langfuse()

        _instrument_openai()

        logger.debug(
            "OTel TracerProvider initialized (collectors=%s)",
            ",".join(_configured_collectors()),
        )
    except Exception:
        logger.warning(
            "Failed to initialize OTel TracerProvider", exc_info=True
        )


def _build_processor(name):
    """Build a SpanProcessor for the given collector name."""
    if name == "console":
        from opentelemetry.sdk.trace.export import (
            ConsoleSpanExporter,
            SimpleSpanProcessor,
        )

        return SimpleSpanProcessor(ConsoleSpanExporter())

    if name == "jaeger":
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        endpoint = getattr(
            settings,
            "RAGTIME_OTEL_JAEGER_ENDPOINT",
            "http://localhost:4318",
        )
        return BatchSpanProcessor(
            OTLPSpanExporter(endpoint=f"{endpoint}/v1/traces")
        )

    if name == "langfuse":
        # Langfuse registers itself via get_client(); handled in setup().
        return None

    logger.warning("Unknown OTel collector: %s", name)
    return None


def _setup_langfuse():
    """Configure Langfuse as an OTel collector.

    Sets ``LANGFUSE_*`` env vars from Django settings and calls
    ``langfuse.get_client()`` which registers a ``LangfuseSpanProcessor``
    on the active TracerProvider.
    """
    secret_key = getattr(settings, "RAGTIME_LANGFUSE_SECRET_KEY", "")
    public_key = getattr(settings, "RAGTIME_LANGFUSE_PUBLIC_KEY", "")
    if not (secret_key and public_key):
        logger.warning(
            "Langfuse collector enabled but API keys are missing"
        )
        return

    host = getattr(
        settings, "RAGTIME_LANGFUSE_HOST", "http://localhost:3000"
    )
    os.environ.setdefault("LANGFUSE_SECRET_KEY", secret_key)
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", public_key)
    os.environ.setdefault("LANGFUSE_HOST", host)

    try:
        import langfuse

        langfuse.get_client()
        logger.debug("Langfuse SpanProcessor registered")
    except ImportError:
        logger.warning(
            "Langfuse collector enabled but langfuse package not installed "
            "(install with: uv sync --extra langfuse)"
        )
    except Exception:
        logger.warning(
            "Failed to initialize Langfuse collector", exc_info=True
        )


def _instrument_openai():
    """Instrument the openai library via OTel instrumentor."""
    try:
        from opentelemetry.instrumentation.openai import OpenAIInstrumentor

        OpenAIInstrumentor().instrument()
    except ImportError:
        logger.debug(
            "opentelemetry-instrumentation-openai not installed, skipping"
        )
    except Exception:
        logger.debug("Failed to instrument OpenAI", exc_info=True)


def is_enabled():
    """Return True when OTel tracing is active.

    Tracing is active when ``RAGTIME_OTEL_COLLECTORS`` contains at least
    one collector name.  Always disabled during test runs.
    """
    if "test" in sys.argv:
        return False
    return bool(_configured_collectors())


def _configured_collectors():
    """Return the list of configured collector names."""
    raw = getattr(settings, "RAGTIME_OTEL_COLLECTORS", "")
    return [c.strip().lower() for c in raw.split(",") if c.strip()]


def is_langfuse_enabled():
    """Return True when the Langfuse collector is active."""
    return is_enabled() and "langfuse" in _configured_collectors()


def get_tracer(name="ragtime"):
    """Return an OTel Tracer, cached by name.

    Returns a no-op tracer when disabled.
    """
    if name in _tracers:
        return _tracers[name]

    from opentelemetry import trace

    tracer = trace.get_tracer(name)
    _tracers[name] = tracer
    return tracer


def trace_step(name):
    """Decorator factory that wraps a pipeline step with OTel tracing.

    The decorated function must accept ``episode_id`` as its first argument.
    Creates a span named *name* with episode metadata as attributes.

    When the Langfuse collector is active, wraps execution with
    ``langfuse.propagate_attributes()`` so that ``session_id``,
    ``user_id``, and ``metadata`` propagate to all child spans.

    Returns a no-op passthrough when OTel is disabled.
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(episode_id, *args, **kwargs):
            if not is_enabled():
                return func(episode_id, *args, **kwargs)

            tracer = get_tracer()
            attributes, session_id, user_id, metadata = (
                _build_step_attributes(name, episode_id)
            )

            with tracer.start_as_current_span(name, attributes=attributes):
                if is_langfuse_enabled():
                    try:
                        from langfuse import propagate_attributes

                        with propagate_attributes(
                            session_id=session_id,
                            user_id=user_id,
                            metadata=metadata,
                        ):
                            result = func(episode_id, *args, **kwargs)
                    except ImportError:
                        result = func(episode_id, *args, **kwargs)
                else:
                    result = func(episode_id, *args, **kwargs)

                from .models import Episode

                try:
                    episode = Episode.objects.get(pk=episode_id)
                    episode.refresh_from_db(fields=["status"])
                    return {
                        "status": episode.status,
                        "episode_id": episode_id,
                    }
                except Episode.DoesNotExist:
                    return {
                        "status": "unknown",
                        "episode_id": episode_id,
                    }

        return wrapper

    return decorator


def _build_step_attributes(step_name, episode_id):
    """Build OTel span attributes for a pipeline step.

    Returns (attributes_dict, session_id, user_id, metadata_dict).
    """
    from .models import Episode, ProcessingRun

    attributes = {
        "ragtime.step.name": step_name,
        "ragtime.episode.id": str(episode_id),
    }

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
        session_id = f"processing-run-{run.pk}-episode-{episode_id}-{ts}"
    else:
        session_id = f"episode-{episode_id}"

    user_id = f"episode-{episode_id}"
    attributes["ragtime.session.id"] = session_id

    metadata = {"episode_id": str(episode_id)}

    try:
        episode = Episode.objects.get(pk=episode_id)
        if episode.title:
            attributes["ragtime.episode.title"] = episode.title
            metadata["episode_title"] = episode.title
    except Episode.DoesNotExist:
        pass

    return attributes, session_id, user_id, metadata


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
            event_attrs["llm.input.response_schema"] = str(
                response_schema
            )
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
