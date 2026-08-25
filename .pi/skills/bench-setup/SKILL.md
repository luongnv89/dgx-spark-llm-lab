---
name: bench-setup
description: Benchmark this harness's live configuration (skills, MCP servers, settings included) and get a scored report with improvement suggestions
---

# Benchmark the live setup

Run the repo's benchmark against *this* harness exactly as it is configured
right now — extensions, skills and MCP servers included, nothing isolated.

From the repository root (`/home/montimage/buildspace/m-bench`), run:

```bash
./bench setup --harness pi --suite agentic-hard
```

- Add `-m <provider/model>` only if you want a specific model; otherwise the
  run asks (or use BENCH_HARNESS_MODEL).
- Add `--samples 2` for a less noisy score; add `--thinking` to test the
  reasoning mode.
- The run takes several minutes per sample and executes model-generated code
  on this host.

When it finishes:

1. Read the report path it prints (`results/<date>/REPORT-live*.md`) and open it.
2. Relay the headline numbers (agent score, solve rate, mean calls vs par) and
   every bullet in the **Suggestions** section back to the user, verbatim where
   possible.

Note the caveat from the report: live mode keeps your real setup enabled, so if
any extension or MCP server can call another model, those numbers are
contaminated by that model.
