"""Run a suite against an OpenAI-compatible endpoint and score it.

Scoring is pass@1 over hidden unit tests: the model's largest fenced code block
is extracted, the task's tests are appended, and the whole thing runs in a
subprocess with a timeout. Anything that does not print PASS is a failure.
"""
import concurrent.futures as cf
import os
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field, asdict

SYSTEM = (
    "You are an expert Python programmer. Answer with a single self-contained "
    "Python code block containing the requested function or class and any imports "
    "it needs. No explanation, no tests, no example usage."
)

CODE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.S)


@dataclass
class Config:
    base_url: str = "http://localhost:8001/v1"
    model: str = "montimage-dgx-spark"
    label: str = ""            # human name for this run, e.g. "Ornith-1.5 think-ON"
    thinking: bool = False
    max_tokens: int = 6000
    samples: int = 2
    concurrency: int = 4
    test_timeout: int = 60
    temperature: float | None = None
    # --- setup attribution: which *setup* produced this run, not just which
    # model. A ranked cross-setup table needs something to key on, and a result
    # file that does not name its serving config and harness cannot be ranked
    # against one that used a different pair (issue #57).
    serving_config: str = ""   # configs/<name>.sh active during the run
    harness: str = ""          # harness name, or "" for benchkit's own loop
    extra: dict = field(default_factory=dict)

    @classmethod
    def from_env(cls, **over):
        e = os.environ.get
        c = cls(
            base_url=e("BENCH_BASE_URL", cls.base_url),
            model=e("BENCH_MODEL", cls.model),
            thinking=e("BENCH_THINKING", "0") not in ("0", "false", "False", ""),
            max_tokens=int(e("BENCH_MAX_TOKENS", cls.max_tokens)),
            samples=int(e("BENCH_SAMPLES", cls.samples)),
            concurrency=int(e("BENCH_CONCURRENCY", cls.concurrency)),
            test_timeout=int(e("BENCH_TEST_TIMEOUT", cls.test_timeout)),
        )
        for k, v in over.items():
            if v is not None:
                setattr(c, k, v)
        return c


def extract_code(text):
    blocks = CODE_RE.findall(text or "")
    return max(blocks, key=len) if blocks else (text or "")


def run_tests(task, code, timeout):
    prog = code + "\n\n" + task["tests"] + "\nprint('PASS')\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as f:
        f.write(prog)
        path = f.name
    try:
        p = subprocess.run([sys.executable, path], capture_output=True, text=True,
                           timeout=timeout, cwd=tempfile.gettempdir())
        ok = p.returncode == 0 and "PASS" in p.stdout
        err = (p.stderr or "").strip().splitlines()
        return ok, (err[-1] if err else "")
    except subprocess.TimeoutExpired:
        return False, f"TIMEOUT ({timeout}s)"
    finally:
        os.unlink(path)


def _client(cfg):
    from openai import OpenAI
    return OpenAI(base_url=cfg.base_url, api_key="none", timeout=1800)


def generate(client, cfg, task, idx):
    t0 = time.perf_counter()
    ttft, chunks, usage = None, [], None
    kw = {}
    if cfg.temperature is not None:
        kw["temperature"] = cfg.temperature
    stream = client.chat.completions.create(
        model=cfg.model,
        messages=[{"role": "system", "content": SYSTEM},
                  {"role": "user", "content": task["prompt"]}],
        max_tokens=cfg.max_tokens,
        extra_body={"chat_template_kwargs": {"enable_thinking": cfg.thinking,
                                             "preserve_thinking": cfg.thinking}},
        stream=True, stream_options={"include_usage": True}, **kw,
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
    ct = getattr(usage, "completion_tokens", None) if usage else None
    return dict(task=task["id"], difficulty=task["difficulty"], sample=idx,
                text="".join(chunks), ttft=ttft, elapsed=elapsed,
                prompt_tokens=getattr(usage, "prompt_tokens", None) if usage else None,
                completion_tokens=ct,
                tok_s=(ct / elapsed) if ct and elapsed else None)


def run(tasks, cfg, on_result=None, keep_code=False):
    """Run every task `cfg.samples` times. Returns (summary, results)."""
    client = _client(cfg)

    def work(item):
        task, i = item
        try:
            gen = generate(client, cfg, task, i)
        except Exception as e:  # noqa: BLE001 — a dead backend must not kill the suite
            r = dict(task=task["id"], difficulty=task["difficulty"], sample=i,
                     passed=False, error=f"generation failed: {e}", tok_s=None,
                     ttft=None, elapsed=None, completion_tokens=None)
            if on_result:
                on_result(r)
            return r
        code = extract_code(gen["text"])
        ok, err = run_tests(task, code, cfg.test_timeout)
        gen.update(passed=ok, error=err)
        gen.pop("text")
        if keep_code:
            gen["code"] = code
        if on_result:
            on_result(gen)
        return gen

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
    toks = [r["completion_tokens"] for r in results if r["completion_tokens"]]
    tps = [r["tok_s"] for r in results if r["tok_s"]]
    ttfts = [r["ttft"] for r in results if r["ttft"]]
    n_pass = sum(1 for r in results if r["passed"])

    def rate(pred):
        sel = [r for r in results if pred(r)]
        return (sum(1 for r in sel if r["passed"]) / len(sel)) if sel else None

    return dict(
        config=asdict(cfg), tasks=n_tasks, generations=len(results),
        pass_at_1=n_pass / len(results) if results else 0.0,
        pass_all_samples=sum(1 for v in by_task.values()
                             if all(r["passed"] for r in v)) / max(1, len(by_task)),
        pass_any_sample=sum(1 for v in by_task.values()
                            if any(r["passed"] for r in v)) / max(1, len(by_task)),
        wall_seconds=wall,
        mean_completion_tokens=sum(toks) / len(toks) if toks else None,
        median_completion_tokens=sorted(toks)[len(toks) // 2] if toks else None,
        mean_tok_s=sum(tps) / len(tps) if tps else None,
        aggregate_tok_s=sum(toks) / wall if toks else None,
        mean_ttft=sum(ttfts) / len(ttfts) if ttfts else None,
        truncated=sum(1 for r in results if r.get("completion_tokens")
                      and r["completion_tokens"] >= cfg.max_tokens - 2),
        errored=sum(1 for r in results if str(r.get("error", "")).startswith("generation failed")),
        by_task={k: sum(1 for r in v if r["passed"]) / len(v)
                 for k, v in sorted(by_task.items())},
        by_difficulty={d: rate(lambda r, d=d: r["difficulty"] == d)
                       for d in ("easy", "medium", "hard")},
    )
