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
| **Claude Code** | `claude -p --output-format stream-json`, `ANTHROPIC_BASE_URL` at the endpoint's Anthropic Messages API | **done** — [adapter](benchkit/harness/claudecode.py), [docs](docs/HARNESSES.md#the-claude-code-adapter) |
| **Codex** | CLI with a custom OpenAI-compatible base URL | planned |

The adapter interface, the real-directory execution backend and per-harness token
accounting all landed with the pi adapter — see [docs/HARNESSES.md](docs/HARNESSES.md).
Adding a harness is now three methods: `available()`, `describe()`, `run()`.

Four harnesses are now measured on the same model and machine, and they rank differently.
On the ranking suite: claude-code 68.2, opencode 60.3, pi 55.0, benchkit's own loop 44.9. On
the base suite, now that claude-code has been re-run at the same samples 2 / concurrency 2 as
the others: opencode 79.3, pi 77.4, claude-code 76.7, our loop 67.4. All four solve 100 % of
the base suite, so that ordering is efficiency alone, and the top three sit within 2.6 points
of each other — a tie at this sample count.

The top of the ranking table is closer than it looks: at 2 samples over 8 tasks one generation
is 6.25 points, so claude-code's 7.9-point lead over opencode and its 100 % versus 93.8 %
solve rate are both inside the noise band. Treat the top two as tied and the bottom two as
separated.

What is *not* noise is prefill. The three-way view concluded that efficiency here is bought
with context — opencode ~179k input tokens per task, pi ~119k, our own loop never measured them
at all. claude-code breaks that trade: ~16k per task, an order of magnitude below either, with
the fewest tool calls of the four (9.0 against a par of 5.9). Call count alone would have
missed this entirely.

The multi-way view also answers the question the two-way one raised. pi's efficiency lead on
the ranking suite came partly from solving less (87.5 % against 93.8 %); opencode and
claude-code reach equal or better efficiency without giving up solve rate, which is what
separates "efficient because it is good" from "efficient because it gave up earlier". Solve
rate and efficiency stay as separate columns next to the composite for exactly this reason.

One caveat on the table itself: with every harness now above 87.5 % solved, the 8-task ranking
suite is close to saturating and no longer has the headroom to separate the top two.

Still open for the remaining adapters:

- Claude Code turned out to expose enough: `--output-format stream-json` carries tool calls,
  turns, stop reason and token totals without touching session transcripts. The one gap is
  reasoning tokens, which the local Anthropic surface reports as `0`; they are billed inside
  output tokens and the adapter says so in `describe()`. Codex is still unmeasured.
- Claude Code only works against this endpoint because vLLM implements `/v1/messages` and the
  router proxies it. It has no OpenAI-compatibility mode, so the adapter is not portable to an
  OpenAI-only server — `available()` probes `/v1/messages/count_tokens` and refuses up front.
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
