# Task 3 Report: Stub `plan_route()` + Structural-Invariant Tests

## Summary

Implemented the frozen `plan_route(CanalConstraints) -> RouteResult` stub and the
structural-invariant test suite that unblocks the parallel Agent Core build.

## Changed Files

- `pound/plan.py` (new)
- `tests/test_plan_stub.py` (new)
- `progress.md` (updated)

## Commands Run

```bash
$ cd /home/kurtt/pound && uv run pytest tests/test_plan_stub.py -q
.......                                                                  [100%]
7 passed in 0.06s
exit code: 0
```

```bash
$ cd /home/kurtt/pound && uv run pytest -q
...........                                                              [100%]
11 passed in 0.08s
exit code: 0
```

```bash
$ cd /home/kurtt/pound && uv run ruff check .
All checks passed!
exit code: 0
```

```bash
$ cd /home/kurtt/pound && git commit -m "feat(plan): stub plan_route() returning hardcoded Oxford leg + structural tests"
[main a42f1ef] feat(plan): stub plan_route() returning hardcoded Oxford leg + structural tests
 2 files changed, 129 insertions(+)
exit code: 0
```

## Surprises / Deviations from Brief

- The exact test code in the brief used `l` as a loop variable and `zip()`
  without `strict=`. Running `uv run ruff check .` flagged these (E741, B905).
  They were minimally adjusted to `leg` and `strict=False` to keep `ruff`
  clean. Functionally identical.

## Residual Risks

- The stub ignores all routing logic; it only satisfies structural invariants.
  Real engine must replace the hardcoded leg, cost constants, and amenities.
- `pyproject.toml` had an unrelated unstaged formatting diff that was not part
  of this task and was left untouched.
- `DayPlan.cruising_minutes` is hardcoded to 131; future day-splitting logic
  must recompute this from leg sums.

## Decisions Needing Approval

- None. All changes are within the brief's scope.
