# Adaptive Audio Resize Tiers

## Problem

The audio resize step always applied the most aggressive ffmpeg settings (mono/22050Hz/64kbps) regardless of how much reduction was actually needed. A slightly oversized 26MB file got the same heavy compression as a 100MB file, unnecessarily degrading transcription quality.

## Changes

| File | Change |
|------|--------|
| `episodes/transcriber.py` | Added `RESIZE_TIERS` (5 tiers from 128k to 32k), `RESIZE_SAFETY_MARGIN`, `_select_resize_tier()` function; updated `_resize_if_needed` to use dynamic tier selection with info logging |
| `episodes/tests/test_transcribe.py` | Added `ResizeTierSelectionTests` (4 unit tests for tier selection logic) and 2 integration tests for duration-based and fallback tier selection |

## Key Parameters

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| `RESIZE_SAFETY_MARGIN` | 1.10 | 10% overhead accounts for MP3 container/framing beyond raw bitrate calculation |
| Tier 0 | mono/44100/128k | Gentlest reduction — for files just slightly over the limit |
| Tier 4 | mono/16000/32k | Most aggressive — last resort and fallback when duration is unknown |

## Verification

```bash
uv run python manage.py test episodes.tests.test_transcribe
```

All 18 tests pass. New tests verify:
- Short episode (600s) selects tier 0 (128k)
- Medium episode (3600s) selects tier 3 (48k)
- Very long episode (20000s) where no tier fits returns `None`
- `None` duration returns tier 4
- Integration: episode with `duration=600` gets 128k ffmpeg args
- Integration: episode without duration gets 32k ffmpeg args

## Files Modified

- `episodes/transcriber.py` — Added tier constants, `_select_resize_tier()`, updated `_resize_if_needed` to use adaptive tiers
- `episodes/tests/test_transcribe.py` — Added `ResizeTierSelectionTests` class and 2 new integration tests
