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

## Current winner — `qwen3.6-35b-a3b-nvfp4`

As of the 2026-08-20 round, the configuration to serve is **Qwen3.6-35B-A3B-NVFP4 on
vLLM with thinking off**. It survived a head-to-head against Ornith-1.5-35B-A3B and tops
every suite it has been run on.

```bash
./bench apply qwen3.6-35b-a3b-nvfp4 --restart
```

| | |
|---|---|
| Model | `unsloth/Qwen3.6-35B-A3B-NVFP4` (MoE, ~3B active) |
| Serving | vLLM, TP1, 262k ctx, fp8 KV cache, MTP speculative decoding (k=2), prefix caching |
| Memory | `--gpu-memory-utilization 0.62` (~74 GB of the 119 GB unified pool) |
| Recipe | [`configs/qwen3.6-35b-a3b-nvfp4.sh`](configs/qwen3.6-35b-a3b-nvfp4.sh) |
| `hard12` + `core16` | **82.1 % pass@1** thinking-on, 80.4 % thinking-off ([report](results/2026-08-20-ornith-vs-qwen3.6/REPORT.md)) |
| `agentic` | **100 % solved**, 95–97 % valid tool calls, no malformed arguments ([report](results/2026-08-20-agentic-baseline/REPORT.md)) |
| Throughput | ~35–48 tok/s per stream, ~122–187 tok/s aggregate at concurrency 4 |

**Serve it with thinking off.** The one-shot suites show reasoning costs ~13× the output
tokens for +1.7 points, and blows the token budget outright at low caps. The agentic suite
is the exception — there thinking cuts turns by a quarter at no accuracy cost — so if your
workload is mostly tool loops, turn it back on:

```
--default-chat-template-kwargs '{"enable_thinking":true,"preserve_thinking":true}'
```

Runner-up: `ornith-1.5-35b-a3b-nvfp4` — same accuracy at its best setting, 38 % fewer
output tokens, but it collapses without its reasoning block and stalls more often.

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
| `all` | 28 | Both of the above |
| `agentic` | 8 | **Multi-turn tool calling.** The model drives a sandboxed workspace through 7 tools — list, read, write, edit, search, run, finish — to reach a goal state: fix a failing test, rename a symbol across files, find a bug by searching, recover from a bad path, implement from a spec, decline to change working code. Scored by a predicate over the final workspace, never by what the model claims |

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
| [2026-08-20](results/2026-08-20-agentic-baseline/) | Can the winner drive a tool loop, and does thinking help there? | **Yes**, 16/16 in both modes — the suite is a floor, not a ranking. Thinking cuts turns 6.8 → 5.2 at no accuracy cost |

The recurring lesson: **always benchmark both thinking modes, on the workload you actually
run.** Reasoning-trained models collapse without their thinking block; non-reasoning models
burn thousands of tokens with it — and the right answer flips between one-shot generation
(thinking off) and multi-turn tool loops (thinking on). Testing one mode, or one workload
shape, will tell you the wrong thing.

## Layout

```
bench                  CLI entry point
benchkit/              the harness
  suites/              task definitions (core16, hard12) and the suite registry
  agentic/             the tool-calling suite: sandboxed workspace, tool schemas, agent loop
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
