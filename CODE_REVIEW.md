# Code Review Report

**Date**: 2026-08-20
**Scope**: Full audit — `benchkit/` (22 files) + `router.py`
**Mode**: Mode 1 (inline fast path — 23 files, ~3,800 lines, under the 50-file / 5K-line threshold)
**Commit**: `509220a`
**Excluded**: `results/**/*.py` (append-only campaign archive, frozen by `AGENTS.md` guardrail), `hf-cache/`, `vllm-cache/`
**Repo sync**: intentionally skipped — this review runs inside a read-only modernization audit that must not move `HEAD`, or every `path:line` citation below would go stale.

## Summary

| Severity | Count |
|----------|-------|
| Critical | 3     |
| Major    | 9     |
| Minor    | 16    |
| Info     | 2     |

---

## Critical Issues

### [Security]: Sandbox escape — `write_file` accepts traversing paths

**File**: `benchkit/agentic/env.py:65`
**Smell**: Missing input validation / path traversal

`write_file` normalises a model-supplied path with `path.strip("/")` only. That strips a leading
slash (so `/etc/passwd` is safely contained as `etc/passwd`) but leaves `../` untouched. The
traversing key is stored in `self.files` and later joined onto the sandbox root in
`_materialise_and_run` (`env.py:117-119`) and in `check` (`env.py:171-174`), so the write lands
outside the temp directory — anywhere the benchmark user can write.

Verified against the current tree:

```
write_file accepted: True | created ../benchkit_escape_probe.txt (7 bytes)
stored key in workspace: ['main.py', '../benchkit_escape_probe.txt']
run_python ok: True
probe written OUTSIDE the sandbox: True -> /tmp/benchkit_escape_probe.txt ESCAPED
```

Repeating `../` walks arbitrarily far up. The model under test authors these paths, so the blast
radius is "whatever the model emits". `edit_file` (`env.py:73`) shares the same normalisation.

**Before**:
```python
def write_file(self, path, content):
    path = path.strip("/")
    if not path:
        raise ToolError("path must not be empty")
```

**Suggested Fix**:
```python
def _safe_path(self, path):
    """Workspace-relative path, or a model-visible error. No escaping."""
    rel = os.path.normpath(path.strip("/"))
    if rel.startswith("..") or os.path.isabs(rel) or rel == ".":
        raise ToolError(f"path must stay inside the workspace: {path!r}")
    return rel

def write_file(self, path, content):
    path = self._safe_path(path)
```

Apply the same helper in `read_file`, `edit_file` and `run_python`, and re-check on
materialisation in `_materialise_and_run` / `check` so a bad key can never reach `os.path.join`.

---

### [Correctness]: A model that does no work scores a PASS

**File**: `benchkit/agentic/loop.py:109`
**Smell**: Missing guard / inconsistent scoring across two code paths

`run_task` scores `task["check"](ws)` over the final workspace without ever asking whether the
model actually did anything. For any task whose predicate is satisfied by the *initial* state —
`verify_no_change_needed` (`benchkit/agentic/tasks.py:255-292`) is scored precisely on the source
being untouched — a model that replies in prose and calls no tools passes. `loop.py:117-118` then
awards it `efficiency = 1.0`, the maximum, because it used zero calls.

Verified against the current tree:

```
loop.py path : tool_calls=0 solved=True efficiency=1.0 detail='OK'
```

`benchkit/harness/base.py:88-96` documents this exact hazard and guards against it — but its
condition is `hr.stop_reason in ("error", "timeout") or (hr.tool_calls == 0 and hr.turns == 0)`.
A harness that completes normally with one turn of prose and zero tool calls satisfies none of
those, so the external-harness path has the same hole its own comment says it closed. The two
scoring paths are also inconsistent with each other, which undermines the cross-harness
comparison in `results/2026-08-20-pi-harness/`.

No recorded result is currently wrong — every `no_tool_call` run in `results/` used ≥ 4 tool
calls. The defect is latent, not realised.

**Before**:
```python
# benchkit/harness/base.py:92
if hr.stop_reason in ("error", "timeout") or (hr.tool_calls == 0 and hr.turns == 0):
```

**Suggested Fix**:
```python
# benchkit/harness/base.py — zero tool calls is zero work, whatever the turn count
if hr.stop_reason in ("error", "timeout") or hr.tool_calls == 0:

# benchkit/agentic/loop.py — the same guard, so both paths score alike
if stop_reason in ("error",) or total_calls == 0:
    if solved:
        detail = f"no tool calls made ({stop_reason}); not counted as solved"
    solved = False
```

Share one helper between the two modules so they cannot drift apart again.

---

### [Security]: Model-generated code runs unsandboxed with full user privileges

**File**: `benchkit/runner.py:61`
**Smell**: Unsafe execution of untrusted input

`run_tests` concatenates the model's largest fenced code block with the task's tests and executes
it via `subprocess.run([sys.executable, path], ..., cwd=tempfile.gettempdir())`. There is no
container, no seccomp, no user drop, and no network restriction — the generated program runs as
the benchmark user with that user's filesystem, network and credential access. `env.py:122`
(`run_python`) and `env.py:177` (`check`) do the same for the agentic suites.

This is partly inherent: you cannot score generated code without running it. The defect is that
it is **nowhere disclosed** — neither `README.md` nor `AGENTS.md` warns that `./bench run` executes
arbitrary model output on the host, and `AGENTS.md`'s Guardrails section, which covers far smaller
risks, is silent on it.

**Suggested Fix** — containment plus disclosure, not removal:
```python
# benchkit/runner.py — opt-in isolation, defaulting to the safest available
def run_tests(task, code, timeout, isolate=os.environ.get("BENCH_ISOLATE", "container")):
    if isolate == "container":
        cmd = ["docker", "run", "--rm", "--network=none", "--read-only",
               "--memory=512m", "--pids-limit=128", "-v", f"{path}:/t.py:ro",
               "python:3.13-slim", "python", "/t.py"]
    else:
        cmd = [sys.executable, path]
```
and a stated warning in `README.md` and a new `AGENTS.md` guardrail line.

---

## Major Issues

### [Security]: Router binds to every interface with no authentication
**File**: `router.py:21`
**Smell**: Insecure default

`LISTEN_HOST = os.environ.get("ROUTER_HOST", "0.0.0.0")` exposes the router — and through it every
backing model — to the whole network by default. The vLLM process behind it deliberately binds
loopback only (`start-qwen.sh:45`: `--host 127.0.0.1`), so the router is the component that widens
the exposure, and it verifies no credential on any path (`proxy`, `router.py:117`). `SERVING.md:69`
confirms "Any `apiKey`/token value works (`sk-local`); nothing is verified."

Default to `127.0.0.1` and require an explicit opt-in for a wider bind.

### [Correctness]: `bench compare` restarts a shared endpoint with no confirmation
**File**: `benchkit/cli.py:137`
**Smell**: Missing guard, contradicts a stated project guardrail

`serving.swap_to(model_id)` rewrites the launcher and restarts the systemd unit
(`benchkit/serving.py:50-53`). `AGENTS.md:129` states: "**Never restart a shared serving endpoint
without explicit human approval.**" The code enforces nothing — no prompt, no `--yes`, no dry-run.
The docstring at `cli.py:126` and the CLI help both call it "DGX box only", which is not a control.

Add an interactive confirmation, plus `--yes` for scripted runs.

### [Correctness]: `bench run` silently overwrites an existing result file
**File**: `benchkit/cli.py:86`
**Smell**: Silent data loss, contradicts a stated project guardrail

`out = args.out or os.path.join(RESULTS, _stamp(), f"{_slug(cfg.label)}.json")` then
`open(out, "w")`. Two runs on the same date with the same label overwrite each other without a
word. `AGENTS.md:127` says results are append-only. Refuse to clobber, or suffix the filename.

### [Reliability]: Launcher rewrite is non-atomic and keeps no backup
**File**: `benchkit/serving.py:74`
**Smell**: Unsafe file write

`open(launcher, "w").write(src)` truncates `start-qwen.sh` before writing. A crash or a full disk
mid-write leaves an empty launcher and a service that cannot start. `serving.py:33` has the same
shape. Neither keeps the previous contents, so `bench apply` is not reversible. Write to a
temporary file in the same directory and `os.replace()` it into place.

### [Correctness]: Report's "where they disagree" can compare the wrong pair
**File**: `benchkit/report.py:222`
**Smell**: Inconsistent ranking keys

`best` is chosen on `agent_score` when the runs are scored (`report.py:139-140`), but the
disagreement section re-sorts on `pass_at_1` (`report.py:222`). With three or more agentic runs the
section can compare a pair that excludes the run the table bolds as the winner. Separately,
`report.py:225` iterates `sorted(ta)` only, so a task present in run B but not run A is dropped
without a note. Rank on one key, and surface non-overlapping task sets.

### [Reliability]: Cleanup in `finally` can mask the real failure
**File**: `benchkit/cli.py:153`
**Smell**: Exception swallowing

If the suite raises and `serving.swap_to(original)` in the `finally` block also raises, the restore
error replaces the original traceback — the actual cause of the failed campaign is lost. Wrap the
restore in its own try/except and log the restore failure.

### [Types]: Subclass narrows a base-class attribute type
**File**: `benchkit/harness/opencode.py:72`
**Smell**: Refused bequest

`excluded_files = (CONFIG_NAME,)` against `benchkit/harness/base.py:60`'s `excluded_files = ()`,
which mypy infers as `tuple[()]`. This is the repo's only type error:

```
benchkit/harness/opencode.py:72: error: Incompatible types in assignment
  (expression has type "tuple[str]", base class "Harness" defined the type as "tuple[()]")
```

Annotate the base as `excluded_files: tuple[str, ...] = ()`.

### [Dependencies]: `aiohttp` is imported but never declared
**File**: `router.py:19`
**Smell**: Broken build from a clean checkout

`from aiohttp import ClientSession, ClientTimeout, web` — but `requirements.txt` declares only
`openai>=1.40`. Following `README.md:40` (`pip install -r requirements.txt`) into a clean
environment and then running `router.py` raises `ModuleNotFoundError`.

### [Dependencies]: Unbounded version floor on the only declared dependency
**File**: `requirements.txt:2`
**Smell**: Irreproducible environment

`openai>=1.40` admits 1.x, 2.x and 3.x alike. Installed here is 2.31.0; PyPI's current release is
3.3.1. A fresh install today resolves to a different major than every result in `results/` was
produced under, and the SDK's streaming surface (`runner.py:89-108`) is exactly what majors change.
There is no lockfile. Pin a compatible range and commit a lock.

---

## Minor Issues

| # | File:line | Issue |
|---|---|---|
| 1 | `benchkit/agentic/loop.py:18` | `_PAR_CACHE` is an unbounded module global shared across the `ThreadPoolExecutor` in `loop.py:145`; two threads can run the same oracle concurrently. |
| 2 | `benchkit/runner.py:75` | `os.unlink(path)` in `finally` raises `FileNotFoundError` if the temp file is already gone, masking the test result. |
| 3 | `benchkit/serving.py:21` | `open(launcher).read()` with no context manager — handle leak / `ResourceWarning`. Same at `:27`, `:33`, `:63`, `:74`, and `benchkit/cli.py:115`. |
| 4 | `benchkit/runner.py:44` | `BENCH_THINKING` truthiness excludes only `("0","false","False","")`, so `no`, `off` and `NO` all enable thinking. |
| 5 | `benchkit/runner.py:45` | `int(e("BENCH_MAX_TOKENS", ...))` — a typo'd env var produces a raw `ValueError` traceback, not a usage message. Same at `:46`, `:47`, `:48`. |
| 6 | `benchkit/report.py:50` | `y_max = max(values) * 1.15` is `0` when every value is `0`, emitting a `0 --> 0` mermaid axis. |
| 7 | `benchkit/report.py:13` | `load()` performs no shape validation; a foreign or truncated JSON fails deep inside `build` with a bare `KeyError`. |
| 8 | `benchkit/cli.py:208` | `summary['mean_input_tokens']:.0f` raises `TypeError` when the value is `None` (empty result set). |
| 9 | `benchkit/harness/pi.py:105` | Error extraction via a nested `and`/`or` chain; `opencode.py:144` and `claudecode.py:234` express the same logic readably. |
| 10 | `benchkit/agentic/env.py:63` | E741 ambiguous variable name `l`. Also `report.py:63`, `:218`, `:261`, `claudecode.py:234`. |
| 11 | `benchkit/harness/__init__.py:5` | F401 — `Harness`, `HarnessResult`, `run_task` re-exported without `__all__`. |
| 12 | `benchkit/report.py:125` | F541 — f-string with no placeholders. |
| 13 | `benchkit/runner.py:151` / `benchkit/agentic/loop.py:151` | Duplicate Code — two `summarize()` functions sharing ~60 % of their body (`by_task`, `pass_all_samples`, `pass_any_sample`, `by_difficulty`, token means). |
| 14 | `benchkit/agentic/env.py:116` | Duplicate Code — the "materialise `self.files` into a temp dir" loop appears three times: here, `env.py:171`, and `benchkit/harness/base.py:71`. |
| 15 | `benchkit/report.py:60` | Long Method — `build()` is 205 lines mixing table assembly, chart emission and caveat prose. Also `cli.py:250` `main` (85), `loop.py:51` `run_task` (79), `claudecode.py:245` `parse_events` (58), `base.py:66` `run_task` (55), `router.py:117` `proxy` (52). |
| 16 | `benchkit/harness/claudecode.py:87` | Long Parameter List — `__init__` takes 9 parameters; `opencode.py:32` takes 7, `pi.py:30` takes 6. |

---

## Info

- **No unit tests for the harness itself.** `./bench validate` proves the *task fixtures* are
  winnable (28/28 and 16/16 pass), which is not the same as testing the code that runs them.
  Measured coverage of `benchkit/` under both validate suites is **28 %**, with
  `harness/base.py`, `harness/pi.py`, `harness/opencode.py`, `harness/claudecode.py`,
  `harness/runner.py` and `serving.py` at **0 %**, and `report.py` at 6 %. Every Major finding
  above sits in an untested module.
- **No CI.** No `.github/workflows/`, no pre-commit config. `ruff check .` currently reports 16
  errors and nothing gates them.

## Recommendations

1. Close the two Critical correctness/security defects first — the path-traversal escape
   (`env.py:65`) and the zero-work PASS (`loop.py:109`, `base.py:92`). Both are cheap fixes in an
   untested module, so land a regression test with each.
2. Fix the two places the code contradicts `AGENTS.md`'s own guardrails: unconfirmed service
   restart (`cli.py:137`) and silent result overwrite (`cli.py:86`). A guardrail a tool does not
   enforce is documentation, not a control.
3. Declare `aiohttp`, bound `openai`, and commit a lockfile — `results/` numbers are not
   reproducible until the environment that produced them is pinned.
4. Stand up CI running `ruff check .`, `mypy`, and both `bench validate` suites, then start unit
   tests at the 0 %-coverage modules that hold the Major findings.
5. Deduplicate the two `summarize()` implementations and the three temp-dir materialisation loops;
   the scoring divergence in Critical #2 is exactly what parallel copies produce.
