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

    def _shared(values, fmt=str):
        """One cell for a setting the runs may or may not agree on.

        Silently printing run 0's value hides a methodology mismatch, so when the
        runs disagree the cell names every value in table order instead.
        """
        vals = list(values)
        if all(v == vals[0] for v in vals):
            return fmt(vals[0]), True
        return ("mixed — " + ", ".join(f"{fmt(v)} ({short[i]})"
                                       for i, v in enumerate(vals)), False)

    def _endpoint(s):
        # harness runs record "(harness)" as the config base_url; the real endpoint
        # the adapter dialled lives on the harness block.
        url = s["config"]["base_url"]
        if url == "(harness)":
            url = (s.get("harness") or {}).get("base_url")
        if not url or url == "(harness)":
            return None
        # claude-code dials the Anthropic surface at the root and the others the
        # OpenAI-compatible /v1 on the same server; compare hosts, not surfaces.
        return url.rstrip("/").removesuffix("/v1")

    # a run that simply did not record its endpoint is not a disagreement about it
    eps = [_endpoint(s) for s in S]
    known = [(short[i], e) for i, e in enumerate(eps) if e]
    if not known:
        endpoint = "not recorded"
    elif all(e == known[0][1] for _, e in known):
        endpoint = f"`{known[0][1]}`"
        if len(known) < len(eps):
            missing = ", ".join(short[i] for i, e in enumerate(eps) if not e)
            endpoint += f" (not recorded for {missing})"
    else:
        endpoint = "mixed — " + ", ".join(f"`{e}` ({n})" for n, e in known)
    tasks, _ = _shared([s["tasks"] for s in S])
    conc, conc_same = _shared([s["config"]["concurrency"] for s in S])
    samples, samples_same = _shared([s["config"]["samples"] for s in S])
    gens, _ = _shared([s["generations"] for s in S])

    out.append("## Setup\n")
    out.append("| | |\n|---|---|")
    out.append(f"| Endpoint | {endpoint} |")
    out.append(f"| Tasks | {tasks} |")
    if samples_same:
        out.append(f"| Samples per task | {samples} (⇒ {gens} generations per run) |")
    else:
        out.append(f"| Samples per task | {samples} |")
    out.append(f"| Concurrency | {conc} |")
    out.append(f"| Metric | pass@1 over hidden executable unit tests |\n")
    if not (conc_same and samples_same):
        out.append("<sub>The runs above were **not** all collected under the same settings. "
                   "Solve rate and tool-call counts are unaffected, but wall-clock is not "
                   "comparable across rows that differ in concurrency, and scores from "
                   "different sample counts carry different noise floors.</sub>\n")

    # --- results table ---
    agentic = all(s.get("kind") == "agentic" for s in S)
    # agentic runs predating oracle-par efficiency carry no agent_score; they can
    # still be reported, just without the column that ranks them.
    scored = agentic and all(s.get("agent_score") is not None for s in S)
    out.append("## Results\n")
    # rank agentic runs on the agent score; solve rate ties too often to rank on
    best = max(range(len(S)),
               key=lambda i: (S[i]["agent_score"] if scored else S[i]["pass_at_1"]))
    if scored:
        out.append("| Run | Agent score | Solved | Efficiency | Mean calls | Par "
                   "| Valid calls | Turn-limit | Wall |\n"
                   "|---|---|---|---|---|---|---|---|---|")
    elif agentic:
        out.append("| Run | solved | easy | medium | hard | Mean turns | Mean calls "
                   "| Valid calls | Turn-limit | Wall |\n"
                   "|---|---|---|---|---|---|---|---|---|---|")
    else:
        out.append("| Run | pass@1 | easy | medium | hard | Wall | Mean out tok "
                   "| Truncated | tok/s |\n|---|---|---|---|---|---|---|---|---|")
    for i, s in enumerate(S):
        d = s["by_difficulty"]
        name = f"**{labels[i]}**" if i == best else labels[i]
        if scored:
            score = (f"**{s['agent_score'] * 100:.1f}**" if i == best
                     else f"{s['agent_score'] * 100:.1f}")
            out.append(f"| {name} | {score} "
                       f"| {_fmt(s['pass_at_1'], pct=True)} "
                       f"| {_fmt(s['mean_efficiency'], pct=True)} "
                       f"| {_fmt(s['mean_tool_calls'])} | {_fmt(s['mean_par_calls'])} "
                       f"| {_fmt(s['valid_call_rate'], pct=True)} | {s['hit_turn_limit']} "
                       f"| {_fmt(s['wall_seconds'], digits=0)} s |")
        elif agentic:
            out.append(f"| {name} | {_fmt(s['pass_at_1'], pct=True)} "
                       f"| {_fmt(d.get('easy'), pct=True)} "
                       f"| {_fmt(d.get('medium'), pct=True)} | {_fmt(d.get('hard'), pct=True)} "
                       f"| {_fmt(s['mean_turns'])} | {_fmt(s['mean_tool_calls'])} "
                       f"| {_fmt(s['valid_call_rate'], pct=True)} | {s['hit_turn_limit']} "
                       f"| {_fmt(s['wall_seconds'], digits=0)} s |")
        else:
            out.append(f"| {name} | {_fmt(s['pass_at_1'], pct=True)} "
                       f"| {_fmt(d.get('easy'), pct=True)} "
                       f"| {_fmt(d.get('medium'), pct=True)} | {_fmt(d.get('hard'), pct=True)} " +
                       f"| {_fmt(s['wall_seconds'], digits=0)} s "
                       f"| {_fmt(s['mean_completion_tokens'], digits=0)} "
                       f"| {s['truncated']} | {_fmt(s['mean_tok_s'])} |")
    out.append("")
    if scored:
        out.append("<sub>**Agent score** = solve rate x efficiency, out of 100 — solving is "
                   "the price of entry, efficiency breaks the ties solve rate cannot. "
                   "*Efficiency* = par tool calls / calls actually used, capped at 1 and "
                   "counted only on solved tasks. *Par* is measured by running each task's "
                   "oracle, so it does not depend on the model. *Valid calls* = calls that "
                   "did not error. *Turn-limit* = runs abandoned without finishing.</sub>\n")
    elif agentic:
        out.append("<sub>*Valid calls* = tool calls that did not error. *Turn-limit* = runs "
                   "abandoned after exhausting the turn budget without finishing.</sub>\n")

    # --- charts ---
    out.append(_chart("Solve rate (%)" if agentic else "pass@1 (%)",
                      "solved %" if agentic else "pass@1 %", short,
                      [s["pass_at_1"] * 100 for s in S], y_max=100))
    out.append(_chart("Cost of that accuracy — suite wall-clock (s)", "seconds", short,
                      [s["wall_seconds"] for s in S]))
    if agentic:
        if scored:
            out.append(_chart("Agent score (solve x efficiency, out of 100)", "score", short,
                              [s["agent_score"] * 100 for s in S], y_max=100))
        out.append(_chart("Mean tool calls per task (par is the floor)" if scored
                          else "Mean tool calls per task", "calls", short,
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
    if samples_same:
        out.append(f"- {cfg0['samples']} samples per task. Differences under ~8 points are "
                   "noise, not signal.")
    else:
        out.append(f"- Samples per task differ between runs ({samples}). Differences under "
                   "~8 points are noise, not signal, and the runs with fewer samples are "
                   "noisier still.")
    if agentic:
        out.append("- Multi-turn agentic tool use against a sandboxed workspace. One-shot code "
                   "generation is not exercised here.")
    else:
        out.append("- Single-turn Python code generation only. Multi-turn agentic tool use is "
                   "not exercised here.")
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
