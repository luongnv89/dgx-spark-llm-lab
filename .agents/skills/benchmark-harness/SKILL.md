---
name: benchmark-harness
description: "Evaluate the coding harness you are running inside (pi, opencode, claude-code) on its live setup and current model, via bench setup run. Use when the user runs /benchmark-harness. Not for serving sweeps, model compare, or one-shot suites."
license: MIT
effort: high
metadata:
  version: 1.3.0
  author: "Luong NGUYEN <luongnv89@gmail.com>"
  architecture: "inline (single agent, no subagents)"
---

# Benchmark Harness

Measure **this** harness — the one whose shell you are running in — exactly as it is
configured right now, and report what to improve. Wraps `./bench setup run` from
`dgx-spark-llm-lab` (issue #76).

## Start here

**Reading this text is the invocation.** Some harnesses inject a skill body with no user
turn attached; never read that absence as "they have not asked yet", and never reply that
you are ready when they are. Begin at step 1 now.

Run **steps 1–4 immediately** — cheap, read-only, seconds: locate the repo, prove the
oracles, detect harness and model, record the conditions, print the plan. Then **stop at
the confirm gate** in step 4. That gate, not this section, protects the user from a 15–40
minute run.

Exception: the user's message contradicts the plan ("just tell me what you would run",
`--dry-run`). Stop after step 4 and say so.

## When to use

This skill is **user-invoked**: `/benchmark-harness`, or a request to benchmark "this
harness", "my current setup", "the agent I'm in". Do not apply it, unprompted, to an
adjacent request that merely mentions benchmarking.

Not this skill: `bench compare` (two models head-to-head), `bench sweep` (serving-config
matrix), `bench run` (one-shot suites through benchkit's own loop), `bench apply`
(installing a serving config).

## Prerequisites

Check these in step 1; each failure stops the run rather than being worked around.

- The `dgx-spark-llm-lab` repo, at issue #76 or newer (it must have `bench setup`). Set
  `BENCH_REPO` when invoking from elsewhere.
- Python ≥ 3.10 with `benchkit` importable (`pip install -e .`).
- One of `pi`, `opencode` or `claude-code` installed, and this shell running inside it.
- Credentials the harness already uses — the run borrows your own auth, and a hosted model
  bills your account.
- `./bench validate --suite agentic-all` printing `16/16`.

## Live run vs isolated run

Two commands measure two different things. This skill always does the **live run**.

| | **live run** — `bench setup run` (this skill) | isolated run — `bench harness run` |
|---|---|---|
| Skills, MCP servers, plugins, settings | on — your daily setup | stripped |
| Answers | "is my setup any good, what should change?" | "how good is this model?" |
| Extra output | `REPORT-live.md` with advice | result JSON only |

If the user wants the model measured rather than the setup, say so and run
`bench harness run` instead — same arguments.

## Repo Sync Before Edits (mandatory)

A run writes new files into the repo (`results/<date>/…`), so sync first:

```bash
branch="$(git rev-parse --abbrev-ref HEAD)"; git fetch origin && git pull --rebase origin "$branch"
```

Dirty tree: `git stash` → sync → `git stash pop`. No `origin`, or conflicts: stop and ask.
Never commit results unless the user asks.

## Defaults and overrides

Arguments to **this skill**; step 4 maps them onto `bench` flags.

| Knob | Default | Override |
|---|---|---|
| harness | detected (step 2) | `--harness pi\|opencode\|claude-code` |
| model | the harness's current selection | `-m <provider/model>` or any unique substring |
| suite | `agentic-hard` (8 tasks) | `--suite agentic\|agentic-hard\|agentic-all` |
| samples | `1` | `--samples N` |
| thinking | detected; **only pi honours it** | `--thinking` / `--no-thinking` |
| concurrency | `2` | `--concurrency N` |
| confirm gate | always confirm | `--yes` |
| plan only | off | `--dry-run` |

One-shot suites (`core16`, `hard12`, `all`) are refused by harness runs — those tasks need
a tool loop. Ask the user to pick an agentic suite; never switch silently.

## Step 1 — Locate the repo and prove the benchmark

```bash
repo="${BENCH_REPO:-}"
[ -x "$repo/bench" ] || { d="$PWD"; while [ "$d" != / ]; do
    [ -x "$d/bench" ] && { repo="$d"; break; }; d=$(dirname "$d"); done; }
[ -x "$repo/bench" ] || repo="$HOME/workspace/luongnv89/dgx-spark-llm-lab"
cd "$repo" || exit 1
python3 -c "import benchkit" 2>/dev/null || pip install -e .
./bench setup --help >/dev/null       # live-setup runs need this repo at #76 or newer
./bench validate --suite agentic-all  # must print 16/16, takes ~1 s
./bench harness list                  # the detected harness must read "ok"
```

Three **hard gates**: no `bench setup` → the clone is too old, offer a `git pull`; not
`16/16` → a broken oracle makes every later number meaningless, fix the harness and never
the task (see Guardrails); `pip install -e .` failing → report and stop, never retry with
`sudo`, `--user` or `--break-system-packages`.

```
◆ Preflight (step 1 of 6 — repo + oracles)
··································································
  Repo located:          √ pass (<path>)
  benchkit importable:   √ pass
  `bench setup` present: √ pass
  Oracles:               √ 16/16
  Harness installed:     √ pass (<name> <version>)
  ____________________________
  Result:                PASS
```

A `×` on any row stops the run; `references/failure-modes.md` maps each failure to its fix.

## Step 2 — Detect harness and model

```bash
bash .agents/skills/benchmark-harness/scripts/detect_setup.sh   # --harness <name> if given
```

The skill lives in `.agents/skills/` so every harness can load it; `.claude/skills/` is a
symlink to the same files. It prints `harness=`, `provider=`, `model=`, `model_source=`,
`thinking=` and how each was decided. Rules:

1. **User arguments always win** over detection.
2. **Never run without `-m`.** With no model the picker prompts on a tty and hard-errors
   everywhere else — including every agent shell.
3. **Empty `model=` means ask, never guess.** Show `./bench harness models --harness <h>`
   and let the user choose. Common on opencode, which has no default until one is set.
4. **claude-code: settings.json is intent, not proof.** An in-session `/model` switch
   leaves no trace on disk. If *you* are the session being measured, your own model beats
   the file — say so, and confirm it in step 3.
5. **Thinking is a pi-only axis.** `thinking=1` → pass `--thinking`; `0` or `unsupported`
   → omit it. pi maps it to `--thinking off|high`; opencode and claude-code ignore the flag
   and their server default applies, so report `n/a` rather than implying a mode was set.
6. **Exit 3 means the harness is unknown, not broken.** Say plainly that this shell is not
   inside pi, opencode or claude-code — a Cursor or aider session is not measurable here —
   and offer `--harness` for one of the three instead of pretending the numbers describe
   the harness the user is in.

Per-harness sources, precedence and edge cases: `references/detection.md`.

```
◆ Detection (step 2 of 6 — harness + model)
··································································
  Harness:            √ <name> (<source>)
  Model spec:         √ <provider/model> (<source>)
  Thinking:           √ <on|off|n/a> (<source>)
  Suite valid:        √ agentic-hard (8 tasks)
  ____________________________
  Result:             PASS
```

## Step 3 — Capture the run conditions

A score is unreadable without the machine and setup that produced it, so record both
before the run starts:

```bash
mkdir -p /tmp/bench-harness
bash .agents/skills/benchmark-harness/scripts/collect_context.sh \
     --harness <h> --model <spec> --thinking <on|off|n/a> > /tmp/bench-harness/context.md
```

It prints the machine, the GPU and what else is using it, the serving endpoint, and the
harness's live surface — skills, MCP servers, extensions. Every probe is fail-soft: a
missing one prints `unknown` rather than blocking the run. Field meanings and how to read
them: `references/run-context.md`.

Two rows decide whether to run at all:

- **GPU util / other GPU processes.** A device already busy makes wall-clock, turns and
  timeouts incomparable with any other run. Surface it at the confirm gate and offer to
  wait rather than quietly producing a number nobody can reuse.
- **serves.** Empty against a local endpoint means nothing is serving yet — fix that first.

```
◆ Conditions (step 3 of 6 — machine + setup)
··································································
  Machine recorded:   √ <host>, <cpu>, <memory>
  GPU:                √ <name>, <util> at start, <N> other process(es)
  Endpoint:           √ <serves> (<base url>)
  Harness surface:    √ <version>, <N> skills, <N> MCP/extensions
  ____________________________
  Result:             PASS | PASS (contended GPU — flagged at the gate)
```

## Step 4 — Confirm the plan

Skip only on `--yes`. Print exactly what will run, then wait:

```
harness      claude-code (env:CLAUDECODE)
model        opus[1m]  (your current session model)
suite        agentic-hard — 8 tasks x 1 sample, concurrency 2
thinking     n/a (adapter ignores it for claude-code)
mode         LIVE — your skills, MCP servers and settings are part of the measurement
estimate     8 tasks / concurrency 2, up to --timeout 900 s each -> 15-40 min typical
writes       results/<today>/<label>.json + REPORT-live.md   (append-only)
cost         billed to your own <harness> account/quota
machine      dgx-spark — GB10, 120 GiB, GPU 95 % busy (vLLM, 73 GiB) ← flag contention here
setup        claude-code 2.1.245, 70 skills, 0 MCP servers — all of it is measured
```

For **claude-code**, smoke-test the spec first — that adapter cannot enumerate models, so
a bad id is otherwise discovered task by task:

```bash
timeout 60 claude -p 'reply with OK' --model "<spec>" >/dev/null && echo "model ok"
```

Rejected: retry with the bare alias (`opus[1m]` → `opus`). Done when the user has said go,
or `--dry-run` stopped you here.

## Step 5 — Run it detached

A run outlives any tool timeout, so never block on it:

```bash
mkdir -p /tmp/bench-harness
log=/tmp/bench-harness/$(date +%s).log
nohup ./bench setup run --harness <h> -m <spec> \
      --suite agentic-hard --samples 1 --concurrency 2 [--thinking] \
      > "$log" 2>&1 &
echo $! > "$log.pid"
```

Poll `tail -n 20 "$log"` every minute or two. Done when the log holds `written to
results/…` and the process is gone. If it dies early, read the last 40 lines against
`references/failure-modes.md` — never re-run blind.

```
◆ Run (step 5 of 6 — <suite>)
··································································
  Process exited:     √ rc=0
  Tasks reported:     √ 8/8
  Result JSON:        √ results/<date>/<label>.json
  Live report:        √ REPORT-live.md
  ____________________________
  Result:             PASS
```

## Step 6 — Report

Take both paths from the log's `written to …` / `report written to …` lines. Append the
conditions captured in step 3 to the report the run just wrote, so the numbers and the
setup that produced them stay together:

```bash
cat /tmp/bench-harness/context.md >> "<results dir>/REPORT-live.md"
```

Appending to this run's own report is the only write allowed here — never touch a report
from an earlier campaign. Then read the printed summary and the advice section, and give
the user:

- **The conditions first** — machine, GPU contention, endpoint, harness version and how
  much live surface (skills, MCP servers, extensions) was in the loop. A reader who cannot
  reproduce the conditions cannot use the score.
- **Agent score** and its two factors (solve rate × efficiency), plus **calls vs par**,
  **turns**, **token** cost in/out per task, **valid tool-call rate**, **wall-clock**.
- **Harness, model and thinking mode next to every number.** The same model scores 67.4
  through benchkit's own loop and 77.4 through pi. A number without its harness is not a
  result.
- **The report's setup advice**, condensed to the changes worth making.
- **A noise caveat where it applies**: differences under ~8 points at `--samples 1–2` are
  noise — say so rather than declaring a winner, and offer `--samples 4`.
- Where the artefacts landed, so a later run can be diffed against them.

On claude-code, add unprompted: reasoning tokens read `0` because Claude Code reports them
in a field this stack always zeroes — the output-token budget is still right.

### Expected output

```
dgx-spark — GB10 / 120 GiB / Ubuntu 24.04 aarch64, GPU 95 % busy (vLLM 73 GiB)
endpoint montimage-dgx-spark @ localhost:8001 — claude-code 2.1.245, 70 skills, 0 MCP
claude-code / opus[1m], thinking n/a — agentic-hard, 1 sample
  agent score        74.2  (solve 87.5 % x efficiency 84.8 %)
  calls vs par       11.4 vs 9.0     turns 6.2
  tokens in/out      41k / 3.1k per task     valid calls 96.4 %
  wall               22 min
advice: 2 MCP servers add 4.1k tokens to every task and were never called — drop them.
noise: gaps under 8 points at 1 sample are not real; re-run with --samples 4 to settle.
written: results/2026-08-25/claude-code-live-opus-1m-think-off.json + REPORT-live.md
         (run context appended to the report)
```

Done when every line above is present, each score carries its harness and model, and the
report on disk ends with the run-context section.

## Guardrails

- **Never edit tasks, tests, asserts or `check`.** That destroys the benchmark.
- **`results/` is append-only.** Never delete or overwrite; the runner picks a unique path.
- **Never restart a serving endpoint here.** That is `bench apply` / `bench sweep`, needs
  human approval, and is out of scope.
- **Live mode really is live**: on claude-code and opencode the run inherits your skills
  and MCP servers, and each concurrent task is a full child session billed to you.
- **Both thinking modes only for pi**, where the flag does something: two runs, each with
  its own `--label`, or the second is impossible to tell from the first.

## References

- `references/detection.md` — per-harness model/thinking sources, precedence, edge cases.
- `references/run-context.md` — what each captured condition means and when it invalidates
  a comparison.
- `references/failure-modes.md` — error message → cause → fix, for every failure seen.
