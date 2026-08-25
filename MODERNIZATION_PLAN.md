# Modernization Plan — llm-serving (m-bench)

Derived from [`MODERNIZATION_REPORT.md`](./MODERNIZATION_REPORT.md) · **Baseline at audit:** AMBER
**Test command of record:** `./bench validate && ./bench validate --suite agentic-all` · **Pass rate at audit:** `44/44` (28/28 + 16/16)

Every P0–P4 task's acceptance criteria include *"`./bench validate && ./bench validate --suite
agentic-all` passes at 44/44"*. The baseline is AMBER, not RED, so Pre carries that assertion too.

All 54 findings are scheduled; the **Deferred** section is empty by design.

## At a glance

| Phase | Sprints | Tasks | Closes | Milestone |
|---|---|---|---|---|
| Pre Agent environment | 1 | 3 | — (enables ME) | ME |
| P0 Stabilize | 1 | 7 | 4 High, 6 Low, 3 Medium | M0 |
| P1 Secure & Patch | 2 | 12 | 2 Critical, 6 High, 5 Medium, 1 Low | M1 |
| P2 Modernize | 1 | 3 | 1 High, 1 Medium | M2 |
| P3 Clean & Harden | 1 | 10 | 1 Critical, 6 Medium, 12 Low | M3 |
| P4 Polish | 1 | 6 | 3 Medium, 5 Low | M4 |

**Critical path:** `Pre.1 → Pre.2 → 0.1 → 0.2 → 0.5 → 1.5 → 1.6 → 2.5 → 3.2 → 3.3 → 4.1 → 4.2 → 4.6 → 4.7` — **22 working days**
(S = 1 d, M = 2 d, L = 5 d). Nothing in P0 starts before `ME`. The chain runs down the upgrade-wave
spine (W1 → W2 → W4) and out into the coverage-then-deduplicate work: Task 4.1 cannot start until
the `openai` major has settled, and the refactors in 4.2 → 4.6 → 4.7 cannot start until there is
coverage to catch them. Task 1.1 is the other pivot — every code-touching task in P1–P3 depends on
it, because the modules holding every Critical and High finding are at 0–37 % coverage today.

---

## Phase Pre — Agent environment

**Goal:** an agent can install, run and verify this repo from project files alone.
**Milestone ME:** `CLAUDE.md` and `AGENTS.md` both exist at the repo root; the recorded build and
test commands are documented in `CLAUDE.md` and in Pre.1's notes.

### Sprint Pre — Agent-runnable environment

#### Task Pre.1: Record the install, run and verify commands as project files

**Description**: The repo has an excellent `AGENTS.md` runbook aimed at *evaluating models*, but no
file records how to install and verify `benchkit` itself. Write down the toolchain floor
(Python ≥ 3.10, from `router.py:70` and `benchkit/runner.py:35`), the environment variables the
harness reads (`BENCH_BASE_URL`, `BENCH_MODEL`, `BENCH_THINKING`, `BENCH_MAX_TOKENS`,
`BENCH_SAMPLES`, `BENCH_CONCURRENCY`, `BENCH_TEST_TIMEOUT`, `PI_CODING_AGENT_DIR`), and the test
command of record. Serves milestone ME.

**Closes**: — (milestone-enabling: ME)

**Acceptance Criteria**:
- [ ] A committed file records the Python floor, every `BENCH_*` / harness env var, and the exact command `./bench validate && ./bench validate --suite agentic-all`
- [ ] `.env.example` exists listing every environment variable the harness reads, with a comment per variable
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: None

**Effort**: S

**Verify**: `test -f .env.example && ./bench validate && ./bench validate --suite agentic-all`

#### Task Pre.2: Create `CLAUDE.md`

**Description**: `CLAUDE.md` is **absent** — confirmed at audit. Create it with
`/agent-config create` targeting `CLAUDE.md`, carrying the commands recorded in Pre.1 and the
repo etiquette already stated in `AGENTS.md:120-140` (results are append-only; never edit a task's
tests; never restart a shared endpoint unapproved). Serves milestone ME. Do not run the skill while
planning.

**Closes**: — (milestone-enabling: ME)

**Acceptance Criteria**:
- [ ] `CLAUDE.md` exists at the repo root
- [ ] `CLAUDE.md` names `./bench validate && ./bench validate --suite agentic-all` as the verification command and the Python ≥ 3.10 floor
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: Pre.1

**Effort**: S

**Verify**: run `/agent-config create` targeting `CLAUDE.md`, then `test -f CLAUDE.md && grep -q 'bench validate' CLAUDE.md`

#### Task Pre.3: Improve `AGENTS.md`

**Description**: `AGENTS.md` is **present** (7.7 kB, a model-evaluation runbook). Run
`/agent-config update` targeting it — improve it against agent-config's checklists only. The
build/test commands stay in Pre.1's notes and `CLAUDE.md`; do not duplicate them here. Serves
milestone ME. Do not run the skill while planning.

**Closes**: — (milestone-enabling: ME)

**Acceptance Criteria**:
- [ ] `AGENTS.md` still contains all eight of its existing Guardrails after the update (no guardrail is lost to reformatting)
- [ ] `AGENTS.md` is improved against agent-config's checklists, with build/test commands left to `CLAUDE.md`
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: Pre.1

**Effort**: S

**Verify**: run `/agent-config update` targeting `AGENTS.md`, then `grep -c '^- \*\*Never\|^- \*\*Do not\|^- \*\*Report\|^- \*\*If' AGENTS.md`

---

## Phase P0 — Stabilize

**Goal:** a clean checkout installs, lints, typechecks and runs both suites — in CI, not just on
this machine.
**Milestone M0:** from a clean clone, install from the committed lockfile and CI reports both
validate suites at 44/44, `ruff check` at 0 errors over `benchkit/` and `router.py`, and `mypy` at
0 errors.

### Sprint 0 — Packaging, gates, and CI

#### Task 0.1: Add `pyproject.toml` declaring every dependency and the Python floor

**Description**: `router.py:19` imports `aiohttp`, which `requirements.txt` does not declare — and
whose line 1 comment claims there are no other dependencies. `openai>=1.40` is unbounded across
three majors while 2.31.0 is installed. No Python version is declared, though `X | None`
annotations require 3.10+. Fix all four together, and re-verify the README quick-start.

**Closes**: `F-DEP-001`, `F-DEP-002`, `F-DEP-004`, `F-DOCS-002`

**Acceptance Criteria**:
- [ ] `pyproject.toml` declares `requires-python = ">=3.10"`, `aiohttp` with a bounded constraint, and `openai>=2.0,<3`
- [ ] In a fresh virtualenv, `pip install -e .` then `python -c "import router"` and `./bench --help` both succeed
- [ ] Every command in `README.md:40-45` runs successfully against that fresh environment
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: Pre.2, Pre.3

**Effort**: S

**Verify**: `python3 -m venv /tmp/v && /tmp/v/bin/pip install -e . && /tmp/v/bin/python -c "import router, benchkit.cli"`

#### Task 0.2: Commit a lockfile

**Description**: Nothing pins the environment that produced `results/`. The repo's deliverable is
reproducible measurement; without a lock, no recorded number can be reproduced.

**Closes**: `F-DEP-003`

**Acceptance Criteria**:
- [ ] A lockfile (`uv.lock` or a fully-pinned `requirements.lock`) is committed and covers both direct dependencies with hashes
- [ ] Installing from the lockfile in a clean container yields the exact `openai` and `aiohttp` versions the lockfile names
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.1

**Effort**: M

**Verify**: `uv sync --locked && uv run ./bench validate` (or the `pip install -r requirements.lock --require-hashes` equivalent)

#### Task 0.3: Configure ruff and mypy in-repo, excluding the frozen archive

**Description**: Both tools are installed on this machine but configured nowhere in the repo, so
their rule sets are whatever the local default is. `results/` is an append-only campaign archive per
`AGENTS.md:127` — 7 of the 16 current ruff errors are in files that must never be edited, so exclude
that tree rather than fixing it.

**Closes**: `F-CI-003`

**Acceptance Criteria**:
- [ ] `pyproject.toml` contains `[tool.ruff]` and `[tool.mypy]` sections with `results/` excluded from both
- [ ] `ruff check .` reports exactly 9 errors (the `benchkit/` set) — not 16 — proving the exclusion works and nothing in `benchkit/` was silently suppressed
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.1

**Effort**: S

**Verify**: `ruff check . --no-cache --output-format=concise | tail -1`

#### Task 0.4: Clear every lint and type error in `benchkit/` and `router.py`

**Description**: Fix the 9 remaining ruff errors and the single mypy error: ambiguous `l` at five
sites, unused re-exports without `__all__`, one placeholder-free f-string, and the
`excluded_files` type narrowing.

**Closes**: `F-BUG-009`, `F-CLEAN-005`, `F-CLEAN-006`, `F-CLEAN-007`

**Acceptance Criteria**:
- [ ] `ruff check .` reports 0 errors
- [ ] `mypy benchkit router.py --ignore-missing-imports` reports 0 errors
- [ ] `benchkit/harness/base.py:60` declares `excluded_files: tuple[str, ...] = ()`
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.3

**Effort**: S

**Verify**: `ruff check . --no-cache && mypy benchkit router.py --ignore-missing-imports`

#### Task 0.5: Stand up CI

**Description**: Nothing runs on push or PR — `gh run list` shows only GitHub's own Dependency
Graph job, and PR #1 merged with the type error and 16 lint errors present. Run this task via
`/devops-pipeline`.

**Closes**: `F-CI-001`

**Acceptance Criteria**:
- [ ] `.github/workflows/ci.yml` runs on `push` and `pull_request` and executes, in order: install from the lockfile, `ruff check .`, `mypy`, `./bench validate`, `./bench validate --suite agentic-all`
- [ ] A deliberately-introduced lint error causes the workflow to fail; reverting it makes it pass
- [ ] The workflow reports both suites at 44/44 on a clean checkout
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.2, 0.4

**Effort**: S

**Verify**: run `/devops-pipeline`, then `gh run list --limit 1` shows a green run of `ci.yml`

#### Task 0.6: Add pre-commit hooks

**Description**: On a repo where an agent is the primary author, nothing catches lint or type
errors before commit. Run this task via `/devops-pipeline`.

**Closes**: `F-CI-002`

**Acceptance Criteria**:
- [ ] `.pre-commit-config.yaml` exists with ruff and mypy hooks scoped to `benchkit/` and `router.py`
- [ ] `pre-commit run --all-files` exits 0
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.5

**Effort**: S

**Verify**: `pre-commit run --all-files`

#### Task 0.7: Configure coverage and report it in CI

**Description**: Coverage is measurable only by hand-running `coverage` from outside the repo. The
audit measured 28 % of `benchkit/` under both validate suites; make that number reproducible and
visible so M3's target can be checked.

**Closes**: `F-TEST-003`

**Acceptance Criteria**:
- [ ] `pyproject.toml` contains a `[tool.coverage]` section with `source = ["benchkit"]`
- [ ] CI runs coverage over both validate suites and prints a total; the first recorded run reports 28 % ± 2, matching the audit baseline
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.5

**Effort**: S

**Verify**: `coverage run --source=benchkit ./bench validate && coverage run -a --source=benchkit ./bench validate --suite agentic-all && coverage report`

---

## Phase P1 — Secure & Patch

**Goal:** close the two defects that make the benchmark's own numbers untrustworthy, close the
network exposure, and ship waves W1–W2.
**Milestone M1:** `pip-audit` reports 0 High/Critical advisories; both direct dependencies are at
the latest patch/minor within their declared bound; the sandbox escape and the zero-work PASS each
have a regression test that fails on the pre-fix code; `router.py` binds loopback by default.

### Sprint 1 — Characterization tests, then the two Criticals

#### Task 1.1: Characterization tests for the untested modules

**Description**: Every Critical and High `BUG` finding sits in a module at 0–37 % coverage
(`benchkit/harness/base.py`, `benchkit/harness/{pi,opencode,claudecode,runner}.py`, `benchkit/serving.py` at 0 %;
`benchkit/report.py` 6 %; `benchkit/runner.py` 37 %), so no fix below can be verified against a regression today.
Pin current behaviour first. Run this task via `/test-coverage` on those modules.

**Closes**: `F-TEST-002`

**Acceptance Criteria**:
- [ ] A `tests/` suite exists and `pytest` collects > 0 tests (it collects 0 today)
- [ ] `benchkit/harness/base.py`, `benchkit/agentic/loop.py`, `benchkit/agentic/env.py`, `benchkit/serving.py` and `benchkit/report.py` each have ≥ 1 test exercising their scoring or file-writing path
- [ ] Coverage of `benchkit/` reported by CI is ≥ 45 % (up from the 28 % baseline)
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.7

**Effort**: L

**Verify**: run `/test-coverage` on `benchkit/harness` and `benchkit/agentic`, then `pytest -q && coverage report --fail-under=45`

#### Task 1.2: Close the sandbox escape

**Description**: `write_file` normalises with `path.strip("/")`, leaving `../` intact; the
traversing key is joined onto the sandbox root at `benchkit/agentic/env.py:117` and `benchkit/agentic/env.py:171`, so a model under
test writes outside the temp directory. Proven at audit. `edit_file` shares the normalisation.

**Closes**: `F-BUG-001`

**Acceptance Criteria**:
- [ ] A `_safe_path` helper rejects `..` segments and absolute paths, and is applied in `read_file`, `write_file`, `edit_file` and `run_python`
- [ ] Materialisation in `benchkit/agentic/env.py:_materialise_and_run` and `benchkit/agentic/env.py:check` re-validates each key before `os.path.join`, so a bad key cannot reach the filesystem by another route
- [ ] A regression test asserts `write_file("../escape.txt", ...)` raises `ToolError`, and fails against the pre-fix code
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.1

**Effort**: S

**Verify**: `pytest tests/ -k traversal -q && ./bench validate --suite agentic-all`

#### Task 1.3: Make zero tool calls score as zero work, in both scoring paths

**Description**: A model replying in prose with no tool calls passes `verify_no_change_needed` at
`efficiency = 1.0`. `benchkit/harness/base.py:92` guards only when `tool_calls == 0` **and** `turns == 0`, so
a one-turn prose reply slips through there too — narrower than its own comment claims — and
`benchkit/agentic/loop.py` has no guard at all. The two paths disagree, which undermines the cross-harness
comparison in `results/2026-08-20-pi-harness/`.

**Closes**: `F-BUG-002`

**Acceptance Criteria**:
- [ ] Both `benchkit/agentic/loop.py` and `benchkit/harness/base.py` refuse to score a run solved when `tool_calls == 0`, via one shared helper rather than two copies
- [ ] A regression test asserts a zero-tool-call run of `verify_no_change_needed` scores `passed=False`, and fails against the pre-fix code
- [ ] Re-scoring the archived `results/2026-08-20-pi-harness/*.json` under the new rule changes no recorded number (the audit found every `no_tool_call` run used ≥ 4 calls); if any number does change, the affected `results/*/REPORT.md` gains a correction note rather than being edited
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.1

**Effort**: S

**Verify**: `pytest tests/ -k zero_work -q && ./bench validate --suite agentic-all`

#### Task 1.4: Bind the router to loopback by default

**Description**: `router.py:21` defaults `LISTEN_HOST` to `0.0.0.0`, exposing every model behind it
to the whole network with no credential verified on any path — while the vLLM process it fronts
deliberately binds loopback (`start-qwen.sh:45`).

**Closes**: `F-SEC-001`

**Acceptance Criteria**:
- [ ] `LISTEN_HOST` defaults to `127.0.0.1`; a non-loopback bind requires an explicit `ROUTER_HOST` value
- [ ] When bound non-loopback, the router requires a bearer token from `ROUTER_TOKEN` and returns 401 without it; loopback binds stay open for local tooling
- [ ] A test asserts a tokenless request to a non-loopback bind returns 401
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.5

**Effort**: S

**Verify**: `python router.py & sleep 2; ss -ltnp | grep 8001 | grep -q 127.0.0.1`

#### Task 1.5: Install and gate a dependency vulnerability scanner (W1 enabler)

**Description**: `pip-audit` is not installed, so the `DEP` vulnerability column is **Not
Assessed**, not clean. Nothing can be said about advisories against `openai` or `aiohttp` until this
runs. Run this task via `/security-setup`.

**Closes**: `F-SEC-004`

**Acceptance Criteria**:
- [ ] `pip-audit` is a declared dev dependency and runs in CI against the committed lockfile
- [ ] The CI job fails on any High or Critical advisory and its first run's findings are recorded in the PR description
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 0.5

**Effort**: S

**Verify**: run `/security-setup`, then `pip-audit -r requirements.lock -f json`

#### Task 1.6: Ship upgrade wave W1 — security patches

**Description**: Apply the smallest version bump that clears every advisory 1.5 reports. Contents
are unknown until that scan runs — this task does not presume any advisory exists. Serves
milestone M1.

**Closes**: — (milestone-enabling: M1)

**Acceptance Criteria**:
- [ ] `pip-audit` reports 0 High or Critical advisories against the committed lockfile
- [ ] Each bump applied is the smallest that clears its advisory, with the advisory ID recorded in the commit message; if the scan found nothing, that is recorded explicitly instead
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.5

**Effort**: S

**Verify**: `pip-audit -r requirements.lock` exits 0

### Sprint 2 — Enforce the stated guardrails, harden the serving stack, ship W2

#### Task 2.1: Enforce the shared-endpoint restart guardrail

**Description**: `AGENTS.md:129` states "Never restart a shared serving endpoint without explicit
human approval". `bench compare` calls `serving.swap_to()` — which rewrites the launcher and
restarts the systemd unit — with no confirmation. The "DGX box only" help text is not a control.

**Closes**: `F-BUG-004`, `F-DOCS-003`

**Acceptance Criteria**:
- [ ] `bench compare` and `bench apply --restart` prompt for confirmation naming the unit and the model before any restart, and accept `--yes` for scripted runs
- [ ] A test asserts that a declined prompt performs no `systemctl` call and no launcher write
- [ ] `AGENTS.md:129` no longer overstates the protection — it describes an enforced control
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.1

**Effort**: S

**Verify**: `pytest tests/ -k restart_confirm -q`

#### Task 2.2: Refuse to overwrite an existing result file

**Description**: `bench run` writes `results/<date>/<slug>.json` with `open(out, "w")`. Two runs on
the same date with the same label silently overwrite each other, against `AGENTS.md:127`'s
append-only rule.

**Closes**: `F-BUG-005`, `F-DOCS-003`

**Acceptance Criteria**:
- [ ] `bench run` and `bench harness run` refuse to write over an existing path, suffixing with a counter or erroring with the conflicting path named
- [ ] A test asserts two identical `bench run` invocations produce two distinct result files and neither is truncated
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.1

**Effort**: S

**Verify**: `pytest tests/ -k no_clobber -q`

#### Task 2.3: Make the launcher rewrite atomic and reversible

**Description**: `benchkit/serving.py:74` and `benchkit/serving.py:33` truncate `start-qwen.sh` before writing. A
crash mid-write leaves an empty launcher and a service that cannot start, and neither call keeps
the previous contents, so `bench apply` is not reversible.

**Closes**: `F-BUG-006`

**Acceptance Criteria**:
- [ ] Both writes go to a sibling temp file and land via `os.replace()`, and a timestamped backup of the previous launcher is kept
- [ ] A test asserts that a write interrupted before `os.replace()` leaves the original launcher byte-identical
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.1

**Effort**: S

**Verify**: `pytest tests/ -k atomic_launcher -q`

#### Task 2.4: Add an isolation option for generated code, and disclose the risk

**Description**: `benchkit/runner.py:61`, `benchkit/agentic/env.py:122` and `benchkit/agentic/env.py:177` execute model-generated code via
`sys.executable` with the benchmark user's full filesystem, network and credential access. Running
generated code is inherent to the design; having no isolation option and no disclosure is not.

**Closes**: `F-BUG-003`, `F-DOCS-004`

**Acceptance Criteria**:
- [ ] A `BENCH_ISOLATE` setting selects between the current in-process subprocess and a container path (`--network=none`, read-only mount, memory and pid limits); the default is stated explicitly in the docs
- [ ] With the container path selected, a generated program attempting a network call or a write outside its mount fails, and the task is scored as a failure rather than crashing the run
- [ ] `README.md` and `AGENTS.md`'s Guardrails section both warn that `./bench run` executes arbitrary model output on the host
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44 under both isolation settings

**Dependencies**: 1.1

**Effort**: M

**Verify**: `BENCH_ISOLATE=container ./bench validate && BENCH_ISOLATE=none ./bench validate`

#### Task 2.5: Ship upgrade wave W2 — patch and minor batch

**Description**: With both direct dependencies declared and bounded (0.1) and locked (0.2), bring
them to the latest patch/minor inside their bounds, as one batch. No major moves here — that is
Task 3.3. Serves milestone M1.

**Closes**: — (milestone-enabling: M1)

**Acceptance Criteria**:
- [ ] `aiohttp` and `openai` are at the latest release within their declared constraints, and the lockfile is regenerated and committed
- [ ] No major version changed in this task (`openai` stays `<3`)
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.6

**Effort**: S

**Verify**: `pip list --outdated --format=json | jq '[.[] | select(.name=="openai" or .name=="aiohttp")]'`

#### Task 2.6: Harden the serving container and its media policy

**Description**: `start-qwen.sh:65` sets `--allowed-media-domains '*'`, letting the inference server
fetch images from any host named in a request. The container also runs `--user root` with
`--network host`, `--ipc host`, `--cap-add=IPC_LOCK` and `--trust-remote-code`. Several of those are
genuinely required on GB10; running as root is not.

**Closes**: `F-SEC-002`, `F-SEC-003`

**Acceptance Criteria**:
- [ ] `--allowed-media-domains` names an explicit list, or multimodal input is disabled, in all four launchers under `configs/` and `start-qwen.sh`
- [ ] The container runs as a non-root user, or `start-qwen.sh` carries a comment stating the measured reason root is required on GB10
- [ ] Each remaining privileged flag (`--network host`, `--ipc host`, `--cap-add=IPC_LOCK`, `--trust-remote-code`) has a one-line comment stating why it is required
- [ ] The endpoint serves `/v1/models` after the change and `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.4

**Effort**: M

**Verify**: `bash -n start-qwen.sh && curl -fsS http://127.0.0.1:8801/v1/models`

---

## Phase P2 — Modernize

**Goal:** pin the serving stack, and move the one dependency that has a major available.
**Milestone M2:** the vLLM image is pinned by digest in all four launchers, and `openai` is either
at 3.x with both suites at 44/44, or deferred with a written rationale committed to this plan.

> P2 is deliberately small. The project has two direct Python dependencies and no framework, so
> there is no long major-upgrade queue — that is a property of the repo, not an omission.

### Sprint 3 — Pin the stack, bump the one major

#### Task 3.1: Pin the vLLM container image by digest (wave W3)

**Description**: `start-qwen.sh:17`, `Dockerfile.gemma:8` and the two `configs/*.sh` launchers pin
to `:latest`. An upstream push silently changes the serving stack under a "known-good config" —
the one thing `configs/README.md` promises will not happen.

**Closes**: `F-DEP-005`

**Acceptance Criteria**:
- [ ] All four files reference the image by `@sha256:` digest, not `:latest`
- [ ] `configs/README.md` records the digest alongside each config's measured numbers
- [ ] The endpoint starts on the pinned digest and serves `/v1/models`
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 2.6

**Effort**: S

**Verify**: `grep -c '@sha256:' start-qwen.sh Dockerfile.gemma configs/*.sh` and `docker image inspect` the pinned digest

#### Task 3.2: Spike — retrieve the `openai` 3.x migration guide

**Description**: The audit did **not** retrieve the guide, and asserted no breaking changes from
memory. This task's whole output is the guide. Serves milestone M2.

**Closes**: — (milestone-enabling: M2)

**Acceptance Criteria**:
- [ ] A written migration note lists the 2.x → 3.x breaking changes affecting the streaming surface used at `benchkit/runner.py:89-108` and the tool-calling surface at `benchkit/agentic/loop.py:66-83`, each cited to the upstream changelog or migration guide
- [ ] The note states explicitly whether `extra_body={"chat_template_kwargs": ...}` and `stream_options={"include_usage": True}` survive the major
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 2.5

**Effort**: S

**Verify**: the migration note exists and cites its source URL or CHANGELOG entry per claim

#### Task 3.3: Bump `openai` 2.31.0 → 3.3.1 (wave W4)

**Description**: One major, one task. The SDK's streaming and tool-calling surfaces are exactly
what this repo depends on, so a regression here silently changes every measured number. Migration
source: the note produced by Task 3.2.

**Closes**: `F-DEP-002`

**Acceptance Criteria**:
- [ ] `pyproject.toml` declares `openai>=3.0,<4` and the lockfile is regenerated and committed
- [ ] Every breaking change named in Task 3.2's note is addressed in code, or explicitly recorded as not applicable
- [ ] A live re-run of `./bench run --suite all --samples 2` against the same endpoint scores within noise (≤ 8 points, the repo's own stated threshold) of `results/2026-08-17-thinking-mode/results_qwen38_live_2026-08-20.json`; a larger gap blocks the bump
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 3.2

**Effort**: M

**Verify**: `./bench run --suite all --samples 2 --label "openai3 check"` and compare pass@1 against the recorded run

---

## Phase P3 — Clean & Harden

**Goal:** raise coverage to a real number, remove the parallel copies that produced the scoring
divergence, and clear the accumulated robustness nits.
**Milestone M3:** CI reports coverage of `benchkit/` at ≥ **60 %**; no logic block is repeated three
or more times (`F-DEAD-001`, `F-DEAD-002`, `F-DEAD-003` all closed); `mypy --strict` is clean over
`benchkit/harness/`.

> Coverage target derivation: baseline 28 % + 20 points = 48 %, floored at 60 % per the plan rule →
> **60 %**. The 28 % baseline is coverage under `./bench validate`, the fixture gate, not under a
> unit suite — which did not exist at audit.

### Sprint 4 — Coverage, deduplication, robustness

#### Task 4.1: Raise `benchkit/` coverage to 60 %

**Description**: Build out from Task 1.1's characterization tests to the M3 target, prioritising
`benchkit/report.py` (6 %), `benchkit/runner.py` (37 %) and the harness adapters (0 %). Run via `/test-coverage`.

**Closes**: `F-TEST-001`

**Acceptance Criteria**:
- [ ] CI-reported coverage of `benchkit/` is ≥ 60 %
- [ ] No module in `benchkit/` remains at 0 % coverage
- [ ] `pytest -q` passes and runs in under 60 s so the pre-commit hook stays usable
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 3.3

**Effort**: L

**Verify**: run `/test-coverage` on `benchkit`, then `pytest -q && coverage report --fail-under=60`

#### Task 4.2: Merge the two `summarize()` implementations

**Description**: `benchkit/runner.py:151` and `benchkit/agentic/loop.py:151` share ~60 % of their body. Parallel copies of
scoring logic are exactly what produced the `F-BUG-002` divergence.

**Closes**: `F-DEAD-001`

**Acceptance Criteria**:
- [ ] One shared function computes `by_task`, `pass_all_samples`, `pass_any_sample`, `by_difficulty` and the token means; only kind-specific fields remain separate
- [ ] Re-running `report.build()` over every file in `results/**/*.json` produces byte-identical Markdown to the committed `results/*/REPORT.md` files
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.1

**Effort**: M

**Verify**: `for d in results/*/; do ./bench report $d/*.json --out /tmp/r.md && diff /tmp/r.md $d/REPORT.md; done`

#### Task 4.3: Extract one workspace-materialisation helper

**Description**: The "materialise a file dict into a temp directory" loop is written three times
(`benchkit/agentic/env.py:116`, `benchkit/agentic/env.py:171`, `benchkit/harness/base.py:71`) — and it is the site of `F-BUG-001`, so the
traversal fix currently has to be applied three times.

**Closes**: `F-DEAD-002`

**Acceptance Criteria**:
- [ ] A single `materialise(files, root)` helper is used by all three call sites, and it performs the `F-BUG-001` path validation once
- [ ] The `F-BUG-001` traversal regression test still fails against pre-fix code and passes after, proving the validation survived the refactor
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.1, 1.2

**Effort**: S

**Verify**: `grep -c 'os.makedirs(os.path.dirname' benchkit/agentic/env.py benchkit/harness/base.py` returns 1 total, then `pytest -q`

#### Task 4.4: Extract the `parse_events` skeleton

**Description**: Three adapters (`benchkit/harness/pi.py:110`, `benchkit/harness/opencode.py:149`, `benchkit/harness/claudecode.py:245`) share the
same fold-JSONL-into-`HarnessResult` skeleton, differing only in event names and field paths.

**Closes**: `F-DEAD-003`

**Acceptance Criteria**:
- [ ] A shared folder takes a per-adapter event map; each adapter's `parse_events` shrinks to that map plus its own quirks
- [ ] Replaying each recorded harness log through the refactored parser reproduces the `tool_calls`, `turns`, `input_tokens` and `output_tokens` in `results/2026-08-20-pi-harness/*.json` exactly
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.1

**Effort**: M

**Verify**: `pytest tests/ -k parse_events -q`

#### Task 4.5: Remove the dead `open_calls` correlation

**Description**: `benchkit/harness/pi.py:113` populates `open_calls` on every `tool_execution_start` and never reads
it — an unfinished start/end correlation.

**Closes**: `F-DEAD-005`

**Acceptance Criteria**:
- [ ] `open_calls` is either removed, or the correlation it was for is completed and asserted by a test
- [ ] `ruff check .` and `mypy` both report 0 errors
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.4

**Effort**: S

**Verify**: `grep -c open_calls benchkit/harness/pi.py`

#### Task 4.6: Split the three oversized functions

**Description**: `benchkit/report.py:60` `build()` is 205 lines across four abstraction levels; `benchkit/cli.py:250`
`main()` is 85 lines of flat argparse wiring; `benchkit/agentic/loop.py:51` `run_task()` is 79 lines mixing the turn
loop with scoring. Run via `code-review` mode `clean` first for the audit, then apply.

**Closes**: `F-CLEAN-001`, `F-CLEAN-002`, `F-CLEAN-003`

**Acceptance Criteria**:
- [ ] No function in `benchkit/` exceeds 50 lines
- [ ] Re-running `report.build()` over every `results/**/*.json` still produces byte-identical Markdown to the committed `results/*/REPORT.md` files
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.2

**Effort**: M

**Verify**: run `code-review` mode `clean`, then the AST line-count check reports 0 functions over 50 lines

#### Task 4.7: Clear the remaining readability findings

**Description**: 9-parameter constructors in the harness adapters, six `open()` calls without a
context manager, and the unreadable `and`/`or` stderr chain in `benchkit/harness/pi.py:105`. Run via `code-review`
mode `cleanup`.

**Closes**: `F-CLEAN-004`, `F-CLEAN-008`, `F-CLEAN-009`

**Acceptance Criteria**:
- [ ] No constructor in `benchkit/harness/` takes more than 4 positional parameters (settings grouped into a dataclass)
- [ ] No `open()` call in `benchkit/` occurs outside a `with` block
- [ ] `benchkit/harness/pi.py`'s stderr extraction matches the form already used in `benchkit/harness/opencode.py:144`
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.6

**Effort**: S

**Verify**: run `code-review` mode `cleanup`, then `grep -nE '(^|[^h])open\(' benchkit/**/*.py | grep -v 'with '`

#### Task 4.8: Fix the six input-and-formatting robustness defects

**Description**: `benchkit/runner.py:75` unlink-in-finally, `benchkit/runner.py:44` env truthiness, `benchkit/runner.py:45`
uncaught `ValueError`, `benchkit/report.py:50` zero-height chart axis, `benchkit/report.py:13` unvalidated load, and
`benchkit/cli.py:208` `None` formatting.

**Closes**: `F-BUG-010`, `F-BUG-011`, `F-BUG-012`, `F-BUG-013`, `F-BUG-014`, `F-BUG-015`

**Acceptance Criteria**:
- [ ] `BENCH_THINKING=off` and `BENCH_THINKING=no` both disable thinking, asserted by a test
- [ ] `BENCH_MAX_TOKENS=abc` produces a named usage error, not a raw traceback
- [ ] `report.load()` on a truncated JSON names the offending file; `_chart` with all-zero values emits a positive y-axis; `benchkit/cli.py:208` formats a `None` token count without raising
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.1

**Effort**: S

**Verify**: `pytest tests/ -k "env_parsing or report_robust" -q`

#### Task 4.9: Make the report rank on one key and surface task-set gaps

**Description**: The "where they disagree" section re-sorts on `pass_at_1` while the results table
bolds the winner by `agent_score`, so with three or more agentic runs it can compare a pair
excluding the declared winner. It also drops tasks present in run B but not run A.

**Closes**: `F-BUG-007`

**Acceptance Criteria**:
- [ ] The disagreement section ranks on the same key the results table used, asserted by a test with three agentic runs where the two keys disagree
- [ ] A task present in one run but not the other appears in the section marked as not-run, rather than being omitted
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.2

**Effort**: S

**Verify**: `pytest tests/ -k disagree -q`

#### Task 4.10: Stop the restore path from masking campaign failures

**Description**: If the suite raises and `benchkit/cli.py:153`'s `finally` block restore also raises, the
restore error replaces the original traceback and the real cause is lost.

**Closes**: `F-BUG-008`

**Acceptance Criteria**:
- [ ] The restore is wrapped in its own try/except; a restore failure is logged with the model it failed to restore, and the original exception propagates
- [ ] A test asserts that when both the suite and the restore raise, the surfaced exception is the suite's
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.1

**Effort**: S

**Verify**: `pytest tests/ -k restore_masking -q`

---

## Phase P4 — Polish

**Goal:** bound the memory the harness adapters and the router hold, and make every documented
command and file reference true.
**Milestone M4:** peak RSS of `./bench harness run --harness opencode --suite agentic-hard
--samples 1` is recorded before and after Task 5.1 and does not increase; every command in
`README.md`, `AGENTS.md`, `SERVING.md` and `docs/*.md` executes successfully from a clean checkout;
no document references a file that does not exist.

> M4 carries no UX clause: `UX` is **Not Assessed — no UI detected**, and no UX findings were
> invented to fill it.

### Sprint 5 — Memory bounds and documentation truth

#### Task 5.1: Bound the harness log capture

**Description**: All three adapters use `subprocess.run(capture_output=True)` with a 900 s timeout
on a verbose JSONL stream, buffering the whole log in memory per concurrent task — recorded runs
reach 178,606 input tokens per task — while only `stdout[-20000:]` is ever kept.

**Closes**: `F-PERF-001`

**Acceptance Criteria**:
- [ ] All three adapters stream and fold line-by-line via `Popen`, retaining only a bounded rolling tail
- [ ] Peak RSS of `./bench harness run --harness opencode --suite agentic-hard --samples 1` is measured before and after, recorded in the PR, and does not increase
- [ ] The refactored parsers reproduce the counts in `results/2026-08-20-pi-harness/*.json` exactly
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.4

**Effort**: M

**Verify**: `/usr/bin/time -v ./bench harness run --harness opencode --suite agentic-hard --samples 1 2>&1 | grep 'Maximum resident'`

#### Task 5.2: Bound the router's request buffering

**Description**: `router.py:119` buffers the whole request body before dispatch and
`client_max_size=1024 ** 3` permits 1 GiB per concurrent request. The response path already streams
correctly; only the request path does not.

**Closes**: `F-PERF-002`

**Acceptance Criteria**:
- [ ] `client_max_size` is lowered to a documented ceiling justified by the 262 k-token context at `start-qwen.sh:52`
- [ ] A request exceeding the ceiling returns 413 rather than being buffered
- [ ] A 256 k-token prompt still routes successfully end to end
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 1.4

**Effort**: M

**Verify**: `curl -s -o /dev/null -w '%{http_code}' -X POST localhost:8001/v1/chat/completions --data-binary @/tmp/oversized.json`

#### Task 5.3: Stop the router re-discovering on every call

**Description**: `handle_models` calls `discover(force=True)` — which fetches `/v1/models` from
every backend — then immediately fetches `/v1/models` from the same backends again. Separately, a
request naming an unknown model triggers a forced re-discovery with no negative cache, so a
misconfigured client in a retry loop hammers every backend.

**Closes**: `F-PERF-003`, `F-PERF-004`

**Acceptance Criteria**:
- [ ] One `GET /v1/models` against the router produces exactly one upstream `/v1/models` call per backend, asserted by a test counting upstream requests
- [ ] Repeated requests naming the same unknown model trigger at most one re-discovery within a documented TTL
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 5.2

**Effort**: S

**Verify**: `pytest tests/ -k router_discovery -q`

#### Task 5.4: Clear the two remaining performance nits

**Description**: `benchkit/agentic/tasks_hard.py:639-641` calls `ws.changed_lines("tests.py")` twice in one
expression, each an O(n²) `difflib.ndiff`; `benchkit/agentic/loop.py:18` shares `_PAR_CACHE` across the thread pool
unguarded, so concurrent samples can each run the oracle.

**Closes**: `F-PERF-005`, `F-PERF-006`

**Acceptance Criteria**:
- [ ] `changed_lines` is computed once per evaluation of that predicate
- [ ] `par_calls` is either lock-guarded or precomputed before the pool starts; a test asserts the oracle runs exactly once per task under concurrency 4
- [ ] `./bench validate --suite agentic-all` still reports 16/16 and the recorded `par_calls` values are unchanged
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 4.1

**Effort**: S

**Verify**: `pytest tests/ -k "par_cache or changed_lines" -q`

#### Task 5.5: Repair the dangling rollback reference

**Description**: `SERVING.md:108`, `start-qwen.sh:6`, `configs/qwen3.6-35b-a3b-nvfp4.sh:6` and
`configs/ornith-1.5-35b-a3b-nvfp4.sh:6` all document `start-qwen.sh.qwen38.bak` as the rollback path
for the Qwen3.8 config. The file does not exist, so the documented recovery cannot be performed.

**Closes**: `F-DOCS-001`

**Acceptance Criteria**:
- [ ] All four references point at a file that exists — either a committed backup launcher or `configs/qwen3.8-27b-nvfp4-dspark.sh`
- [ ] A repo-wide check finds no documentation reference to a nonexistent repo-relative file
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 3.1

**Effort**: S

**Verify**: `grep -ohE '[A-Za-z0-9_./-]+\.(sh|py|md|json|bak)' README.md AGENTS.md SERVING.md ROADMAP.md docs/*.md configs/README.md | sort -u | while read f; do [ -e "$f" ] || echo "MISSING: $f"; done`

#### Task 5.6: Align the docs with the code

**Description**: Re-verify every documented command against the post-P3 tree, and record the
`results/` archive convention explicitly so its byte-identical duplicate scripts read as the
deliberate freeze they are rather than as drift. Run via `/doc-manager`.

**Closes**: `F-DEAD-004`

**Acceptance Criteria**:
- [ ] Every shell command quoted in `README.md`, `AGENTS.md`, `SERVING.md` and `docs/*.md` runs successfully against a clean checkout, or is marked as requiring the DGX host
- [ ] `docs/REPRODUCING.md` states that each `results/<date>-<name>/` directory carries its own frozen copy of the harness scripts, so the duplicate `results/2026-08-17-thinking-mode/bench.py` / `tasks.py` / `validate.py` files are intentional
- [ ] `./bench validate && ./bench validate --suite agentic-all` passes at 44/44

**Dependencies**: 5.5

**Effort**: S

**Verify**: run `/doc-manager` over the repo docs, then re-run the Task 5.5 dangling-reference check

---

## Dependency table

| Task | Depends on | Blocks | Wave |
|---|---|---|---|
| Pre.1 | — | Pre.2, Pre.3 | — |
| Pre.2 | Pre.1 | 0.1 | — |
| Pre.3 | Pre.1 | 0.1 | — |
| 0.1 | Pre.2, Pre.3 | 0.2, 0.3 | W0 |
| 0.2 | 0.1 | 0.5 | W0 |
| 0.3 | 0.1 | 0.4 | W0 |
| 0.4 | 0.3 | 0.5 | W0 |
| 0.5 | 0.2, 0.4 | 0.6, 0.7, 1.4, 1.5 | W0 |
| 0.6 | 0.5 | — | W0 |
| 0.7 | 0.5 | 1.1 | W0 |
| 1.1 | 0.7 | 1.2, 1.3, 2.1, 2.2, 2.3, 2.4 | — |
| 1.2 | 1.1 | 4.3 | — |
| 1.3 | 1.1 | — | — |
| 1.4 | 0.5 | 2.6, 5.2 | — |
| 1.5 | 0.5 | 1.6 | W1 |
| 1.6 | 1.5 | 2.5 | W1 |
| 2.1 | 1.1 | — | — |
| 2.2 | 1.1 | — | — |
| 2.3 | 1.1 | — | — |
| 2.4 | 1.1 | — | — |
| 2.5 | 1.6 | 3.2 | W2 |
| 2.6 | 1.4 | 3.1 | — |
| 3.1 | 2.6 | 5.5 | W3 |
| 3.2 | 2.5 | 3.3 | W4 |
| 3.3 | 3.2 | 4.1 | W4 |
| 4.1 | 3.3 | 4.2, 4.3, 4.4, 4.8, 4.10, 5.4 | — |
| 4.2 | 4.1 | 4.6, 4.9 | — |
| 4.3 | 4.1, 1.2 | — | — |
| 4.4 | 4.1 | 4.5, 5.1 | — |
| 4.5 | 4.4 | — | — |
| 4.6 | 4.2 | 4.7 | — |
| 4.7 | 4.6 | — | — |
| 4.8 | 4.1 | — | — |
| 4.9 | 4.2 | — | — |
| 4.10 | 4.1 | — | — |
| 5.1 | 4.4 | — | — |
| 5.2 | 1.4 | 5.3 | — |
| 5.3 | 5.2 | — | — |
| 5.4 | 4.1 | — | — |
| 5.5 | 3.1 | 5.6 | — |
| 5.6 | 5.5 | — | — |

## Execution waves

Everything within a wave can run in parallel.

| Wave | Tasks |
|---|---|
| 1 | Pre.1 |
| 2 | Pre.2, Pre.3 |
| 3 | 0.1 |
| 4 | 0.2, 0.3 |
| 5 | 0.4 |
| 6 | 0.5 |
| 7 | 0.6, 0.7, 1.4, 1.5 |
| 8 | 1.1, 1.6, 2.6, 5.2 |
| 9 | 1.2, 1.3, 2.1, 2.2, 2.3, 2.4, 2.5, 3.1, 5.3 |
| 10 | 3.2, 5.5 |
| 11 | 3.3, 5.6 |
| 12 | 4.1 |
| 13 | 4.2, 4.3, 4.4, 4.8, 4.10, 5.4 |
| 14 | 4.5, 4.6, 4.9, 5.1 |
| 15 | 4.7 |

## Milestones

| ID | Phase | Exit condition (measurable) | Verify with |
|---|---|---|---|
| ME | Pre | `CLAUDE.md` and `AGENTS.md` both exist; the test command of record and the Python ≥ 3.10 floor are documented in `CLAUDE.md`; `.env.example` lists every `BENCH_*` variable | `test -f CLAUDE.md && test -f AGENTS.md && test -f .env.example && grep -q 'bench validate' CLAUDE.md` |
| M0 | P0 | From a clean clone: install from the lockfile, then CI reports both validate suites at 44/44, `ruff check .` at 0 errors, `mypy` at 0 errors, and a coverage total | `gh run list --limit 1` green on `ci.yml` |
| M1 | P1 | `pip-audit` reports 0 High/Critical advisories; both direct deps at latest patch/minor within bounds; regression tests for `F-BUG-001` and `F-BUG-002` exist and fail against pre-fix code; router binds `127.0.0.1` by default | `pip-audit -r requirements.lock && pytest tests/ -k "traversal or zero_work" -q` |
| M2 | P2 | vLLM image pinned by `@sha256:` digest in all four launchers; `openai` at 3.x with both suites at 44/44 and pass@1 within 8 points of the recorded baseline — or deferred with a rationale committed to this file | `grep -c '@sha256:' start-qwen.sh Dockerfile.gemma configs/*.sh` and the Task 3.3 comparison run |
| M3 | P3 | CI-reported coverage of `benchkit/` ≥ **60 %**; no module at 0 %; `F-DEAD-001`, `F-DEAD-002`, `F-DEAD-003` all closed so no logic block repeats ≥ 3 times; `mypy --strict` clean over `benchkit/harness/` | `coverage report --fail-under=60 && mypy --strict benchkit/harness` |
| M4 | P4 | Peak RSS of `./bench harness run --harness opencode --suite agentic-hard --samples 1` recorded before and after Task 5.1 and not increased; every documented command runs from a clean checkout; no doc references a nonexistent file | `/usr/bin/time -v ./bench harness run ...` and the Task 5.5 dangling-reference check |

## Deferred and out of scope

| ID | Severity | Why deferred | Revisit when |
|---|---|---|---|

**Empty by design.** All 54 findings are closed by at least one task above. Nothing was deferred.

Two things are out of scope rather than deferred, and neither is a finding:

- **`UX`** — Not Assessed, no UI detected. The repo has no frontend files, dependencies or
  templates; the only interface is a CLI. No UX work is scheduled because none was found.
- **`results/**/*.py`** — 7 of the 16 baseline ruff errors live in the append-only campaign archive
  frozen by `AGENTS.md:127`. Task 0.3 excludes that tree from linting rather than editing it, and
  Task 5.6 documents the convention. Editing those files would break a stated guardrail.

## Risks

| Risk | Affects | Mitigation |
|---|---|---|
| Every Critical/High fix targets a module at 0–37 % coverage, so a fix can silently regress something else | Tasks 1.2, 1.3, 2.1–2.4, 2.6 | Task 1.1 lands characterization tests first and every one of those tasks depends on it |
| The `openai` 3.x bump touches the streaming and tool-calling surfaces that produce every measured number; a subtle behaviour change would look like a model regression | Task 3.3 | Task 3.2 is a mandatory spike; Task 3.3's third criterion is a live re-run compared against a recorded baseline within the repo's own 8-point noise threshold |
| Tasks 2.6, 3.1, 3.3 and 5.1–5.2 require restarting the shared vLLM endpoint, which `AGENTS.md:129` forbids without human approval | Tasks 2.6, 3.1, 3.3, 5.1, 5.2 | Task 2.1 makes the confirmation a real control before any of them run; schedule these in a maintenance window agreed with whoever else uses the box |
| The `F-BUG-002` fix changes how runs are scored; if any archived result did depend on the old rule, published numbers would move | Task 1.3 | Task 1.3's third criterion re-scores every archived result and requires either no change or an explicit correction note — never a silent edit of `results/` |
| Deduplicating `summarize()` and `parse_events` could change report output in ways unit tests miss | Tasks 4.2, 4.4, 4.6 | Each carries a byte-identical-output criterion checked against the committed `results/*/REPORT.md` and result files |
| Container hardening (2.6) may fail on GB10 for reasons only reproducible on that hardware | Task 2.6 | The criterion accepts a documented measured reason for keeping a privilege, rather than requiring the privilege be dropped |
