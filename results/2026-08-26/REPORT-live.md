# Live setup: opencode

**Question.** Is opencode's current setup any good, and what should improve?

## Setup

| | |
|---|---|
| Endpoint | not recorded |
| Tasks | 8 |
| Samples per task | 1 (⇒ 8 generations per run) |
| Concurrency | 2 |
| Metric | pass@1 over hidden executable unit tests |

## Results

| Run | Agent score | Solved | Efficiency | Mean calls | Par | Valid calls | Turn-limit | Wall |
|---|---|---|---|---|---|---|---|---|
| **opencode live opencode-muse-spark-1-2-contributor-free think-OFF** | **44.1** | 87.5 % | 50.4 % | 11.9 | 5.9 | 97.9 % | 0 | 1,054 s |

<sub>**Agent score** = solve rate x efficiency, out of 100 — solving is the price of entry, efficiency breaks the ties solve rate cannot. *Efficiency* = par tool calls / calls actually used, capped at 1 and counted only on solved tasks. *Par* is measured by running each task's oracle, so it does not depend on the model. *Valid calls* = calls that did not error. *Turn-limit* = runs abandoned without finishing.</sub>

```mermaid
xychart-beta
    title "Solve rate (%)"
    x-axis ["muse-spark-1 OFF"]
    y-axis "solved %" 0 --> 100
    bar [87.5]
```

```mermaid
xychart-beta
    title "Cost of that accuracy — suite wall-clock (s)"
    x-axis ["muse-spark-1 OFF"]
    y-axis "seconds" 0 --> 1212
    bar [1054]
```

```mermaid
xychart-beta
    title "Agent score (solve x efficiency, out of 100)"
    x-axis ["muse-spark-1 OFF"]
    y-axis "score" 0 --> 100
    bar [44.12]
```

```mermaid
xychart-beta
    title "Mean tool calls per task (par is the floor)"
    x-axis ["muse-spark-1 OFF"]
    y-axis "calls" 0 --> 13.66
    bar [11.88]
```

```mermaid
xychart-beta
    title "Valid tool-call rate (%)"
    x-axis ["muse-spark-1 OFF"]
    y-axis "%" 0 --> 100
    bar [97.89]
```

```mermaid
xychart-beta
    title "pass@1 by difficulty (%)"
    x-axis ["easy", "medium", "hard"]
    y-axis "pass@1 %" 0 --> 100
    line [0, 0, 87.5]
```

<sub>Line 1 = opencode live opencode-muse-spark-1-2-contributor-free think-OFF</sub>

## Suggestions — opencode live opencode-muse-spark-1-2-contributor-free think-OFF

- Tasks use **11.9 tool calls against a par of 5.9**. In a live setup, verbose skills or an over-eager MCP server can push the agent into exploratory calls; trimming instructions usually recovers most of the gap.
- This was a **live-mode** run of your daily setup: extensions, skills and MCP servers were enabled. Any component that can call another model contaminates these numbers — see the caveats section.

## Caveats

- 1 samples per task. Differences under ~8 points are noise, not signal.
- Multi-turn agentic tool use against a sandboxed workspace. One-shot code generation is not exercised here.
- Success is decided by a predicate over the final workspace, never by what the model claims. Every task's oracle is verified to solve it first.
- A task abandoned at the turn limit counts as failed; raise `--max-turns` before concluding the model cannot do it.

## Raw data

- `opencode-live-opencode-muse-spark-1-2-contributor-free-think-off.json` — opencode live opencode-muse-spark-1-2-contributor-free think-OFF
## Run context

_Collected at 2026-08-26 13:36 UTC — the conditions this result must be read against._

### Machine

| Field | Value |
|---|---|
| host | omachi |
| os | Omarchy 7.1.8-arch1-3 (x86_64) |
| cpu | Intel(R) Core(TM) i7-4578U CPU @ 3.00GHz — 4 threads |
| memory | 8 GiB, 4 GiB free at start |
| disk | 64G free on /home |
| load avg | 1.58 0.67 0.26 |

### GPU

No `nvidia-smi` — GPU unknown. On a hosted model this is expected and harmless;
on a local endpoint it means the serving device was not recorded.

### Serving endpoint

| Field | Value |
|---|---|
| base url | http://localhost:8001/v1 |
| serves | not reachable (hosted model, or nothing local is serving) |
| unit | inactive |

### Harness setup

A live run measures this surface, not the model alone. Every skill, MCP server and
extension below is part of the result.

| Field | Value |
|---|---|
| harness | opencode |
| model | opencode/muse-spark-1.2-contributor-free |
| thinking | n/a |
| version | 1.18.21 |
| config | /home/omachi/.config/opencode/opencode.json |
| plugins | 1 in ~/.config/opencode/plugins |
| skills | 42 global |
| project context | CLAUDE.md AGENTS.md  |
## Surface usage

_95 tool calls, classified. Built-ins identified from the isolated arm._

| Kind | What | Calls |
|---|---|---|
| builtin | `read` | 52 |
| builtin | `bash` | 32 |
| builtin | `edit` | 9 |
| builtin | `write` | 2 |

Installed vs called:

- **skills installed**: 42 global
- **plugins installed**: 1 in ~/.config/opencode/plugins

**The surface was idle.** Every call in this run was a built-in: no skill, MCP server or plugin was invoked. Whatever this run scored, the surface did not earn it — and anything it adds to the system prompt was paid for on every task for nothing.

## Surface A/B — live vs isolated

Same model, same suite, same samples. The live arm runs your daily surface; the isolated arm strips skills, MCP servers, plugins and settings.

| Metric | live | isolated | delta |
|---|---|---|---|
| agent score | 44.1 | 56.2 | -12.1 ✗ |
| solve rate % | 87.5 | 100.0 | -12.5 ✗ |
| efficiency % | 50.4 | 56.2 | -5.8 ✗ |
| calls / task | 11.9 | 11.6 | +0.2 ✗ |
| turns / task | 9.4 | 8.9 | +0.5 ✗ |
| input tok / task | 20649 | 29236 | -8588 ✓ |
| output tok / task | 1902 | 1758 | +144 ✗ |
| wall (s) | 1054 | 461 | +592 ✗ |

The **isolated** arm is ahead by 12.1 points at 1 sample(s) — above the 8-point noise floor, so the gap is real. Read it together with the surface usage above: a gap with an idle surface is not caused by the surface.

Caveat: on claude-code the isolated arm also pins the built-in tool set (no Task/WebSearch/WebFetch), so its arm differs by more than the surface alone. `references/surface-ab.md` lists what each harness strips.
