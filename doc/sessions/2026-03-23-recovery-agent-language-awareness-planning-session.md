# Session: Recovery Agent Language Awareness — Planning

**Date:** 2026-03-23

**Session ID:** unavailable

## Summary

Planned the addition of language awareness, a translation tool, and visual analysis capabilities to the Pydantic AI recovery agent. Discussed unified vs separate system prompts, LLM-based vs hardcoded translation, and the visual fallback strategy for finding hidden audio elements.

## Conversation

### User

Let's revisit the Recovery with Pydantic AI logic. We need to make sure we pass the agent the information about in which language the episode is. We also need to pass a tool to the agent to translate text. We should tell the agent in the system prompt that the episode audio sometimes can be found under UI elements called "Information", "More information" or "Download". The agent can then use the text translation tool to translate these words we pass in the system prompt to the specific language the episode is in.

### Assistant

Explored the recovery agent codebase thoroughly: `episodes/agents/agent.py` (system prompts, agent builder), `episodes/agents/deps.py` (RecoveryDeps dataclass), `episodes/agents/tools.py` (7 browser tools), `episodes/recovery.py` (strategy chain), and `episodes/languages.py` (ISO 639-1 mapping). Found that the agent had no awareness of episode language and no translation capability.

Designed a plan with 6 changes: add `language` to RecoveryDeps, pass it from the episode, add `translate_text` tool using the scraping LLM provider, register the tool, update system prompts with language section, and update tests.

### User

Asked whether to use LLM-based translation tool or hardcoded translations.

### Assistant

Recommended LLM-based tool for flexibility — the agent can translate any text it encounters, not just predefined labels. User agreed.

### User

Clarified that there is one agent covering both recovery scenarios (scraping and downloading), not separate agents. Asked about pros/cons of unifying into a single system prompt.

### Assistant

Analyzed trade-offs. Recommended unifying: the two scenarios are closely related, toolset is identical, context variables already distinguish the situation. The current split added maintenance overhead with little benefit.

### User

Agreed to unify. Also requested the agent take a screenshot after every action, and that the download strategy should visit the episode page first (for cookies) before attempting the audio URL.

### Assistant

Updated the plan to include: unified prompt, cookie-first strategy, mandatory screenshots, and conditional language section. Plan was approved.
