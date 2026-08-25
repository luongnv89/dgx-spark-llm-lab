"""Turn one or more result files into a Markdown report with mermaid charts.

The report is the deliverable: a table of every run, charts for accuracy and
cost, a per-task diff between the two most interesting runs, and the caveats
that keep the numbers honest.
"""
import json
import os

BAR = "xychart-beta"

#: CLAUDE.md's noise floor, calibrated at 2 samples per task
NOISE_POINTS = 8.0
NOISE_SAMPLES = 2

#: what a run that used benchkit's own tool loop, rather than a harness, is called
BUILTIN_HARNESS = "built-in loop"


def load(path):
    """Load a result file, naming the file on any parse failure."""
    try:
        with open(path) as f:
            d = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(f"{os.path.basename(path)}: {e}") from None
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
        mx = max(values) if values else 0
        y_max = mx * 1.15 if mx else 1
    cats = ", ".join(f'"{c}"' for c in categories)
    vals = ", ".join(f"{v:.4g}" for v in values)
    return (f"```mermaid\n{BAR}\n"
            f'    title "{title}"\n'
            f"    x-axis [{cats}]\n"
            f'    y-axis "{y_label}" 0 --> {y_max:.4g}\n'
            f"    {kind} [{vals}]\n```\n")


def _setup_of(run):
    """The (harness, thinking, config, model) a run came from, best-effort.

    `bench sweep` records the serving config and harness on the run config, so
    a swept result is fully attributed. Older result files predate those fields
    and fall back to whatever the harness block recorded, then to the built-in
    loop -- an unlabelled row is still reported, just as "not recorded".
    """
    s = run["summary"]
    cfg = s["config"]
    # harness.describe() emits "harness" (base.py/opencode.py/pi.py/claudecode.py),
    # not "name" -- reading the wrong key here would file every legacy harness
    # run under the built-in loop and rank three harnesses inside one block.
    block = s.get("harness") or {}
    harness = cfg.get("harness") or block.get("harness") or block.get("name") \
        or BUILTIN_HARNESS
    return dict(
        harness=harness,
        thinking=bool(cfg.get("thinking")),
        config=cfg.get("serving_config") or "not recorded",
        # a swept row that deliberately used the live launcher says so; only a
        # file that never recorded the field at all is "not recorded"
        model=cfg.get("served_model_id") or cfg.get("model") or "?",
        samples=cfg.get("samples"),
    )


def _blocks(runs):
    """{(harness, thinking): [run index, ...]} — the only comparable groupings.

    One harness in one thinking mode. Everything that names a winner, bolds a
    row or pairs two runs against each other has to respect this boundary, or
    the report crowns the harness instead of the setup.
    """
    blocks = {}
    for i, r in enumerate(runs):
        st = _setup_of(r)
        blocks.setdefault((st["harness"], st["thinking"]), []).append(i)
    return blocks


def _block_key(S, idx):
    """Which metric ranks this block: agent score only if every row has one."""
    return ("agent_score"
            if all(S[i].get("agent_score") is not None for i in idx)
            else "pass_at_1")


def _setup_short(runs):
    """Chart-axis labels for a sweep, keyed on the axes a sweep actually varies.

    `_short` keys on the model, which is exactly what a sweep holds constant —
    it would render three different setups as three identical bars.
    """
    out = []
    for r in runs:
        st = _setup_of(r)
        harness = "builtin" if st["harness"] == BUILTIN_HARNESS else st["harness"]
        cfg = st["config"]
        cfg = "active" if cfg.startswith("(active") else (
            "?" if cfg == "not recorded" else cfg)
        out.append(f"{harness[:7]} {cfg[:8]} {'ON' if st['thinking'] else 'OFF'}")
    # suffix *every* occurrence of a repeated label, not just the first: a
    # chart axis reading "opencod cfg-a OFF" twice names neither run.
    totals = {label: out.count(label) for label in set(out)}
    seen = {}
    for i, label in enumerate(out):
        if totals[label] > 1:
            seen[label] = seen.get(label, 0) + 1
            out[i] = f"{label} {seen[label]}"
    return out


def noise_floor(samples):
    """Points below which a difference is noise, for this many samples per task.

    CLAUDE.md fixes the floor at ~8 points at `--samples 2`. Sampling error
    shrinks as 1/sqrt(n), so quoting that same 8 points beside a 10-sample run
    would be pessimistic, and quoting it beside a 1-sample run would be a lie.
    The scaled figure is still an approximation, and it is named as one.
    """
    try:
        n = max(1, int(samples or NOISE_SAMPLES))
    except (TypeError, ValueError):
        n = NOISE_SAMPLES
    return NOISE_POINTS * (NOISE_SAMPLES / n) ** 0.5


def rank_setups(runs, labels):
    """Markdown ranking setups *within* a comparable block, never across them.

    A block is one harness in one thinking mode. That boundary is not
    fastidiousness: this repo's own harness-spread campaign in `results/`
    records a swing on identical weights as large as a model change, so a table
    that ranks an opencode row above a built-in-loop row is reporting the
    harness, not the setup. Thinking and non-thinking are likewise two products, never
    two candidates for one crown. Inside a block the serving config and the
    model are the axes actually being compared, and there the winner is real --
    subject to the sample-count noise floor, which every block states.
    """
    S = [r["summary"] for r in runs]
    setups = [_setup_of(r) for r in runs]
    blocks = _blocks(runs)

    out = ["## Ranked setups\n"]
    out.append("A setup is the serving config, the harness and the thinking mode "
               "together. Scores are ranked **within** one harness and one thinking "
               "mode and nowhere else: identical weights score materially "
               "differently through different harnesses — see the harness-spread "
               "campaign in `results/` — and thinking and non-thinking are two "
               "products, not two candidates. There is deliberately no single "
               "cross-harness winner below.\n")

    for (harness, thinking), idx in blocks.items():
        # One metric decides the whole block. A block where any run predates
        # oracle-par efficiency falls back to pass@1 for *every* row, so the
        # ranking, the cells and the margin can never quote different rulers.
        key = _block_key(S, idx)
        metric = "Agent score" if key == "agent_score" else "pass@1"

        def value(i, key=key):
            return (S[i].get(key) or 0) * 100

        ranked = sorted(idx, key=lambda i: -value(i))
        out.append(f"### {harness} · thinking {'ON' if thinking else 'OFF'}\n")
        out.append(f"| Rank | Serving config | Model | {metric} | Samples |\n"
                   "|---|---|---|---|---|")
        for rank, i in enumerate(ranked, 1):
            st = setups[i]
            cell = f"**{value(i):.1f}**" if rank == 1 else f"{value(i):.1f}"
            name = f"**{labels[i]}**" if rank == 1 else labels[i]
            out.append(f"| {rank} | `{st['config']}` | {st['model']} — {name} "
                       f"| {cell} | {st['samples']} |")
        out.append("")
        best = ranked[0]
        # the floor is set by the *noisiest* row in the block: quoting the
        # winner's sample count would understate the noise whenever the
        # runner-up ran at fewer samples.
        recorded = [setups[i]["samples"] for i in idx]
        samples = min((r or NOISE_SAMPLES) for r in recorded)
        if len(ranked) == 1:
            out.append(f"**Winner: {labels[best]}** — the only setup in this block, "
                       "so this is a measurement, not a comparison.\n")
            continue
        runner_up = ranked[1]
        margin = value(best) - value(runner_up)
        floor = noise_floor(samples)
        verdict = (f"**Winner: {labels[best]}** — {value(best):.1f} against "
                   f"{value(runner_up):.1f} for {labels[runner_up]}, "
                   f"a margin of {margin:.1f} points. ")
        where = f"at {samples} samples per task"
        if any(r is None for r in recorded):
            where += " (assumed — not every run in this block recorded one)"
        scale = (f"~{floor:.1f} points {where} "
                 f"(~{NOISE_POINTS:.0f} at {NOISE_SAMPLES}, scaled by 1/sqrt(n))")
        if margin < floor:
            verdict += (f"That is **inside the noise floor** of {scale} — treat it as "
                        "a tie and re-run with more samples before acting on it.")
        else:
            verdict += f"That clears the noise floor of {scale}."
        out.append(verdict + "\n")
    return "\n".join(out)


def _shared(values, short, fmt=str):
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


def _endpoint_cell(eps, short):
    """The Setup table's endpoint row: one host when they agree, every host otherwise."""
    known = [(short[i], e) for i, e in enumerate(eps) if e]
    if not known:
        return "not recorded"
    if all(e == known[0][1] for _, e in known):
        endpoint = f"`{known[0][1]}`"
        if len(known) < len(eps):
            missing = ", ".join(short[i] for i, e in enumerate(eps) if not e)
            endpoint += f" (not recorded for {missing})"
        return endpoint
    return "mixed — " + ", ".join(f"`{e}` ({n})" for n, e in known)


def _setup_section(S, short):
    """The Setup table, plus the sample settings the caveats quote back."""
    eps = [_endpoint(s) for s in S]
    tasks, _ = _shared([s["tasks"] for s in S], short)
    conc, conc_same = _shared([s["config"]["concurrency"] for s in S], short)
    samples, samples_same = _shared([s["config"]["samples"] for s in S], short)
    gens, _ = _shared([s["generations"] for s in S], short)

    out = ["## Setup\n"]
    out.append("| | |\n|---|---|")
    out.append(f"| Endpoint | {_endpoint_cell(eps, short)} |")
    out.append(f"| Tasks | {tasks} |")
    if samples_same:
        out.append(f"| Samples per task | {samples} (⇒ {gens} generations per run) |")
    else:
        out.append(f"| Samples per task | {samples} |")
    out.append(f"| Concurrency | {conc} |")
    out.append("| Metric | pass@1 over hidden executable unit tests |\n")
    if not (conc_same and samples_same):
        out.append("<sub>The runs above were **not** all collected under the same settings. "
                   "Solve rate and tool-call counts are unaffected, but wall-clock is not "
                   "comparable across rows that differ in concurrency, and scores from "
                   "different sample counts carry different noise floors.</sub>\n")
    return out, samples, samples_same


def _leaders(S, runs, setups, scored):
    """Which rows the results table bolds: each block's leader in a sweep."""
    if setups:
        leaders = set()
        for idx in _blocks(runs).values():
            key = _block_key(S, idx)
            leaders.add(max(idx, key=lambda i, key=key: (S[i].get(key) or 0)))
        return leaders
    return {max(range(len(S)),
                key=lambda i: (S[i]["agent_score"] if scored
                               else S[i]["pass_at_1"]))}


def _results_section(runs, S, labels, setups):
    """The results table and its footnotes; also whether runs are agentic/scored."""
    agentic = all(s.get("kind") == "agentic" for s in S)
    # agentic runs predating oracle-par efficiency carry no agent_score; they can
    # still be reported, just without the column that ranks them.
    scored = agentic and all(s.get("agent_score") is not None for s in S)
    leaders = _leaders(S, runs, setups, scored)
    out = ["## Results\n"]
    # rank agentic runs on the agent score; solve rate ties too often to rank on
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
        name = f"**{labels[i]}**" if i in leaders else labels[i]
        if scored:
            score = (f"**{s['agent_score'] * 100:.1f}**" if i in leaders
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

    if setups:
        out.append("<sub>Bold marks the leader **within** its own harness and thinking "
                   "mode — see *Ranked setups* below for the verdict. Rows from "
                   "different harnesses are not comparable, and neither are the "
                   "charts that follow.</sub>\n")
        out.append(rank_setups(runs, labels))
    return out, agentic, scored


def _charts_section(S, short, agentic, scored):
    out = []
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
    return out


def _difficulty_section(S, labels):
    """Accuracy by difficulty, one mermaid line per run."""
    diffs = ["easy", "medium", "hard"]
    lines = "\n".join(
        "    line [" + ", ".join(f"{(s['by_difficulty'].get(d) or 0) * 100:.4g}" for d in diffs) + "]"
        for s in S)
    out = ["```mermaid\n" + BAR + "\n"
           '    title "pass@1 by difficulty (%)"\n'
           '    x-axis ["easy", "medium", "hard"]\n'
           '    y-axis "pass@1 %" 0 --> 100\n' + lines + "\n```\n"]
    out.append("<sub>" + " · ".join(f"Line {i+1} = {line}" for i, line in enumerate(labels)) + "</sub>\n")
    return out


def _disagreement_section(runs, S, labels, setups, scored):
    """Per-task disagreement between the best run and the runner-up.

    A head-to-head across harnesses or thinking modes is the cross-block
    comparison the ranking exists to forbid, so in a sweep the pair must come
    from one block -- and if no block holds two runs, there is no pair.
    The pair is selected using the *same* key the results table used to bold
    the winner, so the disagreement section never compares a pair excluding
    the declared winner.
    """
    pool = range(len(S))
    if setups:
        candidates = [idx for idx in _blocks(runs).values() if len(idx) >= 2]
        pool = (max(candidates,
                    key=lambda idx: max(S[i].get("agent_score") if scored
                                        else S[i]["pass_at_1"] for i in idx))
                if candidates else [])
    if len(pool) < 2:
        return []
    key = "agent_score" if scored else "pass_at_1"
    order = sorted(pool, key=lambda i: -(S[i].get(key) or S[i][key]))[:2]
    a, b = order
    ta, tb = S[a]["by_task"], S[b]["by_task"]
    # Include every task from both runs; tasks only in one run show as "–"
    all_tasks = sorted(set(ta) | set(tb))
    rows = []
    for t in all_tasks:
        x = ta.get(t)
        y = tb.get(t)
        if x is None:
            rows.append((t, None, y, labels[b]))
        elif y is None:
            rows.append((t, x, None, labels[a]))
        elif x != y:
            rows.append((t, x, y, labels[a] if x > y else labels[b]))
    if not rows:
        return []
    out = [f"## Where they disagree — {labels[a]} vs {labels[b]}\n"]
    out.append(f"| Task | {labels[a]} | {labels[b]} | Winner |\n|---|---|---|---|")
    for t, x, y, winner in rows:
        if x is None:
            out.append(f"| `{t}` | – | {y*100:.0f} % | {winner} (not run) |")
        elif y is None:
            out.append(f"| `{t}` | {x*100:.0f} % | – | {winner} (not run) |")
        else:
            out.append(f"| `{t}` | {x*100:.0f} % | {y*100:.0f} % | {winner} |")
    out.append("")
    return out


def _caveats_section(cfg0, samples, samples_same, agentic):
    out = ["## Caveats\n"]
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
    return out


def _raw_data_section(runs, labels):
    out = ["\n## Raw data\n"]
    for r, line in zip(runs, labels):
        out.append(f"- `{r['_path']}` — {line}")
    out.append("")
    return out


def build(runs, title, question=None, verdict=None, notes=None, short_labels=None,
          setups=False, advice=False):
    """runs: list of loaded result dicts. Returns Markdown source."""
    labels = [_label(r) for r in runs]
    short = short_labels or (_setup_short(runs) if setups
                             else [_short(r, line) for r, line in zip(runs, labels)])
    S = [r["summary"] for r in runs]

    out = [f"# {title}\n"]
    if question:
        out.append(f"**Question.** {question}\n")
    if verdict:
        out.append(f"**Verdict.** {verdict}\n")
    cfg0 = S[0]["config"]

    setup_lines, samples, samples_same = _setup_section(S, short)
    out.extend(setup_lines)

    result_lines, agentic, scored = _results_section(runs, S, labels, setups)
    out.extend(result_lines)

    out.extend(_charts_section(S, short, agentic, scored))
    out.extend(_difficulty_section(S, labels))
    out.extend(_disagreement_section(runs, S, labels, setups, scored))

    if notes:
        out.append("## Reading the numbers\n")
        out.append(notes.strip() + "\n")

    if advice:
        # `bench setup run` stamps this on its report (issue #76): actionable
        # suggestions derived from each run's own numbers.
        for r in runs:
            from . import advice as advice_mod
            out.extend(advice_mod.section(r["summary"],
                                          title="Suggestions — " + _label(r)))

    out.extend(_caveats_section(cfg0, samples, samples_same, agentic))
    out.extend(_raw_data_section(runs, labels))
    return "\n".join(out)
