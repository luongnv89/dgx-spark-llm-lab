#!/bin/bash
# Qwen3.8-27B Benchmark Script
# Optimized for NVIDIA GB10 GPU with 119.7GB VRAM + 119GB System RAM
# 20 ARM CPU cores (Cortex-X925 + Cortex-A725)

set -euo pipefail

# Model configuration
MODEL_REPO="unsloth/Qwen3.8-27B-GGUF"
MODEL_NAME="Qwen/Qwen3.8-27B"
QUANTIZATION="Q4_K_M"  # ~17.1GB for 27B params - fits easily in 119GB VRAM
MODEL_DIR="/tmp/qwen3-27b"
MODEL_FILE="${MODEL_DIR}/Qwen3.8-27B-${QUANTIZATION}.gguf"
CONTEXT_SIZE=8192
CPU_THREADS=20
GPU_LAYERS=999  # Offload all layers to GPU VRAM
FLASH_ATTN="on"
BENCHMARK_PREDICT=512  # Number of tokens to generate
SERVER_PORT=8080
LLAMA_SERVER="/home/montimage/workspace/ai-llm/llama.cpp/build/bin/llama-server"  # CUDA build; the homebrew bottle is Vulkan-only and can't open the render node here
LOG_FILE="/tmp/llama-server.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

SERVER_PID=""

cleanup() {
    if [ -n "${SERVER_PID}" ] && kill -0 "${SERVER_PID}" 2>/dev/null; then
        echo ""
        echo -e "${YELLOW}Cleaning up...${NC}"
        kill "${SERVER_PID}" 2>/dev/null || true
        wait "${SERVER_PID}" 2>/dev/null || true
    fi
}
trap cleanup EXIT

echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Qwen3.8-27B Benchmark Setup${NC}"
echo -e "${GREEN}========================================${NC}"
echo ""
echo -e "Hardware:${NC}"
echo -e "  GPU: NVIDIA GB10 (119.7 GB VRAM visible to CUDA)"
echo -e "  CPU: 20 cores (ARM Cortex-X925 + Cortex-A725)"
echo -e "  System RAM: 119 GB"
echo -e "  CUDA: 13.0"
echo -e "  llama.cpp: $(${LLAMA_SERVER} --version 2>&1 | grep version | head -1)"
echo ""
echo -e "Model:${NC} ${MODEL_NAME} (${QUANTIZATION} quantization, ~17.1GB)"
echo -e "Context size: ${CONTEXT_SIZE} tokens"
echo -e "CPU threads: ${CPU_THREADS}"
echo -e "GPU layers: ${GPU_LAYERS} (all layers offloaded to GPU)"
echo -e "Flash Attention: ${FLASH_ATTN}"
echo -e "Benchmark tokens: ${BENCHMARK_PREDICT}"
echo ""

# Function to check prerequisites
check_prerequisites() {
    echo -e "${YELLOW}Checking prerequisites...${NC}"

    # Check llama-server
    if ! command -v "${LLAMA_SERVER}" &> /dev/null; then
        echo -e "${RED}Error: llama-server not found${NC}"
        exit 1
    fi

    # Check GPU availability
    if nvidia-smi --list-gpus 2>&1 | grep -q "NVIDIA GB10"; then
        echo -e "  ${GREEN}✓ NVIDIA GB10 GPU detected${NC}"
    else
        echo -e "  ${YELLOW}! NVIDIA GPU not detected, proceeding with CPU only${NC}"
    fi

    # Check model file: must exist, and be a real GGUF (not an HTML error page)
    if [ ! -f "${MODEL_FILE}" ] || [ "$(head -c4 "${MODEL_FILE}" 2>/dev/null)" != "GGUF" ]; then
        echo -e "  ${YELLOW}! Model not found or invalid at ${MODEL_FILE}, downloading (~17.1GB)...${NC}"
        mkdir -p "${MODEL_DIR}"
        if command -v hf &> /dev/null; then
            hf download "${MODEL_REPO}" "Qwen3.8-27B-${QUANTIZATION}.gguf" --local-dir "${MODEL_DIR}"
        elif command -v huggingface-cli &> /dev/null; then
            huggingface-cli download "${MODEL_REPO}" "Qwen3.8-27B-${QUANTIZATION}.gguf" --local-dir "${MODEL_DIR}"
        else
            echo -e "  ${RED}Error: neither 'hf' nor 'huggingface-cli' found to download the model${NC}"
            exit 1
        fi
    fi

    if [ "$(head -c4 "${MODEL_FILE}" 2>/dev/null)" != "GGUF" ]; then
        echo -e "  ${RED}Error: ${MODEL_FILE} is not a valid GGUF file${NC}"
        exit 1
    fi
    echo -e "  ${GREEN}✓ Model file present ($(du -h "${MODEL_FILE}" | cut -f1))${NC}"

    echo ""
}

# Function to start the server
start_server() {
    echo -e "${YELLOW}Starting llama-server...${NC}"
    echo "Command: ${LLAMA_SERVER} \\
--model ${MODEL_FILE} \\
--port ${SERVER_PORT} \\
--gpu-layers ${GPU_LAYERS} \\
--ctx-size ${CONTEXT_SIZE} \\
-t ${CPU_THREADS} \\
--flash-attn ${FLASH_ATTN} \\
--perf \\
--prio 0"

    # Start the server in background
    "${LLAMA_SERVER}" \
        --model "${MODEL_FILE}" \
        --port "${SERVER_PORT}" \
        --gpu-layers "${GPU_LAYERS}" \
        --ctx-size "${CONTEXT_SIZE}" \
        -t "${CPU_THREADS}" \
        --flash-attn "${FLASH_ATTN}" \
        --perf \
        --prio 0 \
        > "${LOG_FILE}" 2>&1 &

    SERVER_PID=$!
    echo "Server PID: ${SERVER_PID}"

    # Poll the health endpoint instead of guessing with a fixed sleep
    echo -n "Waiting for model to load"
    local waited=0
    local max_wait=600
    while [ ${waited} -lt ${max_wait} ]; do
        if ! kill -0 "${SERVER_PID}" 2>/dev/null; then
            echo ""
            echo -e "  ${RED}✗ Server process exited during startup${NC}"
            cat "${LOG_FILE}"
            exit 1
        fi
        if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${SERVER_PORT}/health" 2>/dev/null | grep -q "200"; then
            echo ""
            echo -e "  ${GREEN}✓ Server started and model loaded successfully (${waited}s)${NC}"
            return 0
        fi
        echo -n "."
        sleep 5
        waited=$((waited + 5))
    done

    echo ""
    echo -e "  ${RED}✗ Model failed to load within ${max_wait}s${NC}"
    cat "${LOG_FILE}"
    exit 1
}

# Function to run benchmark
run_benchmark() {
    echo -e "${YELLOW}Running benchmark...${NC}"
    echo ""

    echo -e "Sending test inference request (${BENCHMARK_PREDICT} tokens)..."

    TEST_RESPONSE=$(curl -s -X POST "http://127.0.0.1:${SERVER_PORT}/completion" \
        -H "Content-Type: application/json" \
        -d "{\"prompt\": \"Explain the theory of relativity in simple terms.\", \"n_predict\": ${BENCHMARK_PREDICT}}" \
        --max-time 180 2>/dev/null)

    if [ -z "${TEST_RESPONSE}" ]; then
        echo -e "  ${YELLOW}! Inference test timed out or failed${NC}"
        return
    fi

    echo -e "  ${GREEN}✓ Inference test successful${NC}"

    echo ""
    echo -e "${YELLOW}Performance Stats:${NC}"
    if command -v jq &> /dev/null && echo "${TEST_RESPONSE}" | jq -e '.timings' > /dev/null 2>&1; then
        echo "${TEST_RESPONSE}" | jq '{
            prompt_tokens: .timings.prompt_n,
            prompt_tok_per_sec: .timings.prompt_per_second,
            generated_tokens: .timings.predicted_n,
            generated_tok_per_sec: .timings.predicted_per_second
        }'
    else
        echo "  (no 'timings' field in response, raw response below)"
        echo "${TEST_RESPONSE}" | head -c 500
        echo ""
    fi

    echo ""
    echo -e "${YELLOW}GPU memory usage:${NC}"
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null || true
}

# Main execution
check_prerequisites
start_server
run_benchmark

echo ""
echo -e "${GREEN}========================================${NC}"
echo -e "${GREEN}Benchmark complete!${NC}"
echo -e "${GREEN}========================================${NC}"
