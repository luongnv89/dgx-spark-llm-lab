# Reproducing a benchmark

Everything here runs against **any OpenAI-compatible endpoint** — vLLM, llama.cpp's
`llama-server`, ollama, LM Studio, or a hosted API. You do not need the DGX Spark box;
that only matters for the `compare` and `apply` commands, which drive a local systemd
service.

## 1. Install

```bash
git clone https://github.com/luongnv89/dgx-spark-llm-lab.git
cd dgx-spark-llm-lab
pip install -r requirements.txt        # just `openai`
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

Useful flags:

| Flag | Default | Notes |
|---|---|---|
| `--suite` | `all` | `core16`, `hard12`, `all`, or `agentic` — see `./bench suites -v` |
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
./bench report results/2026-08-20-*/run-*.json \
  --title "My model vs the incumbent" \
  --question "Should we swap?" \
  --verdict "No — ties on accuracy, doubles the latency." \
  --notes my-analysis.md
```

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
