# Boat-hire review refinement design

- **Date:** 2026-08-04
- **Status:** Implementation complete
- **Scope:** Refine the one-time standalone Flask reviewer generated from the OSM catalog.

## Goal

Use the user's 33 completed review decisions (7 `vacation_hire`, 26
`not_vacation_hire`) to improve deterministic rank ordering, and remove catalog
records that are not near the existing routing network. Keep the tool local,
JSON-backed, explainable, and free of website fetching or learned ranking.

## Feedback-driven ranking

Keep candidate extraction broad: all named `marina` and `mooring` records remain
eligible, as do boat-related `landmark` records. Existing positive rules and the
mixed signals `cruisers`, `narrowboats`, and bare `charter` remain.
Marina records are still candidates but `marina` itself is not likelihood
evidence: the kind prior is zero and no text rule targets it.

Add only four contextual negative rule groups, each producing an auditable
reason when matched:

1. **Excursion wording:** `boat trips` or `canal trips`, using the existing
   medium negative contribution (`-6` rule weight).
2. **Other craft:** `kayak`, using a strong negative contribution (`-12` rule
   weight).
3. **Non-vacation boating:** `charter boat` or `launch hire`, using the medium
   negative contribution (`-6` rule weight). Bare `charter` remains available
   for cases such as the positively reviewed Wherry trust.
4. **Landmark-object wording:** `project`, `carving`, `memorial`, `bench`,
   `office`, `stone`, or `welcome post`, using a strong negative contribution
   (`-12` rule weight).

Rules are evaluated against the same searchable fields and normalized text as
existing ranking rules. Candidate extraction is not changed, so a low-scoring
record remains available if the user wants to inspect it. The rules are phrase
classes rather than OSM-identity overrides and are intentionally limited to
patterns present in the reviewed feedback.

## Existing-network pre-filter

The existing England routing artifact is the source of truth for network
membership. The generator loads a graph path supplied by a new `--graph`
argument, defaulting to `artifacts/england.pkl`, validates it with the
existing graph loader, and builds the existing `GraphSpatialIndex`.

A catalog geometry is retained when its metric distance to any
routing-eligible graph edge is at most **250 metres**. This means canals,
rivers, and fairways already represented by the routing graph count as the
existing network; the filter is not restricted to edges tagged only `canal`.
Records with no navigable edge or a distance above the threshold are omitted
from the generated review document.

The current catalog and graph produce approximately 694 active records. This is
a verification expectation for the current artifacts, not a hard-coded runtime
limit.

## Generation and persistence

`pound-boat-review generate` will:

1. Load the prior review JSON if it exists.
2. Load and validate the catalog and graph artifacts.
3. Fail rather than silently fall back to an unfiltered catalog if the graph
   cannot be loaded.
4. Apply the 250 m network filter.
5. Rank the retained records with the feedback-driven rules.
6. Preserve `decision` and `reviewed_at` for retained identities.
7. Atomically replace the output JSON.

Out-of-network records are removed from the active JSON, including any prior
decisions they carried. The review model and format remain unchanged; the
Flask UI continues to operate on the generated active set. README usage will
show the graph input and the generated output remains ignored.

## Testing and verification

Keep new tests deliberately small for this one-time tool:

- one table-driven ranking regression for the new penalties and preserved
  positive examples;
- one network-filter test covering nearby/far records and retained decision
  preservation;
- one real-artifact generation check for the current record count and stable
  output.

Run the existing full test suite and Ruff after implementation. Existing graph,
catalog, and atomic-store tests remain the validation boundary for those
components; no exhaustive new error matrix is required.

## Non-goals

- No website fetching, BM25, machine-learning classifier, or identity-specific
  feedback table.
- No new reviewer UI controls beyond the reduced generated candidate universe.
- No changes to the existing FastAPI/Svelte application.
