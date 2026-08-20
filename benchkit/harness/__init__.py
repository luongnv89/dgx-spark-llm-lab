"""Harness adapters — run the same tasks through the coding agent on this machine.

See benchkit/harness/base.py for why this exists and ROADMAP.md for what is next.
"""
from .base import Harness, HarnessResult, run_task
from .pi import PiHarness

HARNESSES = {"pi": PiHarness}


def get(name, **kw):
    if name not in HARNESSES:
        raise SystemExit(f"unknown harness {name!r}; have: {', '.join(HARNESSES)}")
    return HARNESSES[name](**kw)
