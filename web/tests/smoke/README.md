# Live Google trip smoke test

This is an explicitly opt-in network test that can make billable Google Maps
Platform requests. The ordinary `npm test` suite never collects it, and
`npm run test:smoke` skips it unless `GOOGLE_MAPS_SMOKE=1`,
`VITE_GOOGLE_MAPS_API_KEY`, and `POUND_ARTIFACT_PATH` are all present.

## Prerequisites

- A Google Cloud project with billing and quotas configured. Enable **Maps
  JavaScript API**, **Places API**, and **Routes API**.
- A browser API key restricted by HTTP referrer to `http://127.0.0.1:4173/*`
  (and only the APIs above), plus a map ID belonging to that project.
- A full England Pound artifact. The Oxford development artifact cannot route
  this scenario. Build one as described in the repository README and keep it
  outside version control.
- Chromium for Playwright: `npx playwright install chromium`.

From `web/`, run:

```bash
GOOGLE_MAPS_SMOKE=1 \
VITE_GOOGLE_MAPS_API_KEY='restricted-browser-key' \
VITE_GOOGLE_MAP_ID='project-map-id' \
VITE_TRANSFER_MODE='WALK' \
POUND_ARTIFACT_PATH='pound/artifacts/england.pkl' \
npm run test:smoke
```

Although the command is launched from `web/`, Playwright starts Uvicorn with
the repository root (`..`) as its working directory. Therefore a relative
`POUND_ARTIFACT_PATH` is repository-root-relative; an absolute path also works.
The runner refuses to reuse existing FastAPI or Vite servers so the acceptance
test always exercises the supplied artifact and browser configuration.

`VITE_GOOGLE_MAP_ID` and `VITE_TRANSFER_MODE` are recommended explicit test
configuration, but are not opt-in gates; the application supplies defaults.

The runner starts FastAPI and Vite, so the `VITE_*` values flow into Vite's
browser build/dev transform. They are build-time public configuration, not
runtime secrets. The test chooses Bletchley Park and the searched rental base
“Black Prince Holidays, Stoke Hammond”, waits for ranked candidates, overrides
the destination recommendation, plans the canal route, and checks both land
overlays, the canal overlay, and the trip summary. Exact travel durations are
deliberately not asserted.

## Verification status

As of 2026-07-11, the default mocked frontend suite, Svelte/type check, build,
Playwright collection, and no-credentials skip path passed locally. The live
Google smoke test was **not run** because this environment had neither Google
credentials nor a full England artifact.
