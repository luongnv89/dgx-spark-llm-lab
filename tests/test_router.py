"""Tests for router.py — loopback default, bearer-token auth, and dispatch.

Covers issue #16: Bind the router to loopback by default.
- LISTEN_HOST defaults to 127.0.0.1
- Non-loopback bind requires ROUTER_TOKEN bearer auth, returns 401 without it
- Loopback binds stay open (no auth required)
- When ROUTER_TOKEN is empty, auth is disabled regardless of bind

Covers issue #39: Bound the router request buffering.
- CLIENT_MAX_SIZE derives from the pinned 262144-token context (~4 MiB)
- Bodies over the limit return 413 without being forwarded
- A max-context-sized prompt still routes end to end

Covers issue #40: Stop the router rediscovering on every call.
- One GET /v1/models costs exactly one upstream call per backend
- Repeat requests are served from the TTL cache
- Unknown-model retries trigger at most one re-discovery per TTL
"""
import asyncio
import importlib
import json
import os
import sys
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from aiohttp import web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

import router  # noqa: E402


class TestDefaultListenHost(unittest.TestCase):
    """Issue #16: LISTEN_HOST defaults to loopback."""

    def test_default_is_loopback(self):
        # When ROUTER_HOST is not set, default must be 127.0.0.1
        with patch.dict(os.environ, {"ROUTER_HOST": "", "ROUTER_TOKEN": ""}, clear=False):
            import importlib
            importlib.reload(router)
            self.assertEqual(router.LISTEN_HOST, "127.0.0.1")

    def test_can_override_host(self):
        with patch.dict(os.environ, {"ROUTER_HOST": "0.0.0.0", "ROUTER_TOKEN": ""}):
            import importlib
            importlib.reload(router)
            self.assertEqual(router.LISTEN_HOST, "0.0.0.0")


class TestIsLoopback(unittest.TestCase):
    """Helper: _is_loopback correctly classifies addresses."""

    def test_loopback_addresses(self):
        self.assertTrue(router._is_loopback("127.0.0.1"))
        self.assertTrue(router._is_loopback("::1"))
        self.assertTrue(router._is_loopback("localhost"))

    def test_non_loopback_addresses(self):
        self.assertFalse(router._is_loopback("0.0.0.0"))
        self.assertFalse(router._is_loopback("192.168.1.1"))
        self.assertFalse(router._is_loopback("10.0.0.1"))


class TestAuthMiddleware(unittest.TestCase):
    """Bearer-token auth when non-loopback + ROUTER_TOKEN is set.

    The middleware is aiohttp's version-1 style (@web.middleware): callable
    as (request, handler) directly, which is also how the tests invoke it.
    """

    def test_middleware_is_registered_version_one_style(self):
        import inspect
        self.assertTrue(inspect.iscoroutinefunction(router._auth_middleware))
        self.assertEqual(getattr(router._auth_middleware,
                                 "__middleware_version__", None), 1)

    def _make_request(self, auth_header=""):
        """Create a mock aiohttp web.Request."""
        request = MagicMock()
        if auth_header:
            request.headers.get = lambda k, d="": f"Bearer {auth_header}" if k == "Authorization" else d
        else:
            request.headers.get = lambda k, d="": d
        request.path = "/v1/chat/completions"
        request.method = "POST"
        request.read = AsyncMock(return_value=b'{}')
        return request

    def test_non_loopback_no_token_returns_401(self):
        """When bound non-loopback with a token, no auth → 401."""
        with patch.dict(os.environ, {"ROUTER_HOST": "0.0.0.0", "ROUTER_TOKEN": "secret"}):
            importlib.reload(router)

            request = self._make_request(auth_header="")

            async def handler(r):
                return MagicMock(status=200)

            async def run():
                return await router._auth_middleware(request, handler)

            result = asyncio.get_event_loop().run_until_complete(run())
            self.assertEqual(result.status, 401)

    def test_non_loopback_correct_token_passes(self):
        """When bound non-loopback with correct token, auth passes."""
        with patch.dict(os.environ, {"ROUTER_HOST": "0.0.0.0", "ROUTER_TOKEN": "secret"}):
            importlib.reload(router)

            request = self._make_request(auth_header="secret")

            async def handler(r):
                return MagicMock(status=200)

            async def run():
                return await router._auth_middleware(request, handler)

            result = asyncio.get_event_loop().run_until_complete(run())
            self.assertEqual(result.status, 200)

    def test_non_loopback_wrong_token_returns_401(self):
        """Wrong token → 401."""
        with patch.dict(os.environ, {"ROUTER_HOST": "0.0.0.0", "ROUTER_TOKEN": "secret"}):
            importlib.reload(router)

            request = self._make_request(auth_header="wrong")

            async def handler(r):
                return MagicMock(status=200)

            async def run():
                return await router._auth_middleware(request, handler)

            result = asyncio.get_event_loop().run_until_complete(run())
            self.assertEqual(result.status, 401)

    def test_loopback_no_auth_required(self):
        """Loopback bind: auth is skipped entirely."""
        with patch.dict(os.environ, {"ROUTER_HOST": "127.0.0.1", "ROUTER_TOKEN": "secret"}):
            importlib.reload(router)

            request = self._make_request(auth_header="")

            handler_resp = MagicMock(status=200)

            async def handler(r):
                return handler_resp

            async def run():
                return await router._auth_middleware(request, handler)

            result = asyncio.get_event_loop().run_until_complete(run())
            # Handler should have been called (no 401)
            self.assertEqual(result, handler_resp)

    def test_no_token_configured_opens_all(self):
        """When ROUTER_TOKEN is empty, auth is disabled regardless of bind."""
        with patch.dict(os.environ, {"ROUTER_HOST": "0.0.0.0", "ROUTER_TOKEN": ""}):
            importlib.reload(router)

            request = self._make_request(auth_header="")

            handler_resp = MagicMock(status=200)

            async def handler(r):
                return handler_resp

            async def run():
                return await router._auth_middleware(request, handler)

            result = asyncio.get_event_loop().run_until_complete(run())
            self.assertEqual(result, handler_resp)


class TestResolveAndKnownModels(unittest.TestCase):
    """Basic dispatch tests."""

    def test_resolve_explicit_backend(self):
        with patch.dict(os.environ, {"ROUTER_HOST": "", "ROUTER_TOKEN": ""}, clear=False):
            import importlib
            importlib.reload(router)
            self.assertEqual(router.resolve("montimage-dgx-spark"), "http://127.0.0.1:8801")

    def test_resolve_unknown(self):
        with patch.dict(os.environ, {"ROUTER_HOST": "", "ROUTER_TOKEN": ""}, clear=False):
            import importlib
            importlib.reload(router)
            self.assertIsNone(router.resolve("unknown-model"))

    def test_known_models_includes_explicit(self):
        with patch.dict(os.environ, {"ROUTER_HOST": "", "ROUTER_TOKEN": ""}, clear=False):
            import importlib
            importlib.reload(router)
            models = router.known_models()
            self.assertIn("montimage-dgx-spark", models)


class TestClientMaxSize(unittest.TestCase):
    """Issue #39: request bodies are bounded by a documented ceiling."""

    def test_ceiling_derives_from_pinned_context(self):
        """262144 tokens (start-qwen.sh --max-model-len) x 16 B/token = 4 MiB."""
        self.assertEqual(router.MAX_MODEL_LEN_TOKENS, 262_144)
        self.assertEqual(router.CLIENT_MAX_SIZE, 262_144 * 16)
        self.assertEqual(router.CLIENT_MAX_SIZE, 4 * 1024 * 1024)

    def test_ceiling_is_far_below_the_old_one_gib(self):
        self.assertLess(router.CLIENT_MAX_SIZE, 1024 ** 3)

    def test_create_app_applies_the_ceiling(self):
        app = router.create_app()
        self.assertEqual(app._client_max_size, router.CLIENT_MAX_SIZE)


class TestProxyOversizedBody(unittest.IsolatedAsyncioTestCase):
    """Issue #39: an over-ceiling body returns 413 instead of being buffered."""

    async def test_read_too_large_returns_413_json(self):
        request = MagicMock()
        request.read = AsyncMock(
            side_effect=router.web.HTTPRequestEntityTooLarge(
                router.CLIENT_MAX_SIZE, router.CLIENT_MAX_SIZE + 1))

        resp = await router.proxy(request)
        self.assertEqual(resp.status, 413)
        body = json.loads(resp.body)
        self.assertEqual(body["error"]["code"], "request_too_large")
        # nothing past the read was touched
        request.read.assert_awaited_once()


def _reset_discovery_state():
    router._discovered.clear()
    router._models_cache = []
    router._discovered_at = float("-inf")
    router._unknown_attempts.clear()


class _FakeResp:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self):
        return self.payload


class _FakeSession:
    """Counts /v1/models GETs and answers from a base -> payload map."""

    def __init__(self, payloads_by_url):
        self.payloads_by_url = payloads_by_url
        self.calls: list[str] = []

    def get(self, url):
        self.calls.append(url)
        return _FakeResp(self.payloads_by_url.get(url, {"data": []}))


class TestDiscoveryCache(unittest.IsolatedAsyncioTestCase):
    """Issue #40 (F-PERF-003): one upstream call per backend, TTL-cached."""

    def setUp(self):
        with patch.dict(os.environ,
                        {"ROUTER_HOST": "127.0.0.1", "ROUTER_TOKEN": ""}):
            importlib.reload(router)
        _reset_discovery_state()

    def tearDown(self):
        _reset_discovery_state()

    @staticmethod
    def _session(payloads=None):
        return _FakeSession(payloads or {})

    def _two_backend_session(self):
        payloads = {
            "http://b1:8801/v1/models":
                {"data": [{"id": "montimage-dgx-spark"}, {"id": "shared"}]},
            "http://b2:8802/v1/models":
                {"data": [{"id": "gemma4-12b"}, {"id": "shared"}]},
        }
        session = _FakeSession(payloads)
        router.BACKENDS.clear()
        router.BACKENDS.update({"a": "http://b1:8801", "b": "http://b2:8802"})
        self.addCleanup(lambda: (router.BACKENDS.clear(),
                                 router.BACKENDS.update(
                                     {"montimage-dgx-spark": "http://127.0.0.1:8801"})))
        return session

    async def test_one_pass_per_distinct_backend_dedupes_shared_ids(self):
        session = self._two_backend_session()
        await router.discover(session)
        models_called = [u for u in session.calls if u.endswith("/v1/models")]
        self.assertEqual(len(models_called), 2)  # one per backend, not one per alias
        self.assertEqual(sorted(router._discovered),
                         ["gemma4-12b", "montimage-dgx-spark", "shared"])
        ids = [m["id"] for m in router._models_cache]
        self.assertEqual(len(ids), len(set(ids)))  # merged listing is deduped

    async def test_repeat_discovers_within_ttl_cost_nothing(self):
        session = self._two_backend_session()
        await router.discover(session)
        await router.discover(session)
        await router.discover(session)
        self.assertEqual(len(session.calls), 2)

    async def test_force_bypasses_the_ttl(self):
        session = self._two_backend_session()
        await router.discover(session)
        await router.discover(session, force=True)
        self.assertEqual(len(session.calls), 4)

    async def test_concurrent_discovers_share_one_pass(self):
        session = self._two_backend_session()
        await asyncio.gather(router.discover(session), router.discover(session))
        self.assertEqual(len(session.calls), 2)

    async def test_failed_discovery_retried_only_after_ttl(self):
        router.BACKENDS.clear()
        router.BACKENDS.update({"a": "http://dead:9/v1"})
        self.addCleanup(lambda: (router.BACKENDS.clear(),
                                 router.BACKENDS.update(
                                     {"montimage-dgx-spark": "http://127.0.0.1:8801"})))
        session = _FakeSession({})  # every fetch returns no models
        await router.discover(session)
        await router.discover(session)
        self.assertEqual(len(session.calls), 1)  # empty result still counts as fresh
        router._discovered_at = time.monotonic() - router.DISCOVERY_TTL_SECONDS - 1
        await router.discover(session)
        self.assertEqual(len(session.calls), 2)


class TestUnknownModelNegativeCache(unittest.IsolatedAsyncioTestCase):
    """Issue #40 (F-PERF-004): unknown-model retries do not hammer backends."""

    def setUp(self):
        with patch.dict(os.environ,
                        {"ROUTER_HOST": "127.0.0.1", "ROUTER_TOKEN": ""}):
            importlib.reload(router)
        _reset_discovery_state()

    def tearDown(self):
        _reset_discovery_state()

    async def test_unknown_model_on_fresh_listing_costs_no_fetch(self):
        router._discovered.update({"known": "http://b:1"})
        router._discovered_at = time.monotonic()
        fetcher = AsyncMock(return_value=({}, []))
        with patch.object(router, "_fetch_backends", fetcher):
            base = await router.resolve_or_refresh(MagicMock(), "nope")
        self.assertIsNone(base)
        fetcher.assert_not_awaited()

    async def test_retry_loop_triggers_exactly_one_rediscovery(self):
        fetcher = AsyncMock(return_value=({}, []))  # never finds it
        with patch.object(router, "_fetch_backends", fetcher):
            for _ in range(5):
                base = await router.resolve_or_refresh(MagicMock(), "bogus")
                self.assertIsNone(base)
        self.assertEqual(fetcher.await_count, 1)

    async def test_same_name_rediscovered_after_ttl_expires(self):
        fetcher = AsyncMock(return_value=({}, []))
        with patch.object(router, "_fetch_backends", fetcher):
            await router.resolve_or_refresh(MagicMock(), "bogus")
            router._unknown_attempts["bogus"] -= (
                router.UNKNOWN_MODEL_TTL_SECONDS + 1)
            router._discovered_at = float("-inf")
            await router.resolve_or_refresh(MagicMock(), "bogus")
        self.assertEqual(fetcher.await_count, 2)

    async def test_distinct_unknown_names_share_one_freshness_window(self):
        # the first unknown name pays for a refresh; until DISCOVERY_TTL
        # expires, further distinct names are answered from that fresh
        # listing without touching any backend — a retry loop cycling
        # thousands of bogus names costs at most one pass per TTL
        fetcher = AsyncMock(return_value=({}, []))
        with patch.object(router, "_fetch_backends", fetcher):
            for name in ("a", "b", "c"):
                base = await router.resolve_or_refresh(MagicMock(), name)
                self.assertIsNone(base)
        self.assertEqual(fetcher.await_count, 1)

    async def test_attempt_table_is_pruned_when_huge(self):
        stale_ts = time.monotonic() - router.UNKNOWN_MODEL_TTL_SECONDS - 1
        for i in range(router._UNKNOWN_ATTEMPTS_MAX + 10):
            router._unknown_attempts[f"stale{i}"] = stale_ts
        fetcher = AsyncMock(return_value=({}, []))
        with patch.object(router, "_fetch_backends", fetcher):
            await router.resolve_or_refresh(MagicMock(), "fresh-name")
        self.assertLessEqual(len(router._unknown_attempts),
                             router._UNKNOWN_ATTEMPTS_MAX)


class TestRouterEndToEnd(unittest.IsolatedAsyncioTestCase):
    """Integration: real aiohttp servers for the router and its backends.

    Issue #39: oversized -> 413, max-context prompt routes end to end.
    Issue #40: exactly one upstream /v1/models call per backend; the
    unknown-model retry loop triggers at most one re-discovery per TTL.
    """

    def _make_backend(self, model_ids):
        counter = {"models": 0, "chat": 0}
        last_body = {}

        async def models(request):
            counter["models"] += 1
            data = [{"id": mid, "object": "model"} for mid in model_ids]
            return web.json_response({"object": "list", "data": data})

        async def chat(request):
            counter["chat"] += 1
            last_body["raw"] = await request.read()
            return web.json_response({"received_bytes": len(last_body["raw"])})

        app = web.Application(client_max_size=1024 ** 3)
        app.router.add_get("/v1/models", models)
        app.router.add_post("/v1/chat/completions", chat)
        return app, counter, last_body

    def _install_backends(self, primary, secondary):
        router.BACKENDS.clear()
        router.BACKENDS.update({
            "montimage-dgx-spark": str(primary.make_url("")).rstrip("/"),
            "gemma4-12b": str(secondary.make_url("")).rstrip("/"),
        })

        def restore():
            router.BACKENDS.clear()
            router.BACKENDS.update(
                {"montimage-dgx-spark": "http://127.0.0.1:8801"})

        self.addCleanup(restore)

    async def asyncSetUp(self):
        with patch.dict(os.environ,
                        {"ROUTER_HOST": "127.0.0.1", "ROUTER_TOKEN": ""}):
            importlib.reload(router)

        self.primary_app, self.primary_calls, self.primary_last = \
            self._make_backend(["montimage-dgx-spark"])
        self.secondary_app, self.secondary_calls, _ = \
            self._make_backend(["gemma4-12b", "shared-alias"])
        self.primary = TestServer(self.primary_app)
        self.secondary = TestServer(self.secondary_app)
        await self.primary.start_server()
        await self.secondary.start_server()
        self.addCleanup(self.primary.close)
        self.addCleanup(self.secondary.close)

        self._install_backends(self.primary, self.secondary)
        _reset_discovery_state()

        self.server = TestServer(router.create_app())
        await self.server.start_server()
        self.client = TestClient(self.server)
        self.addCleanup(self.client.close)
        # ignore the warm-up discovery the router performed during startup:
        # assertions below must count only test-driven upstream traffic
        self.primary_calls["models"] = 0
        self.secondary_calls["models"] = 0

    async def test_models_get_costs_exactly_one_upstream_call_per_backend(self):
        # expire whatever the router fetched during startup so this GET
        # demonstrably pays for its own discovery pass
        router._discovered_at = float("-inf")
        async with self.client.get("/v1/models") as r:
            self.assertEqual(r.status, 200)
            body = await r.json()
        ids = {m["id"] for m in body["data"]}
        self.assertIn("montimage-dgx-spark", ids)
        self.assertIn("gemma4-12b", ids)
        self.assertIn("shared-alias", ids)
        self.assertEqual(len(body["data"]), 3)  # deduped across backends
        self.assertEqual(self.primary_calls["models"], 1)
        self.assertEqual(self.secondary_calls["models"], 1)

    async def test_second_models_get_within_ttl_touches_no_backend(self):
        router._discovered_at = float("-inf")
        async with self.client.get("/v1/models"):
            pass
        async with self.client.get("/v1/models"):
            pass
        self.assertEqual(self.primary_calls["models"], 1)
        self.assertEqual(self.secondary_calls["models"], 1)

    async def test_unknown_model_retry_loop_rediscovers_at_most_once(self):
        _reset_discovery_state()  # ignore the warm-up pass from startup
        payload = {"model": "does-not-exist", "messages": []}
        for _ in range(5):
            async with self.client.post("/v1/chat/completions",
                                        json=payload) as r:
                self.assertEqual(r.status, 404)
        # cold cache: first POST pays one discovery pass; the rest are negative-cache hits
        self.assertEqual(self.primary_calls["models"], 1)
        self.assertEqual(self.secondary_calls["models"], 1)

    async def test_unknown_model_rediscovered_after_ttl(self):
        _reset_discovery_state()
        payload = {"model": "does-not-exist", "messages": []}
        async with self.client.post("/v1/chat/completions", json=payload) as r:
            self.assertEqual(r.status, 404)
        age = router.UNKNOWN_MODEL_TTL_SECONDS + 1
        router._unknown_attempts["does-not-exist"] -= age
        router._discovered_at -= age
        async with self.client.post("/v1/chat/completions", json=payload) as r:
            self.assertEqual(r.status, 404)
        self.assertEqual(self.primary_calls["models"], 2)
        self.assertEqual(self.secondary_calls["models"], 2)

    async def test_known_alias_still_routes_after_cold_start(self):
        _reset_discovery_state()
        payload = {"model": "montimage-dgx-spark",
                   "messages": [{"role": "user", "content": "hi"}]}
        async with self.client.post("/v1/chat/completions",
                                    json=payload) as r:
            self.assertEqual(r.status, 200)
            body = await r.json()
        self.assertEqual(self.primary_calls["chat"], 1)
        self.assertEqual(body["received_bytes"],
                         len(json.dumps(payload).encode()))

    async def test_oversized_body_returns_413_without_touching_backend(self):
        too_big = "A" * (router.CLIENT_MAX_SIZE + 1)
        payload = {"model": "montimage-dgx-spark",
                   "messages": [{"role": "user", "content": too_big}]}
        async with self.client.post("/v1/chat/completions",
                                    json=payload) as r:
            self.assertEqual(r.status, 413)
            body = await r.json()
        self.assertEqual(body["error"]["code"], "request_too_large")
        self.assertEqual(self.primary_calls["chat"], 0)
        self.assertEqual(self.secondary_calls["chat"], 0)

    async def test_max_context_prompt_routes_end_to_end(self):
        # ~300k tokens of prose (~1.8 MB): above the served context window's
        # 256k-token mark yet comfortably under the 4 MiB ceiling.
        content = "token " * 300_000
        payload = {"model": "montimage-dgx-spark",
                   "messages": [{"role": "user", "content": content}]}
        raw = json.dumps(payload).encode()
        self.assertLess(len(raw), router.CLIENT_MAX_SIZE)
        async with self.client.post("/v1/chat/completions", data=raw,
                                    headers={"Content-Type":
                                             "application/json"}) as r:
            self.assertEqual(r.status, 200)
            body = await r.json()
        self.assertEqual(body["received_bytes"], len(raw))
        self.assertEqual(self.primary_calls["chat"], 1)


if __name__ == "__main__":
    unittest.main()
