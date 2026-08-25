# Run context reference

What `scripts/collect_context.sh` records, why each field is there, and when a field means
"this result cannot be compared with that one". Read it when a captured value looks odd, or
when deciding whether two runs are comparable at all.

## Why it is captured before the run

A benchmark number is a measurement of a *system under conditions*. The suite and the model
are the visible half; the machine, the device contention and the harness's live surface are
the other half, and they move between runs without anyone noticing. Recording them at the
start — not the end — captures the state the run actually began in.

## Machine

| Field | Why it matters |
|---|---|
| host, os, arch | Results do not transfer between machines; the repo's whole premise. `aarch64` vs `x86_64` also changes which quantisations exist |
| cpu, threads | Tool-heavy agentic tasks run tests and builds; CPU decides part of the wall-clock |
| memory, free at start | A local endpoint holding most of RAM leaves little for the tasks themselves |
| disk free | Each task gets a temp workspace; a full disk fails tasks for reasons unrelated to the model |
| load avg | A machine already busy inflates wall-clock and can trip task timeouts |

## GPU

`vram` reads `unified with host memory` on unified-memory parts (GB10 and friends), where
`nvidia-smi` reports `[N/A]` for totals — the host memory row already covers it.

**Other GPU processes is the field that most often invalidates a comparison.** A serving
engine holding the device is normal and expected — it is usually the endpoint under test.
Anything *else* (a training job, a second engine, someone's notebook) shares bandwidth and
memory with the run, and the wall-clock, turn counts and timeout casualties that come out
cannot be compared with a run from a quiet machine. Flag it at the confirm gate and offer
to wait.

No `nvidia-smi` is not an error: on a hosted model there is no local GPU to record.

## Serving endpoint

`serves` lists the ids the endpoint reports at `/v1/models`. Empty against a local endpoint
means nothing is serving yet — fix that before running, not after. `unit` is the systemd
state of `vllm-qwen` on the serving host, and is absent elsewhere.

The endpoint matters even in harness runs that never touch `--endpoint`: if the harness's
model resolves to a local provider, this is the server actually answering.

## Harness setup

The point of a **live run**: skills, MCP servers, plugins and extensions are inside the
measurement, not around it. Two runs of the same model on the same machine differ if one of
them had a token-hungry MCP server injected into every task.

| Harness | Captured |
|---|---|
| pi | version, agent dir, installed extension packages, catalogue provider count |
| opencode | version, config path, plugin count, global skill count |
| claude-code | version, config dir, global + project skill counts, MCP server names |

`project context` records whether a `CLAUDE.md` / `AGENTS.md` sits in the working directory.
Benchkit's own tasks run in throwaway temp dirs, so these do not leak into task prompts —
but they do shape the session that launched the run.

## Comparability rules of thumb

Two results are comparable when the machine, the endpoint and the harness surface match and
neither run shared its GPU with a stranger. Change one of those and you are measuring the
change, not the model: that is the intended use — vary one axis, record the rest.
