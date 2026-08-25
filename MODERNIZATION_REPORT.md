# Modernization Report — llm-serving (m-bench)

**Audited:** 2026-08-20 · **Commit:** `509220a` · **Branch:** `main`
**Stack:** Python 3.13 (CPython), no packaging manifest · aiohttp router · Docker/vLLM serving scripts
**Size:** 41 source files (23 audited: `benchkit/` 22 + `router.py`), ~5.9 kLOC of Python and shell
**Baseline:** AMBER — imports clean and both fixture-validation suites pass 44/44, but there is no unit-test suite for the harness itself (28 % coverage, six modules at 0 %), 16 lint errors, and no CI

## Summary

| Severity | Count |
|---|---|
| Critical | 3 |
| High | 10 |
| Medium | 20 |
| Low | 21 |

This is a young, well-written, well-documented repo — nine commits over four days, dense
why-comments, and an unusually disciplined `AGENTS.md`. It is not stale. What it has instead is the
gap that fast, single-author, agent-assisted work produces: the code that *measures* is carefully
reasoned about, and the code that *runs the measurement* has never been tested, packaged, or gated.
Every Critical and High finding below sits in a module with 0–37 % coverage.

Two defects strike at the product itself. A model under test can escape the workspace sandbox and
write anywhere the benchmark user can (`benchkit/agentic/env.py:65`, proven, not inferred), and a
model that does no work at all scores a PASS with maximum efficiency on any task whose predicate is
satisfied by the initial state (`benchkit/agentic/loop.py:109`) — in a repo whose entire value is
that its numbers are honest. A third pair of findings is subtler and more telling: `AGENTS.md`
states two hard guardrails — never restart a shared endpoint without approval, never overwrite an
existing result — and the CLI enforces neither.

The plan puts the agent environment first, then stabilises (declare `aiohttp`, pin `openai`, commit
a lockfile, stand up CI), then closes the two Criticals with regression tests written against
modules that currently have none.

**Top 5 by impact:**
- `F-BUG-001` — a model can write outside the sandbox via `../` in `write_file`; verified by probe.
- `F-BUG-002` — zero-tool-call runs score solved at efficiency 1.0; the two scoring paths disagree.
- `F-TEST-001` — no unit test suite; 28 % coverage, and every High finding lives in a 0 % module.
- `F-DEP-001` — `router.py` imports `aiohttp`, which `requirements.txt` does not declare.
- `F-DEP-002` — `openai>=1.40` is unbounded across three majors; no result in `results/` is reproducible.

## Baseline

| Row | Value | Evidence |
|---|---|---|
| Build | pass — no build step; import check of all 22 modules succeeds | `python3 -c "import benchkit, benchkit.cli, ... benchkit.suites.hard12"` → `ALL IMPORTS OK` (exit 0) |
| Tests runnable | yes — the project's own fixture-validation gate | `./bench validate` and `./bench validate --suite agentic-all` |
| Test pass rate | 44/44 (28/28 reference solutions, 16/16 oracles), 0 skipped | `./bench validate` → `28/28 reference solutions pass`; `--suite agentic-all` → `16/16 oracles solve their task` |
| Unit tests | **none** — 0 collected | `python3 -m pytest -q -p no:cacheprovider --collect-only` → `no tests collected in 1.16s` |
| Coverage | 28 % of `benchkit/` under both validate suites; `benchkit/harness/base.py`, `benchkit/harness/pi.py`, `benchkit/harness/opencode.py`, `benchkit/harness/claudecode.py`, `benchkit/harness/runner.py`, `benchkit/serving.py` at **0 %**; `benchkit/report.py` 6 %; `benchkit/runner.py` 37 % | `python3 -m coverage run --source=benchkit ./bench validate` (+ `-a` for agentic-all), `coverage report -m` → `TOTAL 1363 984 28%` |
| Lint | **16 errors** (4 auto-fixable); 9 in `benchkit/`, 7 in the frozen `results/` archive; no in-repo ruff config | `ruff check . --no-cache` → `Found 16 errors.` |
| Typecheck | 1 error | `mypy benchkit router.py --ignore-missing-imports` → `benchkit/harness/opencode.py:72: error: Incompatible types in assignment` |
| CI | **absent** — no `.github/workflows/`, no `.pre-commit-config.yaml`, no `.gitlab-ci.yml`, no `Jenkinsfile`. The only Actions run on the remote is GitHub's own Dependency Graph job | `ls .github/workflows` → no such directory; `gh run list` → `Dependency Graph #1534190633` only |
| Runtime declared vs installed | **nothing declared** / Python 3.13.11 installed. Real floor is **3.10** (`X \| None` annotations evaluated at runtime) | `requirements.txt` (no `requires-python`); `router.py:70`, `benchkit/runner.py:35`; `python3 --version` |
| Lockfile | **missing** — `requirements.txt` holds one unpinned constraint, no `poetry.lock` / `uv.lock` / `requirements.lock` | `ls pyproject.toml setup.py Pipfile poetry.lock` → none exist |
| Last commit | 2026-08-20, 9 commits total, all within 2026-08-17 → 2026-08-20 | `git log -1 --format=%cd`; `git rev-list --count HEAD` |

**Verdict:** AMBER — it builds and its own gate is 100 %, but lint errors, a type error, no CI, and
no unit coverage of the code under audit.

**Test command of record:** `./bench validate && ./bench validate --suite agentic-all` — every
P0–P4 task's acceptance criteria reference this at ≥ 44/44. Pre ACs do not.

> **Note on what the gate proves.** `./bench validate` proves the *task fixtures* are winnable — that
> reference solutions pass the hidden tests and oracles solve their tasks. It is not a test of
> `benchkit` itself, which is why the baseline is AMBER rather than GREEN despite a 100 % pass rate.
> `F-TEST-001` records the distinction; the plan's coverage target is measured against it.

## Dimension coverage

| Dim | Disposition | Path | Findings |
|---|---|---|---|
| DEP | Audited | own probes (the codebase-modernizer skill's `dep_scan.sh` probe, 1 ecosystem: python) | 5 |
| BUG | Audited | delegated → `code-review` mode `review` | 15 |
| PERF | Audited | delegated → `code-review` mode `perf` | 6 |
| UX | Not Assessed — no UI detected | — | 0 |
| CLEAN | Audited | inline | 9 |
| DEAD | Audited | inline | 5 |
| TEST | Audited | inline | 3 |
| CI | Audited | inline | 3 |
| SEC | Audited | inline | 4 |
| DOCS | Audited | inline | 4 |

UX: no `*.tsx/*.jsx/*.vue/*.svelte/*.html/*.css` anywhere outside the caches, no `templates/`,
`static/` or `public/`, no frontend dependency. The only interface is a CLI. Per the skip rule this
is **Not Assessed — no UI detected**; no UX findings were invented.

## Dependency currency

Ecosystem: **python** (one manifest, `requirements.txt`, at the repo root; not a monorepo).

| ID | Package | Ecosystem | Declared | Installed | Latest | Gap | Risk | Blast | Wave | Severity | Evidence |
|---|---|---|---|---|---|---|---|---|---|---|---|
| F-DEP-001 | `aiohttp` | python | **undeclared** | 3.13.5 | 3.14.3 | n/a | build-breaking | 1 file | W0 | High | `router.py:19` imports it; `requirements.txt` does not list it (and `requirements.txt:1` asserts "this is the only dependency") |
| F-DEP-002 | `openai` | python | `>=1.40` | 2.31.0 | 3.3.1 | major×2 reachable under the declared floor | irreproducible | 2 files (`benchkit/runner.py:79`, transitively `benchkit/agentic/loop.py:133`) | W4 | High | `requirements.txt:2` |
| F-DEP-003 | — (lockfile) | python | — | — | — | n/a | irreproducible | repo-wide | W0 | High | no `poetry.lock` / `uv.lock` / pinned `requirements.lock`; `requirements.txt` is the only manifest |
| F-DEP-005 | container base image | docker | `:latest` | — | — | unpinned | irreproducible | 4 files | W3 | Medium | `start-qwen.sh:17`, `Dockerfile.gemma:8`, `configs/qwen3.6-35b-a3b-nvfp4.sh`, `configs/ornith-1.5-35b-a3b-nvfp4.sh` |

**Runtime and toolchain**

| Component | Declared | Installed | Current stable | Status | Severity |
|---|---|---|---|---|---|
| CPython | **nothing declared** (real floor 3.10, from `X \| None` runtime annotations at `router.py:70`, `benchkit/runner.py:35`) | 3.13.11 | 3.13.x | supported, but undeclared — a 3.9 host fails at import with no useful message | Medium (`F-DEP-004`) |
| ruff | not declared in-repo | 0.6.9 | — | present but ungated and unconfigured | see `F-CI-003` |
| mypy | not declared in-repo | 1.20.0 | — | present but ungated | see `F-CI-003` |
| vLLM container | `ghcr.io/miaai-lab/mia-vllm-gb10-linear-b12x:latest` | — | — | floating tag | Medium (`F-DEP-005`) |

**Vulnerability status: Not Assessed — `pip-audit` is not installed.** No advisory scan was run
against either dependency. Recorded as `F-SEC-004`; the plan installs and gates the scanner before
acting on whatever it finds.

**Upgrade waves**

| Wave | Contents | Lands in |
|---|---|---|
| W0 | declare `aiohttp`, bound `openai`, declare `requires-python >= 3.10`, commit a lockfile | P0 |
| W1 | security patches — contents unknown until `pip-audit` runs (`F-SEC-004`) | P1 |
| W2 | patch/minor batch for the two direct dependencies, once pinned | P1 |
| W3 | pin the vLLM container image by digest across all four launchers | P2 |
| W4 | `openai` 2.31.0 → 3.3.1 — **one task, migration guide not retrieved, spike required** | P2 |

## Findings

### DEP

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-DEP-001 | High | `router.py:19`, `requirements.txt:1-2` | `aiohttp` is imported but undeclared; a clean `pip install -r requirements.txt` then `python router.py` raises `ModuleNotFoundError`, and the manifest comment claims there are no other dependencies | Add `aiohttp` with a bounded constraint; correct the comment | S |
| F-DEP-002 | High | `requirements.txt:2` | `openai>=1.40` admits 1.x, 2.x and 3.x. Installed is 2.31.0; PyPI current is 3.3.1. The streaming surface at `benchkit/runner.py:89-108` is exactly what SDK majors change, so a fresh install can resolve to a major no recorded result was produced under | Bound to `>=2.0,<3` now; move to 3.x as its own task in W4 | S |
| F-DEP-003 | High | repo-wide — no lockfile exists | Nothing pins the environment that produced `results/`. The repo's stated value is reproducible measurement; without a lock, the numbers cannot be reproduced | Add `pyproject.toml` + a lockfile (`uv.lock` or `requirements.lock`); commit it | M |
| F-DEP-004 | Medium | `requirements.txt` (no `requires-python`), `router.py:70`, `benchkit/runner.py:35` | No Python version is declared anywhere, but `X \| None` annotations evaluated at runtime require 3.10+. A 3.9 host fails at import | Declare `requires-python = ">=3.10"` in `pyproject.toml`; add `.python-version` | S |
| F-DEP-005 | Medium | `start-qwen.sh:17`, `Dockerfile.gemma:8`, `configs/qwen3.6-35b-a3b-nvfp4.sh:*`, `configs/ornith-1.5-35b-a3b-nvfp4.sh:*` | The vLLM image is pinned to `:latest`. An upstream push silently changes the serving stack under a "known-good config", which is the one thing `configs/README.md` promises it will not do | Pin by digest (`@sha256:…`); record the digest in `configs/README.md` alongside the measured numbers | S |

### BUG

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-BUG-001 | Critical | `benchkit/agentic/env.py:65` (materialised at `benchkit/agentic/env.py:117`, `benchkit/agentic/env.py:171`) | `write_file` normalises with `path.strip("/")`, which leaves `../` intact. The traversing key is stored in `self.files` and joined onto the sandbox root, so the write lands outside the temp directory. **Proven:** `write_file("../benchkit_escape_probe.txt")` → accepted → file created at `/tmp/benchkit_escape_probe.txt`. Repeated `../` walks arbitrarily far. `edit_file` (`benchkit/agentic/env.py:73`) shares the normalisation | Add a `_safe_path` helper rejecting `..` and absolute paths; apply in `read_file`, `write_file`, `edit_file`, `run_python`, and re-check at materialisation | S |
| F-BUG-002 | Critical | `benchkit/agentic/loop.py:109`, `benchkit/harness/base.py:92`, task at `benchkit/agentic/tasks.py:255` | Neither scoring path asks whether the model did any work. A model replying in prose with zero tool calls passes `verify_no_change_needed` and is awarded `efficiency = 1.0` (`benchkit/agentic/loop.py:117`). **Proven:** `tool_calls=0 solved=True efficiency=1.0`. `benchkit/harness/base.py:92` guards only when `tool_calls == 0 **and** turns == 0`, so a one-turn prose reply slips through there too — the guard is narrower than its own comment claims. The two paths also disagree, undermining the cross-harness comparison in `results/2026-08-20-pi-harness/`. No recorded result is currently wrong (every `no_tool_call` run used ≥ 4 calls) | Change the guard to `tool_calls == 0` in both paths and share one helper so they cannot drift | S |
| F-BUG-003 | High | `benchkit/runner.py:61`, `benchkit/agentic/env.py:122`, `benchkit/agentic/env.py:177` | Model-generated code is executed via `sys.executable` with the benchmark user's full filesystem, network and credential access — no container, no seccomp, no user drop. Running generated code is inherent to the design; the defect is that it is nowhere disclosed and there is no isolation option | Add an opt-in `BENCH_ISOLATE` container path; document the risk in `README.md` and as an `AGENTS.md` guardrail | M |
| F-BUG-004 | High | `benchkit/cli.py:137`, `benchkit/serving.py:39` | `bench compare` calls `serving.swap_to()`, which rewrites the launcher and restarts the systemd unit, with no confirmation. `AGENTS.md:129` states "Never restart a shared serving endpoint without explicit human approval" — the code enforces nothing; the "DGX box only" help text is not a control | Add an interactive confirmation plus `--yes` for scripted runs | S |
| F-BUG-005 | High | `benchkit/cli.py:86-89` | `bench run` writes `results/<date>/<slug>.json` with `open(out, "w")`. Two runs on the same date with the same label silently overwrite each other, against `AGENTS.md:127`'s append-only rule | Refuse to clobber an existing path, or suffix with a counter | S |
| F-BUG-006 | High | `benchkit/serving.py:74`, `benchkit/serving.py:33` | `open(launcher, "w").write(src)` truncates `start-qwen.sh` before writing. A crash or full disk mid-write leaves an empty launcher and a service that cannot start; neither call keeps the previous contents, so `bench apply` is not reversible | Write to a sibling temp file and `os.replace()`; keep a timestamped backup | S |
| F-BUG-007 | Medium | `benchkit/report.py:222-225` | The "where they disagree" section re-sorts on `pass_at_1` while the results table bolds the winner by `agent_score` (`benchkit/report.py:139`), so with ≥ 3 agentic runs it can compare a pair excluding the declared winner. Separately it iterates `sorted(ta)` only, silently dropping tasks present in run B but not run A | Rank on one key; surface non-overlapping task sets explicitly | S |
| F-BUG-008 | Medium | `benchkit/cli.py:153-156` | If the suite raises and the `finally` block's `serving.swap_to(original)` also raises, the restore error replaces the original traceback and the real cause of the failed campaign is lost | Wrap the restore in its own try/except and log the restore failure separately | S |
| F-BUG-009 | Low | `benchkit/harness/opencode.py:72` | `excluded_files = (CONFIG_NAME,)` narrows `benchkit/harness/base.py:60`'s inferred `tuple[()]`. The repo's only type error | Annotate the base as `excluded_files: tuple[str, ...] = ()` | S |
| F-BUG-010 | Low | `benchkit/runner.py:75` | `os.unlink(path)` in `finally` raises `FileNotFoundError` if the temp file is already gone, masking the test result | Use `missing_ok=True` / guard the unlink | S |
| F-BUG-011 | Low | `benchkit/runner.py:44` | `BENCH_THINKING` excludes only `("0","false","False","")`, so `no`, `off` and `NO` all enable thinking — a silent methodology change | Parse with an explicit truthy/falsy set | S |
| F-BUG-012 | Low | `benchkit/runner.py:45-48` | `int(e("BENCH_MAX_TOKENS", ...))` and three siblings raise a raw `ValueError` traceback on a typo'd env var instead of a usage message | Validate and report the offending variable | S |
| F-BUG-013 | Low | `benchkit/report.py:50` | `y_max = max(values) * 1.15` is `0` when every value is `0`, emitting a `0 --> 0` mermaid axis | Floor `y_max` at a positive value | S |
| F-BUG-014 | Low | `benchkit/report.py:13-17` | `load()` performs no shape validation; a foreign or truncated result JSON fails deep inside `build()` with a bare `KeyError` | Validate required keys at load and name the offending file | S |
| F-BUG-015 | Low | `benchkit/cli.py:208` | `summary['mean_input_tokens']:.0f` raises `TypeError` when the value is `None` (empty result set) | Format through the existing `_fmt`-style None guard | S |

### PERF

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-PERF-001 | Medium | `benchkit/harness/pi.py:91`, `benchkit/harness/opencode.py:132`, `benchkit/harness/claudecode.py:219` | All three adapters use `subprocess.run(capture_output=True)` with a 900 s timeout on a verbose JSONL stream, buffering the entire log in memory per concurrent task. Recorded runs reach 178,606 input tokens per task (`results/2026-08-20-pi-harness/hard-opencode.json`), so the stream is multi-megabyte — and only `stdout[-20000:]` is ever kept (`benchkit/harness/pi.py:112`), so the full buffer is retained solely to be discarded | Stream and fold line-by-line via `Popen`, keeping only the rolling tail | M |
| F-PERF-002 | Medium | `router.py:119`, `router.py:187` | `raw = await request.read()` buffers the whole request body before dispatch, and `client_max_size=1024 ** 3` permits 1 GiB per concurrent request. The response path already streams correctly (`router.py:158`); only the request path does not | Lower `client_max_size` to a realistic ceiling; stream the request body upstream | M |
| F-PERF-003 | Low | `router.py:82-93` | `handle_models` calls `discover(session, force=True)` — which fetches `/v1/models` from every backend — then immediately fetches `/v1/models` from the same backends again. Exactly 2× the round trips for one response | Reuse the discovery result | S |
| F-PERF-004 | Low | `router.py:135` | A request naming an unknown model triggers `discover(force=True)` against every backend, with no negative cache or rate limit. A misconfigured client in a retry loop hammers every backend | Add a short-lived negative cache for unknown model names | S |
| F-PERF-005 | Low | `benchkit/agentic/tasks_hard.py:639-641` | `ws.changed_lines("tests.py")` is called twice in one expression; each call runs an O(n²) `difflib.ndiff` over the file (`benchkit/agentic/env.py:42-47`) | Compute once and bind it | S |
| F-PERF-006 | Low | `benchkit/agentic/loop.py:18-36` | `_PAR_CACHE` is an unguarded module global read and written from the `ThreadPoolExecutor` at `benchkit/agentic/loop.py:145`; concurrent samples of the same task can each run the oracle. Measured cost is small — 0.55 s total for all 16 agentic tasks — so this is a hygiene defect, not a bottleneck | Guard with a lock, or precompute par before the pool starts | S |

**Measured and deliberately not reported as findings.** Workspace materialisation plus sync-back
costs 24.0 ms per tool call on the largest agentic workspace (8 files) — ~0.6 s for a 25-turn task,
~19 s across all of `agentic-all` at 2 samples. Oracle par computation costs 0.55 s in total. Both
are negligible against multi-minute LLM latency; optimising them would be premature. No local
compute hot path was found.

### CLEAN

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-CLEAN-001 | Medium | `benchkit/report.py:60` | `build()` is 205 lines mixing setup-table assembly, results-table assembly, mermaid emission, per-task diffing and caveat prose at four levels of abstraction | Extract one function per report section | M |
| F-CLEAN-002 | Medium | `benchkit/cli.py:250` | `main()` is 85 lines of flat argparse wiring for eight subcommands | Split per-subcommand parser builders | S |
| F-CLEAN-003 | Medium | `benchkit/agentic/loop.py:51` | `run_task()` is 79 lines mixing the turn loop, tool dispatch, message accumulation, scoring and result shaping | Extract the turn loop from the scoring | M |
| F-CLEAN-004 | Low | `benchkit/harness/claudecode.py:87` | `__init__` takes 9 parameters; `benchkit/harness/opencode.py:32` takes 7 and `benchkit/harness/pi.py:30` takes 6 | Group harness settings into a config dataclass | S |
| F-CLEAN-005 | Low | `benchkit/agentic/env.py:63`, `benchkit/report.py:63`, `:218`, `:261`, `benchkit/harness/claudecode.py:234` | E741 — ambiguous variable name `l` at five sites | Rename to `line` / `label` | S |
| F-CLEAN-006 | Low | `benchkit/harness/__init__.py:5` | F401 — `Harness`, `HarnessResult`, `run_task` re-exported with no `__all__`, so linters cannot tell intent from accident | Declare `__all__` | S |
| F-CLEAN-007 | Low | `benchkit/report.py:125` | F541 — f-string with no placeholders | Drop the `f` prefix | S |
| F-CLEAN-008 | Low | `benchkit/harness/pi.py:105-106` | stderr extraction via a nested `and`/`or` chain; `benchkit/harness/opencode.py:144` and `benchkit/harness/claudecode.py:234` express the identical logic readably | Adopt the sibling adapters' form | S |
| F-CLEAN-009 | Low | `benchkit/serving.py:21`, `:27`, `:33`, `:63`, `:74`, `benchkit/cli.py:115` | `open()` without a context manager at six sites — handle leaks and `ResourceWarning` | Use `with` | S |

### DEAD

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-DEAD-001 | Medium | `benchkit/runner.py:151`, `benchkit/agentic/loop.py:151` | Two `summarize()` functions share ~60 % of their body (`by_task`, `pass_all_samples`, `pass_any_sample`, `by_difficulty`, token means). Parallel copies of scoring logic are exactly what produced the divergence in `F-BUG-002` | Extract the shared core; keep only the kind-specific fields separate | M |
| F-DEAD-002 | Medium | `benchkit/agentic/env.py:116-119`, `:171-174`, `benchkit/harness/base.py:71-75` | The "materialise a file dict into a temp directory" loop is written three times. It is also the site of `F-BUG-001`, so the traversal fix has to be applied three times as things stand | Extract one `materialise(files, root)` helper and route all three through it | S |
| F-DEAD-003 | Low | `benchkit/harness/pi.py:110`, `benchkit/harness/opencode.py:149`, `benchkit/harness/claudecode.py:245` | Three `parse_events()` implementations share the same fold-JSONL-into-`HarnessResult` skeleton, differing only in event names and field paths | Extract the skeleton; make each adapter supply an event map | M |
| F-DEAD-004 | Low | `results/2026-08-17-thinking-mode/{bench,tasks,validate}.py` vs `results/2026-08-18-vllm-vs-ollama/{bench,tasks,validate}.py` | Three file pairs are byte-identical (md5 match). `results/` is deliberately append-only per `AGENTS.md:127`, so this is documented, not accidental — but the duplication is real and future campaigns will keep adding copies | Leave the archive frozen; note the convention in `docs/REPRODUCING.md` so it reads as intentional | S |
| F-DEAD-005 | Low | `benchkit/harness/pi.py:113`, `:129` | `open_calls` is populated on every `tool_execution_start` and never read — presumably a start/end correlation that was not finished | Remove it, or finish the correlation it was for | S |

### TEST

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-TEST-001 | Critical | repo-wide — `pytest --collect-only` → `no tests collected` | No unit test suite exists for `benchkit`. `./bench validate` proves the task *fixtures* are winnable, not that the code running them is correct. Measured coverage of `benchkit/` under both validate suites is 28 % | Add a `tests/` suite and a runner config; start with the modules holding the Critical/High findings | L |
| F-TEST-002 | High | `benchkit/harness/base.py` 0 %, `benchkit/harness/pi.py` 0 %, `benchkit/harness/opencode.py` 0 %, `benchkit/harness/claudecode.py` 0 %, `benchkit/harness/runner.py` 0 %, `benchkit/serving.py` 0 %, `benchkit/report.py` 6 %, `benchkit/runner.py` 37 % | Every Critical and High `BUG` finding sits in a module with 0–37 % coverage, so none of their fixes can be verified against a regression today | Write characterization tests for these modules *before* the fixes land | L |
| F-TEST-003 | Medium | repo-wide — no `.coveragerc`, no `[tool.coverage]`, no coverage invocation in any script | Coverage is measurable only by hand-running `coverage` from outside the repo; nothing records or gates a number | Configure coverage in `pyproject.toml` and report it in CI | S |

### CI

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-CI-001 | High | repo-wide — no `.github/workflows/`, `.gitlab-ci.yml`, `Jenkinsfile`; `gh run list` shows only GitHub's Dependency Graph job | Nothing runs on push or PR. The two validate suites, ruff and mypy all pass locally and are enforced by nobody; PR #1 merged with the type error and 16 lint errors present | Add a workflow running both validate suites, `ruff check`, and `mypy` on push and PR | S |
| F-CI-002 | Medium | repo-wide — no `.pre-commit-config.yaml` | Nothing catches lint or type errors before commit, on a repo where an agent is the primary author | Add pre-commit with ruff and mypy hooks | S |
| F-CI-003 | Medium | `ruff check . --no-cache` → 16 errors; no `ruff.toml`, no `.ruff.toml`, no `pyproject.toml` | ruff and mypy are installed on this machine but configured nowhere in the repo, so their rule sets are whatever the local default happens to be — not reproducible for another contributor | Add `[tool.ruff]` and `[tool.mypy]` to `pyproject.toml`, with `results/` excluded as the frozen archive it is | S |

*Cross-references, excluded from all counts:* build reproducibility (missing lockfile) — see `F-DEP-003`; unpinned container base image — see `F-DEP-005`.

### SEC

Checked and clean: `git grep` for API-key, token, password, private-key and `sk-`/`ghp_`/`hf_`
patterns across all tracked files returned only prose matches on the words "token" and "thinking";
`git log -p -S` for private-key material and `git log --name-only` for `.env`/`.pem`/`id_rsa` in
history returned nothing. **No committed secret was found.**

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-SEC-001 | High | `router.py:21`, `router.py:117` | `LISTEN_HOST` defaults to `0.0.0.0`, exposing the router — and every model behind it — to the whole network, with no credential verified on any path. The vLLM process behind it deliberately binds loopback (`start-qwen.sh:45`), so the router is the component that widens the exposure. `SERVING.md:69` confirms "nothing is verified" | Default to `127.0.0.1`; require an explicit opt-in and a token for a wider bind | S |
| F-SEC-002 | Medium | `start-qwen.sh:65` | `--allowed-media-domains '*'` lets the inference server fetch images from any host named in a request — an SSRF surface reachable by anyone who can reach the endpoint, which per `F-SEC-001` is the whole LAN | Restrict to the domains actually needed, or drop multimodal input | S |
| F-SEC-003 | Medium | `start-qwen.sh:30`, `:31`, `:34`, `:35`, `:47` | The serving container runs `--user root` with `--network host`, `--ipc host`, `--cap-add=IPC_LOCK` and `--trust-remote-code`, which executes arbitrary code shipped in a Hugging Face checkpoint. Several of these are genuinely required for GB10; running as root is not | Drop to a non-root user; document per flag why the remaining privileges are required | M |
| F-SEC-004 | Medium | repo-wide — `pip-audit` not installed; no advisory scan in any script or workflow | No dependency vulnerability scanning exists, so the `DEP` vulnerability column is **Not Assessed** rather than clean | Add `pip-audit` to the dev requirements and gate it in CI | S |

### DOCS

| ID | Severity | Evidence | Problem | Fix direction | Effort |
|---|---|---|---|---|---|
| F-DOCS-001 | Medium | `SERVING.md:108`, `start-qwen.sh:6`, `configs/qwen3.6-35b-a3b-nvfp4.sh:6`, `configs/ornith-1.5-35b-a3b-nvfp4.sh:6` | Four places document `start-qwen.sh.qwen38.bak` as the rollback path for the Qwen3.8 config. **The file does not exist.** The documented recovery from a bad model swap cannot be performed | Either commit the backup launcher or repoint all four references at `configs/qwen3.8-27b-nvfp4-dspark.sh`, which does exist | S |
| F-DOCS-002 | Medium | `README.md:40-45` | The quick-start (`pip install -r requirements.txt`, then the `./bench` commands) does not produce a working `router.py`, because `aiohttp` is undeclared (`F-DEP-001`). A reader following README verbatim gets a `ModuleNotFoundError` the first time they start the router | Fix the manifest, then re-verify every README command against a clean environment | S |
| F-DOCS-004 | Medium | `AGENTS.md:120-140` (Guardrails), `README.md` | Nothing in the docs warns that `./bench run` executes arbitrary model-generated code on the host with the user's privileges (`F-BUG-003`). The Guardrails section covers far smaller risks in detail | Add an explicit guardrail and a README warning; document the isolation option when it lands | S |
| F-DOCS-003 | Low | `AGENTS.md:127`, `AGENTS.md:129` | Two guardrails are stated as absolutes that the tooling does not enforce (`F-BUG-004`, `F-BUG-005`). Until the code enforces them, the docs overstate the protection a reader has | Either enforce them in code (preferred, and planned) or mark them explicitly as conventions the CLI does not check | S |

## Cross-cutting patterns

- **The measuring code is reviewed; the measurement machinery is not.** Every Critical and High
  `BUG` finding sits in a module at 0–37 % coverage, while the task fixtures — the part with a
  validation gate — produced no findings at all. The gate the repo has is aimed at the half that
  was already careful. (`F-BUG-001`…`F-BUG-006`, `F-TEST-001`, `F-TEST-002`)
- **Stated guardrails are documentation, not controls.** `AGENTS.md` declares "never restart a
  shared endpoint without approval" and "never overwrite an existing result"; the CLI enforces
  neither, and there is no CI to notice. (`F-BUG-004`, `F-BUG-005`, `F-DOCS-003`, `F-CI-001`)
- **Parallel copies drift.** The same logic exists two or three times in three places — `summarize`,
  the temp-dir materialisation loop, `parse_events` — and in two of them the copies have already
  diverged in behaviour, which is precisely the `F-BUG-002` scoring inconsistency.
  (`F-DEAD-001`, `F-DEAD-002`, `F-DEAD-003`, `F-BUG-002`)
- **Nothing that produced the published numbers is pinned.** No lockfile, an unbounded `openai`
  floor spanning three majors, an undeclared `aiohttp`, an undeclared Python floor, and a `:latest`
  container tag — in a repo whose deliverable is reproducible measurement.
  (`F-DEP-001`…`F-DEP-005`)
- **Defaults are open where the components they wrap are closed.** vLLM binds loopback and the
  router binds `0.0.0.0`; the container needs GB10 privileges and also runs as root; media domains
  are `*`. (`F-SEC-001`, `F-SEC-002`, `F-SEC-003`)

## Artifacts written

| File | Why |
|---|---|
| `MODERNIZATION_REPORT.md` | this report |
| `MODERNIZATION_PLAN.md` | the derived plan |
| `CODE_REVIEW.md` | declared artifact — written by `code-review` mode `review` during the `BUG` audit |

No probe byproducts landed in the repo: `coverage` was run with `COVERAGE_FILE` pointed at a
scratch directory, and pytest's `--collect-only` ran with `-p no:cacheprovider`. `.pytest_cache/`
and `.ruff_cache/` already existed before this run and are unchanged.

**Tracked files modified: 0** — `git status --porcelain` and `git diff` match the pre-run snapshot
once the three artifacts above are set aside; `git diff --stat` is empty. Verified before and after
every probe.

## Limitations

- **UX — Not Assessed, no UI detected.** No frontend files, dependencies or templates exist; the
  only interface is a CLI. `dont-make-me-think` was not invoked and no UX findings were invented.
- **Dependency vulnerabilities — Not Assessed.** `pip-audit` is not installed, so neither `openai`
  nor `aiohttp` was checked against an advisory database. Recorded as `F-SEC-004`. `pip list
  --outdated` reached PyPI successfully, so latest-version data is real, not guessed — but the
  ambient conda environment it enumerated is not this project's environment; only the two
  project-relevant packages were carried into the `DEP` table.
- **`openai` 3.x migration guide not retrieved.** The W4 task is a spike whose first acceptance
  criterion is producing the guide. No breaking changes were asserted from memory.
- **`results/**/*.py` excluded from the CLEAN/DEAD/BUG scans** beyond lint counting. `AGENTS.md:127`
  freezes `results/` as an append-only campaign archive, so 7 of the 16 ruff errors are in files
  that are correctly never edited. They are counted in the baseline lint number and excluded from
  the findings.
- **Subagents were not used.** All ten dimensions ran inline and sequentially. At 41 source files
  this is the expected path for the repo-size branch, not a degradation — but `BUG` and `PERF` were
  delegated to `code-review` (modes `review` and `perf`) as the policy requires, so those two did
  receive their delegate's analysis.
- **`bench compare`, `bench apply` and `bench harness run` were never executed.** They restart a
  shared serving endpoint or drive external coding agents; both are excluded by the read-only
  contract, so their findings come from reading, not running.
- **Baseline coverage of 28 % is coverage under `./bench validate`**, the fixture gate — not under a
  unit suite, which does not exist. It is a floor for the plan's target, not a conventional
  coverage figure.

## Next step

The plan derived from this report: [`MODERNIZATION_PLAN.md`](./MODERNIZATION_PLAN.md).
