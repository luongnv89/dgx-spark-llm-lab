# Benchmarking through a real coding harness

A model is only half of what you run. The other half is the **harness** wrapped around it —
its system prompt, its tool schemas, how it chunks edits, how much context it resends, how
many turns it will spend before giving up. The same weights behind two harnesses are two
different products.

Everything else in this repo measures a model through *benchkit's own* tool loop, which is
nobody's actual setup. This part measures it through the coding agent installed on your
machine.

```bash
./bench harness list                                   # what is usable here
./bench harness run --harness pi --suite agentic-hard --samples 2
```

## What stays the same

Scoring. A task is still solved when `check(ws)` says the final workspace is right, and
**par still comes from our oracle**. That matters more than it looks: par measures the
*task*, not the harness, so it is the one ruler that stays fixed while the thing being
measured changes. A harness that reaches the same goal state in fewer calls is genuinely
more efficient, and the agent score says so.

## What changes

The workspace becomes a real temp directory instead of an in-memory dict, because external
harnesses drive a filesystem. The harness runs with that directory as its working
directory, and whatever it leaves behind is read back and scored.

Two consequences worth stating plainly:

- **The harness runs real commands on your machine**, in a temp directory, with whatever
  permissions you have. That is the point — it is what your harness does every day — but it
  is not a sandbox.
- **Turn and call counts are not comparable across harnesses** without also reading the
  token columns. A harness that batches four edits into one call looks efficient until you
  see it resent 60k tokens of context to do it.

## The pi adapter

`benchkit/harness/pi.py`, driving `pi -p --mode json` and folding its JSONL event stream
into the same result shape as the built-in loop: `tool_execution_start` for calls,
`turn_start` for turns, assistant `message_end` for token usage.

Three flags in the adapter are load-bearing, and none of them is cosmetic:

| Flag | Why |
|---|---|
| `--no-extensions` | pi extensions can call **other models**. This machine's install ships an advisor extension pointed at `openai-codex/gpt-5.6-sol`; without this flag a frontier model sits silently inside a run that claims to measure a local one |
| `--no-context-files` | pi discovers `AGENTS.md` / `CLAUDE.md` by walking up from the working directory, so without this the benchmark leaks whatever guidance sits above the temp dir |
| `--no-session` | no state carries between tasks |

`stdin` is also redirected to `/dev/null`. Without that pi blocks forever on an inherited
stdin it can never read, and every task times out with zero turns — which looks exactly
like a model that cannot use tools.

### Pointing it at a model

pi resolves models through its own catalogue, not through `BENCH_BASE_URL`. On this machine
`~/.pi/agent/models.json` defines a `local-dgx` provider at `http://localhost:8001/v1`
serving `montimage-dgx-spark`. Override with:

```bash
./bench harness run --harness pi --provider local-dgx --harness-model montimage-dgx-spark
```

`./bench harness list` verifies the provider and model exist in that catalogue before a run
rather than after a confusing result.

### Thinking

`--thinking off` / `--thinking high`, selected by the `--thinking` flag as everywhere else.
pi maps those onto whatever the provider's `compat.thinkingFormat` says; for the local
provider that is `qwen-chat-template`, i.e. the same `enable_thinking` kwarg the direct
suites toggle.

## Adding another harness

Subclass `Harness` in `benchkit/harness/`, implement three methods, and register it in
`benchkit/harness/__init__.py`:

```python
class MyHarness(Harness):
    name = "myharness"

    def available(self):   # (ok, detail) — check before running, not after
        ...
    def describe(self):    # version + config, recorded into the result file
        ...
    def run(self, workdir, prompt, timeout=900, thinking=False) -> HarnessResult:
        ...
```

`run` gets a directory containing the task's files and a prompt, and must leave the
directory in whatever state the harness produced. Everything else — materialising, reading
back, scoring, par, the agent score, the report — is already done for you.

Report what you cannot measure as zero and say so in `describe()`. A harness that does not
expose token usage should not silently look cheap.

## The opencode adapter

`benchkit/harness/opencode.py`, driving `opencode run --format json`. Events map cleanly:
`tool_use` per call (with `state.status` for failures), `step_start`/`step_finish` for steps,
and per-step token counts on `step_finish`.

opencode had no entry for the local endpoint, and editing the user's global
`~/.config/opencode/opencode.json` would change how their editor behaves. The adapter writes
a throwaway provider config **next to** the task directory instead, so nothing lands in the
workspace the model sees or the one that gets scored.

Getting that to work took three findings, none of which are visible from the docs:

| Problem | Fix |
|---|---|
| Project-config discovery found the provider when the identical argv ran through a shell, and not when it was exec'd directly — every task died a second in with `ProviderModelNotFoundError` | Pass the path explicitly in `OPENCODE_CONFIG` |
| Doing that moved opencode's project root to the config file's directory, and the model then reported it could not find the task's files | Pass `--dir <workdir>` as well; it is *not* redundant with `cwd` |
| Extensions and plugins can reach other models | `--pure`, the counterpart to pi's `--no-extensions` |

`--auto` approves tool use, which is safe here only because the workspace is a throwaway temp
directory.

### Thinking

opencode exposes `--variant` for provider-specific reasoning effort rather than a boolean. The
adapter takes a `variant` argument and otherwise leaves the server's default thinking mode in
place — for the local vLLM config that is thinking ON. This is a real limitation: unlike the
direct suites and the pi adapter, `--thinking` does not currently toggle opencode runs, so
compare opencode rows against each other rather than against a specific thinking mode
elsewhere.

## A run that does nothing must not score

While the opencode adapter was failing at launch, it "passed" `verify_no_change_needed` —
whose predicate is satisfied by the source being untouched. `run_task` now fails any task
where the harness errored, timed out, or made no tool calls at all: a run that never started
cannot have solved anything. Any harness you add inherits that guard.

## Planned adapters

Claude Code (headless `-p`, custom provider via `ANTHROPIC_BASE_URL`) and Codex. See
[ROADMAP.md](../ROADMAP.md).
