# Session: Adaptive Audio Resize Tiers — Planning

**Date:** 2026-03-15
**Session ID:** f750c0ab-7ee3-4e9b-81ff-9bebac97db25

## Summary

Planned adaptive tier selection for the audio resize step, so that slightly oversized files get gentler compression instead of always applying the most aggressive ffmpeg settings.

## Conversation

### User

What are the current settings we use to reduce the mp3 file size?

### Assistant

The current ffmpeg resize settings (in `episodes/transcriber.py:38-48`):

- **`-ac 1`** — mono (1 channel)
- **`-ar 22050`** — 22,050 Hz sample rate
- **`-b:a 64k`** — 64 kbps bitrate

Resizing is triggered when the audio file exceeds `RAGTIME_MAX_AUDIO_SIZE` (default **25 MB**). The ffmpeg process has a **5-minute timeout**. If the file still exceeds the limit after resizing, it raises an error.

### User

Since we know the length of the podcast, what about having resize settings depending on the podcast length and file size? We should find a balance between being too aggresive with file reduction so that we do not negatively impact the transcription step.

### Assistant

Good — `duration` is available in seconds. Let me think through the approach with you.

The key insight: right now we always apply the most aggressive settings (mono/22kHz/64kbps) regardless of whether a gentler reduction would suffice. For a 30MB file of a 1-hour podcast, we're crushing quality unnecessarily — a small bitrate reduction would get it under 25MB. But for a 100MB file of a 3-hour podcast, we genuinely need aggressive settings.

**Proposed approach: calculate the minimum bitrate needed to fit under the limit, then pick the least aggressive preset that achieves it.**

For example, tiered presets (from least to most aggressive):

| Tier | Channels | Sample Rate | Bitrate | Rough quality |
|------|----------|-------------|---------|---------------|
| 1    | stereo   | 44100       | 128k    | Near-original |
| 2    | mono     | 44100       | 96k     | Good for speech |
| 3    | mono     | 22050       | 64k     | Current default |
| 4    | mono     | 16000       | 48k     | Last resort |

The logic would be:
1. Compute `target_bitrate = (max_size_bits * 0.95) / duration_seconds` (5% safety margin for container overhead)
2. Walk the tiers from least aggressive to most, pick the first one whose bitrate fits
3. If duration is unknown, fall back to the current fixed settings (tier 3)

This way a 30MB/60min episode only drops to tier 1 or 2, while a 100MB/180min episode gets tier 3 or 4.

**Considerations:**
- Transcription models (Whisper) work fine with mono 16kHz — speech recognition doesn't need stereo or high sample rates. So even tier 4 shouldn't hurt transcription quality meaningfully.
- The real transcription risk is very low bitrate (below ~32kbps), which we'd avoid.
- We still keep the post-resize size check as a safety net.

Does this tiered approach sound right to you, or would you prefer a different strategy (e.g., computing exact target bitrate and passing it directly to ffmpeg without presets)?

### User

Create a plan for this

### Assistant

Now let me design the implementation.

Let me verify a couple of details in the existing tests before finalizing.

Good — existing tests don't set `duration`, so they'll naturally fall back to the most aggressive tier and continue passing. Now let me write the final plan.

### User

[Request interrupted by user for tool use]
