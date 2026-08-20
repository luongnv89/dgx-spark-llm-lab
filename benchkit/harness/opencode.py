"""Adapter for opencode (https://opencode.ai).

Driven headless with `opencode run --format json`, which emits one JSON event per
line: `tool_use` for every tool call, `step_start`/`step_finish` for steps, and
per-step token counts on `step_finish`.

Unlike pi, opencode has no pre-existing entry for the local endpoint in this
machine's config, and editing the user's global `~/.config/opencode/opencode.json`
to add one would change how their editor behaves. Instead the adapter writes a
throwaway `opencode.json` into the *parent* of the task directory: opencode walks
up to find project config, so the provider is defined for this run only and never
appears inside the workspace the model sees or the one that gets scored.

`--pure` is the counterpart to pi's `--no-extensions`: it runs without external
plugins, which can otherwise reach other models or mutate behaviour mid-benchmark.
"""
import json
import os
import shutil
import subprocess

from .base import Harness, HarnessResult

CONFIG_NAME = "opencode.json"


class OpenCodeHarness(Harness):
    name = "opencode"

    _config_path = None

    def __init__(self, provider="local-dgx", model="montimage-dgx-spark",
                 base_url=None, binary="opencode", variant=None, extra_args=()):
        self.provider = provider
        self.model = model
        self.base_url = base_url or os.environ.get(
            "BENCH_BASE_URL", "http://localhost:8001/v1")
        self.binary = binary
        self.variant = variant
        self.extra_args = list(extra_args)

    # --- discovery ------------------------------------------------------
    def available(self):
        path = shutil.which(self.binary)
        if not path:
            return False, f"{self.binary} not found on PATH"
        try:
            v = subprocess.run([path, "--version"], capture_output=True, text=True,
                               timeout=60).stdout.strip().splitlines()[-1]
        except Exception as e:  # noqa: BLE001
            return False, f"{self.binary} --version failed: {e}"
        try:
            import urllib.request
            with urllib.request.urlopen(self.base_url.rstrip("/") + "/models",
                                        timeout=10) as r:
                ids = [m.get("id") for m in json.load(r).get("data", [])]
        except Exception as e:  # noqa: BLE001
            return False, f"endpoint {self.base_url} unreachable: {e}"
        if self.model not in ids:
            return False, (f"model {self.model!r} not served at {self.base_url}; "
                           f"have: {', '.join(map(str, ids)) or 'none'}")
        return True, f"opencode {v} via {self.base_url} ({self.model})"

    def describe(self):
        ok, detail = self.available()
        return dict(harness="opencode", provider=self.provider, model=self.model,
                    base_url=self.base_url, variant=self.variant,
                    available=ok, detail=detail)

    # --- workspace ------------------------------------------------------
    #: written next to the workspace, not into it — but excluded defensively
    excluded_files = (CONFIG_NAME,)

    def prepare(self, container):
        """Task files in container/work; the provider config beside it, not in it.

        The config is handed to opencode through OPENCODE_CONFIG rather than left
        for its project-config search to find. Directory walking only picks it up
        under some invocations — running the identical argv through a shell found
        it, exec'ing it directly did not, and the failure surfaced as
        `ProviderModelNotFoundError` a second into every task. An explicit path is
        deterministic; `--dir` then puts the project root back on the workspace.
        """
        workdir = os.path.join(container, "work")
        os.makedirs(workdir, exist_ok=True)
        self._config_path = os.path.join(container, CONFIG_NAME)
        with open(self._config_path, "w") as f:
            json.dump(self._config(), f, indent=2)
        return workdir

    def _config(self, thinking=None):
        model = {"name": self.model}
        return {
            "$schema": "https://opencode.ai/config.json",
            # the workspace is a throwaway temp dir; prompting for permission
            # would deadlock a headless run
            "permission": "allow",
            "provider": {
                self.provider: {
                    "name": f"benchkit ({self.base_url})",
                    "npm": "@ai-sdk/openai-compatible",
                    "options": {"baseURL": self.base_url},
                    "models": {self.model: model},
                }
            },
        }

    # --- execution ------------------------------------------------------
    def _argv(self, prompt, workdir):
        argv = [
            self.binary, "run",
            # --dir is not redundant with cwd: pointing OPENCODE_CONFIG at a file
            # outside the workspace moves opencode's idea of the project root with
            # it, and the model then reports it cannot find the task's files.
            "--dir", workdir,
            "--format", "json",
            "--auto",     # approve tool use; the workspace is a throwaway temp dir
            "--pure",     # no external plugins — they can reach other models
            "-m", f"{self.provider}/{self.model}",
        ]
        if self.variant:
            argv += ["--variant", self.variant]
        return argv + self.extra_args + [prompt]

    def run(self, workdir, prompt, timeout=900, thinking=False):
        env = dict(os.environ)
        cfg = getattr(self, "_config_path", None) or os.path.join(
            os.path.dirname(workdir), CONFIG_NAME)
        env["OPENCODE_CONFIG"] = cfg
        env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
        try:
            p = subprocess.run(self._argv(prompt, workdir), cwd=workdir, env=env,
                               capture_output=True, text=True, timeout=timeout,
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return HarnessResult(stop_reason="timeout",
                                 error=f"opencode exceeded {timeout}s")
        except Exception as e:  # noqa: BLE001
            return HarnessResult(stop_reason="error", error=f"{type(e).__name__}: {e}")

        res = parse_events(p.stdout)
        if p.returncode != 0 and not res.error:
            res.stop_reason = "error"
            tail = (p.stderr or "").strip().splitlines()
            res.error = tail[-1][:200] if tail else f"exit {p.returncode}"
        return res


def parse_events(stdout):
    """Fold opencode's JSONL event stream into a HarnessResult."""
    res = HarnessResult(raw_log=stdout[-20000:])
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type")
        part = ev.get("part") or {}
        if t == "step_start":
            res.turns += 1
        elif t == "tool_use":
            res.tool_calls += 1
            res.trace.append(part.get("tool", "?"))
            status = (part.get("state") or {}).get("status")
            if status not in ("completed", "running", "pending", None):
                res.failed_calls += 1
        elif t == "step_finish":
            tok = part.get("tokens") or {}
            res.input_tokens += tok.get("input") or 0
            res.output_tokens += tok.get("output") or 0
            res.reasoning_tokens += tok.get("reasoning") or 0
            if part.get("reason"):
                res.stop_reason = part["reason"]
        elif t == "error":
            res.error = str(part or ev)[:200]
            res.stop_reason = "error"
    if res.stop_reason == "unknown" and res.turns:
        res.stop_reason = "finished"
    return res
