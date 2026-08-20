#!/usr/bin/env bash
# Standalone / experimental launcher for 4-bit Qwen3.8-27B on GB10 (SM121).
#
# This is the bench rig, NOT the production endpoint. It runs detached on its own
# port (8002) so it can sit alongside the systemd-managed vllm-qwen on 8801 --
# but note the two compete for the same unified memory pool, so stop one before
# giving the other a large --gpu-memory-utilization.
#
# Production equivalent: start-qwen.sh (systemd unit vllm-qwen.service, port 8801,
# alias montimage-dgx-spark).
#
# Recipe measured on this machine 2026-08-17, reproducing
# github.com/0xBakeer/Qwen3.8-27B-4-bit-on-a-single-DGX-Spark:
#
#            fresh gen   edit-heavy      c1      c4      c8     c16
#   k=7         28.22   58.3 / 60.7   60.21  159.85  ~234.4  232.49   <- best overall
#   k=14        21.66   67.5 / 74.2   67.18  140.50  167.39      --   <- single-stream only
#
#   K=14 ./serve-qwen38-4bit.sh     deeper drafting: faster on one interactive
#                                   stream, worse on everything else
#   SPEC=off ./serve-qwen38-4bit.sh no speculative decoding (~8 tok/s; baseline only)
set -euo pipefail

MODEL="${MODEL:-unsloth/Qwen3.8-27B-NVFP4}"
DRAFTER="${DRAFTER:-Doopeworld/Qwen3.8-27B-DSpark-vLLM}"
IMAGE="${IMAGE:-vllm/vllm-openai:v0.27.1-aarch64}"
NAME="${NAME:-qwen38-4bit}"
PORT="${PORT:-8002}"
SERVED_NAME="${SERVED_NAME:-qwen3.8-27b}"

HF_CACHE="${HF_CACHE:-/home/montimage/llm-serving/hf-cache}"
VLLM_CACHE="${VLLM_CACHE:-/home/montimage/llm-serving/vllm-cache}"

# CUDA counts reclaimable page cache as unavailable on this box and there is no
# passwordless sudo to drop it, so free memory drifts down after large file reads.
# 0.85 (the upstream repo's value) fails the startup check here; 0.65 leaves
# ~590k KV tokens, far past what a 262k context needs.
GMU="${GMU:-0.65}"
MAX_LEN="${MAX_LEN:-262144}"

# Draft slots come out of the batch token budget: k * max_num_seqs above this
# makes max_num_scheduled_tokens negative at startup. Required at K=14.
MAX_BATCHED="${MAX_BATCHED:-16384}"

SPEC="${SPEC:-dspark}"
K="${K:-7}"

case "$SPEC" in
  dspark) SPEC_CFG="{\"method\":\"dspark\",\"model\":\"$DRAFTER\",\"num_speculative_tokens\":$K,\"draft_sample_method\":\"probabilistic\"}" ;;
  mtp)    SPEC_CFG="{\"method\":\"mtp\",\"num_speculative_tokens\":$K}" ;;
  off)    SPEC_CFG="" ;;
  *)      echo "SPEC must be one of: dspark, mtp, off" >&2; exit 2 ;;
esac

mkdir -p "$HF_CACHE" "$VLLM_CACHE"
docker rm -f "$NAME" >/dev/null 2>&1 || true

ARGS=(
  serve "$MODEL"
  --served-model-name "$SERVED_NAME"
  --host 0.0.0.0 --port "$PORT"
  --max-model-len "$MAX_LEN"
  --gpu-memory-utilization "$GMU"
  --max-num-batched-tokens "$MAX_BATCHED"
  --enable-prefix-caching
  --reasoning-parser qwen3
  --tool-call-parser qwen3_xml
  --enable-auto-tool-choice
  --limit-mm-per-prompt '{"image":2}'
)
[ -n "$SPEC_CFG" ] && ARGS+=( --speculative-config "$SPEC_CFG" )

echo "starting $NAME :: $MODEL :: spec=$SPEC k=$K gmu=$GMU"

# VLLM_MARLIN_USE_ATOMIC_ADD is not optional on SM121: a race in the Marlin kernel
# produces INCORRECT OUTPUT rather than an error, and 4-bit weights are dequantized
# through Marlin on this device, so it sits directly in the decode path.
# VLLM_USE_FLASHINFER_MOE_FP4=0 keeps the MoE path off CUTLASS FP4, which is
# reported to emit silent garbage here. Unused by this dense model; cheap insurance.
docker run -d --name "$NAME" --gpus all --ipc host \
  -p "127.0.0.1:$PORT:$PORT" \
  -e VLLM_MARLIN_USE_ATOMIC_ADD=1 \
  -e VLLM_USE_FLASHINFER_MOE_FP4=0 \
  -v "$HF_CACHE":/root/.cache/huggingface \
  -v "$VLLM_CACHE":/root/.cache/vllm \
  --entrypoint vllm "$IMAGE" "${ARGS[@]}" >/dev/null

echo -n "waiting for readiness"
for _ in $(seq 1 360); do
  if curl -sf "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo; echo "ready on http://127.0.0.1:$PORT/v1  (model: $SERVED_NAME)"
    docker logs "$NAME" 2>&1 | grep -o "GPU KV cache size: [0-9,]*" | tail -1
    exit 0
  fi
  if ! docker ps --format '{{.Names}}' | grep -qx "$NAME"; then
    echo; echo "container exited. last errors:" >&2
    docker logs "$NAME" 2>&1 | grep -iE "ValueError|Value error|ImportError|Error:" | tail -5 >&2
    exit 1
  fi
  echo -n "."
  sleep 5
done

echo; echo "timed out waiting for readiness" >&2
exit 1
