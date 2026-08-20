# dgx-spark-llm-lab

**Find the best configuration for your daily-driver LLM — then keep it.**

Public benchmarks rank *models* on hardware you don't have, at settings you won't use.
This one answers a narrower and more useful question: **of the things I could actually
serve on this box, which exact configuration should I run every day?**

The answer is machine-local, and that is the point. The best setup for user A is routinely
the wrong one for user B — different GPU, different memory ceiling, different quantisation
available, different concurrency, different work. A published score cannot know any of
that. Running the suite on your own endpoint can.

A configuration is more than a model name — it's the model, the quantisation, the serving
flags, and the thinking mode, together. Those interact: the same weights score 60.7 % or
80.4 % on the same suite depending on one chat-template kwarg, and the right answer flips
between one-shot coding and tool loops. A leaderboard cannot tell you that. Measuring on
your own endpoint can.

So the loop here is **benchmark → decide → install**, and it ends in a config file you
serve, not a number you quote:

- **Measured where it runs.** Any OpenAI-compatible endpoint, your hardware, your flags.
- **Both thinking modes, always.** Reported as separate rows, because they are separate
  products.
- **Cost next to accuracy.** Output tokens, wall-clock, turns, truncation — a model that
  wins by thinking for 16k tokens has not won.
- **Two workload shapes.** One-shot code generation *and* multi-turn agentic tool calling,
  because they disagree.
- **The winner is installable.** `./bench apply <config> --restart` and you're serving it.
- **Nothing scored on vibes.** Hidden executable unit tests and workspace predicates, each
  proven passable by a reference solution before any model is judged.

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
| `agentic-hard` | **agent score 54.6** thinking-on (100 % solved x 54.6 % efficiency), 50.1 thinking-off ([report](results/2026-08-20-agentic-hard/REPORT.md)) |
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
Running this as an AI agent: **[AGENTS.md](AGENTS.md)** — a runbook with checks and guardrails.
Where this is going: **[ROADMAP.md](ROADMAP.md)** — next up is benchmarking through the
coding harness you actually use (pi, opencode, Claude Code, Codex), not just our tool loop.

## The suites

| Suite | Tasks | What it covers |
|---|---|---|
| `core16` | 16 | Algorithms, data structures, parsing, Python idiom. **Saturated** — current models score 100 % |
| `hard12` | 12 | Written when `core16` stopped discriminating: regex-matching DP, a relaxed-JSON parser, Vixie-cron `next_run`, bigint long division, nestable transactions, a tiny SQL evaluator, weighted interval scheduling, first-order unification. Current models land at 45–75 % |
| `all` | 28 | Both of the above |
| `agentic-hard` | 8 | **Ranking tasks.** Hidden tests the model never sees, decoys that fail the task if touched, cascading bugs, a performance budget, generalisation to an unseen input, and cases where the correct move is to change nothing. Scored on an **agent score** = solve rate x efficiency against oracle par |
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
| [2026-08-20](results/2026-08-20-agentic-hard/) | Can a harder agentic suite separate configs that both look perfect? | **Yes**, 54.6 vs 50.1. Solve rate still nearly ties; efficiency against oracle par is what separates them |

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
AGENTS.md              runbook for an AI agent driving the whole thing
ROADMAP.md             what is planned, and what is deliberately not
docs/REPRODUCING.md    how to reproduce or extend any of it
SERVING.md             the serving stack on the reference hardware
start-qwen.sh          the active launcher (systemd runs this; `bench apply` writes it)
router.py              OpenAI-compatible router fronting multiple vLLM backends
```

Results directories are append-only: a superseded campaign stays next to the one that
replaced it. Model weights and torch-compile caches are gitignored.

## Licence

MIT — see [LICENSE](LICENSE).
