# Session: Merge Resize Step into Transcribe Step — Planning

**Date:** 2026-03-15
**Session ID:** ab6c3b6c-4c8f-4c92-ada2-1c5485876d45

## Summary

Planned the refactoring to merge the `resize` pipeline step into the `transcribe` step. The resize step exists solely to satisfy the Whisper API's 25MB file size limit — a transcription provider implementation detail, not a meaningful domain event. The plan absorbs resize logic into the transcriber, removes the `RESIZING` status, simplifies the downloader, and reduces the pipeline from 11 to 10 steps.

## Conversation

### User

Let's review the following steps: download, resize and transcribe. Somewhere in those steps we are also extracting the episode length. My gut feeling is that the "resize" step is actually too small of a step (implementation detail) of the Transcribe step. Propose a refactoring of these steps with pros/cons.

### Assistant

Let me also check the pipeline orchestration and status enum.

Now I have a clear picture. Here's the analysis:

---

## Current state

- **Download** (`downloader.py`): Downloads audio, extracts duration via `mutagen`, checks file size against 25MB Whisper limit. If small enough → skips resize and jumps to transcribing. If too large → sets status to resizing.
- **Resize** (`resizer.py`): Runs ffmpeg to downsample (mono, 22050Hz, 64kbps). Replaces the audio file. Transitions to transcribing.
- **Transcribe** (`transcriber.py`): Sends audio file to transcription provider, saves result.

Duration extraction already happens in `download`, not in resize or transcribe. Resize is conditionally skipped (via `skip_step`) when the file is already small enough.

---

## Option A: Merge resize into transcribe

Resize becomes an internal concern of the transcribe step — "prepare the audio and transcribe it."

| | |
|---|---|
| **Pros** | Resize exists solely to satisfy Whisper's 25MB limit — it's a transcription constraint, not a meaningful domain step. Reduces pipeline from 11 to 10 steps. Removes the conditional skip logic from download. Simplifies signals (no `RESIZING` status to dispatch on). Single file/module owns the full "audio → text" responsibility. |
| **Cons** | The transcribe step becomes longer-running and does two things (ffmpeg + API call). Harder to distinguish "failed during resize" vs "failed during transcription" in the status alone (though `error_message` still captures it). Slightly larger module. |

## Option B: Merge resize into download

Download becomes "fetch and normalize audio" — delivers a file that's guaranteed ready for transcription.

| | |
|---|---|
| **Pros** | Download already inspects the file size and makes the resize decision. Keeps transcribe clean and focused. |
| **Cons** | Download would do too much: network I/O + ffmpeg processing. These have very different failure modes and timeouts (60s vs 600s). Conceptually, downloading and audio processing are distinct concerns. |

## Option C: Keep all three steps as-is

| | |
|---|---|
| **Pros** | Each step has a single responsibility. Clear status tracking for monitoring/debugging. Resize can be retried independently. |
| **Cons** | Resize is never a meaningful domain event — it's a provider implementation detail (Whisper's size limit). The conditional skip adds complexity to download. 11 steps is a lot; this one doesn't carry its weight. If we switch to a provider without the 25MB limit, this step is dead code. |

---

## Recommendation

**Option A (merge resize into transcribe)** is the strongest choice. The resize exists only because of the transcription provider's constraint, so it belongs with transcription. The transcribe module would check file size, run ffmpeg if needed, then call the provider — all under a single `TRANSCRIBING` status. The `RESIZING` status and `skip_step` logic go away, and download becomes simpler.

Want me to plan this refactoring?

### User

Yes please.

### Assistant

Now let me design the plan.

Let me verify a couple of key details before finalizing.

Now let me write the plan file.

### User

[Request interrupted by user for tool use]
