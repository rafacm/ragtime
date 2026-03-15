# Session: Adaptive Audio Resize Tiers — Planning

**Session ID:** f750c0ab-7ee3-4e9b-81ff-9bebac97db25
**Date:** 2026-03-15

## Summary

Planned adaptive tier selection for the audio resize step, so that slightly oversized files get gentler compression instead of always applying the most aggressive ffmpeg settings.

## Conversation

### User
Requested planning for adaptive audio resize tiers — the current `_resize_if_needed` always applies mono/22050Hz/64kbps regardless of how much reduction is needed.

### Assistant
Explored `episodes/transcriber.py` to understand the current resize logic. Noted that `episode.duration` (added in the episode-duration feature) is available and can be used to estimate the minimum bitrate needed. Considered approaches:

- **Rejected:** Binary search on ffmpeg settings — too slow (multiple ffmpeg invocations).
- **Rejected:** Single formula for bitrate — doesn't account for discrete sample rate/channel options.
- **Chosen:** Tiered approach — 5 preset quality tiers, pick the first whose estimated output fits under the size limit.

Designed the tier table (128k down to 32k), all mono since Whisper processes mono internally. Added a 10% safety margin for MP3 container overhead. Defined fallback behavior: `None` duration → most aggressive tier, no tier fits → attempt most aggressive anyway.

### User
Approved the plan.
