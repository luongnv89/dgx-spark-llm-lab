"""Adapter interface for running tasks through a real coding harness.

A model is only half of what a user runs; the other half is the harness wrapped
around it — its system prompt, its tool schemas, how it chunks edits, how many
turns it will spend. The same weights behind two harnesses are two different
products, so the honest question is not "how good is this model" but "how good is
this model *through the harness on this machine*".

Scoring does not change. Tasks are still scored by `check(ws)` over the final
workspace, and par still comes from our oracle — par measures the task, not the
harness, which is exactly what makes it a usable ruler across harnesses.
"""
import os
import shutil
import tempfile
import time
from dataclasses import dataclass, field

from ..agentic.env import Workspace


@dataclass
class HarnessResult:
    """What a harness did, normalised across implementations."""
    tool_calls: int = 0
    failed_calls: int = 0
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    stop_reason: str = "unknown"
    error: str = ""
    trace: list = field(default_factory=list)
    raw_log: str = ""


class Harness:
    """Run a prompt against a real directory and leave the result on disk."""

    name = "abstract"

    def available(self):
        """(ok, detail) — is this harness usable on this machine right now?"""
        raise NotImplementedError

    def describe(self):
        """Version and configuration, recorded in the result file."""
        return {}

    def prepare(self, container):
        """Given a fresh temp dir, return the directory the task files go in.

        A harness that needs config files of its own writes them into
        `container` and returns a subdirectory, so its own plumbing never shows
        up inside the workspace the model sees or the one that gets scored.
        """
        return container

    #: files the harness writes into the workspace that are not part of the task
    excluded_files: tuple[str, ...] = ()

    def run(self, workdir, prompt, timeout=900, thinking=False):
        raise NotImplementedError


def run_task(harness, task, sample, timeout=900, thinking=False, keep_dir=False):
    """Materialise a task, hand it to the harness, score the directory it leaves."""
    container = tempfile.mkdtemp(prefix=f"benchkit-{harness.name}-")
    workdir = harness.prepare(container)
    try:
        for path, body in task["files"].items():
            full = os.path.join(workdir, path)
            os.makedirs(os.path.dirname(full) or workdir, exist_ok=True)
            with open(full, "w") as f:
                f.write(body)

        t0 = time.perf_counter()
        hr = harness.run(workdir, task["prompt"], timeout=timeout, thinking=thinking)
        elapsed = time.perf_counter() - t0

        ws = Workspace(task["files"])
        ws.files = _read_back(workdir, exclude=harness.excluded_files)
        try:
            solved, detail = task["check"](ws)
        except Exception as e:  # noqa: BLE001 — a broken predicate is a test bug, report it
            solved, detail = False, f"check raised {e!r}"

        # A run that never started cannot have solved anything. Without this, a
        # harness that dies on launch "passes" every task whose predicate is
        # satisfied by the initial state — verify_no_change_needed most obviously,
        # which is scored on the source being untouched.
        if hr.stop_reason in ("error", "timeout") or (hr.tool_calls == 0 and hr.turns == 0):
            if solved:
                detail = f"harness produced no work ({hr.stop_reason}); not counted as solved"
            solved = False

        from ..agentic.loop import par_calls
        par = par_calls(task)
        efficiency = (min(1.0, par / hr.tool_calls)
                      if (solved and par and hr.tool_calls) else (1.0 if solved else None))
        return dict(
            task=task["id"], difficulty=task["difficulty"], sample=sample,
            passed=bool(solved), error=hr.error or ("" if solved else str(detail)[:200]),
            harness=harness.name,
            turns=hr.turns, tool_calls=hr.tool_calls, failed_calls=hr.failed_calls,
            malformed_args=0, unknown_tools=0,
            valid_call_rate=((hr.tool_calls - hr.failed_calls) / hr.tool_calls)
            if hr.tool_calls else None,
            par_calls=par, efficiency=efficiency,
            stop_reason=hr.stop_reason,
            completion_tokens=hr.output_tokens, input_tokens=hr.input_tokens,
            reasoning_tokens=hr.reasoning_tokens,
            elapsed=elapsed,
            tok_s=(hr.output_tokens / elapsed) if hr.output_tokens and elapsed else None,
            ttft=None, trace=hr.trace,
            workdir=workdir if keep_dir else None,
        )
    finally:
        if not keep_dir:
            shutil.rmtree(container, ignore_errors=True)


def _read_back(workdir, max_bytes=1_000_000, exclude=()):
    """Read the directory the harness left into a workspace-shaped dict."""
    out = {}
    exclude = set(exclude)
    for root, dirs, names in os.walk(workdir):
        dirs[:] = [d for d in dirs if d not in
                   (".git", "__pycache__", ".pi", ".claude", "node_modules", ".venv")]
        for n in names:
            full = os.path.join(root, n)
            rel = os.path.relpath(full, workdir)
            if rel in exclude:
                continue
            try:
                if os.path.getsize(full) > max_bytes:
                    continue
                with open(full) as f:
                    out[rel] = f.read()
            except (OSError, UnicodeDecodeError):
                continue          # binary or unreadable: not part of the workspace
    return out
