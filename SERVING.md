# Local LLM serving (DGX Spark / GB10)

Single OpenAI-compatible endpoint on **port 8001**, unchanged for clients:

```
base_url: http://<host>:8001/v1
model:    montimage-dgx-spark      # Qwen3.6-35B-A3B-NVFP4 (MoE)  (primary)
model:    gemma4-12b               # Gemma 4 12B QAT W4A16  (secondary)
```

Replaces the previous llama.cpp `llama-server.service`, which is now stopped
and disabled (its unit, drop-in and GGUF remain on disk for rollback).

## Architecture

vLLM serves exactly one model per process, so two backends sit behind a small
router that dispatches on the request's `model` field:

```
client -> :8001 router.py -> 127.0.0.1:8801  vllm-qwen   (montimage-dgx-spark)
                          -> 127.0.0.1:8802  vllm-gemma  (gemma4-12b)
```

| Unit | Serves | Port | GPU budget |
|---|---|---|---|
| `vllm-qwen.service` | Qwen3.6-35B-A3B-NVFP4 (MoE) | 8801 | `--gpu-memory-utilization 0.62` (~74 GB) |
| `vllm-gemma.service` | gemma-4-12B-it QAT W4A16 | 8802 | `--gpu-memory-utilization 0.16` (~19 GB) — stopped and disabled since 2026-08-17; fits again at Qwen 0.62, re-enable with `systemctl --user enable --now vllm-gemma` |
| `llm-router.service` | routing + `/v1/models` merge | 8001 | — |

## Operating

```bash
systemctl --user status  vllm-qwen vllm-gemma llm-router
systemctl --user restart vllm-qwen          # ~6 min: weight load + CUDA graphs
journalctl --user -u vllm-qwen -f

curl -s localhost:8001/health | jq          # per-backend health
curl -s localhost:8001/v1/models | jq '.data[].id'
```

Changing which model hides behind the alias: edit `MODEL_ID` /
`--served-model-name` in `start-qwen.sh`, then restart the unit. Clients never
change.

### Router limits

- **Request bodies** are capped at `CLIENT_MAX_SIZE` = 262 144 tokens × 16
  B/token ≈ 4 MiB, derived from the `--max-model-len 262144` that
  `start-qwen.sh` pins: a larger body cannot fit the context window anyway and
  is rejected with `413` instead of being buffered.
- **Backend discovery** (`/v1/models` fetches) is cached for
  `ROUTER_DISCOVERY_TTL` seconds (default 60); one listing request costs at
  most one upstream call per backend.
- An unknown model name triggers at most one re-discovery per name per
  `ROUTER_UNKNOWN_MODEL_TTL` seconds (default 60); retries of the same bogus
  name cost no upstream traffic.

## Connecting clients

Model is selected by the `model` field in the request body (or `--model` /
config on the client). Both API styles work on the same port:

| API | Path | Used by |
|---|---|---|
| OpenAI Chat Completions | `/v1/chat/completions` | pi, Cline, Continue, OpenAI SDKs |
| Anthropic Messages | `/v1/messages` | Claude Code (`ANTHROPIC_BASE_URL`) |

```bash
# what can I ask for?
curl -s localhost:8001/v1/models | jq -r '.data[].id'

# OpenAI style
curl -s localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"montimage-dgx-spark","messages":[{"role":"user","content":"hi"}]}'

# thinking off for this request (default is ON)
curl -s localhost:8001/v1/chat/completions \
  -H 'Content-Type: application/json' \
  -d '{"model":"montimage-dgx-spark","messages":[{"role":"user","content":"hi"}],
       "chat_template_kwargs":{"enable_thinking":false}}'
```

Any `apiKey`/token value works (`sk-local`); nothing is verified.
An unknown model name returns HTTP 404 listing the valid ids.

Configured launchers (`~/.claude-codex-local/bin/`):

- `cc`  -> Claude Code, model `montimage-dgx-spark` via `/v1/messages`
- `ccp` -> `pi --provider ccl-llamacpp --model montimage-dgx-spark`
  (**stale**: `ccp` exports `PI_CODING_AGENT_DIR=~/.pi/agent`, whose models.json
  has no `ccl-llamacpp` provider, so `ccp` fails with "Unknown provider". The
  working invocation is `--provider local-dgx`.)

Provider/model list pi actually reads is `~/.pi/agent/models.json` (selected by
`PI_CODING_AGENT_DIR`), **not** `~/.claude-codex-local/pi-agent/models.json`,
which is an unused leftover.

### pi and thinking (important)

The `local-dgx` model entry needs `"reasoning": true` plus
`"thinkingFormat": "qwen-chat-template"` in the provider's `compat`. Without
them pi sends no thinking control, the server's thinking-ON default applies
anyway, and **reasoning consumes the entire `max_tokens` budget so the turn
emits no answer at all** — measured 2026-08-17: 2000 tokens, 6634 chars of
reasoning, 0 chars of answer, `finish_reason: length`, 90 s. With the fix,
`pi --thinking off` returns a complete answer in ~15 s.

`thinking_token_budget` (pi's `supportsThinkingTokenBudget`) would cap reasoning
instead of disabling it, but this vLLM rejects it with HTTP 400 unless the server
runs with `VLLM_USE_V2_MODEL_RUNNER=0`.

## Why these settings

- `--enable-prefix-caching` — **not** on by default in this vLLM build. Without
  it, warm TTFT never improves (measured: 11.9 s at 64k ctx); with it, 1.05 s.
  Never remove this flag.
- `ghcr.io/miaai-lab/mia-vllm-gb10-linear-b12x` rather than the stock aarch64
  image, plus `--moe-backend auto` / `--linear-backend flashinfer_b12x` /
  `--attention-backend flashinfer`: Qwen3.6-35B-A3B is MoE and needs the GB10
  linear kernels. These flags do **not** transfer to a dense model — the
  Qwen3.8-27B recipe (stock image, DSpark drafter at k=7, no MoE flags) is kept
  intact in `configs/qwen3.8-27b-nvfp4-dspark.sh` and `serve-qwen38-4bit.sh`.
- MTP speculative decoding, 2 tokens, triton MoE backend for the draft pass.
- Do not benchmark the first engine instance after a cold `vllm-cache` — the
  first start JIT-compiles kernels *during* inference and reads far slower than
  every subsequent start on the identical flag set. Let it warm up, then measure.
- `--max-num-seqs 12` — sized for 3-6 concurrent clients with headroom.
- Thinking is **ON** (`enable_thinking: true`). Clients can disable per request
  with `chat_template_kwargs: {"enable_thinking": false}`.
- Qwen at 0.62 (~74 GB: 24.8 GB weights + ~45 GB KV), which leaves room for the
  gemma backend alongside. Raising it is risky: CUDA counts reclaimable page
  cache as unavailable on GB10, so free memory drifts down after large file
  reads and an over-ambitious value fails the startup check, leaving the unit
  restart-looping.

## Memory budget

The 119 GB unified pool is the binding constraint. Qwen at 0.62 takes ~74 GB,
which does leave room for gemma's ~19 GB, but gemma is still disabled from the
Qwen3.8 era — `systemctl --user enable --now vllm-gemma` to bring it back.
Anything else holding GPU memory (an ollama model at ~26 GB, a training
job) will push a backend into CUDA OOM. Check with:

```bash
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
ollama ps        # ollama's KEEP_ALIVE is 24h; `ollama stop <model>` to release
```

## The gemma image

Gemma 4 checkpoints use model type `gemma4_unified`, which the upstream image's
transformers 5.8.1 does not recognise (vLLM itself already supports the
architecture). `Dockerfile.gemma` layers transformers 5.14.1 on top:

```bash
docker build -f Dockerfile.gemma -t mia-vllm-gb10-gemma:latest .
```

The Qwen backend deliberately keeps the untouched upstream image.

## Rollback to llama.cpp

```bash
systemctl --user disable --now vllm-qwen vllm-gemma llm-router
systemctl --user enable  --now llama-server.service
```
