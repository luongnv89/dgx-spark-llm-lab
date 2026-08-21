# dgx-spark-llm-lab — CLAUDE.md

## Critical commands

```bash
pip install -e .                          # openai>=2, aiohttp
./bench validate                          # 28/28
./bench validate --suite agentic-all      # 16/16
./bench run --suite all --label "..."     # full evaluation
./bench compare <A> <B> --both-modes      # head-to-head
./bench sweep --setup config=<c>,thinking=both --dry-run   # rank whole setups
./bench harness models                    # models your opencode/pi can reach
./bench harness run --harness opencode -m <p>/<m>   # benchmark one of them
./bench apply <config> --restart          # install winner (serving host only)
```

## Toolchain floor

- **Python ≥ 3.10** (router.py:70, benchkit/runner.py:35)
- **Runtime**: `openai>=1.40` only; **endpoint**: any OpenAI-compatible server

## Environment variables

All `BENCH_*` vars read by `benchkit/runner.py:Config.from_env()`; full list with comments in `.env.example`:

| Variable | Default | Purpose |
|---|---|---|
| `BENCH_BASE_URL` | `http://localhost:8001/v1` | OpenAI-compatible endpoint |
| `BENCH_MODEL` | `montimage-dgx-spark` | Model id from `/v1/models` |
| `BENCH_THINKING` | `0` | Enable thinking mode |
| `BENCH_MAX_TOKENS` | `6000` | Output token budget |
| `BENCH_SAMPLES` | `2` | Samples per task |
| `BENCH_CONCURRENCY` | `4` | Parallel tasks |
| `BENCH_TEST_TIMEOUT` | `60` | Test timeout (s) |
| `BENCH_HARNESS_MODEL` | — | `provider/model` the harness benchmarks |
| `BENCH_HARNESS_ENDPOINT` | — | Point a harness at this endpoint, not its own providers |
| `PI_CODING_AGENT_DIR` | — | pi agent directory |

## Architecture map

```
./
├── bench                # CLI entry point
├── benchkit/
│   ├── cli.py           # validate, run, compare, sweep, report, harness, apply
│   ├── runner.py        # Config + suite runner
│   ├── suites/          # one-shot task definitions
│   ├── agentic/         # agentic tasks + oracles
│   ├── harness/         # pi.py, opencode.py, claudecode.py + models.py picker
│   └── references.py    # reference solutions
├── configs/             # serving recipes; results/ — append-only archives
├── AGENTS.md            # model-evaluation runbook
└── README.md            # project overview
```

## Hard rules

- **Never edit a task's tests, asserts or `check` to make a model pass.** That destroys the benchmark.
- **Never delete or overwrite `results/`.** It is append-only.
- **Never restart a shared serving endpoint without explicit human approval.** `bench sweep` refuses without `--yes-restart-endpoint` or an interactive yes.
- **Always run both thinking modes** (`--thinking` and without). They are different products.
- **Raise `--max-tokens` with `--thinking`** or reasoning eats the entire budget.
- **Differences under ~8 points at `--samples 2` are noise.** Say so; raise `--samples`.
- **Report the harness name** alongside every score. Same model scores differently through different loops.

## Workflow preferences

- Read `AGENTS.md` first — the full runbook.
- Baseline the incumbent before evaluating a new model.
- `./bench compare` for head-to-head; it swaps the model, restarts, and restores.
- Harness runs use **your** opencode/pi config; pick the model with `-m` (`./bench harness models`).

## Token Efficiency
- Never re-read files you just wrote or edited; never re-run commands to "verify" a certain outcome.
- Don't echo back large blocks of code or file contents unless asked.
- Batch related edits into single operations. Don't make 5 edits when 1 handles it.
- Skip confirmations like "I'll continue..." Just do it. If a task needs 1 tool call, don't use 3.
- Do not summarize what you just did unless the result is ambiguous or you need additional input.
