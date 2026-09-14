# Towpath agent runtime

Optional TypeScript Pi adapter for Towpath's application tools (#79).
The website integration belongs to #20; this package runs independently of Python.

## Setup and offline checks

Requires Node 24.15+. From this directory:

```sh
npm ci
npm test
npm run demo
```

Tests and the Bletchley demo use the real Pi SDK with fake models and synthetic tools.
They need no API key and make no provider calls. Dependencies are pinned in the lockfile.

## Live OpenAI smoke test

Requires Node 24.15+ and an OpenAI API key with access to **GPT 5.6 Luna**.
Pi uses the `openai` provider, `gpt-5.6-luna`, and the Responses API at
`https://api.openai.com/v1`. Inference billing goes to OpenAI; AWS Secrets Manager
can hold the API key. See the [OpenAI model documentation](https://developers.openai.com/api/docs/models/gpt-5.6-luna).

With `OPENAI_API_KEY` in the environment, run `npm run smoke:live`.
Use `-- --prompt "..."` for a custom one-shot prompt.

To use `towpath/openai-api-key` from AWS Secrets Manager:

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

The secret stores the raw key as plaintext. The AWS identity needs
`secretsmanager:GetSecretValue` and, for a customer-managed KMS key, `kms:Decrypt`.
The CLI reads `OPENAI_API_KEY`; the host is responsible for retrieving the secret.

Success requires a completed run, an executed synthetic `resolve_place` tool, and a
text reply. The test allows up to three model calls, 1024 output tokens per call,
and 60 seconds. It checks tool connectivity, not route quality, and never runs in CI.
Missing keys fail immediately; `model_unavailable` means to check OpenAI credentials,
billing, and model access.

Live validation passed on 2026-09-08: one tool execution and a streamed reply in 5.8 seconds.

## Integration

The host supplies the model/runtime, authenticated owner, domain tools, and event transport.
Only allowlisted domain tools are enabled. Sessions hold metadata; transcripts last for
one run. There is no HTTP listener, cross-run conversation memory, or live Pound tool yet.

See the [integration reference](../../docs/agent-runtime.md) for the embedding example,
session/browser-task APIs, execution limits, and deployment responsibilities, and the
[runtime design](../../docs/completed/2026-09-05-pi-agent-runtime-design.md) for the #20 handoff.

## Local chat lab

With a local Pound API running and `OPENAI_API_KEY` set, run `npm run chat:lab` and
open <http://127.0.0.1:8787>. The page streams chat, shows real API/tool traces, and
supports follow-ups, stop/reset, and session download. See the
[chat lab guide](../../docs/chat-lab.md) for setup, prompt experiments, and current gaps.
