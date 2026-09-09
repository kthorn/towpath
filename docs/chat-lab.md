# Local chat lab

Use the lab to try natural-language requests against the real Pound API and inspect
where the tool schemas or prompts need work. It runs separately from the map and is
not included in the production website image.

## Start

1. Start the current Pound backend with graph, catalog, and boat-hire data as described
   in the [development guide](development.md#map-prototype-local-development).
   Check `/api/health` before opening a chat. Use current Great Britain artifacts;
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

- “Find Bletchley Park and show its canal access options.”
- Choose one of the returned canal candidates and ask for an out-and-back preview,
  specifying days and hours per day. Follow up with “Make that five days.”
- Try an ambiguous or missing attraction, or ask for a ring/hire-base comparison,
  and check that the response acknowledges the ambiguity or missing capability.

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

## Current scope

The lab wraps real OSM attraction resolution, geometric canal candidates,
point-to-point routes and out-and-back previews. It only accepts place/candidate
references previously returned in that conversation. Pound owns route feasibility
and rejects stale artifact revisions. Unknown boat dimensions remain unknown.

Multi-base trip discovery (#78), Google place fallback, verified walking transfers,
ring search, and map route adoption are not connected. The lab exposes those gaps;
it does not replace #20's hosted backend or #80's final map conversation UI.
Model prose is still exploratory output, not evidence of bookability or access.

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
