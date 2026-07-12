# UI Settings Page Design

## Goal

Clean up the trip-planning interface by moving persistent boat dimensions to a
dedicated settings page and removing manual latitude/longitude endpoint entry.

## Interface

The header exposes two navigation choices: **Plan trip** and **Settings**. This
remains a small client-side application, so `App.svelte` switches views without
adding a routing dependency. The planner keeps place search, map selection,
candidate selection, schedule controls, the derelict-waterway option, route
submission, and route results.

The settings view owns four optional measurements in metres: boat length, beam,
draft, and height. Each supplied value must be finite and greater than zero.
Saved settings persist in browser `localStorage`; empty settings remain `null`.
Malformed or invalid stored data is ignored and replaced with empty settings.

## Data Flow

A small boat-settings store loads and validates persisted settings, exposes them
as a readable Svelte store, and saves validated updates. `App.svelte` creates one
store for its lifetime and passes it to the settings form and schedule form. On
route submission, the schedule form combines current days, hours per day, and
the derelict flag with the current persisted boat settings before calling the
existing trip store. The API contract is unchanged.

## Endpoint Cleanup

`EndpointPanel.svelte` retains place search, the selected place summary,
candidates, transfer warnings, and confirmation behavior. Latitude/longitude
state, validation, fields, and the “Use coordinates” action are deleted. Map
clicks remain a supported endpoint-selection method.

## Error Handling and Tests

The settings form displays validation errors and only persists valid values.
Storage reads and writes degrade safely if storage is unavailable. Tests cover
navigation, valid persistence, reload behavior, invalid persisted data,
automatic route-request inclusion, validation, and the absence of manual
coordinate controls. Existing place-search and map-click tests continue to
protect endpoint selection.
