# Surface A/B — measuring what your skills and MCP servers are worth

A live run enables the whole daily surface — skills, MCP servers, plugins, settings,
context files — and folds all of it into one agent score. That score cannot answer the
question people actually have: **is any of this earning its keep?**

Two things separate "the surface helped" from "the surface sat there":

1. **The A/B** (`--ab`) — run the same model, suite and samples twice, once live and once
   isolated, and diff them.
2. **The usage attribution** (`scripts/surface_usage.py`) — classify every tool call in a
   run as built-in, MCP, skill or plugin, so an idle surface is visible as idle.

Neither is meaningful without the other. A live arm can win by 10 points with a surface
that was never invoked — in which case the surface did not cause the win, and reporting it
that way is a fabrication.

## What each arm is

| | live arm — `bench setup run` | isolated arm — `bench harness run` |
|---|---|---|
| skills / MCP / plugins | on | stripped |
| settings, context files | on | stripped |
| answers | "is my setup any good?" | "how good is this model?" |
| extra output | `REPORT-live.md` | result JSON only |

Both commands take identical flags, which is what makes the A/B honest: the arms differ in
isolation and nothing else. Pass the **same** `-m`, `--suite`, `--samples`, `--concurrency`
and `--thinking` to each, or you are measuring two things at once.

## What each harness actually strips

Isolation is per-adapter, and the arms are not equally clean:

| Harness | Isolation flags dropped in live mode | Clean A/B? |
|---|---|---|
| pi | `--no-extensions`, `--no-context-files` | yes — extensions and context only |
| opencode | `--pure` | yes — all-or-nothing, but only the surface |
| claude-code | `--bare`, `--disable-slash-commands`, `--strict-mcp-config`, `--mcp-config '{}'`, `--setting-sources ""` | **no** — see below |

**claude-code's isolated arm also pins the built-in tool set.** `benchkit/harness/claudecode.py`
sets `self.tools = [] if self.live else list(DEFAULT_TOOLS)`, and `DEFAULT_TOOLS` excludes
`Task`, `WebSearch` and `WebFetch` — deliberately, since subagents and web access can reach
other models and contaminate a measurement. So a claude-code isolated arm loses the surface
*and* three built-in tools. A delta on claude-code is an upper bound on the surface's
contribution, not a measurement of it. Say so when reporting; never present it as the
surface alone.

The exact flags each adapter drops are recorded per run in the result JSON at
`summary.harness.disabled_isolation` — read them from there rather than trusting this
table, which can go stale.

## How tool calls are attributed

`surface_usage.py` classifies every name in each result's `trace` array:

| Kind | Rule |
|---|---|
| `mcp` | name matches `mcp__<server>__<tool>` — the server is in the name |
| `skill` | name is `Skill`, `skill` or `SlashCommand` |
| `builtin` | see below |
| `surface` | ran in the live arm, never in the isolated arm |
| `unattributed` | unrecognised, and no isolated arm to check against |

**With an isolated arm, built-ins are derived, not assumed.** Isolation strips skills, MCP
and plugins, so any tool the isolated arm called is a built-in by demonstration. Anything
the live arm called that the isolated arm never did is attributable to the surface. This
needs no allowlist and cannot go stale when a harness adds a tool.

**Without an isolated arm**, the script falls back to a static per-harness table of
built-in names (`BUILTIN` in the script). That table is a guess about someone else's
product, so a name missing from it is reported as `unattributed` — never as a skill.
Prefer the A/B when the attribution matters.

## The gap: which skill fired

On claude-code a skill invocation appears in the trace as the tool name `Skill`. **Which**
skill it was lives in the tool call's `input`, and benchkit does not keep it —
`claudecode.py:322` records `block.get("name")` and discards the rest, and `raw_log` is
never written to the result JSON. So skill invocations are **counted, not named**.

Report it that way. "3 skill invocations, names not recorded" is true; naming a skill you
inferred from context is not. Closing the gap is a two-line benchkit change (record
`Skill:<name>` from the tool input) and belongs in benchkit with its own tests, not here.

pi extensions and opencode plugins do not have this problem: their tools appear under their
own names, so the A/B attributes them by name.

## Reading the delta

- **Under 8 points is noise** at 1–2 samples — the repo-wide rule, and it applies here
  twice over, since an A/B compares two noisy numbers. The script says so and asks for more
  samples rather than declaring a winner.
- **An idle surface explains nothing.** If the usage section says zero skill/MCP calls, the
  delta is caused by something else: prompt-token overhead, context files, run-to-run
  variance. Say that plainly.
- **Prompt cost is the surface's floor.** `input tok / task` is where an unused surface
  shows up: tokens paid on every task for tools nobody called. A live arm that scores the
  same as isolated but costs 12k more input tokens per task has a negative result, not a
  neutral one.
- **Wall-clock is not comparable across arms on a contended GPU.** Check the GPU rows in
  the run context before reading the wall delta as anything.

## Cost

Two arms is twice the wall-clock and twice the billing. The confirm gate shows the doubled
estimate before either arm starts, and `--ab` is opt-in for that reason — the single live
arm stays the default.
