"""Actionable suggestions from a run's own numbers — no model calls, pure heuristics.

`bench setup run` (issue #76) measures a live harness setup and then has to say
something *useful* about it. The signals already exist in every summary:
`summarize()` in benchkit/agentic/loop.py and the fields the harness runner adds
(`mean_input_tokens`, the `harness` describe block). This module reads those and
emits Markdown suggestions, each tied to the number that triggered it.

Every rule is deliberately conservative: it fires on a threshold crossed, not on
a vibe, and it always names the metric so the reader can check it.
"""

#: mean input tokens per task above which context bloat is worth calling out.
#: A harness resends its whole context every turn; skills and MCP servers are
#: billed through this number even when they never help solve anything.
INPUT_TOKEN_BLOAT = 50_000

#: valid-call rate below which tool schemas are probably mismatched
LOW_VALID_RATE = 0.90

#: solved tasks using more than this multiple of par are wasting turns
INEFFICIENCY_RATIO = 1.5

#: reasoning tokens per task that suggest the thinking budget dominates
REASONING_TOKEN_HEAVY = 8_000


def build(summary):
    """Markdown suggestion bullets for one agentic summary dict.

    Returns [] when nothing crosses a threshold — silence is better than
    padding a good run with filler.
    """
    s = summary
    tips: list[str] = []
    live = _is_live(s)

    ins = s.get("mean_input_tokens")
    if ins and ins > INPUT_TOKEN_BLOAT:
        tips.append(
            f"Mean input tokens is **{ins:,.0f} per task** — context is being "
            "resent every turn. In a "
            + ("live setup, audit installed **skills and MCP servers**: each "
               "one's prompt/schema rides along on every call even when unused. "
               "Disable what this work does not need."
               if live else
               "harness, check system-prompt size and how much history is "
               "resend per turn."))

    if s.get("hit_turn_limit"):
        tips.append(
            f"**{s['hit_turn_limit']} task(s) hit the turn limit** without "
            "finishing. Either the budget is too small for this suite or the "
            "harness is missing a tool the tasks need — check which tools the "
            "harness exposes against what the tasks require.")

    if s.get("stalled_no_tool_call"):
        tips.append(
            f"**{s['stalled_no_tool_call']} task(s) stalled with no tool call**. "
            "That usually means the model replied in prose where a tool was "
            "expected — often a chat-template or tool-call-parser mismatch "
            "rather than model inability.")

    rate = s.get("valid_call_rate")
    if rate is not None and rate < LOW_VALID_RATE:
        tips.append(
            f"Valid tool-call rate is **{rate * 100:.1f} %** — many calls error. "
            "Check the harness's tool-call parser / schema wiring against the "
            "model's expected format before blaming the model.")

    par, calls = s.get("mean_par_calls"), s.get("mean_tool_calls")
    if par and calls and calls > par * INEFFICIENCY_RATIO:
        tips.append(
            f"Tasks use **{calls:.1f} tool calls against a par of {par:.1f}**. "
            "In a live setup, verbose skills or an over-eager MCP server can "
            "push the agent into exploratory calls; trimming instructions "
            "usually recovers most of the gap.")

    reas = s.get("mean_reasoning_tokens")
    if reas and reas > REASONING_TOKEN_HEAVY:
        tips.append(
            f"Mean reasoning tokens is **{reas:,.0f} per task** — thinking "
            "dominates the wall-clock. Consider a lower thinking level for "
            "tool-loop work unless accuracy demands it.")

    errs = s.get("errored")
    if errs:
        tips.append(
            f"**{errs} generation(s) errored** outright. Check the harness "
            "block's `detail` field in the result file — an adapter-level "
            "failure is a wiring problem, not a model failure.")

    hard = (s.get("by_difficulty") or {}).get("hard")
    easy = (s.get("by_difficulty") or {}).get("easy")
    if hard is not None and easy is not None and easy - hard > 0.4:
        tips.append(
            f"Hard-task solve rate (**{hard * 100:.0f} %**) trails easy tasks "
            f"({easy * 100:.0f} %) by a wide margin — the ceiling here is "
            "capability, not configuration. More samples will not close it.")

    if live:
        tips.append(
            "This was a **live-mode** run of your daily setup: extensions, "
            "skills and MCP servers were enabled. Any component that can call "
            "another model contaminates these numbers — see the caveats section.")
    return tips


def section(summary, title="Suggestions"):
    """The full Markdown section, or [] when there is nothing to suggest."""
    tips = build(summary)
    if not tips:
        return [f"## {title}\n", "Nothing crossed a threshold — the setup looks "
                "healthy on every signal measured.\n"]
    out = [f"## {title}\n"]
    out.extend(f"- {t}" for t in tips)
    out.append("")
    return out


def _is_live(summary):
    """Was this run in live mode? Read from either place it may be stamped."""
    cfg = summary.get("config") or {}
    if cfg.get("extra", {}).get("live") or cfg.get("live"):
        return True
    return bool((summary.get("harness") or {}).get("live"))
