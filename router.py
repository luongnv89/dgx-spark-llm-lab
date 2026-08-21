#!/usr/bin/env python3
"""Minimal OpenAI-compatible router for multiple local vLLM backends.

vLLM serves exactly one model per process, but clients must keep using a
single endpoint (port 8001) and the stable alias `montimage-dgx-spark`.
This router dispatches on the request's "model" field and streams responses
back verbatim, so it is transparent to OpenAI-compatible clients.

Backends are declared in BACKENDS below: model name -> upstream base URL.
Any model name a backend reports via /v1/models is also accepted and routed
to that backend, so aliases configured with --served-model-name work too.
"""

import asyncio
import json
import logging
import os
import time

from aiohttp import ClientSession, ClientTimeout, web

LISTEN_HOST = os.environ.get("ROUTER_HOST") or "127.0.0.1"
LISTEN_PORT = int(os.environ.get("ROUTER_PORT", "8001"))
ROUTER_TOKEN = os.environ.get("ROUTER_TOKEN", "")

# Request bodies are capped at MAX_MODEL_LEN_TOKENS * BYTES_PER_TOKEN bytes:
# start-qwen.sh pins --max-model-len 262144, so no servable request can carry
# more than that many tokens, and 16 bytes per token is generous even for
# multi-byte UTF-8 plus JSON \uXXXX escaping and formatting overhead (~4 MiB).
# Anything larger cannot fit the context window anyway, so aiohttp rejects it
# with 413 instead of buffering up to the previous 1 GiB per concurrent
# request (issue #39).
MAX_MODEL_LEN_TOKENS = int(os.environ.get("ROUTER_MAX_MODEL_LEN", "262144"))
BYTES_PER_TOKEN = 16
CLIENT_MAX_SIZE = MAX_MODEL_LEN_TOKENS * BYTES_PER_TOKEN

# Backend /v1/models listings are cached for DISCOVERY_TTL_SECONDS: both the
# routing map and the merged listing come out of one fetch pass (one upstream
# call per backend). A request naming an unknown model may trigger at most one
# extra pass per name per UNKNOWN_MODEL_TTL_SECONDS (negative cache), so a
# misconfigured client in a retry loop cannot hammer every backend (issue #40).
DISCOVERY_TTL_SECONDS = float(os.environ.get("ROUTER_DISCOVERY_TTL", "60"))
UNKNOWN_MODEL_TTL_SECONDS = float(os.environ.get("ROUTER_UNKNOWN_MODEL_TTL", "60"))
_UNKNOWN_ATTEMPTS_MAX = 4096


def _is_loopback(host: str) -> bool:
    """Return True when *host* resolves to a loopback address."""
    return host in ("127.0.0.1", "::1", "localhost")


@web.middleware
async def _auth_middleware(
    request: web.Request,
    handler,
) -> web.StreamResponse:
    """Require a Bearer token when the router is bound non-loopback."""
    if _is_loopback(LISTEN_HOST):
        return await handler(request)
    if not ROUTER_TOKEN:
        return await handler(request)  # no token configured → open (local dev)
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer ") or auth[7:] != ROUTER_TOKEN:
        return web.json_response(
            {"error": {"message": "unauthorized", "type": "unauthorized_error"}},
            status=401,
        )
    return await handler(request)

# model name -> upstream base (no trailing slash), in priority order
BACKENDS = {
    "montimage-dgx-spark": "http://127.0.0.1:8801",
    # "gemma4-12b": "http://127.0.0.1:8802",  # vllm-gemma stopped and disabled
    # 2026-08-17: does not fit alongside Qwen3.8-27B at gmu 0.70. Re-enable the
    # unit and this line together (see README "Memory budget").
}

# /health must stay 200 while the primary model works, even if a secondary
# backend is down. Client preflights (e.g. `curl -fsS .../health` in the `cc`
# launcher) treat any non-2xx as "server is down" and try to start a competing
# server on this port.
PRIMARY_MODEL = "montimage-dgx-spark"

# Long timeout: a 256k-token prefill can legitimately take minutes.
UPSTREAM_TIMEOUT = ClientTimeout(total=None, sock_connect=15, sock_read=1800)

log = logging.getLogger("router")

# discovered at runtime: upstream-reported model id -> backend base
_discovered: dict[str, str] = {}
# merged, deduped /v1/models listing served by handle_models
_models_cache: list[dict] = []
# time.monotonic() of the last discovery pass (successful or not)
_discovered_at: float = float("-inf")
# unknown model name -> time.monotonic() of the last re-discovery it triggered
_unknown_attempts: dict[str, float] = {}
_discover_lock = asyncio.Lock()


async def _fetch_backends(session: ClientSession) -> tuple[dict[str, str], list[dict]]:
    """Fetch /v1/models from every distinct backend exactly once.

    Returns (model id -> backend base, merged deduped model objects).
    """
    found: dict[str, str] = {}
    data: list[dict] = []
    seen: set[str] = set()
    for base in dict.fromkeys(BACKENDS.values()):
        try:
            async with session.get(f"{base}/v1/models") as r:
                if r.status != 200:
                    continue
                for m in (await r.json()).get("data", []):
                    mid = m.get("id")
                    if not mid:
                        continue
                    if mid not in found:
                        found[mid] = base
                    if mid not in seen:
                        seen.add(mid)
                        data.append(m)
        except Exception as e:
            log.warning("discover %s failed: %s", base, e)
    return found, data


async def _discover_locked(session: ClientSession, force: bool = False) -> None:
    """Run at most one backend fetch pass; caller holds _discover_lock."""
    global _models_cache, _discovered_at
    now = time.monotonic()
    # Freshness is tracked by _discovered_at alone: an empty pass (every
    # backend down or still loading) also counts as fresh, so a dead backend
    # is re-polled at most once per TTL instead of on every request.
    if not force and now - _discovered_at < DISCOVERY_TTL_SECONDS:
        return
    found, data = await _fetch_backends(session)
    if found:
        _discovered.clear()
        _discovered.update(found)
        _models_cache = data
    _discovered_at = now


async def discover(session: ClientSession, force: bool = False) -> None:
    """Ask each backend which model ids it serves (TTL-cached)."""
    async with _discover_lock:
        await _discover_locked(session, force)


def resolve(model: str) -> str | None:
    if model in BACKENDS:
        return BACKENDS[model]
    return _discovered.get(model)


def known_models() -> list[str]:
    return sorted(set(BACKENDS) | set(_discovered))


async def resolve_or_refresh(session: ClientSession, model: str) -> str | None:
    """Resolve *model*, re-discovering at most once per name per TTL.

    An unknown model triggers one discovery pass — and only if the cached
    listing is stale; a fresh listing that lacks the name is authoritative.
    Either way the attempt is remembered, so retries of the same unknown
    model cost no upstream traffic until UNKNOWN_MODEL_TTL_SECONDS elapses.
    """
    base = resolve(model)
    if base is not None:
        return base
    async with _discover_lock:
        now = time.monotonic()
        last = _unknown_attempts.get(model, float("-inf"))
        if now - last < UNKNOWN_MODEL_TTL_SECONDS:
            return None  # negative cache hit: recently tried for this name
        _unknown_attempts[model] = now
        if len(_unknown_attempts) > _UNKNOWN_ATTEMPTS_MAX:
            for stale in [k for k, t in _unknown_attempts.items()
                          if t < now - UNKNOWN_MODEL_TTL_SECONDS]:
                del _unknown_attempts[stale]
        if not (_discovered and now - _discovered_at < DISCOVERY_TTL_SECONDS):
            # listing is stale or empty — one refresh attempt (a no-op when
            # another pass just completed under this lock)
            await _discover_locked(session)
    return resolve(model)


async def handle_models(request: web.Request) -> web.Response:
    session: ClientSession = request.app["session"]
    # One TTL-gated discovery pass fills both the routing map and the merged
    # listing; within the TTL this serves from cache with no upstream calls.
    await discover(session)
    return web.json_response({"object": "list", "data": list(_models_cache)})


async def handle_health(request: web.Request) -> web.Response:
    session: ClientSession = request.app["session"]
    status = {}
    for name, base in BACKENDS.items():
        try:
            async with session.get(f"{base}/health") as r:
                status[name] = "ok" if r.status == 200 else f"http {r.status}"
        except Exception as e:
            status[name] = f"down ({type(e).__name__})"
    all_ok = all(v == "ok" for v in status.values())
    primary_ok = status.get(PRIMARY_MODEL) == "ok"
    return web.json_response(
        {"status": "ok" if all_ok else ("degraded" if primary_ok else "down"),
         "backends": status},
        # 200 while the primary serves; only fail the check if it is down.
        status=200 if primary_ok else 503)


async def proxy(request: web.Request) -> web.StreamResponse:
    session: ClientSession = request.app["session"]
    try:
        raw = await request.read()
    except web.HTTPRequestEntityTooLarge:
        # aiohttp enforces CLIENT_MAX_SIZE before buffering; nothing beyond
        # the limit is ever read (issue #39).
        return web.json_response(
            {"error": {"message": f"request body too large; limit is "
                                  f"{CLIENT_MAX_SIZE} bytes",
                       "type": "invalid_request_error",
                       "code": "request_too_large"}},
            status=413)
    try:
        payload = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return web.json_response(
            {"error": {"message": "invalid JSON body", "type": "invalid_request_error"}},
            status=400)

    model = payload.get("model")
    if not model:
        return web.json_response(
            {"error": {"message": "missing 'model'", "type": "invalid_request_error"}},
            status=400)

    base = await resolve_or_refresh(session, model)
    if base is None:
        return web.json_response(
            {"error": {"message": f"unknown model {model!r}; available: "
                                  f"{known_models()}",
                       "type": "invalid_request_error", "code": "model_not_found"}},
            status=404)

    url = f"{base}{request.path}"
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length", "accept-encoding")}

    try:
        async with session.request(request.method, url, data=raw,
                                   headers=headers) as upstream:
            resp = web.StreamResponse(status=upstream.status)
            ctype = upstream.headers.get("Content-Type")
            if ctype:
                resp.content_type = ctype.split(";")[0].strip()
                if "charset=" in ctype:
                    resp.charset = ctype.split("charset=")[1].split(";")[0].strip()
            await resp.prepare(request)
            async for chunk in upstream.content.iter_any():
                await resp.write(chunk)
            await resp.write_eof()
            return resp
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.error("upstream %s failed: %s", url, e)
        return web.json_response(
            {"error": {"message": f"upstream {base} error: {e}",
                       "type": "api_error"}}, status=502)


async def on_start(app: web.Application) -> None:
    app["session"] = ClientSession(timeout=UPSTREAM_TIMEOUT)
    try:
        await discover(app["session"])
        log.info("routing: %s", {m: b for m, b in _discovered.items()})
    except Exception as e:
        log.warning("initial discovery failed (backends may still be loading): %s", e)


async def on_stop(app: web.Application) -> None:
    await app["session"].close()


def create_app() -> web.Application:
    app = web.Application(client_max_size=CLIENT_MAX_SIZE,
                          middlewares=[_auth_middleware])
    app.on_startup.append(on_start)
    app.on_cleanup.append(on_stop)
    app.router.add_get("/v1/models", handle_models)
    app.router.add_get("/health", handle_health)
    # /v1/messages is the Anthropic Messages API, which vLLM implements and
    # Claude Code uses via ANTHROPIC_BASE_URL. Both API styles carry the model
    # name in the body, so the same dispatch works for all of them.
    for path in ("/v1/chat/completions", "/v1/completions",
                 "/v1/embeddings", "/v1/rerank",
                 "/v1/messages", "/v1/messages/count_tokens",
                 "/v1/responses"):
        app.router.add_post(path, proxy)
    return app


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = create_app()
    mode = "loopback (no auth)" if _is_loopback(LISTEN_HOST) else "non-loopback"
    if ROUTER_TOKEN:
        mode += " + bearer token required"
    log.info("router listening on %s:%s [%s]", LISTEN_HOST, LISTEN_PORT, mode)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)


if __name__ == "__main__":
    main()
