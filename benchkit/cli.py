"""bench — validate suites, run them against an endpoint, and write the report."""
import argparse
import datetime as _dt
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from benchkit import report, runner
from benchkit.references import REFERENCES
from benchkit.suites import DESCRIPTIONS, SUITES, get, kind

RESULTS = os.path.join(HERE, "results")


def _confirm_restart(unit: str, model_id: str, yes: bool) -> None:
    """Prompt for confirmation before restarting a shared endpoint.

    The guardrail from AGENTS.md:129 — "Never restart a shared serving
    endpoint without explicit human approval" — is enforced here.
    """
    if yes:
        return
    answer = input(
        f"\n⚠ This will restart unit {unit!r} and serve {model_id!r}. "
        f"Continue? [y/N] "
    )
    if answer.strip().lower() != "y":
        raise SystemExit("restart declined — no changes made")


def _print_agentic(r):
    mark = "PASS" if r["passed"] else "FAIL"
    print(f"  {mark}  {r['task']:<24} s{r['sample']} "
          f"{r['turns']:>3} turns {r['tool_calls']:>3} calls "
          f"({r['failed_calls']} failed) {r['stop_reason']:<12} "
          f"{r.get('completion_tokens') or 0:>6}tok {(r.get('elapsed') or 0):6.1f}s"
          + (f"   <{str(r.get('error'))[:60]}>" if not r["passed"] else ""), flush=True)


def _print_result(r):
    mark = "PASS" if r["passed"] else "FAIL"
    print(f"  {mark}  {r['task']:<20} s{r['sample']} "
          f"{r.get('completion_tokens') or 0:>6}tok "
          f"{(r.get('elapsed') or 0):6.1f}s "
          f"{(r.get('tok_s') or 0):5.1f}tok/s"
          + (f"   <{str(r.get('error'))[:70]}>" if not r["passed"] else ""), flush=True)


def _execute_suite(suite, tasks, cfg, max_turns=None, keep_code=False):
    """The single place that decides *how* a suite is executed.

    Codegen suites are one-shot (`runner.run`, scored by hidden unit tests);
    agentic suites are multi-turn tool-calling loops (`agentic.loop.run`,
    scored by an oracle over the final workspace). Every command that executes
    a suite -- `run`, `compare`, and anything added later -- must route through
    here, so the two paths cannot silently diverge again (issue #55).

    Returns the ``(summary, results)`` pair of whichever runner was chosen.
    """
    if kind(suite) == "agentic":
        from benchkit.agentic import loop
        extra = {} if max_turns is None else {"max_turns": max_turns}
        return loop.run(tasks, cfg, on_result=_print_agentic, **extra)
    return runner.run(tasks, cfg, on_result=_print_result, keep_code=keep_code)


def cmd_suites(args):
    for name, tasks in SUITES.items():
        print(f"{name:<8} {len(tasks):>3} tasks   {DESCRIPTIONS[name]}")
        if args.verbose:
            for t in tasks:
                print(f"           {t['difficulty']:<7} {t['id']}")


def cmd_validate(args):
    """Prove every task's hidden tests pass against a reference solution."""
    tasks = get(args.suite)
    if kind(args.suite) == "agentic":
        from benchkit.agentic.loop import validate
        return 1 if validate(tasks) else 0
    bad = 0
    for t in tasks:
        code = REFERENCES.get(t["id"])
        if not code:
            print(f"  MISSING  {t['id']}")
            bad += 1
            continue
        ok, err = runner.run_tests(t, code, args.test_timeout)
        print(f"  {'ok  ' if ok else 'FAIL'} {t['id']}")
        if not ok:
            bad += 1
            print(f"         {err}")
    print(f"\n{len(tasks) - bad}/{len(tasks)} reference solutions pass")
    return 1 if bad else 0


def cmd_run(args):
    tasks = get(args.suite)
    cfg = runner.Config.from_env(
        base_url=args.base_url, model=args.model, label=args.label,
        thinking=args.thinking, max_tokens=args.max_tokens, samples=args.samples,
        concurrency=args.concurrency, test_timeout=args.test_timeout,
    )
    if not cfg.label:
        cfg.label = f"{cfg.model} think-{'ON' if cfg.thinking else 'OFF'} {cfg.max_tokens // 1000}k"
    print(f"suite={args.suite} ({len(tasks)} tasks)  {cfg.label}\n"
          f"endpoint={cfg.base_url}  samples={cfg.samples}  concurrency={cfg.concurrency}\n",
          flush=True)
    summary, results = _execute_suite(args.suite, tasks, cfg,
                                      max_turns=args.max_turns,
                                      keep_code=args.keep_code)

    out = args.out or os.path.join(RESULTS, _stamp(), f"{_slug(cfg.label)}.json")
    out = _ensure_unique_path(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(dict(summary=summary, results=results), f, indent=2)

    print("\n" + "=" * 64)
    print(f"pass@1                 {summary['pass_at_1'] * 100:.1f} %")
    print("by difficulty          " + "  ".join(
        f"{k}={v * 100:.1f}%" for k, v in summary["by_difficulty"].items() if v is not None))
    print(f"wall                   {summary['wall_seconds']:.0f} s")
    print(f"mean output tokens     {summary['mean_completion_tokens'] or 0:.0f}")
    print(f"truncated / errored    {summary['truncated']} / {summary['errored']}")
    if summary.get("kind") == "agentic":
        print(f"agent score            {summary['agent_score'] * 100:.1f}   "
              f"(solve {summary['pass_at_1'] * 100:.1f} % x efficiency "
              f"{(summary['mean_efficiency'] or 0) * 100:.1f} %)")
        print(f"mean calls vs par      {summary['mean_tool_calls'] or 0:.1f} vs "
              f"{summary['mean_par_calls'] or 0:.1f}")
        print(f"mean turns / calls     {summary['mean_turns'] or 0:.1f} / {summary['mean_tool_calls'] or 0:.1f}")
        print(f"valid tool-call rate   {(summary['valid_call_rate'] or 0) * 100:.1f} %")
        print(f"malformed / unknown    {summary['malformed_args']} / {summary['unknown_tools']}")
        print(f"turn-limit / stalled   {summary['hit_turn_limit']} / {summary['stalled_no_tool_call']}")
    print("=" * 64)
    print(f"\nwritten to {out}")
    return 0


def cmd_report(args):
    runs = [report.load(p) for p in args.results]
    notes = open(args.notes).read() if args.notes else None
    md = report.build(runs, title=args.title, question=args.question,
                      verdict=args.verdict, notes=notes, setups=args.setups)
    out = args.out or os.path.join(os.path.dirname(args.results[0]), "REPORT.md")
    if os.path.exists(out) and not args.force:
        # results/ is append-only, and the default output path lands straight in
        # a finished campaign's directory.
        raise SystemExit(f"refusing to overwrite an existing report: {out}\n"
                         "Pass --out <path> to write elsewhere, or --force.")
    with open(out, "w") as f:
        f.write(md)
    print(f"written to {out}")
    return 0


def cmd_compare(args):
    """Full pipeline: swap the local vLLM to each model, run the suite, report."""
    from benchkit import serving
    stamp = _stamp()
    outdir = os.path.join(RESULTS, f"{stamp}-{_slug(args.title)}")
    os.makedirs(outdir, exist_ok=True)
    original = serving.current_model()
    print(f"currently serving {original}; results -> {outdir}\n")
    paths = []
    try:
        for model_id in args.models:
            print(f"\n=== swapping to {model_id} ===", flush=True)
            _confirm_restart(serving.UNIT, model_id, args.yes)
            serving.swap_to(model_id)
            for thinking in ([False, True] if args.both_modes else [args.thinking]):
                label = f"{model_id.split('/')[-1]} think-{'ON' if thinking else 'OFF'}"
                cfg = runner.Config(
                    base_url=args.base_url, model=args.model, label=label,
                    thinking=thinking,
                    max_tokens=args.max_tokens_think if thinking else args.max_tokens,
                    samples=args.samples, concurrency=args.concurrency,
                    test_timeout=args.test_timeout)
                print(f"\n--- {label} ---", flush=True)
                summary, results = _execute_suite(
                    args.suite, get(args.suite), cfg, max_turns=args.max_turns)
                p = os.path.join(outdir, f"{_slug(label)}.json")
                with open(p, "w") as f:
                    json.dump(dict(summary=summary, results=results), f, indent=2)
                paths.append(p)
                line = f"  -> pass@1 {summary['pass_at_1'] * 100:.1f} %"
                if summary.get("kind") == "agentic":
                    line += (f"  agent score {summary['agent_score'] * 100:.1f}"
                             f"  {summary['mean_tool_calls']:.1f} calls vs par "
                             f"{summary['mean_par_calls']:.1f}"
                             f"  {summary['mean_turns']:.1f} turns")
                print(f"{line}  ({p})", flush=True)
    finally:
        if original and args.restore:
            try:
                print(f"\nrestoring {original}")
                serving.swap_to(original)
            except Exception as e:  # noqa: BLE001 — log the failure, never mask the original
                print(f"WARNING: could not restore {original}: {e}", file=sys.stderr)

    md = report.build([report.load(p) for p in paths], title=args.title,
                      question=args.question)
    out = os.path.join(outdir, "REPORT.md")
    with open(out, "w") as f:
        f.write(md)
    print(f"\nreport written to {out}")
    return 0


def _sweep_model(args, setup):
    """Resolve one harness setup's model spec, as a user error not a traceback.

    Called once up front for the whole matrix as well as at run time, so a typo
    is answered before the first endpoint restart rather than after it.
    """
    from benchkit.harness import models as hmodels
    spec = setup.model or args.model
    try:
        # in endpoint mode the id is whatever the server reports, so it is taken
        # literally; there is no catalogue to match against
        return hmodels.resolve(spec, [])
    except hmodels.ModelSpecError as e:
        raise SystemExit(f"setup {setup.resolved_label(args.model)!r}: {e}") from e


def _sweep_harness(args, setup):
    """Build and probe the harness one setup needs. Every failure is a user error.

    Called from the pre-flight pass as well as from the run, so a wrong suite
    kind, a bad model spec or an uninstalled harness is reported before the
    first endpoint restart rather than after it -- a shared endpoint should
    never be restarted twice to discover a typo.
    """
    from benchkit import harness as H

    if kind(args.suite) != "agentic":
        raise SystemExit(f"setup {setup.resolved_label(args.model)!r} runs through "
                         f"a harness, which needs an agentic suite; --suite is "
                         f"{args.suite!r} (try agentic, agentic-hard, agentic-all)")
    # A sweep exists to measure *this* endpoint, so a harness in a sweep is
    # always pointed at it rather than at its own configured providers.
    endpoint = args.endpoint or args.base_url
    provider, model = _sweep_model(args, setup)
    h = H.get(setup.harness,
              H.HarnessConfig(provider=provider, model=model, base_url=endpoint))
    ok, detail = h.available()
    if not ok:
        raise SystemExit(f"harness {h.name!r} is not usable here: {detail}")
    return h


def _sweep_execute(args, setup, label):
    """Run one setup row and return its (summary, results).

    The two execution paths differ only in *what* wraps the model: benchkit's
    own tool loop, or a real harness pointed at this endpoint. Both record the
    serving config and harness on the run config, which is what lets the report
    rank setups rather than models.
    """
    tasks = get(args.suite)
    if not setup.harness:
        cfg = runner.Config(
            base_url=args.base_url, model=setup.model or args.model, label=label,
            thinking=setup.thinking,
            max_tokens=args.max_tokens_think if setup.thinking else args.max_tokens,
            samples=args.samples, concurrency=args.concurrency,
            test_timeout=args.test_timeout,
            serving_config=setup.config or setup.config_name, harness="")
        return _execute_suite(args.suite, tasks, cfg, max_turns=args.max_turns)

    from benchkit.harness import runner as hrunner

    h = _sweep_harness(args, setup)
    endpoint = args.endpoint or args.base_url
    cfg = runner.Config(base_url=endpoint, model=h.model_spec, label=label,
                        thinking=setup.thinking, max_tokens=0,
                        samples=args.samples, concurrency=args.concurrency,
                        test_timeout=args.test_timeout,
                        serving_config=setup.config or setup.config_name,
                        harness=h.name)
    return hrunner.run(h, tasks, cfg, on_result=_print_agentic,
                       timeout=args.timeout, keep_dirs=False)


def cmd_sweep(args):
    """Sweep an explicit setup matrix and rank the setups, not the models.

    `bench compare` answers "which model?". This answers "which *setup*?" --
    serving config x harness x thinking mode -- with one endpoint restart per
    distinct serving config, behind the shared-endpoint approval gate, and with
    the launcher that was active when the sweep began put back on the way out.
    """
    from benchkit import serving
    from benchkit import sweep as S

    setups = S.parse_setups(args.setups, known_harnesses=_harness_names(),
                            default_model=args.model)
    if args.dry_run:
        S.check_sweepable(setups, serving)
        print(S.plan(setups, default_model=args.model))
        needed = S.configs_needing_swap(setups)
        print("\nendpoint restarts: " + (", ".join(needed) if needed else "none"))
        if needed and not args.yes_restart_endpoint:
            print("  -> would ask for approval first "
                  "(or pass --yes-restart-endpoint)")
        return 0

    S.check_sweepable(setups, serving)
    for setup in setups:
        if setup.harness:
            _sweep_harness(args, setup)

    # results/ is append-only and _stamp() is day-granular, so a second sweep
    # with the same title on the same day would land in the same directory.
    # Every collision is found now, not after a restart and an hour of runs.
    outdir = os.path.join(RESULTS, f"{_stamp()}-{_slug(args.title)}")
    out = os.path.join(outdir, "REPORT.md")
    taken = [p for p in [out] + S.result_paths(setups, outdir, args.model)
             if os.path.exists(p)]
    if taken:
        raise SystemExit("refusing to overwrite files from an earlier campaign:\n"
                         + "\n".join(f"  {p}" for p in taken)
                         + "\nGive this sweep a different --title.")
    print(f"suite={args.suite}  {S._n(len(setups), 'setup')}  "
          f"results -> {outdir}\n")

    paths = S.run_sweep(
        setups, outdir,
        execute=lambda setup, label: _sweep_execute(args, setup, label),
        serving=serving, assume_yes=args.yes_restart_endpoint,
        default_model=args.model)

    md = report.build([report.load(p) for p in paths], title=args.title,
                      question=args.question, setups=True)
    with open(out, "w") as f:
        f.write(md)
    print(f"\nreport written to {out}")
    return 0


def cmd_harness(args):
    """Run a suite through a real coding harness, on whichever model you pick.

    The point of the harness commands is that they work on *your* machine with
    *your* setup: the model list comes from opencode's or pi's own configuration
    and credentials, so anyone can run this benchmark against the models they
    already use, without editing their editor's config.
    """
    if args.harness_cmd == "list":
        _harness_list()
        return 0
    if args.harness_cmd == "models":
        _harness_models(args)
        return 0
    endpoint = args.endpoint or os.environ.get("BENCH_HARNESS_ENDPOINT") or None
    return _harness_run(args, endpoint)


def _harness_list():
    from benchkit import harness as H
    for name in H.HARNESSES:
        ok, detail = H.get(name).probe()
        print(f"{name:<12} {'ok     ' if ok else 'MISSING'} {detail}")


def _harness_models(args):
    from benchkit import harness as H
    from benchkit.harness import models as hmodels
    names = [args.harness] if args.harness_explicit else list(H.HARNESSES)
    for name in names:
        probe = H.get(name)
        ok, detail = probe.probe()
        print(f"\n{name}: {detail}")
        for provider, model in hmodels.catalogue(probe):
            print(f"  {hmodels.spec(provider, model)}")


def _harness_pick(args, endpoint):
    """Which model to benchmark, resolved from the user's own harness config."""
    from benchkit import harness as H
    from benchkit.harness import models as hmodels
    probe = H.get(args.harness, H.HarnessConfig(base_url=endpoint))
    entries = [] if endpoint else hmodels.catalogue(probe)
    spec = args.model or os.environ.get("BENCH_HARNESS_MODEL") or ""
    if spec:
        return hmodels.resolve(spec, entries, provider=args.provider)
    if endpoint:
        raise SystemExit("--endpoint needs --model <id served by that endpoint>")
    return hmodels.pick(args.harness, entries)


def _harness_config(args, h, base_url, live=False):
    """The Config one harness run records, label included."""
    cfg = runner.Config(base_url=base_url, model=h.model_spec,
                        label=args.label, thinking=args.thinking, max_tokens=0,
                        samples=args.samples, concurrency=args.concurrency,
                        test_timeout=args.test_timeout)
    if live:
        # Stamp live mode on the run config so a report can tell a measurement
        # of the user's daily setup from one of an isolated harness (#76).
        cfg.extra["live"] = True
    if not cfg.label:
        # The model belongs in the label: two runs of the same harness on
        # different models are the whole point, and a file named after the
        # harness alone would overwrite one with the other.
        cfg.label = (f"{h.name} {'live ' if live else ''}"
                     f"{_slug(str(h.model_spec))} "
                     f"think-{'ON' if args.thinking else 'OFF'}")
    return cfg


def _print_harness_summary(h, summary):
    print("\n" + "=" * 64)
    print(f"harness / model        {h.name} / {h.model_spec}")
    print(f"agent score            {summary['agent_score'] * 100:.1f}   "
          f"(solve {summary['pass_at_1'] * 100:.1f} % x efficiency "
          f"{(summary['mean_efficiency'] or 0) * 100:.1f} %)")
    print(f"mean calls vs par      {summary['mean_tool_calls']:.1f} vs "
          f"{summary['mean_par_calls']:.1f}")
    print(f"mean turns             {summary['mean_turns']:.1f}")
    print(f"tokens in / out        {summary['mean_input_tokens']:.0f} / "
          f"{summary['mean_completion_tokens'] or 0:.0f} per task")
    print(f"valid tool-call rate   {(summary['valid_call_rate'] or 0) * 100:.1f} %")
    print(f"wall                   {summary['wall_seconds']:.0f} s")
    print("=" * 64)


def _harness_run(args, endpoint, live=False):
    from benchkit import harness as H
    from benchkit.harness import runner as hrunner

    provider, model = _harness_pick(args, endpoint)
    h = H.get(args.harness,
              H.HarnessConfig(provider=provider, model=model, base_url=endpoint,
                              live=live))
    tasks = get(args.suite)
    if kind(args.suite) != "agentic":
        raise SystemExit("harness runs need an agentic suite "
                         "(agentic, agentic-hard, agentic-all)")
    ok, detail = h.available()
    if not ok:
        raise SystemExit(f"harness {h.name!r} is not usable here: {detail}")

    cfg = _harness_config(args, h, endpoint or "(harness)", live=live)
    print(f"harness={h.name}{'+live' if live else ''}  {detail}\n"
          f"suite={args.suite} ({len(tasks)} tasks)  "
          f"{cfg.label}  samples={cfg.samples} concurrency={cfg.concurrency}\n", flush=True)

    summary, results = hrunner.run(h, tasks, cfg, on_result=_print_agentic,
                                   timeout=args.timeout, keep_dirs=args.keep_dirs)
    out = args.out or os.path.join(RESULTS, _stamp(), f"{_slug(cfg.label)}.json")
    out = _ensure_unique_path(out)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(dict(summary=summary, results=results), f, indent=2)

    _print_harness_summary(h, summary)
    print(f"\nwritten to {out}")
    if live:
        # A live run is judged on its own setup, so the advice section is part
        # of the deliverable, not an extra step. Same append-only rule as the
        # result json: never overwrite a report from an earlier campaign.
        md = report.build([report.load(out)], title=f"Live setup: {h.name}",
                          question=(f"Is {h.name}'s current setup any good, and "
                                    f"what should improve?"),
                          verdict=None, advice=True)
        rpt = os.path.join(os.path.dirname(out), "REPORT-live.md")
        rpt = _ensure_unique_path(rpt)
        with open(rpt, "w") as f:
            f.write(md)
        print(f"report written to {rpt}")
    return 0


def cmd_setup(args):
    """Benchmark the harness you are sitting in, with its live configuration.

    `bench harness run` isolates: no extensions, no skills, no MCP servers, so
    the model alone is measured. `bench setup` is the opposite — the user's
    daily setup runs exactly as they experience it (issue #76), and the report
    ends with concrete suggestions about that setup.
    """
    endpoint = args.endpoint or os.environ.get("BENCH_HARNESS_ENDPOINT") or None
    return _harness_run(args, endpoint, live=True)


def cmd_configs(args):
    from benchkit import serving
    active = serving.current_model()
    ok, skipped = serving.sweepable_configs()
    for name, model_id, _ in ok:
        mark = " (active model)" if model_id == active else ""
        print(f"{name:<34} {model_id}{mark}")
    for name, model_id, reason in skipped:
        # still a known-good recipe, just not one `bench sweep` can install and
        # restart -- say why here rather than crashing halfway through a sweep.
        mark = " (active model)" if model_id == active else ""
        print(f"{name:<34} {model_id}{mark}\n{'':<34} not sweepable: {reason}")
    return 0


def cmd_apply(args):
    """Install a known-good config as the active launcher, optionally restarting."""
    from benchkit import serving
    prev = serving.current_model()
    path, model_id = serving.apply_config(args.name)
    print(f"installed {os.path.relpath(path, HERE)} -> start-qwen.sh")
    print(f"  model: {prev} -> {model_id}")
    if args.restart:
        _confirm_restart(serving.UNIT, model_id, args.yes)
        print("restarting the service; engine init takes several minutes...")
        serving.restart()
        print("endpoint healthy")
    else:
        print("\nNot restarted. Apply with:  systemctl --user restart vllm-qwen")
    return 0


def _harness_names():
    from benchkit.harness import HARNESSES
    return list(HARNESSES)


def _stamp():
    return _dt.date.today().isoformat()


def _slug(s):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s.lower()).strip("-")


def _ensure_unique_path(path: str) -> str:
    """Return a path that does not overwrite an existing result file.

    If *path* already exists, suffix with a counter (e.g. ``.1``, ``.2``)
    until we find a free name. This enforces the append-only rule from
    AGENTS.md and prevents two runs from silently overwriting each other.
    """
    if not os.path.exists(path):
        return path
    base, ext = os.path.splitext(path)
    i = 1
    while True:
        candidate = f"{base}.{i}{ext}"
        if not os.path.exists(candidate):
            return candidate
        i += 1


def _common_args(sp):
    sp.add_argument("--suite", default="all", choices=list(SUITES))
    sp.add_argument("--base-url", default=os.environ.get("BENCH_BASE_URL",
                                                         "http://localhost:8001/v1"))
    sp.add_argument("--model", default=os.environ.get("BENCH_MODEL", "montimage-dgx-spark"),
                    help="model name to send in the request (the served alias)")
    sp.add_argument("--samples", type=int, default=2)
    sp.add_argument("--concurrency", type=int, default=4)
    sp.add_argument("--test-timeout", type=int, default=60)


def _parser_suites(sub):
    s = sub.add_parser("suites", help="list the available suites")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_suites)


def _parser_validate(sub):
    s = sub.add_parser("validate", help="prove the hidden tests are passable")
    s.add_argument("--suite", default="all", choices=list(SUITES))
    s.add_argument("--test-timeout", type=int, default=120)
    s.set_defaults(func=cmd_validate)


def _parser_run(sub):
    s = sub.add_parser("run", help="run a suite against an endpoint")
    _common_args(s)
    s.add_argument("--thinking", action="store_true", help="enable the model's reasoning block")
    s.add_argument("--max-tokens", type=int, default=6000)
    s.add_argument("--label", default="", help="human name for this run, used in the report")
    s.add_argument("--out", help="result json path (default: results/<date>/<label>.json)")
    s.add_argument("--keep-code", action="store_true", help="store each generated program")
    s.add_argument("--max-turns", type=int, default=25,
                   help="agentic suite: tool-calling turns before the task is abandoned")
    s.set_defaults(func=cmd_run)


def _parser_report(sub):
    s = sub.add_parser("report", help="build a Markdown report from result files")
    s.add_argument("results", nargs="+")
    s.add_argument("--title", default="Benchmark report")
    s.add_argument("--question")
    s.add_argument("--verdict")
    s.add_argument("--notes", help="path to a Markdown file inserted as analysis")
    s.add_argument("--setups", action="store_true",
                   help="add the ranked-setups section, as `bench sweep` writes it "
                        "— rebuilds a sweep's ranking from its result files")
    s.add_argument("--force", action="store_true",
                   help="overwrite the output file if it already exists")
    s.add_argument("--out")
    s.set_defaults(func=cmd_report)


def _parser_compare(sub):
    s = sub.add_parser("compare", help="swap the local vLLM between models and report (DGX box only)")
    _common_args(s)
    s.add_argument("models", nargs="+", help="Hugging Face model ids to serve in turn")
    s.add_argument("--title", default="Model comparison")
    s.add_argument("--question")
    s.add_argument("--thinking", action="store_true")
    s.add_argument("--both-modes", action="store_true",
                   help="run each model twice, thinking off then on")
    s.add_argument("--max-tokens", type=int, default=6000)
    s.add_argument("--max-tokens-think", type=int, default=16000)
    s.add_argument("--max-turns", type=int, default=25,
                   help="agentic suite: tool-calling turns before the task is abandoned")
    s.add_argument("--no-restore", dest="restore", action="store_false",
                   help="leave the last model serving instead of restoring the original")
    s.add_argument("--yes", action="store_true",
                   help="skip the restart confirmation prompt")
    s.set_defaults(func=cmd_compare)


def _parser_sweep(sub):
    s = sub.add_parser("sweep",
                       help="sweep an explicit setup matrix (config x harness x "
                            "thinking) and rank the setups")
    _common_args(s)
    s.add_argument("--setup", dest="setups", action="append", default=[],
                   metavar="config=...,harness=...,model=...,thinking=...",
                   help="one setup, repeatable. Keys: config (a `bench configs` "
                        "name; omit to use whatever is already serving), harness "
                        "(omit for benchkit's own loop), model, thinking "
                        "(on|off|both), label. Setups are explicit on purpose: "
                        "independent axes cross-product into combinations that "
                        "cannot exist.")
    s.add_argument("--title", default="Setup sweep")
    s.add_argument("--question")
    s.add_argument("--max-tokens", type=int, default=6000)
    s.add_argument("--max-tokens-think", type=int, default=16000)
    s.add_argument("--max-turns", type=int, default=25,
                   help="agentic suite: tool-calling turns before the task is abandoned")
    s.add_argument("--timeout", type=int, default=900,
                   help="harness setups: seconds per task")
    s.add_argument("--endpoint", default="",
                   help="endpoint to point harness setups at "
                        "(default: --base-url, i.e. the endpoint being swept)")
    s.add_argument("--yes-restart-endpoint", action="store_true",
                   help="approve restarting the shared serving endpoint once per "
                        "serving config in the matrix. Without it a sweep that "
                        "needs a restart refuses to start (CLAUDE.md: never "
                        "restart a shared endpoint without explicit approval).")
    s.add_argument("--dry-run", action="store_true",
                   help="print the matrix and the restart plan, run nothing")
    s.set_defaults(func=cmd_sweep)


def _parser_harness(sub):
    s = sub.add_parser("harness",
                       help="run a suite through a real coding harness (opencode, pi, ...)")
    s.add_argument("harness_cmd", nargs="?", default="run",
                   choices=["run", "list", "models"],
                   help="run a suite, list installed harnesses, or list their models")
    s.add_argument("--harness", default="pi",
                   help="which harness to drive: " + ", ".join(_harness_names()))
    s.add_argument("--model", "-m", "--harness-model", dest="model", default="",
                   help="model to benchmark, as <provider>/<model> or any unique "
                        "part of it, from your own harness config "
                        "(default: BENCH_HARNESS_MODEL, else ask)")
    s.add_argument("--provider", help="restrict --model to one provider")
    s.add_argument("--endpoint", default="",
                   help="OpenAI-compatible endpoint to point the harness at for "
                        "this run instead of using its configured providers, "
                        "without touching your harness config "
                        "(default: BENCH_HARNESS_ENDPOINT)")
    s.add_argument("--suite", default="agentic-hard", choices=list(SUITES))
    s.add_argument("--samples", type=int, default=1)
    s.add_argument("--concurrency", type=int, default=2)
    s.add_argument("--thinking", action="store_true")
    s.add_argument("--timeout", type=int, default=900, help="seconds per task")
    s.add_argument("--test-timeout", type=int, default=60)
    s.add_argument("--label", default="")
    s.add_argument("--out")
    s.add_argument("--keep-dirs", action="store_true",
                   help="leave each task's working directory on disk for inspection")
    s.set_defaults(func=cmd_harness)


def _parser_setup(sub):
    """`bench setup` — benchmark the harness's live, as-used configuration."""
    s = sub.add_parser("setup",
                       help="benchmark a harness with its live configuration "
                            "(skills, MCP servers, settings included) and get "
                            "improvement suggestions")
    s.add_argument("setup_cmd", nargs="?", default="run", choices=["run"],
                   help="run the live-setup benchmark")
    s.add_argument("--harness", default="pi",
                   help="which harness to drive: " + ", ".join(_harness_names()))
    s.add_argument("--model", "-m", dest="model", default="",
                   help="model to benchmark, as <provider>/<model> or any unique "
                        "part of it (default: BENCH_HARNESS_MODEL, else ask; the "
                        "harness's own default model is usually what you want)")
    s.add_argument("--provider", help="restrict --model to one provider")
    s.add_argument("--endpoint", default="",
                   help="optional endpoint for the model itself; the harness's "
                        "live configuration is still used unchanged")
    s.add_argument("--suite", default="agentic-hard", choices=list(SUITES))
    s.add_argument("--samples", type=int, default=1)
    s.add_argument("--concurrency", type=int, default=2)
    s.add_argument("--thinking", action="store_true")
    s.add_argument("--timeout", type=int, default=900, help="seconds per task")
    s.add_argument("--test-timeout", type=int, default=60)
    s.add_argument("--label", default="")
    s.add_argument("--out")
    s.add_argument("--keep-dirs", action="store_true",
                   help="leave each task's working directory on disk for inspection")
    s.set_defaults(func=cmd_setup)


def _parser_configs(sub):
    s = sub.add_parser("configs", help="list known-good serving configs")
    s.set_defaults(func=cmd_configs)


def _parser_apply(sub):
    s = sub.add_parser("apply", help="install a known-good config as the active launcher")
    s.add_argument("name", help="config name from `bench configs`")
    s.add_argument("--restart", action="store_true",
                   help="restart the vLLM service and wait until it serves")
    s.add_argument("--yes", action="store_true",
                   help="skip the restart confirmation prompt")
    s.set_defaults(func=cmd_apply)


def _build_parser():
    p = argparse.ArgumentParser(prog="bench", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    _parser_suites(sub)
    _parser_validate(sub)
    _parser_run(sub)
    _parser_report(sub)
    _parser_compare(sub)
    _parser_sweep(sub)
    _parser_harness(sub)
    _parser_setup(sub)
    _parser_configs(sub)
    _parser_apply(sub)
    return p


def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    args = _build_parser().parse_args(argv)
    # `bench harness models` lists every installed harness; naming one narrows
    # it. argparse cannot tell a default from an explicit `--harness pi`.
    args.harness_explicit = any(a == "--harness" or a.startswith("--harness=")
                                for a in argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
