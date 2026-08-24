"""Tests for harness model selection.

The point of these is the promise the harness commands make: you can benchmark
whatever your own opencode or pi install can already reach, and a bad selection
is reported before the run rather than as a provider error inside every task.
"""
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchkit.harness import HARNESSES, HarnessConfig, get, models

CATALOGUE = [
    ("anthropic", "claude-sonnet-4-5"),
    ("ollama", "qwen3-coder:latest"),
    ("ollama", "gpt-oss:20b"),
    ("openrouter", "anthropic/claude-3.5-haiku"),
]


class TestResolve(unittest.TestCase):
    def test_exact_spec(self):
        self.assertEqual(models.resolve("ollama/gpt-oss:20b", CATALOGUE),
                         ("ollama", "gpt-oss:20b"))

    def test_bare_model_id(self):
        self.assertEqual(models.resolve("qwen3-coder:latest", CATALOGUE),
                         ("ollama", "qwen3-coder:latest"))

    def test_unique_substring(self):
        self.assertEqual(models.resolve("qwen3", CATALOGUE),
                         ("ollama", "qwen3-coder:latest"))

    def test_model_id_containing_a_slash(self):
        """openrouter-style ids have their own slash; only the first splits."""
        self.assertEqual(models.resolve("openrouter/anthropic/claude-3.5-haiku",
                                        CATALOGUE),
                         ("openrouter", "anthropic/claude-3.5-haiku"))

    def test_provider_narrows_an_ambiguous_spec(self):
        self.assertEqual(models.resolve("claude-3.5-haiku", CATALOGUE,
                                        provider="openrouter"),
                         ("openrouter", "anthropic/claude-3.5-haiku"))

    def test_ambiguous_lists_candidates(self):
        with self.assertRaises(SystemExit) as cm:
            models.resolve("claude", CATALOGUE)
        self.assertIn("anthropic/claude-sonnet-4-5", str(cm.exception))
        self.assertIn("openrouter/anthropic/claude-3.5-haiku", str(cm.exception))

    def test_unknown_lists_what_is_available(self):
        with self.assertRaises(SystemExit) as cm:
            models.resolve("gpt-4o", CATALOGUE)
        self.assertIn("ollama/qwen3-coder:latest", str(cm.exception))

    def test_unknown_provider_is_named(self):
        with self.assertRaises(SystemExit) as cm:
            models.resolve("anything", CATALOGUE, provider="nope")
        self.assertIn("nope", str(cm.exception))

    def test_empty_spec_rejected(self):
        with self.assertRaises(SystemExit):
            models.resolve("", CATALOGUE)

    def test_no_catalogue_takes_the_spec_literally(self):
        """A harness that cannot enumerate must still run a named model."""
        self.assertEqual(models.resolve("sonnet", []), (None, "sonnet"))
        self.assertEqual(models.resolve("acme/m1", []), ("acme", "m1"))
        self.assertEqual(models.resolve("m1", [], provider="acme"), ("acme", "m1"))


class TestPick(unittest.TestCase):
    """Selection at benchmark time must never hang an unattended run."""

    def test_non_tty_lists_and_exits(self):
        with self.assertRaises(SystemExit) as cm:
            models.pick("opencode", CATALOGUE, stdin=io.StringIO())
        self.assertIn("BENCH_HARNESS_MODEL", str(cm.exception))
        self.assertIn("ollama/gpt-oss:20b", str(cm.exception))

    def test_no_catalogue_says_so(self):
        with self.assertRaises(SystemExit) as cm:
            models.pick("claude-code", [], stdin=io.StringIO())
        self.assertIn("cannot list its own models", str(cm.exception))


class TestCatalogue(unittest.TestCase):
    def test_enumeration_failure_is_empty_not_an_exception(self):
        class Broken:
            def list_models(self):
                raise RuntimeError("binary exploded")
        self.assertEqual(models.catalogue(Broken()), [])

    def test_spec_without_provider(self):
        self.assertEqual(models.spec(None, "sonnet"), "sonnet")
        self.assertEqual(models.spec("ollama", "m"), "ollama/m")


def _offline_describe(h):
    """describe() without the reachability probe it normally runs.

    `available()` calls the endpoint, and a unit suite must not care what
    happens to be serving on the machine running it — nor pay a DNS timeout for
    a hostname invented by the test.
    """
    h.available = lambda: (True, "stubbed")
    return h.describe()


class TestHarnessDefaults(unittest.TestCase):
    """No harness may default to one machine's model or endpoint."""

    def test_no_hardcoded_model(self):
        for name in HARNESSES:
            with self.subTest(harness=name):
                self.assertIsNone(get(name).model)

    def test_no_endpoint_unless_asked(self):
        for name in HARNESSES:
            with self.subTest(harness=name):
                self.assertIsNone(get(name).base_url)
                self.assertFalse(get(name).uses_endpoint)

    def test_unselected_model_is_not_available(self):
        for name in HARNESSES:
            with self.subTest(harness=name):
                ok, detail = get(name).available()
                if ok:
                    self.fail(f"{name} reports available with no model: {detail}")

    def test_pi_accepts_an_endpoint(self):
        """pi used to refuse one outright; it now stages a catalogue instead."""
        h = get("pi", HarnessConfig(model="m", base_url="http://localhost:8001/v1"))
        self.assertTrue(h.uses_endpoint)
        self.assertEqual(h.base_url, "http://localhost:8001/v1")
        self.assertEqual(h.provider, "benchkit")
        self.assertEqual(_offline_describe(h)["source"], "endpoint")

    def test_every_harness_takes_the_same_endpoint_kwarg(self):
        """--endpoint is one contract, not three: cli.py passes it blindly."""
        for name in HARNESSES:
            with self.subTest(harness=name):
                h = get(name, HarnessConfig(model="m", base_url="http://x/v1"))
                self.assertTrue(h.uses_endpoint)
                self.assertEqual(_offline_describe(h)["source"], "endpoint")

    def test_opencode_injects_config_only_for_an_endpoint(self):
        h = get("opencode", HarnessConfig(provider="ollama", model="m"))
        self.assertNotIn("provider", str(h.describe().get("base_url") or ""))
        self.assertEqual(h.model_spec, "ollama/m")
        e = get("opencode", HarnessConfig(model="m", base_url="http://x/v1"))
        self.assertEqual(e.provider, "benchkit")
        self.assertIn("http://x/v1", e._config()["provider"]["benchkit"]
                      ["options"]["baseURL"])


if __name__ == "__main__":
    unittest.main()
