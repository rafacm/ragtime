import django.dispatch

# Custom signals for pipeline events (used by processing.py audit trail)
step_completed = django.dispatch.Signal()  # sends: event=StepCompletedEvent
step_failed = django.dispatch.Signal()     # sends: event=StepFailureEvent
