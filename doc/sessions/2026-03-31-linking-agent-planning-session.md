# Linking Agent — Planning Session

**Date:** 2026-03-31

**Session ID:** unavailable — session UUID could not be recovered from Claude Code logs

## Summary

Planned the decoupling of Wikidata entity linking from the pipeline resolve step into a background linking agent. Explored alternative knowledge bases (YAGO, MusicBrainz, DBpedia, Jazz Ontology), analyzed the current Wikidata integration, and designed an agent-based architecture following the existing recovery agent pattern.

### User

In the step in the pipeline where we resolve the entities to wikidata IDs, I am seeing timeouts from the Wikidata API. Since the Wikidata database is quite large I do not want to download it to use it locally. Are there smaller datasets available that we could use instead? Or Jazz-focused datasets? What about YAGO3? Alternatively, could we have an agent that takes care in the background of the linking part, i.e. linking resolved entities with Wikidata IDs but as an after process?

### Assistant

Launched two parallel exploration agents: one to understand the current entity resolution code (resolver.py, wikidata.py, models, signals), and another to research alternative knowledge bases (YAGO3/4, MusicBrainz, Jazz Ontology, DBpedia).

Key findings from research:
- **YAGO3/4**: Not smaller than Wikidata (YAGO4 has 64M entities, built FROM Wikidata). Has SPARQL endpoint but wouldn't solve the timeout problem.
- **MusicBrainz**: Domain-specific music database with REST API. Good jazz coverage for artists, albums, labels. Best alternative but a separate feature.
- **Jazz Ontology**: Academic RDF datasets from Jazz Encyclopedia. Specialized but limited scope, unclear API availability.
- **DBpedia**: Similar scale to Wikidata, extracted from Wikipedia infoboxes. Not smaller.

Key insight: The codebase already handles missing `wikidata_id` gracefully — entities are created without it, and the resolver falls back to name-based matching. The `wikidata_id` is NOT used in embedding or RAG queries. This makes decoupling into a background process the cleanest solution.

Launched a Plan agent to design the implementation. Initial plan proposed a simple background task triggered after resolve.

### User

Is this linking step then a new pipeline step? Will it be shown in the ProcessingRun information? What about implementing the linking logic as an agent? Similar to the recovery agent we already have?

### Assistant

Explored the ProcessingRun/ProcessingStep models, recovery agent architecture (recovery.py, agents/agent.py, agents/tools.py, agents/deps.py, agents/resume.py), and admin display patterns. Found the recovery agent uses Pydantic AI with Playwright tools, triggered by `step_failed` signal, tracked via RecoveryAttempt model, with admin retry actions.

Design decisions:
- **Not a pipeline step**: Adding to PIPELINE_STEPS would re-introduce blocking. The pipeline completes without waiting for Wikidata.
- **No ProcessingRun entry**: Visibility comes from `linking_status` field on Entity + admin filters instead.
- **Agent pattern**: Follows recovery agent architecture — triggered by signal, runs async via Django Q2, uses Pydantic AI with tools, retryable from admin.

Updated plan to use the agent pattern with a comparison table showing the parallel architecture between recovery agent and linking agent.

### User

We need to make sure we update the root README and the doc/README with the changes.

### Assistant

Added documentation step to the plan covering README.md (pipeline table update, linking agent note) and doc/README.md (rewritten resolve step, new Linking Agent section). Updated the critical files table accordingly. Plan approved.
