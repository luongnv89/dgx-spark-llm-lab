#!/usr/bin/env python3
"""Measure prompt-processing + decode for a given ollama model at a long,
coding-agent-shaped prompt. Uses /api/generate so ollama reports its own
prompt_eval/eval counters instead of us timing the stream."""
import json, sys, urllib.request

MODEL = sys.argv[1]
NCTX = int(sys.argv[2]) if len(sys.argv) > 2 else None
NBATCH = int(sys.argv[3]) if len(sys.argv) > 3 else None

# ~6k-token synthetic "repo context" followed by a real question about it.
CHUNK = '''
def handler_{i}(request, ctx):
    """Route handler number {i}. Validates the payload and dispatches."""
    payload = request.get("payload") or {{}}
    if not isinstance(payload, dict):
        raise ValueError("payload must be a mapping, got %r" % type(payload))
    token = ctx.session.get("token_{i}")
    if token is None or token.expired:
        ctx.metrics.incr("auth.miss.{i}")
        return {{"status": 401, "body": "unauthorized"}}
    result = ctx.store.query("SELECT * FROM t{i} WHERE k = ?", payload.get("k"))
    ctx.metrics.timing("query.{i}", result.elapsed_ms)
    return {{"status": 200, "body": result.rows}}
'''
body = "".join(CHUNK.format(i=i) for i in range(90))
PROMPT = ("Here is part of a Python service:\n\n```python\n" + body +
          "\n```\n\nEvery handler repeats the same auth check and metrics calls. "
          "Write a single decorator that factors out the repeated auth + metrics "
          "logic, and show handler_0 rewritten to use it. Code only.")

opts = {"num_predict": 400, "temperature": 0.0}
if NCTX:
    opts["num_ctx"] = NCTX
if NBATCH:
    opts["num_batch"] = NBATCH

req = urllib.request.Request(
    "http://localhost:11434/api/generate",
    data=json.dumps({"model": MODEL, "prompt": PROMPT, "stream": False,
                     "think": False, "options": opts}).encode(),
    headers={"Content-Type": "application/json"})
d = json.load(urllib.request.urlopen(req, timeout=1800))
pe, ped = d.get("prompt_eval_count", 0), d.get("prompt_eval_duration", 1)
ec, ed = d.get("eval_count", 0), d.get("eval_duration", 1)
print(json.dumps({
    "model": MODEL, "num_ctx": NCTX, "num_batch": NBATCH,
    "prompt_tokens": pe,
    "prompt_tok_s": round(pe / (ped / 1e9), 1),
    "prompt_seconds": round(ped / 1e9, 2),
    "gen_tokens": ec,
    "gen_tok_s": round(ec / (ed / 1e9), 1),
    "load_seconds": round(d.get("load_duration", 0) / 1e9, 2),
    "total_seconds": round(d.get("total_duration", 0) / 1e9, 2),
    "response_chars": len(d.get("response", "")),
}))
