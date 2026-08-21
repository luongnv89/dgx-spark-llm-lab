"""bench — validate suites, run them against an endpoint, and write the report."""
import argparse
import datetime as _dt
import json
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from benchkit import runner, report  # noqa: E402
from benchkit.references import REFERENCES  # noqa: E402
from benchkit.suites import SUITES, DESCRIPTIONS, get, kind  # noqa: E402

RESULTS = os.path.join(HERE, "results")


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
        print(f"mean calls vs par      {summary['mean_tool_calls']:.1f} vs "
              f"{summary['mean_par_calls']:.1f}")
        print(f"mean turns / calls     {summary['mean_turns']:.1f} / {summary['mean_tool_calls']:.1f}")
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
                      verdict=args.verdict, notes=notes)
    out = args.out or os.path.join(os.path.dirname(args.results[0]), "REPORT.md")
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
            print(f"\nrestoring {original}")
            serving.swap_to(original)

    md = report.build([report.load(p) for p in paths], title=args.title,
                      question=args.question)
    out = os.path.join(outdir, "REPORT.md")
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
    from benchkit import harness as H
    from benchkit.harness import models as hmodels
    from benchkit.harness import runner as hrunner

    if args.harness_cmd == "list":
        for name in H.HARNESSES:
            ok, detail = H.get(name).probe()
            print(f"{name:<12} {'ok     ' if ok else 'MISSING'} {detail}")
        return 0

    endpoint = args.endpoint or os.environ.get("BENCH_HARNESS_ENDPOINT") or None

    if args.harness_cmd == "models":
        names = [args.harness] if args.harness_explicit else list(H.HARNESSES)
        for name in names:
            probe = H.get(name)
            ok, detail = probe.probe()
            print(f"\n{name}: {detail}")
            for provider, model in hmodels.catalogue(probe):
                print(f"  {hmodels.spec(provider, model)}")
        return 0

    # --- which model, from the user's own setup --------------------------
    probe = H.get(args.harness, **_endpoint_kw(args.harness, endpoint))
    entries = [] if endpoint else hmodels.catalogue(probe)
    spec = args.model or os.environ.get("BENCH_HARNESS_MODEL") or ""
    if spec:
        provider, model = hmodels.resolve(spec, entries, provider=args.provider)
    elif endpoint:
        raise SystemExit("--endpoint needs --model <id served by that endpoint>")
    else:
        provider, model = hmodels.pick(args.harness, entries)

    h = H.get(args.harness, provider=provider, model=model,
              **_endpoint_kw(args.harness, endpoint))
    tasks = get(args.suite)
    if kind(args.suite) != "agentic":
        raise SystemExit("harness runs need an agentic suite "
                         "(agentic, agentic-hard, agentic-all)")
    ok, detail = h.available()
    if not ok:
        raise SystemExit(f"harness {h.name!r} is not usable here: {detail}")

    cfg = runner.Config(base_url=endpoint or "(harness)", model=h.model_spec,
                        label=args.label, thinking=args.thinking, max_tokens=0,
                        samples=args.samples, concurrency=args.concurrency,
                        test_timeout=args.test_timeout)
    if not cfg.label:
        # The model belongs in the label: two runs of the same harness on
        # different models are the whole point, and a file named after the
        # harness alone would overwrite one with the other.
        cfg.label = (f"{h.name} {_slug(str(h.model_spec))} "
                     f"think-{'ON' if args.thinking else 'OFF'}")
    print(f"harness={h.name}  {detail}\nsuite={args.suite} ({len(tasks)} tasks)  "
          f"{cfg.label}  samples={cfg.samples} concurrency={cfg.concurrency}\n", flush=True)

    summary, results = hrunner.run(h, tasks, cfg, on_result=_print_agentic,
                                   timeout=args.timeout, keep_dirs=args.keep_dirs)
    out = args.out or os.path.join(RESULTS, _stamp(), f"{_slug(cfg.label)}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(dict(summary=summary, results=results), f, indent=2)

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
    print(f"\nwritten to {out}")
    return 0


def _endpoint_kw(name, endpoint):
    """An explicit endpoint is opt-in, and not every harness can take one."""
    if not endpoint:
        return {}
    return {"base_url": endpoint}


def cmd_configs(args):
    from benchkit import serving
    active = serving.current_model()
    for name, model_id, _ in serving.list_configs():
        mark = " (active model)" if model_id == active else ""
        print(f"{name:<34} {model_id}{mark}")
    return 0


def cmd_apply(args):
    """Install a known-good config as the active launcher, optionally restarting."""
    from benchkit import serving
    prev = serving.current_model()
    path, model_id = serving.apply_config(args.name)
    print(f"installed {os.path.relpath(path, HERE)} -> start-qwen.sh")
    print(f"  model: {prev} -> {model_id}")
    if args.restart:
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


def main(argv=None):
    p = argparse.ArgumentParser(prog="bench", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--suite", default="all", choices=list(SUITES))
        sp.add_argument("--base-url", default=os.environ.get("BENCH_BASE_URL",
                                                             "http://localhost:8001/v1"))
        sp.add_argument("--model", default=os.environ.get("BENCH_MODEL", "montimage-dgx-spark"),
                        help="model name to send in the request (the served alias)")
        sp.add_argument("--samples", type=int, default=2)
        sp.add_argument("--concurrency", type=int, default=4)
        sp.add_argument("--test-timeout", type=int, default=60)

    s = sub.add_parser("suites", help="list the available suites")
    s.add_argument("-v", "--verbose", action="store_true")
    s.set_defaults(func=cmd_suites)

    s = sub.add_parser("validate", help="prove the hidden tests are passable")
    s.add_argument("--suite", default="all", choices=list(SUITES))
    s.add_argument("--test-timeout", type=int, default=120)
    s.set_defaults(func=cmd_validate)

    s = sub.add_parser("run", help="run a suite against an endpoint")
    common(s)
    s.add_argument("--thinking", action="store_true", help="enable the model's reasoning block")
    s.add_argument("--max-tokens", type=int, default=6000)
    s.add_argument("--label", default="", help="human name for this run, used in the report")
    s.add_argument("--out", help="result json path (default: results/<date>/<label>.json)")
    s.add_argument("--keep-code", action="store_true", help="store each generated program")
    s.add_argument("--max-turns", type=int, default=25,
                   help="agentic suite: tool-calling turns before the task is abandoned")
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("report", help="build a Markdown report from result files")
    s.add_argument("results", nargs="+")
    s.add_argument("--title", default="Benchmark report")
    s.add_argument("--question")
    s.add_argument("--verdict")
    s.add_argument("--notes", help="path to a Markdown file inserted as analysis")
    s.add_argument("--out")
    s.set_defaults(func=cmd_report)

    s = sub.add_parser("compare", help="swap the local vLLM between models and report (DGX box only)")
    common(s)
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
    s.set_defaults(func=cmd_compare)

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
                        "this run instead of using its configured providers "
                        "(default: BENCH_HARNESS_ENDPOINT; pi does not support it)")
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

    s = sub.add_parser("configs", help="list known-good serving configs")
    s.set_defaults(func=cmd_configs)

    s = sub.add_parser("apply", help="install a known-good config as the active launcher")
    s.add_argument("name", help="config name from `bench configs`")
    s.add_argument("--restart", action="store_true",
                   help="restart the vLLM service and wait until it serves")
    s.set_defaults(func=cmd_apply)

    argv = sys.argv[1:] if argv is None else list(argv)
    args = p.parse_args(argv)
    # `bench harness models` lists every installed harness; naming one narrows
    # it. argparse cannot tell a default from an explicit `--harness pi`.
    args.harness_explicit = any(a == "--harness" or a.startswith("--harness=")
                                for a in argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
