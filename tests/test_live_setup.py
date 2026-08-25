"""Live-mode harness runs (issue #76): isolation dropped, contamination recorded.

`bench setup` measures the user's daily configuration as-is. The contract under
test: each adapter drops its own isolation flags in live mode, keeps them
otherwise, and a live run always says so in describe() — an unlabelled live run
would let a contaminated score be read as a clean one.
"""
import pytest

from benchkit import advice, report
from benchkit.harness import HarnessConfig


# --- pi -------------------------------------------------------------------
def test_pi_isolated_keeps_flags():
    from benchkit.harness.pi import PiHarness
    h = PiHarness(HarnessConfig(model="m"))
    argv = " ".join(h._argv("p", False))
    assert "--no-extensions" in argv
    assert "--no-context-files" in argv


def test_pi_live_drops_isolation_and_records_it():
    from benchkit.harness.pi import PiHarness
    h = PiHarness(HarnessConfig(model="m", live=True))
    argv = " ".join(h._argv("p", False))
    assert "--no-extensions" not in argv
    assert "--no-context-files" not in argv
    d = h.describe()
    assert d["live"] is True
    assert "--no-extensions" in d["disabled_isolation"]
    assert d["caveats"]


# --- opencode ---------------------------------------------------------------
def test_opencode_isolated_keeps_pure():
    from benchkit.harness.opencode import OpenCodeHarness
    h = OpenCodeHarness(HarnessConfig(model="p/m"))
    assert "--pure" in h._argv("p", "/tmp")


def test_opencode_live_drops_pure_and_records_it():
    from benchkit.harness.opencode import OpenCodeHarness
    h = OpenCodeHarness(HarnessConfig(model="p/m", live=True))
    assert "--pure" not in h._argv("p", "/tmp")
    d = h.describe()
    assert d["live"] is True
    assert "--pure" in d["disabled_isolation"]


# --- claude-code --------------------------------------------------------------
def test_claudecode_isolated_pins_tools():
    from benchkit.harness.claudecode import ClaudeCodeHarness
    h = ClaudeCodeHarness(HarnessConfig(model="m"))
    argv = " ".join(h._argv("p"))
    for flag in ("--bare", "--disable-slash-commands", "--strict-mcp-config",
                 "--setting-sources"):
        assert flag in argv
    assert "--tools" in argv


def test_claudecode_live_unpins_everything_and_records_it():
    from benchkit.harness.claudecode import ClaudeCodeHarness
    h = ClaudeCodeHarness(HarnessConfig(model="m", live=True))
    argv = " ".join(h._argv("p"))
    for flag in ("--bare", "--disable-slash-commands", "--strict-mcp-config",
                 "--mcp-config", "--setting-sources"):
        assert flag not in argv
    assert "--tools" not in argv
    d = h.describe()
    assert d["live"] is True
    assert d["tools"] == []
    assert d["caveats"]


def test_claudecode_session_persistence_survives_live_mode():
    # no-session-persistence is benchmark hygiene, not isolation: tasks must
    # never share state even when the user's setup is live.
    from benchkit.harness.claudecode import ClaudeCodeHarness
    h = ClaudeCodeHarness(HarnessConfig(model="m", live=True))
    assert "--no-session-persistence" in h._argv("p")


# --- advice -------------------------------------------------------------------
def _summary(**over):
    s = dict(kind="agentic", pass_at_1=0.8, agent_score=0.7, mean_efficiency=0.9,
             mean_input_tokens=10_000, hit_turn_limit=0,
             wall_seconds=10.0, tasks=8, generations=8,
             stalled_no_tool_call=0, valid_call_rate=1.0, mean_par_calls=4.0,
             mean_tool_calls=5.0, mean_reasoning_tokens=100, errored=0,
             by_difficulty={"easy": 1.0, "hard": 0.8},
             config={"extra": {}, "label": "test run", "thinking": False,
                     "max_tokens": 0, "model": "m", "base_url": "", 
                     "concurrency": 2, "samples": 1}, harness={})
    s.update(over)
    return s


def test_advice_flags_context_bloat_on_high_input_tokens():
    s = _summary(mean_input_tokens=80_000)
    s["config"]["extra"]["live"] = True
    tips = "\n".join(advice.build(s))
    assert "input tokens" in tips
    assert "MCP" in tips or "skills" in tips


def test_advice_flags_turn_limit_and_stalls():
    tips = advice.build(_summary(hit_turn_limit=2, stalled_no_tool_call=1))
    joined = "\n".join(tips)
    assert "turn limit" in joined
    assert "no tool call" in joined


def test_advice_flags_low_valid_call_rate_as_schema_mismatch():
    joined = "\n".join(advice.build(_summary(valid_call_rate=0.5)))
    assert "tool-call" in joined


def test_advice_silent_on_healthy_run():
    tips = [t for t in advice.build(_summary()) if "live-mode" not in t]
    assert tips == []


def test_advice_section_has_fallback_for_healthy_run():
    out = advice.section(_summary())
    text = "\n".join(out)
    assert text.startswith("## Suggestions")
    assert "healthy" in text


def test_advice_reads_live_flag_from_config_or_harness_block():
    s = _summary(config={"extra": {"live": True}})
    assert advice._is_live(s) is True
    s2 = _summary(harness={"live": True})
    assert advice._is_live(s2) is True


# --- report / cli wiring --------------------------------------------------------
def _result_file(tmp_path):
    import json
    summary = _summary(mean_input_tokens=90_000)
    summary["config"]["extra"]["live"] = True
    p = tmp_path / "r.json"
    p.write_text(json.dumps(dict(summary=summary, results=[])))
    return str(p)


@pytest.fixture(autouse=True)
def _fake_paths(monkeypatch):
    monkeypatch.setattr(report, "_raw_data_section",
                        lambda runs, labels: ["\n## Raw data\n"])
    monkeypatch.setattr(report, "_setup_section",
                        lambda S, short: ([""], 1, True))
    monkeypatch.setattr(report, "_charts_section", lambda *a: [])
    monkeypatch.setattr(report, "_difficulty_section", lambda S, labels: [])
    monkeypatch.setattr(report, "_disagreement_section",
                        lambda *a, **k: [])
    monkeypatch.setattr(report, "_caveats_section", lambda *a, **k: [])


def test_report_build_with_advice_includes_suggestions(tmp_path):
    md = report.build([report.load(_result_file(tmp_path))], title="t",
                      advice=True)
    assert "## Suggestions" in md
    assert "MCP" in md or "skills" in md


def test_report_build_without_advice_omits_section(tmp_path):
    md = report.build([report.load(_result_file(tmp_path))], title="t")
    assert "Suggestions" not in md


def test_cli_parser_accepts_setup_subcommand():
    from benchkit.cli import _build_parser
    args = _build_parser().parse_args(
        ["setup", "--harness", "pi", "--suite", "agentic-hard"])
    assert args.func.__name__ == "cmd_setup"
    assert args.suite == "agentic-hard"


def test_harness_config_stamps_live_metadata():
    """The live stamp is what makes a result comparable/attributable later."""
    from benchkit import runner
    from benchkit.cli import _harness_config

    class H:
        name = "pi"
        model_spec = "prov/m"

    cfg = _harness_config(type("A", (), {
        "label": "", "thinking": False, "samples": 1,
        "concurrency": 2, "test_timeout": 60})(), H(), "(harness)", live=True)
    assert cfg.extra["live"] is True
    assert cfg.label.startswith("pi live ")
    assert isinstance(cfg, runner.Config)
