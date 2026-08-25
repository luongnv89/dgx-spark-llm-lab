---
description: Benchmark opencode's live configuration (plugins, MCP servers included) and get a scored report with improvement suggestions
---

Benchmark this harness's live setup with the repo's own tooling. From
`/home/montimage/buildspace/dgx-spark-llm-lab`, run:

```bash
./bench setup --harness opencode --suite agentic-hard
```

Add `-m <provider/model>` to pick a model, `--samples 2` for a steadier score,
`--thinking` for reasoning mode. It takes several minutes per sample and runs
model-generated code on this host.

Then read the printed report path (`results/<date>/REPORT-live*.md`) and relay
the headline numbers (agent score, solve rate, calls vs par) plus every bullet
of the **Suggestions** section. Live mode keeps plugins and MCP servers
enabled — if any can call another model, the measurement is contaminated by it.
