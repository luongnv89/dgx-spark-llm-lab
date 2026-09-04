# Known-good serving configs

Each file here is a complete, working `vllm serve` invocation that has been run and
benchmarked on the hardware below. Pick one, install it, restart — you have a server.

```bash
./bench configs                              # list them
./bench apply qwen3.6-35b-a3b-nvfp4          # install as start-qwen.sh
./bench apply qwen3.6-35b-a3b-nvfp4 --restart   # ...and restart the service
```

`apply` copies the recipe over `start-qwen.sh`, which is what the `vllm-qwen`
systemd unit executes. Nothing else changes: same port, same
`--served-model-name`, so clients never notice a swap.

## Reference hardware

NVIDIA **DGX Spark (GB10)** — 119 GB unified CPU/GPU memory, 20 ARM cores
(Cortex-X925 + A725), CUDA arch `sm_121a`. On different hardware treat
`--gpu-memory-utilization`, `--max-model-len` and the backend flags as starting
points, not gospel.

## The recipes

| Config | Model | Quant | VRAM budget | Image digest | Measured | Use it when |
|---|---|---|---|---|---|---|
| `qwen3.6-35b-a3b-nvfp4` | Qwen3.6-35B-A3B | NVFP4 | 0.62 (~74 GB) | `@sha256:1962734…` | **82.1 % pass@1**, **100 % agentic**, 47.8 tok/s | **Current winner.** Best accuracy/latency mix for coding agents |
| `ornith-1.5-35b-a3b-nvfp4` | Ornith-1.5-35B-A3B | NVFP4 | 0.62 (~74 GB) | `@sha256:1962734…` | 80.4 % pass@1, 38.9 tok/s | Runner-up. Fewer output tokens per answer, but it collapses without its reasoning block |
| `qwen3.8-27b-nvfp4-dspark` | Qwen3.8-27B (dense) | NVFP4 | 0.70 | `v0.27.1-aarch64` | 96.9 % on core16 only | Dense-model comparison; much slower TTFT for agent loops |
| `qwen3.8-27b-nvfp4-tunable` | Qwen3.8-27B (dense) | NVFP4 | env-tunable | — | — | Sweeping speculative-decoding settings (`K`, `DRAFTER`, `SPEC`) |
| `gemma4-12b-w4a16` | Gemma 4 12B | QAT W4A16 | 0.16 | built from `@sha256:1962734…` | — | Small secondary backend alongside the primary, on port 8802 |
| `llamacpp-qwen3.8-27b-bench.sh` | Qwen3.8-27B GGUF | Q4_K_M | — | ~11.6 tok/s | — | llama.cpp comparison, not a vLLM recipe |
| (no recipe — evaluated, not adopted) | Qwen3.8-Flash-Next NVFP4 (Mia-AiLab, 99 GB, PLE-offload, solo tenant) | NVFP4+MXFP8 | ~100 GB, KV cut 22→18 GiB to fit | `vllm/vllm-openai:qwen38-flash-next` | 87.5 % think-OFF / 58.9 % think-ON / 87.5 % agentic-OFF / 87.5 % agentic-ON — see [`../results/2026-09-04/REPORT-flash-next-analysis.md`](../results/2026-09-04/REPORT-flash-next-analysis.md) | **Not adopted.** Only win is think-OFF (+7pp, noise); loses think-ON and both agentic modes, 2–3× slower, shipped defaults fail this box's safety check |

"Measured" links to the campaign in [`../results/`](../results/) that produced it.
Where a cell is blank, that config has not been put through the coding suite.

## Which recipes `bench sweep` can drive

`bench sweep` installs a recipe over `start-qwen.sh` and restarts the `vllm-qwen` systemd
unit, so a recipe is sweepable only if it declares a literal `MODEL_ID="..."` (the one line
`serving.py` can read back and report) **and** `NAME="vllm-qwen"` (the unit that actually
gets restarted). `bench configs` marks the rest and says why:

| Config | Sweepable | Why not |
|---|---|---|
| `qwen3.6-35b-a3b-nvfp4` | yes | — |
| `ornith-1.5-35b-a3b-nvfp4` | yes | — |
| `qwen3.8-27b-nvfp4-dspark` | yes | — |
| `qwen3.8-27b-nvfp4-tunable` | no | No `MODEL_ID=` line (it parameterises `MODEL=` instead) — the reason `bench configs` prints. It also runs as `qwen38-4bit` on port 8002, a standalone server for sweeping `K`/`DRAFTER`/`SPEC` by hand |
| `gemma4-12b-w4a16` | no | Runs as `vllm-gemma` on port 8802 — a secondary backend, so restarting `vllm-qwen` would not serve it |
| `llamacpp-qwen3.8-27b-bench` | no | llama.cpp, not vLLM, and no `MODEL_ID=` line at all |

None of that makes them bad recipes. To make one sweepable, give it a literal
`MODEL_ID="..."` and `NAME="vllm-qwen"` — that is all the sweep machinery reads.

## What makes these configs non-obvious

- **MoE models need the `mia-vllm-gb10-linear-b12x` image** plus `--moe-backend` and
  `--linear-backend flashinfer_b12x`. The stock aarch64 image will not serve them well.
  The dense Qwen3.8 recipe's flags are *not* interchangeable with the MoE ones.
- **MTP speculative decoding** (`--speculative-config '{"method":"mtp",...}'`) needs MTP
  weights in the checkpoint. Check `model.safetensors.index.json` for `mtp.` keys before
  enabling it, or startup fails.
- **`--gpu-memory-utilization` is a fraction of the whole unified pool**, not of free
  memory. Two backends must sum to well under 1.0.
- **Draft slots come out of the batch token budget.** `k * max_num_seqs` above
  `--max-num-batched-tokens` makes the scheduler's token count negative at startup.
- **Thinking defaults matter more than any flag, and the right default depends on the
  workload.** For one-shot code generation `enable_thinking: false` is the single biggest
  win; for multi-turn tool loops thinking is free and cuts turns by a quarter. See the
  campaign reports.
- **Tool calling needs its own flags.** `--enable-auto-tool-choice` plus a
  `--tool-call-parser` that matches the model's template, or the `agentic` suite scores
  zero for reasons that have nothing to do with the model.

## Adding your own

Copy the closest recipe, change `MODEL_ID`, benchmark it, and add a row above with the
result. A config without a measured row is a guess, not a known-good config.
