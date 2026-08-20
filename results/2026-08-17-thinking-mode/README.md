# Coding benchmark — montimage-dgx-spark, 2026-08-17

Model under test: `unsloth/Qwen3.8-27B-NVFP4` served as `montimage-dgx-spark`
via vLLM 0.27.1 (aarch64 docker) on 127.0.0.1:8801, fronted by llm-router on :8001.
dspark speculative decoding (7 draft tokens), 262k ctx, thinking enabled by default.

## Benchmark

16 hand-written Python coding tasks with hidden executable unit tests
(easy / medium / hard): algorithms, data structures (LRU cache, sliding-window
rate limiter), parsing (SQL, arithmetic expression, version strings), and Python
idiom (decorator preserving `__name__`, LCS-based line diff).

All 16 test suites were first validated against reference solutions
(`validate.py`, 16/16 ok), so a failure means the model failed — not the test.

2 samples per task, code extracted from the response's largest fenced block and
executed in a subprocess with a 30 s timeout.

## Results

| Config | pass@1 | Suite wall time | Mean output tokens |
|---|---|---|---|
| Thinking ON, 6k cap (deployment default) | 62.5 % | 1365 s | 2 934 |
| Thinking ON, 32k cap | ~90.6 % (29/32) | ~4100 s | 17 430 (on the hard 7) |
| **Thinking OFF, 4k cap** | **96.9 %** | **42 s** | **226** |

By difficulty, thinking ON @ 6k: easy 100 %, medium 64 %, hard 30 %.

### The headline

Thinking mode is counterproductive for this workload. Every failure at the 6k cap
was truncation *inside the reasoning block* — the model never emitted code. Raising
the budget to 32k recovers most of them, but at absurd cost:

- `topo_sort`: 21 512 tokens / 22.5 min with thinking → 225 tokens / 8 s without. Both pass.
- `flatten_json`: 14 356 tokens → 216 tokens. Both pass.
- `diff_lines`: 31 791 tokens → 517 tokens. Both pass.
- `expr_eval` (both samples) and `sql_parse` (one sample) never terminated even at
  32k tokens — genuine runaway reasoning, not a budget artifact.

Reasoning length is also wildly variable for a fixed prompt: `retry_decorator`
took 1 110 tokens on one sample and 5 469 on another; `sql_parse` finished at
5 337 on one sample and blew past 32 000 on another.

The single thinking-off failure (`expr_eval`, 1 of 32) is a real bug: the tokenizer
handles decimals but `parse_primary` rejects them, so `-(2.5 * 2)` raises.

### Throughput

- Single-stream: 25.2 tok/s, TTFT 11.7 s (cold-ish, 341-token generation)
- 4 concurrent: ~21 tok/s per stream, 68.8 tok/s aggregate
- Thinking off, 8 concurrent: 20–36 tok/s per stream
- dspark speculative decoding: mean acceptance length ~2.3–2.9, draft acceptance ~19–27 %

## Recommendation

For coding-agent use, disable thinking by default:

```
--default-chat-template-kwargs {"enable_thinking":false,"preserve_thinking":false}
```

or have clients send `chat_template_kwargs: {"enable_thinking": false}`. Same
accuracy or better, ~13x fewer output tokens, ~32x lower wall-clock on this suite.
If thinking stays on, budget at least 32k output tokens and expect occasional
non-termination.

## Caveat

The first 32k re-run was invalidated when `llm-router.service` was restarted
externally at 08:55:38, killing in-flight streams (12/14 connection errors). The
reported 32k numbers come from a clean re-run against vLLM on :8801 directly.

## Files

- `tasks.py` — the 16 tasks + hidden tests
- `validate.py` — reference solutions, proves the tests are passable
- `bench.py` — main runner (pass@1 + latency/throughput)
- `bench2.py` — re-runner with task filter / thinking toggle / token budget
- `results.json`, `think6k.log` — thinking ON @ 6k
- `results_think32k.json`, `think32k.log` — thinking ON @ 32k
- `results_nothink.json`, `nothink.log` — thinking OFF @ 4k

Reproduce:

```bash
cd ~/llm-serving/benchmarks/coding-bench-2026-08-17
python3 validate.py
BENCH_BASE_URL=http://localhost:8801/v1 python3 -u bench.py
```
