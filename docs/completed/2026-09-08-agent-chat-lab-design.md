# Local agent chat lab

Provide a local browser workspace for exercising Luna prompts against real Pound HTTP APIs
before the public conversational planner is built. A loopback-only Node service owns the API
key, bounded conversation context, issued place/candidate references, and the Pi runtime.
The page shows streamed chat and expandable tool request/result traces, with reset, cancel,
and transcript download. It is started explicitly and is excluded from production builds.

The first tools resolve OSM catalog places, obtain geometric canal candidates, and preview
point-to-point or out-and-back routes using existing validated endpoints. Place/candidate
references are issued and checked within the current conversation; route handles and artifact
revisions come from Pound, never model-generated coordinates or node IDs. Results passed to the
model omit route geometry and retain sourced summaries and warnings. Tool traces show the actual
validated requests and summary results; no credentials or provider reasoning are exposed.

Prior user/assistant messages and tool observations are kept as bounded application-owned context
for follow-up turns. Reset destroys this context and issued references; no files store chat history.
This is a developer evaluation surface, not a production authorization or trip-adoption flow.
A fixed capability preamble explains unsupported multi-base discovery (#78), rings, and browser
walking/Google fallback. Absence of catalog matches is reported explicitly. Prompt iteration uses
an optional local prompt file read at startup; the core safety instructions remain in the adapter.

The server binds 127.0.0.1, validates Host/Origin and a per-launch request token, bounds request
and response sizes, permits one run at a time, and cancels on disconnect. Pound's URL is fixed
by host configuration and restricted to a loopback origin. Local state expires with the runtime.
The UI renders all model/tool text using textContent. It never changes the manual planner.

Offline tests cover real API mapping with mocked HTTP, unknown references, cancellation and
follow-up context, and local HTTP request protections. Live validation is opt-in and bounded.
The lab does not complete #20/#80; it makes their API and prompting gaps testable.

## Default-first exploration (2026-09-13)

System, lab and tool instructions permit reversible preview choices instead of requiring
confirmation for every ambiguous record. Nearby same-attraction records use one sourced
representative, preserving identity; materially distinct destinations still need clarification.
Missing schedules default to three days and six cruising hours per day. A missing start uses
a nearby canal candidate for an explicitly provisional area preview. Explicit preferences and
unknown boat dimensions remain authoritative. The model chains tools in one turn and uses
canal candidate references, never OSM place references, in route arguments. No API or route
feasibility changes are required. Offline checks plus a minimal real two-turn browser check
verify integration; route-quality evaluation remains interactive.

## Hire bases and API coverage (2026-09-13)

Hire discovery exposes published public base records with their existing validated canal anchors,
source-provider identities and source links. Comparisons first search canal connectivity from the
attraction access point, using separate outward and return travel costs and half the full cruising
budget for each direction. They inspect all public anchors before applying pagination; geographic
proximity never establishes reachability. Each shortlisted base then uses the existing full
out-and-back planner with the required attraction waypoint. Failure to reach a turnaround or fit
daily scheduling remains a rejection even if the base passed the preliminary reachability test.
The agent compares bounded batches and reports when more bases remain. The cruising budget does
not include a land visit, walking transfer, pickup allowance, or booking availability.

Named tools cover server-side planning endpoints, with strict arguments and bounded summaries.
Conversation-local preview references retain geometry for place/POI follow-ups and original
request/route IDs for exact out-and-back replay. Model-supplied handles, route geometry, arbitrary
URLs and credentials remain outside the tool surface. Large network geometry, climate masks and
sample arrays are processed by the host rather than copied into model context. Google place and
walking verification remains an application-owned browser protocol; model-authored callbacks
cannot establish provider results.
