"""Multi-turn agent loop: give the model tools, let it work, score the result.

Success is decided by the task's `check` over the final workspace, never by what
the model says it did. Alongside pass@1 the loop records tool hygiene — malformed
arguments, unknown tool names, failed calls — because a model that solves a task
by flailing through twenty calls is not the same as one that solves it in four.
"""
import concurrent.futures as cf
import json
import time
from dataclasses import asdict

from .env import Workspace, call
from .tools import TOOLS, SYSTEM

MAX_TURNS = 25

_PAR_CACHE = {}


def par_calls(task):
    """Minimum tool calls to solve the task, measured by running its oracle.

    This is the suite's ruler for effort. Two models that both solve everything
    are not equal, and par turns "how much flailing" into a number that does not
    depend on the model, the prompt, or the wall clock.
    """
    tid = task["id"]
    if tid not in _PAR_CACHE:
        ws = Workspace(task["files"])
        try:
            task["oracle"](ws)
            _PAR_CACHE[tid] = max(1, len(ws.calls))
        except Exception:  # noqa: BLE001 — a broken oracle is caught by `bench validate`
            _PAR_CACHE[tid] = None
    return _PAR_CACHE[tid]


def _args_of(tc):
    """Parse a tool call's arguments. Returns (args, malformed)."""
    raw = getattr(tc.function, "arguments", None) or "{}"
    try:
        args = json.loads(raw)
    except (ValueError, TypeError):
        return {}, True
    if not isinstance(args, dict):
        return {}, True
    return args, False


def run_task(client, cfg, task, sample, max_turns=MAX_TURNS):
    t0 = time.perf_counter()
    ws = Workspace(task["files"])
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": task["prompt"]}]
    turns = malformed = unknown = 0
    completion_tokens = 0
    stop_reason = "max_turns"
    error = ""

    try:
        for turns in range(1, max_turns + 1):
            kw = {}
            if cfg.temperature is not None:
                kw["temperature"] = cfg.temperature
            resp = client.chat.completions.create(
                model=cfg.model, messages=messages, tools=TOOLS, tool_choice="auto",
                max_tokens=cfg.max_tokens,
                extra_body={"chat_template_kwargs": {"enable_thinking": cfg.thinking,
                                                     "preserve_thinking": cfg.thinking}},
                **kw)
            if resp.usage:
                completion_tokens += resp.usage.completion_tokens or 0
            msg = resp.choices[0].message
            calls = msg.tool_calls or []
            messages.append({
                "role": "assistant",
                "content": msg.content or "",
                "tool_calls": [{"id": c.id, "type": "function",
                                "function": {"name": c.function.name,
                                             "arguments": c.function.arguments}}
                               for c in calls] or None,
            })
            if not calls:
                stop_reason = "no_tool_call"
                break
            for tc in calls:
                name = tc.function.name
                args, bad = _args_of(tc)
                if bad:
                    malformed += 1
                    out = ("error: arguments were not a JSON object. Send valid JSON "
                           "matching the tool's schema.")
                    ws.record(name, {"_raw": str(tc.function.arguments)[:200]}, False, out)
                else:
                    ok, out = call(ws, name, args)
                    if not ok and out.startswith("no such tool"):
                        unknown += 1
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": out})
            if ws.finished is not None:
                stop_reason = "finished"
                break
    except Exception as e:  # noqa: BLE001 — a dead backend must not kill the suite
        stop_reason = "error"
        error = f"{type(e).__name__}: {e}"

    elapsed = time.perf_counter() - t0
    try:
        solved, detail = task["check"](ws)
    except Exception as e:  # noqa: BLE001 — a broken predicate is a test bug, report it
        solved, detail = False, f"check raised {e!r}"

    total_calls = len(ws.calls)
    par = par_calls(task)
    # Efficiency only means something for a solved task: failing in three calls is
    # not efficient. Capped at 1.0 so beating par cannot inflate a weak run.
    efficiency = (min(1.0, par / total_calls) if (solved and par and total_calls) else
                  (1.0 if solved and not total_calls else None))
    return dict(
        par_calls=par, efficiency=efficiency,
        task=task["id"], difficulty=task["difficulty"], sample=sample,
        passed=bool(solved), error=error or ("" if solved else str(detail)[:200]),
        turns=turns, tool_calls=total_calls, failed_calls=ws.failed_calls,
        malformed_args=malformed, unknown_tools=unknown,
        valid_call_rate=((total_calls - ws.failed_calls) / total_calls) if total_calls else None,
        stop_reason=stop_reason, completion_tokens=completion_tokens, elapsed=elapsed,
        tok_s=(completion_tokens / elapsed) if completion_tokens and elapsed else None,
        ttft=None, trace=[c["tool"] for c in ws.calls],
    )


def run(tasks, cfg, on_result=None, max_turns=MAX_TURNS):
    from ..runner import _client
    client = _client(cfg)

    def work(item):
        task, i = item
        r = run_task(client, cfg, task, i, max_turns)
        if on_result:
            on_result(r)
        return r

    items = [(t, i) for t in tasks for i in range(cfg.samples)]
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=cfg.concurrency) as ex:
        results = list(ex.map(work, items))
    wall = time.perf_counter() - t0
    return summarize(results, cfg, wall, len(tasks)), results


def summarize(results, cfg, wall, n_tasks):
    by_task = {}
    for r in results:
        by_task.setdefault(r["task"], []).append(r)

    def mean(key):
        vals = [r[key] for r in results if r.get(key) is not None]
        return sum(vals) / len(vals) if vals else None

    def rate(pred):
        sel = [r for r in results if pred(r)]
        return (sum(1 for r in sel if r["passed"]) / len(sel)) if sel else None

    total_calls = sum(r["tool_calls"] for r in results)
    total_failed = sum(r["failed_calls"] for r in results)
    effs = [r["efficiency"] for r in results if r.get("efficiency") is not None]
    mean_eff = sum(effs) / len(effs) if effs else None
    solve = sum(1 for r in results if r["passed"]) / len(results) if results else 0.0
    # Solving is the price of entry; efficiency breaks the ties that solve rate
    # cannot. A model that solves everything in twice par scores 0.5, not 1.0.
    agent_score = solve * (mean_eff if mean_eff is not None else 0.0)
    return dict(
        kind="agentic", config=asdict(cfg), tasks=n_tasks, generations=len(results),
        pass_at_1=solve,
        agent_score=agent_score,
        mean_efficiency=mean_eff,
        mean_par_calls=(sum(r["par_calls"] for r in results if r.get("par_calls"))
                        / max(1, sum(1 for r in results if r.get("par_calls")))),
        pass_all_samples=sum(1 for v in by_task.values()
                             if all(r["passed"] for r in v)) / max(1, len(by_task)),
        pass_any_sample=sum(1 for v in by_task.values()
                            if any(r["passed"] for r in v)) / max(1, len(by_task)),
        wall_seconds=wall,
        mean_completion_tokens=mean("completion_tokens"),
        median_completion_tokens=(sorted(r["completion_tokens"] for r in results)[len(results) // 2]
                                  if results else None),
        mean_tok_s=mean("tok_s"), mean_ttft=None,
        aggregate_tok_s=(sum(r["completion_tokens"] for r in results) / wall) if wall else None,
        truncated=0,
        errored=sum(1 for r in results if r["stop_reason"] == "error"),
        # --- agentic-specific ---
        mean_turns=mean("turns"),
        mean_tool_calls=mean("tool_calls"),
        total_tool_calls=total_calls,
        valid_call_rate=((total_calls - total_failed) / total_calls) if total_calls else None,
        malformed_args=sum(r["malformed_args"] for r in results),
        unknown_tools=sum(r["unknown_tools"] for r in results),
        hit_turn_limit=sum(1 for r in results if r["stop_reason"] == "max_turns"),
        stalled_no_tool_call=sum(1 for r in results if r["stop_reason"] == "no_tool_call"),
        by_task={k: sum(1 for r in v if r["passed"]) / len(v) for k, v in sorted(by_task.items())},
        by_difficulty={d: rate(lambda r, d=d: r["difficulty"] == d)
                       for d in ("easy", "medium", "hard")},
    )


def validate(tasks):
    """Run each task's oracle and confirm its check then passes."""
    bad = 0
    for t in tasks:
        ws = Workspace(t["files"])
        try:
            t["oracle"](ws)
            ok, detail = t["check"](ws)
        except Exception as e:  # noqa: BLE001
            ok, detail = False, repr(e)
        print(f"  {'ok  ' if ok else 'FAIL'} {t['id']}")
        if not ok:
            bad += 1
            print(f"         {detail}")
    print(f"\n{len(tasks) - bad}/{len(tasks)} oracles solve their task")
    return bad
