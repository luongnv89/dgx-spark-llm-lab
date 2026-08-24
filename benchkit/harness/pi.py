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

### Pointing it at an endpoint pi has never heard of

`--endpoint <url>` benchmarks a server that is not in the user's catalogue —
a freshly served HuggingFace model, a local vLLM — without touching their pi
configuration. pi has no base-URL flag, so the adapter does the same thing the
opencode and claude-code adapters do with `OPENCODE_CONFIG` / `CLAUDE_CONFIG_DIR`:
it stages a throwaway catalogue in the run's temp directory holding one
synthetic OpenAI-compatible provider pointed at the endpoint, and hands it to
the subprocess through `PI_CODING_AGENT_DIR`. The user's
`~/.pi/agent/models.json` is never written, and in this mode never even read —
their credentials stay where they are.

```bash
bench harness run --harness pi --endpoint http://localhost:8001/v1 \
    -m montimage-dgx-spark
```

Thinking in endpoint mode is best-effort: the staged provider declares a plain
OpenAI-compatible server, so a model that needs a particular `compat.thinkingFormat`
is still better added to pi's own catalogue.
"""
import json
import os
import shutil
import subprocess
import urllib.request

from .base import Harness, HarnessConfig, HarnessResult
from .events import parse_events as _parse_events
from .stream import StreamTimeout, stream_events

THINKING_LEVELS = {False: "off", True: "high"}

#: pi's model catalogue, relative to the agent directory
CATALOGUE_NAME = "models.json"

#: subdirectory of the run container holding the staged catalogue copy
STAGED_AGENT_DIR = "pi-agent"

#: where pi looks when neither --agent-dir nor PI_CODING_AGENT_DIR says otherwise
DEFAULT_AGENT_DIR = "~/.pi/agent"

#: provider id used for the staged catalogue in explicit-endpoint mode
DEFAULT_ENDPOINT_PROVIDER = "benchkit"

#: conservative limits for a server we know nothing about beyond its URL
ENDPOINT_CONTEXT_WINDOW = 128000
ENDPOINT_MAX_TOKENS = 16384


class PiHarness(Harness):
    name = "pi"

    def __init__(self, cfg=None, *, agent_dir=None):
        c = cfg or HarnessConfig()
        self.base_url = c.base_url or None
        self.provider = c.provider or (DEFAULT_ENDPOINT_PROVIDER if self.base_url else None)
        self.model = c.model
        self.binary = c.binary or "pi"
        #: the user's own agent directory. Read for a normal run, and in
        #: endpoint mode not even that — it is never opened for writing.
        self.agent_dir = agent_dir or os.environ.get("PI_CODING_AGENT_DIR")
        self.api_key = c.api_key
        self.extra_args = list(c.extra_args)

    @property
    def uses_endpoint(self):
        """True when this run reads a staged catalogue instead of the user's."""
        return bool(self.base_url)

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

    def _env(self, agent_dir=None):
        env = dict(os.environ)
        agent_dir = agent_dir or self.agent_dir
        if agent_dir:
            env["PI_CODING_AGENT_DIR"] = agent_dir
        env["PI_OFFLINE"] = "1"     # no update checks mid-benchmark
        return env

    def list_models(self):
        """Whatever `pi --list-models` prints: the user's own catalogue.

        The printed table is `provider  model  context  max-out  thinking
        images`, so the first two whitespace-separated columns are the pair we
        need. Falls back to reading `models.json` directly if the table cannot
        be parsed, because a listing failure must not look like an empty setup.

        In explicit-endpoint mode there is nothing to enumerate: the injected
        provider exists only for the duration of a run, and the model id is
        whatever the endpoint serves.
        """
        if self.uses_endpoint:
            return []
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

    def _catalogue_path(self, agent_dir=None):
        return os.path.expanduser(
            os.path.join(agent_dir or self.agent_dir or DEFAULT_AGENT_DIR,
                         CATALOGUE_NAME))

    def _catalogue(self, agent_dir=None):
        """(providers, error) read straight from pi's model catalogue file."""
        path = self._catalogue_path(agent_dir)
        if not os.path.exists(path):
            return None, f"no pi model catalogue at {path}"
        try:
            with open(path) as f:
                return json.load(f).get("providers", {}), None
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
        if self.uses_endpoint:
            # Nothing to count: an endpoint run does not consult the catalogue,
            # so reporting it empty would read as a broken pi install.
            return True, f"pi {v} — endpoint mode ({self.base_url})"
        n = len(self.list_models())
        return True, (f"pi {v} — {n} model(s) in your catalogue"
                      if n else f"pi {v} — no models in your catalogue")

    def available(self):
        v, err = self._version()
        if err:
            return False, err
        if not self.model:
            if self.uses_endpoint:
                # `harness models` cannot help here: the endpoint defines the id.
                return False, (f"pi {v}: --endpoint needs --model "
                               f"<id served by {self.base_url}>")
            return False, (f"pi {v}: no model selected — "
                           f"`bench harness models --harness pi`")
        if self.uses_endpoint:
            return self._endpoint_available(v)
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

    def _endpoint_available(self, v):
        """Check the model against the endpoint, not against your catalogue.

        In endpoint mode the catalogue cannot answer the question — the served
        model is deliberately not in it — so the endpoint's own `/models` is
        asked instead, exactly as the opencode adapter does.
        """
        url = self.base_url.rstrip("/") + "/models"
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                ids = [m.get("id") for m in json.load(r).get("data", [])]
        except Exception as e:  # noqa: BLE001
            return False, f"endpoint {url} unreachable: {e}"
        if self.model not in ids:
            return False, (f"model {self.model!r} not served at {self.base_url}; "
                           f"have: {', '.join(map(str, ids)) or 'none'}")
        return True, f"pi {v} via {self.base_url} ({self.model})"

    def describe(self):
        ok, detail = self.available()
        return dict(harness="pi", provider=self.provider, model=self.model,
                    model_spec=self.model_spec, base_url=self.base_url,
                    source="endpoint" if self.uses_endpoint else "pi-catalogue",
                    available=ok, detail=detail)

    @property
    def model_spec(self):
        return f"{self.provider}/{self.model}" if self.provider else self.model

    # --- workspace ------------------------------------------------------
    def prepare(self, container):
        """Endpoint mode: task files in container/work, staged catalogue beside.

        The staged catalogue is written into the run's own temp directory and
        handed to the subprocess through `PI_CODING_AGENT_DIR` — the seam
        `_env()` and `_catalogue_path()` already honour. Staging it in a sibling
        of the workspace rather than in the workspace itself keeps `models.json`
        out of the directory that gets read back and scored.

        Its path is derived from `container`, never remembered on `self`: a
        single harness instance serves every task, and the runner drives those
        tasks on a thread pool, so an instance field would let one task's
        subprocess be pointed at another task's directory after that one had
        been cleaned up.

        Without `--endpoint` nothing is staged and nothing is redirected: the
        run uses the user's own catalogue and credentials, unchanged.
        """
        if not self.uses_endpoint:
            return container
        workdir = os.path.join(container, "work")
        os.makedirs(workdir, exist_ok=True)
        staged = os.path.join(container, STAGED_AGENT_DIR)
        os.makedirs(staged, exist_ok=True)
        with open(os.path.join(staged, CATALOGUE_NAME), "w") as f:
            json.dump(self._staged_catalogue(), f, indent=2)
        return workdir

    def _staged_dir(self, workdir):
        """Where `prepare()` put this task's catalogue, from its workdir alone."""
        return os.path.join(os.path.dirname(workdir), STAGED_AGENT_DIR)

    def _staged_catalogue(self):
        """A catalogue holding the endpoint provider and nothing else.

        The user's own providers are deliberately *not* copied in. Nothing in an
        endpoint run can address them — `--model`/`--provider` both name the
        injected one — so copying them would only duplicate their `apiKey`
        values into a temp directory for no benefit, and would leave a route by
        which a run could reach a model other than the one being benchmarked.
        Their file is never opened here at all: copy out, never write back, and
        in this mode not even copy.
        """
        return {"providers": {self.provider: self._endpoint_provider()}}

    def _endpoint_provider(self):
        """One synthetic OpenAI-compatible provider aimed at `--endpoint`."""
        return {
            "name": f"benchkit ({self.base_url})",
            "baseUrl": self.base_url,
            "api": "openai-completions",
            # pi wants a key field; an open local server ignores the value.
            "apiKey": self.api_key or "not-needed",
            "compat": {"supportsReasoningEffort": False,
                       "maxTokensField": "max_tokens"},
            "models": [{
                "id": self.model,
                "name": self.model,
                "reasoning": True,
                "input": ["text"],
                "contextWindow": ENDPOINT_CONTEXT_WINDOW,
                "maxTokens": ENDPOINT_MAX_TOKENS,
                "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            }],
        }

    # --- execution ------------------------------------------------------
    def _argv(self, prompt, thinking, agent_dir=None):
        return [
            self.binary, "-p", prompt,
            # Only providers pi itself will accept; see the module docstring.
            *(["--provider", self.provider]
              if self._provider_addressable(agent_dir) else []),
            "--model", self.model,
            "--thinking", THINKING_LEVELS[bool(thinking)],
            "--mode", "json",
            "--no-session",         # no state carried between tasks
            "--no-context-files",   # do not discover AGENTS.md/CLAUDE.md above the temp dir
            "--no-extensions",      # extensions can call other models — see module docstring
            "--approve",            # trust the temp workspace, do not block on a prompt
        ] + self.extra_args

    def _provider_addressable(self, agent_dir=None):
        """Is `--provider <name>` a thing pi will accept, or listing-only?"""
        if not self.provider:
            return False
        provs, err = self._catalogue(agent_dir)
        return bool(not err and self.provider in provs)

    def run(self, workdir, prompt, timeout=900, thinking=False):
        # Endpoint mode reads the catalogue this task staged, found from the
        # workdir rather than from shared state — see prepare().
        agent_dir = self._staged_dir(workdir) if self.uses_endpoint else None
        env = self._env(agent_dir)
        try:
            res, rc, err_tail = stream_events(
                self._argv(prompt, thinking, agent_dir), cwd=workdir, env=env,
                handler=_pi_handler, timeout=timeout, label="pi")
        except StreamTimeout:
            return HarnessResult(stop_reason="timeout",
                                 error=f"pi exceeded {timeout}s")
        except Exception as e:  # noqa: BLE001
            return HarnessResult(stop_reason="error", error=f"{type(e).__name__}: {e}")

        if rc != 0 and not res.error:
            res.stop_reason = "error"
            tail = (err_tail or "").strip().splitlines()
            res.error = tail[-1][:200] if tail else f"exit {rc}"
        return res


def _pi_handler(ev, res, _state):
    """Handle one pi event. Mutates *res* in place."""
    t = ev.get("type")
    if t == "turn_start":
        res.turns += 1
    elif t == "tool_execution_start":
        res.tool_calls += 1
        name = ev.get("toolName", "?")
        res.trace.append(name)
        # open_calls was for a start/end correlation that was never completed —
        # left behind when the skeleton was first written; removed in #32.
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


def parse_events(stdout):
    """Fold pi's JSONL event stream into a HarnessResult."""
    return _parse_events(stdout, _pi_handler)


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
