"""Tests for benchkit/agentic/env.py — Workspace and call dispatch.

The workspace is entirely in-memory; subprocess helpers are tested via
run_python which invokes a trivial script.  No real LLM endpoint is needed.
"""
import sys
import unittest

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.dirname(
    __import__("os").path.abspath(__file__))))

from benchkit.agentic import env  # noqa: E402


# ---------------------------------------------------------------------------
# Workspace bookkeeping
# ---------------------------------------------------------------------------

class TestWorkspaceInit(unittest.TestCase):
    def test_files_stored(self):
        ws = env.Workspace({"a.txt": "hello"})
        self.assertEqual(ws.files["a.txt"], "hello")

    def test_initial_copy(self):
        ws = env.Workspace({"a.txt": "hello"})
        self.assertEqual(ws.initial["a.txt"], "hello")
        ws.files["a.txt"] = "world"
        self.assertEqual(ws.initial["a.txt"], "hello")

    def test_empty_files(self):
        ws = env.Workspace({})
        self.assertEqual(ws.files, {})

    def test_run_timeout_stored(self):
        ws = env.Workspace({}, run_timeout=60)
        self.assertEqual(ws.run_timeout, 60)


class TestWorkspaceRecord(unittest.TestCase):
    def test_record_appends(self):
        ws = env.Workspace({})
        ws.record("read_file", {"path": "x"}, True, "content")
        self.assertEqual(len(ws.calls), 1)
        self.assertEqual(ws.calls[0]["tool"], "read_file")
        self.assertTrue(ws.calls[0]["ok"])

    def test_failed_call_counted(self):
        ws = env.Workspace({})
        ws.record("bad", {}, False, "error")
        ws.record("good", {}, True, "ok")
        self.assertEqual(ws.failed_calls, 1)

    def test_result_truncated(self):
        ws = env.Workspace({})
        ws.record("r", {}, True, "x" * 600)
        self.assertEqual(len(ws.calls[0]["result"]), 500)

    def test_snapshot_returns_copy(self):
        ws = env.Workspace({"a.txt": "hello"})
        snap = ws.snapshot()
        snap["a.txt"] = "changed"
        self.assertEqual(ws.files["a.txt"], "hello")


class TestWorkspaceChangedLines(unittest.TestCase):
    def test_no_change(self):
        ws = env.Workspace({"a.txt": "line1\nline2\n"})
        self.assertEqual(ws.changed_lines("a.txt"), 0)

    def test_modified_line(self):
        ws = env.Workspace({"a.txt": "line1\nline2\n"})
        ws.files["a.txt"] = "line1\nchanged\n"
        self.assertEqual(ws.changed_lines("a.txt"), 2)  # remove + add

    def test_new_file(self):
        ws = env.Workspace({})
        ws.files["b.txt"] = "new\n"
        # Initial is empty, new file has 1 line → 1 added line = 1 change
        self.assertEqual(ws.changed_lines("b.txt"), 1)


# ---------------------------------------------------------------------------
# Workspace tools: list_files, read_file, write_file, edit_file, search
# ---------------------------------------------------------------------------

class TestListFiles(unittest.TestCase):
    def setUp(self):
        self.ws = env.Workspace({
            "src/main.py": "print(1)",
            "src/util.py": "def f(): pass",
            "README.md": "# Project",
        })

    def test_list_all_files(self):
        out = self.ws.list_files()
        self.assertIn("README.md", out)
        self.assertIn("src/main.py", out)
        self.assertIn("src/util.py", out)

    def test_list_subdirectory(self):
        out = self.ws.list_files("src")
        self.assertIn("src/main.py", out)
        self.assertNotIn("README.md", out)

    def test_empty_directory_raises(self):
        ws = env.Workspace({})
        with self.assertRaises(env.ToolError):
            ws.list_files("nonexistent")


class TestReadFile(unittest.TestCase):
    def setUp(self):
        self.ws = env.Workspace({"a.txt": "hello\nworld\n"})

    def test_read_existing_file(self):
        out = self.ws.read_file("a.txt")
        self.assertIn("1| hello", out)
        self.assertIn("2| world", out)

    def test_missing_file_raises(self):
        with self.assertRaises(env.ToolError) as cm:
            self.ws.read_file("nope.txt")
        self.assertIn("no such file", str(cm.exception))

    def test_output_truncated(self):
        ws = env.Workspace({"big.txt": "x\n" * 2000})
        out = ws.read_file("big.txt")
        self.assertLessEqual(len(out), env.MAX_OUTPUT)

    def test_rejects_absolute_path(self):
        with self.assertRaises(env.ToolError):
            self.ws.read_file("/a.txt")


class TestWriteFile(unittest.TestCase):
    def setUp(self):
        self.ws = env.Workspace({})

    def test_create_new_file(self):
        out = self.ws.write_file("new.txt", "content")
        self.assertIn("created", out)
        self.assertEqual(self.ws.files["new.txt"], "content")

    def test_overwrite_existing_file(self):
        self.ws.files["old.txt"] = "old"
        out = self.ws.write_file("old.txt", "new")
        self.assertIn("overwrote", out)
        self.assertEqual(self.ws.files["old.txt"], "new")

    def test_empty_path_raises(self):
        with self.assertRaises(env.ToolError):
            self.ws.write_file("", "x")

    def test_rejects_absolute_path(self):
        with self.assertRaises(env.ToolError):
            self.ws.write_file("/new.txt", "c")


class TestEditFile(unittest.TestCase):
    def setUp(self):
        self.ws = env.Workspace({"a.txt": "line1\nline2\nline3\n"})

    def test_edit_replaces_text(self):
        self.ws.edit_file("a.txt", "line2", "replaced")
        self.assertEqual(self.ws.files["a.txt"], "line1\nreplaced\nline3\n")

    def test_edit_missing_file_raises(self):
        with self.assertRaises(env.ToolError):
            self.ws.edit_file("nope.txt", "x", "y")

    def test_edit_not_found_raises(self):
        with self.assertRaises(env.ToolError):
            self.ws.edit_file("a.txt", "nonexistent", "y")

    def test_edit_not_unique_raises(self):
        ws = env.Workspace({"dup.txt": "x\nx\n"})
        with self.assertRaises(env.ToolError):
            ws.edit_file("dup.txt", "x", "y")

    def test_rejects_absolute_path(self):
        with self.assertRaises(env.ToolError):
            self.ws.edit_file("/a.txt", "line2", "replaced")


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.ws = env.Workspace({
            "a.py": "def hello(): pass",
            "b.py": "def world(): pass",
        })

    def test_search_finds_matches(self):
        out = self.ws.search("hello")
        self.assertIn("a.py", out)
        self.assertIn("hello", out)

    def test_search_no_match(self):
        out = self.ws.search("nonexistent")
        self.assertEqual(out, "no matches")

    def test_search_bad_regex_raises(self):
        with self.assertRaises(env.ToolError):
            self.ws.search("[invalid")

    def test_search_limits_output(self):
        ws = env.Workspace({f"f{i}.py": "hello" for i in range(200)})
        out = ws.search("hello")
        self.assertLessEqual(len(out), env.MAX_OUTPUT)


# ---------------------------------------------------------------------------
# Workspace: run_python and finish
# ---------------------------------------------------------------------------

class TestFinish(unittest.TestCase):
    def test_finish_sets_summary(self):
        ws = env.Workspace({})
        out = ws.finish("all done")
        self.assertEqual(out, "done")
        self.assertEqual(ws.finished, "all done")


class TestRunPython(unittest.TestCase):
    def test_run_success(self):
        ws = env.Workspace({"script.py": "print('ok')\n"})
        out = ws.run_python("script.py")
        self.assertIn("exit code: 0", out)
        self.assertIn("ok", out)

    def test_run_failure(self):
        ws = env.Workspace({"script.py": "raise SystemExit(1)\n"})
        out = ws.run_python("script.py")
        self.assertIn("exit code: 1", out)

    def test_run_missing_file_raises(self):
        ws = env.Workspace({})
        with self.assertRaises(env.ToolError):
            ws.run_python("nope.py")

    def test_run_python_syncs_output_files(self):
        """A script that writes a file should sync it back."""
        ws = env.Workspace({
            "gen.py": "open('out.txt','w').write('generated')\n",
        })
        out = ws.run_python("gen.py")
        self.assertIn("exit code: 0", out)
        self.assertIn("files written by the program", out)
        self.assertEqual(ws.files.get("out.txt"), "generated")


# ---------------------------------------------------------------------------
# Workspace: check
# ---------------------------------------------------------------------------

class TestCheck(unittest.TestCase):
    def test_check_returns_exit_code_and_output(self):
        ws = env.Workspace({"test.py": "print('result')\n"})
        rc, out = ws.check("test.py")
        self.assertEqual(rc, 0)
        self.assertIn("result", out)

    def test_check_with_extra_files(self):
        ws = env.Workspace({"runner.py": "import sys; print(sys.argv[-1])\n"})
        rc, out = ws.check("runner.py", extra_files={"arg.txt": "extra"})
        self.assertEqual(rc, 0)

    def test_check_missing_file(self):
        ws = env.Workspace({})
        rc, out = ws.check("nope.py")
        self.assertNotEqual(rc, 0)


# ---------------------------------------------------------------------------
# call() dispatch
# ---------------------------------------------------------------------------

class TestSandboxEscape(unittest.TestCase):
    """Regression tests for issue #14: sandbox escape via path traversal."""

    def test_write_file_rejects_dotdot(self):
        ws = env.Workspace({})
        with self.assertRaises(env.ToolError):
            ws.write_file("../escape.txt", "pwned")

    def test_write_file_rejects_absolute_path(self):
        ws = env.Workspace({})
        with self.assertRaises(env.ToolError):
            ws.write_file("/etc/passwd", "root:x:0:0")

    def test_edit_file_rejects_dotdot(self):
        ws = env.Workspace({"a.txt": "hello"})
        with self.assertRaises(env.ToolError):
            ws.edit_file("../a.txt", "hello", "world")

    def test_read_file_rejects_dotdot(self):
        ws = env.Workspace({"a.txt": "hello"})
        with self.assertRaises(env.ToolError):
            ws.read_file("../a.txt")

    def test_run_python_rejects_dotdot(self):
        ws = env.Workspace({})
        with self.assertRaises(env.ToolError):
            ws.run_python("../escape.py")

    def test_nested_dotdot_rejected(self):
        ws = env.Workspace({})
        with self.assertRaises(env.ToolError):
            ws.write_file("a/b/../../escape.txt", "pwned")

    def test_normal_relative_path_works(self):
        ws = env.Workspace({})
        out = ws.write_file("sub/dir/file.txt", "content")
        self.assertIn("created", out)
        self.assertEqual(ws.files["sub/dir/file.txt"], "content")


class TestCallDispatch(unittest.TestCase):
    def test_list_files_dispatch(self):
        ws = env.Workspace({"a.txt": "x"})
        ok, out = env.call(ws, "list_files", {"path": "."})
        self.assertTrue(ok)
        self.assertIn("a.txt", out)

    def test_read_file_dispatch(self):
        ws = env.Workspace({"a.txt": "hello"})
        ok, out = env.call(ws, "read_file", {"path": "a.txt"})
        self.assertTrue(ok)
        self.assertIn("hello", out)

    def test_write_file_dispatch(self):
        ws = env.Workspace({})
        ok, out = env.call(ws, "write_file", {"path": "n.txt", "content": "c"})
        self.assertTrue(ok)
        self.assertIn("created", out)

    def test_edit_file_dispatch(self):
        ws = env.Workspace({"a.txt": "old"})
        ok, out = env.call(ws, "edit_file", {"path": "a.txt", "old_text": "old", "new_text": "new"})
        self.assertTrue(ok)
        self.assertEqual(ws.files["a.txt"], "new")

    def test_search_dispatch(self):
        ws = env.Workspace({"a.txt": "hello"})
        ok, out = env.call(ws, "search", {"pattern": "hello"})
        self.assertTrue(ok)
        self.assertIn("hello", out)

    def test_finish_dispatch(self):
        ws = env.Workspace({})
        ok, out = env.call(ws, "finish", {"summary": "done"})
        self.assertTrue(ok)
        self.assertEqual(ws.finished, "done")

    def test_run_python_dispatch(self):
        ws = env.Workspace({"s.py": "print(1)\n"})
        ok, out = env.call(ws, "run_python", {"path": "s.py"})
        self.assertTrue(ok)
        self.assertIn("exit code: 0", out)

    def test_unknown_tool(self):
        ws = env.Workspace({})
        ok, out = env.call(ws, "nope", {})
        self.assertFalse(ok)
        self.assertIn("no such tool", out)

    def test_missing_argument(self):
        ws = env.Workspace({"a.txt": "x"})
        ok, out = env.call(ws, "read_file", {})
        self.assertFalse(ok)
        self.assertIn("missing required argument", out)

    def test_tool_error_becomes_failed_call(self):
        ws = env.Workspace({})
        ok, out = env.call(ws, "write_file", {"path": "", "content": "x"})
        self.assertFalse(ok)
        self.assertIn("error:", out)
        self.assertEqual(ws.failed_calls, 1)


# ---------------------------------------------------------------------------
# _materialise_and_run (directly)
# ---------------------------------------------------------------------------

class TestMaterialiseAndRun(unittest.TestCase):
    def test_runs_command_in_temp_dir(self):
        ws = env.Workspace({})
        out = ws._materialise_and_run([sys.executable, "-c", "print('hi')"])
        self.assertIn("hi", out)

    def test_timeout_returns_message(self):
        ws = env.Workspace({}, run_timeout=0)
        out = ws._materialise_and_run([sys.executable, "-c", "import time; time.sleep(10)"])
        self.assertIn("TIMEOUT", out)


if __name__ == "__main__":
    unittest.main()
