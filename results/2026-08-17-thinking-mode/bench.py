#!/usr/bin/env python3
"""Coding benchmark against the local montimage-dgx-spark endpoint.

pass@1 over executable unit tests + latency/throughput stats.
"""
import concurrent.futures as cf
import json
import os
import re
import subprocess
import sys
import tempfile
import time

from openai import OpenAI

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from tasks import TASKS  # noqa: E402

BASE_URL = os.environ.get("BENCH_BASE_URL", "http://localhost:8001/v1")
MODEL = os.environ.get("BENCH_MODEL", "montimage-dgx-spark")
SAMPLES = int(os.environ.get("BENCH_SAMPLES", "2"))
CONCURRENCY = int(os.environ.get("BENCH_CONCURRENCY", "4"))
MAX_TOKENS = int(os.environ.get("BENCH_MAX_TOKENS", "6000"))
OUT = os.environ.get("BENCH_OUT", "results.json")

SYSTEM = (
    "You are an expert Python programmer. Answer with a single self-contained "
    "Python code block containing the requested function or class and any imports "
    "it needs. No explanation, no tests, no example usage."
)

client = OpenAI(base_url=BASE_URL, api_key="none", timeout=1800)

CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


def extract_code(text: str) -> str:
    blocks = CODE_RE.findall(text or "")
    if blocks:
        return max(blocks, key=len)
    return text or ""


def generate(task, idx):
    t0 = time.perf_counter()
    ttft = None
    chunks = []
    usage = None
    stream = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": task["prompt"]},
        ],
        max_tokens=MAX_TOKENS,
        stream=True,
        stream_options={"include_usage": True},
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
    elapsed = time.perf_counter() - t0
    text = "".join(chunks)
    ct = getattr(usage, "completion_tokens", None) if usage else None
    return dict(
        task=task["id"], difficulty=task["difficulty"], sample=idx,
        text=text, ttft=ttft, elapsed=elapsed,
        prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
        completion_tokens=ct,
        tok_s=(ct / elapsed) if ct and elapsed else None,
    )


def run_tests(task, code):
    prog = code + "\n\n" + task["tests"] + "\nprint('PASS')\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(prog)
        path = f.name
    try:
        p = subprocess.run(
            [sys.executable, path], capture_output=True, text=True, timeout=30,
            cwd=tempfile.gettempdir(),
        )
        ok = p.returncode == 0 and "PASS" in p.stdout
        err = (p.stderr or "").strip().splitlines()
        return ok, (err[-1] if err else "")
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT (30s)"
    finally:
        os.unlink(path)


def work(item):
    task, i = item
    try:
        gen = generate(task, i)
    except Exception as e:  # noqa: BLE001
        return dict(task=task["id"], difficulty=task["difficulty"], sample=i,
                    passed=False, error=f"generation failed: {e}", tok_s=None,
                    ttft=None, elapsed=None, completion_tokens=None)
    code = extract_code(gen["text"])
    ok, err = run_tests(task, code)
    gen.update(passed=ok, error=err, code=code)
    gen.pop("text")
    print(f"  {'PASS' if ok else 'FAIL'}  {task['id']:<18} s{i} "
          f"{gen['completion_tokens'] or 0:>5}tok "
          f"{gen['elapsed']:.1f}s "
          f"{(gen['tok_s'] or 0):.1f}tok/s"
          + (f"  <{err[:70]}>" if not ok else ""), flush=True)
    return gen


def single_stream_probe():
    """Isolated single-request throughput measurement (no concurrency)."""
    t = TASKS[0]
    r = generate(t, -1)
    return r


def main():
    print(f"endpoint={BASE_URL} model={MODEL} tasks={len(TASKS)} "
          f"samples={SAMPLES} concurrency={CONCURRENCY}\n", flush=True)

    print("Single-stream probe (warm, no concurrency)...", flush=True)
    probe = single_stream_probe()
    print(f"  ttft={probe['ttft']:.2f}s  gen={probe['completion_tokens']}tok  "
          f"{probe['tok_s']:.1f} tok/s\n", flush=True)

    items = [(t, i) for t in TASKS for i in range(SAMPLES)]
    t0 = time.perf_counter()
    with cf.ThreadPoolExecutor(max_workers=CONCURRENCY) as ex:
        results = list(ex.map(work, items))
    wall = time.perf_counter() - t0

    by_task = {}
    for r in results:
        by_task.setdefault(r["task"], []).append(r)

    n_pass = sum(1 for r in results if r["passed"])
    toks = [r["completion_tokens"] for r in results if r["completion_tokens"]]
    tps = [r["tok_s"] for r in results if r["tok_s"]]
    ttfts = [r["ttft"] for r in results if r["ttft"]]

    summary = dict(
        model=MODEL, endpoint=BASE_URL, tasks=len(TASKS), samples=SAMPLES,
        concurrency=CONCURRENCY, generations=len(results),
        pass_at_1=n_pass / len(results),
        pass_all_samples=sum(1 for v in by_task.values() if all(r["passed"] for r in v)) / len(by_task),
        pass_any_sample=sum(1 for v in by_task.values() if any(r["passed"] for r in v)) / len(by_task),
        wall_seconds=wall,
        single_stream_tok_s=probe["tok_s"], single_stream_ttft=probe["ttft"],
        mean_completion_tokens=sum(toks) / len(toks) if toks else None,
        median_completion_tokens=sorted(toks)[len(toks) // 2] if toks else None,
        mean_tok_s_concurrent=sum(tps) / len(tps) if tps else None,
        aggregate_tok_s=sum(toks) / wall if toks else None,
        mean_ttft=sum(ttfts) / len(ttfts) if ttfts else None,
        by_difficulty={
            d: sum(1 for r in results if r["difficulty"] == d and r["passed"])
               / max(1, sum(1 for r in results if r["difficulty"] == d))
            for d in ("easy", "medium", "hard")
        },
    )
    with open(OUT, "w") as f:
        json.dump(dict(summary=summary, results=results), f, indent=2)

    print("\n" + "=" * 60)
    for k, v in summary.items():
        print(f"{k:>28}: {v}")
    print("=" * 60)
    print(f"\nwritten to {OUT}")


if __name__ == "__main__":
    main()
