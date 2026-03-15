# Update README Pipeline Section to Subsection Format

## Context

The README's "Processing Pipeline" section uses a numbered list with one-line descriptions per step. Several descriptions diverge from the actual implementation, and the format doesn't allow enough detail (e.g., Entity Types management details feel out of place in a list item). Converting to subsections per step fixes both issues: descriptions can be richer, entity type details stay inline, and each step gets a linkable anchor.

## Format

A `### Steps` heading is added under `## Processing Pipeline`. Each step becomes a `#### N. EMOJI Name (status: \`...\`)` heading followed by a short paragraph (1-3 sentences). The introductory text is replaced with a description of the signal-based dispatch mechanism.

## File to edit

**`README.md`** — replace the numbered list in the Processing Pipeline section with subsection format.

## New content for each step

### 1. Submit — `pending`
> User submits an episode page URL. Duplicate URLs are rejected.

*(Unchanged except "detected and the user is notified" → "rejected")*

### 2. Scrape — `scraping`
> Extract metadata (title, description, date, image, audio URL) and detect language via LLM-based structured extraction. Episodes with missing required fields (title or audio URL) are flagged for manual review (`needs_review`).

*(Added: audio URL, NEEDS_REVIEW path)*

### 3. Download — `downloading`
> Download the audio file and extract duration. Files ≤ 25 MB skip directly to Transcribe.

*(Removed misleading "Find"; added duration extraction and conditional skip)*

### 4. Resize — `resizing`
> If audio > 25 MB, downsample with ffmpeg to fit within the transcription API's file-size limit.

*(Added rationale for the 25 MB threshold)*

### 5. Transcribe — `transcribing`
> Whisper transcription with detected language, producing segment and word-level timestamps.

*(Minor rewording for clarity)*

### 6. Summarize — `summarizing`
> LLM-generated episode summary in the episode's detected language.

*(Added "in the episode's detected language")*

### 7. Chunk — `chunking`
> Split transcript into ~150-word chunks along Whisper segment boundaries, with 1-segment overlap.

*(Added chunking strategy details)*

### 8. Extract — `extracting`
> LLM-based entity extraction from the transcript. [Full entity type management details.]

*(Unchanged — the subsection format now accommodates this level of detail naturally)*

### 9. Resolve — `resolving`
> Match extracted entities against existing DB records using LLM-based fuzzy matching to prevent duplicates. Creates canonical entity records and links them to episodes.

*(Clarified what "resolution" means)*

### 10. Embed — `embedding`
> Generate multilingual embeddings for transcript chunks and store in ChromaDB.

*(Added "for transcript chunks")*

### 11. Ready — `ready`
> Episode fully processed and available for Scott to query.

*(Minor rewording)*

## Verification

1. Review the updated README to confirm each step description matches implementation
2. Verify markdown renders correctly (subsection headings, code formatting, links)
3. `uv run python manage.py check` — sanity check
