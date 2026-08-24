"""Tests for `bench sweep` — the setup matrix, the restart gate, the restore.

Nothing here touches a real endpoint or a real systemd unit. `serving` is
replaced by a recorder that counts `apply_config`/`restart` calls against a
temporary launcher file, both runners are stubbed, and results go to a temp
dir — so the guardrail these tests pin (never restart a shared endpoint
without explicit approval) is never violated by the tests themselves.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchkit import report, sweep
from benchkit import serving as real_serving

SUMMARY = dict(
    kind="agentic", pass_at_1=0.5, agent_score=0.4, mean_efficiency=0.8,
    mean_tool_calls=6.0, mean_par_calls=5.0, mean_turns=7.0, by_task={},
    by_difficulty={}, wall_seconds=1.0, mean_completion_tokens=10,
    truncated=0, errored=0, valid_call_rate=1.0, malformed_args=0,
    unknown_tools=0, hit_turn_limit=0, stalled_no_tool_call=0, generations=2,
    tasks=1,
)


def _summary(label, *, config="", harness="", thinking=False, score=0.4,
             samples=2):
    s = dict(SUMMARY)
    s["agent_score"] = score
    s["config"] = dict(label=label, model="montimage-dgx-spark", thinking=thinking,
                       max_tokens=0, samples=samples, concurrency=2,
                       base_url="http://x/v1", serving_config=config,
                       harness=harness)
    return s


class FakeServing:
    """Records what a sweep *would* do to the endpoint, and does none of it."""

    def __init__(self, tmp, sweepable=("cfg-a", "cfg-b"), fail_restore=False):
        self.LAUNCHER = os.path.join(tmp, "start-qwen.sh")
        with open(self.LAUNCHER, "w") as f:
            f.write('MODEL_ID="original/model"\nNAME="vllm-qwen"\n')
        self._sweepable = list(sweepable)
        self.applied = []
        self.restarts = 0
        self.fail_restore = fail_restore

    def sweepable_configs(self):
        ok = [(n, f"org/{n}", f"/configs/{n}.sh") for n in self._sweepable]
        return ok, [("llamacpp-qwen3.8-27b-bench", "?", "not a vLLM recipe")]

    def apply_config(self, name):
        self.applied.append(name)
        with open(self.LAUNCHER, "w") as f:
            f.write(f'MODEL_ID="org/{name}"\nNAME="vllm-qwen"\n')
        return f"/configs/{name}.sh", f"org/{name}"

    def restart(self):
        self.restarts += 1
        if self.fail_restore and self.applied and self.restarts > len(self.applied):
            raise RuntimeError("systemctl exploded during restore")
        return True


class ParseSetups(unittest.TestCase):
    def test_thinking_both_expands_to_two_products(self):
        got = sweep.parse_setup("config=cfg-a,thinking=both")
        self.assertEqual([s.thinking for s in got], [False, True])
        self.assertEqual({s.config for s in got}, {"cfg-a"})

    def test_defaults_are_active_launcher_and_builtin_loop(self):
        s, = sweep.parse_setup("model=foo")
        self.assertEqual(s.config, "")
        self.assertEqual(s.harness, "")
        self.assertEqual(s.harness_name, sweep.BUILTIN)
        self.assertEqual(s.config_name, "(active launcher)")

    def test_unknown_key_is_a_user_error(self):
        with self.assertRaises(SystemExit) as e:
            sweep.parse_setup("cnofig=cfg-a")
        self.assertIn("unknown --setup key", str(e.exception))

    def test_field_without_equals_is_a_user_error(self):
        with self.assertRaises(SystemExit):
            sweep.parse_setup("cfg-a")

    def test_bad_thinking_value_is_a_user_error(self):
        with self.assertRaises(SystemExit):
            sweep.parse_setup("thinking=maybe")

    def test_unknown_harness_is_rejected_before_anything_runs(self):
        with self.assertRaises(SystemExit) as e:
            sweep.parse_setups(["harness=emacs"], known_harnesses=("pi", "opencode"))
        self.assertIn("unknown harness", str(e.exception))

    def test_empty_matrix_is_a_user_error(self):
        with self.assertRaises(SystemExit):
            sweep.parse_setups([])

    def test_duplicate_rows_are_rejected_so_no_result_file_collides(self):
        with self.assertRaises(SystemExit) as e:
            sweep.parse_setups(["config=cfg-a", "config=cfg-a"])
        self.assertIn("duplicate setup", str(e.exception))

    def test_labelled_both_modes_keep_distinct_labels(self):
        a, b = sweep.parse_setup("config=cfg-a,thinking=both,label=trial")
        self.assertNotEqual(a.resolved_label(), b.resolved_label())


class Grouping(unittest.TestCase):
    def test_grouped_by_config_in_first_appearance_order(self):
        setups = (sweep.parse_setup("config=cfg-b,thinking=both")
                  + sweep.parse_setup("config=cfg-a")
                  + sweep.parse_setup("config=cfg-b,harness=pi,model=m"))
        groups = sweep.group_by_config(setups)
        self.assertEqual([c for c, _ in groups], ["cfg-b", "cfg-a"])
        self.assertEqual(len(groups[0][1]), 3)

    def test_configs_needing_swap_skips_the_active_launcher_rows(self):
        setups = sweep.parse_setup("harness=pi,model=m") + sweep.parse_setup("config=cfg-a")
        self.assertEqual(sweep.configs_needing_swap(setups), ["cfg-a"])


class Sweepability(unittest.TestCase):
    def test_llamacpp_recipe_is_excluded_with_a_reason_not_a_crash(self):
        with open(os.path.join(real_serving.CONFIGS,
                               "llamacpp-qwen3.8-27b-bench.sh")) as f:
            ok, reason = real_serving.sweepable(f.read())
        self.assertFalse(ok)
        self.assertIn("MODEL_ID", reason)

    def test_a_recipe_for_another_unit_is_excluded(self):
        ok, reason = real_serving.sweepable('MODEL_ID="a/b"\nNAME="vllm-gemma"\n')
        self.assertFalse(ok)
        self.assertIn("vllm-gemma", reason)

    def test_the_shipped_vllm_recipes_are_sweepable(self):
        ok, skipped = real_serving.sweepable_configs()
        names = {n for n, _, _ in ok}
        self.assertIn("qwen3.6-35b-a3b-nvfp4", names)
        self.assertIn("qwen3.8-27b-nvfp4-dspark", names)
        self.assertIn("llamacpp-qwen3.8-27b-bench", {n for n, _, _ in skipped})
        # a skipped recipe keeps its model id so `bench configs` stays complete
        self.assertEqual(len(skipped[0]), 3)

    def test_naming_an_undrivable_config_fails_before_any_restart(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        srv = FakeServing(tmp)
        setups = sweep.parse_setup("config=llamacpp-qwen3.8-27b-bench")
        with self.assertRaises(SystemExit) as e:
            sweep.check_sweepable(setups, srv)
        self.assertIn("cannot drive", str(e.exception))
        self.assertEqual(srv.restarts, 0)


class ApprovalGate(unittest.TestCase):
    """CLAUDE.md: never restart a shared serving endpoint without approval."""

    def test_non_interactive_without_the_flag_refuses(self):
        with self.assertRaises(SystemExit) as e:
            sweep.approve_restart(["cfg-a"], assume_yes=False,
                                  stdin=io.StringIO(""), stdout=io.StringIO())
        self.assertIn("--yes-restart-endpoint", str(e.exception))

    def test_refusal_counts_the_restore_restart_too(self):
        """Two configs cost three restarts — the gate must not quote two."""
        with self.assertRaises(SystemExit) as e:
            sweep.approve_restart(["cfg-a", "cfg-b"], assume_yes=False,
                                  stdin=io.StringIO(""), stdout=io.StringIO())
        msg = str(e.exception)
        self.assertIn("3 time(s)", msg)
        self.assertIn("restore the original serving config", msg)

    def test_explicit_flag_approves(self):
        self.assertTrue(sweep.approve_restart(["cfg-a"], assume_yes=True,
                                              log=lambda *a: None))

    def test_no_config_swap_needs_no_approval(self):
        self.assertTrue(sweep.approve_restart([], log=lambda *a: None))

    def test_interactive_yes_approves_and_anything_else_aborts(self):
        class Tty(io.StringIO):
            def isatty(self):
                return True

        self.assertTrue(sweep.approve_restart(
            ["cfg-a"], stdin=Tty("yes\n"), stdout=io.StringIO(), log=lambda *a: None))
        with self.assertRaises(SystemExit):
            sweep.approve_restart(["cfg-a"], stdin=Tty("y\n"),
                                  stdout=io.StringIO(), log=lambda *a: None)

    def test_a_refused_sweep_writes_nothing_and_restarts_nothing(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        srv = FakeServing(tmp)
        with open(srv.LAUNCHER) as f:
            before = f.read()
        out = os.path.join(tmp, "results")
        with self.assertRaises(SystemExit):
            sweep.run_sweep(sweep.parse_setup("config=cfg-a"), out,
                            execute=lambda s, label: (_summary(label), []),
                            serving=srv, stdin=io.StringIO(""),
                            stdout=io.StringIO(), log=lambda *a: None)
        self.assertEqual(srv.applied, [])
        self.assertEqual(srv.restarts, 0)
        with open(srv.LAUNCHER) as f:
            self.assertEqual(f.read(), before)
        self.assertFalse(os.path.exists(out) and os.listdir(out))


class RunSweep(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.out = os.path.join(self.tmp, "results")
        self.srv = FakeServing(self.tmp)
        with open(self.srv.LAUNCHER) as f:
            self.original = f.read()

    def _run(self, setups, **kw):
        calls = []

        def execute(setup, label):
            calls.append(label)
            return _summary(label, config=setup.config, harness=setup.harness,
                            thinking=setup.thinking), []

        kw.setdefault("assume_yes", True)
        paths = sweep.run_sweep(setups, self.out, execute=execute,
                                serving=self.srv, log=lambda *a: None, **kw)
        return paths, calls

    def test_one_restart_per_distinct_config_not_per_setup(self):
        setups = (sweep.parse_setup("config=cfg-a,thinking=both")
                  + sweep.parse_setup("config=cfg-b,thinking=both"))
        paths, calls = self._run(setups)
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.srv.applied, ["cfg-a", "cfg-b"])
        # two swaps plus the single restore restart
        self.assertEqual(self.srv.restarts, 3)
        self.assertEqual(len(paths), 4)

    def test_every_result_names_its_serving_config_and_harness(self):
        setups = (sweep.parse_setup("config=cfg-a")
                  + sweep.parse_setup("config=cfg-a,harness=opencode,model=m"))
        paths, _ = self._run(setups)
        seen = []
        for p in paths:
            with open(p) as f:
                cfg = json.load(f)["summary"]["config"]
            seen.append((cfg["serving_config"], cfg["harness"]))
        self.assertEqual(seen, [("cfg-a", ""), ("cfg-a", "opencode")])

    def test_original_launcher_is_restored_on_success(self):
        self._run(sweep.parse_setup("config=cfg-a"))
        with open(self.srv.LAUNCHER) as f:
            self.assertEqual(f.read(), self.original)

    def test_original_launcher_is_restored_on_failure(self):
        def boom(setup, label):
            raise RuntimeError("the run itself failed")

        with self.assertRaises(RuntimeError) as e:
            sweep.run_sweep(sweep.parse_setup("config=cfg-a"), self.out,
                            execute=boom, serving=self.srv, assume_yes=True,
                            log=lambda *a: None)
        # the *original* exception survives, unmasked by the restore
        self.assertEqual(str(e.exception), "the run itself failed")
        with open(self.srv.LAUNCHER) as f:
            self.assertEqual(f.read(), self.original)

    def test_a_failing_restore_never_masks_the_original_exception(self):
        srv = FakeServing(self.tmp, fail_restore=True)
        logged = []

        def boom(setup, label):
            raise RuntimeError("the run itself failed")

        with self.assertRaises(RuntimeError) as e:
            sweep.run_sweep(sweep.parse_setup("config=cfg-a"), self.out,
                            execute=boom, serving=srv, assume_yes=True,
                            log=logged.append)
        self.assertEqual(str(e.exception), "the run itself failed")
        self.assertTrue(any("could not restore" in line for line in logged))

    def test_a_failing_restore_on_the_success_path_is_reported(self):
        srv = FakeServing(self.tmp, fail_restore=True)
        with self.assertRaises(RuntimeError) as e:
            sweep.run_sweep(sweep.parse_setup("config=cfg-a"), self.out,
                            execute=lambda s, label: (_summary(label), []),
                            serving=srv, assume_yes=True, log=lambda *a: None)
        self.assertIn("systemctl exploded", str(e.exception))

    def test_no_config_in_the_matrix_means_no_swap_and_no_restore(self):
        paths, calls = self._run(sweep.parse_setup("harness=opencode,model=m"),
                                 assume_yes=False)
        self.assertEqual(self.srv.applied, [])
        self.assertEqual(self.srv.restarts, 0)
        self.assertEqual(len(paths), 1)

    def test_results_are_append_only_never_overwritten(self):
        os.makedirs(self.out, exist_ok=True)
        setups = sweep.parse_setup("config=cfg-a,label=fixed")
        taken = os.path.join(self.out, sweep._slug(setups[0].resolved_label()) + ".json")
        with open(taken, "w") as f:
            f.write("{}")
        with self.assertRaises(SystemExit) as e:
            self._run(setups)
        self.assertIn("refusing to overwrite", str(e.exception))
        with open(taken) as f:
            self.assertEqual(f.read(), "{}")


class RankedReport(unittest.TestCase):
    def _runs(self, *specs):
        return [{"summary": _summary(label, config=cfg, harness=h,
                                     thinking=t, score=score),
                 "_path": f"{label}.json"}
                for label, cfg, h, t, score in specs]

    def test_ranks_within_a_harness_and_never_across_harnesses(self):
        runs = self._runs(("a", "cfg-a", "", False, 0.40),
                          ("b", "cfg-b", "", False, 0.62),
                          ("c", "cfg-a", "opencode", False, 0.79))
        md = report.rank_setups(runs, ["a", "b", "c"])
        self.assertIn("### built-in loop · thinking OFF", md)
        self.assertIn("### opencode · thinking OFF", md)
        self.assertIn("no single cross-harness winner", md)
        # the 79.0 opencode row must not be crowned over the built-in block
        builtin = md.split("### built-in loop")[1].split("###")[0]
        self.assertIn("Winner: b", builtin)

    def test_thinking_modes_are_separate_blocks(self):
        runs = self._runs(("off", "cfg-a", "", False, 0.4),
                          ("on", "cfg-a", "", True, 0.9))
        md = report.rank_setups(runs, ["off", "on"])
        self.assertIn("thinking OFF", md)
        self.assertIn("thinking ON", md)
        self.assertIn("only setup in this block", md)

    def test_a_margin_inside_the_noise_floor_is_called_a_tie(self):
        runs = self._runs(("a", "cfg-a", "", False, 0.40),
                          ("b", "cfg-b", "", False, 0.43))
        md = report.rank_setups(runs, ["a", "b"])
        self.assertIn("noise floor", md)
        self.assertIn("treat it as a tie", md)

    def test_a_margin_clearing_the_noise_floor_is_called_a_win(self):
        runs = self._runs(("a", "cfg-a", "", False, 0.40),
                          ("b", "cfg-b", "", False, 0.70))
        md = report.rank_setups(runs, ["a", "b"])
        self.assertIn("clears the noise floor", md)
        self.assertIn("~8.0 points at 2 samples per task", md)

    def test_the_noise_floor_shrinks_with_the_sample_count(self):
        self.assertEqual(report.noise_floor(2), report.NOISE_POINTS)
        self.assertLess(report.noise_floor(8), report.NOISE_POINTS)
        self.assertGreater(report.noise_floor(1), report.NOISE_POINTS)
        # a result file with no recorded sample count falls back, never crashes
        self.assertEqual(report.noise_floor(None), report.NOISE_POINTS)

    def test_a_block_mixing_scored_and_unscored_runs_uses_one_ruler(self):
        """A table must never rank on a metric its own cells do not show."""
        runs = self._runs(("a", "cfg-a", "", False, 0.90),
                          ("b", "cfg-b", "", False, 0.10))
        runs[0]["summary"]["agent_score"] = None      # predates oracle-par
        runs[0]["summary"]["pass_at_1"] = 0.10
        runs[1]["summary"]["pass_at_1"] = 0.80
        md = report.rank_setups(runs, ["a", "b"])
        self.assertIn("| pass@1 |", md)
        self.assertNotIn("Agent score", md)
        # ranked on pass@1, so b wins and the quoted figures are pass@1 figures
        self.assertIn("Winner: b", md)
        self.assertIn("80.0 against 10.0", md)

    def test_every_row_names_its_serving_config_and_harness(self):
        runs = self._runs(("a", "cfg-a", "opencode", False, 0.4))
        md = report.rank_setups(runs, ["a"])
        self.assertIn("`cfg-a`", md)
        self.assertIn("opencode", md)

    def test_no_cross_block_row_is_bolded_as_the_overall_winner(self):
        """The Results table must not crown a harness above the section that
        explains no cross-harness winner exists."""
        runs = self._runs(("builtin-a", "cfg-a", "", False, 0.40),
                          ("builtin-b", "cfg-b", "", False, 0.50),
                          ("opencode-a", "cfg-a", "opencode", False, 0.90))
        md = report.build(runs, title="t", setups=True)
        results = md.split("## Results")[1].split("## Ranked setups")[0]
        # one leader per block, so exactly two bolded rows, not one global best
        self.assertIn("**builtin-b**", results)
        self.assertIn("**opencode-a**", results)
        self.assertNotIn("**builtin-a**", results)
        self.assertIn("Bold marks the leader **within** its own harness", results)

    def test_the_disagreement_table_never_pairs_two_blocks(self):
        runs = self._runs(("builtin", "cfg-a", "", False, 0.40),
                          ("opencode", "cfg-a", "opencode", False, 0.90))
        for r, tasks in zip(runs, ({"t1": 1.0}, {"t1": 0.0})):
            r["summary"]["by_task"] = tasks
        md = report.build(runs, title="t", setups=True)
        self.assertNotIn("Where they disagree", md)

    def test_chart_labels_distinguish_setups_on_one_model(self):
        runs = self._runs(("a", "cfg-a", "", False, 0.4),
                          ("b", "cfg-b", "", False, 0.5),
                          ("c", "cfg-a", "opencode", False, 0.6))
        short = report._setup_short(runs)
        self.assertEqual(len(set(short)), 3)

    def test_the_noise_floor_follows_the_noisiest_row_in_the_block(self):
        runs = self._runs(("a", "cfg-a", "", False, 0.40),
                          ("b", "cfg-b", "", False, 0.50))
        runs[0]["summary"]["config"]["samples"] = 8
        runs[1]["summary"]["config"]["samples"] = 2
        md = report.rank_setups(runs, ["a", "b"])
        self.assertIn("at 2 samples per task", md)

    def test_build_embeds_the_ranking_when_asked(self):
        runs = self._runs(("a", "cfg-a", "", False, 0.4),
                          ("b", "cfg-b", "", False, 0.7))
        md = report.build(runs, title="t", setups=True)
        self.assertIn("## Ranked setups", md)
        self.assertNotIn("## Ranked setups",
                         report.build(runs, title="t"))


class LegacyAttribution(unittest.TestCase):
    """Result files written before `bench sweep` must still rank honestly.

    `harness.describe()` records the harness under the key "harness", not
    "name". Reading the wrong key would file every pre-sweep harness run under
    the built-in loop and rank three harnesses inside a single block — exactly
    the cross-harness comparison the ranking exists to prevent.
    """

    def test_a_legacy_harness_block_is_read_and_kept_in_its_own_block(self):
        runs = []
        for name, score in (("opencode", 0.79), ("pi", 0.77), (None, 0.67)):
            s = _summary(name or "benchkit loop", score=score)
            s["config"].pop("harness")
            s["config"].pop("serving_config")
            if name:
                s["harness"] = {"harness": name, "model": "m"}
            runs.append({"summary": s, "_path": f"{name}.json"})
        md = report.rank_setups(runs, ["opencode", "pi", "builtin"])
        self.assertIn("### opencode · thinking OFF", md)
        self.assertIn("### pi · thinking OFF", md)
        self.assertIn(f"### {report.BUILTIN_HARNESS} · thinking OFF", md)
        # every block holds exactly one run, so none can crown another harness
        self.assertEqual(md.count("only setup in this block"), 3)

    def test_a_missing_sample_count_never_renders_as_none(self):
        runs = []
        for label, score in (("a", 0.40), ("b", 0.80)):
            s = _summary(label, score=score)
            s["config"]["samples"] = None
            runs.append({"summary": s, "_path": f"{label}.json"})
        md = report.rank_setups(runs, ["a", "b"])
        self.assertNotIn("None samples", md)
        self.assertIn("assumed — not every run in this block recorded one", md)


class NoRestartIsRefused(unittest.TestCase):
    """Swapping a config without restarting would file a lie in append-only results/."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.srv = FakeServing(self.tmp)

    def test_a_config_swap_without_a_restart_is_refused(self):
        with self.assertRaises(SystemExit) as e:
            sweep.run_sweep(sweep.parse_setup("config=cfg-a"),
                            os.path.join(self.tmp, "out"),
                            execute=lambda s, label: (_summary(label), []),
                            serving=self.srv, assume_yes=True, restart=False,
                            log=lambda *a: None)
        self.assertIn("cannot run without restarting", str(e.exception))
        self.assertEqual(self.srv.applied, [])

    def test_a_matrix_with_no_config_swap_needs_no_restart(self):
        paths = sweep.run_sweep(sweep.parse_setup("harness=opencode,model=m"),
                                os.path.join(self.tmp, "out"),
                                execute=lambda s, label: (_summary(label), []),
                                serving=self.srv, restart=False,
                                log=lambda *a: None)
        self.assertEqual(len(paths), 1)
        self.assertEqual(self.srv.restarts, 0)


class CliWiring(unittest.TestCase):
    """The argparse surface and the per-setup Config attribution."""

    def test_dry_run_prints_the_plan_and_touches_nothing(self):
        from benchkit import cli
        buf = io.StringIO()
        old = sys.stdout
        sys.stdout = buf
        try:
            rc = cli.main(["sweep", "--dry-run", "--suite", "agentic",
                           "--setup", "config=qwen3.6-35b-a3b-nvfp4,thinking=both",
                           "--setup", "config=qwen3.8-27b-nvfp4-dspark"])
        finally:
            sys.stdout = old
        text = buf.getvalue()
        self.assertEqual(rc, 0)
        self.assertIn("3 setups in 2 serving-config groups", text)
        self.assertIn("2 endpoint restarts", text)
        self.assertIn("would ask for approval first", text)

    def test_dry_run_rejects_an_undrivable_config(self):
        from benchkit import cli
        with self.assertRaises(SystemExit):
            cli.main(["sweep", "--dry-run",
                      "--setup", "config=llamacpp-qwen3.8-27b-bench"])

    def test_builtin_setup_config_carries_the_attribution(self):
        from benchkit import cli

        captured = {}

        def fake_execute(suite, tasks, cfg, max_turns=None, keep_code=False):
            captured["cfg"] = cfg
            return _summary(cfg.label), []

        orig = cli._execute_suite
        cli._execute_suite = fake_execute
        try:
            parsed = _Args(suite="agentic", base_url="http://x/v1",
                           model="montimage-dgx-spark", samples=2, concurrency=2,
                           test_timeout=60, max_tokens=6000, max_tokens_think=16000,
                           max_turns=25, timeout=900, endpoint="")
            setup, = sweep.parse_setup("config=cfg-a,thinking=on")
            cli._sweep_execute(parsed, setup, "a label")
        finally:
            cli._execute_suite = orig
        cfg = captured["cfg"]
        self.assertEqual(cfg.serving_config, "cfg-a")
        self.assertEqual(cfg.harness, "")
        self.assertTrue(cfg.thinking)
        self.assertEqual(cfg.max_tokens, 16000)
        self.assertEqual(cfg.label, "a label")

    def test_result_paths_are_known_before_the_first_restart(self):
        setups = sweep.parse_setup("config=cfg-a,thinking=both")
        paths = sweep.result_paths(setups, "/out", "m")
        self.assertEqual(len(paths), 2)
        self.assertTrue(all(p.startswith("/out/") and p.endswith(".json")
                            for p in paths))
        self.assertEqual(len(set(paths)), 2)

    def test_a_colliding_result_file_is_caught_before_any_restart(self):
        from benchkit import cli
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        setups = sweep.parse_setups(["config=qwen3.6-35b-a3b-nvfp4"],
                                    default_model="montimage-dgx-spark")
        outdir = os.path.join(tmp, f"{cli._stamp()}-half-finished")
        os.makedirs(outdir)
        victim, = sweep.result_paths(setups, outdir, "montimage-dgx-spark")
        with open(victim, "w") as f:
            f.write("an earlier campaign")
        orig = cli.RESULTS
        cli.RESULTS = tmp
        try:
            with self.assertRaises(SystemExit) as e:
                cli.main(["sweep", "--title", "half finished",
                          "--setup", "config=qwen3.6-35b-a3b-nvfp4"])
        finally:
            cli.RESULTS = orig
        self.assertIn("earlier campaign", str(e.exception))
        with open(victim) as f:
            self.assertEqual(f.read(), "an earlier campaign")

    def test_a_harness_setup_on_a_codegen_suite_fails_in_preflight(self):
        """The wrong --suite must cost zero endpoint restarts, not two."""
        from benchkit import cli
        with self.assertRaises(SystemExit) as e:
            cli.main(["sweep", "--suite", "core16",
                      "--setup", "config=qwen3.6-35b-a3b-nvfp4,harness=opencode,"
                                 "model=montimage-dgx-spark"])
        self.assertIn("agentic suite", str(e.exception))

    def test_report_refuses_to_overwrite_an_existing_report(self):
        from benchkit import cli
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        src = os.path.join(tmp, "a.json")
        with open(src, "w") as f:
            json.dump(dict(summary=_summary("a"), results=[]), f)
        out = os.path.join(tmp, "REPORT.md")
        with open(out, "w") as f:
            f.write("an earlier campaign")
        with self.assertRaises(SystemExit) as e:
            cli.main(["report", src])
        self.assertIn("refusing to overwrite an existing report", str(e.exception))
        with open(out) as f:
            self.assertEqual(f.read(), "an earlier campaign")
        cli.main(["report", src, "--force"])
        with open(out) as f:
            self.assertNotEqual(f.read(), "an earlier campaign")

    def test_report_can_rebuild_the_ranking_from_result_files(self):
        from benchkit import cli
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        paths = []
        for label, score in (("a", 0.4), ("b", 0.7)):
            p = os.path.join(tmp, f"{label}.json")
            with open(p, "w") as f:
                json.dump(dict(summary=_summary(label, config="cfg-" + label,
                                                score=score), results=[]), f)
            paths.append(p)
        out = os.path.join(tmp, "REPORT.md")
        cli.main(["report", *paths, "--setups", "--out", out])
        with open(out) as f:
            self.assertIn("## Ranked setups", f.read())

    def test_a_bad_harness_model_spec_fails_before_any_restart(self):
        from benchkit import cli
        parsed = _Args(model="")
        setup, = sweep.parse_setup("config=cfg-a,harness=opencode")
        with self.assertRaises(SystemExit) as e:
            cli._sweep_model(parsed, setup)
        self.assertIn("no model selected", str(e.exception))

    def test_the_restart_flag_is_wired_through_to_run_sweep(self):
        """An argparse dest typo on the guardrail flag must not pass CI.

        Belt and braces: `run_sweep` is stubbed *and* the real restart path is
        stubbed, so even a refactor that moved the patch target could not turn
        this test into a live `systemctl restart` in CI.
        """
        from benchkit import cli
        from benchkit import serving as real
        from benchkit import sweep as sweep_mod
        seen, touched = {}, []
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)

        def fake_run_sweep(setups, outdir, **kw):
            seen.update(kw)
            raise SystemExit("stop here")

        saved = (sweep_mod.run_sweep, real.restart, real.apply_config, cli.RESULTS)
        sweep_mod.run_sweep = fake_run_sweep
        real.restart = lambda *a, **k: touched.append("restart")
        real.apply_config = lambda *a, **k: touched.append("apply")
        cli.RESULTS = tmp
        try:
            with self.assertRaises(SystemExit):
                cli.main(["sweep", "--suite", "agentic", "--yes-restart-endpoint",
                          "--title", "wiring probe",
                          "--setup", "config=qwen3.6-35b-a3b-nvfp4"])
        finally:
            (sweep_mod.run_sweep, real.restart, real.apply_config,
             cli.RESULTS) = saved
        self.assertIs(seen.get("assume_yes"), True)
        self.assertEqual(touched, [])

    def test_a_same_day_report_is_never_overwritten(self):
        """_stamp() is day-granular, so two same-title sweeps share an outdir."""
        from benchkit import cli
        tmp = tempfile.mkdtemp()          # never the real results/, which is append-only
        self.addCleanup(shutil.rmtree, tmp)
        outdir = os.path.join(tmp, f"{cli._stamp()}-collision-probe")
        os.makedirs(outdir)
        report_path = os.path.join(outdir, "REPORT.md")
        with open(report_path, "w") as f:
            f.write("first campaign")
        orig = cli.RESULTS
        cli.RESULTS = tmp
        try:
            with self.assertRaises(SystemExit) as e:
                cli.main(["sweep", "--title", "collision probe",
                          "--setup", "config=qwen3.6-35b-a3b-nvfp4"])
        finally:
            cli.RESULTS = orig
        self.assertIn("refusing to overwrite files from an earlier campaign",
                      str(e.exception))
        with open(report_path) as f:
            self.assertEqual(f.read(), "first campaign")

    def test_a_harness_setup_needs_an_agentic_suite(self):
        from benchkit import cli
        parsed = _Args(suite="core16", base_url="http://x/v1", model="m",
                       samples=1, concurrency=1, test_timeout=60, max_tokens=1,
                       max_tokens_think=1, max_turns=1, timeout=1, endpoint="")
        setup, = sweep.parse_setup("harness=opencode,model=m")
        with self.assertRaises(SystemExit) as e:
            cli._sweep_execute(parsed, setup, "l")
        self.assertIn("agentic suite", str(e.exception))


class _Args:
    def __init__(self, **kw):
        self.__dict__.update(kw)


if __name__ == "__main__":
    unittest.main()
