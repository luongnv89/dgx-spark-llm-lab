"""Tests for suite dispatch — `bench run` and `bench compare` must agree.

`bench compare` used to call the one-shot `runner.run` unconditionally, so an
agentic suite (whose tasks carry `check`/`files`/`oracle` and no `tests`) blew
up with `KeyError: 'tests'` inside `runner.run_tests` (issue #55). Both
commands now route through the single `_execute_suite` dispatch point, and
these tests pin that: the codegen path is unchanged, the agentic path reaches
the tool-calling loop, and the summary written by compare carries the agentic
metrics the report renders.

Nothing here touches a real endpoint: `serving.current_model`/`swap_to`, both
runners and the report builder are stubbed, and results go to a temp dir.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchkit import cli

AGENTIC_SUMMARY = dict(
    kind="agentic", pass_at_1=0.5, agent_score=0.4, mean_efficiency=0.8,
    mean_tool_calls=6.0, mean_par_calls=5.0, mean_turns=7.0,
    by_difficulty={}, wall_seconds=1.0, mean_completion_tokens=10,
    truncated=0, errored=0, valid_call_rate=1.0, malformed_args=0,
    unknown_tools=0, hit_turn_limit=0, stalled_no_tool_call=0,
)
CODEGEN_SUMMARY = dict(
    kind="codegen", pass_at_1=0.5, by_difficulty={}, wall_seconds=1.0,
    mean_completion_tokens=10, truncated=0, errored=0,
)


class _Recorder:
    """Stand-in for a runner: records the call, returns a canned summary."""

    def __init__(self, summary):
        self.summary = summary
        self.calls = []

    def __call__(self, tasks, cfg, on_result=None, **kw):
        self.calls.append(dict(tasks=tasks, cfg=cfg, on_result=on_result, **kw))
        return dict(self.summary), []


class TestExecuteSuite(unittest.TestCase):
    """The dispatch helper itself: one decision point, two paths."""

    def setUp(self):
        self.codegen = _Recorder(CODEGEN_SUMMARY)
        self._orig_runner_run = cli.runner.run
        cli.runner.run = self.codegen
        from benchkit.agentic import loop
        self.loop = loop
        self.agentic = _Recorder(AGENTIC_SUMMARY)
        self._orig_loop_run = loop.run
        loop.run = self.agentic

    def tearDown(self):
        cli.runner.run = self._orig_runner_run
        self.loop.run = self._orig_loop_run

    def test_agentic_suite_goes_to_the_tool_calling_loop(self):
        summary, _ = cli._execute_suite("agentic", ["t"], "cfg", max_turns=9)
        self.assertEqual(len(self.agentic.calls), 1)
        self.assertEqual(self.codegen.calls, [])
        self.assertEqual(self.agentic.calls[0]["max_turns"], 9)
        self.assertEqual(summary["kind"], "agentic")

    def test_every_agentic_suite_name_dispatches_the_same_way(self):
        for name in ("agentic", "agentic-hard", "agentic-all"):
            with self.subTest(suite=name):
                self.agentic.calls.clear()
                cli._execute_suite(name, ["t"], "cfg")
                self.assertEqual(len(self.agentic.calls), 1)
        self.assertEqual(self.codegen.calls, [])

    def test_codegen_suite_still_goes_to_the_one_shot_runner(self):
        summary, _ = cli._execute_suite("core16", ["t"], "cfg", keep_code=True)
        self.assertEqual(len(self.codegen.calls), 1)
        self.assertEqual(self.agentic.calls, [])
        self.assertTrue(self.codegen.calls[0]["keep_code"])
        self.assertEqual(summary["kind"], "codegen")

    def test_omitted_max_turns_leaves_the_loop_default_alone(self):
        cli._execute_suite("agentic", ["t"], "cfg")
        self.assertNotIn("max_turns", self.agentic.calls[0])


class TestWrongDispatchIsFatal(unittest.TestCase):
    """Why dispatch matters: the one-shot runner cannot execute an agentic task.

    This is the original #55 crash, isolated. It documents that routing an
    agentic suite to `runner.run` is not merely suboptimal but fatal, so the
    dispatch assertions above are guarding a real failure and not a style
    preference. Read-only over the suite definitions -- no task is modified.
    """

    def test_run_tests_cannot_score_an_agentic_task(self):
        from benchkit import runner
        from benchkit.suites import get

        task = get("agentic")[0]
        self.assertNotIn("tests", task)
        with self.assertRaises(KeyError) as caught:
            runner.run_tests(task, "", timeout=1)
        self.assertEqual(caught.exception.args[0], "tests")


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


class _FakeServing:
    def __init__(self):
        self.swaps = []

    def current_model(self):
        return "org/original"

    def swap_to(self, model_id, **kw):
        self.swaps.append(model_id)

    def restart(self, *a, **kw):  # pragma: no cover - must never be reached
        raise AssertionError("tests must never restart a serving endpoint")


class TestCompareDispatch(unittest.TestCase):
    """`bench compare --suite agentic` completes and writes agentic metrics."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self._orig_results = cli.RESULTS
        cli.RESULTS = self.tmp

        self.serving = _FakeServing()
        import benchkit.serving as real_serving
        self._orig_serving = dict(
            current_model=real_serving.current_model,
            swap_to=real_serving.swap_to,
            restart=real_serving.restart,
        )
        self.real_serving = real_serving
        real_serving.current_model = self.serving.current_model
        real_serving.swap_to = self.serving.swap_to
        real_serving.restart = self.serving.restart

        self.codegen = _Recorder(CODEGEN_SUMMARY)
        self._orig_runner_run = cli.runner.run
        cli.runner.run = self.codegen
        from benchkit.agentic import loop
        self.loop = loop
        self.agentic = _Recorder(AGENTIC_SUMMARY)
        self._orig_loop_run = loop.run
        loop.run = self.agentic

        self._orig_build = cli.report.build
        cli.report.build = lambda runs, **kw: "# report\n"

    def tearDown(self):
        cli.RESULTS = self._orig_results
        for name, fn in self._orig_serving.items():
            setattr(self.real_serving, name, fn)
        cli.runner.run = self._orig_runner_run
        self.loop.run = self._orig_loop_run
        cli.report.build = self._orig_build
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _args(self, suite):
        return _Args(
            models=["org/model-a"], suite=suite, title="t", question=None,
            base_url="http://localhost:8001/v1", model="served-alias",
            thinking=False, both_modes=False, max_tokens=6000,
            max_tokens_think=16000, samples=1, concurrency=1,
            test_timeout=60, max_turns=9, restore=True, yes=True,
        )

    def _written(self):
        outdir = os.path.join(self.tmp, os.listdir(self.tmp)[0])
        files = sorted(f for f in os.listdir(outdir) if f.endswith(".json"))
        return [json.load(open(os.path.join(outdir, f))) for f in files]

    def test_agentic_compare_runs_the_loop_and_writes_agentic_metrics(self):
        self.assertEqual(cli.cmd_compare(self._args("agentic")), 0)
        self.assertEqual(len(self.agentic.calls), 1)
        self.assertEqual(self.codegen.calls, [])
        self.assertEqual(self.agentic.calls[0]["max_turns"], 9)

        written = self._written()
        self.assertEqual(len(written), 1)
        summary = written[0]["summary"]
        self.assertEqual(summary["kind"], "agentic")
        self.assertIsNotNone(summary["agent_score"])
        self.assertIn("mean_turns", summary)

    def test_one_shot_compare_is_unchanged(self):
        self.assertEqual(cli.cmd_compare(self._args("core16")), 0)
        self.assertEqual(len(self.codegen.calls), 1)
        self.assertEqual(self.agentic.calls, [])
        self.assertEqual(self._written()[0]["summary"]["kind"], "codegen")

    def test_compare_restores_the_original_model_and_never_restarts(self):
        cli.cmd_compare(self._args("agentic"))
        self.assertEqual(self.serving.swaps, ["org/model-a", "org/original"])


class TestCompareParser(unittest.TestCase):
    """The compare subparser must accept the agentic knob `run` already has."""

    def test_compare_accepts_max_turns(self):
        parsed = {}

        def fake_compare(args):
            parsed.update(vars(args))
            return 0

        # main() rebuilds the parser on every call and resolves cmd_compare
        # from the module globals then, so patching before the call is enough.
        orig = cli.cmd_compare
        cli.cmd_compare = fake_compare
        try:
            self.assertEqual(
                cli.main(["compare", "org/a", "--suite", "agentic",
                          "--max-turns", "7"]), 0)
        finally:
            cli.cmd_compare = orig
        self.assertEqual(parsed["max_turns"], 7)


if __name__ == "__main__":
    unittest.main()
