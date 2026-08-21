"""Tests for benchkit/agentic/tasks_hard.py — task predicate behaviour.

Focus: the wrong_test_not_code predicate evaluates `ws.changed_lines("tests.py")`
at most once per call (F-PERF-005) and still routes to the same verdicts.
"""
import sys
import unittest

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__))))

from benchkit.agentic.env import Workspace  # noqa: E402
from benchkit.agentic.tasks_hard import TASKS  # noqa: E402


class CountingWorkspace(Workspace):
    """A workspace that counts changed_lines evaluations."""

    def __init__(self, files):
        super().__init__(files)
        self.changed_line_queries = 0

    def changed_lines(self, path):
        self.changed_line_queries += 1
        return super().changed_lines(path)


def _wrong_test_task():
    return next(t for t in TASKS if t["id"] == "wrong_test_not_code")


class TestWrongTestNotCodeCheck(unittest.TestCase):
    """The restraint predicate computes its diff once and keeps its verdicts."""

    def setUp(self):
        self.task = _wrong_test_task()
        self.original_tests = self.task["files"]["tests.py"]
        self.original_code = self.task["files"]["business_days.py"]

    def test_untouched_workspace_queries_changed_lines_once(self):
        ws = CountingWorkspace(dict(self.task["files"]))
        solved, _detail = self.task["check"](ws)
        self.assertEqual(ws.changed_line_queries, 1)

    def test_over_edited_tests_fail_with_single_query(self):
        ws = CountingWorkspace(dict(self.task["files"]))
        ws.files["tests.py"] = self.original_tests + "\n" * 10
        solved, detail = self.task["check"](ws)
        self.assertEqual(ws.changed_line_queries, 1)
        self.assertFalse(solved)
        self.assertIn("lines of tests.py", detail)

    def test_modified_solution_short_circuits_before_diff(self):
        ws = CountingWorkspace(dict(self.task["files"]))
        ws.files["business_days.py"] = "# tampered\n"
        solved, detail = self.task["check"](ws)
        self.assertEqual(ws.changed_line_queries, 0)
        self.assertFalse(solved)
        self.assertIn("business_days.py was modified", detail)


if __name__ == "__main__":
    unittest.main()
