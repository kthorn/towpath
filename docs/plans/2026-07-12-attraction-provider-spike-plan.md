# Attraction Provider Spike Execution Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Evaluate durable attraction datasets and live POI enrichment providers for canal-network exploration and route planning.

**Architecture:** Treat reusable open data as the offline catalog and commercial APIs as optional live enrichment. Gather evidence from official policies, reproducible OSM samples, and explicit cost calculations before recommending providers.

**Tech Stack:** Markdown, Overpass API or local OSM extracts, official provider documentation, small checked-in analysis fixtures containing only redistributable data.

### Task 1: Establish the evaluation matrix

**Files:**
- Create: `docs/spikes/2026-07-12-attraction-provider-evaluation.md`

1. Record the chosen attraction categories, 2 km canal corridor, sample-area criteria, and evaluation dimensions from issue #27.
2. Separate facts verified from official documentation, live-query observations, and unresolved assumptions.
3. Record the research date because provider terms and prices change.

### Task 2: Review provider policy and capability

**Files:**
- Modify: `docs/spikes/2026-07-12-attraction-provider-evaluation.md`

1. Review official Google Places API capabilities, field/SKU pricing, caching, attribution, map-display, and privacy requirements.
2. Review official Tripadvisor Content API access, search limits, pricing, caching, attribution, and migration notices.
3. Review OSM licensing, relevant tourism/historic tags, Overpass suitability, and bulk-extract feasibility.
4. Identify plausible official UK tourism and heritage datasets and verify licensing and access from primary sources.
5. Add direct links and an explicit confidence level for each conclusion.

### Task 3: Sample open-data attraction coverage

**Files:**
- Create: `docs/spikes/fixtures/attraction-provider-osm-sample.json`
- Modify: `docs/spikes/2026-07-12-attraction-provider-evaluation.md`

1. Select dense-city, canal-town, rural, tourism-heavy, and sparse canal samples.
2. Run reproducible OSM queries for the agreed visitor-attraction categories within 2 km of representative canal points or corridors.
3. Store only OSM-derived summary/sample data with query text, timestamp, and attribution.
4. Compare counts, tagging completeness, duplicate patterns, and representative quality.
5. Do not describe a point-radius sample as a complete route-corridor census.

### Task 4: Model commercial-enrichment cost and operations

**Files:**
- Modify: `docs/spikes/2026-07-12-attraction-provider-evaluation.md`

1. Define low, medium, and high monthly usage scenarios.
2. Calculate search/detail/photo costs from official current pricing and field tiers.
3. State every volume, cache, free-tier, and currency assumption.
4. Model quota exhaustion, missing credentials, provider outage, and identifier refresh behavior.
5. Mark live coverage/quality as unverified when credentials are unavailable.

### Task 5: Make the decision

**Files:**
- Modify: `docs/spikes/2026-07-12-attraction-provider-evaluation.md`

1. Recommend the durable baseline sources, live enrichment provider, and fallback behavior.
2. Give explicit go/no-go decisions for Google Places and Tripadvisor.
3. List blockers requiring credentials, legal review, or provider approval.
4. Map the decision to issues #23, #25, #26, #28, and #24.
5. Confirm no restricted commercial response data was committed.

### Task 6: Verify and publish the spike

1. Check every provider claim against a direct official source.
2. Validate the JSON fixture and recalculate cost examples independently.
3. Run Markdown/repository checks available in the project.
4. Review `git diff` for restricted content, secrets, and unrelated changes.
5. Commit only the plan, evaluation, and permitted OSM sample fixture.
6. Update issue #27 with the conclusion and verification evidence.
