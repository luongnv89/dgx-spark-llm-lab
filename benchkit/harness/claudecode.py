"""Adapter for Claude Code (https://claude.com/claude-code).

Driven headless with `claude -p <prompt> --output-format stream-json --verbose`,
which emits one JSON event per line: `assistant` messages carrying `tool_use`
content blocks, `user` messages carrying `tool_result` blocks, and a final
`result` event with `num_turns`, `stop_reason` and cumulative `usage`.

### Pointing it at the local model

Claude Code speaks the **Anthropic Messages API**, not the OpenAI one, so
`BENCH_BASE_URL` (`.../v1`, OpenAI-shaped) is not directly usable. It works here
only because the local stack happens to serve both surfaces: vLLM implements
`/v1/messages` and `router.py` proxies it alongside `/v1/chat/completions`. The
adapter therefore points `ANTHROPIC_BASE_URL` at the API *root* (no `/v1`) and
`available()` probes `/v1/messages/count_tokens` explicitly — an endpoint that
serves OpenAI traffic but not Anthropic traffic would otherwise only fail once
every task had already burned its timeout.

There is no OpenAI-compatibility mode in Claude Code. Against a server that does
not implement `/v1/messages`, this adapter cannot be made to work and
`available()` says so rather than the run quietly measuring nothing.

### Keeping the run honest

Claude Code's defaults reach much further than pi's or opencode's, and several of
its built-in tools would invalidate the measurement outright:

| Flag | Why |
|---|---|
| `--bare` | skips hooks, LSP, plugin sync, auto-memory and **CLAUDE.md auto-discovery** — the counterpart to pi's `--no-context-files`, which otherwise leaks whatever guidance sits above the temp dir |
| `--tools ...` | pins the built-in set. The default set includes `Task`/`Workflow` (spawn subagents, which can be pointed at **other models**) and `WebSearch`/`WebFetch` (pull outside context into a local-model run). This is the counterpart to pi's `--no-extensions` and opencode's `--pure` |
| `--disable-slash-commands` | skills are user-installed prompt injections; this machine has dozens |
| `--strict-mcp-config` + empty `--mcp-config` | MCP servers are arbitrary external tools |
| `--no-session-persistence` | no state carries between tasks |
| `CLAUDE_CONFIG_DIR` | a throwaway config home per run, so nothing is read from or written to the user's |

`--permission-mode bypassPermissions` is safe here only because the workspace is
a throwaway temp directory, exactly as with opencode's `--auto`.

`stdin` is `DEVNULL`, for the reason recorded in the pi adapter.

### Telemetry, and what is missing

Better than ROADMAP feared, with one real gap:

- tool calls, failures and the trace come from `tool_use` / `tool_result` blocks;
- turns, stop reason and token totals come from the final `result` event;
- **reasoning tokens are not measurable.** Claude Code reports them in
  `usage.output_tokens_details.thinking_tokens`, which the local vLLM Anthropic
  surface reports as `0` even for responses that visibly contain `thinking`
  blocks. Those tokens are billed inside `output_tokens`, so the output column is
  right and the reasoning column reads `0`. `describe()` carries that caveat into
  every result file; do not read a `0` here as "this harness did not think".
"""
import json
import os
import shutil
import subprocess
import urllib.request

from .base import Harness, HarnessResult

#: Built-in tools the model is allowed. Deliberately excludes Task/Workflow
#: (subagents, which can reach other models) and WebSearch/WebFetch (outside
#: context) — see the module docstring.
DEFAULT_TOOLS = ("Bash", "Read", "Edit", "Write", "Glob", "Grep")

#: Environment this process may have inherited from a *parent* Claude Code
#: session. Left in place it would tell the child it is a nested/CI run and
#: change its behaviour mid-benchmark.
_SCRUB = (
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX",
    "CLAUDE_CODE_MAX_OUTPUT_TOKENS", "ANTHROPIC_MODEL", "ANTHROPIC_SMALL_FAST_MODEL",
    "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "ANTHROPIC_DEFAULT_HAIKU_MODEL", "CLAUDE_CONFIG_DIR",
)

CONFIG_DIR = "claude-home"


class ClaudeCodeHarness(Harness):
    name = "claude-code"

    _config_home = None

    def __init__(self, provider=None, model="montimage-dgx-spark",
                 base_url=None, binary="claude", api_key="sk-local",
                 tools=DEFAULT_TOOLS, effort=None, extra_args=()):
        # `provider` exists only so the shared CLI flag is accepted; Claude Code
        # has no provider concept for a custom base URL.
        self.provider = provider
        self.model = model
        self.base_url = _api_root(base_url or os.environ.get(
            "BENCH_BASE_URL", "http://localhost:8001/v1"))
        self.binary = binary
        self.api_key = api_key
        self.tools = list(tools)
        self.effort = effort
        self.extra_args = list(extra_args)

    # --- discovery ------------------------------------------------------
    def available(self):
        path = shutil.which(self.binary)
        if not path:
            return False, f"{self.binary} not found on PATH"
        try:
            v = subprocess.run([path, "--version"], capture_output=True, text=True,
                               timeout=60, stdin=subprocess.DEVNULL
                               ).stdout.strip().splitlines()[-1]
        except Exception as e:  # noqa: BLE001
            return False, f"{self.binary} --version failed: {e}"

        models_url = self.base_url + "/v1/models"
        try:
            with urllib.request.urlopen(models_url, timeout=10) as r:
                ids = [m.get("id") for m in json.load(r).get("data", [])]
        except Exception as e:  # noqa: BLE001
            return False, f"endpoint {models_url} unreachable: {e}"
        if self.model not in ids:
            return False, (f"model {self.model!r} not served at {self.base_url}; "
                           f"have: {', '.join(map(str, ids)) or 'none'}")

        # The load-bearing check: Claude Code speaks the Anthropic Messages API.
        # An OpenAI-only endpoint passes everything above and fails every task.
        ok, detail = self._probe_messages_api()
        if not ok:
            return False, detail
        return True, f"{v} via {self.base_url} ({self.model}, Messages API ok)"

    def _probe_messages_api(self):
        url = self.base_url + "/v1/messages/count_tokens"
        body = json.dumps({"model": self.model,
                           "messages": [{"role": "user", "content": "ping"}]}).encode()
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "content-type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                json.load(r)
        except Exception as e:  # noqa: BLE001
            return False, (f"{self.base_url} does not serve the Anthropic Messages "
                           f"API ({url}: {e}); Claude Code has no OpenAI-compatible "
                           f"mode, so it cannot be pointed at this endpoint")
        return True, "ok"

    def describe(self):
        ok, detail = self.available()
        return dict(
            harness=self.name, model=self.model, base_url=self.base_url,
            api="anthropic-messages", tools=self.tools, effort=self.effort,
            available=ok, detail=detail,
            caveats=[
                # Never let a missing number read as a cheap harness.
                "reasoning_tokens is always 0: Claude Code reports thinking tokens "
                "in usage.output_tokens_details.thinking_tokens, which this "
                "endpoint reports as 0 even when responses contain thinking "
                "blocks. Those tokens are counted inside output_tokens.",
                "--thinking does not toggle claude-code runs; the server's default "
                "thinking mode applies, as with the opencode adapter.",
                "Built-in tools are pinned to " + ",".join(self.tools) +
                "; Task/Workflow/WebSearch/WebFetch are disabled because they can "
                "reach other models or outside context.",
            ],
        )

    # --- workspace ------------------------------------------------------
    def prepare(self, container):
        """Task files in container/work; Claude Code's own state beside it.

        CLAUDE_CONFIG_DIR is pointed at a sibling directory so sessions, project
        state and history never land in the workspace that gets scored, and never
        touch the user's real ~/.claude.
        """
        workdir = os.path.join(container, "work")
        os.makedirs(workdir, exist_ok=True)
        self._config_home = os.path.join(container, CONFIG_DIR)
        os.makedirs(self._config_home, exist_ok=True)
        return workdir

    # --- execution ------------------------------------------------------
    def _argv(self, prompt):
        argv = [
            self.binary, "-p", prompt,
            "--model", self.model,
            "--output-format", "stream-json",
            "--verbose",                 # required for stream-json in print mode
            "--permission-mode", "bypassPermissions",  # throwaway temp workspace
            "--bare",                    # no hooks/plugins/auto-memory/CLAUDE.md
            "--disable-slash-commands",  # no user-installed skills
            "--strict-mcp-config",
            "--mcp-config", '{"mcpServers":{}}',
            "--no-session-persistence",  # no state between tasks
            "--setting-sources", "",     # ignore user/project/local settings
        ]
        if self.tools:
            argv += ["--tools", *self.tools]
        if self.effort:
            argv += ["--effort", self.effort]
        return argv + self.extra_args

    def run(self, workdir, prompt, timeout=900, thinking=False):
        env = {k: v for k, v in os.environ.items() if k not in _SCRUB}
        env["ANTHROPIC_BASE_URL"] = self.base_url
        env["ANTHROPIC_API_KEY"] = self.api_key
        env["ANTHROPIC_AUTH_TOKEN"] = self.api_key
        env["CLAUDE_CONFIG_DIR"] = (getattr(self, "_config_home", None)
                                    or os.path.join(os.path.dirname(workdir), CONFIG_DIR))
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["CLAUDE_CODE_ATTRIBUTION_HEADER"] = "0"
        env["DISABLE_AUTOUPDATER"] = "1"
        env["DISABLE_TELEMETRY"] = "1"
        env["DISABLE_ERROR_REPORTING"] = "1"
        env["DISABLE_BUG_COMMAND"] = "1"
        os.makedirs(env["CLAUDE_CONFIG_DIR"], exist_ok=True)
        try:
            p = subprocess.run(self._argv(prompt), cwd=workdir, env=env,
                               capture_output=True, text=True, timeout=timeout,
                               # see the pi adapter: an inherited stdin it can
                               # never read turns every task into a zero-turn
                               # timeout that looks like a model failure.
                               stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return HarnessResult(stop_reason="timeout",
                                 error=f"claude exceeded {timeout}s")
        except Exception as e:  # noqa: BLE001
            return HarnessResult(stop_reason="error", error=f"{type(e).__name__}: {e}")

        res = parse_events(p.stdout)
        if p.returncode != 0 and not res.error:
            res.stop_reason = "error"
            tail = [line for line in (p.stderr or "").strip().splitlines() if line.strip()]
            res.error = tail[-1][:200] if tail else f"exit {p.returncode}"
        return res


def _api_root(url):
    """Claude Code appends /v1/messages itself, so strip an OpenAI-style /v1."""
    url = url.rstrip("/")
    return url[:-3].rstrip("/") if url.endswith("/v1") else url


def parse_events(stdout):
    """Fold Claude Code's stream-json event stream into a HarnessResult."""
    res = HarnessResult(raw_log=stdout[-20000:])
    seen_calls = set()
    assistant_msgs = set()
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        t = ev.get("type")
        if t == "assistant":
            msg = ev.get("message") or {}
            assistant_msgs.add(msg.get("id"))
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    # one message is emitted once per content block, all sharing
                    # an id; dedupe on the tool_use id rather than the message
                    tid = block.get("id")
                    if tid in seen_calls:
                        continue
                    seen_calls.add(tid)
                    res.tool_calls += 1
                    res.trace.append(block.get("name", "?"))
        elif t == "user":
            msg = ev.get("message") or {}
            for block in msg.get("content") or []:
                if (isinstance(block, dict) and block.get("type") == "tool_result"
                        and block.get("is_error")):
                    res.failed_calls += 1
        elif t == "result":
            res.turns = ev.get("num_turns") or res.turns
            u = ev.get("usage") or {}
            # cache tokens are prefill too; the input column must stay comparable
            # with pi's and opencode's, which count every token sent.
            res.input_tokens += ((u.get("input_tokens") or 0)
                                 + (u.get("cache_creation_input_tokens") or 0)
                                 + (u.get("cache_read_input_tokens") or 0))
            res.output_tokens += u.get("output_tokens") or 0
            # always 0 on this endpoint — see the module docstring and describe()
            res.reasoning_tokens += (
                (u.get("output_tokens_details") or {}).get("thinking_tokens") or 0)
            if ev.get("subtype") == "success":
                res.stop_reason = ev.get("stop_reason") or "end_turn"
            else:
                res.stop_reason = "error"
                res.error = str(ev.get("result") or ev.get("subtype") or "error")[:200]
            if ev.get("is_error"):
                res.stop_reason = "error"
                res.error = res.error or str(ev.get("result") or "error")[:200]
    if not res.turns:
        res.turns = len(assistant_msgs)
    if res.stop_reason == "unknown" and res.turns:
        res.stop_reason = "finished"
    return res
