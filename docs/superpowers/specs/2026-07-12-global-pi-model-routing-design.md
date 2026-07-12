# Global Pi Model Routing Design

**Date:** 2026-07-12
**Scope:** User-wide Pi configuration under `~/.pi/agent/`

## Goal

Implement Pareto-frontier model routing for Pi sessions and subagents using the
frontier registry at `docs/pi-model-frontier.csv`. Select models along the
quality-cost Pareto frontier: use the least expensive model capable of
completing each role reliably, upgrade explicitly to a more capable model when
the work's complexity justifies the additional cost, and rotate per-task
reviews across a five-model roster.

## Role Routing

<!-- markdownlint-disable MD013 -->

| Work | Agent roles | Model | Thinking |
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

<!-- markdownlint-enable MD013 -->

The parent session remains the decision-maker. Sol produces plans and handles
explicitly escalated judgment. Luna handles routine organization and implements
approved work. MiMo V2.5 Pro handles routine implementation at lower cost.
DeepSeek V4 Flash receives only bounded reconnaissance or mechanical tasks with
clear acceptance criteria. The quality-cost frontier is catalogued at
`docs/pi-model-frontier.csv`; the pinned `kthorn-skills` package checkout is
intentionally outside this change.

## Task-Review Rotation

Each new implementation task selects its reviewer from this ordered roster:

1. `opencode-go/deepseek-v4-pro` at `high`
2. `opencode-go/glm-5.2` at `high`
3. `opencode-go/mimo-v2.5-pro` at `high`
4. `opencode-go/kimi-k2.7-code` at `high`
5. `openai-codex/gpt-5.6-luna` at `xhigh`

Selection is deterministic: task number `N` uses roster index `(N - 1) mod 5`.
Each dispatch passes both the model and thinking level explicitly. Re-reviews
after fixes retain the original task's model so the same reviewer verifies
resolution. The next new task advances the cycle.

The shared `task-reviewer` agent defines the review contract. The orchestrating
parent must pass the selected model and thinking level explicitly on every
initial review and re-review dispatch. Direct task-reviewer invocations may
retain MiMo V2.5 Pro at high effort as a safe fallback, but plan execution
must not rely on that fallback.

## Configuration Changes

### `~/.pi/agent/settings.json`

- Set `defaultProvider` to `openai-codex`.
- Set `defaultModel` to `gpt-5.6-luna`.
- Set `defaultThinkingLevel` to `max`.
- Override planning and complex advisory agents with Sol at the effort levels
  in the role table.
- Override normal execution agents with Luna Max.
- Override `scout` with DeepSeek V4 Flash High.
- Preserve explicit provider-qualified model IDs.

### `~/.pi/agent/agents/*.md`

- Re-pin `worker-integration` and `worker-architecture` to Luna Max because they
  execute approved work even when the work is difficult.
- Keep `worker-mechanical` on DeepSeek V4 Flash and explicitly set high effort.
- Keep `task-reviewer` on MiMo V2.5 Pro High only as its direct-invocation
  fallback; orchestration supplies the rotating model explicitly.
- Update descriptions that name obsolete model assignments.

### `~/.pi/agent/AGENTS.md`

- Replace the existing implementation/review model roster with the role-routing
  policy in this design.
- Preserve task complexity guidance and the rule that every subagent dispatch
  specifies a canonical `provider/model` ID.
- Add the deterministic task-review roster, task-number selection rule, and
  same-model re-review rule.
- Preserve the requirement to use the least expensive role capable of
  completing the work reliably.

## Failure Behavior

Model resolution must fail loudly. Configuration must not silently switch
providers, substitute an unapproved model, or promote mechanical work to Sol.
Explicit provider-qualified IDs prevent ambiguous resolution. Existing
fallback behavior must not bypass the task-review rotation during plan
execution.

## Validation

After editing:

1. Parse `~/.pi/agent/settings.json` as JSON.
2. Confirm Pi lists all selected models:
   - `openai-codex/gpt-5.6-luna`
   - `openai-codex/gpt-5.6-sol`
   - `opencode-go/deepseek-v4-flash`
   - `opencode-go/deepseek-v4-pro`
   - `opencode-go/glm-5.2`
   - `opencode-go/mimo-v2.5-pro`
   - `opencode-go/kimi-k2.7-code`
3. Confirm subagent discovery resolves every edited agent and its intended
   model/effort.
4. Confirm `towpath` has no project-level `.pi/settings.json` overriding the
   global policy.
5. Review the resulting diffs for unrelated configuration changes.

Configuration changes affect new sessions and newly launched subagents. An
already-running parent session retains its selected model until changed or
restarted.

## Non-Goals

- No custom provider or model registration changes.
- No project-specific routing policy.
- No automatic fallback between Sol, Luna, and opencode-go models.
- No parallel writer orchestration changes.
- No changes to task-review criteria or output format.
