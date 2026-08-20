#!/usr/bin/env python3
"""Does the configured num_ctx actually let the model see the top of a large
repo context? Plants a distinctive constant early, asks for it at the end."""
import json, sys, urllib.request

MODEL, NCTX = sys.argv[1], (int(sys.argv[2]) if len(sys.argv) > 2 else None)
NEEDLE = "RETRY_BACKOFF_CEILING_MS = 8_641"
CHUNK = '''
def handler_{i}(request, ctx):
    payload = request.get("payload") or {{}}
    token = ctx.session.get("token_{i}")
    if token is None or token.expired:
        return {{"status": 401}}
    return {{"status": 200, "body": ctx.store.query("SELECT * FROM t{i}").rows}}
'''
body = f"# config.py\n{NEEDLE}\n\n" + "".join(CHUNK.format(i=i) for i in range(120))
prompt = ("Here is a Python service:\n\n```python\n" + body +
          "\n```\n\nWhat is the exact numeric value assigned to "
          "RETRY_BACKOFF_CEILING_MS in this codebase? Answer with the number only.")
opts = {"num_predict": 60, "temperature": 0.0}
if NCTX:
    opts["num_ctx"] = NCTX
req = urllib.request.Request("http://localhost:11434/api/generate",
    data=json.dumps({"model": MODEL, "prompt": prompt, "stream": False,
                     "think": False, "options": opts}).encode(),
    headers={"Content-Type": "application/json"})
d = json.load(urllib.request.urlopen(req, timeout=1800))
ans = d.get("response", "").strip().replace("\n", " ")
print(json.dumps({"num_ctx": NCTX, "prompt_tokens": d.get("prompt_eval_count"),
                  "found": "8641" in ans.replace("_", "").replace(",", ""),
                  "answer": ans[:120]}))
