# Pareto-Frontier Pi Model Routing Update

**Date:** 2026-07-12
**Status:** Approved design
**Scope:** User-wide Pi configuration under `~/.pi/agent/`, the global routing contract, and its repository documentation

## Context

The existing global Pi policy uses GPT-5.6 Luna for most execution, GPT-5.6 Sol
for planning and advisory work, and a four-model OpenCode rotation for task
reviews. The available model/effort combinations have since been measured as a
Pareto frontier with materially different cost and coding-performance scores.

Pi exposes GPT-5.6 Luna and GPT-5.6 Sol as model IDs; `low`, `medium`, `high`,
`xhigh`, and `max` are thinking levels. Every configured ID must therefore use
its canonical provider-qualified form and carry its effort level separately.

## Goals

1. Route each execution and advisory role to the least expensive frontier point
   that is appropriate for its complexity.
2. Keep review diversity rather than collapsing every review onto the highest
   scoring OpenAI model.
3. Add GPT-5.6 Luna xhigh to the deterministic review rotation.
4. Record the frontier data and policy in repository documentation so later
   changes are auditable.
5. Fail loudly on model resolution problems; do not silently substitute a
   provider, model, or effort level.

## Frontier registry

The implementation will add a provider-neutral frontier registry to the
repository. Costs and scores are the supplied comparative values; they are
metadata for routing decisions, not runtime configuration.

| Label | Canonical model ID | Thinking | Cost | Score |
| --- | --- | --- | ---: | ---: |
| DeepSeek V4 Flash | `opencode-go/deepseek-v4-flash` | `max` | 0.03 | 56 |
| MiMo V2.5 Pro | `opencode-go/mimo-v2.5-pro` | `high` | 0.04 | 60 |
| GPT-5.6 Luna | `openai-codex/gpt-5.6-luna` | `high` | 0.09 | 63 |
| GPT-5.6 Luna | `openai-codex/gpt-5.6-luna` | `xhigh` | 0.10 | 69 |
| GPT-5.6 Sol | `openai-codex/gpt-5.6-sol` | `low` | 0.13 | 70 |
| GPT-5.6 Luna | `openai-codex/gpt-5.6-luna` | `max` | 0.16 | 71 |
| GPT-5.6 Sol | `openai-codex/gpt-5.6-sol` | `medium` | 0.18 | 76 |
| GPT-5.6 Sol | `openai-codex/gpt-5.6-sol` | `high` | 0.22 | 77 |
| GPT-5.6 Sol | `openai-codex/gpt-5.6-sol` | `xhigh` | 0.30 | 78 |

## Role routing

The routing ladder uses the cheapest frontier point capable of the role. The
role boundary remains authoritative: execution agents implement approved work;
planning and advisory agents retain decision authority where specified.

| Work | Agent roles | Canonical model ID | Thinking |
| --- | --- | --- | --- |
| Default session and routine orchestration | global default | `openai-codex/gpt-5.6-luna` | `high` |
| Mechanical transcription/testing and bounded scouting | `worker-mechanical`, `scout` | `opencode-go/deepseek-v4-flash` | `max` |
| Routine implementation | `worker`, `delegate` | `opencode-go/mimo-v2.5-pro` | `high` |
| Multi-file prose-spec implementation | `worker-integration` | `openai-codex/gpt-5.6-luna` | `xhigh` |
| Broad-codebase execution of an approved design | `worker-architecture` | `openai-codex/gpt-5.6-luna` | `max` |
| Context building | `context-builder` | `openai-codex/gpt-5.6-sol` | `low` |
| Planning and research | `planner`, `researcher` | `openai-codex/gpt-5.6-sol` | `medium` |
| Architecture advice and decision consistency | `oracle` | `openai-codex/gpt-5.6-sol` | `high` |
| Final whole-branch review | `reviewer` | `openai-codex/gpt-5.6-sol` | `xhigh` |

The direct-invocation fallback in `task-reviewer` remains
`opencode-go/mimo-v2.5-pro` at `high`; plan execution supplies the selected
rotation entry explicitly.

## Review rotation

The existing diverse review set is retained and extended with Luna xhigh:

1. `opencode-go/deepseek-v4-pro` at `high`
2. `opencode-go/glm-5.2` at `high`
3. `opencode-go/mimo-v2.5-pro` at `high`
4. `opencode-go/kimi-k2.7-code` at `high`
5. `openai-codex/gpt-5.6-luna` at `xhigh`

For implementation task number `N`, the initial reviewer is entry
`(N - 1) mod 5`. A re-review after fixes retains the original task's reviewer;
only a new task advances the cycle. The orchestrator must pass both the
canonical model ID and thinking level on every review dispatch.

## Configuration and documentation changes

The implementation will:

- update `~/.pi/agent/settings.json` with the global default and builtin-agent
  overrides from the role table;
- update the custom worker and task-reviewer frontmatter in
  `~/.pi/agent/agents/` so direct invocation agrees with global defaults;
- replace the routing and review sections in `~/.pi/agent/AGENTS.md`;
- add the frontier registry and update the committed routing design/plan to
  describe the new policy and validation commands;
- leave the separately pinned `kthorn-skills` checkout unchanged. Its
  `pi-refine` defaults are a separate published-package concern; global plan
  execution uses the explicit five-entry review rotation above.

No project-level `.pi/settings.json` will be created. No project application
code or unrelated dirty worktree changes will be modified.

## Failure behavior

All model references use canonical `provider/model` IDs. A missing or
unavailable model/effort combination is an error. The policy must not silently
fall back to another provider, model, or effort tier, and the review rotation
must not be bypassed by a default reviewer model during plan execution.

## Validation

After implementation:

1. Parse `~/.pi/agent/settings.json` as JSON and assert every role mapping.
2. Inspect custom agent frontmatter for the required model and thinking pairs.
3. Confirm Pi lists the selected model IDs with `pi --list-models`.
4. Confirm all discovered subagents resolve to their intended defaults.
5. Confirm `/home/kurtt/towpath/.pi/settings.json` remains absent.
6. Review the repository diff to ensure only routing documentation and the new
   registry are added alongside the intended global configuration changes.

## Non-goals

- No provider registration or model alias changes.
- No automatic fallback or retry policy between frontier points.
- No changes to review criteria, report formats, or orchestration concurrency.
- No update to the pinned `kthorn-skills` package in this task.
