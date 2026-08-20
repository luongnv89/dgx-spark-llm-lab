#!/usr/bin/env bash
# Qwen3.8-27B (4-bit NVFP4) on vLLM, behind the stable alias montimage-dgx-spark.
# Runs attached (no -d) so systemd owns the lifecycle.
#
# Re-swapped from Qwen3.6-35B-A3B-NVFP4 on 2026-08-20 for a trial run before a
# final decision. Roll back with:
#   cp start-qwen.sh.qwen36.bak start-qwen.sh && systemctl --user restart vllm-qwen
#
# NOTE (2026-08-20): enable_thinking defaults to FALSE here, unlike the 08-17
# version. Thinking ON with this vLLM chat template scored 62.5% pass@1 on the
# 16-task coding suite (runaway reasoning truncating before any code); OFF
# scored 96.9% and 32x faster. Clients opt in per request with
# chat_template_kwargs:{"enable_thinking":true}.
#
# Swapped from Qwen3.6-35B-A3B-NVFP4 on 2026-08-17. Previous version kept as
# start-qwen.sh.qwen36.bak -- restore it and `systemctl --user restart vllm-qwen`
# to roll back. Clients are unaffected either way: same port, same alias.
#
# Recipe from github.com/0xBakeer/Qwen3.8-27B-4-bit-on-a-single-DGX-Spark,
# reproduced on this machine (edit-heavy 58-61 tok/s single stream, ~234 tok/s
# aggregate at 8-way). See serve-qwen38-4bit.sh for the bench rig and the k=14
# variant. NOTE: this uses the stock aarch64 vLLM image, not the mia-vllm-gb10
# build -- Qwen3.8-27B is dense-hybrid, so the flags the Qwen3.6 MoE needed
# (--moe-backend, --linear-backend flashinfer_b12x) do not apply here.
set -euo pipefail

MODEL_ID="unsloth/Qwen3.8-27B-NVFP4"
DRAFTER_ID="Doopeworld/Qwen3.8-27B-DSpark-vLLM"
IMAGE="vllm/vllm-openai:v0.27.1-aarch64"
NAME="vllm-qwen"
PORT="${QWEN_PORT:-8801}"
# 0.70 of the 119 GB unified pool (~84 GB): weights 22 GB + drafter 2.6 GB, and
# ~590k KV tokens were measured at 0.65. Not raised further because CUDA counts
# reclaimable page cache as unavailable on GB10 -- free memory drifts down after
# large file reads, and an over-ambitious value fails the startup check and
# leaves the unit restart-looping. 0.85 (the upstream repo's value) does not
# start on this box.
UTIL="${QWEN_UTIL:-0.70}"
# Draft depth. 7 is the best all-round setting measured here; 14 is faster on a
# single interactive stream but worse at every concurrency >= 4 and 23 % worse
# on fresh generation. Draft slots come out of the batch token budget.
SPEC_K="${QWEN_SPEC_K:-7}"
HF_HOME="${HF_HOME_DIR:-/home/montimage/llm-serving/hf-cache}"
VLLM_CACHE="${VLLM_CACHE_DIR:-/home/montimage/llm-serving/vllm-cache}"

mkdir -p "${HF_HOME}" "${VLLM_CACHE}"
docker rm -f "${NAME}" >/dev/null 2>&1 || true

# VLLM_MARLIN_USE_ATOMIC_ADD is not optional on SM121: a documented race in the
# Marlin kernel yields INCORRECT OUTPUT rather than an error, and 4-bit weights
# are dequantized through Marlin on this device (GB10 has no native FP4 compute
# path), so it sits directly in the decode path.
# VLLM_USE_FLASHINFER_MOE_FP4=0 keeps the MoE path off CUTLASS FP4, reported to
# emit silent garbage on this architecture. Unused by this dense model.
exec docker run --rm \
  --name "${NAME}" \
  --user root \
  --network host \
  --shm-size=32g \
  --ulimit memlock=-1:-1 \
  --cap-add=IPC_LOCK \
  --ipc host \
  --gpus all \
  --entrypoint /usr/local/bin/vllm \
  -e VLLM_MARLIN_USE_ATOMIC_ADD=1 \
  -e VLLM_USE_FLASHINFER_MOE_FP4=0 \
  -e HF_HOME=/root/.cache/huggingface \
  -v "${HF_HOME}:/root/.cache/huggingface" \
  -v "${VLLM_CACHE}:/root/.cache/vllm" \
  "${IMAGE}" \
  serve "${MODEL_ID}" \
    --served-model-name montimage-dgx-spark "${MODEL_ID}" \
    --host 127.0.0.1 --port "${PORT}" \
    --tensor-parallel-size 1 \
    --trust-remote-code \
    --gpu-memory-utilization "${UTIL}" \
    --max-model-len 262144 \
    --max-num-seqs 12 \
    --max-num-batched-tokens 16384 \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --speculative-config "{\"method\":\"dspark\",\"model\":\"${DRAFTER_ID}\",\"num_speculative_tokens\":${SPEC_K},\"draft_sample_method\":\"probabilistic\"}" \
    --reasoning-parser qwen3 \
    --default-chat-template-kwargs '{"enable_thinking":false,"preserve_thinking":true}' \
    --tool-call-parser qwen3_xml \
    --enable-auto-tool-choice \
    --limit-mm-per-prompt '{"image":4}' \
    --allowed-media-domains '*' \
    --override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":20,"min_p":0.0}'
