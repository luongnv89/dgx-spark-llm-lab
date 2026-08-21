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

from aiohttp import ClientSession, ClientTimeout, web

LISTEN_HOST = os.environ.get("ROUTER_HOST") or "127.0.0.1"
LISTEN_PORT = int(os.environ.get("ROUTER_PORT", "8001"))
ROUTER_TOKEN = os.environ.get("ROUTER_TOKEN", "")


def _is_loopback(host: str) -> bool:
    """Return True when *host* resolves to a loopback address."""
    return host in ("127.0.0.1", "::1", "localhost")


async def _auth_middleware(request: web.Request, handler) -> web.Response:
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
_discover_lock = asyncio.Lock()


async def discover(session: ClientSession, force: bool = False) -> None:
    """Ask each backend which model ids it serves."""
    async with _discover_lock:
        if _discovered and not force:
            return
        found: dict[str, str] = {}
        for name, base in BACKENDS.items():
            try:
                async with session.get(f"{base}/v1/models") as r:
                    if r.status != 200:
                        continue
                    body = await r.json()
                    for m in body.get("data", []):
                        if m.get("id"):
                            found[m["id"]] = base
            except Exception as e:
                log.warning("discover %s (%s) failed: %s", name, base, e)
        if found:
            _discovered.clear()
            _discovered.update(found)


def resolve(model: str) -> str | None:
    if model in BACKENDS:
        return BACKENDS[model]
    return _discovered.get(model)


def known_models() -> list[str]:
    return sorted(set(BACKENDS) | set(_discovered))


async def handle_models(request: web.Request) -> web.Response:
    session: ClientSession = request.app["session"]
    await discover(session, force=True)
    data = []
    seen = set()
    for base in dict.fromkeys(BACKENDS.values()):
        try:
            async with session.get(f"{base}/v1/models") as r:
                if r.status != 200:
                    continue
                for m in (await r.json()).get("data", []):
                    if m.get("id") and m["id"] not in seen:
                        seen.add(m["id"])
                        data.append(m)
        except Exception as e:
            log.warning("models from %s failed: %s", base, e)
    return web.json_response({"object": "list", "data": data})


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
    raw = await request.read()
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

    base = resolve(model)
    if base is None:
        await discover(session, force=True)
        base = resolve(model)
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


def main() -> None:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    app = web.Application(client_max_size=1024 ** 3, middlewares=[_auth_middleware])
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
    mode = "loopback (no auth)" if _is_loopback(LISTEN_HOST) else "non-loopback"
    if ROUTER_TOKEN:
        mode += " + bearer token required"
    log.info("router listening on %s:%s [%s]", LISTEN_HOST, LISTEN_PORT, mode)
    web.run_app(app, host=LISTEN_HOST, port=LISTEN_PORT, access_log=None)


if __name__ == "__main__":
    main()
