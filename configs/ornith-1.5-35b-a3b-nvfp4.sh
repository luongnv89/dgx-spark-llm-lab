#!/usr/bin/env bash
# Qwen3.6-35B-A3B-NVFP4 on vLLM, behind the stable alias montimage-dgx-spark.
# Runs attached (no -d) so systemd owns the lifecycle.
#
# Restored as the default on 2026-08-17, reverting the 2026-08-17 swap to
# Qwen3.8-27B-NVFP4. That version is kept as start-qwen.sh.qwen38.bak (dense
# model, stock aarch64 image, DSpark drafter at k=7) -- copy it back over this
# file and `systemctl --user restart vllm-qwen` to switch again. Clients are
# unaffected either way: same port 8801, same alias, same router on :8001.
#
# This is a MoE model, so it needs the mia-vllm-gb10 build and the
# --moe-backend / --linear-backend flashinfer_b12x flags below; the Qwen3.8
# recipe's flags are not interchangeable with these.
set -euo pipefail

MODEL_ID="ornith-ai/Ornith-1.5-35B-A3B-NVFP4"
IMAGE="ghcr.io/miaai-lab/mia-vllm-gb10-linear-b12x:latest"
NAME="vllm-qwen"
PORT="${QWEN_PORT:-8801}"
# 0.62 of the 119 GB unified pool (~74 GB): weights 24.8 GB + ~45 GB KV.
# Leaves room for the gemma backend alongside.
UTIL="${QWEN_UTIL:-0.62}"
HF_HOME="${HF_HOME_DIR:-/home/montimage/llm-serving/hf-cache}"

mkdir -p "${HF_HOME}"
docker rm -f "${NAME}" >/dev/null 2>&1 || true

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
  -e VLLM_TARGET_DEVICE=cuda \
  -e CUTE_DSL_ARCH=sm_121a \
  -e HF_HOME=/root/.cache/huggingface \
  -v "${HF_HOME}:/root/.cache/huggingface" \
  "${IMAGE}" \
  serve "${MODEL_ID}" \
    --served-model-name montimage-dgx-spark "${MODEL_ID}" \
    --host 127.0.0.1 --port "${PORT}" \
    --tensor-parallel-size 1 \
    --trust-remote-code \
    --moe-backend auto \
    --gpu-memory-utilization "${UTIL}" \
    --linear-backend flashinfer_b12x \
    --attention-backend flashinfer \
    --max-model-len 262144 \
    --max-num-seqs 12 \
    --max-num-batched-tokens 32768 \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --async-scheduling \
    --kv-cache-dtype fp8 \
    --speculative-config '{"method":"mtp","num_speculative_tokens":2,"moe_backend":"triton"}' \
    --reasoning-parser qwen3 \
    --default-chat-template-kwargs '{"enable_thinking":true,"preserve_thinking":true}' \
    --tool-call-parser qwen3_coder \
    --enable-auto-tool-choice \
    --limit-mm-per-prompt '{"image":4}' \
    --allowed-media-domains '*' \
    --override-generation-config '{"temperature":0.6,"top_p":0.95,"top_k":20,"min_p":0.0}'
