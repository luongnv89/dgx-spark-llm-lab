"""Tests for the pi harness's explicit-endpoint mode.

The promise being tested is narrow and load-bearing: `--endpoint` must let pi
benchmark a server that is not in the user's catalogue, and it must do that
*without* the run ever writing to the user's own pi configuration. Copy out,
never write back — so the tests below check both halves, and the non-mutation
half is checked byte-for-byte rather than by inspection.
"""
import json
import os
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from benchkit.harness import get  # noqa: E402
from benchkit.harness.pi import (  # noqa: E402
    CATALOGUE_NAME,
    DEFAULT_ENDPOINT_PROVIDER,
    STAGED_AGENT_DIR,
)

ENDPOINT = "http://localhost:8001/v1"

#: a stand-in for ~/.pi/agent/models.json, with the user's own provider in it
USER_CATALOGUE = {
    "providers": {
        "local-dgx": {
            "baseUrl": "http://localhost:9999/v1",
            "api": "openai-completions",
            "apiKey": "secret-of-the-user",
            "models": [{"id": "montimage-dgx-spark", "name": "DGX"}],
        }
    }
}


class PiEndpointCase(unittest.TestCase):
    """A fake pi agent directory plus a fresh run container for each test."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.agent_dir = os.path.join(self.tmp.name, "pi-agent-home")
        os.makedirs(self.agent_dir)
        self.catalogue = os.path.join(self.agent_dir, CATALOGUE_NAME)
        with open(self.catalogue, "w") as f:
            json.dump(USER_CATALOGUE, f, indent=2)
        with open(self.catalogue, "rb") as f:
            self.before = f.read()
        self.container = os.path.join(self.tmp.name, "container")
        os.makedirs(self.container)

    def harness(self, **kw):
        kw.setdefault("agent_dir", self.agent_dir)
        return get("pi", **kw)

    def staged(self):
        return os.path.join(self.container, STAGED_AGENT_DIR, CATALOGUE_NAME)

    def assert_user_config_untouched(self):
        with open(self.catalogue, "rb") as f:
            self.assertEqual(f.read(), self.before,
                             "the user's pi catalogue was modified by the run")

    def read_json(self, path):
        with open(path) as f:
            return json.load(f)


class TestEndpointStaging(PiEndpointCase):
    def test_prepare_writes_the_endpoint_provider_into_a_copy(self):
        h = self.harness(model="served-model", base_url=ENDPOINT)
        workdir = h.prepare(self.container)

        catalogue = self.read_json(self.staged())
        provider = catalogue["providers"][DEFAULT_ENDPOINT_PROVIDER]
        self.assertEqual(provider["baseUrl"], ENDPOINT)
        self.assertEqual(provider["api"], "openai-completions")
        self.assertEqual([m["id"] for m in provider["models"]], ["served-model"])
        # the workspace that gets scored must not contain pi's plumbing
        self.assertTrue(workdir.startswith(self.container))
        self.assertNotEqual(os.path.dirname(self.staged()), workdir)

    def test_the_users_own_providers_survive_in_the_copy(self):
        """Copying, not replacing: their providers stay reachable in the run."""
        h = self.harness(model="served-model", base_url=ENDPOINT)
        h.prepare(self.container)
        providers = self.read_json(self.staged())["providers"]
        self.assertIn("local-dgx", providers)
        self.assertIn(DEFAULT_ENDPOINT_PROVIDER, providers)

    def test_the_users_catalogue_is_never_written(self):
        """The whole reason pi refused an endpoint before: prove it is safe."""
        h = self.harness(model="served-model", base_url=ENDPOINT)
        h.prepare(self.container)
        self.assert_user_config_untouched()

    def test_the_subprocess_is_pointed_at_the_copy(self):
        h = self.harness(model="served-model", base_url=ENDPOINT)
        h.prepare(self.container)
        env = h._env()
        self.assertEqual(env["PI_CODING_AGENT_DIR"],
                         os.path.join(self.container, STAGED_AGENT_DIR))
        self.assertNotEqual(env["PI_CODING_AGENT_DIR"], self.agent_dir)

    def test_the_injected_provider_is_addressable(self):
        """`--provider benchkit` is only passed if pi would accept it."""
        h = self.harness(model="served-model", base_url=ENDPOINT)
        h.prepare(self.container)
        self.assertTrue(h._provider_addressable())
        argv = h._argv("do the thing", thinking=False)
        self.assertIn("--provider", argv)
        self.assertEqual(argv[argv.index("--provider") + 1],
                         DEFAULT_ENDPOINT_PROVIDER)
        self.assertEqual(argv[argv.index("--model") + 1], "served-model")

    def test_a_missing_user_catalogue_is_not_an_error(self):
        """Endpoint mode must work on a machine with no pi config at all."""
        empty = os.path.join(self.tmp.name, "nothing-here")
        os.makedirs(empty)
        h = get("pi", model="served-model", base_url=ENDPOINT, agent_dir=empty)
        h.prepare(self.container)
        providers = self.read_json(self.staged())["providers"]
        self.assertEqual(list(providers), [DEFAULT_ENDPOINT_PROVIDER])
        self.assertFalse(os.path.exists(os.path.join(empty, CATALOGUE_NAME)))

    def test_an_explicit_api_key_reaches_the_staged_provider(self):
        h = self.harness(model="served-model", base_url=ENDPOINT, api_key="k")
        h.prepare(self.container)
        providers = self.read_json(self.staged())["providers"]
        self.assertEqual(providers[DEFAULT_ENDPOINT_PROVIDER]["apiKey"], "k")


class TestWithoutAnEndpoint(PiEndpointCase):
    """No --endpoint means nothing is staged and nothing is redirected."""

    def test_prepare_stages_nothing(self):
        h = self.harness(provider="local-dgx", model="montimage-dgx-spark")
        workdir = h.prepare(self.container)
        self.assertEqual(workdir, self.container)
        self.assertFalse(os.path.exists(
            os.path.join(self.container, STAGED_AGENT_DIR)))
        self.assert_user_config_untouched()

    def test_the_users_own_agent_dir_is_still_used(self):
        h = self.harness(provider="local-dgx", model="montimage-dgx-spark")
        h.prepare(self.container)
        self.assertEqual(h.agent_dir, self.agent_dir)
        self.assertEqual(h._env()["PI_CODING_AGENT_DIR"], self.agent_dir)
        self.assertEqual(h._catalogue_path(), self.catalogue)

    def test_the_users_catalogue_still_resolves_the_model(self):
        h = self.harness(provider="local-dgx", model="montimage-dgx-spark")
        self.assertEqual(h._catalogue_models(),
                         [("local-dgx", "montimage-dgx-spark")])
        self.assertFalse(h.uses_endpoint)
        self.assertIsNone(h.base_url)


class _ModelsHandler(BaseHTTPRequestHandler):
    """The one route `available()` needs: an OpenAI-compatible /v1/models."""

    served = ["served-model"]

    def do_GET(self):  # noqa: N802 — BaseHTTPRequestHandler's name
        body = json.dumps({"data": [{"id": i} for i in self.served]}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):  # keep the test output clean
        pass


class TestEndpointAvailability(PiEndpointCase):
    """In endpoint mode the endpoint answers, not the catalogue.

    Backed by a stub server rather than a real one: the point is the branch
    taken, and a benchmark's unit tests must not depend on what happens to be
    serving on this machine.
    """

    def setUp(self):
        super().setUp()
        self.server = HTTPServer(("127.0.0.1", 0), _ModelsHandler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/v1"

    def test_a_served_model_is_accepted(self):
        h = self.harness(model="served-model", base_url=self.url)
        ok, detail = h.available()
        self.assertTrue(ok, detail)
        self.assertIn(self.url, detail)

    def test_a_model_the_endpoint_does_not_serve_is_named(self):
        h = self.harness(model="not-there", base_url=self.url)
        ok, detail = h.available()
        self.assertFalse(ok)
        self.assertIn("not-there", detail)
        self.assertIn("served-model", detail)

    def test_the_catalogue_is_not_consulted_in_endpoint_mode(self):
        """`local-dgx/montimage-dgx-spark` is in the fixture and irrelevant here."""
        h = self.harness(model="montimage-dgx-spark", base_url=self.url)
        ok, detail = h.available()
        self.assertFalse(ok, "the user's catalogue must not vouch for an endpoint")
        self.assertIn("not served at", detail)

    def test_an_unreachable_endpoint_says_so(self):
        h = self.harness(model="served-model", base_url="http://127.0.0.1:1/v1")
        ok, detail = h.available()
        self.assertFalse(ok)
        self.assertIn("unreachable", detail)

    def test_endpoint_mode_enumerates_nothing(self):
        """The injected provider exists for one run; there is no list to show."""
        h = self.harness(model="served-model", base_url=self.url)
        self.assertEqual(h.list_models(), [])


if __name__ == "__main__":
    unittest.main()
