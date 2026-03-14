# Plan: Transcript Chunking (Step 8)

## Context

Step 10 in the README ("Chunk — Split transcript by Whisper segments") shared the `embedding` status with Step 11. Chunking needs its own `chunking` status and should be reordered to happen right after summarization and before entity extraction. This way, future refactoring of extraction/resolution to work per-chunk will give us natural entity-to-chunk mapping.

## New pipeline order

| Step | Description | Status |
|------|-------------|--------|
| 7. Summarize | LLM-generated summary | `summarizing` |
| **8. Chunk** | **Split transcript by Whisper segments** | **`chunking`** |
| 9. Extract | LLM entity extraction (full transcript) | `extracting` |
| 10. Resolve | LLM entity resolution | `resolving` |
| 11. Embed | Generate embeddings, store in ChromaDB | `embedding` |
| 12. Ready | Episode available for Scott | `ready` |

## Changes

1. Add `CHUNKING` status between `SUMMARIZING` and `EXTRACTING` in `Episode.Status` and `PIPELINE_STEPS`.
2. New `Chunk` model with episode FK, index, text, timestamps, segment range.
3. New `episodes/chunker.py` with `chunk_transcript()` (pure function) and `chunk_episode()` (pipeline task).
4. Summarizer advances to `CHUNKING` instead of `EXTRACTING`.
5. Signal handler dispatches chunker on `CHUNKING` status.
6. Update README and AGENTS.md pipeline descriptions.
7. Tests for both pure function and pipeline task.
