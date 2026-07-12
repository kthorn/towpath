# OSM POI Ingest Design — External Review Convergence

## Parameters

- Artifact: `docs/plans/2026-07-12-osm-poi-ingest-design.md`
- Successful-round cap: 6
- Family rotation: GLM → Kimi → DeepSeek
- Convergence: two consecutive clean successful rounds from different families
- Blind packet: current design only; prior reviews and this ledger excluded

## Round 01 — GLM 5.2

- Raw output: `reviews/2026-07-12-osm-poi-ingest-design-round-01-glm-5-2.md`
- Finding 1: **substantive narrowed and accepted**. Section 5 now requires recursive member
  resolution with a cycle guard and defines completeness in terms of resolved role-bearing members,
  closed outer rings, and assigned inner rings. The review's suggested blanket requirement that all
  roles be present was narrowed because multipolygon completeness is governed by outer/inner ring
  members, while unsupported roles should be diagnosed rather than silently consumed.
- Finding 2: **rejected**. `pound/graph/build.py` constructs `nx.Graph`, not `MultiGraph`; the design
  also explicitly validates an undirected NetworkX graph. `(u, v)` uniquely identifies an edge.
- Finding 3: **rejected as duplicate/incorrect**. Section 6 already states the node STRtree stores
  `(lon, lat)`, requires the shared conversion helper at query boundaries, and explicitly requires a
  separate asymmetric node test. UID mappings permit haversine lookup from canonical graph attrs,
  so no geometry-coordinate reversal is required for each hit.
- Finding 4: **rejected as contrary to an explicit decision**. Sections 2 and 7 require versionless
  strict structural validation, field-level expected-shape details, and rebuild guidance.
- Finding 5: **rejected as non-blocking process advice**. Section 10 accurately records the baseline
  limitation and acceptance criterion 8 requires the implementation to establish a passing suite.
- Clean streak: 0 (accepted substantive edit)

## Failed attempt — Kimi K2.7 Code

- The initial full-packet invocation and the required smaller-packet retry returned no usable review
  text. Per the review protocol, neither attempt counts as a successful round.

## Round 02 — DeepSeek V4 Pro

- Raw output: `reviews/2026-07-12-osm-poi-ingest-design-round-02-deepseek-v4-pro.md`
- Result: `NO_FINDINGS`
- Disposition: clean successful round
- Clean streak: 1 (DeepSeek family)

## Round 03 — GLM 5.2

- Raw output: `reviews/2026-07-12-osm-poi-ingest-design-round-03-glm-5-2.md`
- Finding 1: **rejected as duplicate**. Section 3's allowlist explicitly excludes `mooring=no` at
  classification time. Artifact validation need not duplicate every classifier exclusion.
- Finding 2: **rejected as technically incorrect**. Pydantic supports fixed-length tuple fields and
  validates/coerces their shape. Neither the pickle contract nor frozen `GraphArtifact` requires POIs
  to be hashable.
- Finding 3: **rejected as technically incorrect**. Edge-tree tie-breaking and node-tree expanding
  queries are independent. Node results are mapped deterministically to UIDs and finally sorted by
  `(distance, uid)`, so STRtree return order cannot affect output.
- Finding 4: **substantive accepted**. Section 7 now specifies a 0.01 m EPSG:27700 Cartesian
  consistency tolerance and the exact comparison.
- Finding 5: **substantive narrowed and accepted**. Section 5 already says the STRtree contains
  navigable edges; Section 7 now additionally rejects an attachment outside the identical
  routing-eligible navigable subset.
- Finding 6: **rejected as duplicate**. Sections 2 and 3 explicitly prohibit parking and say parking
  tags are ignored. A future classifier regression is test coverage, not a second artifact schema.
- Clean streak: 0 (accepted substantive edits)

## Round 04 — DeepSeek V4 Flash

- Raw output: `reviews/2026-07-12-osm-poi-ingest-design-round-04-deepseek-v4-flash.md`
- Output note: malformed trailing `NO_FINDINGS` was ignored because concrete findings preceded it.
- Finding 1: **rejected**. `WaterwayFeatures` is an existing ingest IR model and “gains” unambiguously
  specifies extension. Writer/reader signature symmetry is not a contract requirement; Section 4
  deliberately makes construction writer-owned while readers receive the validated container.
- Finding 2: **rejected as incorrect**. Sections 4 and 7 both explicitly state the serialized exact
  lowercase keys `graph`, `pois`, and `metadata`; no `Graph` key appears in the design.
- Finding 3: **substantive narrowed and accepted**. Section 6 now pins the spherical bounding-box
  formula, pole behavior, normalization, antimeridian splitting, and angle units.
- Clean streak: 0 (accepted substantive edit)

## Failed attempts before Round 05

- GLM 5.2: the normal and smaller-packet calls produced no captured output.
- Kimi K2.7 Code: a fresh normal call and smaller-packet retry produced no captured output.
- These are not successful rounds. Because the helper cannot normally exit successfully without
  printing, the missing output may be an outer orchestration capture failure rather than an empty
  model completion.

## Round 05 — DeepSeek V4 Pro

- Raw output: `reviews/2026-07-12-osm-poi-ingest-design-round-05-deepseek-v4-pro.md`
- Result: `NO_FINDINGS`
- Disposition: clean successful round
- Clean streak: 1 (DeepSeek family)

## Round 06 — GLM 5.2

- Raw output: `reviews/2026-07-12-osm-poi-ingest-design-round-06-glm-5-2.md`
- Finding 1: **rejected as factually incorrect**. `PointOfInterest` already declares
  `name: str | None` in Section 4.
- Finding 2: **language-only narrowed**. Existing edge selection already uses graph UIDs and
  `(min_uid, max_uid)` ordering. Section 4 now states those semantics explicitly without renaming or
  changing the interface.
- Finding 3: **language-only narrowed**. Section 7 already requires transforming the stored point
  back to EPSG:27700, implying WGS84 storage. Section 4 now explicitly distinguishes edge projection
  from projected-CRS storage.
- Clean streak: 2 (DeepSeek then GLM; language-only edits do not reset it)

## Result

**CONVERGED** after six successful rounds. Rounds 05 and 06 were consecutive clean rounds from
different model families.

### Post-convergence product change

After convergence, the product scope removed toilet and shower ingestion, including preservation of
toilet-availability metadata on retained POIs. It also narrowed water-service ingestion from generic
`amenity=drinking_water` features to boat-specific `waterway=water_point` features. These substantive
changes were not part of the six-round review packet, so the convergence result above applies to the
preceding revision of the design.

## Review Tooling Observations

- The apparent empty responses were mostly long-running child processes hidden behind an outer
  command yield. The caller must retain and poll the returned process session rather than treating
  completion of the outer orchestration cell as completion of `review_external.py`.
- `review_external.py` should give `subprocess.run()` a per-model timeout, catch
  `subprocess.TimeoutExpired`, terminate the PI process group, and classify the attempt as a timeout
  before rotating. Its current unbounded wait can hang convergence indefinitely.
- Emit one machine-readable final record containing model, status (`ok`, `empty`, `timeout`, or
  `error`), and review text. This prevents transport/capture failures from being mislabeled as empty
  model completions.
- Enforce the requested finding cap after parsing. Several reviewers ignored “at most three,” and
  one emitted findings followed by `NO_FINDINGS`; contradictory sentinel output should be marked
  malformed rather than silently treated as clean.
