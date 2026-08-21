# OpenAI 2.x → 3.x Migration Notes

**Date:** 2026-08-22
**Scope:** Streaming surface (`benchkit/runner.py`) and tool-calling surface (`benchkit/agentic/loop.py`)
**Source:** [openai-python v3.0.0 changelog](https://github.com/openai/openai-python/releases/tag/v3.0.0), [HTTPX2 migration guide](https://github.com/openai/openai-python/blob/main/httpx2.md), SDK type comparison (2.54.0 ↔ 3.3.1)

---

## 1. Breaking changes overview

The **only** breaking change in openai 3.0 is the HTTP client migration:

| Change | Impact on this repo |
|--------|-------------------|
| HTTPX → HTTPX2 as default HTTP client | **No code change needed.** The repo does not configure a custom HTTP client, transport, or event hook. The `OpenAI()` constructor still accepts `base_url` and `api_key` exactly as before. |

All other API surfaces — `chat.completions.create`, streaming, tool calls, `extra_body`, `stream_options`, `tool_choice` — are **unchanged**.

---

## 2. Streaming surface (`benchkit/runner.py:124-141`)

```python
stream = client.chat.completions.create(
    model=cfg.model,
    messages=[...],
    max_tokens=cfg.max_tokens,
    extra_body={"chat_template_kwargs": {...}},
    stream=True, stream_options={"include_usage": True},
)
for ch in stream:
    if ch.usage: ...
    d = ch.choices[0].delta
    reasoning = getattr(d, "reasoning_content", None) or ""
```

| Field | 2.x status | 3.x status | Action needed |
|-------|-----------|-----------|---------------|
| `extra_body` | Supported | Supported — maps to `extra_json` internally in `_base_client.py` | **None** |
| `stream_options={"include_usage": True}` | Supported | Supported — `ChatCompletionStreamOptionsParam` type exists in 3.x | **None** |
| `stream=True` → `Stream` iterator | Supported | Supported — returns `Stream[ChatCompletionChunk]` | **None** |
| `chunk.usage` | Present on last chunk | Present on last chunk | **None** |
| `chunk.choices[0].delta.content` | `Optional[str]` | `Optional[str]` | **None** |
| `chunk.choices[0].delta.reasoning_content` | **Not in SDK type** (present at runtime via Pydantic extra) | **Not in SDK type** (present at runtime via Pydantic extra) | **None** — `getattr(d, "reasoning_content", None)` works in both versions because the SDK uses Pydantic `BaseModel` which allows extra fields at runtime |
| `chunk.choices[0].delta.tool_calls` | Not used in runner | Not used in runner | **N/A** |

**Verdict:** No code changes required for the streaming surface.

---

## 3. Tool-calling surface (`benchkit/agentic/loop.py:66-83`)

```python
resp = client.chat.completions.create(
    model=cfg.model, messages=messages, tools=TOOLS, tool_choice="auto",
    max_tokens=cfg.max_tokens,
    extra_body={"chat_template_kwargs": {...}},
)
msg = resp.choices[0].message
calls = msg.tool_calls or []
for c in calls:
    name = c.function.name
    args = c.function.arguments
```

| Field | 2.x status | 3.x status | Action needed |
|-------|-----------|-----------|---------------|
| `extra_body` | Supported | Supported | **None** |
| `tool_choice="auto"` | `Literal["auto"|"none"|"required"]` | Same literal type | **None** |
| `resp.choices[0].message.tool_calls` | `Optional[List[ChatCompletionMessageToolCall]]` | `Optional[List[ChatCompletionMessageToolCallUnion]]` (union type, same shape) | **None** |
| `c.function.name` | `str` | `str` | **None** |
| `c.function.arguments` | `str` | `str` | **None** |
| `resp.usage.completion_tokens` | `Optional[int]` | `Optional[int]` | **None** |

**Verdict:** No code changes required for the tool-calling surface.

---

## 4. Deprecated fields (no impact)

The following fields are marked deprecated but **still present and functional** in 3.x:

| Deprecated field | Replacement | Impact |
|-----------------|-------------|--------|
| `FunctionCall` (in `ChatCompletionMessage`) | `tool_calls` | Not used in this repo |
| `ChoiceDeltaFunctionCall` (in streaming chunks) | `tool_calls` | Not used in this repo |
| `function_call` on delta/message | `tool_calls` | Not used in this repo |

---

## 5. Dependencies change

| Dependency | 2.x | 3.x |
|-----------|-----|-----|
| `httpx` | `httpx>=0.27.0,<0.28.0` | **Removed** — replaced by `httpx2>=0.1.0,<0.2.0` |
| `pydantic` | `pydantic>=2.0` | `pydantic>=2.0` (unchanged) |
| `anyio` | `anyio>=4.9` | `anyio>=4.9` (unchanged) |

The repo does not depend on `httpx` directly — it goes through the `openai` package. The dependency swap is transparent.

---

## 6. Summary

| Surface | Breaking? | Code change? |
|---------|-----------|-------------|
| `OpenAI(base_url=..., api_key=...)` | No | No |
| Streaming + `stream_options` | No | No |
| `extra_body` / `chat_template_kwargs` | No | No |
| Tool calls + `tool_choice` | No | No |
| `reasoning_content` (getattr) | No | No |
| HTTP client (httpx → httpx2) | Yes | No — repo does not configure custom HTTP |

**Conclusion:** The bump from `openai>=2.31.0,<3` to `openai>=3.0,<4` is a **drop-in replacement** for this codebase. No source code changes are required. The only risk surface is the benchmark regression check (issue #27) to confirm scores stay within noise.
