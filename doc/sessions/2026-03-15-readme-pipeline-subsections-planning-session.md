# Session: README Pipeline Subsections — Planning

**Date:** 2026-03-15

**Session ID:** a25c155f-6751-4a1f-b711-5ad9f84f435e

## Summary

Reviewed every pipeline step description in the README against the actual implementation, identified 7 mismatches and a format limitation, and produced a plan to convert the numbered list to `###` subsections with corrected descriptions.

## Conversation

### User

Switch to main branch and pull remote changes

### Assistant

Done. Now on `main`, up to date with remote.

### User

Review the "Processing Pipeline" section in the README. For each of the steps, review the current implementation and verify if the summary description for the step corresponds to the current implementaton. Suggest new steps that could be added or steps that could be merged.

### Assistant

Now let me explore the pipeline implementation and related code in parallel.

Now let me read a couple of key files to verify specific details before writing the plan.

Now I have a thorough understanding. Let me write the plan.

Here's a summary of findings:

**Description mismatches (6 steps need updates):**
- **Submit** — "notified" is vague; duplicates are actually rejected via form validation
- **Scrape** — omits audio URL extraction (critical!) and the `NEEDS_REVIEW` fallback path
- **Download** — says "find and download" but finding happens in Scrape; also omits duration extraction and the conditional Resize skip
- **Chunk** — too vague; doesn't mention the ~150-word target or 1-segment overlap strategy
- **Extract** — description is disproportionately detailed compared to other steps (entity type management details could move to a separate section)
- **Resolve** — could be clearer about what "resolution" means

**Implementation gaps:**
- **Embed** and **Ready** are documented but **not implemented** — pipeline stalls after Resolve
- **`NEEDS_REVIEW`** is a real pipeline state (after failed scrape) but isn't mentioned in the README at all

**Merge suggestions:** None — each step is a distinct async task with per-step status tracking; merging would reduce observability.

**New step suggestions:** A **Validate** step (check audio integrity before processing) and a **Notify** step (alert users when processing completes).

This is a research/review task — no code changes to implement. The plan file contains the complete analysis. Let me ask if you have any questions or want me to dig deeper into anything.

This is the same task — my review is complete. Let me update the plan to be an implementation plan for applying the suggested README changes.

Good idea — a format like subsections per step (with `###` headings) would allow richer descriptions, keep entity type details in-place, and support future links to implementation files. Let me draft a couple of options.

### User

[Request interrupted by user for tool use]
