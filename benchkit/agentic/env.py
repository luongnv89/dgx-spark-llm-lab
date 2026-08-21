"""A sandboxed workspace the model manipulates through tools.

Files live in memory and are materialised into a temp directory only when the
model runs something. Every tool returns a string — what the model sees — and
records whether the call succeeded, so a run can be scored on tool hygiene as
well as on whether the task got done.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

MAX_OUTPUT = 4000


def _no_tool_calls(solved: bool, tool_calls: int) -> tuple[bool, str | None]:
    """Refuse to score a run as solved when the model made zero tool calls.

    A model that replies in prose with no tool calls has not done any work.
    Returns ``(False, reason)`` when tool_calls is zero, else ``(solved, None)``.
    """
    if tool_calls == 0 and solved:
        return False, "no tool calls made; the model did not do any work"
    return solved, None


def _safe_path(path: str) -> str:
    """Validate and normalise a tool path.

    Rejects absolute paths and ``..`` segments that would escape the sandbox.
    Returns the cleaned path on success, raises ``ToolError`` otherwise.
    """
    if not path:
        raise ToolError("path must not be empty")
    # Reject absolute paths
    if path.startswith("/"):
        raise ToolError(f"absolute paths are not allowed: {path!r}")
    # Reject path traversal
    parts = path.split("/")
    for part in parts:
        if part == "..":
            raise ToolError(f"path traversal is not allowed: {path!r}")
    return path.strip("/")


class ToolError(Exception):
    """Raised by a tool for a recoverable, model-visible error."""


class Workspace:
    def __init__(self, files, run_timeout=30):
        self.files = dict(files)
        self.initial = dict(files)   # for tasks scored on *not* changing things
        self.run_timeout = run_timeout
        self.calls = []          # (name, args, ok, result)
        self.finished = None     # the summary passed to finish(), if any

    # --- bookkeeping -----------------------------------------------------
    def record(self, name, args, ok, result):
        self.calls.append(dict(tool=name, args=args, ok=ok,
                               result=result[:500] if isinstance(result, str) else result))

    @property
    def failed_calls(self):
        return sum(1 for c in self.calls if not c["ok"])

    def snapshot(self):
        return dict(self.files)

    def changed_lines(self, path):
        """How many lines differ from the initial version of a file."""
        import difflib
        a = self.initial.get(path, "").splitlines()
        b = self.files.get(path, "").splitlines()
        return sum(1 for d in difflib.ndiff(a, b) if d[0] in "+-")

    # --- tools -----------------------------------------------------------
    def list_files(self, path="."):
        prefix = "" if path in (".", "", "/") else path.strip("/") + "/"
        names = sorted(p for p in self.files if p.startswith(prefix))
        if not names:
            raise ToolError(f"no files under {path!r}")
        return "\n".join(names)

    def read_file(self, path):
        path = _safe_path(path)
        if path not in self.files:
            raise ToolError(f"no such file: {path}. Use list_files to see what exists.")
        body = self.files[path]
        lines = body.splitlines()
        return "\n".join(f"{i:>4}| {line}" for i, line in enumerate(lines, 1))[:MAX_OUTPUT]

    def write_file(self, path, content):
        path = _safe_path(path)
        new = path not in self.files
        self.files[path] = content
        return f"{'created' if new else 'overwrote'} {path} ({len(content)} bytes)"

    def edit_file(self, path, old, new):
        path = _safe_path(path)
        if path not in self.files:
            raise ToolError(f"no such file: {path}")
        body = self.files[path]
        n = body.count(old)
        if n == 0:
            raise ToolError(f"the text to replace was not found in {path}. "
                            "Read the file again and copy the exact text, including indentation.")
        if n > 1:
            raise ToolError(f"the text to replace appears {n} times in {path}; "
                            "include more surrounding context so it is unique.")
        self.files[path] = body.replace(old, new, 1)
        return f"edited {path}"

    def search(self, pattern):
        try:
            rx = re.compile(pattern)
        except re.error as e:
            raise ToolError(f"bad regular expression: {e}")
        hits = []
        for path in sorted(self.files):
            for i, line in enumerate(self.files[path].splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{path}:{i}: {line.strip()}")
        if not hits:
            return "no matches"
        return "\n".join(hits[:100])[:MAX_OUTPUT]

    def run_python(self, path):
        path = _safe_path(path)
        if path not in self.files:
            raise ToolError(f"no such file: {path}")
        return self._materialise_and_run([sys.executable, path], sync_back=True)

    def finish(self, summary):
        self.finished = summary
        return "done"

    # --- execution -------------------------------------------------------
    def _materialise_and_run(self, cmd, sync_back=False):
        d = tempfile.mkdtemp(prefix="benchkit-agentic-")
        try:
            for p, body in self.files.items():
                # Re-validate each key before joining — a bad key cannot
                # reach the filesystem by another route.
                _safe_path(p)
                full = os.path.join(d, p)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as f:
                    f.write(body)
            isolate = os.environ.get("BENCH_ISOLATE", "").lower() in ("1", "true", "yes")
            try:
                if isolate:
                    # Run inside a new network + mount namespace for isolation.
                    # Falls back to unisolated if unshare is unavailable.
                    try:
                        r = subprocess.run(
                            ["unshare", "--net", "--mount"] + cmd,
                            cwd=d, capture_output=True, text=True,
                            timeout=self.run_timeout,
                        )
                    except (FileNotFoundError, OSError):
                        r = subprocess.run(cmd, cwd=d, capture_output=True, text=True,
                                           timeout=self.run_timeout)
                else:
                    r = subprocess.run(cmd, cwd=d, capture_output=True, text=True,
                                       timeout=self.run_timeout)
            except subprocess.TimeoutExpired:
                return f"TIMEOUT after {self.run_timeout}s"
            created = self._sync_back(d) if sync_back else []
            parts = [f"exit code: {r.returncode}"]
            if r.stdout.strip():
                parts.append("stdout:\n" + r.stdout.strip()[:MAX_OUTPUT])
            if r.stderr.strip():
                parts.append("stderr:\n" + r.stderr.strip()[:MAX_OUTPUT])
            if created:
                parts.append("files written by the program: " + ", ".join(sorted(created)))
            return "\n".join(parts)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def _sync_back(self, d, max_bytes=1_000_000):
        """Pull files the program created or changed back into the workspace.

        Without this a script that writes an output file would appear to succeed
        and leave no trace, which is neither how a real workspace behaves nor
        something a model can debug.
        """
        touched = []
        for root, _dirs, names in os.walk(d):
            for n in names:
                full = os.path.join(root, n)
                rel = os.path.relpath(full, d)
                try:
                    if os.path.getsize(full) > max_bytes:
                        continue
                    with open(full) as f:
                        body = f.read()
                except (OSError, UnicodeDecodeError):
                    continue          # binary or unreadable: not part of the workspace
                if self.files.get(rel) != body:
                    self.files[rel] = body
                    touched.append(rel)
        return touched

    def check(self, path, extra_files=None):
        """Run a file for scoring. Returns (exit_code, combined_output).

        `extra_files` are written into the sandbox for this run only and are never
        visible to the model — that is how a task is scored against the full spec
        rather than against the asserts the model could read and special-case.
        """
        d = tempfile.mkdtemp(prefix="benchkit-check-")
        try:
            for p, body in dict(self.files, **(extra_files or {})).items():
                _safe_path(p)
                full = os.path.join(d, p)
                os.makedirs(os.path.dirname(full), exist_ok=True)
                with open(full, "w") as f:
                    f.write(body)
            try:
                r = subprocess.run([sys.executable, path], cwd=d, capture_output=True,
                                   text=True, timeout=self.run_timeout)
            except subprocess.TimeoutExpired:
                return 124, "TIMEOUT"
            return r.returncode, (r.stdout + r.stderr)
        finally:
            shutil.rmtree(d, ignore_errors=True)


DISPATCH = {
    "list_files": lambda ws, a: ws.list_files(a.get("path", ".")),
    "read_file": lambda ws, a: ws.read_file(a["path"]),
    "write_file": lambda ws, a: ws.write_file(a["path"], a["content"]),
    "edit_file": lambda ws, a: ws.edit_file(a["path"], a["old_text"], a["new_text"]),
    "search": lambda ws, a: ws.search(a["pattern"]),
    "run_python": lambda ws, a: ws.run_python(a["path"]),
    "finish": lambda ws, a: ws.finish(a.get("summary", "")),
}


def call(ws, name, args):
    """Execute one tool call. Returns (ok, text_for_the_model)."""
    fn = DISPATCH.get(name)
    if fn is None:
        msg = f"no such tool: {name}. Available: {', '.join(DISPATCH)}"
        ws.record(name, args, False, msg)
        return False, msg
    try:
        out = fn(ws, args)
        ws.record(name, args, True, out)
        return True, out
    except ToolError as e:
        ws.record(name, args, False, str(e))
        return False, f"error: {e}"
    except KeyError as e:
        msg = f"missing required argument {e} for {name}"
        ws.record(name, args, False, msg)
        return False, f"error: {msg}"
    except Exception as e:  # noqa: BLE001 — a broken tool must not kill the run
        ws.record(name, args, False, repr(e))
        return False, f"error: {e!r}"
