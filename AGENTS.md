# AGENTS.md — runbook for an AI agent

You are being asked to find the best LLM configuration **for this specific machine**.

Read this whole file before running anything. It is written to be executed, not skimmed:
every step has a check, and the guardrails at the end are not optional.

## The premise

A public benchmark tells you which model wins on someone else's hardware, at settings you
do not run, on work you do not do. That number does not transfer. The same weights in this
repo scored **60.7 % or 80.4 %** on one identical suite depending on a single chat-template
kwarg, and the better thinking mode **flips** between one-shot code generation and
multi-turn tool loops.

So the answer is machine-local. The best configuration for user A is frequently the wrong
one for user B — different GPU, different memory ceiling, different quantisation available,
different concurrency, different work. **Your job is to measure on the machine in front of
you and end with a config that machine will actually serve.** A run that does not change
what gets served was not worth doing.

## Step 0 — establish the endpoint

```bash
echo "$BENCH_BASE_URL" "$BENCH_MODEL"
curl -s "${BENCH_BASE_URL:-http://localhost:8001/v1}/models"
```

If nothing answers, find out what is serving on this machine before doing anything else —
vLLM, llama.cpp, ollama, LM Studio and hosted APIs all work, the harness only needs an
OpenAI-compatible URL. Set both variables and re-check:

```bash
export BENCH_BASE_URL=http://localhost:8001/v1
export BENCH_MODEL=<the id the server reports>
```

Do not proceed until `/models` returns the model you intend to test.

## Step 1 — install and prove the tests

```bash
pip install -r requirements.txt
./bench validate                  # must print 28/28
./bench validate --suite agentic-all   # must print 16/16
```

**If either is not 100 %, stop and fix the harness.** A failing reference solution or oracle
means the test is broken, and every model number you produce after that is meaningless.
Never "fix" this by editing the task's tests.

## Step 2 — take a baseline of what is running now

Before evaluating anything new, measure the incumbent. Without a baseline you cannot say a
candidate is better.

```bash
./bench run --suite all     --samples 2 --label "incumbent think-OFF"
./bench run --suite all     --samples 2 --label "incumbent think-ON"  --thinking --max-tokens 16000
./bench run --suite agentic-hard --samples 2 --label "incumbent agentic-OFF"
./bench run --suite agentic-hard --samples 2 --label "incumbent agentic-ON" --thinking --max-tokens 10000
```

**Always run both thinking modes.** They are different products. Reasoning-trained models
collapse without their thinking block; non-reasoning models burn thousands of tokens with
it. Reporting one mode is reporting the wrong answer half the time.

Raise `--max-tokens` with `--thinking` or reasoning eats the whole budget and the model
emits no answer — that failure looks like incompetence and is not.

## Step 3 — check the candidate can even be served here

Before downloading tens of gigabytes, check that this machine can run it:

- Does a quantisation exist that fits this hardware? Check the model's Hugging Face repo
  for the formats your server supports.
- Does the checkpoint carry what your flags assume? For MTP speculative decoding, grep
  `model.safetensors.index.json` for `mtp.` keys — absent means startup fails.
- Does the chat template match your `--tool-call-parser`? If not, the agentic suites score
  zero for reasons unrelated to the model.
- Will the weights fit next to whatever else this box serves?

Record what you checked. "It did not fit" is a valid, useful result.

## Step 4 — evaluate the candidate

On a machine with a swappable local service:

```bash
./bench compare <incumbent-model-id> <candidate-model-id> \
  --suite all --both-modes --title "<candidate> vs <incumbent>" \
  --question "Should <candidate> replace <incumbent>?"
```

This rewrites `MODEL_ID`, restarts the service, waits for health, runs both modes for each
model, restores the original, and writes the report. **It takes the endpoint down for
minutes per swap — confirm with a human first if anyone else uses it.**

Otherwise point `BENCH_BASE_URL` at each endpoint in turn and use `./bench run`.

## Step 5 — decide, and write it down

```bash
./bench report results/<date>-<name>/run-*.json \
  --title "..." --question "..." --verdict "..." --notes analysis.md
```

The verdict must be a decision, not a summary. Judge on:

| Signal | Weight |
|---|---|
| pass@1 on `all` | Primary for one-shot coding |
| Agent score on `agentic-hard` | Primary for tool-loop work |
| Mean output tokens, wall-clock | A model that wins by thinking 16k tokens has not won |
| Truncated / turn-limit counts | Runaway reasoning hangs real agents; weigh it heavily |
| Whether it fits alongside everything else on the box | Hard constraint |

**Differences under ~8 points at `--samples 2` are noise.** Say so rather than declaring a
winner. Raise `--samples` before calling a close race.

## Step 6 — check it through the harness you actually use

The suites above measure the model through benchkit's own tool loop, which is nobody's real
setup. If a coding agent is installed on this machine, measure through it too:

```bash
./bench harness list
./bench harness run --harness pi --suite agentic-hard --samples 2
```

The gap is not cosmetic — on this repo's first such comparison the same model scored 67.4
through the built-in loop and 77.4 through pi. When you report a number, name the harness it
came from.

## Step 7 — install the winner

```bash
./bench configs
./bench apply <config-name> --restart
```

Then add a row to `configs/README.md` with the measured numbers. A config with no measured
row is a guess, not a known-good config.

## Guardrails

- **Never edit a task's tests, asserts or `check` to make a model pass.** That is the one
  change that destroys the value of the entire repo.
- **Never delete or overwrite an existing `results/` directory.** They are append-only; a
  superseded campaign stays next to the one that replaced it.
- **Never restart a shared serving endpoint without explicit human approval.**
- **Do not report a number you did not measure.** No estimating, no carrying a figure over
  from another machine, no quoting the model card.
- **Report failures that were the harness's fault as such.** One `run_python` bug in this
  repo cost a model 12.5 points until it was found; the model was innocent. When driving an
  external harness, a run with zero turns is almost always a wiring problem, not a model
  failure — check `docs/HARNESSES.md` before recording it.
- **Never let a harness extension call a different model.** pi's extensions can; the adapter
  passes `--no-extensions` for exactly this reason. Verify the equivalent for any harness you
  add, or the benchmark silently measures something else.
- **If a suite returns ~100 %, say it has stopped measuring** rather than calling the model
  perfect. Then write harder tasks — see `docs/REPRODUCING.md`.

## Adding tasks

Both kinds require proof the task is winnable before any model is judged:

- one-shot: a task in `benchkit/suites/`, a reference solution in `benchkit/references.py`,
  then `./bench validate` stays at 100 %.
- agentic: a task in `benchkit/agentic/tasks*.py` with `files`, `check(ws)` and an
  `oracle(ws)`, then `./bench validate --suite agentic-all` stays at 100 %.

The oracle also sets **par** — the minimum tool calls — which is what the agent score
measures efficiency against. Write the oracle the way a competent engineer would work, not
the shortest path that happens to satisfy the predicate.
