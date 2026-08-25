#!/usr/bin/env bash
# detect_setup.sh — which coding harness is this shell running inside, and
# which model is that harness currently set to use?
#
# Prints key=value lines on stdout (never JSON: every harness can parse this):
#
#   harness=pi|opencode|claude-code
#   harness_source=<how it was decided>
#   provider=<provider id, may be empty>
#   model=<model id, may be empty>
#   model_source=<how it was decided, or "none">   # BENCH_HARNESS_MODEL wins if set
#   thinking=1|0|unsupported
#   thinking_source=<how it was decided>
#
# An empty `model=` is a normal answer, not a failure: opencode has no default
# model until the user sets one, and Claude Code's in-session `/model` switch
# leaves no trace on disk. The caller asks the user in that case.
#
# Exit codes: 0 detected, 3 harness unknown (message on stderr), 4 bad usage.
set -uo pipefail

usage() {
  cat >&2 <<'USAGE'
usage: detect_setup.sh [--harness pi|opencode|claude-code]

Detects the harness this shell is running inside and the model it is set to.
Pass --harness to skip harness detection (model detection still runs).
USAGE
  exit 4
}

FORCE_HARNESS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --harness) [ $# -ge 2 ] || usage; FORCE_HARNESS="$2"; shift 2 ;;
    --harness=*) FORCE_HARNESS="${1#*=}"; shift ;;
    -h|--help) usage ;;
    *) echo "detect_setup: unknown argument '$1'" >&2; usage ;;
  esac
done
case "$FORCE_HARNESS" in
  ""|pi|opencode|claude-code) ;;
  *) echo "detect_setup: unknown harness '$FORCE_HARNESS'; have: pi, opencode, claude-code" >&2; exit 4 ;;
esac

# --- json reading ----------------------------------------------------------
# python3 is already required by the benchmark itself (>= 3.10), so use it and
# fall back to grep only if it is somehow absent.
json_get() {  # json_get <file> <dotted.key>
  local file="$1" key="$2"
  [ -r "$file" ] || return 1
  if command -v python3 >/dev/null 2>&1; then
    python3 - "$file" "$key" <<'PY' 2>/dev/null
import json, sys
try:
    with open(sys.argv[1]) as f:
        cur = json.load(f)
except Exception:
    sys.exit(1)
for part in sys.argv[2].split("."):
    if not isinstance(cur, dict) or part not in cur:
        sys.exit(1)
    cur = cur[part]
print(cur if isinstance(cur, str) else json.dumps(cur))
PY
  else
    grep -oE "\"${key##*.}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" "$file" |
      head -1 | sed -E 's/.*:[[:space:]]*"([^"]*)"/\1/'
  fi
}

emit() { printf '%s=%s\n' "$1" "${2-}"; }

# --- 1. which harness ------------------------------------------------------
harness=""; harness_source=""

if [ -n "$FORCE_HARNESS" ]; then
  harness="$FORCE_HARNESS"; harness_source="explicit:--harness"
fi

if [ -z "$harness" ]; then                      # environment markers
  if [ -n "${CLAUDECODE:-}${CLAUDE_CODE_ENTRYPOINT:-}${CLAUDE_CODE_SESSION_ID:-}" ]; then
    harness="claude-code"; harness_source="env:CLAUDECODE"
  elif [ -n "${OPENCODE:-}${OPENCODE_BIN_PATH:-}${OPENCODE_CLIENT:-}${OPENCODE_SESSION_ID:-}" ]; then
    harness="opencode"; harness_source="env:OPENCODE"
  elif [ -n "${PI_CODING_AGENT_DIR:-}${PI_AGENT_DIR:-}${PI_SESSION_ID:-}" ]; then
    harness="pi"; harness_source="env:PI"
  fi
fi

if [ -z "$harness" ]; then                      # process ancestry (ps: Linux + macOS)
  # Match the *basename of argv[0]* (and argv[1] behind a node/bun launcher),
  # never the whole command line: a PATH entry like ~/.opencode/bin inside an
  # ancestor's arguments would otherwise be read as "running inside opencode".
  pid="${PPID:-0}"; depth=0
  while [ "$pid" -gt 1 ] && [ "$depth" -lt 12 ]; do
    args=$(ps -o args= -p "$pid" 2>/dev/null)
    # shellcheck disable=SC2086  # deliberate word splitting: argv0 then argv1
    set -- $args
    a0=$(basename "${1:-}" 2>/dev/null)
    a1=$(basename "${2:-}" 2>/dev/null)
    case "$a0" in
      node|bun|deno|npx|nodejs) probe="$a1" ;;
      *)                        probe="$a0" ;;
    esac
    case "$probe" in
      claude|claude-code) harness="claude-code"; harness_source="ancestry:$probe"; break ;;
      opencode)           harness="opencode";    harness_source="ancestry:$probe"; break ;;
      pi)                 harness="pi";          harness_source="ancestry:$probe"; break ;;
    esac
    pid=$(ps -o ppid= -p "$pid" 2>/dev/null | tr -d ' ')
    [ -n "$pid" ] || break
    depth=$((depth + 1))
  done
fi

if [ -z "$harness" ]; then
  echo "detect_setup: cannot tell which harness this shell is inside." >&2
  echo "  Checked: CLAUDECODE / OPENCODE_* / PI_* environment markers, then the" >&2
  echo "  process ancestry of PID ${PPID:-?}. Neither named a known harness." >&2
  echo "  Re-run with --harness pi|opencode|claude-code, or ask the user." >&2
  exit 3
fi

# --- 2. which model --------------------------------------------------------
provider=""; model=""; model_source="none"
thinking="unsupported"; thinking_source="adapter ignores --thinking for this harness"

if [ -n "${BENCH_HARNESS_MODEL:-}" ]; then
  # the benchmark's own override, honoured by `bench` itself; outranks whatever
  # the harness happens to be set to, and is outranked only by explicit args
  model="$BENCH_HARNESS_MODEL"; model_source="env:BENCH_HARNESS_MODEL"
  case "$model" in */*) provider="${model%%/*}"; model="${model#*/}" ;; esac
fi

case "$harness" in
  claude-code)
    # No env var carries the session model, and `/model` switches leave no
    # trace on disk — settings.json is the last written intent, not proof.
    if [ -n "$model" ]; then :
    elif [ -n "${ANTHROPIC_MODEL:-}" ]; then
      model="$ANTHROPIC_MODEL"; model_source="env:ANTHROPIC_MODEL"
    else
      cfgdir="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
      for f in "$PWD/.claude/settings.local.json" "$PWD/.claude/settings.json" \
               "$cfgdir/settings.local.json" "$cfgdir/settings.json"; do
        v=$(json_get "$f" model) || continue
        [ -n "$v" ] || continue
        model="$v"; model_source="file:$f"; break
      done
    fi
    ;;
  opencode)
    if [ -n "$model" ]; then :
    elif [ -n "${OPENCODE_MODEL:-}" ]; then
      model="$OPENCODE_MODEL"; model_source="env:OPENCODE_MODEL"
    else
      ocdir="${OPENCODE_CONFIG_DIR:-$HOME/.config/opencode}"
      for f in "${OPENCODE_CONFIG:-}" "$PWD/opencode.json" "$PWD/opencode.jsonc" \
               "$ocdir/opencode.json" "$ocdir/config.json"; do
        [ -n "$f" ] || continue
        v=$(json_get "$f" model) || continue
        [ -n "$v" ] || continue
        model="$v"; model_source="file:$f"; break
      done
    fi
    # opencode.json writes the selection as provider/model
    case "$model" in */*) provider="${model%%/*}"; model="${model#*/}" ;; esac
    ;;
  pi)
    pidir="${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}"
    [ -n "$model" ] || v=$(json_get "$pidir/settings.json" defaultModel) && [ -n "${v:-}" ] && [ -z "$model" ] && {
      model="$v"; model_source="file:$pidir/settings.json"
      p=$(json_get "$pidir/settings.json" defaultProvider) && provider="$p"
    }
    lvl=$(json_get "$pidir/settings.json" defaultThinkingLevel) || lvl=""
    # pi is the only adapter that maps --thinking onto a real flag (off|high)
    case "$lvl" in
      ""|off|none) thinking=0; thinking_source="pi settings.json defaultThinkingLevel=${lvl:-unset}" ;;
      *)           thinking=1; thinking_source="pi settings.json defaultThinkingLevel=$lvl" ;;
    esac
    ;;
esac

emit harness "$harness"
emit harness_source "$harness_source"
emit provider "$provider"
emit model "$model"
emit model_source "$model_source"
emit thinking "$thinking"
emit thinking_source "$thinking_source"
