# Live setup: opencode

**Question.** Is opencode's current setup any good, and what should improve?

## Setup

| | |
|---|---|
| Endpoint | not recorded |
| Tasks | 8 |
| Samples per task | 4 (⇒ 32 generations per run) |
| Concurrency | 2 |
| Metric | pass@1 over hidden executable unit tests |

## Results

| Run | Agent score | Solved | Efficiency | Mean calls | Par | Valid calls | Turn-limit | Wall |
|---|---|---|---|---|---|---|---|---|
| **opencode live opencode-x-preview-f-free think-OFF** | **75.5** | 100.0 % | 75.5 % | 8.2 | 5.9 | 100.0 % | 0 | 1,392 s |

<sub>**Agent score** = solve rate x efficiency, out of 100 — solving is the price of entry, efficiency breaks the ties solve rate cannot. *Efficiency* = par tool calls / calls actually used, capped at 1 and counted only on solved tasks. *Par* is measured by running each task's oracle, so it does not depend on the model. *Valid calls* = calls that did not error. *Turn-limit* = runs abandoned without finishing.</sub>

```mermaid
xychart-beta
    title "Solve rate (%)"
    x-axis ["x-preview-f- OFF"]
    y-axis "solved %" 0 --> 100
    bar [100]
```

```mermaid
xychart-beta
    title "Cost of that accuracy — suite wall-clock (s)"
    x-axis ["x-preview-f- OFF"]
    y-axis "seconds" 0 --> 1601
    bar [1392]
```

```mermaid
xychart-beta
    title "Agent score (solve x efficiency, out of 100)"
    x-axis ["x-preview-f- OFF"]
    y-axis "score" 0 --> 100
    bar [75.48]
```

```mermaid
xychart-beta
    title "Mean tool calls per task (par is the floor)"
    x-axis ["x-preview-f- OFF"]
    y-axis "calls" 0 --> 9.416
    bar [8.188]
```

```mermaid
xychart-beta
    title "Valid tool-call rate (%)"
    x-axis ["x-preview-f- OFF"]
    y-axis "%" 0 --> 100
    bar [100]
```

```mermaid
xychart-beta
    title "pass@1 by difficulty (%)"
    x-axis ["easy", "medium", "hard"]
    y-axis "pass@1 %" 0 --> 100
    line [0, 0, 100]
```

<sub>Line 1 = opencode live opencode-x-preview-f-free think-OFF</sub>

## Suggestions — opencode live opencode-x-preview-f-free think-OFF

- This was a **live-mode** run of your daily setup: extensions, skills and MCP servers were enabled. Any component that can call another model contaminates these numbers — see the caveats section.

## Caveats

- 4 samples per task. Differences under ~8 points are noise, not signal.
- Multi-turn agentic tool use against a sandboxed workspace. One-shot code generation is not exercised here.
- Success is decided by a predicate over the final workspace, never by what the model claims. Every task's oracle is verified to solve it first.
- A task abandoned at the turn limit counts as failed; raise `--max-turns` before concluding the model cannot do it.

## Raw data

- `opencode-live-opencode-x-preview-f-free-think-off.1.json` — opencode live opencode-x-preview-f-free think-OFF
## Run context

_Collected at 2026-08-25 15:49 UTC — the conditions this result must be read against._

### Machine

| Field | Value |
|---|---|
| host | dgx-spark |
| os | Ubuntu 24.04.3 LTS 6.14.0-1013-nvidia (aarch64) |
| cpu | Cortex-X925 — 20 threads |
| memory | 120 GiB, 36 GiB free at start |
| disk | 2.7T free on / |
| load avg | 0.50 0.32 0.50 |

### GPU

| Field | Value |
|---|---|
| gpu | NVIDIA GB10 |
| vram | unified with host memory — see the memory row above |
| util | 0 % at start |
| driver | 580.95.05, CUDA 13.0 |

**Other GPU processes at start** — anything here shares the device with the run,
and a contended GPU makes wall-clock and turn counts incomparable:

```
18459, VLLM::EngineCore, 73249 MiB
```

### Serving endpoint

| Field | Value |
|---|---|
| base url | http://localhost:8001/v1 |
| serves | montimage-dgx-spark, unsloth/Qwen3.6-35B-A3B-NVFP4 |
| unit | active |

### Harness setup

A live run measures this surface, not the model alone. Every skill, MCP server and
extension below is part of the result.

| Field | Value |
|---|---|
| harness | opencode |
| model | opencode/x-preview-f-free |
| thinking | n/a |
| version | 1.18.23 |
| config | /home/montimage/.config/opencode/opencode.json |
| plugins | 1 in ~/.config/opencode/plugins |
| skills | 112 global |
| project context | CLAUDE.md AGENTS.md  |
