"""Adapter for opencode (https://opencode.ai).

Driven headless with `opencode run --format json`, which emits one JSON event per
line: `tool_use` for every tool call, `step_start`/`step_finish` for steps, and
per-step token counts on `step_finish`.

### Two ways to point it at a model

**Your existing setup** (the default). opencode already knows about providers you
have configured and authenticated — Anthropic, OpenAI, ollama, opencode's own
gateway, anything in `~/.config/opencode/opencode.json`. The adapter changes
nothing about that: it enumerates them with `opencode models` and runs the one
you select. Nothing is written to your config.

```bash
bench harness models --harness opencode
bench harness run --harness opencode --model ollama/qwen3-coder:latest
```

**An explicit endpoint** (`--endpoint http://host:port/v1`), for a server that
opencode has no entry for — a local vLLM or llama.cpp, say. Editing the user's
global config to add one would change how their editor behaves, so the adapter
writes a throwaway `opencode.json` into the *parent* of the task directory and
hands it over through `OPENCODE_CONFIG`: the provider exists for this run only
and never appears inside the workspace the model sees or the one that gets
scored.

`--pure` is the counterpart to pi's `--no-extensions` in both modes: it runs
without external plugins, which can otherwise reach other models or mutate
behaviour mid-benchmark.
"""
import json
import os
import shutil
import subprocess

from .base import Harness, HarnessConfig, HarnessResult
from .events import parse_events as _parse_events
from .stream import StreamTimeout, stream_events

CONFIG_NAME = "opencode.json"

#: provider id used for the throwaway config in explicit-endpoint mode
DEFAULT_ENDPOINT_PROVIDER = "benchkit"


class OpenCodeHarness(Harness):
    name = "opencode"

    _config_path = None

    def __init__(self, cfg=None, *, variant=None):
        c = cfg or HarnessConfig()
        self.base_url = c.base_url or None
        self.provider = c.provider or (DEFAULT_ENDPOINT_PROVIDER if self.base_url else None)
        self.model = c.model
        self.binary = c.binary or "opencode"
        self.variant = variant
        self.api_key = c.api_key
        self.extra_args = list(c.extra_args)

    @property
    def uses_endpoint(self):
        """True when this run injects its own provider instead of using yours."""
        return bool(self.base_url)

    @property
    def model_spec(self):
        return f"{self.provider}/{self.model}" if self.provider else self.model

    # --- discovery ------------------------------------------------------
    def _version(self):
        path = shutil.which(self.binary)
        if not path:
            return None, f"{self.binary} not found on PATH"
        try:
            out = subprocess.run([path, "--version"], capture_output=True, text=True,
                                 timeout=60, stdin=subprocess.DEVNULL).stdout
            return out.strip().splitlines()[-1], None
        except Exception as e:  # noqa: BLE001
            return None, f"{self.binary} --version failed: {e}"

    def probe(self):
        v, err = self._version()
        if err:
            return False, err
        n = len(self.list_models())
        return True, (f"opencode {v} — {n} model(s) configured"
                      if n else f"opencode {v} — no models configured")

    def list_models(self):
        """Whatever `opencode models` reports: the user's own providers.

        In explicit-endpoint mode the injected provider is not in that list (it
        exists only for the duration of a run), so there is nothing to enumerate
        and the model id is taken from the endpoint instead.
        """
        if self.uses_endpoint:
            return []
        path = shutil.which(self.binary)
        if not path:
            return []
        try:
            out = subprocess.run([path, "models"], capture_output=True, text=True,
                                 timeout=120, stdin=subprocess.DEVNULL)
        except Exception:  # noqa: BLE001
            return []
        entries = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line or "/" not in line or line.startswith(("-", "#")):
                continue
            provider, model = line.split("/", 1)
            entries.append((provider, model))
        return entries

    def available(self):
        v, err = self._version()
        if err:
            return False, err
        if not self.model:
            return False, (f"opencode {v}: no model selected — "
                           f"`bench harness models --harness opencode`")
        if self.uses_endpoint:
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

        entries = self.list_models()
        if entries and (self.provider, self.model) not in entries:
            return False, (f"model {self.model_spec!r} is not configured in opencode; "
                           f"`bench harness models --harness opencode` lists "
                           f"{len(entries)}")
        return True, f"opencode {v} via your opencode config ({self.model_spec})"

    def describe(self):
        ok, detail = self.available()
        return dict(harness="opencode", provider=self.provider, model=self.model,
                    model_spec=self.model_spec,
                    source="endpoint" if self.uses_endpoint else "opencode-config",
                    base_url=self.base_url, variant=self.variant,
                    available=ok, detail=detail)

    # --- workspace ------------------------------------------------------
    #: written next to the workspace, not into it — but excluded defensively
    excluded_files = (CONFIG_NAME,)

    def prepare(self, container):
        """Task files in container/work; any injected config beside it, not in it.

        In explicit-endpoint mode the config is handed to opencode through
        OPENCODE_CONFIG rather than left for its project-config search to find.
        Directory walking only picks it up under some invocations — running the
        identical argv through a shell found it, exec'ing it directly did not,
        and the failure surfaced as `ProviderModelNotFoundError` a second into
        every task. An explicit path is deterministic; `--dir` then puts the
        project root back on the workspace.
        """
        workdir = os.path.join(container, "work")
        os.makedirs(workdir, exist_ok=True)
        if self.uses_endpoint:
            self._config_path = os.path.join(container, CONFIG_NAME)
            with open(self._config_path, "w") as f:
                json.dump(self._config(), f, indent=2)
        return workdir

    def _config(self, thinking=None):
        options = {"baseURL": self.base_url}
        if self.api_key:
            options["apiKey"] = self.api_key
        return {
            "$schema": "https://opencode.ai/config.json",
            # the workspace is a throwaway temp dir; prompting for permission
            # would deadlock a headless run
            "permission": "allow",
            "provider": {
                self.provider: {
                    "name": f"benchkit ({self.base_url})",
                    "npm": "@ai-sdk/openai-compatible",
                    "options": options,
                    "models": {self.model: {"name": self.model}},
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
            "-m", self.model_spec,
        ]
        if self.variant:
            argv += ["--variant", self.variant]
        return argv + self.extra_args + [prompt]

    def run(self, workdir, prompt, timeout=900, thinking=False):
        env = dict(os.environ)
        if self.uses_endpoint:
            env["OPENCODE_CONFIG"] = getattr(self, "_config_path", None) or \
                os.path.join(os.path.dirname(workdir), CONFIG_NAME)
        env["OPENCODE_DISABLE_AUTOUPDATE"] = "1"
        try:
            res, rc, err_tail = stream_events(
                self._argv(prompt, workdir), cwd=workdir, env=env,
                handler=_opencode_handler, timeout=timeout, label="opencode")
        except StreamTimeout:
            return HarnessResult(stop_reason="timeout",
                                 error=f"opencode exceeded {timeout}s")
        except Exception as e:  # noqa: BLE001
            return HarnessResult(stop_reason="error", error=f"{type(e).__name__}: {e}")

        if rc != 0 and not res.error:
            res.stop_reason = "error"
            tail = (err_tail or "").strip().splitlines()
            res.error = tail[-1][:200] if tail else f"exit {rc}"
        return res


def _opencode_handler(ev, res, _state):
    """Handle one opencode event. Mutates *res* in place."""
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


def parse_events(stdout):
    """Fold opencode's JSONL event stream into a HarnessResult."""
    return _parse_events(stdout, _opencode_handler)
