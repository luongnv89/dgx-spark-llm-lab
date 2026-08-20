"""Optional helpers for swapping the model behind the local vLLM service.

Only useful on the DGX Spark box described in SERVING.md. Everything else in
benchkit works against any OpenAI-compatible endpoint and never imports this.
"""
import os
import re
import subprocess
import time
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIGS = os.path.join(HERE, "configs")
LAUNCHER = os.path.join(HERE, "start-qwen.sh")
UNIT = "vllm-qwen"
HEALTH_URL = "http://127.0.0.1:8801/v1/models"
MODEL_RE = re.compile(r'^MODEL_ID="([^"]+)"', re.M)


def current_model(launcher=LAUNCHER):
    m = MODEL_RE.search(open(launcher).read())
    return m.group(1) if m else None


def set_model(model_id, launcher=LAUNCHER):
    """Rewrite MODEL_ID in the launcher. Returns the previous value."""
    src = open(launcher).read()
    m = MODEL_RE.search(src)
    if not m:
        raise RuntimeError(f"no MODEL_ID= line in {launcher}")
    prev = m.group(1)
    if prev != model_id:
        open(launcher, "w").write(MODEL_RE.sub(f'MODEL_ID="{model_id}"', src, count=1))
    return prev


def restart(unit=UNIT, timeout=900, poll=10):
    """Restart the unit and block until the endpoint serves /v1/models."""
    subprocess.run(["systemctl", "--user", "restart", unit], check=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(HEALTH_URL, timeout=5):
                return True
        except Exception:  # noqa: BLE001 — engine init takes minutes; keep polling
            time.sleep(poll)
    raise TimeoutError(f"{unit} did not become healthy within {timeout}s")


def swap_to(model_id, **kw):
    prev = set_model(model_id)
    restart(**kw)
    return prev


def list_configs(configs=CONFIGS):
    """Known-good launch recipes: [(name, model_id, path), ...]."""
    out = []
    for fn in sorted(os.listdir(configs)):
        if not fn.endswith(".sh"):
            continue
        path = os.path.join(configs, fn)
        m = MODEL_RE.search(open(path).read())
        out.append((fn[:-3], m.group(1) if m else "?", path))
    return out


def apply_config(name, configs=CONFIGS, launcher=LAUNCHER):
    """Install a recipe as the active launcher. Returns (path, model_id)."""
    path = os.path.join(configs, name if name.endswith(".sh") else name + ".sh")
    if not os.path.exists(path):
        raise SystemExit(f"no such config: {name}. Try `bench configs`.")
    src = open(path).read()
    open(launcher, "w").write(src)
    os.chmod(launcher, 0o755)
    m = MODEL_RE.search(src)
    return path, (m.group(1) if m else None)
