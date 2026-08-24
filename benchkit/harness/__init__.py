"""Harness adapters — run the same tasks through the coding agent on this machine.

See benchkit/harness/base.py for why this exists and ROADMAP.md for what is next.
"""
__all__ = [
    "HARNESSES",
    "ClaudeCodeHarness",
    "Harness",
    "HarnessConfig",
    "HarnessResult",
    "OpenCodeHarness",
    "PiHarness",
    "get",
    "run_task",
]

from .base import Harness as Harness
from .base import HarnessConfig as HarnessConfig
from .base import HarnessResult as HarnessResult
from .base import run_task as run_task
from .claudecode import ClaudeCodeHarness
from .opencode import OpenCodeHarness
from .pi import PiHarness

HARNESSES = {"pi": PiHarness, "opencode": OpenCodeHarness,
              "claude-code": ClaudeCodeHarness}


def get(name, cfg=None, **kw):
    if name not in HARNESSES:
        raise SystemExit(f"unknown harness {name!r}; have: {', '.join(HARNESSES)}")
    return HARNESSES[name](cfg, **kw)
