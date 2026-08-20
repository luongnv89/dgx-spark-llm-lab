# Roadmap

The through-line: **benchmark the thing the user actually runs, on the machine they
actually run it on.** Everything below moves closer to that.

## Now

- [x] One-shot code generation: `core16`, `hard12` — hidden executable tests
- [x] Agentic tool calling: `agentic` (floor), `agentic-hard` (ranking, oracle-par efficiency)
- [x] Installable serving configs — `bench apply`, measured rows in `configs/README.md`
- [x] `AGENTS.md` — a runbook an AI agent can execute unattended

## Next: benchmark the harness, not just the model

A model is only half of what a user runs. The other half is the **coding harness** wrapped
around it — its system prompt, its tool schemas, its context strategy, how it chunks edits,
how many turns it will spend. The same weights behind two harnesses are two different
products, and today this repo measures the model through *our* tool loop, which is nobody's
actual setup.

So the next step is to run the same tasks through the harness sitting on the user's machine:

| Harness | Integration route | Status |
|---|---|---|
| **pi** | `pi -p --mode json`, events folded into the standard result shape | **done** — [adapter](benchkit/harness/pi.py), reports on the [base](results/2026-08-20-pi-harness/REPORT.md) and [ranking](results/2026-08-20-pi-harness/REPORT-hard.md) suites |
| **opencode** | `opencode run --format json`, throwaway provider config via `OPENCODE_CONFIG` | **done** — [adapter](benchkit/harness/opencode.py), [docs](docs/HARNESSES.md#the-opencode-adapter) |
| **Claude Code** | Custom provider via `ANTHROPIC_BASE_URL`; headless `-p` runs, tool use through its own harness | planned |
| **Codex** | CLI with a custom OpenAI-compatible base URL | planned |

The adapter interface, the real-directory execution backend and per-harness token
accounting all landed with the pi adapter — see [docs/HARNESSES.md](docs/HARNESSES.md).
Adding a harness is now three methods: `available()`, `describe()`, `run()`.

Three harnesses are now measured on the same model and machine, and they rank differently on
both suites: opencode 79.3 / 60.3, pi 77.4 / 55.0, benchkit's own loop 67.4 / 44.9 (base /
ranking). Efficiency is bought with prefill, and the ordering inverts — opencode sends ~179k
input tokens per task, pi ~119k, and our own loop never measured them at all.

The three-way view also answers the question the two-way one raised. pi's efficiency lead on
the ranking suite came partly from solving less (87.5 % against 93.8 %); opencode reaches the
same efficiency while matching benchkit's solve rate, which is what separates "efficient
because it is good" from "efficient because it gave up earlier". Solve rate and efficiency
stay as separate columns next to the composite for exactly this reason.

Still open for the remaining adapters:

Still open for the remaining adapters:

- Claude Code and Codex expose less structured telemetry than pi's and opencode's JSONL; call
  and token counts may have to come from session transcripts rather than a live event stream.
- Harnesses that batch several edits into one call are not comparable to ones that do not on
  call count alone — the token columns have to be read alongside.
- Thinking mode is not uniformly controllable. pi takes a level, opencode takes a
  provider-specific `--variant`, and neither maps cleanly onto the `enable_thinking` kwarg the
  direct suites toggle. Until that is normalised, compare harness rows against each other
  rather than against a specific thinking mode elsewhere.

The output is the comparison nobody currently has: *for **this** machine and **this**
harness, which model and which settings?* — with the answer legitimately differing between
two users running the same model.

## Also planned

- **Concurrency sweeps** — every number here is at concurrency 4. Per-stream throughput and
  TTFT under 1/4/8/16 clients change which config wins for a team versus one person.
- **Long-context suite** — retrieval and edit accuracy at 32k / 128k / 256k. The configs
  advertise 262k; nothing here tests past a few thousand tokens.
- **Quantisation ladder** — same model at NVFP4 / FP8 / BF16, to price the accuracy each
  step actually costs on this hardware rather than in general.
- **Cold-start and memory-pressure numbers** — engine init time and behaviour with a second
  backend resident, both of which decide whether a config is livable day to day.
- **Non-Python tasks** — the suites are Python-only, which flatters models tuned for it.
- **A `bench doctor` command** — inspect the endpoint and report what it supports (tool
  calling, thinking kwargs, context length, speculative decoding) before a run rather than
  after a confusing result.

## Not planned

- A global leaderboard. If these numbers get averaged across machines they stop meaning
  anything, which is the failure mode this repo exists to avoid.
