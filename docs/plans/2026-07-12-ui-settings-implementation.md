# UI Settings Page Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a persistent boat-dimensions settings page and remove manual coordinate endpoint entry.

**Architecture:** Introduce a focused Svelte store backed by `localStorage`, with strict parsing at the storage boundary. Split the existing combined constraints form into a settings form for boat dimensions and a planner form for schedule submission, joined in `App.svelte` through the shared settings store.

**Tech Stack:** Svelte 5, TypeScript, Svelte stores, browser `localStorage`, Vitest, Testing Library.

### Task 1: Persistent boat settings store

**Files:**

- Create: `web/src/lib/stores/boat-settings.ts`
- Create: `web/src/lib/stores/boat-settings.test.ts`

1. Write tests for empty defaults, valid saved values, malformed/invalid stored values, and saving updates.
2. Run `npm test -- --run src/lib/stores/boat-settings.test.ts` and verify the missing-module failure.
3. Implement `BoatSettings`, `BoatSettingsStore`, and `createBoatSettingsStore(storage?)` with nullable dimensions and safe storage access.
4. Re-run the narrow test and verify it passes.

### Task 2: Settings view and navigation

**Files:**

- Create: `web/src/component/BoatSettings.svelte`
- Modify: `web/src/App.svelte`
- Modify: `web/src/app.css`
- Test: `web/src/component/App.test.ts`

1. Add failing interaction tests for Plan trip/Settings navigation, saving dimensions, validation, and restoring persisted values.
2. Run the narrow component tests and confirm the expected missing navigation/settings failures.
3. Implement header navigation, conditional views, and the settings form with positive-number validation.
4. Re-run the component tests and verify they pass.

### Task 3: Planner integration and coordinate removal

**Files:**

- Modify: `web/src/component/BoatConstraints.svelte`
- Modify: `web/src/component/EndpointPanel.svelte`
- Modify: `web/src/App.svelte`
- Test: `web/src/component/App.test.ts`

1. Replace the controlled-constraints test with a failing test proving saved boat settings are included in route submissions, and add a failing assertion that manual coordinate controls are absent.
2. Run the narrow tests and confirm failures for the old combined form/coordinate UI.
3. Reduce `BoatConstraints.svelte` to schedule controls, merge in the settings values on submit, and delete coordinate-entry and derelict-option state and markup.
4. Remove obsolete coordinate-fallback tests and keep place-search/map-click coverage.
5. Re-run the component test file and verify it passes.

### Task 4: Verification

**Files:**

- Modify if needed: `web/src/app.css`

1. Run `npm test -- --run` and verify all web tests pass.
2. Run `npm run check` if defined and fix any type/Svelte diagnostics.
3. Run `npm run build` and verify the production bundle succeeds.
4. Review `git diff --check`, `git status --short`, and the final diff for unintended changes.
