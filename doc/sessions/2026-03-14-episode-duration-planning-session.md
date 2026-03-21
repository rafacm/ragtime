# Session: Episode Duration — Planning

**Date:** 2026-03-14

**Session ID:** 7f339a4a-fc60-429d-a3a5-5a6acda9935c

## Summary

Planned the addition of an episode duration field extracted from MP3 metadata and reordering of admin list columns. Explored the codebase to understand the Episode model, download pipeline, and admin configuration, then produced a 5-step implementation plan.

## Conversation

### User

In the Episodes list in the Django admin interface, we want the first column to be "Title", then the URL, then the language, then the episode lenght in hours minutes and seconds, then the status, and finally the created and last updated columns. The episode length should be added to the Episode model and after the episode is downloaded the information about the length should be extracted from the downloaded MP3 file.

[Request interrupted by user]

In the Episodes list in the Django admin interface, we want the first column to be "Title", then the URL, then the language, then the episode lenght in hours minutes and seconds, then the status, and finally the created and last updated columns. The episode length should be added to the Episode model and after the episode is downloaded the information about the length should be extracted from the downloaded MP3 file.

### Assistant

I have all the information I need. Let me write the plan.
