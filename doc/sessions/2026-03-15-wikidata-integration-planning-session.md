# Session: Wikidata Integration — Planning

**Date:** 2026-03-15

**Session ID:** 338ce28e-0518-499d-9202-0e280fe151bd

## Summary

Planned the addition of Wikidata Q-ID integration to the Extract and Resolve pipeline steps, including model changes, Wikidata API client, resolver enhancements, management command, and configuration updates.

## Conversation

### User

Let's revisit the Extract step. Let's rename the section to "Extract entities" and let's explore options to implement the folowing requirements:
- we want to use wikidata and specifically wikidata IDs to identify canonical or resolved entities
- we want to make sure we cache the requests to the wikidata API
- the initial_entity_types.yaml will need to include the wikidata ID and we will need to update the model
- the entity name, description and examples should ideally be extracted from the wikidata information
- we probably want to have a manage command to lookup entities in wikidata and save them in the initial_entity_types.yaml file
- research if instead of an LLM we can use GLiNER (Generalist Lightweight NER) for Multilingual Named Entity Recognition (NER)
- reseatch if instead of an LLM we can use mReFinED to link the recognized entities into wikidata entity IDs

### Assistant

Let me explore the current state of the extract step and research the tools you mentioned.

Now let me read the README sections on Extract and Resolve, and the current entity types YAML.

Now let me launch a Plan agent with all the context gathered.

Let me verify a few details before finalizing the plan.

Now I have all the context needed. Let me write the plan.

Let me research alternative entity linking libraries and clarify the uniqueness question.

Good research. Let me clarify the uniqueness question and present the entity linking options.

**On the `wikidata_id` uniqueness question:** The issue is about what happens when two different `Entity` records end up with the same Wikidata Q-ID. For example, suppose during episode 1 processing, we create an Entity "Miles Davis" (artist) with `wikidata_id=Q93341`. Then during episode 2, a different text variant "Miles Dewey Davis" gets extracted and — due to a bug or race condition — gets created as a *second* Entity record also with `wikidata_id=Q93341`. Now you have two Entity rows representing the same real-world person. A partial unique constraint prevents this at the DB level: it says "no two Entity rows can share the same `wikidata_id`, unless it's empty." Entities without a Wikidata match (`wikidata_id=""`) are unaffected — there can be many of those.

Got it — the scope is narrower than I initially planned. Let me confirm my understanding:

1. **Keep LLM-based extraction and resolution** — no GLiNER, no new provider ABCs for now
2. **Add Wikidata IDs** to models (`EntityType.wikidata_id`, `Entity.wikidata_id`) and YAML
3. **LLM resolver** should now resolve entities to Wikidata Q-IDs (the LLM prompt includes Wikidata context to help match/assign Q-IDs)
4. **Management command** to look up entities in Wikidata and populate the YAML
5. **Cache** Wikidata API requests
6. **README** renames: "Extract" → "Extract entities", "Resolve" → "Resolve entities", with updated descriptions and code blocks for commands

What would you like to clarify about these questions? Happy to rephrase or provide more context.

### User

Since we are keepign the LLM-based approach we had now, is the uniqueness still an issue?

### Assistant

Good point — with the current LLM-based resolver, the uniqueness concern is minimal. The resolver already uses `get_or_create` on `(entity_type, name)` which prevents duplicates by name. Adding `wikidata_id` as an informational field (set during resolution) doesn't introduce a new race condition path since the LLM resolver creates entities by name first, then attaches the Q-ID.

So **no partial unique constraint needed** — we just add `wikidata_id` as a plain indexed field. If we later switch to a Wikidata-API-first resolution approach, we can add the constraint then.

Now for the remaining open question:

Good — Wikidata API lookup + LLM confirmation, with a shorter cache TTL. Let me update the plan with the revised scope.

Plan updated with the revised scope. Key changes from the original:
- **No GLiNER/mReFinED** — LLM-based extraction stays as-is
- **No new provider ABCs** — existing `LLMProvider` used for both extraction and resolution
- **Wikidata API + LLM confirmation** — resolver queries Wikidata for Q-ID candidates, passes them to the LLM to pick the best match
- **7-day cache TTL** (down from 30 days)
- **No uniqueness constraint** on `wikidata_id`

### User

[Request interrupted by user for tool use]
