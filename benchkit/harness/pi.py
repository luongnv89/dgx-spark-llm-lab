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

### Pointing it at a model

pi resolves models through its own catalogue and credentials, so there is
nothing for this adapter to configure: whatever you can run in pi, you can
benchmark. `list_models()` shells out to `pi --list-models` and returns the
provider/model pairs it prints, which is how `bench harness models` and the
interactive picker learn what *your* install can reach.

```bash
bench harness models --harness pi
bench harness run --harness pi --model local-dgx/montimage-dgx-spark
```

One wrinkle in pi's addressing, learned the hard way: the `provider` column of
`--list-models` is not always a valid `--provider` value. Providers from pi's
bundled catalogues (`opencode-cli`, …) appear in the listing but are rejected by
`--provider`, which only knows the ones in `models.json`. Model **ids** resolve
globally, so the adapter passes `--model <id>` always and `--provider` only when
the provider really is one pi will accept — the listing's provider column is
kept for labelling and reporting either way.

There is no explicit-endpoint mode here, unlike the opencode and claude-code
adapters: pi has no way to take a base URL on the command line, and quietly
writing a provider into the user's `models.json` would change their editor.
Adding an endpoint means adding it to pi, once, the normal way.
"""
import json
import os
import shutil
import subprocess

from .base import Harness, HarnessResult

THINKING_LEVELS = {False: "off", True: "high"}


class PiHarness(Harness):
    name = "pi"

    def __init__(self, provider=None, model=None, base_url=None,
                 binary="pi", agent_dir=None, extra_args=()):
        if base_url:
            raise SystemExit(
                "the pi harness has no explicit-endpoint mode: pi resolves models "
                "through its own catalogue. Add the endpoint to pi's models.json "
                "once, then select it with --model <provider>/<model>.")
        self.provider = provider
        self.model = model
        self.binary = binary
        self.agent_dir = agent_dir or os.environ.get("PI_CODING_AGENT_DIR")
        self.extra_args = list(extra_args)

    # --- discovery ------------------------------------------------------
    def _version(self):
        path = shutil.which(self.binary)
        if not path:
            return None, f"{self.binary} not found on PATH"
        try:
            v = subprocess.run([path, "--version"], capture_output=True, text=True,
                               timeout=30, stdin=subprocess.DEVNULL).stdout.strip()
            return v.splitlines()[-1] if v else "?", None
        except Exception as e:  # noqa: BLE001
            return None, f"{self.binary} --version failed: {e}"

    def _env(self):
        env = dict(os.environ)
        if self.agent_dir:
            env["PI_CODING_AGENT_DIR"] = self.agent_dir
        env["PI_OFFLINE"] = "1"     # no update checks mid-benchmark
        return env

    def list_models(self):
        """Whatever `pi --list-models` prints: the user's own catalogue.

        The printed table is `provider  model  context  max-out  thinking
        images`, so the first two whitespace-separated columns are the pair we
        need. Falls back to reading `models.json` directly if the table cannot
        be parsed, because a listing failure must not look like an empty setup.
        """
        path = shutil.which(self.binary)
        if path:
            try:
                out = subprocess.run([path, "--list-models"], env=self._env(),
                                     capture_output=True, text=True, timeout=120,
                                     stdin=subprocess.DEVNULL).stdout
            except Exception:  # noqa: BLE001
                out = ""
            entries = []
            for line in out.splitlines():
                cols = line.split()
                if len(cols) < 2 or cols[0].lower() == "provider":
                    continue
                entries.append((cols[0], cols[1]))
            if entries:
                return entries
        return self._catalogue_models()

    def _catalogue_path(self):
        return os.path.expanduser(
            os.path.join(self.agent_dir or "~/.pi/agent", "models.json"))

    def _catalogue(self):
        """(providers, error) read straight from pi's model catalogue file."""
        path = self._catalogue_path()
        if not os.path.exists(path):
            return None, f"no pi model catalogue at {path}"
        try:
            return json.load(open(path)).get("providers", {}), None
        except Exception as e:  # noqa: BLE001
            return None, f"unreadable {path}: {e}"

    def _catalogue_models(self):
        provs, err = self._catalogue()
        if err:
            return []
        return [(name, m.get("id")) for name, p in provs.items()
                for m in p.get("models", []) if m.get("id")]

    def probe(self):
        v, err = self._version()
        if err:
            return False, err
        n = len(self.list_models())
        return True, (f"pi {v} — {n} model(s) in your catalogue"
                      if n else f"pi {v} — no models in your catalogue")

    def available(self):
        v, err = self._version()
        if err:
            return False, err
        if not self.model:
            return False, (f"pi {v}: no model selected — "
                           f"`bench harness models --harness pi`")
        entries = self.list_models()
        if not entries:
            return False, (f"pi {v} lists no models; check `pi --list-models` "
                           f"and {self._catalogue_path()}")
        if self.provider and not any(p == self.provider for p, _ in entries):
            return False, (f"provider {self.provider!r} is not in `pi --list-models`; "
                           f"have: {', '.join(sorted({p for p, _ in entries}))}")
        pool = [m for p, m in entries if not self.provider or p == self.provider]
        if self.model not in pool:
            where = (f"under provider {self.provider!r}" if self.provider
                     else "in your pi catalogue")
            return False, (f"model {self.model!r} not {where}; "
                           f"have: {', '.join(map(str, pool)) or 'none'}")
        return True, f"pi {v} via {self.model_spec}"

    def describe(self):
        ok, detail = self.available()
        return dict(harness="pi", provider=self.provider, model=self.model,
                    model_spec=self.model_spec, source="pi-catalogue",
                    available=ok, detail=detail)

    @property
    def model_spec(self):
        return f"{self.provider}/{self.model}" if self.provider else self.model

    # --- execution ------------------------------------------------------
    def _argv(self, prompt, thinking):
        return [
            self.binary, "-p", prompt,
            # Only providers pi itself will accept; see the module docstring.
            *(["--provider", self.provider] if self._provider_addressable() else []),
            "--model", self.model,
            "--thinking", THINKING_LEVELS[bool(thinking)],
            "--mode", "json",
            "--no-session",         # no state carried between tasks
            "--no-context-files",   # do not discover AGENTS.md/CLAUDE.md above the temp dir
            "--no-extensions",      # extensions can call other models — see module docstring
            "--approve",            # trust the temp workspace, do not block on a prompt
        ] + self.extra_args

    def _provider_addressable(self):
        """Is `--provider <name>` a thing pi will accept, or listing-only?"""
        if not self.provider:
            return False
        provs, err = self._catalogue()
        return bool(not err and self.provider in provs)

    def run(self, workdir, prompt, timeout=900, thinking=False):
        env = self._env()
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
