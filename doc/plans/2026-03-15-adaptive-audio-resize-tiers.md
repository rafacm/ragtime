# Adaptive Audio Resize Tiers

**Date:** 2026-03-15

## Context

The `_resize_if_needed` function in `episodes/transcriber.py` always applies the most aggressive ffmpeg settings (mono/22kHz/64kbps) when an audio file exceeds the 25MB Whisper API limit. A 26MB file of a 10-minute episode gets the same treatment as a 100MB file of a 3-hour episode, degrading transcription quality unnecessarily. Since we now have the episode `duration` (seconds, set during download), we can calculate the minimum reduction needed and pick the gentlest settings that fit.

## Approach

Define a tier list ordered from highest to lowest quality. For each tier, estimate the output size using `(bitrate / 8) * duration * 1.10` (10% safety margin for MP3 overhead). Pick the first tier whose estimate fits under the limit.

### Tiers

| Tier | Channels | Sample Rate | Bitrate | Use case |
|------|----------|-------------|---------|----------|
| 0    | mono     | 44100       | 128k    | Slightly oversized files |
| 1    | mono     | 32000       | 96k     | Moderate reduction |
| 2    | mono     | 22050       | 64k     | Previous hardcoded behavior |
| 3    | mono     | 16000       | 48k     | Long episodes |
| 4    | mono     | 16000       | 32k     | Last resort |

All tiers use mono — Whisper processes mono internally, so stereo doubles size for zero benefit.

### Fallback behavior

- `episode.duration is None` → use tier 4 (most aggressive, safe default)
- No tier fits the estimate → still attempt tier 4; the post-resize size check catches actual failures

## Changes

### `episodes/transcriber.py`

1. Add `RESIZE_TIERS` tuple constant and `RESIZE_SAFETY_MARGIN = 1.10` after `FFMPEG_TIMEOUT`
2. Add `_select_resize_tier(duration_seconds, max_size_bytes)` — pure function, returns tier index or `None`
3. Update `_resize_if_needed` to call `_select_resize_tier` and build ffmpeg args from the selected tier instead of hardcoded values
4. Add info-level logging of which tier was selected

### `episodes/tests/test_transcribe.py`

1. New `ResizeTierSelectionTests` class — pure unit tests for `_select_resize_tier`
2. New tests in `ResizeWithinTranscribeTests` for duration-based tier selection and `None` duration fallback
3. Existing tests pass unchanged — they don't set `duration`, so they fall back to tier 4
