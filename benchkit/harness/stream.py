"""Bounded-memory subprocess capture for the harness adapters.

The adapters used to run each task with `subprocess.run(capture_output=True)`
on a verbose JSONL stream — the whole multi-megabyte log sat in memory per
concurrent task (recorded runs reach 178,606 input tokens per task,
`results/2026-08-20-pi-harness/hard-opencode.json`) while only
`stdout[-20000:]` was ever kept (`events.py`). This module streams instead:
the pipes are drained line-by-line, every complete line is folded into the
result immediately, and both streams are retained only as bounded rolling
tails. Peak memory per task is O(tail + result), not O(log).

Timeout parity with `subprocess.run`: a watchdog timer kills the child at
*timeout* seconds and the partial fold is discarded exactly as TimeoutExpired
did — a timed-out task must not look like a partially productive one.
"""
import collections
import os
import signal
import subprocess
import threading

from .events import finish, fold_line, new_result

#: chars of stdout kept for raw_log — matches the old ``stdout[-20000:]`` slice
RAW_TAIL_CHARS = 20_000

#: chars of stderr kept; only its last non-blank line is ever reported
STDERR_TAIL_CHARS = 4_000


class StreamTimeout(Exception):
    """The child outlived *timeout* and was killed."""


class _CharTail:
    """Keep only the last *limit* characters of everything appended.

    Appends are amortised O(1): chunks accumulate until the running length
    passes *limit*, then compact once into a single slice. ``value()`` equals
    the last *limit* characters of the concatenated input, which reproduces
    the old ``stdout[-20000:]`` slice byte-for-byte.
    """

    __slots__ = ("_chunks", "_len", "_limit")

    def __init__(self, limit):
        self._chunks = collections.deque()
        self._len = 0
        self._limit = limit

    def add(self, text):
        if not text:
            return
        self._chunks.append(text)
        self._len += len(text)
        if self._len > self._limit:
            joined = "".join(self._chunks)[-self._limit:]
            self._chunks.clear()
            self._chunks.append(joined)
            self._len = len(joined)

    def value(self):
        return "".join(self._chunks)[-self._limit:]


def stream_events(argv, *, cwd, env, handler, finalize=None, timeout=900,
                  label="harness"):
    """Run *argv*, folding its JSONL stdout line-by-line as it arrives.

    Returns ``(HarnessResult, returncode, stderr_tail)``. Raises StreamTimeout
    when the child outlives *timeout* — after killing it and discarding the
    partial fold, exactly as the previous TimeoutExpired path did.

    stderr is drained on a helper thread so neither pipe can fill up and
    deadlock the child; it is kept only as a bounded tail, since an adapter
    reports just its last line when a task fails.
    """
    res = new_result()
    state = {}
    out_tail = _CharTail(RAW_TAIL_CHARS)
    p = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                         # own process group: the timeout watchdog kills the
                         # whole tree — see _kill
                         start_new_session=True,
                         # replace, not strict: one bad byte must not turn a
                         # finished run into an error after everything parsed
                         text=True, errors="replace")

    def _kill():
        # Only a still-running child means a real timeout; a child that just
        # exited must not be reported as one by a timer firing a moment late.
        try:
            if p.poll() is not None:
                return
            # Kill the whole process group, not just the direct child: real
            # harnesses spawn grandchildren (every shell tool call), and a
            # survivor holding the stdout pipe would stall this reader until
            # it exited of its own accord.
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
            fired.set()
        except (ProcessLookupError, PermissionError):
            fired.set()

    fired = threading.Event()
    watchdog = threading.Timer(timeout, _kill)
    watchdog.daemon = True
    watchdog.start()

    err_tail = _CharTail(STDERR_TAIL_CHARS)

    def _drain_stderr():
        try:
            for line in p.stderr:
                err_tail.add(line)
        finally:
            p.stderr.close()

    err_thread = threading.Thread(target=_drain_stderr, daemon=True)
    err_thread.start()
    try:
        for line in p.stdout:
            out_tail.add(line)
            fold_line(line, res, state, handler)
        p.wait()
    except BaseException:
        # An exception unwinding through here (a handler bug, KeyboardInterrupt)
        # must not leave the child running or the stderr reader stuck on a pipe
        # nobody will close.
        try:
            os.killpg(os.getpgid(p.pid), signal.SIGKILL)
        except OSError:
            pass
        raise
    finally:
        watchdog.cancel()
        err_thread.join(timeout=30)
    if fired.is_set():
        raise StreamTimeout(f"{label} exceeded {timeout}s")
    finish(res, state, finalize)
    res.raw_log = out_tail.value()
    return res, p.returncode, err_tail.value()
