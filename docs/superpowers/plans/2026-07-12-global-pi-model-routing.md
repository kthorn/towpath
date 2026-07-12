# Global Pi Model Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Configure user-wide Pi model routing so Luna Max handles routine work and execution, Sol Medium/High handles explicit complex roles, DeepSeek V4 Flash High handles bounded mechanical work, and per-task reviews rotate across four models.

**Architecture:** Builtin role routing lives in `~/.pi/agent/settings.json`; custom worker defaults remain in their agent frontmatter; the global orchestration contract lives in `~/.pi/agent/AGENTS.md`. Task-review diversity is deterministic and stateless: task number selects a reviewer model, while re-reviews retain that task's original reviewer.

**Tech Stack:** Pi JSON settings, pi-subagents Markdown agent definitions, global Markdown agent instructions, Python 3 JSON validation, Pi model and subagent discovery.

## Global Constraints

- The global default is `openai-codex/gpt-5.6-luna` at `max` effort.
- `planner`, `context-builder`, and `researcher` use `openai-codex/gpt-5.6-sol` at `medium` effort.
- `oracle` and final whole-branch `reviewer` use `openai-codex/gpt-5.6-sol` at `high` effort.
- `worker`, `delegate`, `worker-integration`, and `worker-architecture` use `openai-codex/gpt-5.6-luna` at `max` effort.
- `scout` and `worker-mechanical` use `opencode-go/deepseek-v4-flash` at `high` effort.
- New-task reviews rotate in this order at `high` effort: `opencode-go/deepseek-v4-pro`, `opencode-go/glm-5.2`, `opencode-go/mimo-v2.5-pro`, `opencode-go/kimi-k2.7-code`.
- Task number `N` selects review roster index `(N - 1) mod 4`; re-reviews retain the original task model.
- Every delegated run specifies a canonical `provider/model` ID explicitly.
- Model resolution fails loudly; do not add cross-model or cross-provider fallbacks.
- Do not change provider registration, task-review criteria, output formats, or project-local Pi settings.
- `~/.pi/agent` is not a Git repository, so global configuration changes cannot be committed there; verify them directly and commit only this repository's plan document.

---

### Task 1: Apply and verify the global routing policy

**Files:**

- Modify: `~/.pi/agent/settings.json`
- Modify: `~/.pi/agent/agents/worker-integration.md`
- Modify: `~/.pi/agent/agents/worker-architecture.md`
- Modify: `~/.pi/agent/agents/worker-mechanical.md`
- Modify: `~/.pi/agent/agents/task-reviewer.md`
- Modify: `~/.pi/agent/AGENTS.md`
- Verify: `/home/kurtt/towpath/.pi/settings.json` remains absent

**Interfaces:**

- Consumes: Pi's `defaultProvider`, `defaultModel`, `defaultThinkingLevel`, and `subagents.agentOverrides` settings; pi-subagents agent frontmatter fields `model` and `thinking`.
- Produces: a user-wide role-to-model policy resolved by Pi for all new sessions and subagents.

- [ ] **Step 1: Run the pre-change assertions and confirm the current configuration does not satisfy the approved design**

Run:

```bash
python -c 'import json, pathlib; p=pathlib.Path.home()/".pi/agent/settings.json"; s=json.loads(p.read_text()); assert (s["defaultProvider"], s["defaultModel"], s["defaultThinkingLevel"]) == ("openai-codex", "gpt-5.6-luna", "max")'
```

Expected: FAIL with `AssertionError`, because the current default is GPT-5.6 Sol High.

Run:

```bash
rg -n '^model:|^thinking:' ~/.pi/agent/agents/{worker-integration,worker-architecture,worker-mechanical,task-reviewer}.md
```

Expected: integration is MiMo, architecture is GLM, mechanical has no explicit `thinking`, and task-reviewer has no explicit `thinking`.

- [ ] **Step 2: Replace `~/.pi/agent/settings.json` with the approved builtin-role routing**

Write exactly:

```json
{
  "lastChangelogVersion": "0.80.6",
  "defaultProvider": "openai-codex",
  "defaultModel": "gpt-5.6-luna",
  "defaultThinkingLevel": "max",
  "hideThinkingBlock": true,
  "skills": [
    "~/.pi/agent/superpowers/skills"
  ],
  "packages": [
    "npm:pi-subagents",
    "npm:pi-lens",
    "npm:pi-web-access",
    "git:github.com/kthorn/kthorn-skills",
    "npm:pi-intercom",
    "npm:pi-prompt-template-model"
  ],
  "subagents": {
    "agentOverrides": {
      "worker": {
        "model": "openai-codex/gpt-5.6-luna",
        "thinking": "max"
      },
      "delegate": {
        "model": "openai-codex/gpt-5.6-luna",
        "thinking": "max"
      },
      "context-builder": {
        "model": "openai-codex/gpt-5.6-sol",
        "thinking": "medium"
      },
      "oracle": {
        "model": "openai-codex/gpt-5.6-sol",
        "thinking": "high"
      },
      "planner": {
        "model": "openai-codex/gpt-5.6-sol",
        "thinking": "medium"
      },
      "researcher": {
        "model": "openai-codex/gpt-5.6-sol",
        "thinking": "medium"
      },
      "reviewer": {
        "model": "openai-codex/gpt-5.6-sol",
        "thinking": "high"
      },
      "scout": {
        "model": "opencode-go/deepseek-v4-flash",
        "thinking": "high"
      }
    }
  },
  "theme": "dark"
}
```

Do not duplicate custom worker overrides here; their user agent files are the single source of their pinned defaults.

- [ ] **Step 3: Re-pin the integration worker to Luna Max**

In `~/.pi/agent/agents/worker-integration.md`, change the frontmatter and opening role description to:

```markdown
---
name: worker-integration
description: Integration/judgment-tier TDD implementer (multi-file, prose spec) pinned to GPT-5.6 Luna Max via OpenAI Codex. Dispatch with a task brief file, a report file path, and scene-setting context. Follows TDD: failing test -> implement -> green -> commit -> self-review -> report.
tools: bash, read, edit, write
model: openai-codex/gpt-5.6-luna
thinking: max
systemPromptMode: append
inheritProjectContext: false
inheritSkills: true
defaultContext: fresh
---

You are an integration/judgment-tier implementation agent for multi-file tasks with a prose (not verbatim-code) spec. GPT-5.6 Luna Max is the standard execution model for this work. A task that is pure transcription-plus-testing belongs on the mechanical tier; unresolved product or architecture decisions must return to the Sol-powered parent planning or oracle role before execution continues.
```

Leave the remainder of the agent contract unchanged.

- [ ] **Step 4: Re-pin the architecture worker to Luna Max without granting it planning authority**

In `~/.pi/agent/agents/worker-architecture.md`, change the frontmatter and opening role description to:

```markdown
---
name: worker-architecture
description: Architecture/hard-tier TDD implementer (broad codebase execution of approved designs) pinned to GPT-5.6 Luna Max via OpenAI Codex. Dispatch with a task brief file, a report file path, and scene-setting context. Follows TDD: failing test -> implement -> green -> commit -> self-review -> report.
tools: bash, read, edit, write
model: openai-codex/gpt-5.6-luna
thinking: max
systemPromptMode: append
inheritProjectContext: false
inheritSkills: true
defaultContext: fresh
---

You are an architecture/hard-tier implementation agent for broad-codebase execution after the parent has approved the design. GPT-5.6 Luna Max implements that approved direction; it does not replace the Sol-powered planner or oracle for unresolved product or architecture decisions. A task that is pure transcription or self-contained integration belongs on a lower tier.
```

Leave the remainder of the agent contract unchanged.

- [ ] **Step 5: Make mechanical and direct task-review effort explicit**

In `~/.pi/agent/agents/worker-mechanical.md`, insert this directly after its existing `model:` line:

```yaml
thinking: high
```

In `~/.pi/agent/agents/task-reviewer.md`, insert this directly after its existing `model:` line:

```yaml
thinking: high
```

Keep MiMo V2.5 Pro as `task-reviewer`'s direct-invocation fallback. Plan execution must override it with the task's selected roster model.

- [ ] **Step 6: Replace the obsolete global model roster with the approved routing contract**

In `~/.pi/agent/AGENTS.md`, replace the entire section from `## Subagent-Driven Development: default agents` through the end of the file with:

```markdown
## Subagent-Driven Development: global model routing

Use role-based routing for every subagent dispatch. Always pass the canonical
`provider/model` ID and `thinking` level explicitly; do not rely on parent-model
inheritance or silently substitute a fallback.

| Work | Agent | Model | Thinking |
|------|-------|-------|----------|
| Planning and implementation plans | `planner` | `openai-codex/gpt-5.6-sol` | medium |
| Context building and research | `context-builder`, `researcher` | `openai-codex/gpt-5.6-sol` | medium |
| Architecture advice and decision consistency | `oracle` | `openai-codex/gpt-5.6-sol` | high |
| Final whole-branch review | `reviewer` | `openai-codex/gpt-5.6-sol` | high |
| Routine implementation | `worker`, `delegate` | `openai-codex/gpt-5.6-luna` | max |
| Multi-file prose-spec implementation | `worker-integration` | `openai-codex/gpt-5.6-luna` | max |
| Broad-codebase execution of an approved design | `worker-architecture` | `openai-codex/gpt-5.6-luna` | max |
| Mechanical transcription/testing and bounded scouting | `worker-mechanical`, `scout` | `opencode-go/deepseek-v4-flash` | high |

The global interactive default is GPT-5.6 Luna Max. Routine organization and
execution stay on Luna. Upgrade explicitly to Sol Medium for planning, design,
context building, and research; use Sol High for oracle work, unresolved
architecture decisions, and final whole-branch review. A hard implementation
still runs on Luna after Sol resolves and approves the design.

### Per-task review rotation

Use the shared `task-reviewer` contract, but pass the review model explicitly.
For implementation task number `N`, select roster index `(N - 1) mod 4`:

1. `opencode-go/deepseek-v4-pro`
2. `opencode-go/glm-5.2`
3. `opencode-go/mimo-v2.5-pro`
4. `opencode-go/kimi-k2.7-code`

Run every task reviewer at `thinking: high`. A re-review after fixes uses the
same model as the task's initial review; only the next new task advances the
cycle. `task-reviewer`'s MiMo frontmatter is a safe direct-invocation default,
not permission for plan execution to omit the explicit rotating model.

### Task classification and escalation

Tier the task before dispatch:

- Complete code or exact mechanical instructions, limited to 1–2 files:
  `worker-mechanical`.
- Multi-file implementation from an approved prose specification:
  `worker-integration`.
- Broad-codebase implementation of an approved architecture:
  `worker-architecture`.
- Unresolved design, product, or architecture judgment: stop execution and
  return to `planner` or `oracle` before dispatching a worker.

Turn count still beats token price: do not force Flash through prose-spec or
integration work merely because it is cheap. Conversely, do not spend Sol on
routine execution after the design is approved. Children must escalate rather
than silently inventing scope or architecture.

Agent definitions live at
`~/.pi/agent/agents/{worker-mechanical,worker-integration,worker-architecture,task-reviewer}.md`.
Dispatch implementers with a task brief, report path, and scene-setting context;
dispatch task reviewers with the brief, implementer report, and review-package
diff. Preserve TDD, single-writer execution, per-task review, and final
whole-branch review requirements from the active workflow skill.

Always use canonical IDs such as `opencode-go/kimi-k2.7-code`, never ambiguous
bare model IDs. Model-resolution failures must stop the workflow; do not switch
providers or model tiers silently. `opencode models` may under-list gateway
models, so validate availability through Pi's loaded model registry or a direct
gateway probe before changing the approved roster.
```

- [ ] **Step 7: Run focused configuration validation**

Run:

```bash
python -c 'import json, pathlib; p=pathlib.Path.home()/".pi/agent/settings.json"; s=json.loads(p.read_text()); assert (s["defaultProvider"], s["defaultModel"], s["defaultThinkingLevel"]) == ("openai-codex", "gpt-5.6-luna", "max"); o=s["subagents"]["agentOverrides"]; expected={"worker":("openai-codex/gpt-5.6-luna","max"),"delegate":("openai-codex/gpt-5.6-luna","max"),"context-builder":("openai-codex/gpt-5.6-sol","medium"),"oracle":("openai-codex/gpt-5.6-sol","high"),"planner":("openai-codex/gpt-5.6-sol","medium"),"researcher":("openai-codex/gpt-5.6-sol","medium"),"reviewer":("openai-codex/gpt-5.6-sol","high"),"scout":("opencode-go/deepseek-v4-flash","high")}; assert {k:(v["model"],v["thinking"]) for k,v in o.items()} == expected'
```

Expected: exit 0 with no output.

Run:

```bash
python -c 'from pathlib import Path; a=Path.home()/".pi/agent/agents"; expected={"worker-integration.md":("model: openai-codex/gpt-5.6-luna","thinking: max"),"worker-architecture.md":("model: openai-codex/gpt-5.6-luna","thinking: max"),"worker-mechanical.md":("model: opencode-go/deepseek-v4-flash","thinking: high"),"task-reviewer.md":("model: opencode-go/mimo-v2.5-pro","thinking: high")}; [(lambda t,p: (_ for _ in ()).throw(AssertionError(p)) if not all(x in t for x in pairs) else None)((a/p).read_text(),p) for p,pairs in expected.items()]'
```

Expected: exit 0 with no output.

Run:

```bash
pi --list-models | rg '^(openai-codex\s+gpt-5\.6-(luna|sol)|opencode-go\s+(deepseek-v4-(flash|pro)|glm-5\.2|mimo-v2\.5-pro|kimi-k2\.7-code))\b'
```

Expected: exactly seven matching available-model rows.

Run:

```bash
test ! -e /home/kurtt/towpath/.pi/settings.json
```

Expected: exit 0 with no output.

- [ ] **Step 8: Verify Pi subagent discovery and inspect each resolved role**

Call:

```text
subagent({ action: "list" })
```

Expected: `worker`, `delegate`, `planner`, `context-builder`, `researcher`, `oracle`, `reviewer`, `scout`, `worker-mechanical`, `worker-integration`, `worker-architecture`, and `task-reviewer` are executable.

Then call `subagent({ action: "get", agent: "ROLE" })` once for each of those roles. Confirm every resolved `model` and `thinking` value matches the Global Constraints; `task-reviewer` itself must resolve to its MiMo V2.5 Pro High direct-invocation fallback, while `AGENTS.md` requires plan execution to override that fallback with the rotating model. Do not launch model requests merely to test configuration.

- [ ] **Step 9: Review the completed configuration for scope and report evidence**

Run:

```bash
rg -n 'gpt-5\.6-(luna|sol)|deepseek-v4-(flash|pro)|glm-5\.2|mimo-v2\.5-pro|kimi-k2\.7-code|thinking:' ~/.pi/agent/settings.json ~/.pi/agent/AGENTS.md ~/.pi/agent/agents/{worker-integration,worker-architecture,worker-mechanical,task-reviewer}.md
```

Expected: only the approved routing models and effort levels appear in the edited routing sections and agent frontmatter. Report changed files, validation commands with exit codes, all resolved role mappings, and any residual risk. Do not commit unrelated files or modify the dirty `towpath` worktree.
