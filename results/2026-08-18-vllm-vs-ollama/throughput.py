#!/usr/bin/env python3
"""Concurrency sweep: per-stream and aggregate decode throughput on ollama."""
import concurrent.futures as cf, json, os, time
from openai import OpenAI

c = OpenAI(base_url="http://localhost:11434/v1", api_key="none", timeout=1800)
MODEL = os.environ.get("BENCH_MODEL", "qwen3.8-27b-bench")
PROMPT = ("Write a Python implementation of a thread-safe LRU cache with get/put, "
          "then a binary search tree with insert/search/delete. Full code only.")


def one(i):
    t0 = time.perf_counter(); ttft = None; usage = None
    s = c.chat.completions.create(model=MODEL, reasoning_effort="none",
        messages=[{"role": "user", "content": PROMPT}], max_tokens=600,
        stream=True, stream_options={"include_usage": True})
    for ch in s:
        if ch.usage: usage = ch.usage
        if ch.choices and (ch.choices[0].delta.content or "") and ttft is None:
            ttft = time.perf_counter() - t0
    el = time.perf_counter() - t0
    ct = usage.completion_tokens
    return dict(ttft=ttft, elapsed=el, tokens=ct, tok_s=ct / el)


out = {}
for n in (1, 2, 4, 6):
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=n) as ex:
        rs = list(ex.map(one, range(n)))
    wall = time.perf_counter() - t0
    out[n] = dict(
        clients=n,
        per_stream_tok_s=sum(r["tok_s"] for r in rs) / n,
        aggregate_tok_s=sum(r["tokens"] for r in rs) / wall,
        mean_ttft=sum(r["ttft"] for r in rs) / n,
        max_ttft=max(r["ttft"] for r in rs),
        wall=wall,
    )
    print(json.dumps(out[n]), flush=True)
json.dump(out, open("throughput.json", "w"), indent=2)
