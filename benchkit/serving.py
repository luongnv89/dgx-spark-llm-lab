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
UNIT_RE = re.compile(r'^NAME="([^"$]+)"', re.M)


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


def unit_of(src):
    """The systemd unit a recipe declares via NAME=, or None if it is dynamic."""
    m = UNIT_RE.search(src)
    return m.group(1) if m else None


def sweepable(src, unit=UNIT):
    """(ok, reason) — can `bench sweep` install this recipe and restart it?

    Two conditions, both mechanical. The recipe must carry a literal
    `MODEL_ID="..."` line, because that is the only thing MODEL_RE can read and
    report; and it must declare the same systemd unit this module restarts,
    because installing a recipe for a different engine or a different backend
    and then restarting `vllm-qwen` would leave the endpoint serving something
    nobody asked for. configs/ deliberately holds recipes that fail both -- a
    llama.cpp benchmark script, an env-tunable standalone server, a secondary
    gemma backend on its own port. They are good recipes; they are just not
    drivable from here, and naming one is a user error, not a crash.
    """
    if not MODEL_RE.search(src):
        return False, 'no literal MODEL_ID="..." line — not a vLLM recipe this can drive'
    declared = unit_of(src)
    if declared is None:
        return False, 'no literal NAME="..." unit — the launcher target is dynamic'
    if declared != unit:
        return False, f"runs as {declared!r}, not the {unit!r} unit this sweep restarts"
    return True, ""


def sweepable_configs(configs=CONFIGS, unit=UNIT):
    """([(name, model_id, path), ...], [(name, model_id, reason), ...]).

    A skipped recipe keeps its model id: it is still a known-good config that
    `bench configs` must list in full, just not one this module can install and
    restart.
    """
    ok, skipped = [], []
    for name, model_id, path in list_configs(configs):
        with open(path) as f:
            good, reason = sweepable(f.read(), unit=unit)
        if good:
            ok.append((name, model_id, path))
        else:
            skipped.append((name, model_id, reason))
    return ok, skipped
