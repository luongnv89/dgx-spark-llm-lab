# Detection reference

How `scripts/detect_setup.sh` decides which harness it is inside and which model that
harness is set to. Read this when detection returns something surprising, when the model
comes back empty, or when adding a fourth harness.

## Harness

Tried in order; the first hit wins and is reported in `harness_source=`.

| Order | Signal | Notes |
|---|---|---|
| 1 | `--harness <name>` | user override, never second-guessed |
| 2 | `CLAUDECODE`, `CLAUDE_CODE_ENTRYPOINT`, `CLAUDE_CODE_SESSION_ID` | claude-code |
| 3 | `OPENCODE`, `OPENCODE_BIN_PATH`, `OPENCODE_CLIENT`, `OPENCODE_SESSION_ID` | opencode |
| 4 | `PI_CODING_AGENT_DIR`, `PI_AGENT_DIR`, `PI_SESSION_ID` | pi |
| 5 | process ancestry, up to 12 levels | `ps -o args=`, Linux and macOS |
| — | none matched | exit 3, message names what was checked |

Ancestry compares the **basename of argv[0]** (or of argv[1] behind `node`/`bun`/`deno`/
`npx`, which is how pi and opencode are usually launched). It deliberately does not
substring-match the whole command line: a `PATH` entry such as `~/.opencode/bin` sitting in
an ancestor's arguments would otherwise be read as "running inside opencode".

Nesting is not a hazard for the run itself — the claude-code adapter scrubs `CLAUDECODE`,
`ANTHROPIC_MODEL`, `CLAUDE_CONFIG_DIR` and friends from the child, so a benchmark launched
from inside Claude Code does not tell its children they are nested.

## Model

`BENCH_HARNESS_MODEL` outranks every per-harness source below (it is the benchmark's own
override, and the CLI already honours it), and explicit user arguments outrank that.

| Harness | Sources, in precedence order | Reliability |
|---|---|---|
| claude-code | `ANTHROPIC_MODEL` → `./.claude/settings.local.json` → `./.claude/settings.json` → `$CLAUDE_CONFIG_DIR/settings{,.local}.json` (`.model`) | **intent, not proof** — a `/model` switch inside the session leaves no trace on disk |
| opencode | `OPENCODE_MODEL` → `$OPENCODE_CONFIG` → `./opencode.json(c)` → `~/.config/opencode/opencode.json` → `~/.config/opencode/config.json` (`.model`, `provider/model`) | often absent: opencode keeps the TUI selection in its own database, not in JSON |
| pi | `$PI_CODING_AGENT_DIR/settings.json` (`defaultProvider` + `defaultModel`), default `~/.pi/agent` | reliable — pi writes the selection to disk |

An empty `model=` is a normal answer. Resolve it by asking, never by guessing:

```bash
./bench harness models --harness <h>       # what this harness can actually reach
```

`bench` resolves `-m` against that catalogue, accepting `provider/model`, a bare id, or any
unique substring (`-m qwen3-coder` finds `ollama/qwen3-coder:latest`); ambiguous or unknown
specs are rejected up front with the list. claude-code is the exception — it cannot
enumerate models, so its spec is taken literally and is worth the smoke test in step 3.

### If you are the session being measured

An agent knows its own model even when the config file disagrees. Prefer that over the
file, name the source when reporting, and let the user correct it at the confirm gate.
Aliases (`opus`, `sonnet`, `haiku`) and full ids both work with `claude --model`; a
suffixed id such as `opus[1m]` may not, so fall back to the bare alias if it is rejected.

## Thinking

Only **pi** turns `--thinking` into a real flag (`--thinking off|high`), read from
`defaultThinkingLevel` in its settings. The opencode and claude-code adapters accept the
flag and ignore it — the server's or account's own default applies — so the script reports
`thinking=unsupported` for them. Reporting "thinking ON" for those two would be a fiction;
report `n/a` instead, and only offer a both-modes campaign on pi.
