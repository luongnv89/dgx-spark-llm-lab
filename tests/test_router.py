"""Tests for router.py — loopback default, bearer-token auth, and dispatch.

Covers issue #16: Bind the router to loopback by default.
- LISTEN_HOST defaults to 127.0.0.1
- Non-loopback bind requires ROUTER_TOKEN bearer auth, returns 401 without it
- Loopback binds stay open (no auth required)
- When ROUTER_TOKEN is empty, auth is disabled regardless of bind
"""
import asyncio
import os
import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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
    """Bearer-token auth when non-loopback + ROUTER_TOKEN is set."""

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
            import importlib
            importlib.reload(router)

            request = self._make_request(auth_header="")

            async def handler(r):
                return MagicMock(status=200)

            async def run():
                middleware = router._auth_middleware
                result = await middleware(request, handler)
                return result

            result = asyncio.get_event_loop().run_until_complete(run())
            self.assertEqual(result.status, 401)

    def test_non_loopback_correct_token_passes(self):
        """When bound non-loopback with correct token, auth passes."""
        with patch.dict(os.environ, {"ROUTER_HOST": "0.0.0.0", "ROUTER_TOKEN": "secret"}):
            import importlib
            importlib.reload(router)

            request = self._make_request(auth_header="secret")

            async def handler(r):
                return MagicMock(status=200)

            async def run():
                middleware = router._auth_middleware
                result = await middleware(request, handler)
                return result

            result = asyncio.get_event_loop().run_until_complete(run())
            self.assertEqual(result.status, 200)

    def test_non_loopback_wrong_token_returns_401(self):
        """Wrong token → 401."""
        with patch.dict(os.environ, {"ROUTER_HOST": "0.0.0.0", "ROUTER_TOKEN": "secret"}):
            import importlib
            importlib.reload(router)

            request = self._make_request(auth_header="wrong")

            async def handler(r):
                return MagicMock(status=200)

            async def run():
                middleware = router._auth_middleware
                result = await middleware(request, handler)
                return result

            result = asyncio.get_event_loop().run_until_complete(run())
            self.assertEqual(result.status, 401)

    def test_loopback_no_auth_required(self):
        """Loopback bind: auth is skipped entirely."""
        with patch.dict(os.environ, {"ROUTER_HOST": "127.0.0.1", "ROUTER_TOKEN": "secret"}):
            import importlib
            importlib.reload(router)

            request = self._make_request(auth_header="")

            handler_resp = MagicMock(status=200)

            async def handler(r):
                return handler_resp

            async def run():
                middleware = router._auth_middleware
                result = await middleware(request, handler)
                return result

            result = asyncio.get_event_loop().run_until_complete(run())
            # Handler should have been called (no 401)
            self.assertEqual(result, handler_resp)

    def test_no_token_configured_opens_all(self):
        """When ROUTER_TOKEN is empty, auth is disabled regardless of bind."""
        with patch.dict(os.environ, {"ROUTER_HOST": "0.0.0.0", "ROUTER_TOKEN": ""}):
            import importlib
            importlib.reload(router)

            request = self._make_request(auth_header="")

            handler_resp = MagicMock(status=200)

            async def handler(r):
                return handler_resp

            async def run():
                middleware = router._auth_middleware
                result = await middleware(request, handler)
                return result

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


if __name__ == "__main__":
    unittest.main()
