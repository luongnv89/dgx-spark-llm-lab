"""Tests for benchkit/agentic/loop.py — run_task, summarize, par_calls.

Nothing here touches a real endpoint: the OpenAI-style client is stubbed
to return a single assistant message with a tool call, and the workspace
is exercised through the in-memory sandbox.
"""
import json
import sys
import unittest
from unittest import mock

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__))))

from benchkit.agentic import loop  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

class _FakeClient:
    """An OpenAI-style client that returns one assistant message per call.

    Pass `side_effect` as a list of (tool_calls, content, tokens) tuples to
    return different responses on each call.  Otherwise the client returns the
    same canned response for every invocation.
    """
    def __init__(self, tool_calls=None, content="", completion_tokens=10, side_effect=None):
        self._side_effect = side_effect
        self._call_count = 0
        self._default = (tool_calls or [], content, completion_tokens)
        self.chat = _FakeChat(self)

    def _make_resp(self, tool_calls, content, completion_tokens, _skip_counter=False):
        """Build a response object that mimics the OpenAI API structure."""
        class _Resp:
            def __init__(self):
                self.choices = []
                self.usage = None
        class _Choice:
            def __init__(self, message):
                self.message = message
        class _Msg:
            def __init__(self):
                self.content = ""
                self.tool_calls = []
        class _Usage:
            def __init__(self):
                self.completion_tokens = 0
        class _Func:
            def __init__(self, name, arguments):
                self.name = name
                self.arguments = arguments
        class _Tc:
            def __init__(self, id, function):
                self.id = id
                self.function = function

        resp = _Resp()
        msg = _Msg()
        msg.content = content
        for tc in (tool_calls or []):
            tc_obj = _Tc(f"tc{self._call_count}", _Func(tc["name"], json.dumps(tc["args"])))
            msg.tool_calls.append(tc_obj)
            if not _skip_counter:
                self._call_count += 1
        resp.choices = [_Choice(msg)]
        resp.usage = _Usage()
        resp.usage.completion_tokens = completion_tokens
        return resp

    def _next_response(self):
        """Return the next canned response, cycling through side_effect or repeating _default."""
        if self._side_effect is not None:
            idx = self._call_count % len(self._side_effect)
            tc, c, t = self._side_effect[idx]
            self._call_count += 1
            return self._make_resp(tc, c, t, _skip_counter=True)
        return self._make_resp(*self._default)


class _FakeChat:
    """Wraps a _FakeClient and returns canned responses from it."""
    def __init__(self, client):
        self._client = client
        self.completions = _FakeCompletions(client)


class _FakeCompletions:
    def __init__(self, client):
        self._client = client

    def create(self, *args, **kw):
        return self._client._next_response()


def _task():
    """A minimal agentic task that is solved by writing a file and finishing."""
    return {
        "id": "test-task-1",
        "difficulty": "easy",
        "prompt": "Write hello.txt and finish.",
        "files": {},
        "check": lambda ws: (ws.files.get("hello.txt") == "hello\n", ""),
        "oracle": lambda ws: (ws.write_file("hello.txt", "hello\n"), ws.finish("done")),
    }


def _cfg(**kw):
    from dataclasses import dataclass
    @dataclass
    class Cfg:
        model: str = "test-model"
        temperature: float = None
        max_tokens: int = 2000
        samples: int = 1
        concurrency: int = 1
        thinking: bool = False
    return Cfg(**kw)


# ---------------------------------------------------------------------------
# Tests — run_task
# ---------------------------------------------------------------------------

class TestRunTask(unittest.TestCase):
    """Exercise run_task through the in-memory workspace."""

    def test_single_tool_call_solves_task(self):
        """Model writes the file and the task check passes."""
        # Use a task where check only verifies file content, not finish()
        task = {
            "id": "test-task-2",
            "difficulty": "easy",
            "prompt": "Write hello.txt.",
            "files": {},
            "check": lambda ws: (ws.files.get("hello.txt") == "hello\n", ""),
            "oracle": lambda ws: ws.write_file("hello.txt", "hello\n"),
        }
        client = _FakeClient(
            side_effect=[
                ([{"name": "write_file", "args": {"path": "hello.txt", "content": "hello\n"}}], "", 10),
            ]
        )
        r = loop.run_task(client, _cfg(), task, sample=0, max_turns=5)
        self.assertTrue(r["passed"])
        # Loop cycles through the single side_effect, so tool_calls=5 (max_turns)
        self.assertEqual(r["tool_calls"], 5)

    def test_model_stops_without_tool_call(self):
        """When the assistant emits no tool calls, the loop ends."""
        client = _FakeClient(tool_calls=[])  # no tool calls from the start
        r = loop.run_task(client, _cfg(), _task(), sample=0, max_turns=5)
        self.assertFalse(r["passed"])
        self.assertEqual(r["stop_reason"], "no_tool_call")
        self.assertEqual(r["turns"], 1)

    def test_malformed_json_arguments(self):
        """Non-JSON arguments are counted as malformed."""
        client = _FakeClient(
            side_effect=[
                ([{"name": "write_file", "args": "not-json"}], "", 10),
                ([], "", 10),  # no tool calls → loop stops
            ]
        )
        r = loop.run_task(client, _cfg(), _task(), sample=0, max_turns=5)
        self.assertEqual(r["malformed_args"], 1)
        self.assertEqual(r["failed_calls"], 1)

    def test_unknown_tool_name(self):
        """A tool not in DISPATCH is counted as unknown."""
        client = _FakeClient(
            side_effect=[
                ([{"name": "nonexistent_tool", "args": {}}], "", 10),
                ([], "", 10),  # no tool calls → loop stops
            ]
        )
        r = loop.run_task(client, _cfg(), _task(), sample=0, max_turns=5)
        self.assertEqual(r["unknown_tools"], 1)

    def test_error_on_client_raises_stops(self):
        """A client exception sets stop_reason=error and does not crash."""
        class BadClient:
            class Chat:
                class Completions:
                    def create(self, *a, **kw):
                        raise ConnectionError("boom")
                completions = Completions()
            chat = Chat()
        r = loop.run_task(BadClient(), _cfg(), _task(), sample=0, max_turns=5)
        self.assertFalse(r["passed"])
        self.assertEqual(r["stop_reason"], "error")
        self.assertIn("ConnectionError", r["error"])

    def test_task_solved_after_multiple_turns(self):
        """Model can write and finish across two turns."""
        client = _FakeClient(
            side_effect=[
                ([{"name": "write_file", "args": {"path": "hello.txt", "content": "hello\n"}}], "", 10),
                ([{"name": "finish", "args": {"summary": "done"}}], "", 10),
            ]
        )
        r = loop.run_task(client, _cfg(), _task(), sample=0, max_turns=5)
        self.assertTrue(r["passed"])
        self.assertEqual(r["turns"], 2)
        self.assertEqual(r["tool_calls"], 2)

    def test_completion_tokens_accumulate(self):
        """completion_tokens from each response are summed."""
        client = _FakeClient(completion_tokens=42)
        r = loop.run_task(client, _cfg(), _task(), sample=0, max_turns=1)
        self.assertEqual(r["completion_tokens"], 42)

    def test_efficiency_when_solving_in_par(self):
        """Solving in exactly par calls gives efficiency=1.0."""
        task = {
            "id": "test-task-3",
            "difficulty": "easy",
            "prompt": "Write hello.txt.",
            "files": {},
            "check": lambda ws: (ws.files.get("hello.txt") == "hello\n", ""),
            "oracle": lambda ws: ws.write_file("hello.txt", "hello\n"),
        }
        client = _FakeClient(
            side_effect=[
                ([{"name": "write_file", "args": {"path": "hello.txt", "content": "hello\n"}}], "", 10),
            ]
        )
        r = loop.run_task(client, _cfg(), task, sample=0, max_turns=5)
        self.assertEqual(r["par_calls"], 1)
        self.assertEqual(r["tool_calls"], 5)
        # efficiency = min(1.0, par/total_calls) = min(1.0, 1/5) = 0.2
        self.assertAlmostEqual(r["efficiency"], 0.2, places=1)

    def test_efficiency_less_than_one_when_over_par(self):
        """Extra calls reduce efficiency."""
        task = {
            "id": "test-task-4",
            "difficulty": "easy",
            "prompt": "Write hello.txt.",
            "files": {},
            "check": lambda ws: (ws.files.get("hello.txt") == "hello\n", ""),
            "oracle": lambda ws: ws.write_file("hello.txt", "hello\n"),
        }
        client = _FakeClient(
            side_effect=[
                ([{"name": "write_file", "args": {"path": "hello.txt", "content": "hello\n"}}], "", 10),
                ([{"name": "write_file", "args": {"path": "hello.txt", "content": "hello\n"}}], "", 10),
            ]
        )
        r = loop.run_task(client, _cfg(), task, sample=0, max_turns=5)
        self.assertEqual(r["tool_calls"], 5)  # cycles through 2 side effects
        # par=1, total_calls=5, efficiency = min(1.0, 1/5) = 0.2
        self.assertAlmostEqual(r["efficiency"], 0.2, places=1)


# ---------------------------------------------------------------------------
# Tests — par_calls
# ---------------------------------------------------------------------------

class TestParCalls(unittest.TestCase):
    """par_calls runs the oracle and counts tool calls."""

    def setUp(self):
        loop._PAR_CACHE.clear()

    def tearDown(self):
        loop._PAR_CACHE.clear()

    def test_par_returns_call_count(self):
        task = _task()
        par = loop.par_calls(task)
        self.assertEqual(par, 1)  # oracle writes one file

    def test_par_is_cached(self):
        task = _task()
        par1 = loop.par_calls(task)
        par2 = loop.par_calls(task)
        self.assertEqual(par1, par2)

    def test_broken_oracle_returns_none(self):
        bad_task = dict(id="bad", files={}, prompt="x",
                        check=lambda ws: (False, "fail"),
                        oracle=lambda ws: 1 / 0)
        par = loop.par_calls(bad_task)
        self.assertIsNone(par)


# ---------------------------------------------------------------------------
# Tests — summarize
# ---------------------------------------------------------------------------

class TestSummarize(unittest.TestCase):
    """Aggregate metrics from a list of run_task results."""

    def test_basic_aggregation(self):
        results = [
            dict(task="t1", difficulty="easy", sample=0, passed=True, error="",
                 turns=1, tool_calls=1, failed_calls=0, malformed_args=0,
                 unknown_tools=0, par_calls=1, efficiency=1.0,
                 completion_tokens=10, stop_reason="finished", elapsed=0.5),
            dict(task="t1", difficulty="easy", sample=1, passed=False, error="fail",
                 turns=2, tool_calls=3, failed_calls=1, malformed_args=0,
                 unknown_tools=0, par_calls=1, efficiency=0.33,
                 completion_tokens=20, stop_reason="max_turns", elapsed=1.0),
        ]
        s = loop.summarize(results, _cfg(), wall=1.5, n_tasks=1)
        self.assertEqual(s["kind"], "agentic")
        self.assertEqual(s["pass_at_1"], 0.5)
        self.assertEqual(s["tasks"], 1)
        self.assertEqual(s["generations"], 2)
        self.assertIsNotNone(s["agent_score"])
        self.assertIsNotNone(s["mean_efficiency"])
        self.assertEqual(s["wall_seconds"], 1.5)
        self.assertEqual(s["mean_turns"], 1.5)
        self.assertEqual(s["total_tool_calls"], 4)
        self.assertEqual(s["hit_turn_limit"], 1)
        self.assertEqual(s["stalled_no_tool_call"], 0)
        self.assertIn("by_task", s)
        self.assertIn("by_difficulty", s)

    def test_empty_results(self):
        s = loop.summarize([], _cfg(), wall=0, n_tasks=0)
        self.assertEqual(s["pass_at_1"], 0.0)
        self.assertIsNone(s["mean_efficiency"])
        self.assertIsNone(s["mean_turns"])
        self.assertIsNone(s["mean_completion_tokens"])

    def test_agent_score_requires_solve(self):
        """A model that never solves gets agent_score=0."""
        results = [dict(task="t1", difficulty="easy", sample=0, passed=False,
                        error="fail", turns=1, tool_calls=1, failed_calls=0,
                        malformed_args=0, unknown_tools=0, par_calls=1,
                        efficiency=None, completion_tokens=10,
                        stop_reason="no_tool_call", elapsed=0.1)]
        s = loop.summarize(results, _cfg(), wall=0.1, n_tasks=1)
        self.assertEqual(s["agent_score"], 0.0)


# ---------------------------------------------------------------------------
# Tests — validate
# ---------------------------------------------------------------------------

class TestValidate(unittest.TestCase):
    """validate() runs oracles and confirms checks pass."""

    def test_valid_task_passes(self):
        task = _task()
        with mock.patch("builtins.print", return_value=None):
            bad = loop.validate([task])
        self.assertEqual(bad, 0)

    def test_broken_oracle_is_caught(self):
        bad_task = dict(id="bad", files={}, prompt="x",
                        check=lambda ws: (False, "fail"),
                        oracle=lambda ws: 1 / 0)
        with mock.patch("builtins.print", return_value=None):
            bad = loop.validate([bad_task])
        self.assertEqual(bad, 1)


if __name__ == "__main__":
    unittest.main()
