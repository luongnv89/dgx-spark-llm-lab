#!/usr/bin/env python3
"""Coding benchmark against a local ollama endpoint.

Same 16 tasks / hidden unit tests as coding-bench-2026-08-17, but adapted to
ollama's OpenAI-compatible endpoint: thinking is disabled with
reasoning_effort="none" (ollama silently ignores chat_template_kwargs and
think:false on /v1), and the reasoning text arrives on delta.reasoning.
"""
import concurrent.futures as cf
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench  # noqa: E402
from tasks import TASKS  # noqa: E402

THINKING = os.environ.get("BENCH_THINKING", "0") == "1"
MAX_TOKENS = int(os.environ.get("BENCH_MAX_TOKENS", "4000"))
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "1"))
SAMPLES = int(os.environ.get("BENCH_SAMPLES", "2"))
ONLY = set(os.environ["BENCH_ONLY"].split(",")) if os.environ.get("BENCH_ONLY") else None
OUT = os.environ.get("BENCH_OUT", "results_ollama.json")


def generate(task, idx):
    t0 = time.perf_counter()
    ttft = None
    chunks, reason_chunks = [], []
    usage = None
    kwargs = {}
    if not THINKING:
        kwargs["reasoning_effort"] = "none"
    stream = bench.client.chat.completions.create(
        model=bench.MODEL,
        messages=[
            {"role": "system", "content": bench.SYSTEM},
            {"role": "user", "content": task["prompt"]},
        ],
        max_tokens=MAX_TOKENS, stream=True,
        stream_options={"include_usage": True}, **kwargs,
    )
    ch = None
    for ch in stream:
        if ch.usage:
            usage = ch.usage
        if not ch.choices:
            continue
        d = ch.choices[0].delta
        piece = d.content or ""
        reasoning = (getattr(d, "reasoning", None)
                     or getattr(d, "reasoning_content", None) or "")
        if (piece or reasoning) and ttft is None:
            ttft = time.perf_counter() - t0
        chunks.append(piece)
        reason_chunks.append(reasoning)
    elapsed = time.perf_counter() - t0
    ct = getattr(usage, "completion_tokens", None) if usage else None
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
        print(f"  ERR   {task['id']:<18} s{i} {e}", flush=True)
        return dict(task=task["id"], difficulty=task["difficulty"], sample=i,
                    passed=False, error=str(e), truncated=None,
                    reasoning_chars=None, completion_tokens=None,
                    elapsed=None, ttft=None, tok_s=None)
    code = bench.extract_code(gen["text"])
    ok, err = bench.run_tests(task, code)
    gen.update(passed=ok, error=err, code=code)
    gen.pop("text")
    print(f"  {'PASS' if ok else 'FAIL'}  {task['id']:<18} s{i} "
          f"{gen['completion_tokens'] or 0:>6}tok {gen['elapsed']:.0f}s "
          f"{(gen['tok_s'] or 0):.1f}tok/s"
          f"{' TRUNCATED' if gen['truncated'] else ''}"
          + (f"  <{(err or '')[:70]}>" if not ok else ""), flush=True)
    return gen


tasks = [t for t in TASKS if ONLY is None or t["id"] in ONLY]
print(f"model={bench.MODEL} base={bench.BASE_URL} thinking={THINKING} "
      f"max_tokens={MAX_TOKENS} concurrency={CONCURRENCY} samples={SAMPLES} "
      f"tasks={len(tasks)}", flush=True)
items = [(t, i) for t in tasks for i in range(SAMPLES)]
t0 = time.perf_counter()
with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
    res = list(ex.map(work, items))
wall = time.perf_counter() - t0
by = {}
for r in res:
    by.setdefault(r["task"], []).append(r)
bydiff = {}
for r in res:
    bydiff.setdefault(r["difficulty"], []).append(r["passed"])
summary = dict(
    model=bench.MODEL, thinking=THINKING, max_tokens=MAX_TOKENS,
    concurrency=CONCURRENCY, generations=len(res),
    pass_at_1=sum(r["passed"] for r in res) / len(res),
    pass_any=sum(1 for v in by.values() if any(x["passed"] for x in v)) / len(by),
    by_difficulty={k: sum(v) / len(v) for k, v in bydiff.items()},
    truncated=sum(1 for r in res if r["truncated"]),
    errors=sum(1 for r in res if r.get("error") and r["completion_tokens"] is None),
    wall_seconds=wall,
    mean_completion_tokens=sum(r["completion_tokens"] or 0 for r in res) / len(res),
    mean_tok_s=(sum(r["tok_s"] or 0 for r in res)
                / max(1, sum(1 for r in res if r["tok_s"]))),
    mean_ttft=(sum(r["ttft"] or 0 for r in res)
               / max(1, sum(1 for r in res if r["ttft"]))),
)
json.dump(dict(summary=summary, results=res), open(OUT, "w"), indent=2)
print("\n" + json.dumps(summary, indent=2))
