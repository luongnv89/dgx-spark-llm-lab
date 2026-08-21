"""Harness adapters — run the same tasks through the coding agent on this machine.

See benchkit/harness/base.py for why this exists and ROADMAP.md for what is next.
"""
__all__ = ["Harness", "HarnessConfig", "HarnessResult", "run_task", "PiHarness",
           "OpenCodeHarness", "ClaudeCodeHarness", "HARNESSES", "get"]

from .base import (Harness as Harness, HarnessConfig as HarnessConfig,
                   HarnessResult as HarnessResult, run_task as run_task)
from .pi import PiHarness
from .opencode import OpenCodeHarness
from .claudecode import ClaudeCodeHarness

HARNESSES = {"pi": PiHarness, "opencode": OpenCodeHarness,
              "claude-code": ClaudeCodeHarness}


def get(name, cfg=None, **kw):
    if name not in HARNESSES:
        raise SystemExit(f"unknown harness {name!r}; have: {', '.join(HARNESSES)}")
    return HARNESSES[name](cfg, **kw)
