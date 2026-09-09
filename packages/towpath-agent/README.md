# Towpath agent runtime

Optional TypeScript library for #79. Adapts Book Explorer's restricted Pi SDK session pattern
for Towpath's application tools. Live routing tools and authenticated web transport belong to
#20, with place/access coordination in #77 and trip discovery in #78.

## Run the offline checks

Requires Node 24.15+. The SDK is pinned to `@earendil-works/pi-coding-agent@0.84.2`, with
`@earendil-works/pi-ai@0.84.4` for the faux-provider interface; the lockfile pins the SDK's
compatible nested dependencies. SDK and TypeBox licenses are MIT. No book-tool checkout is
needed to install or run this package.

```sh
npm ci
npm test
npm run demo
```

Tests use the real Pi SDK with its faux provider, or injected fake sessions. No API keys,
OAuth credentials, real routes, or provider calls are needed. The demo's route IDs are synthetic:

```text
Synthetic offline fixture; no real route, provider, or model calls.
...
{"type":"options","data":{"optionIds":["fixture:base-a:turn-1","fixture:base-b:turn-2"]}}
{"type":"clarification","data":{"question":"Which return trip would you like?","optionIds":["fixture:base-a:turn-1","fixture:base-b:turn-2"]}}
{"type":"complete","data":{}}
```

The fixture scripts an unavailable `bash` call and invented option selection to exercise their
rejection. It tests enforced capability and selection boundaries, not a model's general resistance
to prompt injection. No real Bletchley trip is validated here.

## Embed in an application host

The package deliberately has no server/listener or automatic model configuration. The host
passes a configured Pi `ModelRuntime` and an explicitly selected model to `createPiSessionFactory`.
It must reject missing models/credentials at startup rather than select another provider.
Use a service-owned secret path and application directories, not `~/.pi` or Book Explorer's
local OAuth store. The adapter never discovers or copies credentials and never calls catalog
refresh. Domain handlers call Pound through its validated HTTP boundary; they do not load or
mutate graph artifacts.

```ts
import { AgentRuntime, createPiSessionFactory } from '@towpath/agent';

// modelRuntime, model and poundTools are configured by the trusted application host.
const runtime = new AgentRuntime({
  factory: createPiSessionFactory({
    cwd: '/var/lib/towpath-agent/work',
    agentDir: '/var/lib/towpath-agent/config',
    modelRuntime,
    model,
  }),
  tools: poundTools,
});

// ownerId comes from authentication, never a browser-supplied owner field.
const session = runtime.createSession(ownerId);
const result = await runtime.run({
  ownerId,
  ...session,
  message: 'I want a canal trip visiting Bletchley Park.',
  signal: disconnectSignal,
  onEvent(event) { boundedTransportQueue.enqueue(event); },
});
```

This is a private repository package; build it and import its `dist/src/index.js` or use a local
package dependency in the future host. The illustrative import name does not imply npm publishing.
No real provider setup is included in the offline demo.

Each `DomainTool` has one of `TOOL_NAMES`, a description, a TypeBox object schema with
`additionalProperties: false`, and an async handler. Input JSON is size-checked and schema-checked
before the handler runs. Use nested strict schemas and bounded fields as appropriate. Keep
Pydantic HTTP validation in Pound; TypeScript validation does not replace it. Results must be
JSON, without undefined/non-finite numbers, and fit the payload budget.

The handler context includes authenticated `ownerId`, `sessionId`, `runId`, `revision`, and an
abort signal. Use these identity fields to scope application option stores; do not accept identity
or confirmations from model arguments. `publish('options' | 'clarification', payload)` is reserved
for trusted handler-owned facts. There is no tool for adopting a trip or claiming user approval.
#20 must bind user actions to issued options, current settings, and artifact/data revisions.

The factory creates a fresh Pi session and loader for each run. Built-ins, ambient extensions,
skills, project instructions, templates, themes and automatic compaction/retries are disabled.
Only the explicitly supplied domain tools are enabled; the exact active set is checked before
prompting and provider calls. No web-search extension is installed.

## Sessions, revisions and browser tasks

Application sessions contain ownership/revision metadata only. Pi transcripts are in memory for
one run and then disposed: **there is no cross-run conversation memory**. #20 must supply current
structured trip context with each request and decide any future history/retention policy. Do not
persist restricted provider responses by casually adding Pi JSONL persistence.

- `revise(ownerId, sessionId)` increments the plan revision and aborts active work. Call it after
  any relevant user setting, route selection, or artifact change; propagate the returned revision.
- `cancel(ownerId, sessionId, runId)` aborts that exact run.
- `deleteSession(ownerId, sessionId)` removes metadata and aborts active work.
- Unknown, foreign, deleted or expired sessions return the same `not_found` error.

A handler may await `ctx.requestBrowserTask(task, responseSchema)`. Task JSON must be constructed
from trusted candidate data. Events carry `sessionId`, `runId`, `revision`, `sequence` and a
single-use task ID. The host delivers the task to the browser and passes its reply through
`submitBrowserResult({ownerId, sessionId, runId, revision, taskId, result})` using authenticated
ownership. The result must match both correlation fields and the handler-supplied schema.
A valid result consumes the task; invalid data can be corrected while it remains pending. Replays,
stale revisions and late results fail. This generic primitive does not yet implement #77's Google
transfer schemas; keep provider-specific content transient and in its permitted browser path.

Events are application contracts: `started`, `text_delta`, `tool_status`, `options`,
`clarification`, `browser_task`, `complete`, and `error`. Only the first three originate from Pi
activity; tools publish domain events and the coordinator owns terminal events. Text remains
untrusted explanation and must not override route cards. Raw provider errors, reasoning, tool
arguments and results are not streamed. Error events contain a stable code only.

`onEvent` must return synchronously. Queue events in a bounded transport buffer; slow or failed
clients need host-level disconnect/backpressure handling. No SSE reconnect buffer is provided.

## Execution limits and operations

| Limit | Default |
| --- | --- |
| Provider calls per run | 8 |
| Handler calls per run (including rejected arguments) | 20 |
| Output tokens per provider call | 2048 |
| Elapsed run time | 60 seconds |
| Individual JSON input/result/task/reply | 64 KiB |
| Cumulative emitted payload data | 64 KiB |
| Events, including terminal event | 2000 |
| Concurrent runs per process | 2 |
| Runs per application session | 1 at a time |
| Session metadata records | 100 |
| Session lifetime | 30 minutes from creation |

The SDK may reject invalid tool calls before a handler is invoked; provider-call and event bounds
still apply. The token cap is per call, not a dollar limit; configure account/project budgets and
host admission/rate limits separately. No live cost or latency benchmark was performed.

Cancellation, revision changes, expiry, and budget failure revoke handler contexts and pending
browser tasks. Deadline covers session creation, provider activity, tools and browser waits.
Budget errors abort the run rather than becoming recoverable Pi tool failures. Ordinary tool
schema errors can be corrected by the model within remaining limits. Session expiry is checked
on access/session creation, with active runs also bounded by remaining lifetime.

After cancellation the caller receives an error promptly, but the concurrency slot stays reserved
until work actually settles and the session is disposed. Tools must honor the abort signal and
bound their own search/HTTP work. Permanently stuck work consumes capacity until process recycling;
this library cannot preempt synchronous CPU loops. #20 should isolate uncooperative or CPU-heavy
work in workers and supervise the optional service.

Session metadata and limits are process-local. A hosted multi-instance deployment needs routing
affinity or shared coordination. Restart loses sessions; clients must start fresh. Deploy the host
as a separately supervised optional Node service with its own authentication, secrets, quotas and
lifecycle. The Python website container and manual planner remain usable without this package.

See [the design](../../docs/completed/2026-09-05-pi-agent-runtime-design.md) for the #20 handoff.

## Live OpenAI smoke test

Requires Node 24.15+ and an OpenAI API key with access to **GPT 5.6 Luna**.
Pi uses the `openai` provider, `gpt-5.6-luna`, and the Responses API at
`https://api.openai.com/v1`. Inference billing goes to OpenAI; AWS Secrets Manager
can hold the API key. See the [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

From this package directory, with `OPENAI_API_KEY` supplied in the environment:

```sh
npm ci
npm run smoke:live
# Optional one-shot prompt (still requires a tool call to pass):
npm run smoke:live -- --prompt 'Use resolve_place to look up Bletchley Park.'
```

For AWS Secrets Manager, create an **Other type of secret**, with the raw API key
as its plaintext secret value (not a JSON object). Suggested name: `towpath/openai-api-key`.
Then run this Bash command to fetch it into the smoke process environment:

```bash
(
  set +x
  OPENAI_API_KEY="$(aws secretsmanager get-secret-value \
    --profile default --region us-east-1 \
    --secret-id towpath/openai-api-key \
    --query SecretString --output text --no-cli-pager)" || exit
  export OPENAI_API_KEY
  npm run smoke:live
)
```

The subshell keeps the key out of the parent shell environment and command history.
The calling AWS identity needs `secretsmanager:GetSecretValue` for that secret (and
`kms:Decrypt` if it uses a customer-managed KMS key). See the
[AWS retrieval documentation](https://docs.aws.amazon.com/cli/latest/reference/secretsmanager/get-secret-value.html).
For the future hosted service, inject the same secret as `OPENAI_API_KEY` at startup;
the agent library itself does not fetch secrets.

The CLI fails immediately when the key is missing. It does not load Pi credential files,
use ChatGPT subscription credentials, or fall back to Bedrock or another model.
This makes at most three billed model calls (1024 output tokens each), with a 60-second
run deadline. One synthetic `resolve_place` tool returns a fixed fixture; no routing or
place service is contacted. JSON event output shows tool status and streamed text, followed
by elapsed time and the executed tool count. Exit status is zero only if the run completes,
executes the tool, and emits text. This checks connectivity, not route-selection quality.
Each invocation starts a fresh in-memory session. The live command is opt-in and never runs
in CI; `npm test` checks the harness's pass/fail behavior offline.

If it reports `model_unavailable`, check the OpenAI API key, billing, and model access.
Live validation passed on 2026-09-08 using the key from AWS Secrets Manager: Luna
executed `resolve_place` once, received its synthetic result, and streamed a text reply.
The run completed successfully in 5833 ms (exit status 0).
