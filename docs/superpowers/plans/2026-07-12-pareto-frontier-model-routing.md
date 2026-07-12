# Pareto-Frontier Pi Model Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply the approved Pareto-frontier model routing policy to all new Pi sessions, preserve diverse task reviews with Luna xhigh added, and update the repository's routing documentation.

**Architecture:** User-wide behavior lives in `~/.pi/agent/settings.json`, custom agent frontmatter, and `~/.pi/agent/AGENTS.md`; these files are loaded independently of the current repository. The repository stores the provider-neutral frontier registry and the design/plan documentation that explains the policy. The pinned `kthorn-skills` checkout remains unchanged because its defaults are a separately published-package concern.

**Tech Stack:** Pi JSON settings, Pi agent Markdown frontmatter, Markdown documentation, CSV metadata, Python 3 validation commands, Git worktree.

## Global Constraints

- Use canonical provider-qualified model IDs and explicit thinking levels on every configured or dispatched subagent.
- Use the cheapest Pareto-frontier point capable of each role.
- Set the global default to `openai-codex/gpt-5.6-luna` with `thinking: high`.
- Route `worker` and `delegate` to `opencode-go/mimo-v2.5-pro` with `thinking: high`.
- Route `worker-mechanical` and `scout` to `opencode-go/deepseek-v4-flash` with `thinking: max`.
- Route `worker-integration` to `openai-codex/gpt-5.6-luna` with `thinking: xhigh`.
- Route `worker-architecture` to `openai-codex/gpt-5.6-luna` with `thinking: max`.
- Route `context-builder` to `openai-codex/gpt-5.6-sol` with `thinking: low`.
- Route `planner` and `researcher` to `openai-codex/gpt-5.6-sol` with `thinking: medium`.
- Route `oracle` to `openai-codex/gpt-5.6-sol` with `thinking: high`.
- Route final whole-branch `reviewer` to `openai-codex/gpt-5.6-sol` with `thinking: xhigh`.
- Preserve the diverse review roster and append `openai-codex/gpt-5.6-luna` at `thinking: xhigh` as entry five.
- Select review entry `(N - 1) mod 5` for new task number `N`; retain the original entry on re-review.
- Keep direct `task-reviewer` fallback at `opencode-go/mimo-v2.5-pro` with `thinking: high`.
- Do not create `/home/kurtt/towpath/.pi/settings.json` or modify project application code.
- Do not modify the dirty current worktree's unrelated files.
- Do not update or publish the pinned `kthorn-skills` package in this task.

---

## File map

| File | Responsibility |
| --- | --- |
| `docs/pi-model-frontier.csv` | Provider-neutral cost/score metadata for the approved frontier. |
| `docs/superpowers/specs/2026-07-12-global-pi-model-routing-design.md` | Committed design record for the user-wide routing policy. |
| `docs/superpowers/plans/2026-07-12-global-pi-model-routing.md` | Historical implementation plan; update its model values and validation expectations so it does not describe obsolete routing. |
| `~/.pi/agent/settings.json` | User-wide Pi default and builtin-agent overrides. |
| `~/.pi/agent/agents/worker-mechanical.md` | Direct invocation default for mechanical implementation. |
| `~/.pi/agent/agents/worker-integration.md` | Direct invocation default for prose-spec integration implementation. |
| `~/.pi/agent/agents/worker-architecture.md` | Direct invocation default for approved broad architecture execution. |
| `~/.pi/agent/agents/task-reviewer.md` | Direct invocation fallback for per-task review. |
| `~/.pi/agent/AGENTS.md` | User-wide orchestration contract and five-entry review rotation. |

---

### Task 1: Add the frontier registry and update committed routing documentation

**Files:**

- Create: `docs/pi-model-frontier.csv`
- Modify: `docs/superpowers/specs/2026-07-12-global-pi-model-routing-design.md`
- Modify: `docs/superpowers/plans/2026-07-12-global-pi-model-routing.md`

**Interfaces:**

- Consumes: approved routing design at `docs/superpowers/specs/2026-07-12-pareto-frontier-model-routing-design.md`.
- Produces: repository documentation that names the same canonical IDs, effort levels, frontier costs/scores, role mappings, and five-entry review rotation as the user-wide configuration.

- [ ] **Step 1: Add the provider-neutral frontier registry**

Create `docs/pi-model-frontier.csv` with exactly this content:

```csv
label,provider_model_id,thinking,cost,score
DeepSeek V4 Flash,opencode-go/deepseek-v4-flash,max,0.03,56
MiMo V2.5 Pro,opencode-go/mimo-v2.5-pro,high,0.04,60
GPT-5.6 Luna,openai-codex/gpt-5.6-luna,high,0.09,63
GPT-5.6 Luna,openai-codex/gpt-5.6-luna,xhigh,0.10,69
GPT-5.6 Sol,openai-codex/gpt-5.6-sol,low,0.13,70
GPT-5.6 Luna,openai-codex/gpt-5.6-luna,max,0.16,71
GPT-5.6 Sol,openai-codex/gpt-5.6-sol,medium,0.18,76
GPT-5.6 Sol,openai-codex/gpt-5.6-sol,high,0.22,77
GPT-5.6 Sol,openai-codex/gpt-5.6-sol,xhigh,0.30,78
```

- [ ] **Step 2: Update the committed design's model and review sections**

In `docs/superpowers/specs/2026-07-12-global-pi-model-routing-design.md`:

1. Change the goal from Luna Max routine execution to the Pareto-frontier routing policy.
2. Replace the role table with these exact mappings:

```markdown
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
```

1. Replace the four-entry review roster with:

```markdown
1. `opencode-go/deepseek-v4-pro` at `high`
2. `opencode-go/glm-5.2` at `high`
3. `opencode-go/mimo-v2.5-pro` at `high`
4. `opencode-go/kimi-k2.7-code` at `high`
5. `openai-codex/gpt-5.6-luna` at `xhigh`
```

1. Change the rotation modulus from `4` to `5` and state that each dispatch passes both model and thinking explicitly.
2. Add a reference to `docs/pi-model-frontier.csv` and state that the pinned `kthorn-skills` checkout is intentionally outside this change.

- [ ] **Step 3: Update the historical routing plan's binding values**

In `docs/superpowers/plans/2026-07-12-global-pi-model-routing.md`, update the `Goal`, `Architecture`, and `Global Constraints` sections to exactly match Task 1 Step 2's role table and five-entry roster. Update its validation commands so they expect:

```text
openai-codex/gpt-5.6-luna at high as the global default
opencode-go/deepseek-v4-flash at max for scout and worker-mechanical
opencode-go/mimo-v2.5-pro at high for worker and delegate
openai-codex/gpt-5.6-luna at xhigh for worker-integration
openai-codex/gpt-5.6-luna at max for worker-architecture
openai-codex/gpt-5.6-sol at low for context-builder
openai-codex/gpt-5.6-sol at medium for planner and researcher
openai-codex/gpt-5.6-sol at high for oracle
openai-codex/gpt-5.6-sol at xhigh for reviewer
```

Preserve its warning that global settings and agent files are user-wide and cannot be committed from this repository. Do not edit unrelated plan documents.

- [ ] **Step 4: Validate the documentation artifacts**

Run:

```bash
python - <<'PY'
import csv
from pathlib import Path

path = Path("docs/pi-model-frontier.csv")
rows = list(csv.DictReader(path.open(newline="")))
assert len(rows) == 9
assert {(row["provider_model_id"], row["thinking"]) for row in rows} == {
    ("opencode-go/deepseek-v4-flash", "max"),
    ("opencode-go/mimo-v2.5-pro", "high"),
    ("openai-codex/gpt-5.6-luna", "high"),
    ("openai-codex/gpt-5.6-luna", "xhigh"),
    ("openai-codex/gpt-5.6-sol", "low"),
    ("openai-codex/gpt-5.6-luna", "max"),
    ("openai-codex/gpt-5.6-sol", "medium"),
    ("openai-codex/gpt-5.6-sol", "high"),
    ("openai-codex/gpt-5.6-sol", "xhigh"),
}
PY

git diff --check
rg -n 'gpt-5\.6-(luna|sol)|deepseek-v4-flash|mimo-v2\.5-pro|deepseek-v4-pro|glm-5\.2|kimi-k2\.7-code|mod 5' docs/pi-model-frontier.csv docs/superpowers/specs/2026-07-12-global-pi-model-routing-design.md docs/superpowers/plans/2026-07-12-global-pi-model-routing.md
```

Expected: the Python check exits 0, `git diff --check` emits no errors, and all nine frontier rows plus the five review IDs appear.

- [ ] **Step 5: Commit the repository documentation**

```bash
git add docs/pi-model-frontier.csv docs/superpowers/specs/2026-07-12-global-pi-model-routing-design.md docs/superpowers/plans/2026-07-12-global-pi-model-routing.md
git commit -m "docs: update Pareto frontier model routing"
```

---

### Task 2: Apply the user-wide Pi settings and agent defaults

**Files:**

- Modify: `/home/kurtt/.pi/agent/settings.json`
- Modify: `/home/kurtt/.pi/agent/agents/worker-mechanical.md`
- Modify: `/home/kurtt/.pi/agent/agents/worker-integration.md`
- Modify: `/home/kurtt/.pi/agent/agents/worker-architecture.md`
- Verify unchanged contract: `/home/kurtt/.pi/agent/agents/task-reviewer.md`

**Interfaces:**

- Consumes: the canonical IDs and thinking levels from Task 1.
- Produces: user-wide defaults used by every new Pi session and direct agent invocation, regardless of current working directory.

- [ ] **Step 1: Capture the pre-change configuration and prove the old policy is present**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

settings = json.loads((Path.home() / ".pi/agent/settings.json").read_text())
assert settings["defaultThinkingLevel"] == "max"
assert settings["subagents"]["agentOverrides"]["worker"]["model"] == "openai-codex/gpt-5.6-luna"
assert settings["subagents"]["agentOverrides"]["scout"]["thinking"] == "high"
PY
```

Expected: exit 0 before the update, documenting that the old routing is the reproducible precondition.

- [ ] **Step 2: Update only the routing fields in global settings**

Preserve `lastChangelogVersion`, `hideThinkingBlock`, `skills`, `packages`, and `theme` exactly. Set these fields:

```json
{
  "defaultProvider": "openai-codex",
  "defaultModel": "gpt-5.6-luna",
  "defaultThinkingLevel": "high",
  "subagents": {
    "agentOverrides": {
      "worker": { "model": "opencode-go/mimo-v2.5-pro", "thinking": "high" },
      "delegate": { "model": "opencode-go/mimo-v2.5-pro", "thinking": "high" },
      "context-builder": { "model": "openai-codex/gpt-5.6-sol", "thinking": "low" },
      "oracle": { "model": "openai-codex/gpt-5.6-sol", "thinking": "high" },
      "planner": { "model": "openai-codex/gpt-5.6-sol", "thinking": "medium" },
      "researcher": { "model": "openai-codex/gpt-5.6-sol", "thinking": "medium" },
      "reviewer": { "model": "openai-codex/gpt-5.6-sol", "thinking": "xhigh" },
      "scout": { "model": "opencode-go/deepseek-v4-flash", "thinking": "max" }
    }
  }
}
```

- [ ] **Step 3: Update direct-invocation agent frontmatter**

Make these exact frontmatter pairs present:

```text
/home/kurtt/.pi/agent/agents/worker-mechanical.md
model: opencode-go/deepseek-v4-flash
thinking: max

/home/kurtt/.pi/agent/agents/worker-integration.md
model: openai-codex/gpt-5.6-luna
thinking: xhigh

/home/kurtt/.pi/agent/agents/worker-architecture.md
model: openai-codex/gpt-5.6-luna
thinking: max

/home/kurtt/.pi/agent/agents/task-reviewer.md
model: opencode-go/mimo-v2.5-pro
thinking: high
```

Update the opening descriptions of the three worker files so they name the same model/effort pair. Leave `task-reviewer`'s review contract unchanged.

- [ ] **Step 4: Validate the user-wide configuration before changing the global contract**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

settings = json.loads((Path.home() / ".pi/agent/settings.json").read_text())
assert (settings["defaultProvider"], settings["defaultModel"], settings["defaultThinkingLevel"]) == (
    "openai-codex", "gpt-5.6-luna", "high"
)
expected = {
    "worker": ("opencode-go/mimo-v2.5-pro", "high"),
    "delegate": ("opencode-go/mimo-v2.5-pro", "high"),
    "context-builder": ("openai-codex/gpt-5.6-sol", "low"),
    "oracle": ("openai-codex/gpt-5.6-sol", "high"),
    "planner": ("openai-codex/gpt-5.6-sol", "medium"),
    "researcher": ("openai-codex/gpt-5.6-sol", "medium"),
    "reviewer": ("openai-codex/gpt-5.6-sol", "xhigh"),
    "scout": ("opencode-go/deepseek-v4-flash", "max"),
}
actual = {name: (value["model"], value["thinking"]) for name, value in settings["subagents"]["agentOverrides"].items()}
assert actual == expected

agent_dir = Path.home() / ".pi/agent/agents"
frontmatter = {
    "worker-mechanical.md": ("opencode-go/deepseek-v4-flash", "max"),
    "worker-integration.md": ("openai-codex/gpt-5.6-luna", "xhigh"),
    "worker-architecture.md": ("openai-codex/gpt-5.6-luna", "max"),
    "task-reviewer.md": ("opencode-go/mimo-v2.5-pro", "high"),
}
for filename, (model, thinking) in frontmatter.items():
    text = (agent_dir / filename).read_text()
    assert f"model: {model}" in text
    assert f"thinking: {thinking}" in text
PY
```

Expected: exit 0 with no output.

---

### Task 3: Replace the global orchestration contract and review rotation

**Files:**

- Modify: `/home/kurtt/.pi/agent/AGENTS.md`

**Interfaces:**

- Consumes: Task 1's role table and review roster; Task 2's configured defaults.
- Produces: instructions that every Pi session loads from the user's home directory, independent of repository.

- [ ] **Step 1: Replace the existing model-routing section**

Replace the section beginning at `## Subagent-Driven Development: global model routing` through the end of `/home/kurtt/.pi/agent/AGENTS.md` with:

```markdown
## Subagent-Driven Development: global model routing

Use role-based routing for every subagent dispatch. Always pass the canonical
`provider/model` ID and `thinking` level explicitly; do not rely on parent-model
inheritance or silently substitute a fallback.

| Work | Agent | Model | Thinking |
|------|-------|-------|----------|
| Planning and implementation plans | `planner` | `openai-codex/gpt-5.6-sol` | medium |
| Context building | `context-builder` | `openai-codex/gpt-5.6-sol` | low |
| Research | `researcher` | `openai-codex/gpt-5.6-sol` | medium |
| Architecture advice and decision consistency | `oracle` | `openai-codex/gpt-5.6-sol` | high |
| Final whole-branch review | `reviewer` | `openai-codex/gpt-5.6-sol` | xhigh |
| Routine implementation | `worker`, `delegate` | `opencode-go/mimo-v2.5-pro` | high |
| Multi-file prose-spec implementation | `worker-integration` | `openai-codex/gpt-5.6-luna` | xhigh |
| Broad-codebase execution of an approved design | `worker-architecture` | `openai-codex/gpt-5.6-luna` | max |
| Mechanical transcription/testing and bounded scouting | `worker-mechanical`, `scout` | `opencode-go/deepseek-v4-flash` | max |

The global interactive default is GPT-5.6 Luna High. MiMo Pro handles routine
implementation at lower cost. Luna xhigh and max handle progressively harder
approved execution. Sol low is sufficient for context assembly; Sol medium,
high, and xhigh are reserved for progressively more demanding planning,
advisory, and final-review work.

### Per-task review rotation

Use the shared `task-reviewer` contract, but pass the selected model and thinking
level explicitly. For implementation task number `N`, select roster index
`(N - 1) mod 5`:

1. `opencode-go/deepseek-v4-pro` at `high`
2. `opencode-go/glm-5.2` at `high`
3. `opencode-go/mimo-v2.5-pro` at `high`
4. `opencode-go/kimi-k2.7-code` at `high`
5. `openai-codex/gpt-5.6-luna` at `xhigh`

A re-review after fixes uses the same model and thinking level as the original
task review; only the next new task advances the cycle. The direct
`task-reviewer` fallback remains MiMo V2.5 Pro High, but plan execution must
override it with the selected roster entry.

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

- [ ] **Step 2: Validate the global contract text**

Run:

```bash
rg -n 'gpt-5\.6-(luna|sol)|deepseek-v4-(flash|pro)|mimo-v2\.5-pro|glm-5\.2|kimi-k2\.7-code|mod 5|Thinking' /home/kurtt/.pi/agent/AGENTS.md
```

Expected: all role mappings use the approved canonical IDs and effort levels; the review modulus is `5`; no obsolete `qwen3.6-plus` or `kimi-k2.6` appears in the routing section.

---

### Task 4: Verify global availability and cross-repository scope

**Files:**

- Verify: `/home/kurtt/.pi/agent/settings.json`
- Verify: `/home/kurtt/.pi/agent/AGENTS.md`
- Verify: `/home/kurtt/.pi/agent/agents/*.md`
- Verify: `/home/kurtt/towpath/.pi/settings.json` is absent
- Verify: `/tmp` can see the global package/model configuration without loading this repository's files

**Interfaces:**

- Consumes: Tasks 1–3's registry, settings, agent defaults, and global contract.
- Produces: evidence that the routing is user-wide and applies to new sessions outside `/home/kurtt/towpath`.

- [ ] **Step 1: Confirm every selected model is exposed by Pi**

Run from outside the repository:

```bash
cd /tmp
pi --list-models | rg '^(openai-codex\s+gpt-5\.6-(luna|sol)|opencode-go\s+(deepseek-v4-flash|mimo-v2\.5-pro|deepseek-v4-pro|glm-5\.2|kimi-k2\.7-code))\b'
```

Expected: rows for `gpt-5.6-luna`, `gpt-5.6-sol`, `deepseek-v4-flash`, `mimo-v2.5-pro`, `deepseek-v4-pro`, `glm-5.2`, and `kimi-k2.7-code`.

- [ ] **Step 2: Confirm package and project scope**

Run from `/tmp`:

```bash
cd /tmp
pi list
```

Expected: the user packages, including the pinned `git:github.com/kthorn/kthorn-skills@88d462f9a06290640bd9bed440b44be3bf223496`, are listed. Then run:

```bash
test ! -e /home/kurtt/towpath/.pi/settings.json
```

Expected: exit 0.

- [ ] **Step 3: Confirm no pinned package mutation occurred**

Run:

```bash
git -C /home/kurtt/.pi/agent/git/github.com/kthorn/kthorn-skills status --short --branch
git -C /home/kurtt/.pi/agent/git/github.com/kthorn/kthorn-skills rev-parse HEAD
```

Expected: the checkout remains at commit `88d462f9a06290640bd9bed440b44be3bf223496`; only its pre-existing untracked `package-lock.json` may appear.

- [ ] **Step 4: Run final repository and configuration checks**

Run in the implementation worktree:

```bash
git diff --check
git status --short
```

Run globally:

```bash
python -m json.tool /home/kurtt/.pi/agent/settings.json >/dev/null
```

Expected: all commands exit 0. The repository status contains only the intended documentation commit relative to its worktree base, and the current `/home/kurtt/towpath` dirty files remain untouched.

- [ ] **Step 5: Record the global configuration effect**

Report that the settings apply to new Pi sessions from any working directory. An already-running Pi process retains its current model and must be restarted or switched manually to observe the new defaults.

---

## Integration handoff

After Tasks 1–4 pass in the isolated worktree:

```bash
git log -1 --format='%H %s'
git status --short
```

Cherry-pick only the documentation commit onto the user's current branch; do not stage or commit its unrelated dirty files. The global files under `~/.pi/agent/` are intentionally outside Git and remain applied in place.
