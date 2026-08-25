"""The benchmark-harness skill's scripts are executable artifacts, so they get tests.

`shellcheck` lints the shell ones in CI, but a linter cannot catch an argument
parser that loops forever or an attribution rule that calls a plugin a built-in.
Same reasoning as tests/test_launcher_scripts.py: anything an agent runs
unattended is worth a regression test.
"""
import importlib.util
import json
import os
import subprocess
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, ".agents", "skills", "benchmark-harness")
SCRIPTS = os.path.join(SKILL, "scripts")

#: seconds any of these scripts may take. The point of the --harness-with-no-value
#: cases is that they used to never return at all, so a generous-but-finite cap
#: is the assertion.
TIMEOUT = 30


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


surface = _load("surface_usage", os.path.join(SCRIPTS, "surface_usage.py"))


def _run(argv, **kw):
    return subprocess.run(argv, cwd=SCRIPTS, capture_output=True, text=True,
                          timeout=TIMEOUT, **kw)


def _result_doc(harness, traces, summary=None):
    """A result JSON shaped like the ones `bench` writes."""
    s = dict(harness=dict(harness=harness), config=dict(samples=1))
    s.update(summary or {})
    return dict(summary=s,
                results=[dict(task=f"t{i}", trace=t) for i, t in enumerate(traces)])


class FlagValueGuards(unittest.TestCase):
    """A value-taking flag with no value must fail, not spin (PR #78 review)."""

    def test_collect_context_flags_without_values_exit_two(self):
        for flag in ("--harness", "--model", "--thinking"):
            with self.subTest(flag=flag):
                p = _run(["bash", "collect_context.sh", flag])
                self.assertEqual(p.returncode, 2, p.stderr)
                self.assertIn("needs a value", p.stderr)

    def test_collect_context_help_and_unknown_arg(self):
        self.assertEqual(_run(["bash", "collect_context.sh", "--help"]).returncode, 0)
        p = _run(["bash", "collect_context.sh", "--bogus"])
        self.assertEqual(p.returncode, 2)
        self.assertIn("unknown argument", p.stderr)

    def test_detect_setup_flags_without_values_do_not_hang(self):
        for flag in ("--harness", "--model"):
            with self.subTest(flag=flag):
                p = _run(["bash", "detect_setup.sh", flag])
                self.assertNotEqual(p.returncode, 0)


class ProviderSplit(unittest.TestCase):
    """detect_setup.sh must split the provider off the first slash only.

    benchkit/harness/models.py:_split does `text.split("/", 1)`; a second split
    in the opencode branch used to turn openrouter/qwen/qwen3-coder into
    provider=qwen (PR #78 review, F2).
    """

    def _detect(self, spec):
        env = dict(os.environ, BENCH_HARNESS_MODEL=spec)
        p = _run(["bash", "detect_setup.sh", "--harness", "opencode"], env=env)
        return dict(line.split("=", 1) for line in p.stdout.splitlines() if "=" in line)

    def test_multi_slash_spec_keeps_its_real_provider(self):
        got = self._detect("openrouter/qwen/qwen3-coder")
        self.assertEqual(got.get("provider"), "openrouter")
        self.assertEqual(got.get("model"), "qwen/qwen3-coder")

    def test_single_slash_spec(self):
        got = self._detect("anthropic/claude-sonnet-4-5")
        self.assertEqual(got.get("provider"), "anthropic")
        self.assertEqual(got.get("model"), "claude-sonnet-4-5")

    def test_spec_without_a_slash_has_no_provider(self):
        got = self._detect("noslashmodel")
        self.assertEqual(got.get("model"), "noslashmodel")
        self.assertEqual(got.get("provider", ""), "")


class Classification(unittest.TestCase):
    def test_mcp_server_recovered_from_the_tool_name(self):
        self.assertEqual(surface.classify("mcp__vercel__deploy", "claude-code"),
                         (surface.MCP_KIND, "vercel"))

    def test_mcp_server_name_may_contain_underscores(self):
        kind, server = surface.classify("mcp__claude_ai_Gmail__send", "claude-code")
        self.assertEqual(kind, surface.MCP_KIND)
        self.assertEqual(server, "claude_ai_Gmail")

    def test_skill_calls_are_counted_but_never_named(self):
        for name in ("Skill", "skill", "SlashCommand"):
            kind, detail = surface.classify(name, "claude-code")
            self.assertEqual(kind, surface.SKILL_KIND)
            self.assertNotIn(name.lower(), detail.lower().replace("(name not recorded)", ""))

    def test_static_table_used_when_there_is_no_isolated_arm(self):
        self.assertEqual(surface.classify("read", "pi")[0], surface.BUILTIN_KIND)

    def test_unknown_name_is_unattributed_not_a_skill(self):
        kind, _ = surface.classify("some_plugin_tool", "pi")
        self.assertEqual(kind, surface.UNKNOWN_KIND)

    def test_isolated_arm_outranks_the_static_table(self):
        # `read` is in pi's static table, but this isolated arm never called it,
        # so it is attributable to the surface — demonstration beats assumption.
        seen = {"bash"}
        self.assertEqual(surface.classify("read", "pi", seen)[0], surface.SURFACE_KIND)
        self.assertEqual(surface.classify("bash", "pi", seen)[0], surface.BUILTIN_KIND)

    def test_isolated_arm_still_classifies_mcp_first(self):
        kind, _ = surface.classify("mcp__vercel__deploy", "claude-code", {"Read"})
        self.assertEqual(kind, surface.MCP_KIND)


class Tally(unittest.TestCase):
    def test_per_task_index_holds_only_surface_attributed_calls(self):
        doc = _result_doc("claude-code", [["Read", "mcp__vercel__deploy", "Skill"]])
        kinds, per_task = surface.tally(doc, "claude-code")
        self.assertEqual(kinds[surface.MCP_KIND], {"vercel": 1})
        self.assertEqual(sorted(per_task["t0"]), ["Skill", "mcp__vercel__deploy"])

    def test_a_run_with_no_traces_tallies_to_nothing(self):
        kinds, per_task = surface.tally(_result_doc("pi", [[]]), "pi")
        self.assertEqual((kinds, per_task), ({}, {}))


class Rendering(unittest.TestCase):
    def test_idle_surface_is_called_out(self):
        doc = _result_doc("pi", [["read", "bash"]])
        out = "\n".join(surface.render_usage(doc, "pi", None, {}))
        self.assertIn("surface was idle", out)

    def test_used_surface_lists_the_tasks(self):
        doc = _result_doc("claude-code", [["Read"], ["mcp__vercel__deploy"]])
        out = "\n".join(surface.render_usage(doc, "claude-code", None, {}))
        self.assertNotIn("surface was idle", out)
        self.assertIn("`t1`", out)

    def test_skill_gap_is_stated_whenever_a_skill_fired(self):
        doc = _result_doc("claude-code", [["Skill"]])
        out = "\n".join(surface.render_usage(doc, "claude-code", None, {}))
        self.assertIn("not named", out)

    def test_ab_flags_a_sub_noise_gap_as_not_a_result(self):
        live = _result_doc("pi", [[]], dict(agent_score=0.70, config=dict(samples=2)))
        iso = _result_doc("pi", [[]], dict(agent_score=0.68, config=dict(samples=2)))
        out = "\n".join(surface.render_ab(live, iso))
        self.assertIn("Not a result", out)

    def test_ab_calls_a_real_gap_real(self):
        live = _result_doc("pi", [[]], dict(agent_score=0.80, config=dict(samples=4)))
        iso = _result_doc("pi", [[]], dict(agent_score=0.60, config=dict(samples=4)))
        out = "\n".join(surface.render_ab(live, iso))
        self.assertNotIn("Not a result", out)
        self.assertIn("live", out)

    def test_ab_never_recommends_the_sample_count_just_used(self):
        live = _result_doc("pi", [[]], dict(agent_score=0.70, config=dict(samples=4)))
        iso = _result_doc("pi", [[]], dict(agent_score=0.69, config=dict(samples=4)))
        out = "\n".join(surface.render_ab(live, iso))
        self.assertIn("--samples 8", out)


class Cli(unittest.TestCase):
    def _write(self, doc):
        f = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        json.dump(doc, f)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_missing_result_file_is_a_usage_error_not_a_traceback(self):
        p = subprocess.run(["python3", os.path.join(SCRIPTS, "surface_usage.py"),
                            "--live", "/definitely/not/here.json"],
                           capture_output=True, text=True, timeout=TIMEOUT)
        self.assertEqual(p.returncode, 2)
        self.assertNotIn("Traceback", p.stderr)

    def test_json_mode_emits_parsable_attribution(self):
        path = self._write(_result_doc("claude-code", [["Read", "mcp__vercel__x"]]))
        p = subprocess.run(["python3", os.path.join(SCRIPTS, "surface_usage.py"),
                            "--live", path, "--json"],
                           capture_output=True, text=True, timeout=TIMEOUT)
        self.assertEqual(p.returncode, 0, p.stderr)
        got = json.loads(p.stdout)
        self.assertEqual(got["harness"], "claude-code")
        self.assertFalse(got["builtin_from_isolated_arm"])

    def test_isolated_arm_is_recorded_as_the_attribution_source(self):
        live = self._write(_result_doc("pi", [["read", "plug"]]))
        iso = self._write(_result_doc("pi", [["read"]]))
        p = subprocess.run(["python3", os.path.join(SCRIPTS, "surface_usage.py"),
                            "--live", live, "--isolated", iso, "--json"],
                           capture_output=True, text=True, timeout=TIMEOUT)
        got = json.loads(p.stdout)
        self.assertTrue(got["builtin_from_isolated_arm"])
        self.assertEqual(got["kinds"][surface.SURFACE_KIND], {"plug": 1})


class ContextScrape(unittest.TestCase):
    def test_rows_are_scraped_and_a_missing_file_degrades(self):
        f = tempfile.NamedTemporaryFile("w", suffix=".md", delete=False)
        f.write("| Field | Value |\n|---|---|\n| skills | 70 global, 1 project |\n"
                "| mcp | none recorded |\n")
        f.close()
        self.addCleanup(os.unlink, f.name)
        got = surface.installed(f.name)
        self.assertEqual(got["skills"], "70 global, 1 project")
        self.assertEqual(got["mcp"], "none recorded")
        self.assertEqual(surface.installed("/definitely/not/here.md"), {})


if __name__ == "__main__":
    unittest.main()
