# dgx-spark-llm-lab

**Benchmark a local coding LLM, then keep the config that won.**

A reproducible harness for answering one question honestly: *is this new model actually
better than the one I'm serving?* It runs a suite of coding tasks with hidden executable
unit tests against any OpenAI-compatible endpoint, and emits a Markdown report with
charts you can hand to someone else.

Built and used on an **NVIDIA DGX Spark (GB10)**, but the harness itself only needs a URL.

```bash
pip install -r requirements.txt
export BENCH_BASE_URL=http://localhost:8001/v1 BENCH_MODEL=my-model

./bench validate                      # 28/28 — the tests are passable
./bench run --suite all --thinking --max-tokens 16000 --label "my-model think-ON"
./bench report results/*/run-*.json --title "My model" --verdict "..."
```

The last command writes a `REPORT.md` like
[this one](results/2026-08-20-ornith-vs-qwen3.6/REPORT.md).

## Why the tests are trustworthy

Every task ships a **reference solution**. `./bench validate` runs all 28 of them against
the same hidden tests the model will face. If it does not print `28/28`, the test is
broken and no model score means anything. Run it first, every time.

Scoring is pass@1 over executable tests, not string matching and not an LLM judge: the
model's largest fenced code block is extracted, the hidden tests are appended, and the
program runs in a subprocess. It passes or it does not.

## Commands

| Command | What it does |
|---|---|
| `./bench suites [-v]` | List suites and their tasks |
| `./bench validate` | Prove every task's hidden tests are passable |
| `./bench run` | Run a suite against an endpoint, write a result JSON |
| `./bench report *.json` | Build a Markdown report with mermaid charts |
| `./bench configs` | List known-good serving configs |
| `./bench apply <name> [--restart]` | Install one as your live server config |
| `./bench compare <model>...` | DGX box only: swap, run, restore, report — one command |

Full walkthrough: **[docs/REPRODUCING.md](docs/REPRODUCING.md)**.

## The suites

| Suite | Tasks | What it covers |
|---|---|---|
| `core16` | 16 | Algorithms, data structures, parsing, Python idiom. **Saturated** — current models score 100 % |
| `hard12` | 12 | Written when `core16` stopped discriminating: regex-matching DP, a relaxed-JSON parser, Vixie-cron `next_run`, bigint long division, nestable transactions, a tiny SQL evaluator, weighted interval scheduling, first-order unification. Current models land at 45–75 % |
| `all` | 28 | Both |

When `hard12` saturates too, write the next one — see
[adding tasks](docs/REPRODUCING.md#adding-tasks-and-suites).

## Serving configs you can adopt

[`configs/`](configs/) holds complete, benchmarked `vllm serve` recipes. Install one and
you have a server:

```bash
./bench apply qwen3.6-35b-a3b-nvfp4 --restart
```

Each recipe is listed with its measured pass@1 and throughput, and the reasons its flags
are the way they are (MoE backends, MTP weight requirements, how the memory fraction is
computed). Architecture, ports and rollback: [SERVING.md](SERVING.md).

## Findings so far

| Campaign | Question | Answer |
|---|---|---|
| [2026-08-17](results/2026-08-17-thinking-mode/) | Does thinking mode help a coding agent? | **No.** Thinking off: same or better pass@1, ~13× fewer output tokens, ~32× lower wall-clock |
| [2026-08-18](results/2026-08-18-vllm-vs-ollama/) | vLLM vs ollama vs llama.cpp | vLLM wins from 3 concurrent clients up; prefix caching is off by default |
| [2026-08-20](results/2026-08-20-ornith-vs-qwen3.6/) | Should Ornith-1.5-35B-A3B replace Qwen3.6-35B-A3B? | **No.** Ties at its best config, −20 points at the config we deploy |

The recurring lesson: **always benchmark both thinking modes.** Reasoning-trained models
collapse without their thinking block; non-reasoning models burn thousands of tokens with
it. Testing one mode will tell you the wrong thing.

## Layout

```
bench                  CLI entry point
benchkit/              the harness
  suites/              task definitions (core16, hard12)
  references.py        a working solution for every task — the validation floor
  runner.py            generation, sandboxed test execution, scoring
  report.py            Markdown + mermaid report generator
  serving.py           optional: swap and restart the local vLLM service
configs/               benchmarked, ready-to-run serving recipes
results/               one dated directory per campaign: raw JSON, logs, REPORT.md
docs/REPRODUCING.md    how to reproduce or extend any of it
SERVING.md             the serving stack on the reference hardware
start-qwen.sh          the active launcher (systemd runs this; `bench apply` writes it)
router.py              OpenAI-compatible router fronting multiple vLLM backends
```

Results directories are append-only: a superseded campaign stays next to the one that
replaced it. Model weights and torch-compile caches are gitignored.

## Licence

MIT — see [LICENSE](LICENSE).
