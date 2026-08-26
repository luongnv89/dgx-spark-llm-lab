#!/usr/bin/env bash
# collect_context.sh — the conditions a benchmark result must be read against.
#
# Prints a markdown "Run context" section on stdout: the machine, the GPU and
# what else is using it, the serving endpoint, and the harness's live surface
# (skills, MCP servers, extensions) that a live run folds into the measurement.
#
#   bash collect_context.sh [--harness <name>] [--model <spec>] [--thinking <on|off|n/a>]
#
# Every field is fail-soft: a probe that is missing, slow or unsupported prints
# `unknown` and the script still exits 0. A benchmark must never be blocked by
# its own bookkeeping, and a blank field is more honest than a guessed one.
set -uo pipefail

usage() {  # usage [exit-code]
  echo "usage: collect_context.sh [--harness <name>] [--model <spec>] [--thinking <on|off|n/a>]" >&2
  exit "${1:-2}"
}
# a flag whose value is missing is a usage error, never a silent `shift 2` that
# fails and spins the loop on the same argument forever
need() { [ "$1" -ge 2 ] || { echo "collect_context: $2 needs a value" >&2; usage; }; }

HARNESS=""; MODEL=""; THINKING=""
while [ $# -gt 0 ]; do
  case "$1" in
    --harness) need $# --harness; HARNESS="$2"; shift 2 ;;
    --model) need $# --model; MODEL="$2"; shift 2 ;;
    --thinking) need $# --thinking; THINKING="$2"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "collect_context: unknown argument '$1'" >&2
       usage ;;
  esac
done

u() { printf '%s' "${1:-unknown}"; }
row() { printf '| %s | %s |\n' "$1" "$(u "$2")"; }
have() { command -v "$1" >/dev/null 2>&1; }
count() { printf '%s' "$(ls -1 "$1" 2>/dev/null | wc -l | tr -d ' ')"; }

echo "## Run context"
echo
echo "_Collected at $(date -u '+%Y-%m-%d %H:%M UTC') — the conditions this result must be read against._"
echo

# --- machine ---------------------------------------------------------------
os=$(. /etc/os-release 2>/dev/null && printf '%s' "$PRETTY_NAME")
[ -n "$os" ] || os=$(sw_vers -productName 2>/dev/null)$(sw_vers -productVersion 2>/dev/null | sed 's/^/ /')
cpu=$(awk -F': ' '/^model name/{print $2; exit}' /proc/cpuinfo 2>/dev/null)
[ -n "$cpu" ] || cpu=$(sysctl -n machdep.cpu.brand_string 2>/dev/null)
[ -n "$cpu" ] || cpu=$(lscpu 2>/dev/null | awk -F': +' '/^Model name/{print $2; exit}')
cpu=$(printf '%s' "$cpu" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//; s/[[:space:]]+/ /g')
cores=$(nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null)
memtot=$(awk '/MemTotal/{printf "%.0f GiB", $2/1048576}' /proc/meminfo 2>/dev/null)
memavail=$(awk '/MemAvailable/{printf "%.0f GiB free", $2/1048576}' /proc/meminfo 2>/dev/null)
[ -n "$memtot" ] || memtot=$(sysctl -n hw.memsize 2>/dev/null | awk '{printf "%.0f GiB", $1/1073741824}')

echo "### Machine"
echo
echo "| Field | Value |"
echo "|---|---|"
row "host"      "$(hostname 2>/dev/null)"
row "os"        "$os $(uname -r 2>/dev/null) ($(uname -m 2>/dev/null))"
row "cpu"       "$cpu${cores:+ — $cores threads}"
row "memory"    "$memtot${memavail:+, $memavail at start}"
row "disk"      "$(df -h . 2>/dev/null | awk 'NR==2{print $4" free on "$6}')"
row "load avg"  "$(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null || uptime | sed 's/.*averages*: //')"
echo

# --- gpu -------------------------------------------------------------------
echo "### GPU"
echo
if have nvidia-smi; then
  echo "| Field | Value |"
  echo "|---|---|"
  nvidia-smi --query-gpu=name,memory.total,memory.used,utilization.gpu,driver_version \
             --format=csv,noheader 2>/dev/null |
  while IFS=, read -r name total used util drv; do
    row "gpu"     "$(echo "$name" | sed 's/^ //')"
    total=$(echo "$total" | sed 's/^ //'); used=$(echo "$used" | sed 's/^ //')
    case "$total" in
      # unified-memory parts (GB10 and friends) report [N/A] here; the GPU shares
      # the host RAM already recorded above, so point there instead of printing N/A
      *N/A*) row "vram" "unified with host memory — see the memory row above" ;;
      *)     row "vram" "$used used of $total" ;;
    esac
    row "util"    "$(echo "$util" | sed 's/^ //') at start"
    row "driver"  "$(echo "$drv" | sed 's/^ //')$(nvidia-smi 2>/dev/null | awk '/CUDA Version/{print ", CUDA "$9}')"
  done
  apps=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null)
  echo
  if [ -n "$apps" ]; then
    echo "**Other GPU processes at start** — anything here shares the device with the run,"
    echo "and a contended GPU makes wall-clock and turn counts incomparable:"
    echo
    echo '```'
    echo "$apps"
    echo '```'
  else
    echo "No other compute processes on the GPU at start."
  fi
else
  echo "No \`nvidia-smi\` — GPU unknown. On a hosted model this is expected and harmless;"
  echo "on a local endpoint it means the serving device was not recorded."
fi
echo

# --- serving endpoint ------------------------------------------------------
base="${BENCH_BASE_URL:-http://localhost:8001/v1}"
echo "### Serving endpoint"
echo
echo "| Field | Value |"
echo "|---|---|"
row "base url" "$base"
ids=""
if have curl; then
  ids=$(curl -s --max-time 5 "$base/models" 2>/dev/null |
        python3 -c 'import json,sys;d=json.load(sys.stdin);print(", ".join(m["id"] for m in d.get("data",[])))' 2>/dev/null)
fi
row "serves"   "${ids:-not reachable (hosted model, or nothing local is serving)}"
row "unit"     "$(systemctl --user is-active vllm-qwen 2>/dev/null)"
echo

# --- harness ---------------------------------------------------------------
echo "### Harness setup"
echo
echo "A live run measures this surface, not the model alone. Every skill, MCP server and"
echo "extension below is part of the result."
echo
echo "| Field | Value |"
echo "|---|---|"
row "harness"  "$HARNESS"
row "model"    "$MODEL"
row "thinking" "$THINKING"
case "$HARNESS" in
  pi)
    row "version"    "$(pi --version 2>/dev/null | tail -1)"
    row "agent dir"  "${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
    row "extensions" "$(python3 -c 'import json,os,sys
p=os.path.expanduser(os.environ.get("PI_CODING_AGENT_DIR","~/.pi/agent"))+"/settings.json"
try: print(", ".join(json.load(open(p)).get("packages") or []) or "none")
except Exception: print("unknown")' 2>/dev/null)"
    row "catalogue"  "$(python3 -c 'import json,os
p=os.path.expanduser(os.environ.get("PI_CODING_AGENT_DIR","~/.pi/agent"))+"/models.json"
try:
    n=len(json.load(open(p)).get("providers") or [])
    print(str(n)+" provider(s)")
except Exception:
    print("unknown")' 2>/dev/null)"
    ;;
  opencode)
    row "version"  "$(opencode --version 2>/dev/null | tail -1)"
    row "config"   "${OPENCODE_CONFIG:-$HOME/.config/opencode/opencode.json}"
    row "plugins"  "$(count "$HOME/.config/opencode/plugins") in ~/.config/opencode/plugins"
    row "skills"   "$(count "$HOME/.config/opencode/skills") global"
    ;;
  claude-code)
    row "version"  "$(claude --version 2>/dev/null | tail -1)"
    row "config"   "${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
    row "skills"   "$(count "${CLAUDE_CONFIG_DIR:-$HOME/.claude}/skills") global, $(count "$PWD/.claude/skills") project"
    row "mcp"      "$(python3 -c 'import json,os
for p in (os.path.expanduser("~/.claude.json"), os.path.expanduser("~/.claude/settings.json")):
    try:
        s=json.load(open(p)).get("mcpServers") or {}
        if s: print(", ".join(s)); break
    except Exception: pass
else: print("none recorded")' 2>/dev/null)"
    ;;
  *) row "version" "" ;;
esac
project=""
for f in CLAUDE.md AGENTS.md; do [ -f "$f" ] && project="$project$f "; done
row "project context" "${project:-none in $(basename "$PWD")}"
