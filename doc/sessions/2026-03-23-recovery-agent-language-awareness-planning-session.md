# Session: Recovery Agent Language Awareness — Planning

**Date:** 2026-03-23

**Session ID:** 168626d0-1f48-419b-9a7f-d17b2257f7b0

## Summary

Planned the addition of language awareness, a translation tool, and visual analysis capabilities to the Pydantic AI recovery agent. Discussed unified vs separate system prompts, LLM-based vs hardcoded translation, and the visual fallback strategy for finding hidden audio elements.

## Conversation

### User

Let's revisit the Recovery with Pydantic AI logic. We need to make sure we pass the agent the information about in which language the episode is. We also need to pass a tool to the agent to translate text. We should tell the agent in the system prompt that the episode audio sometimes can be found under UI elements called "Information", "More information" or "Download". The agent can then use the text translation tool to translate these words we pass in the system prompt to the specific language the episode is in.

### Assistant

Explored the recovery agent codebase thoroughly: `episodes/agents/agent.py` (system prompts, agent builder), `episodes/agents/deps.py` (RecoveryDeps dataclass), `episodes/agents/tools.py` (7 browser tools), `episodes/recovery.py` (strategy chain), and `episodes/languages.py` (ISO 639-1 mapping). Found that the agent had no awareness of episode language and no translation capability.

Designed a plan with 6 changes: add `language` to RecoveryDeps, pass it from the episode, add `translate_text` tool using the scraping LLM provider, register the tool, update system prompts with language section, and update tests.

### User

For the translate_text tool, should we call the LLM provider (get_scraping_provider().structured_extract()) or would you prefer a simpler approach where we just include the pre-translated labels directly in the system prompt (e.g. hardcode translations of 'Information', 'More information', 'Download' for all supported languages in ISO_639_LANGUAGE_NAMES)?

### Assistant

Presented both options. Recommended LLM-based tool for flexibility — the agent can translate any text it encounters, not just predefined labels. User selected the LLM-based approach.

### User

I need some clarification, is there one agent that covers both the Recovery logic for both steps or are there separate agents?

### Assistant

Explained there is one agent that handles both steps. The same `_build_agent()` creates a single Pydantic AI agent with the same tools. The only difference is the system prompt — `_get_system_prompt()` picks either `SCRAPING_SYSTEM_PROMPT` or `DOWNLOADING_SYSTEM_PROMPT` based on `deps.step_name`.

### User

What would be the pros/cons of having one system prompt that captures both scenarios?

### Assistant

Analyzed trade-offs. Pros of unified: simpler code, agent gets full context, easier to maintain, tools identical either way. Cons: slightly longer prompt, could confuse agent (but context vars disambiguate), harder to tune one step without affecting the other. Recommended unified prompt.

### User

Yes, let's go for a single unified prompt.

### Assistant

Updated the plan with a single `RECOVERY_SYSTEM_PROMPT` covering both scenarios.

### User

If the download URL for the episode MP3 has been found in the scrape step, we should pass to the agent in the system prompt and tell the agent that the first approach to try is to first visit the episode URL page (this way all the website cookies are set) and then add the MP3 download URL in the location so this triggers the episode audio download.

### Assistant

Updated the `DOWNLOADING_SYSTEM_PROMPT` strategy to prioritize the cookie-then-download approach.

### User

Let's also update the system prompt to make sure the agent takes a screenshot of every single step it does.

### Assistant

Added "IMPORTANT: Take a screenshot after EVERY action you perform" to the unified prompt. Plan was approved.
