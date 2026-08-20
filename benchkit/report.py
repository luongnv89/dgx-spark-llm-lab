"""Turn one or more result files into a Markdown report with mermaid charts.

The report is the deliverable: a table of every run, charts for accuracy and
cost, a per-task diff between the two most interesting runs, and the caveats
that keep the numbers honest.
"""
import json
import os

BAR = "xychart-beta"


def load(path):
    with open(path) as f:
        d = json.load(f)
    d["_path"] = os.path.basename(path)
    return d


def _label(run):
    cfg = run["summary"]["config"]
    if cfg.get("label"):
        return cfg["label"]
    return f"{cfg['model']} think-{'ON' if cfg['thinking'] else 'OFF'} {cfg['max_tokens']//1000}k"


def _short(run, label):
    """A chart-axis label that still distinguishes runs after truncation."""
    cfg = run["summary"]["config"]
    model = (cfg.get("served_model_id") or cfg.get("model") or "").split("/")[-1]
    model = model.replace("-NVFP4", "").replace("-A3B", "").replace("-Instruct", "")
    stem = model or label.split()[0]
    if len(stem) > 12:
        stem = stem[:12]
    return f"{stem} {'ON' if cfg.get('thinking') else 'OFF'}"


def _fmt(v, pct=False, digits=1):
    if v is None:
        return "—"
    if pct:
        return f"{v * 100:.{digits}f} %"
    if isinstance(v, float):
        return f"{v:,.{digits}f}"
    return f"{v:,}"


def _chart(title, y_label, categories, values, y_max=None, kind="bar"):
    if y_max is None:
        y_max = max(values) * 1.15 if values else 1
    cats = ", ".join(f'"{c}"' for c in categories)
    vals = ", ".join(f"{v:.4g}" for v in values)
    return (f"```mermaid\n{BAR}\n"
            f'    title "{title}"\n'
            f"    x-axis [{cats}]\n"
            f'    y-axis "{y_label}" 0 --> {y_max:.4g}\n'
            f"    {kind} [{vals}]\n```\n")


def build(runs, title, question=None, verdict=None, notes=None, short_labels=None):
    """runs: list of loaded result dicts. Returns Markdown source."""
    labels = [_label(r) for r in runs]
    short = short_labels or [_short(r, l) for r, l in zip(runs, labels)]
    S = [r["summary"] for r in runs]

    out = [f"# {title}\n"]
    if question:
        out.append(f"**Question.** {question}\n")
    if verdict:
        out.append(f"**Verdict.** {verdict}\n")

    # --- setup table ---
    cfg0 = S[0]["config"]
    out.append("## Setup\n")
    out.append("| | |\n|---|---|")
    out.append(f"| Endpoint | `{cfg0['base_url']}` |")
    out.append(f"| Tasks | {S[0]['tasks']} |")
    out.append(f"| Samples per task | {cfg0['samples']} (⇒ {S[0]['generations']} generations per run) |")
    out.append(f"| Concurrency | {cfg0['concurrency']} |")
    out.append(f"| Metric | pass@1 over hidden executable unit tests |\n")

    # --- results table ---
    agentic = all(s.get("kind") == "agentic" for s in S)
    out.append("## Results\n")
    best = max(range(len(S)), key=lambda i: S[i]["pass_at_1"])
    if agentic:
        out.append("| Run | solved | easy | medium | hard | Mean turns | Mean calls "
                   "| Valid calls | Turn-limit | Wall |\n"
                   "|---|---|---|---|---|---|---|---|---|---|")
    else:
        out.append("| Run | pass@1 | easy | medium | hard | Wall | Mean out tok "
                   "| Truncated | tok/s |\n|---|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(S):
        d = s["by_difficulty"]
        name = f"**{labels[i]}**" if i == best else labels[i]
        head = (f"| {name} | {_fmt(s['pass_at_1'], pct=True)} | {_fmt(d.get('easy'), pct=True)} "
                f"| {_fmt(d.get('medium'), pct=True)} | {_fmt(d.get('hard'), pct=True)} ")
        if agentic:
            out.append(head +
                       f"| {_fmt(s['mean_turns'])} | {_fmt(s['mean_tool_calls'])} "
                       f"| {_fmt(s['valid_call_rate'], pct=True)} | {s['hit_turn_limit']} "
                       f"| {_fmt(s['wall_seconds'], digits=0)} s |")
        else:
            out.append(head +
                       f"| {_fmt(s['wall_seconds'], digits=0)} s "
                       f"| {_fmt(s['mean_completion_tokens'], digits=0)} "
                       f"| {s['truncated']} | {_fmt(s['mean_tok_s'])} |")
    out.append("")
    if agentic:
        out.append("<sub>*Valid calls* = tool calls that did not error. *Turn-limit* = runs "
                   "abandoned after exhausting the turn budget without finishing.</sub>\n")

    # --- charts ---
    out.append(_chart("pass@1 (%)", "pass@1 %", short,
                      [s["pass_at_1"] * 100 for s in S], y_max=100))
    out.append(_chart("Cost of that accuracy — suite wall-clock (s)", "seconds", short,
                      [s["wall_seconds"] for s in S]))
    if agentic:
        out.append(_chart("Mean tool calls per task", "calls", short,
                          [s["mean_tool_calls"] or 0 for s in S]))
        out.append(_chart("Valid tool-call rate (%)", "%", short,
                          [(s["valid_call_rate"] or 0) * 100 for s in S], y_max=100))
    else:
        out.append(_chart("Mean output tokens per answer", "tokens", short,
                          [s["mean_completion_tokens"] or 0 for s in S]))

    # --- accuracy by difficulty, one line per run ---
    diffs = ["easy", "medium", "hard"]
    lines = "\n".join(
        "    line [" + ", ".join(f"{(s['by_difficulty'].get(d) or 0) * 100:.4g}" for d in diffs) + "]"
        for s in S)
    out.append("```mermaid\n" + BAR + "\n"
               '    title "pass@1 by difficulty (%)"\n'
               '    x-axis ["easy", "medium", "hard"]\n'
               '    y-axis "pass@1 %" 0 --> 100\n' + lines + "\n```\n")
    out.append("<sub>" + " · ".join(f"Line {i+1} = {l}" for i, l in enumerate(labels)) + "</sub>\n")

    # --- per-task disagreement between best and runner-up ---
    if len(S) >= 2:
        order = sorted(range(len(S)), key=lambda i: -S[i]["pass_at_1"])[:2]
        a, b = order
        ta, tb = S[a]["by_task"], S[b]["by_task"]
        rows = [(t, ta[t], tb.get(t, 0.0)) for t in sorted(ta) if ta[t] != tb.get(t, 0.0)]
        if rows:
            out.append(f"## Where they disagree — {labels[a]} vs {labels[b]}\n")
            out.append(f"| Task | {labels[a]} | {labels[b]} | Winner |\n|---|---|---|---|")
            for t, x, y in rows:
                out.append(f"| `{t}` | {x*100:.0f} % | {y*100:.0f} % | "
                           f"{labels[a] if x > y else labels[b]} |")
            out.append("")

    if notes:
        out.append("## Reading the numbers\n")
        out.append(notes.strip() + "\n")

    out.append("## Caveats\n")
    out.append(f"- {cfg0['samples']} samples per task. Differences under ~8 points are noise, "
               "not signal.")
    out.append("- Single-turn Python code generation only. Multi-turn agentic tool use is not "
               "exercised here.")
    if agentic:
        out.append("- Success is decided by a predicate over the final workspace, never by what "
                   "the model claims. Every task's oracle is verified to solve it first.")
        out.append("- A task abandoned at the turn limit counts as failed; raise `--max-turns` "
                   "before concluding the model cannot do it.")
    else:
        out.append("- A truncated generation counts as a failure; a high `Truncated` column means "
                   "runaway reasoning, which hangs real agents.")
    out.append("\n## Raw data\n")
    for r, l in zip(runs, labels):
        out.append(f"- `{r['_path']}` — {l}")
    out.append("")
    return "\n".join(out)
