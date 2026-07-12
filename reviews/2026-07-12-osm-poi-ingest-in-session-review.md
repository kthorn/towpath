# OSM POI Ingest — In-Session Readiness Review

## Scope

Reviewed the complete current design and implementation plan bidirectionally against the existing
repository contracts. This single in-session review replaces the proposed post-scope-change external
convergence review by user direction.

## Findings and dispositions

1. **Important — inconsistent exclusion diagnostics.** Design section 3 said parking was ignored,
   acceptance criterion 2 said it was reported, and implementation Task 2 emitted
   `excluded_parking`. Resolved by making parking and the explicitly ignored amenities silent
   exclusions everywhere; unknown allowlist values remain reported.
2. **Important — stale review gate.** The implementation handoff still required external review.
   Resolved by recording this in-session review as the replacement gate.
3. **Important — non-executable verification steps.** Multiple tasks said only “run focused tests and
   Ruff.” Resolved with exact test and Ruff commands for Tasks 2 through 10.
4. **Important — bulk malformed-area assertions were weaker than the design.** Task 4 now requires
   deterministic diagnostics and prohibits center/partial-polygon fallbacks.

## Assessment

No unresolved material blocker remains in the design-to-plan mapping. Implementation may proceed
task by task using the plan's required TDD, review checkpoints, and final verification workflow.
