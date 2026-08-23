# Canal Holidays Base 62 snap exception design

## Purpose

Permit exactly one already-evidenced active seed to start against the approved
England graph without weakening the default boat-hire overlay distance rule.

The exact official Canal Holidays map coordinate for
`canal-holidays/base:62` is `52.2559783723458,-1.31417997134753`. Against
`/home/kurtt/towpath/pound/artifacts/england.pkl`, its nearest routing-eligible
edge is 250.968 m away. This is 0.968 m above the global 250 m cap.

## Contract

Add a constant identity-keyed exception mapping in `pound/web/boat_hire.py`:

```python
BOAT_HIRE_OVERLAY_DISTANCE_EXCEPTIONS_M = {
    "canal-holidays/base:62": 251.0,
}
```

`select_boat_hire_overlay` continues to use
`BOAT_HIRE_OVERLAY_DISTANCE_M = 250.0` for every seed other than the exact
mapping key. It uses the mapping value only for that exact `BoatHireSeed.identity`.
A distance of exactly 251.0 m is accepted for Base 62; a greater or non-finite
distance fails startup. The existing exception message uses the effective limit.

No CSV schema field, configurable override, source/provider wildcard, geometry
projection rewrite, or global threshold change is allowed.

## Evidence and validation

- Assert the exception mapping exactly equals
  `{"canal-holidays/base:62": 251.0}`.
- Add focused selector tests for Base 62 at 251.0 m acceptance and immediately
  above 251.0 m rejection.
- Retain the existing test proving a non-exception seed immediately above 250.0
  m fails, and add the same direct check for Canal Holidays sibling `base:61`.
- Add an exact note to the Base 62 canonical row and ignored queue handoff:
  this is a user-approved one-base 251 m startup exception for the current
  England artifact’s measured 250.968 m snap distance.
- Update the original overlay design to name this sole exception and link to
  `docs/completed/2026-08-23-canal-holidays-base-62-snap-exception-design.md`.
- Rerun the real-artifact startup/API gate. It must still fail for any other
  active seed farther than 250 m.

## Non-goals

- Do not add an exception for ABC Boat Hire or any other base.
- Do not alter the 250 m default, graph artifact, routing graph, overlay
  filtering model, or data-evidence requirement.
