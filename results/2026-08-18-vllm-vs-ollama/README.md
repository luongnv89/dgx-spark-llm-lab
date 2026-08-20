# Coding benchmark — Qwen3.8-27B on ollama, GB10 (dgx-spark), 2026-08-18

Model under test: `qwen3.8:27b` (ollama default tag = Q4, 17 GB) served by
ollama 0.32.14 on 127.0.0.1:11434, 100 % GPU offload, NVIDIA GB10.

Benchmarked as a derived model `qwen3.8-27b-bench` (`Modelfile.bench`) whose only
change is `PARAMETER num_ctx 16384` — the stock tag defaults to **num_ctx 4096**,
which silently truncates any thinking-heavy generation.

Same 16 hand-written Python tasks with hidden executable unit tests as
`../coding-bench-2026-08-17` (vLLM/NVFP4). `validate.py` re-run here: 16/16 suites
pass against reference solutions, so a failure means the model failed.
2 samples per task = 32 generations per config, run sequentially (concurrency 1)
because ollama serializes requests anyway.

## Results

| Config | pass@1 | Suite wall | Mean output tokens | Decode | TTFT |
|---|---|---|---|---|---|
| Thinking ON (ollama default) @ 6k cap | **96.9 %** (31/32) | 1033 s | 940 | 29.0 tok/s | 0.93 s |
| Thinking OFF (`reasoning_effort:"none"`) @ 4k cap | 93.8 % (30/32) | 263 s | 251 | 30.3 tok/s | 0.63 s |

pass_any = 100 % in both configs — every task passes on at least one sample.
Zero truncations, zero connection errors in both runs.

By difficulty — thinking ON: easy 100 %, medium 92.9 %, hard 100 %.
Thinking OFF: easy 100 %, medium 100 %, hard 80 %.

### Failures

- Thinking OFF: `expr_eval` s0 (`ValueError: Unexpected token at position 0` — the
  tokenizer accepts decimals but `parse_primary` rejects them; the *same* bug the
  vLLM run hit) and `rate_limiter` s1 (`AttributeError: 'list' object has no
  attribute 'popleft'` — built a `list` then used it as a `deque`).
- Thinking ON: `sql_parse` s0 (`TypeError: first argument must be string or
  compiled pattern`).

### Thinking behaviour differs sharply from vLLM

ollama's `qwen3.8` renderer produces **far shorter** reasoning than vLLM's
`enable_thinking:true` chat template: mean 2 416 reasoning chars / 940 completion
tokens, max 14 841 chars. On vLLM the same suite averaged 2 934 output tokens at
the 6k cap and 17 430 on the hard tasks at 32k, with runaway non-termination on
`expr_eval` and `sql_parse`. Here nothing ran away — the worst case was
`diff_lines` s0 at 5 721 tokens / 203 s, and it still finished and passed.

So the "thinking is catastrophic for coding" result from 2026-08-17 is a
**vLLM-template** effect more than a model property. Under ollama, thinking costs
~3.7x the tokens and ~3.9x the wall-clock for +3.1 pp pass@1 (one task) —
a real but much less dramatic trade.

### Throughput (`throughput.py`, thinking off, 600-token generations)

| Clients | Per-stream tok/s | Aggregate tok/s | Mean TTFT | Max TTFT |
|---|---|---|---|---|
| 1 | 30.4 | 30.4 | 0.87 s | 0.87 s |
| 2 | 24.4 | 30.9 | 9.4 s | 18.3 s |
| 4 | 17.3 | 32.7 | 27.4 s | 54.1 s |
| 6 | 12.5 | 32.5 | 47.8 s | 93.0 s |

Aggregate throughput is **flat at ~31-33 tok/s** from 1 to 6 clients: ollama runs
`-np 1`, so requests serialize and extra clients only inflate TTFT (0.87 s → 93 s).
Fine for a single interactive coding agent, unusable for a shared endpoint.

## Comparison with other backends, same model family

| Backend | Model | Decode (single stream) |
|---|---|---|
| ollama Q4 (this run) | Qwen3.8-27B | **30.4 tok/s** |
| llama.cpp Q4_K_M (2026-08-15) | Qwen3.8-27B | 11.6 tok/s |
| vLLM NVFP4 (2026-08-17) | Qwen3.8-27B | 25.2 tok/s |

The llama.cpp number was measured with vLLM resident (~84 GB VRAM held, bandwidth
contention); this run had the box to itself, so it is not a clean backend
comparison — but ollama on an idle GB10 is clearly in the 30 tok/s class for this
dense 27B, not the 11 tok/s class.

## Gotchas hit

1. **ollama cached a CPU-only device list.** GPU discovery ran at boot while
   `vllm-qwen` owned the memory pool and aborted with `CUDA error: out of memory`;
   ollama then recorded `inference compute id=cpu` and ran the 27B entirely on CPU
   (74 s for a 23-token reply). `sudo systemctl restart ollama` after stopping the
   container fixed it — re-discovery reports `library=CUDA name="NVIDIA GB10"`.
   Always restart ollama after freeing GPU memory.
2. **num_ctx defaults to 4096**, not the model's context length.
3. Only `reasoning_effort:"none"` disables thinking on `/v1`; `think:false` and
   `chat_template_kwargs` are silently ignored (confirmed again here).

## Files

- `tasks.py`, `validate.py`, `bench.py` — copied unchanged from `../coding-bench-2026-08-17`
- `bench_ollama.py` — runner adapted for ollama (`reasoning_effort`, `delta.reasoning`)
- `Modelfile.bench` — `qwen3.8:27b` + `num_ctx 16384`
- `throughput.py`, `throughput.json` — concurrency sweep
- `results_nothink.json` / `nothink.log`, `results_think6k.json` / `think6k.log`

Reproduce:

```bash
cd ~/llm-serving/benchmarks/coding-bench-ollama-2026-08-18
ollama create qwen3.8-27b-bench -f Modelfile.bench
python3 validate.py
BENCH_BASE_URL=http://localhost:11434/v1 BENCH_MODEL=qwen3.8-27b-bench \
  BENCH_THINKING=0 BENCH_MAX_TOKENS=4000 BENCH_CONCURRENCY=1 \
  BENCH_OUT=results_nothink.json python3 -u bench_ollama.py
```
