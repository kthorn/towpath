# Local chat lab

Use the lab to try natural-language requests against the real Pound API and inspect
where the tool schemas or prompts need work. It runs separately from the map and is
not included in the production website image.

## Start

1. Start the current Pound backend with graph, catalog, and boat-hire data as described
   in the [development guide](development.md#map-prototype-local-development).
   Set `POUND_CLIMATE_PATH` and `POUND_CLIMATE_GRID_PATH` to the local climate artifacts
   to enable climate tools. Check `/api/health` before opening a chat. Use current Great Britain artifacts;
   artifacts from before the package split cannot be loaded by current main.
2. With Node 24.15+, install and build the agent package:

   ```bash
   cd packages/towpath-agent
   npm ci
   npm run build
   ```

3. Supply `OPENAI_API_KEY`, or retrieve the existing plaintext secret and start:

   ```bash
   (
     set +x
     OPENAI_API_KEY="$(aws secretsmanager get-secret-value \
       --profile default --region us-east-1 --secret-id towpath/openai-api-key \
       --query SecretString --output text --no-cli-pager)" || exit
     export OPENAI_API_KEY
     npm run chat:lab
   )
   ```

Open <http://127.0.0.1:8787>. Set `POUND_API_URL=http://127.0.0.1:8011` if your
backend uses another port. The backend URL must be a loopback HTTP origin.
Use `npm run chat:lab -- --port 8788` to choose another chat port.

Luna calls are billed to OpenAI; the key stays in the server process. The lab binds
only to loopback and is for one local developer. All tabs share its conversation.
Stop the process with Ctrl-C. It is not a hosted authentication/session solution.

## Try a conversation

- “Find hire bases for a seven-day canal trip visiting Bletchley Park at six cruising hours per day. Compare a couple of options.”
- “Show the daily plan and pubs along the first day of that option.”
- “What is the historical summer temperature near there?”
- Follow up with a changed cruising budget and inspect the recomputed routes.

Expand **Tool activity** to see model arguments, actual Pound API requests, summary
results and error codes. Route summaries retain Pound's distances, lock counts,
cruising time and warnings; bulky geometry is not sent to the model. No route is
adopted or written into the manual planner. Out-and-back results show at most five
alternatives and explicitly report when more were found.

**Stop** cancels the current run. **New conversation** clears both conversation
context and issued references. Context is kept only in process memory, up to 12
turns / 48 KB; the lab asks for a reset when full or expired. **Download session**
saves the visible conversation and traces as JSON for a bug report. It can contain
your prompts and place/route data; the key and provider reasoning are not included.

To experiment with prompting, create a local text file and restart with
`npm run chat:lab -- --prompt-file /path/to/prompt.txt` (up to 4000 bytes).
These instructions supplement the adapter's fixed safety instructions. Reset and
repeat the same request when comparing variants; no prompt changes are auto-saved.

## Exploration defaults

The agent investigates before asking questions. For nearby same-name records representing an
attraction, it chooses a plausible representative without merging their OSM identities. It
chooses a nearby named canal candidate and, if no start is given, searches published hire
bases that can reach that waypoint within the cruising budget. Walking access is not verified. Distinct destinations without a reasonable default still warrant one focused question.

Unspecified schedules default to **3 days at 6 cruising hours per day**. Explicit user choices
and follow-up changes take precedence, and boat dimensions remain unknown unless supplied.
The agent states material assumptions briefly, uses readable names instead of internal IDs,
and chains lookup, canal access, and route tools in one turn. Route parameters must use issued
canal candidate references; OSM attraction references cannot be used as route waypoints.

## Current scope

The agent has typed tools for every server-side planning API:

| Tools | API capability |
| --- | --- |
| `get_api_status` | Backend health and artifact revisions |
| `resolve_place`, `get_canal_access_options` | OSM place resolution and canal candidates |
| `plan_canal_route`, `plan_out_and_back`, `get_trip_option` | Route previews and exact replay of stored selections |
| `find_hire_bases`, `find_hire_trip_options` | Published hire bases and reachable out-and-back comparisons |
| `search_places`, `get_route_pois` | Nearby/viewport catalog searches and POIs along a route or day |
| `get_canal_network` | Budgeted canal network summary |
| `get_climate_locations`, `get_climate_location` | Historical climate location summaries and detail |
| `get_climate_grid`, `get_climate_cell` | Historical climate grid summaries and cell detail |

Hire trip discovery searches all published base anchors by canal connectivity, allowing at
most half the trip's cruising minutes in each direction between the base and attraction
waypoint. It does not apply a geographic radius first. It then previews complete trips from
up to six bases per call, retaining the required waypoint and supplied boat constraints.
Pagination is explicit. “Longest” means longest among the returned recommended previews,
not a global optimum over all bases and route branches. Provider names and source links come
from the published dataset; availability, prices, and current operator identity are not checked.

References are scoped to the conversation. Stored previews retain geometry for subsequent
day searches and exact replay, while model results omit bulky geometry and climate samples.
Pound owns route feasibility and rejects stale revisions. Unknown boat dimensions remain unknown.

The Google fallback, walking verification, and selection callback protocol is browser-owned:
its session/task credentials and verified results are not model-authored tool arguments.
Those integrations, ring search, and map route adoption remain outside the local lab.
The broader trip-discovery work (#78) and public conversation UI (#80) remain open.
Climate results describe historical summer conditions, not a weather forecast.

## Checks

`npm test` runs offline tests with fake models and API responses, including reference
mapping, conversation reset/expiry and loopback HTTP guards. No live calls run in CI.
The existing `npm run smoke:live` remains the minimal model/tool connectivity check.

## Initial live findings (2026-09-08)

The browser chat resolved Bletchley Park, fetched real canal candidates on a follow-up,
and called the out-and-back endpoint after explicit confirmation. Reset worked and no
browser JavaScript errors were reported. This verified model/tool/HTTP integration,
not route-selection quality.

The catalog returned four OSM entries named Bletchley Park with limited distinguishing
labels. A follow-up referring to the “first canal candidate” was also interpreted as selecting
the first place before canal alternatives had been presented. These cases are tracked in
[#94](https://github.com/kthorn/towpath/issues/94), which blocks the public chat UI (#80).

The initial artifact lacked the turnaround index and returned
`503 turnarounds_unavailable`. After rebuilding from the September 8 Great Britain
extract, the browser conversation successfully called the route tool and returned a
17.6 km, eight-lock out-and-back preview using a mapped winding hole. The rebuilt
index contains 392 winding holes and 1,199 junction turnarounds.

A combined request still stopped after place resolution despite saying it would fetch
canal candidates next. Explicit follow-ups fetched candidates and then planned the
route successfully. This is a prompting/control-flow finding to revisit while testing.

The route evidence also exposed a dimensional parser gap: a mapped `maxlength=22 m`
was retained in source tags but absent from normalized turning limits. This is tracked
in [#97](https://github.com/kthorn/towpath/issues/97), which blocks the public chat UI.
Boat-fit conclusions need that fix and another artifact rebuild.

## Default-first live check (2026-09-13)

“I want to do a canal trip that passes through Bletchley Park” completed with three tool calls
and no clarification: place lookup, canal candidates, then a successful out-and-back preview
using the 3-day/6-hour defaults. A follow-up requesting five days at four hours recomputed the
preview successfully. This checks the interaction and tool chain, not route-selection quality.
The check used real Luna calls and the local API; no live-model tests run automatically in CI.

## Expanded API live check (2026-09-14)

Real API checks exercised catalog search, the canal network, and climate location/grid summaries
and details. A Luna conversation created a 49.82 km, 32-lock out-and-back preview, then replayed
its exact daily plan and queried first-day pubs using the retained route geometry.

The seven-day Bletchley hire search found a published Leighton Buzzard base within the half-trip
budget, but the full turnaround planner rejected its itinerary. Reachability alone is therefore
reported separately from a complete trip preview; the lab does not invent a second base or claim
a route exists when the API rejects it. The rejection is tracked in
[#103](https://github.com/kthorn/towpath/issues/103), which blocks the public chat UI.
