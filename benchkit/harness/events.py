"""Shared skeleton for folding a harness's JSONL event stream into a HarnessResult.

Three adapters (pi, opencode, claude-code) share the same fold-JSONL-into-HarnessResult
skeleton, differing only in event names and field paths.  This module provides a
`parse_events` function that takes a per-adapter event map; each adapter's parser
shrinks to that map plus its own quirks.

Usage::

    def _handle(ev, res, state):
        t = ev.get("type")
        if t == "turn_start":
            res.turns += 1
        # ... more event handlers ...

    result = parse_events(stdout, _handle)
"""
import json


def parse_events(stdout, handler, finalize=None):
    """Fold a JSONL event stream into a HarnessResult using *handler*.

    *handler* is a callable ``(event_dict, HarnessResult, state) -> None`` that
    inspects ``event_dict["type"]`` (or any other key) and mutates the result.
    *state* is a mutable dict shared across all calls, for deduplication and
    counters that cannot live on the result object.

    *finalize*, when given, is ``(HarnessResult, state) -> None`` and runs once
    after the last event — before this function applies its default stop_reason,
    so a fallback that fills in *turns* still feeds that default.

    Lines that are not valid JSON objects are silently skipped.
    """
    res = _make_result(stdout)
    _state = {}
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        handler(ev, res, _state)
    if finalize is not None:
        finalize(res, _state)
    if res.stop_reason == "unknown" and res.turns:
        res.stop_reason = "finished"
    return res


def _make_result(stdout):
    """Create a HarnessResult with the raw log tail."""
    from .base import HarnessResult
    return HarnessResult(raw_log=stdout[-20000:])
