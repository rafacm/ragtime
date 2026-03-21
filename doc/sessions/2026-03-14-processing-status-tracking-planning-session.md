# Session: Processing Status Tracking — Planning

**Date:** 2026-03-14
**Session ID:** ebcf8a85-6dd7-41a6-b9e6-707e1ea8cbbe

## Summary

Planned per-step processing status tracking with ProcessingRun and ProcessingStep models, enabling retry from the exact failure point instead of reprocessing from scratch. Designed a unified admin reprocess action with an intermediate step-selection page.

## Conversation

### User

How do we currently the processing status for an episode?

### Assistant

The `Episode` model has a single `status` CharField (line 20) using a `TextChoices` enum (lines 5-17) that tracks where the episode is in the pipeline:

**`PENDING`** → **`SCRAPING`** → **`NEEDS_REVIEW`** → **`DOWNLOADING`** → **`RESIZING`** → **`TRANSCRIBING`** → **`SUMMARIZING`** → **`EXTRACTING`** → **`RESOLVING`** → **`EMBEDDING`** → **`READY`**

With **`FAILED`** as a terminal error state, paired with the `error_message` field (line 51) for details.

It's a single linear status field — there's no per-step tracking, no timestamps for when each stage started/finished, and no retry count or history.

### User

This is too simple. The problem is that sometimes we want to re-process the last failed step for an episode and not all the steps starting from the begining. Since are using LLMs for most of the steps, this is incurring additional costs that do not add any value. Therefore we need to implement a better processing status tracking. We want to:
- track each of the steps in the pipeline, when it started, finished, and whether the it was suscessful or there was an error. If there was an errror we want to store the details
- from the Django admin UI we want to be able to trigger re-processing from the last failed step or full reprocessing from the begining.
- there can be several reprocessing runs for the same episode, if for a given processing run a step was skipped, we want to know this
- we want to expose this information in the Django admin UI

### Assistant

Now let me read the key files directly and then design the implementation.

Now let me design the implementation.

Let me read one step function to verify the pattern before finalizing.

Good — I've confirmed the patterns. Now I have one question before finalizing the plan.

Now let me write the final plan.
