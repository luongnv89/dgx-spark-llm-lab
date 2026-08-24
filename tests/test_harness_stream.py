"""Tests for the streaming Popen log capture in the harness adapters.

The adapters used to buffer each task's whole multi-megabyte JSONL stream via
subprocess.run(capture_output=True) and keep only stdout[-20000:]. They now
stream and fold line-by-line through benchkit.harness.stream.stream_events,
retaining bounded rolling tails.

The load-bearing property under test: given the SAME stream, the new
line-streaming path must produce a HarnessResult identical to the old
whole-string parser — same turns, tool_calls, token totals, stop_reason,
error — plus a raw_log equal to the old `stdout[-20000:]` slice. That is the
offline stand-in for "reproduce the counts in results/2026-08-20-pi-harness":
those recorded fixtures carry aggregate counts only (no raw logs), so the
counts are re-derived here from streams shaped exactly like each harness's
documented event schema, and the two code paths must agree on them.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchkit.harness import HarnessConfig
from benchkit.harness.claudecode import _claudecode_finalize, _claudecode_handler
from benchkit.harness.claudecode import parse_events as parse_claude
from benchkit.harness.opencode import OpenCodeHarness, _opencode_handler
from benchkit.harness.opencode import parse_events as parse_opencode
from benchkit.harness.pi import PiHarness, _pi_handler
from benchkit.harness.pi import parse_events as parse_pi
from benchkit.harness.stream import (
    RAW_TAIL_CHARS,
    StreamTimeout,
    stream_events,
)

PY = sys.executable


def _emit(code):
    """argv for a child that runs *code* with stdout/stderr piped."""
    return [PY, "-c", code]


def _emit_text(text):
    """argv for a child whose stdout is exactly *text*.

    Delivered via a temp file: inline `-c` payloads hit E2BIG once the
    simulated log grows past ~100 KB.
    """
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False)
    f.write(text)
    f.close()
    return [PY, "-c",
            f"import sys; sys.stdout.write(open({f.name!r}).read())"]


# --- representative streams -------------------------------------------------

PI_STREAM = "".join([
    '{"type":"session_start","session":"abc"}\n',
    'not json at all\n',
    '{"type":"turn_start"}\n',
    '{"type":"tool_execution_start","toolName":"read","id":1}\n',
    '{"type":"tool_execution_end","isError":false,"id":1}\n',
    '{"type":"message_end","message":{"role":"assistant",'
    '"usage":{"input":1000,"output":50,"reasoning":7},'
    '"stopReason":"turn_end"}}\n',
    '\n',
    '{"type":"turn_start"}\n',
    '{"type":"tool_execution_start","toolName":"edit","id":2}\n',
    '{"type":"tool_execution_end","result":{"isError":true},"id":2}\n',
    '{"type":"message_end","message":{"role":"assistant",'
    '"usage":{"input":2000,"output":80,"reasoning":9},'
    '"stopReason":"stop"}}\n',
    '{"type":"agent_end","reason":"done"}\n',
])

OPENCODE_STREAM = "".join([
    '{"type":"step_start","part":{}}\n',
    '{"type":"tool_use","part":{"tool":"bash",'
    '"state":{"status":"completed"}}}\n',
    '{"type":"tool_use","part":{"tool":"edit",'
    '"state":{"status":"error"}}}\n',
    'garbage {"not":"an event prefix"}\n',
    '{"type":"step_finish","part":{"tokens":{"input":500,"output":25,'
    '"reasoning":3},"reason":"stop"}}\n',
    '{"type":"step_start","part":{}}\n',
    '{"type":"step_finish","part":{"tokens":{"input":1500,"output":60,'
    '"reasoning":4},"reason":"stop"}}\n',
])

CLAUDE_STREAM = "".join([
    '{"type":"system","subtype":"init"}\n',
    '{"type":"assistant","message":{"id":"m1","content":['
    '{"type":"text","text":"thinking"},'
    '{"type":"tool_use","id":"t1","name":"Read","input":{}}]}}\n',
    # same message id emitted once per block: tool_use ids dedupe
    '{"type":"assistant","message":{"id":"m1","content":['
    '{"type":"tool_use","id":"t1","name":"Read","input":{}}]}}\n',
    '{"type":"user","message":{"content":[{"type":"tool_result",'
    '"tool_use_id":"t1","is_error":false}]}}\n',
    '{"type":"user","message":{"content":[{"type":"tool_result",'
    '"tool_use_id":"t1","is_error":true}]}}\n',
    '{"type":"assistant","message":{"id":"m2","content":['
    '{"type":"tool_use","id":"t2","name":"Edit","input":{}}]}}\n',
    '{"type":"result","subtype":"success","num_turns":4,'
    '"usage":{"input_tokens":300,"output_tokens":40,'
    '"cache_read_input_tokens":1200,"cache_creation_input_tokens":80,'
    '"output_tokens_details":{"thinking_tokens":15}}}\n',
])


class TestCountsMatchWholeStringParser(unittest.TestCase):
    """Streaming path == whole-string path, per adapter, on equal input."""

    def _assert_same(self, text, handler, finalize, parse):
        old = parse(text)
        new, rc, err = stream_events(
            _emit_text(text), cwd=tempfile.gettempdir(), env=dict(os.environ),
            handler=handler, finalize=finalize)
        self.assertEqual(rc, 0)
        self.assertEqual(err, "")
        for field in ("turns", "tool_calls", "failed_calls", "input_tokens",
                      "output_tokens", "reasoning_tokens", "stop_reason",
                      "error", "trace"):
            self.assertEqual(getattr(new, field), getattr(old, field),
                             f"{field} diverged")
        # raw_log parity with the old `stdout[-20000:]` slice
        self.assertEqual(new.raw_log, text[-RAW_TAIL_CHARS:])
        return new

    def test_pi_stream(self):
        res = self._assert_same(PI_STREAM, _pi_handler, None, parse_pi)
        self.assertEqual((res.turns, res.tool_calls, res.failed_calls), (2, 2, 1))
        self.assertEqual((res.input_tokens, res.output_tokens), (3000, 130))
        self.assertEqual(res.stop_reason, "done")  # agent_end.reason wins

    def test_opencode_stream(self):
        res = self._assert_same(OPENCODE_STREAM, _opencode_handler, None,
                                parse_opencode)
        self.assertEqual((res.turns, res.tool_calls, res.failed_calls), (2, 2, 1))
        self.assertEqual((res.input_tokens, res.output_tokens), (2000, 85))
        self.assertEqual(res.stop_reason, "stop")

    def test_claude_stream(self):
        res = self._assert_same(CLAUDE_STREAM, _claudecode_handler,
                                _claudecode_finalize, parse_claude)
        self.assertEqual((res.turns, res.tool_calls, res.failed_calls), (4, 2, 1))
        self.assertEqual((res.input_tokens, res.output_tokens), (1580, 40))
        self.assertEqual(res.reasoning_tokens, 15)
        self.assertEqual(res.stop_reason, "end_turn")

    def test_counts_match_recorded_fixture_shapes(self):
        """Aggregate counts re-derived from the shapes behind
        results/2026-08-20-pi-harness/*.json agree across both paths.

        The fixtures store summary counts only (no raw logs), so exact
        reproduction is verified structurally: identical input, identical
        counts, on both the pre-change parser and the streaming one.
        """
        for text, handler, finalize, parse in (
                (PI_STREAM, _pi_handler, None, parse_pi),
                (OPENCODE_STREAM, _opencode_handler, None, parse_opencode),
                (CLAUDE_STREAM, _claudecode_handler, _claudecode_finalize,
                 parse_claude)):
            old = parse(text)
            streamed, _, _ = stream_events(
                _emit_text(text), cwd=tempfile.gettempdir(),
                env=dict(os.environ), handler=handler, finalize=finalize)
            self.assertEqual(old.turns, streamed.turns)
            self.assertEqual(old.tool_calls, streamed.tool_calls)
            self.assertEqual(old.input_tokens, streamed.input_tokens)
            self.assertGreater(old.tool_calls, 0)


class TestBoundedTails(unittest.TestCase):
    def test_raw_log_is_bounded_and_exact(self):
        line = '{"type":"step_start","pad":"' + "x" * 300 + '"}\n'
        text = line * 5000  # ~1.5 MB, far past RAW_TAIL_CHARS
        res, rc, _ = stream_events(
            _emit_text(text), cwd=tempfile.gettempdir(), env=dict(os.environ),
            handler=_opencode_handler)
        self.assertEqual(rc, 0)
        self.assertLessEqual(len(res.raw_log), RAW_TAIL_CHARS)
        self.assertEqual(len(res.raw_log), RAW_TAIL_CHARS)
        self.assertTrue(res.raw_log.endswith("}\n"))
        self.assertEqual(res.raw_log, text[-RAW_TAIL_CHARS:])

    def test_stderr_tail_bounded(self):
        noise = ("err" + "y" * 200 + "\n") * 400  # ~80 KB of stderr
        _, rc, err = stream_events(
            _emit("import sys\n"
                  f"sys.stderr.write({noise!r})\n"
                  "sys.stderr.write('final line\\n')\n"
                  "sys.exit(3)\n"),
            cwd=tempfile.gettempdir(), env=dict(os.environ),
            handler=_opencode_handler)
        self.assertEqual(rc, 3)
        self.assertLessEqual(len(err), 8000)
        self.assertIn("final line", err)

    def test_bad_bytes_do_not_kill_the_fold(self):
        payload = b'{"type":"step_start"}\n\xff\xfe not utf8\n{"type":"step_finish","part":{"tokens":{"input":5,"output":6,"reasoning":0},"reason":"stop"}}\n'
        res, rc, _ = stream_events(
            [PY, "-c", "import sys; sys.stdout.buffer.write(%r)" % payload],
            cwd=tempfile.gettempdir(), env=dict(os.environ),
            handler=_opencode_handler)
        self.assertEqual(rc, 0)
        self.assertEqual((res.turns, res.input_tokens, res.output_tokens),
                         (1, 5, 6))


class TestFailurePaths(unittest.TestCase):
    def test_pi_wiring_streams_and_reports_last_stderr_line(self):
        """pi's run() goes through the stream path: non-zero exit surfaces the
        bounded stderr tail's last line as the error."""
        h = PiHarness(HarnessConfig(binary="/bin/sh", model="x")).run(
            tempfile.gettempdir(), "unused", timeout=30)
        self.assertEqual(h.stop_reason, "error")
        self.assertTrue(h.error)
        self.assertNotIn("\n", h.error)

    def test_nonzero_exit_reports_last_stderr_line(self):
        res = OpenCodeHarness(HarnessConfig(binary="/bin/sh", model="x")).run(
            tempfile.gettempdir(), "unused", timeout=30)
        self.assertEqual(res.stop_reason, "error")

    def _run_with_binary(self, binary, timeout=30):
        return OpenCodeHarness(
            HarnessConfig(binary=binary, model="probe")).run(
            tempfile.gettempdir(), "unused", timeout=timeout)

    def test_timeout_kills_child_tree_promptly(self):
        """Timeout kills the whole process tree, and reading does not stall.

        The child spawns a grandchild that inherits stdout and sleeps far past
        the deadline: killing only the direct shell would leave the grandchild
        holding the pipe open, stalling this reader until it exited (60 s in
        the first version of this test).
        """
        sleeper = os.path.join(tempfile.mkdtemp(), "slow-harness")
        with open(sleeper, "w") as f:
            f.write("#!/bin/sh\n"
                    "echo '{\"type\":\"step_start\",\"part\":{}}'\n"
                    "sleep 60 &\n"
                    "sleep 60\n")
        os.chmod(sleeper, 0o755)
        h = self._run_with_binary(sleeper, timeout=2)
        self.assertEqual(h.stop_reason, "timeout")
        self.assertIn("exceeded 2s", h.error)
        self.assertEqual(h.turns, 0)   # partial fold discarded, as TimeoutExpired did
        self.assertEqual(h.tool_calls, 0)

    def test_missing_binary_reports_error_not_crash(self):
        h = self._run_with_binary("/nonexistent/benchkit-missing-binary-xyz")
        self.assertEqual(h.stop_reason, "error")
        self.assertIn("No such file", h.error)

    def test_stdin_devnull_survives_streaming(self):
        """A child that reads stdin must see EOF, never block forever."""
        reader = os.path.join(tempfile.mkdtemp(), "stdin-reader")
        with open(reader, "w") as f:
            f.write("#!/bin/sh\n"
                    "cat > /dev/null\n"
                    "echo '{\"type\":\"step_finish\",\"part\":{\"tokens\":"
                    "{\"input\":1,\"output\":1,\"reasoning\":0},"
                    "\"reason\":\"stop\"}}'\n")
        os.chmod(reader, 0o755)
        h = self._run_with_binary(reader, timeout=10)
        self.assertEqual(h.stop_reason, "stop")  # step_finish.reason wins
        self.assertEqual(h.input_tokens, 1)


class TestStreamTimeoutException(unittest.TestCase):
    def test_stream_events_raises_after_timeout(self):
        with self.assertRaises(StreamTimeout):
            stream_events(_emit("import time; time.sleep(30)"),
                          cwd=tempfile.gettempdir(), env=dict(os.environ),
                          handler=_opencode_handler, timeout=1)


if __name__ == "__main__":
    unittest.main()
