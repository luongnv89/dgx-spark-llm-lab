#!/usr/bin/env python3
"""surface_usage.py — did the harness's skills, MCP servers and plugins do anything?

A live run enables the whole daily surface, but the result file only ever said
that the surface was *on*. It could not tell "the skills helped" from "the
skills sat there costing prompt tokens and were never called" — the two look
identical in an agent score. Every live run committed to `results/` so far is
in fact the second case, which is exactly why this exists.

Two questions, one script:

  1. **usage** — of the tool calls in a run, which were built-in, which came
     from an MCP server, and which came from a skill, plugin or extension?
  2. **A/B** — with an isolated arm to compare against, what did the surface
     actually buy? Scores, efficiency and prompt cost, side by side.

Reads only the result JSONs `bench` already writes. Prints markdown on stdout,
so the caller can append it to a report the same way the run context is
appended.

    surface_usage.py --live results/<date>/<live>.json
    surface_usage.py --live <live>.json --isolated <iso>.json
    surface_usage.py --live <live>.json --context /tmp/bench-harness/context.md
"""
import argparse
import json
import os
import re
import sys

#: Tool names each harness ships with. Used only when there is no isolated arm
#: to derive them from — an allowlist is a guess about someone else's product,
#: and a name missing from it must never be reported as a skill. Unknown names
#: are reported as `unattributed`, which is honest about not knowing.
BUILTIN = {
    "claude-code": {
        "Bash", "Read", "Edit", "Write", "Glob", "Grep", "MultiEdit",
        "NotebookEdit", "TodoWrite", "Task", "WebSearch", "WebFetch",
        "BashOutput", "KillShell", "ExitPlanMode", "AskUserQuestion",
    },
    "pi": {
        "read", "write", "edit", "bash", "glob", "grep", "ls", "list",
        "todo", "todowrite", "task", "webfetch", "websearch", "patch",
    },
    "opencode": {
        "read", "write", "edit", "bash", "glob", "grep", "list", "patch",
        "todowrite", "todoread", "webfetch", "task",
    },
}

#: A claude-code MCP tool call is named `mcp__<server>__<tool>`; the server is
#: recoverable from the name alone, which is why MCP needs no allowlist.
_MCP = re.compile(r"^mcp__(?P<server>[^_]+(?:_[^_]+)*?)__(?P<tool>.+)$")

#: Tool names that mean "a skill was invoked". The skill's own name lives in
#: the tool-call input, which benchkit does not persist (claudecode.py records
#: `block["name"]` only), so these are counted and never named. See
#: references/surface-ab.md.
_SKILL_TOOLS = {"Skill", "skill", "SlashCommand"}

BUILTIN_KIND, MCP_KIND, SKILL_KIND = "builtin", "mcp", "skill"
SURFACE_KIND, UNKNOWN_KIND = "surface", "unattributed"


def classify(name, harness, builtin_seen=None):
    """(kind, detail) for one tool name.

    *builtin_seen* is the set of tool names observed in an isolated arm. When
    it is given it outranks the static table: isolation strips skills, MCP and
    plugins, so anything the isolated arm called is a built-in by demonstration
    rather than by assumption, and anything absent from it is attributable to
    the surface.
    """
    m = _MCP.match(name)
    if m:
        return MCP_KIND, m.group("server")
    if name in _SKILL_TOOLS:
        return SKILL_KIND, "(name not recorded)"
    if builtin_seen is not None:
        return (BUILTIN_KIND, name) if name in builtin_seen else (SURFACE_KIND, name)
    if name in BUILTIN.get(harness, ()):
        return BUILTIN_KIND, name
    return UNKNOWN_KIND, name


def harness_name(doc):
    """The harness a result file was produced by, or "" when unrecorded."""
    h = (doc.get("summary") or {}).get("harness") or {}
    return h.get("harness", "") if isinstance(h, dict) else str(h)


def tool_names(doc):
    """Every tool name in a result file's traces, run order preserved."""
    for r in doc.get("results") or []:
        for name in r.get("trace") or []:
            yield name


def tally(doc, harness, builtin_seen=None):
    """{kind: {detail: count}} plus a per-task index of surface-attributed calls."""
    kinds, per_task = {}, {}
    for r in doc.get("results") or []:
        for name in r.get("trace") or []:
            kind, detail = classify(name, harness, builtin_seen)
            kinds.setdefault(kind, {}).setdefault(detail, 0)
            kinds[kind][detail] += 1
            if kind in (MCP_KIND, SKILL_KIND, SURFACE_KIND):
                task = r.get("task", "?")
                per_task.setdefault(task, {}).setdefault(name, 0)
                per_task[task][name] += 1
    return kinds, per_task


def installed(context_path):
    """Surface counts scraped from a collect_context.sh markdown table.

    Best-effort by design: the table is for humans first, and a row that moved
    or was never emitted must degrade to "not recorded", never to a crash.
    """
    out = {}
    try:
        with open(context_path) as f:
            text = f.read()
    except OSError:
        return out
    for field in ("skills", "mcp", "extensions", "plugins"):
        m = re.search(rf"^\|\s*{field}\s*\|\s*(.+?)\s*\|\s*$", text,
                      re.MULTILINE | re.IGNORECASE)
        if m:
            out[field] = m.group(1)
    return out


def _pct(x):
    return "n/a" if x is None else f"{x * 100:.1f}"


def _num(x, places=1):
    return "n/a" if x is None else f"{x:.{places}f}"


#: (key, label, formatter, higher-is-better, decimals in the delta) for the A/B
#: table. Deltas carry the precision of the metric they belong to: a tenth of a
#: point matters on a score, a tenth of a token does not.
_METRICS = (
    ("agent_score", "agent score", _pct, True, 1),
    ("pass_at_1", "solve rate %", _pct, True, 1),
    ("mean_efficiency", "efficiency %", _pct, True, 1),
    ("mean_tool_calls", "calls / task", _num, False, 1),
    ("mean_turns", "turns / task", _num, False, 1),
    ("mean_input_tokens", "input tok / task", lambda v: _num(v, 0), False, 0),
    ("mean_completion_tokens", "output tok / task", lambda v: _num(v, 0), False, 0),
    ("wall_seconds", "wall (s)", lambda v: _num(v, 0), False, 0),
)

#: Below this many points, an agent-score gap at 1-2 samples is not a result.
#: Same threshold the repo applies everywhere else (CLAUDE.md hard rules).
NOISE_POINTS = 8.0


def render_usage(doc, harness, builtin_seen, context):
    """The 'what did the surface actually do' section."""
    kinds, per_task = tally(doc, harness, builtin_seen)
    total = sum(sum(v.values()) for v in kinds.values())
    lines = ["## Surface usage", ""]
    if not total:
        lines += ["No tool calls recorded in this run — nothing to attribute.", ""]
        return lines

    lines += [f"_{total} tool calls, classified. "
              + ("Built-ins identified from the isolated arm."
                 if builtin_seen is not None
                 else "Built-ins identified from the static table for "
                      f"`{harness or 'unknown harness'}`; unrecognised names are "
                      "reported as unattributed, not as skills.") + "_", ""]
    lines += ["| Kind | What | Calls |", "|---|---|---|"]
    order = (BUILTIN_KIND, SKILL_KIND, MCP_KIND, SURFACE_KIND, UNKNOWN_KIND)
    for kind in order:
        for detail, n in sorted(kinds.get(kind, {}).items(), key=lambda kv: -kv[1]):
            lines.append(f"| {kind} | `{detail}` | {n} |")
    lines.append("")

    surface_calls = sum(sum(kinds.get(k, {}).values())
                        for k in (SKILL_KIND, MCP_KIND, SURFACE_KIND))
    if context:
        lines += ["Installed vs called:", ""]
        for field, value in context.items():
            lines.append(f"- **{field} installed**: {value}")
        lines.append("")
    if surface_calls == 0:
        lines += [
            "**The surface was idle.** Every call in this run was a built-in: no skill, "
            "MCP server or plugin was invoked. Whatever this run scored, the surface did "
            "not earn it — and anything it adds to the system prompt was paid for on "
            "every task for nothing.", "",
        ]
    else:
        lines += [f"**{surface_calls} of {total} calls came from the surface.** By task:",
                  ""]
        for task, names in sorted(per_task.items()):
            detail = ", ".join(f"`{n}` x{c}" for n, c in sorted(names.items()))
            lines.append(f"- `{task}` — {detail}")
        lines.append("")
    if kinds.get(SKILL_KIND):
        lines += ["Skill invocations are counted but not named: benchkit records the tool "
                  "name only, and the skill's identity lives in the tool-call input it "
                  "discards. See `references/surface-ab.md`.", ""]
    return lines


def render_ab(live, iso):
    """The 'what did the surface buy' section, live arm against isolated arm."""
    ls, is_ = live.get("summary") or {}, iso.get("summary") or {}
    lines = ["## Surface A/B — live vs isolated", "",
             "Same model, same suite, same samples. The live arm runs your daily "
             "surface; the isolated arm strips skills, MCP servers, plugins and "
             "settings.", "",
             "| Metric | live | isolated | delta |", "|---|---|---|---|"]
    for key, label, fmt, higher_better, places in _METRICS:
        lv, iv = ls.get(key), is_.get(key)
        if lv is None and iv is None:
            continue
        if lv is None or iv is None:
            delta = "n/a"
        else:
            d = (lv - iv) * (100 if fmt is _pct else 1)
            arrow = "" if d == 0 else (" ✓" if (d > 0) == higher_better else " ✗")
            delta = f"{d:+.{places}f}{arrow}"
        lines.append(f"| {label} | {fmt(lv)} | {fmt(iv)} | {delta} |")
    lines.append("")

    lv, iv = ls.get("agent_score"), is_.get("agent_score")
    samples = max((ls.get("config") or {}).get("samples") or 1,
                  (is_.get("config") or {}).get("samples") or 1)
    if lv is not None and iv is not None:
        gap = abs(lv - iv) * 100
        if gap < NOISE_POINTS:
            # Always ask for strictly more than was just run: recommending the
            # sample count the user already used reads as "do nothing".
            nxt = max(4, samples * 2)
            lines += [f"**Not a result.** The arms differ by {gap:.1f} points at "
                      f"{samples} sample(s); anything under {NOISE_POINTS:.0f} is noise "
                      f"in this benchmark. Re-run both arms at `--samples {nxt}` before "
                      f"concluding the surface helps or hurts.", ""]
        else:
            better = "live" if lv > iv else "isolated"
            lines += [f"The **{better}** arm is ahead by {gap:.1f} points at {samples} "
                      f"sample(s) — above the {NOISE_POINTS:.0f}-point noise floor, so "
                      f"the gap is real. Read it together with the surface usage above: "
                      f"a gap with an idle surface is not caused by the surface.", ""]
    lines += ["Caveat: on claude-code the isolated arm also pins the built-in tool set "
              "(no Task/WebSearch/WebFetch), so its arm differs by more than the surface "
              "alone. `references/surface-ab.md` lists what each harness strips.", ""]
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="surface_usage.py",
        description="Attribute a harness run's tool calls to skills, MCP and plugins, "
                    "and diff a live arm against an isolated one.")
    ap.add_argument("--live", required=True, help="result JSON of the live arm")
    ap.add_argument("--isolated", help="result JSON of the isolated arm (enables the A/B)")
    ap.add_argument("--context", help="collect_context.sh markdown, for installed counts")
    ap.add_argument("--json", action="store_true", dest="as_json",
                    help="emit the attribution as JSON instead of markdown")
    args = ap.parse_args(argv)

    for path in (args.live, args.isolated):
        if path and not os.path.exists(path):
            ap.error(f"no such result file: {path}")

    with open(args.live) as f:
        live = json.load(f)
    iso = None
    if args.isolated:
        with open(args.isolated) as f:
            iso = json.load(f)

    harness = harness_name(live)
    builtin_seen = set(tool_names(iso)) if iso is not None else None

    if args.as_json:
        kinds, per_task = tally(live, harness, builtin_seen)
        json.dump(dict(harness=harness, kinds=kinds, per_task=per_task,
                       builtin_from_isolated_arm=builtin_seen is not None),
                  sys.stdout, indent=2, sort_keys=True)
        print()
        return 0

    out = render_usage(live, harness, builtin_seen, installed(args.context)
                       if args.context else {})
    if iso is not None:
        out += render_ab(live, iso)
    print("\n".join(out).rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
