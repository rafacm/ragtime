# Session: Step 9 — Resolve Entities — Planning

**Date:** 2026-03-13
**Session ID:** 09ef4d53-d8b5-48a3-8fb8-bd017e1499ee

## Summary

Planned Step 9 (Resolve Entities): LLM-based entity resolution against existing database records using fuzzy matching, canonical Entity model with cross-language support, and idempotent reprocessing via EntityMention linking.

## Conversation

### User

Let's plan the implementation of Step 9 - Resolve LLM-based entity resolution against existing entities in DB.
In the files starting with `extracted-entities-*.json` there are examples of the JSON we get from the LLM after entity extraction.
Besides the entities themselves, we also want to persist the context so that we can use it later. We also want to persist the relationship to the given episode. We want to be able to see the entities in the Django admin interface and also see from which episodes they were extracted. We want to model entities in a generic way so that we can add more entities in the future.

### Assistant

I'll explore the codebase and the entity JSON files to understand the current state and what's needed.

Now let me read the key files to understand the current models, entity types, and the existing patterns.

Now let me look at the provider base class and an existing feature plan for reference.

Now I have a thorough understanding. Let me design the implementation plan.

Let me check one more file — the configure helpers — to understand the subsystem pattern.

Good, I now have all the context needed. Before writing the final plan, I have a few design questions.

Good point about multilingual contexts. Let me clarify the naming aspect given this.

### User

Show me the questions again.

### Assistant

Got it. So to summarize the decisions:

1. **Own provider**: `RAGTIME_RESOLUTION_*` env vars
2. **LLM picks best canonical name**: The LLM resolves to the most commonly recognized form (e.g., "Saxophone" over "Saxophon", proper names stay as-is). Context strings remain in their original episode language.

Let me write the final plan.

Good catch. This means we also need to rename the existing `DEDUPLICATING` status in the Episode model to `RESOLVING`, and update all references to it. Let me update the plan.

Now let me update the plan to rename `DEDUPLICATING` → `RESOLVING` and include this as a prerequisite change.

I'll wait for your feedback on the plan.
