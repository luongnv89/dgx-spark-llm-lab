#!/usr/bin/env bash
# google/gemma-4-12B-it-qat-w4a16-ct on vLLM, served as "gemma4-12b".
# QAT 4-bit compressed-tensors: ~10.3 GB of weights.
set -euo pipefail

MODEL_ID="google/gemma-4-12B-it-qat-w4a16-ct"
# Derived image: base + transformers 5.14.1 (base ships 5.8.1, which does not
# know the `gemma4_unified` model type). Build with:
#   docker build -f Dockerfile.gemma -t mia-vllm-gb10-gemma:latest .
IMAGE="mia-vllm-gb10-gemma:latest"
NAME="vllm-gemma"
PORT="${GEMMA_PORT:-8802}"
# 0.16 of 119 GB (~19 GB): weights 10.3 GB + ~8 GB KV.
UTIL="${GEMMA_UTIL:-0.16}"
# Context capped well below the model's 262k so the KV cache fits the budget.
MAXLEN="${GEMMA_MAXLEN:-32768}"
HF_HOME="${HF_HOME_DIR:-/home/montimage/llm-serving/hf-cache}"

mkdir -p "${HF_HOME}"
docker rm -f "${NAME}" >/dev/null 2>&1 || true

exec docker run --rm \
  --name "${NAME}" \
  --user root \
  --network host \
  --shm-size=8g \
  --ulimit memlock=-1:-1 \
  --cap-add=IPC_LOCK \
  --ipc host \
  --gpus all \
  --entrypoint /usr/local/bin/vllm \
  -e VLLM_TARGET_DEVICE=cuda \
  -e CUTE_DSL_ARCH=sm_121a \
  -e HF_HOME=/root/.cache/huggingface \
  -e HF_TOKEN="${HF_TOKEN:-}" \
  -v "${HF_HOME}:/root/.cache/huggingface" \
  "${IMAGE}" \
  serve "${MODEL_ID}" \
    --served-model-name gemma4-12b "${MODEL_ID}" \
    --host 127.0.0.1 --port "${PORT}" \
    --tensor-parallel-size 1 \
    --trust-remote-code \
    --gpu-memory-utilization "${UTIL}" \
    --attention-backend flashinfer \
    --max-model-len "${MAXLEN}" \
    --max-num-seqs 8 \
    --enable-chunked-prefill \
    --enable-prefix-caching \
    --kv-cache-dtype fp8
