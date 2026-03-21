# Session: Entity Types to DB — Planning

**Date:** 2026-03-14
**Session ID:** 66a82ba2-f434-43d3-ad62-6aa697eb6421

## Summary

Planned the migration of entity types from a static YAML file to a database-backed model with Django admin UI. Covered model design, migration strategy, deletion semantics, and admin UX.

## Conversation

### User

We want the extracted entities to be persisted in the database, be exposed in the Django admin UI. The current file "entity_types.yaml" should actually be used as an initial list of entities and used to prepopulate the database. In the README, the section "Extracted Entities" should be adapted. The table should be removed and the text should be rephrased to say that an initial list of extracted entities can be found in file "initial_entity_types.yaml" but more entities can be added via the Django admin UI. We need to think what to do when a user changes existing entity types and we have already processed episodes.

### Assistant

Let me explore the codebase to understand the current state of entities and related code.

Now let me design the implementation approach.

Let me read the critical files to verify details before finalizing the plan.

Now I have all the context I need. Let me write the plan.

This is the same task — the plan from the previous session is still relevant. It's comprehensive and ready. Let me exit plan mode so you can review and approve it.
