# Global Pi Model Routing Design

**Date:** 2026-07-12
**Scope:** User-wide Pi configuration under `~/.pi/agent/`

## Goal

Route routine Pi coordination and execution through GPT-5.6 Luna while reserving GPT-5.6 Sol for explicit planning and high-complexity advisory work. Delegate narrowly specified mechanical work to DeepSeek V4 Flash. Preserve diverse per-task review through a deterministic four-model cycle.

## Role Routing

| Work type | Agent roles | Model | Effort |
|---|---|---|---|
| Default session and routine orchestration | global default | `openai-codex/gpt-5.6-luna` | max |
| Planning, design, context building, research | `planner`, `context-builder`, `researcher` | `openai-codex/gpt-5.6-sol` | medium |
| Architecture advice and final whole-branch review | `oracle`, `reviewer` | `openai-codex/gpt-5.6-sol` | high |
| Normal execution | `worker`, `delegate`, `worker-integration`, `worker-architecture` | `openai-codex/gpt-5.6-luna` | max |
| Bounded reconnaissance and mechanical execution | `scout`, `worker-mechanical` | `opencode-go/deepseek-v4-flash` | high |
| Per-task review | `task-reviewer` | explicit rotating roster | high |

The parent session remains the decision-maker. Sol produces plans and handles explicitly escalated judgment. Luna handles routine organization and implements approved work. DeepSeek V4 Flash receives only bounded reconnaissance or mechanical tasks with clear acceptance criteria.

## Task-Review Rotation

Each new implementation task selects its reviewer from this ordered roster:

1. `opencode-go/deepseek-v4-pro`
2. `opencode-go/glm-5.2`
3. `opencode-go/mimo-v2.5-pro`
4. `opencode-go/kimi-k2.7-code`

Selection is deterministic: task number `N` uses roster index `(N - 1) mod 4`. All task reviewers run at high effort. Re-reviews after fixes retain the original task's model so the same reviewer verifies resolution. The next new task advances the cycle.

The shared `task-reviewer` agent defines the review contract. The orchestrating parent must pass the selected model explicitly on every initial review and re-review dispatch. Direct task-reviewer invocations may retain MiMo V2.5 Pro at high effort as a safe fallback, but plan execution must not rely on that fallback.

## Configuration Changes

### `~/.pi/agent/settings.json`

- Set `defaultProvider` to `openai-codex`.
- Set `defaultModel` to `gpt-5.6-luna`.
- Set `defaultThinkingLevel` to `max`.
- Override planning and complex advisory agents with Sol at the effort levels in the role table.
- Override normal execution agents with Luna Max.
- Override `scout` with DeepSeek V4 Flash High.
- Preserve explicit provider-qualified model IDs.

### `~/.pi/agent/agents/*.md`

- Re-pin `worker-integration` and `worker-architecture` to Luna Max because they execute approved work even when the work is difficult.
- Keep `worker-mechanical` on DeepSeek V4 Flash and explicitly set high effort.
- Keep `task-reviewer` on MiMo V2.5 Pro High only as its direct-invocation fallback; orchestration supplies the rotating model explicitly.
- Update descriptions that name obsolete model assignments.

### `~/.pi/agent/AGENTS.md`

- Replace the existing implementation/review model roster with the role-routing policy in this design.
- Preserve task complexity guidance and the rule that every subagent dispatch specifies a canonical `provider/model` ID.
- Add the deterministic task-review roster, task-number selection rule, and same-model re-review rule.
- Preserve the requirement to use the least expensive role capable of completing the work reliably.

## Failure Behavior

Model resolution must fail loudly. Configuration must not silently switch providers, substitute an unapproved model, or promote mechanical work to Sol. Explicit provider-qualified IDs prevent ambiguous resolution. Existing fallback behavior must not bypass the task-review rotation during plan execution.

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
3. Confirm subagent discovery resolves every edited agent and its intended model/effort.
4. Confirm `towpath` has no project-level `.pi/settings.json` overriding the global policy.
5. Review the resulting diffs for unrelated configuration changes.

Configuration changes affect new sessions and newly launched subagents. An already-running parent session retains its selected model until changed or restarted.

## Non-Goals

- No custom provider or model registration changes.
- No project-specific routing policy.
- No automatic fallback between Sol, Luna, and opencode-go models.
- No parallel writer orchestration changes.
- No changes to task-review criteria or output format.
