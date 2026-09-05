# Towpath Pi runtime adapter

Status: implemented for #79; live agent tools and HTTP integration remain in #20.

## Decision and ownership

Use the restricted Pi coding-agent SDK pattern already used successfully in Book Explorer.
The source reference was `~/book-explorer/src/agent-runtime.ts` and `src/turns.ts`:
fresh loader per turn, disabled built-ins, exact active-tool assertion, application events,
cancellation/disposal, and fake runtime injection. No Book Explorer code, credentials, web-search
extension, persistent library state, or local-only authentication configuration is copied.

`packages/towpath-agent` is an independently installed TypeScript library, excluded from the uv
workspace. It has no HTTP listener and is not started by the website container. Python routing
and catalog handlers stay deterministic and network-free. The host implementing #20 will supply
its own authentication, Pi model runtime, model choice, event transport, and Pound tool handlers.

## Contracts

`AgentRuntime` owns temporary session IDs, authenticated owner associations, monotonically
increasing plan revisions, active run IDs, event sequence numbers, and bounded client tasks.
The host creates a session using an identity from its own authentication layer. All later actions
check the same owner. Unknown, expired, deleted, and foreign sessions produce `not_found`.

A run is a fresh Pi session with an in-memory transcript. No transcript is retained between
runs. The session metadata is not chat memory. #20 must construct each request from current
application-owned trip state and explicitly decide any later conversation-retention policy.
This prevents accidentally carrying restricted provider details or stale route handles forward.
The adapter does not persist prompts, results, or credentials.

Domain tools use an allowlisted name and strict object schema. Their application handlers receive
validated JSON and trusted run identity, an abort signal, and methods for publishing issued
options/clarifications or awaiting browser input. Model prose is untrusted explanatory text.
There is no route-adoption tool: issued option validation and actual user selection belong to
application handlers and #20/#80. The adapter cannot establish the truth of domain tool data;
Pound must validate route requests and keep graph/data ownership at its existing boundary.

The Pi factory requires explicit absolute application directories, model, and model runtime.
It never creates a runtime using a developer's default credentials. It uses in-memory settings
and a newly reloaded resource loader with ambient instructions, extensions, skills, templates,
and themes disabled. Only supplied domain tools are active; the tool surface is checked at
creation and before prompting/provider calls. Template/extension command expansion is disabled.
Automatic compaction and retries are disabled so they cannot add hidden model calls.

## Browser and streaming boundary

Every event contains session ID, run ID, revision, and increasing sequence number. Pi events
are normalized to text deltas and tool status; raw messages, thinking, errors, arguments and
results are not forwarded. Trusted handlers publish options and clarification payloads. A browser
request carries an application-owned JSON task plus a generated single-use task ID. This is a
transport primitive for #77, not a fixed Google schema.

The corresponding reply must match owner/session/run/revision/task and a handler-provided
response schema. Invalid data may be corrected before the deadline; an accepted reply consumes
the task. Replayed, late, stale-plan, foreign-session, and completed-run replies are rejected.
The application must ensure task content comes from validated domain records and keep Google
content on the permitted browser path. Browser replies never mutate shared graph/catalog data.

Event sinks are synchronous; transport hosts should copy events into a bounded queue and return
promptly. The adapter does not implement SSE, network authentication, reconnect replay, durable
queues, or a Google adapter. Those remain the host's responsibilities.

## Bounds and cancellation

Defaults: 8 model calls, 20 handler calls, 2048 output tokens per model call, 60 seconds per run,
64 KiB per JSON input/result/task/reply, 64 KiB cumulative emitted payload data, 2000 events,
2 concurrent runs, 100 session records, and a 30-minute absolute session lifetime. These are
conservative starting limits, not a measured cost or latency objective. Metadata expiry is
checked at access/session creation; no transcript remains in an expired record.

A plan revision change, deletion, cancellation, caller abort, deadline, or fatal budget violation
revokes tool contexts and browser tasks. A payload limit must abort the run: throwing alone is
insufficient because Pi can recover from tool exceptions. Tool validation failures remain
recoverable within call limits. Raw handler/provider exceptions are not returned to clients.

The caller receives a terminal error promptly on cancellation. The concurrency slot remains held
until the factory/prompt actually settles and the driver is disposed. A provider or handler that
ignores cancellation cannot release a slot and multiply background work. A permanently stuck
operation consumes a slot until process recycling. This library cannot preempt synchronous CPU
work: #20 must use cooperative/bounded calls or an isolated worker for expensive operations.

## Deployment handoff

The intended host is an optional Node 24.15+ service in front of or beside the existing website.
The production Python image does not contain or require Pi. Add authenticated same-origin event
transport, session ownership resolution, rate limits, provider budgets, and service supervision
in #20. Route requests use existing Pound HTTP/schema validation, not direct graph access.
Use a service-specific model configuration and secret path; choose the provider/model explicitly.
No automatic provider fallback or inherited local subscription is part of this design.
Multi-instance routing needs affinity or shared lifecycle coordination; the current in-memory
registry and concurrency limits are process-local. Restart invalidates all sessions/runs.

## Verification

The package tests exercise the actual pinned SDK with Pi's faux provider and synthetic tools.
The Bletchley fixture resolves a sourced fixture attraction, rejects a scripted unavailable
`bash` call, coordinates a browser task, publishes two issued return-trip IDs, rejects an invented
selection, and requests explicit user choice. This verifies tool/adoption boundaries; it does
not claim resistance to arbitrary model prompt injection or real-world route feasibility.

Tests cover ambient-resource isolation, fresh-session reuse after disposal, model-call/output
limits, strict tool schemas, ownership/revision/deletion/expiry, concurrency, cancellation,
late factories/tool results, browser replay/schema failures, and error redaction. Regression
coverage includes fatal payload budgets through real Pi and browser promises rejected before
the task event can be emitted. All default tests and the demonstration are offline.
