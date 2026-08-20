#!/usr/bin/env python3
"""Re-run selected tasks with a configurable token budget / thinking mode."""
import concurrent.futures as cf
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402
from tasks import TASKS  # noqa: E402

ONLY = set(os.environ["BENCH_ONLY"].split(","))
THINKING = os.environ.get("BENCH_THINKING", "1") == "1"
MAX_TOKENS = int(os.environ.get("BENCH_MAX_TOKENS", "32000"))
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "8"))
SAMPLES = int(os.environ.get("BENCH_SAMPLES", "2"))
OUT = os.environ.get("BENCH_OUT", "results2.json")


def generate(task, idx):
    t0 = time.perf_counter()
    ttft = None
    chunks = []
    reason_chunks = []
    usage = None
    kwargs = {}
    if not THINKING:
        kwargs["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    stream = bench.client.chat.completions.create(
        model=bench.MODEL,
        messages=[
            {"role": "system", "content": bench.SYSTEM},
            {"role": "user", "content": task["prompt"]},
        ],
        max_tokens=MAX_TOKENS, stream=True,
        stream_options={"include_usage": True}, **kwargs,
    )
    for ch in stream:
        if ch.usage:
            usage = ch.usage
        if not ch.choices:
            continue
        d = ch.choices[0].delta
        piece = d.content or ""
        reasoning = getattr(d, "reasoning_content", None) or ""
        if (piece or reasoning) and ttft is None:
            ttft = time.perf_counter() - t0
        chunks.append(piece)
        reason_chunks.append(reasoning)
    elapsed = time.perf_counter() - t0
    ct = getattr(usage, "completion_tokens", None) if usage else None
    finish = ch.choices[0].finish_reason if ch.choices else None
    return dict(
        task=task["id"], difficulty=task["difficulty"], sample=idx,
        text="".join(chunks), reasoning_chars=len("".join(reason_chunks)),
        ttft=ttft, elapsed=elapsed, completion_tokens=ct,
        tok_s=(ct / elapsed) if ct and elapsed else None,
        truncated=(ct is not None and ct >= MAX_TOKENS),
    )


def work(item):
    task, i = item
    try:
        gen = generate(task, i)
    except Exception as e:  # noqa: BLE001
        return dict(task=task["id"], difficulty=task["difficulty"], sample=i,
                    passed=False, error=str(e), truncated=None,
                    completion_tokens=None, elapsed=None, tok_s=None)
    code = bench.extract_code(gen["text"])
    ok, err = bench.run_tests(task, code)
    gen.update(passed=ok, error=err, code=code)
    gen.pop("text")
    print(f"  {'PASS' if ok else 'FAIL'}  {task['id']:<18} s{i} "
          f"{gen['completion_tokens'] or 0:>6}tok {gen['elapsed']:.0f}s "
          f"{(gen['tok_s'] or 0):.1f}tok/s"
          f"{' TRUNCATED' if gen['truncated'] else ''}"
          + (f"  <{err[:70]}>" if not ok else ""), flush=True)
    return gen


tasks = [t for t in TASKS if t["id"] in ONLY]
print(f"re-run: thinking={THINKING} max_tokens={MAX_TOKENS} "
      f"tasks={[t['id'] for t in tasks]}", flush=True)
items = [(t, i) for t in tasks for i in range(SAMPLES)]
t0 = time.perf_counter()
with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
    res = list(ex.map(work, items))
wall = time.perf_counter() - t0
by = {}
for r in res:
    by.setdefault(r["task"], []).append(r)
summary = dict(
    thinking=THINKING, max_tokens=MAX_TOKENS, generations=len(res),
    pass_at_1=sum(r["passed"] for r in res) / len(res),
    pass_any=sum(1 for v in by.values() if any(x["passed"] for x in v)) / len(by),
    truncated=sum(1 for r in res if r["truncated"]),
    wall_seconds=wall,
    mean_completion_tokens=sum(r["completion_tokens"] or 0 for r in res) / len(res),
)
json.dump(dict(summary=summary, results=res), open(OUT, "w"), indent=2)
print("\n" + json.dumps(summary, indent=2))
