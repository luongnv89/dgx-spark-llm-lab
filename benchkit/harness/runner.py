"""Run a suite through a real coding harness instead of benchkit's own tool loop."""
import concurrent.futures as cf
import time
from dataclasses import asdict

from ..agentic import loop as agentic_loop
from .base import run_task


def run(harness, tasks, cfg, on_result=None, timeout=900, keep_dirs=False):
    ok, detail = harness.available()
    if not ok:
        raise SystemExit(f"harness {harness.name!r} is not usable here: {detail}")

    def work(item):
        task, i = item
        r = run_task(harness, task, i, timeout=timeout, thinking=cfg.thinking,
                     keep_dir=keep_dirs)
        if on_result:
            on_result(r)
        return r

    items = [(t, i) for t in tasks for i in range(cfg.samples)]
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=cfg.concurrency) as ex:
        results = list(ex.map(work, items))
    wall = time.perf_counter() - t0

    summary = agentic_loop.summarize(results, cfg, wall, len(tasks))
    summary["harness"] = harness.describe()
    # A harness charges its own overhead — system prompt, tool schemas, context
    # resends — which is invisible in output tokens and dominates the bill.
    ins = [r.get("input_tokens") or 0 for r in results]
    summary["mean_input_tokens"] = sum(ins) / len(ins) if ins else None
    summary["total_input_tokens"] = sum(ins)
    reas = [r.get("reasoning_tokens") or 0 for r in results]
    summary["mean_reasoning_tokens"] = sum(reas) / len(reas) if reas else None
    summary["config"] = asdict(cfg)
    return summary, results
