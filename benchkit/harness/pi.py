"""Adapter for the `pi` coding assistant (https://github.com/badlogic/pi-mono).

pi is driven headless with `-p --mode json`, which emits one JSON event per line.
We count `tool_execution_*` events for tool hygiene, `turn_*` for turns, and read
token usage off each assistant `message_end`.

Two flags matter for benchmark validity and are not optional:

- `--no-extensions`: pi's extensions can call *other* models. This machine's
  install ships an advisor extension pointed at `openai-codex/gpt-5.6-sol`, which
  would silently put a frontier model inside a run that claims to measure a local
  one.
- `--no-context-files`: without it pi discovers AGENTS.md / CLAUDE.md by walking
  up from the working directory, so the benchmark would leak whatever guidance
  happens to sit above the temp dir.
"""
import json
import os
import shutil
import subprocess

from .base import Harness, HarnessResult

THINKING_LEVELS = {False: "off", True: "high"}


class PiHarness(Harness):
    name = "pi"

    def __init__(self, provider="local-dgx", model="montimage-dgx-spark",
                 binary="pi", agent_dir=None, extra_args=()):
        self.provider = provider
        self.model = model
        self.binary = binary
        self.agent_dir = agent_dir or os.environ.get("PI_CODING_AGENT_DIR")
        self.extra_args = list(extra_args)

    # --- discovery ------------------------------------------------------
    def available(self):
        path = shutil.which(self.binary)
        if not path:
            return False, f"{self.binary} not found on PATH"
        try:
            v = subprocess.run([path, "--version"], capture_output=True, text=True,
                               timeout=30).stdout.strip()
        except Exception as e:  # noqa: BLE001
            return False, f"{self.binary} --version failed: {e}"
        models = os.path.expanduser(
            os.path.join(self.agent_dir or "~/.pi/agent", "models.json"))
        if not os.path.exists(models):
            return False, f"no pi model catalogue at {models}"
        try:
            cat = json.load(open(models))
            provs = cat.get("providers", {})
        except Exception as e:  # noqa: BLE001
            return False, f"unreadable {models}: {e}"
        if self.provider not in provs:
            return False, (f"provider {self.provider!r} not in {models}; "
                           f"have: {', '.join(provs) or 'none'}")
        ids = [m.get("id") for m in provs[self.provider].get("models", [])]
        if self.model not in ids:
            return False, (f"model {self.model!r} not under provider {self.provider!r}; "
                           f"have: {', '.join(map(str, ids)) or 'none'}")
        return True, f"pi {v} via {self.provider}/{self.model}"

    def describe(self):
        ok, detail = self.available()
        return dict(harness="pi", provider=self.provider, model=self.model,
                    available=ok, detail=detail)

    # --- execution ------------------------------------------------------
    def _argv(self, prompt, thinking):
        return [
            self.binary, "-p", prompt,
            "--provider", self.provider,
            "--model", self.model,
            "--thinking", THINKING_LEVELS[bool(thinking)],
            "--mode", "json",
            "--no-session",         # no state carried between tasks
            "--no-context-files",   # do not discover AGENTS.md/CLAUDE.md above the temp dir
            "--no-extensions",      # extensions can call other models — see module docstring
            "--approve",            # trust the temp workspace, do not block on a prompt
        ] + self.extra_args

    def run(self, workdir, prompt, timeout=900, thinking=False):
        env = dict(os.environ)
        if self.agent_dir:
            env["PI_CODING_AGENT_DIR"] = self.agent_dir
        env["PI_OFFLINE"] = "1"     # no update checks mid-benchmark
        try:
            p = subprocess.run(self._argv(prompt, thinking), cwd=workdir, env=env,
                               capture_output=True, text=True, timeout=timeout,
                               # pi blocks forever on an inherited stdin it can never
                               # read; every task then times out with zero turns.
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return HarnessResult(stop_reason="timeout",
                                 error=f"pi exceeded {timeout}s")
        except Exception as e:  # noqa: BLE001
            return HarnessResult(stop_reason="error", error=f"{type(e).__name__}: {e}")

        res = parse_events(p.stdout)
        if p.returncode != 0 and not res.error:
            res.stop_reason = "error"
            res.error = (p.stderr or "").strip().splitlines()[-1:] and \
                (p.stderr or "").strip().splitlines()[-1][:200] or f"exit {p.returncode}"
        return res


def parse_events(stdout):
    """Fold pi's JSONL event stream into a HarnessResult."""
    res = HarnessResult(raw_log=stdout[-20000:])
    open_calls = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "turn_start":
            res.turns += 1
        elif t == "tool_execution_start":
            res.tool_calls += 1
            name = ev.get("toolName", "?")
            res.trace.append(name)
            open_calls[ev.get("toolCallId")] = name
        elif t == "tool_execution_end":
            if _call_failed(ev):
                res.failed_calls += 1
        elif t == "message_end":
            m = ev.get("message") or {}
            if m.get("role") == "assistant":
                u = m.get("usage") or {}
                res.input_tokens += u.get("input") or 0
                res.output_tokens += u.get("output") or 0
                res.reasoning_tokens += u.get("reasoning") or 0
                if m.get("stopReason"):
                    res.stop_reason = m["stopReason"]
        elif t == "agent_end":
            res.stop_reason = ev.get("reason") or res.stop_reason or "agent_end"
        elif t == "error":
            res.error = str(ev.get("message") or ev)[:200]
            res.stop_reason = "error"
    if res.stop_reason == "unknown" and res.turns:
        res.stop_reason = "finished"
    return res


def _call_failed(ev):
    """pi reports tool failure in a few shapes depending on the tool."""
    for key in ("isError", "error", "failed"):
        v = ev.get(key)
        if isinstance(v, bool) and v:
            return True
        if isinstance(v, str) and v:
            return True
    result = ev.get("result")
    if isinstance(result, dict):
        if result.get("isError") or result.get("error"):
            return True
    return False
