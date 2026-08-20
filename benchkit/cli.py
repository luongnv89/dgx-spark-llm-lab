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
from benchkit.suites import SUITES, DESCRIPTIONS, get  # noqa: E402

RESULTS = os.path.join(HERE, "results")


def _print_result(r):
    mark = "PASS" if r["passed"] else "FAIL"
    print(f"  {mark}  {r['task']:<20} s{r['sample']} "
          f"{r.get('completion_tokens') or 0:>6}tok "
          f"{(r.get('elapsed') or 0):6.1f}s "
          f"{(r.get('tok_s') or 0):5.1f}tok/s"
          + (f"   <{str(r.get('error'))[:70]}>" if not r["passed"] else ""), flush=True)


def cmd_suites(args):
    for name, tasks in SUITES.items():
        print(f"{name:<8} {len(tasks):>3} tasks   {DESCRIPTIONS[name]}")
        if args.verbose:
            for t in tasks:
                print(f"           {t['difficulty']:<7} {t['id']}")


def cmd_validate(args):
    """Prove every task's hidden tests pass against a reference solution."""
    tasks = get(args.suite)
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
    summary, results = runner.run(tasks, cfg, on_result=_print_result, keep_code=args.keep_code)

    out = args.out or os.path.join(RESULTS, _stamp(), f"{_slug(cfg.label)}.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as f:
        json.dump(dict(summary=summary, results=results), f, indent=2)

    print("\n" + "=" * 64)
    print(f"pass@1                 {summary['pass_at_1'] * 100:.1f} %")
    print(f"by difficulty          " + "  ".join(
        f"{k}={(v or 0) * 100:.1f}%" for k, v in summary["by_difficulty"].items()))
    print(f"wall                   {summary['wall_seconds']:.0f} s")
    print(f"mean output tokens     {summary['mean_completion_tokens'] or 0:.0f}")
    print(f"truncated / errored    {summary['truncated']} / {summary['errored']}")
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
                summary, results = runner.run(get(args.suite), cfg, on_result=_print_result)
                p = os.path.join(outdir, f"{_slug(label)}.json")
                with open(p, "w") as f:
                    json.dump(dict(summary=summary, results=results), f, indent=2)
                paths.append(p)
                print(f"  -> pass@1 {summary['pass_at_1'] * 100:.1f} %  ({p})", flush=True)
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
    s.add_argument("--no-restore", dest="restore", action="store_false",
                   help="leave the last model serving instead of restoring the original")
    s.set_defaults(func=cmd_compare)

    s = sub.add_parser("configs", help="list known-good serving configs")
    s.set_defaults(func=cmd_configs)

    s = sub.add_parser("apply", help="install a known-good config as the active launcher")
    s.add_argument("name", help="config name from `bench configs`")
    s.add_argument("--restart", action="store_true",
                   help="restart the vLLM service and wait until it serves")
    s.set_defaults(func=cmd_apply)

    args = p.parse_args(argv)
    return args.func(args) or 0


if __name__ == "__main__":
    raise SystemExit(main())
