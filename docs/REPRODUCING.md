# Reproducing a benchmark

The goal of a run here is not a score to quote — it is a decision: *which configuration do
I serve tomorrow?* So benchmark the candidates in both thinking modes, read accuracy and
cost together, then install the winner with `bench apply`. A result that does not change
what you serve was not worth running.

Everything here runs against **any OpenAI-compatible endpoint** — vLLM, llama.cpp's
`llama-server`, ollama, LM Studio, or a hosted API. You do not need the DGX Spark box;
that only matters for the `compare` and `apply` commands, which drive a local systemd
service.

## 1. Install

```bash
git clone https://github.com/luongnv89/dgx-spark-llm-lab.git
cd dgx-spark-llm-lab
pip install -e .                       # openai + aiohttp
```

## 2. Point it at a server

```bash
export BENCH_BASE_URL=http://localhost:8001/v1
export BENCH_MODEL=montimage-dgx-spark   # whatever name your server reports
curl -s $BENCH_BASE_URL/models           # sanity check
```

Any server works as long as it accepts `POST /v1/chat/completions` with streaming.

## 3. Prove the tests before blaming the model

```bash
./bench validate
```

Every task ships a reference solution. This runs all 28 of them against the same hidden
tests the model will face and must print `28/28`. If a task fails here, the *test* is
broken — fix it before reading any model score.

## 4. Run a suite

```bash
./bench run --suite all --samples 2 --label "my-model think-OFF"
```

Results land in `results/<today>/<label>.json` and the pass/fail of every generation
streams to the terminal as it happens.

`results/` is append-only: one dated directory per campaign, and a superseded campaign
stays on disk next to the one that replaced it. Never delete or overwrite a campaign
directory.

The two oldest campaigns — `results/2026-08-17-thinking-mode/` and
`results/2026-08-18-vllm-vs-ollama/` — each carry their own copy of the harness that
produced them (`bench.py`, `tasks.py`, `validate.py`, plus a few campaign-specific
probes). **Those duplicates are a deliberate freeze, not drift.** They predate the
`benchkit/` package, so there is no current root-level `bench.py` for them to have
drifted from — shipping the harness alongside its own results is the only thing that
keeps those two campaigns reproducible. Campaigns from `2026-08-20` onward contain
only `REPORT.md`, the run JSON and logs, because `benchkit/` in the repo is the
harness that produced them.

Useful flags:

| Flag | Default | Notes |
|---|---|---|
| `--suite` | `all` | `core16`, `hard12`, `all`, `agentic`, `agentic-hard`, `agentic-all` — see `./bench suites -v` |
| `--thinking` | off | Enables the model's reasoning block via `chat_template_kwargs` |
| `--max-tokens` | 6000 | Raise to ~16000 with `--thinking`, or reasoning eats the budget |
| `--samples` | 2 | Generations per task. 2 is cheap; 5+ before trusting small gaps |
| `--concurrency` | 4 | Parallel in-flight requests |
| `--test-timeout` | 60 | Seconds a generated program may run before counting as failed |
| `--keep-code` | off | Store every generated program in the result file, for post-mortems |
| `--max-turns` | 25 | `agentic` only: tool-calling turns before a task is abandoned |

**Always run both thinking modes.** Reasoning-trained models collapse without their
thinking block and non-reasoning models waste thousands of tokens with it; one mode
alone will mislead you. That single mistake is the finding behind two of the three
campaigns in `results/`.

## 5. Build the report

```bash
./bench report results/<today>/my-model-think-*.json \
  --title "My model vs the incumbent" \
  --question "Should we swap?" \
  --verdict "No — ties on accuracy, doubles the latency." \
  --out results/<today>/REPORT.md
```

`--notes <file.md>` splices your own written analysis into the report. `bench report`
refuses to overwrite an existing `REPORT.md`, so pass `--out` or `--force` when you
re-run it against a directory that already has one.

Writes `REPORT.md` next to the results: a setup table, a per-run results table, four
mermaid charts (pass@1, wall-clock, output tokens, accuracy by difficulty), a per-task
diff of the two best runs, your analysis, and the standing caveats.

GitHub renders the mermaid charts inline, so the report is the shareable artefact.

## 6. On the DGX box: do all of it in one command

```bash
./bench compare \
  unsloth/Qwen3.6-35B-A3B-NVFP4 \
  ornith-ai/Ornith-1.5-35B-A3B-NVFP4 \
  --both-modes --title "Ornith vs Qwen3.6" \
  --question "Should Ornith replace the incumbent?"
```

For each model this rewrites `MODEL_ID` in `start-qwen.sh`, restarts `vllm-qwen`, waits
for the endpoint to come back (engine init is ~6 min), runs the suite thinking-off then
thinking-on, and finally writes the report. The originally-served model is restored at
the end unless you pass `--no-restore`.

**This takes the endpoint down** for several minutes per swap. Don't run it against a
server other people are using.

## 7. Through the coding agent you actually use

Everything above runs through benchkit's own tool loop, which is nobody's real setup. Two
ways to close that gap:

```bash
./bench harness run --harness opencode -m <provider>/<model> --suite agentic-hard
```

```bash
./bench setup --harness pi --suite agentic-hard
```

`harness run` isolates — no extensions, no skills, no MCP servers — so the model alone is
what varies, and it uses your own harness configuration and credentials to reach it.
`setup` drops the isolation and measures your daily setup end-to-end, writing a
`REPORT-live.md` that ends in suggestions about that setup. A live score measures the whole
configuration (its parts may call other models), never the model.

Adapter details, `--endpoint` injection and per-harness caveats: [HARNESSES.md](HARNESSES.md).

## Interpreting a result honestly

- **Sample count.** At `--samples 2` the standard error on a 28-task suite is roughly
  5 points. Do not call a 3-point difference a win.
- **Truncation is failure.** A high `Truncated` count means the model never stopped
  reasoning. That is a real defect for an agent, not a budget artefact — but re-run at a
  higher `--max-tokens` before concluding, to separate the two.
- **Saturation.** When a suite returns ~100 % it has stopped measuring. `core16` reached
  that point on 2026-08-17, which is why `hard12` exists. When `hard12` saturates, write
  the next one.
- **Scope.** These are single-turn Python code-generation tasks. They predict very little
  about multi-turn agentic tool use, long-context retrieval, or non-Python work.

## Ranking with `agentic-hard`

`agentic` is a floor: a model that fails it has a real tool-calling problem, but passing
proves only that it clears the bar. `agentic-hard` is built to rank, using levers the base
suite does not have:

| Lever | What it catches |
|---|---|
| **Hidden tests** | Scoring runs asserts the model never saw, so satisfying the visible ones does not pay |
| **Decoys** | The obvious suspect is innocent; the task fails if you edit it |
| **Cascades** | Fixing one bug reveals the next — one run/fix cycle is not enough |
| **Restraint** | Some tasks are failed by changing anything, or by changing the wrong file |
| **Generalisation** | The checked input is not the sample input |
| **Budgets** | A correct but quadratic answer fails on time |

It is scored on an **agent score**, out of 100:

```
agent_score = solve_rate x mean_efficiency
efficiency  = par_tool_calls / calls_actually_used     (capped at 1, solved tasks only)
```

`par` is measured by running each task's oracle, so it depends on the task, not on the
model, the prompt or the wall clock. Solving is the price of entry; efficiency breaks the
ties that solve rate cannot — which matters because strong models tie at 100 % solved while
still using twice the calls they need.

```bash
./bench run --suite agentic-hard --samples 2 --max-turns 30 --label "my-model"
```

If a model scores 100 on solve *and* near 100 on efficiency, this suite has stopped
measuring too. Write the next one.

## The agentic suite

`--suite agentic` is a different shape of test: instead of one prompt and one answer, the
model is given seven tools — `list_files`, `read_file`, `write_file`, `edit_file`,
`search`, `run_python`, `finish` — and a sandboxed in-memory workspace, and has to reach a
goal state.

```bash
./bench validate --suite agentic          # 8/8 oracles solve their task
./bench run --suite agentic --samples 2 --label "my-model agentic"
```

A task is solved when a predicate over the **final workspace** says so — never because the
model announced success. Alongside solve rate the runner reports tool hygiene:

| Metric | Why it matters |
|---|---|
| `mean_turns` / `mean_tool_calls` | Two models that both solve a task are not equal if one needs three times the calls |
| `valid_call_rate` | Tool calls that did not error |
| `malformed_args` | Arguments that were not a valid JSON object — a broken tool-calling implementation |
| `unknown_tools` | Calls to tools that do not exist — hallucinated capability |
| `hit_turn_limit` | Runs abandoned without finishing: the flailing failure mode |
| `stalled_no_tool_call` | The model replied in prose instead of calling a tool |

Your server must support OpenAI-style function calling (`tools` + `tool_choice`). On vLLM
that means `--enable-auto-tool-choice` and a `--tool-call-parser` matching the model.

Writing an agentic task needs three things: `files` (the initial workspace), `check(ws)`
returning `(ok, detail)`, and `oracle(ws)` — a scripted sequence of tool calls that solves
it. The oracle is the equivalent of a reference solution: `bench validate` runs it and
confirms `check` then passes, so a failing task is provably the model's fault.

**Make `check` strict about the whole final state.** `verify_no_change_needed` fails a
model that edits already-correct code, and `rename_across_files` fails one that leaves the
old symbol behind even if the tests pass. Predicates that only run the tests reward
plausible-looking work.

## Adding tasks and suites

A task is a dict with four keys:

```python
dict(
    id="my_task", difficulty="hard",     # easy | medium | hard
    prompt="Write a Python function `f(x)` that ...",
    tests="""
assert f(1) == 2
assert f(0) == 0
""",
)
```

`tests` is source appended after the model's code and executed in a subprocess; raising
anything is a failure. Then:

1. Add the task to a module in `benchkit/suites/`.
2. Add a working reference solution to `benchkit/references.py` under the same id.
3. Run `./bench validate` — it must stay at 100 %.

For a new suite, create `benchkit/suites/<name>.py` exporting `TASKS`, then register it
in `benchkit/suites/__init__.py` with a one-line description.

**Write tasks that fail for the right reason.** Specify the edge cases in the prompt if
you test them; a task that fails because the spec was ambiguous measures your writing,
not the model.
