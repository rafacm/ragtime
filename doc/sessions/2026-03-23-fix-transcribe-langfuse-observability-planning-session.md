# Fix Transcription Langfuse Observability — Planning Session

**Date:** 2026-03-23

**Session ID:** unavailable

## Summary

User reported that the `transcribe_episode` step does not show the actual OpenAI transcription API request or response in Langfuse. Investigated the root cause, identified the fix, and implemented it in the same session.

### User

Checking in Langfuse, for the "transcribe_episode" step I cannot see the actual request sent to the OpenAI transcribe API nor the response received.

### Assistant

Investigated the codebase and found that `OpenAITranscriptionProvider.transcribe()` was missing the `@observe_provider` decorator and `set_observation_input`/`set_observation_output` calls that the LLM provider methods have. The Langfuse OpenAI wrapper (`langfuse.openai.OpenAI`) does not auto-instrument `audio.transcriptions.create()`, so without explicit logging nothing was captured.

Plan: add the decorator and logging calls, extending `set_observation_input()` to support a dict-style calling convention for non-chat providers. User agreed to proceed with implementation.
