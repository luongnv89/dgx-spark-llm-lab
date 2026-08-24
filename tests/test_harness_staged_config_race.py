"""Tests for per-task staged config paths in the opencode/claude-code adapters.

The runner drives every task through ONE harness instance on a thread pool
(`benchkit/harness/runner.py`), so an adapter must never park a per-task path
on itself: the last task to call prepare() would win, and every other task's
subprocess would be pointed at a directory that has since been rmtree'd. For
opencode that failure was silent — opencode falls back to the user's own
config and the benchmark measures the wrong provider with no error.

The promise tested here: N parallel tasks sharing one adapter instance get N
distinct staged paths, checked against what `run()` actually hands the
subprocess — plus a missing staged config failing loudly instead of silently.
"""
import os
import shutil
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchkit.harness import HarnessConfig, get  # noqa: E402
from benchkit.harness.claudecode import CONFIG_DIR as CLAUDE_HOME  # noqa: E402
from benchkit.harness.opencode import CONFIG_NAME  # noqa: E402

ENDPOINT = "http://localhost:8001/v1"

TASKS = 8


class _FakeProcess:
    stdout = ""
    stderr = ""
    returncode = 0


class StagedPathCase(unittest.TestCase):
    """A fresh run container set, one shared adapter, captured subprocess env."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def containers(self, n=TASKS):
        out = []
        for i in range(n):
            c = os.path.join(self.tmp.name, f"task-{i}")
            os.makedirs(c)
            out.append(c)
        return out

    def staged_path(self, workdir, name):
        return os.path.join(os.path.dirname(workdir), name)


class TestOpenCodeStaging(StagedPathCase):
    def harness(self):
        return get("opencode", HarnessConfig(model="m", base_url=ENDPOINT))

    def test_run_hands_the_subprocess_this_tasks_own_config(self):
        h = self.harness()
        first, second = self.containers(2)
        w1 = h.prepare(first)
        w2 = h.prepare(second)
        seen = {}
        with mock.patch("subprocess.run", return_value=_FakeProcess()) as run:
            h.run(w1, "p")
            h.run(w2, "p")
            seen[w1] = run.call_args_list[0].kwargs["env"]["OPENCODE_CONFIG"]
            seen[w2] = run.call_args_list[1].kwargs["env"]["OPENCODE_CONFIG"]
        self.assertEqual(seen[w1], self.staged_path(w1, CONFIG_NAME))
        self.assertEqual(seen[w2], self.staged_path(w2, CONFIG_NAME))
        self.assertNotEqual(seen[w1], seen[w2])

    def test_parallel_tasks_on_one_shared_instance_get_distinct_paths(self):
        """The runner's actual shape: one instance, a thread pool, many tasks.

        A barrier holds every fake subprocess open until all N tasks are inside
        run(), maximising the interleaving under the old shared-field code,
        where every task would have been handed whichever path prepare() wrote
        last.
        """
        h = self.harness()
        workdirs = [h.prepare(c) for c in self.containers()]
        barrier = threading.Barrier(TASKS)
        lock = threading.Lock()
        handed = {}

        def fake_run(argv, **kw):
            barrier.wait(timeout=30)
            with lock:
                handed[kw["cwd"]] = kw["env"].get("OPENCODE_CONFIG")
            return _FakeProcess()

        before = dict(vars(h))
        with mock.patch("subprocess.run", side_effect=fake_run):
            with ThreadPoolExecutor(max_workers=TASKS) as ex:
                list(ex.map(lambda w: h.run(w, "p"), workdirs))

        self.assertEqual(len(handed), TASKS, "each task ran exactly once")
        for wd in workdirs:
            self.assertEqual(handed[wd], self.staged_path(wd, CONFIG_NAME),
                             f"task {wd} was handed another task's config")
        self.assertEqual(len(set(handed.values())), TASKS,
                         "concurrent tasks must get distinct staged paths")
        self.assertEqual(vars(h), before,
                         "no adapter field may be written after __init__")

    def test_a_missing_staged_config_fails_loudly(self):
        """No silent fallback: opencode must not end up benchmarking our config."""
        h = self.harness()
        container, = self.containers(1)
        workdir = h.prepare(container)
        shutil.rmtree(container)

        res = h.run(workdir, "p")
        self.assertEqual(res.stop_reason, "error")
        self.assertIn(self.staged_path(workdir, CONFIG_NAME), res.error)
        self.assertIn("staged config", res.error)

    def test_a_missing_staged_config_never_runs_opencode(self):
        h = self.harness()
        container, = self.containers(1)
        workdir = h.prepare(container)
        shutil.rmtree(container)
        with mock.patch("subprocess.run",
                        side_effect=AssertionError("must not be invoked")):
            h.run(workdir, "p")

    def test_without_an_endpoint_nothing_is_redirected(self):
        h = get("opencode", HarnessConfig(provider="ollama", model="m"))
        container, = self.containers(1)
        workdir = h.prepare(container)
        self.assertFalse(os.path.exists(self.staged_path(workdir, CONFIG_NAME)),
                         "endpoint-less runs must stage no config")
        seen = {}
        with mock.patch("subprocess.run", return_value=_FakeProcess()) as run:
            h.run(workdir, "p")
            seen["env"] = run.call_args.kwargs["env"]
        self.assertNotIn("OPENCODE_CONFIG", seen["env"])


class TestClaudeCodeStaging(StagedPathCase):
    def harness(self):
        return get("claude-code", HarnessConfig(model="sonnet",
                                                base_url=ENDPOINT))

    def test_prepare_makes_the_config_home_but_remembers_nothing(self):
        h = self.harness()
        before = dict(vars(h))
        workdir = h.prepare(self.containers(1)[0])
        self.assertTrue(os.path.isdir(
            self.staged_path(workdir, CLAUDE_HOME)))
        self.assertEqual(vars(h), before,
                         "no adapter field may be written after __init__")

    def test_parallel_tasks_on_one_shared_instance_get_distinct_paths(self):
        h = self.harness()
        workdirs = [h.prepare(c) for c in self.containers()]
        barrier = threading.Barrier(TASKS)
        lock = threading.Lock()
        handed = {}

        def fake_run(argv, **kw):
            barrier.wait(timeout=30)
            with lock:
                handed[kw["cwd"]] = kw["env"].get("CLAUDE_CONFIG_DIR")
            return _FakeProcess()

        with mock.patch("subprocess.run", side_effect=fake_run):
            with ThreadPoolExecutor(max_workers=TASKS) as ex:
                list(ex.map(lambda w: h.run(w, "p"), workdirs))

        self.assertEqual(len(handed), TASKS, "each task ran exactly once")
        for wd in workdirs:
            self.assertEqual(handed[wd], self.staged_path(wd, CLAUDE_HOME),
                             f"task {wd} was handed another task's home")
        self.assertEqual(len(set(handed.values())), TASKS,
                         "concurrent tasks must get distinct config homes")

    def test_without_an_endpoint_nothing_is_redirected(self):
        h = get("claude-code", HarnessConfig(model="sonnet"))
        container, = self.containers(1)
        workdir = h.prepare(container)
        seen = {}
        with mock.patch("subprocess.run", return_value=_FakeProcess()) as run:
            h.run(workdir, "p")
            seen["env"] = run.call_args.kwargs["env"]
        self.assertNotIn("CLAUDE_CONFIG_DIR", seen["env"])


if __name__ == "__main__":
    unittest.main()
