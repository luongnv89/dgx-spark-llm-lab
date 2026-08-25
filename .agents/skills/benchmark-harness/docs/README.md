<!--
  DO NOT READ THIS FILE — This README.md is for human catalog browsing only.
  It ships inside the .skill package but is NEVER auto-loaded into agent context.
  The runtime loader only reads SKILL.md + references/ + scripts/ + agents/ when the skill triggers.
  If you're an AI agent, read the SKILL.md file instead for skill instructions.
-->

# Benchmark Harness

> Benchmark the coding harness you are sitting in — pi, opencode or claude-code — on its
> live configuration and currently selected model, then report what to improve.

## Highlights

- **Detects the harness for you.** Environment markers first, process ancestry second; no
  need to tell it where it is running.
- **Uses the model you already selected.** Read from pi's settings, opencode's config, or
  Claude Code's settings/session — overridable with `-m`.
- **Measures the setup, not just the model.** Wraps `bench setup run`, so your skills, MCP
  servers, plugins and settings are part of the measurement, and the run ends with written
  advice about them.
- **Confirms before it spends.** A run is 15–40 minutes and, on a hosted model, real money,
  so it prints the plan and waits — unless you pass `--yes`.

## When to Use

| Say this...                              | Skill will...                                                   |
| ---------------------------------------- | --------------------------------------------------------------- |
| `/benchmark-harness`                     | Detect harness + model, confirm the plan, run `agentic-hard`      |
| `/benchmark-harness --harness pi -m qwen` | Benchmark that harness and model instead of the detected ones     |
| "benchmark my current setup"             | Same live run, with the setup advice condensed into next steps    |
| `/benchmark-harness --dry-run`           | Print the resolved plan and stop                                  |

Not for: `bench compare` (two models head-to-head), `bench sweep` (serving-config matrix),
`bench run` (one-shot suites), `bench apply` (installing a serving config).

## Requirements

- The `dgx-spark-llm-lab` repo, with `pip install -e .` done (Python ≥ 3.10).
- At least one harness installed: `pi`, `opencode` or `claude-code`.
- `./bench validate --suite agentic-all` printing `16/16` — the skill enforces this.
- Set `BENCH_REPO` if you invoke the skill from outside the repo.

## Workflow

```
detect_setup.sh ──► preflight (16/16 oracles, harness ok)
        │
        ▼
  confirm plan  ──►  bench setup run --harness <h> -m <spec> --suite agentic-hard
        │                     │
     --yes skips              ▼
                     results/<date>/<label>.json + REPORT-live.md
                                  │
                                  ▼
                   agent score, calls vs par, turns, tokens, advice
```

## Notes

- `--thinking` is a real axis only on **pi**; the opencode and claude-code adapters ignore
  it and the server's default applies.
- `results/` is append-only. Runs never overwrite each other.
- A live claude-code or opencode run inherits your skills and MCP servers, and each
  concurrent task is a full child session billed to your account.
