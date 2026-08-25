# Live setup: pi

**Question.** Is pi's current setup any good, and what should improve?

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
| **pi live local-dgx-montimage-dgx-spark think-ON** | **50.6** | 75.0 % | 67.5 % | 9.6 | 5.9 | 90.9 % | 0 | 326 s |

<sub>**Agent score** = solve rate x efficiency, out of 100 — solving is the price of entry, efficiency breaks the ties solve rate cannot. *Efficiency* = par tool calls / calls actually used, capped at 1 and counted only on solved tasks. *Par* is measured by running each task's oracle, so it does not depend on the model. *Valid calls* = calls that did not error. *Turn-limit* = runs abandoned without finishing.</sub>

```mermaid
xychart-beta
    title "Solve rate (%)"
    x-axis ["montimage-dg ON"]
    y-axis "solved %" 0 --> 100
    bar [75]
```

```mermaid
xychart-beta
    title "Cost of that accuracy — suite wall-clock (s)"
    x-axis ["montimage-dg ON"]
    y-axis "seconds" 0 --> 374.5
    bar [325.6]
```

```mermaid
xychart-beta
    title "Agent score (solve x efficiency, out of 100)"
    x-axis ["montimage-dg ON"]
    y-axis "score" 0 --> 100
    bar [50.64]
```

```mermaid
xychart-beta
    title "Mean tool calls per task (par is the floor)"
    x-axis ["montimage-dg ON"]
    y-axis "calls" 0 --> 11.07
    bar [9.625]
```

```mermaid
xychart-beta
    title "Valid tool-call rate (%)"
    x-axis ["montimage-dg ON"]
    y-axis "%" 0 --> 100
    bar [90.91]
```

```mermaid
xychart-beta
    title "pass@1 by difficulty (%)"
    x-axis ["easy", "medium", "hard"]
    y-axis "pass@1 %" 0 --> 100
    line [0, 0, 75]
```

<sub>Line 1 = pi live local-dgx-montimage-dgx-spark think-ON</sub>

## Suggestions — pi live local-dgx-montimage-dgx-spark think-ON

- Mean input tokens is **141,928 per task** — context is being resent every turn. In a live setup, audit installed **skills and MCP servers**: each one's prompt/schema rides along on every call even when unused. Disable what this work does not need.
- Tasks use **9.6 tool calls against a par of 5.9**. In a live setup, verbose skills or an over-eager MCP server can push the agent into exploratory calls; trimming instructions usually recovers most of the gap.
- This was a **live-mode** run of your daily setup: extensions, skills and MCP servers were enabled. Any component that can call another model contaminates these numbers — see the caveats section.

## Caveats

- 1 samples per task. Differences under ~8 points are noise, not signal.
- Multi-turn agentic tool use against a sandboxed workspace. One-shot code generation is not exercised here.
- Success is decided by a predicate over the final workspace, never by what the model claims. Every task's oracle is verified to solve it first.
- A task abandoned at the turn limit counts as failed; raise `--max-turns` before concluding the model cannot do it.

## Raw data

- `pi-live-local-dgx-montimage-dgx-spark-think-on.json` — pi live local-dgx-montimage-dgx-spark think-ON
