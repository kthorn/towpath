# Open-Issue Priority Order

> **Snapshot:** 2026-08-23
> **Assumption:** optimize next for a reliable shared trip planner, not a discovery-only demo. Issue labels are treated as stale.

## Removed from the queue

- **#9 — Select cloud platform and productionize map deployment:** merged. Close the issue if its remaining acceptance criteria are satisfied; open a smaller deployment-hardening issue later only when catalog-backed or wider public use requires it.

## Resolve or initiate now, but do not start feature implementation

- **#28 — Compliant on-demand attraction enrichment:** resolve the conflict between the older Google-enrichment recommendation and the later repository policy that blocks Places enrichment pending legal/support review. Keep OSM-only behavior as the baseline. Even if approved, this waits for #26's user-triggered detail surface.
- **#15 and #24:** split out one shared, deterministic route-leg/day attachment primitive. Do not implement it independently in each issue. The remaining boat-rental-catalog portion of #15 can follow the shared slice.
- **#21 — Saved rental bases, trips, sharing, and accounts:** split saved trips/bases from accounts/sharing; they have materially different storage, privacy, and deployment needs.
- **#10 — IWA advisory** and **#19 — CanalPlanAC oracle:** request written reuse permission now. Neither wait should block the core roadmap; do not implement or collect data without it.

## Main implementation order

1. **#12 — Model private, permissive, and permit-only waterway access**

   Make route eligibility operationally and legally meaningful while preserving uncertainty as warnings.

2. **#16 — Apply movable-bridge and tunnel constraints in route cost**

   The graph already retains relevant flags; path selection and totals need to use them consistently.

3. **#6 — Rank canal meeting-point candidates using OSM access evidence**

   Replace nearest-coordinate-plus-spacing selection with evidence-backed ranking, retaining deterministic geometric fallback.

4. **#15 — Complete the shared route-leg/day attachment slice**

   Use the existing catalog rather than creating another POI system. This is the common primitive for practical day stops and route-relevant attractions.

5. **#17 — Add CRT asset and amenity enrichment to artifact builds**

   First pass a source-license, freshness, and coverage gate—especially for moorings and winding holes. Ingest only evidence that proves current and useful.

6. **#8 — Make day plans prefer practical mooring and turning points**

   Replace greedy graph-node day boundaries after access, mooring/winding, and route-anchor evidence are available.

7. **#18 — Implement ring and round-trip canal routing**

   Deliver the bounded named-ring/explicit-via version; defer general budget-constrained loop search.

8. **#24 — Show visitor attractions along planned canal routes**

   Use selected-route proximity and the shared leg/day attachment; fix branch/loop association before presenting attractions as route-relevant.

9. **#11 — Compare transfer modes and add taxi/fare planning**

   Add comparison and explainable unavailable states, but keep booking and side effects out of scope.

10. **#14 — Add CAMRA outbound pub and guide links**

    A small, reversible enhancement once route/pub context is stable. Preserve the no-fetch/no-scrape boundary.

11. **#25 — Add a progressive whole-canal-network explorer**

    First build Explore navigation and a stable URL, then measure national/regional payload and render behavior before choosing chunks, tiles, or another delivery format.

12. **#26 — Add attraction discovery, clustering, filters, and detail cards**

    Build on #25's explorer shell, retaining the accessible synchronized list/map, planner handoff, and Back/Forward behavior.

13. **#21 — Deliver saved trips and rental bases**

    Do this as the first split of #21; defer public sharing and accounts until real use establishes their requirements.

14. **#20 — Define NanoClaw agent tools and natural-language trip planning**

    Wait until manual routing, persistence boundaries, and the Pound/Labyrinth ownership seam are stable. An agent should not automate unresolved route-access or day-stop behavior.

## Conditional / waiting work

- **#10:** if IWA permission is granted, implement it as a build-time advisory after the core route-correctness work; otherwise document the decision and close it.
- **#19:** if CanalPlanAC permission is granted, implement it as a disabled-by-default validation oracle after the core planner is credible; otherwise document the decision and close it.
- **#28:** only enter the implementation queue after explicit compliance approval and #26.

## Discovery-first alternative

If the immediate goal changes to a public discovery demo rather than reliable trip planning, move **#25** and **#26** immediately after **#16**. Keep **#28** blocked regardless.
