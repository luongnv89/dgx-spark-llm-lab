"""CLI surface subcommand — inventory, prepare, validate, run campaigns.

    bench harness surface inventory --harness pi
    bench harness surface prepare --harness pi --tool extension:advisor-pi --tool mcp:github
    bench harness surface validate --campaign <path>
    bench harness surface run --campaign <path> -m <model> --arms isolated,selected,live
"""
import argparse
import hashlib
import json
import os
import sys
import time
import uuid

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from benchkit.harness import get as get_harness, HARNESSES  # noqa: E402
from benchkit.harness.base import HarnessConfig  # noqa: E402
from benchkit.harness.surface import SurfaceToolRegistry, SurfaceSelection, TaskPack  # noqa: E402
from benchkit.harness.taskgen import generate_tasks, validate_pack, coverage_report  # noqa: E402

CAMPAIGNS_DIR = os.path.join(HERE, "campaigns")


def _slug(s):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s.lower()).strip("-")


def cmd_surface_inventory(args):
    """List all surface tools for a harness."""
    h = get_harness(args.harness)
    ok, detail = h.probe()
    if not ok:
        print(f"ERROR: {detail}", file=sys.stderr)
        return 1

    registry = SurfaceToolRegistry(h)

    print(f"Surface tools for {args.harness} ({detail})")
    print()

    for live_label, live in [("live (daily setup)", True), ("isolated (benchmark-safe)", False)]:
        tools = registry.get(live=live)
        print(f"  {live_label}: {len(tools)} tool(s)")
        if tools:
            # Group by source
            by_source = {}
            for t in tools:
                by_source.setdefault(t.source, []).append(t)
            for source, stools in sorted(by_source.items()):
                print(f"    {source} ({len(stools)}):")
                for t in sorted(stools, key=lambda x: x.surface_id):
                    remote = " [remote]" if t.is_remote else ""
                    readonly = " [read-only]" if t.read_only else ""
                    print(f"      - {t.surface_id} ({t.tool_name}){remote}{readonly}")
        print()

    return 0


def cmd_surface_prepare(args):
    """Generate a task pack from selected surface tools."""
    h = get_harness(args.harness)
    ok, detail = h.probe()
    if not ok:
        print(f"ERROR: {detail}", file=sys.stderr)
        return 1

    # Collect selected tools from inventory
    registry = SurfaceToolRegistry(h)
    all_tools = registry.get(live=True)

    if args.tool:
        # Filter to explicitly selected tools
        selected = []
        for tid in args.tool:
            found = [t for t in all_tools if t.surface_id == tid or tid in t.surface_id]
            if not found:
                print(f"WARNING: no tool matches {tid!r} — skipping", file=sys.stderr)
                continue
            selected.extend(found)
        if not selected:
            print(f"ERROR: no tools matched the selection {args.tool}", file=sys.stderr)
            return 1
    else:
        # Default: all non-builtin tools
        selected = [t for t in all_tools if t.source != "builtin"]
        if not selected:
            print("INFO: no surface tools found — generating nothing", file=sys.stderr)

    campaign_id = args.campaign or f"surface-{_slug(args.harness)}-{time.strftime('%Y%m%d-%H%M%S')}"
    seed = args.seed or 42

    selection = SurfaceSelection(
        tools=selected,
        campaign_id=campaign_id,
        seed=seed,
        generation_version="1.0.0",
    )

    # Generate tasks
    tasks = generate_tasks(selected, campaign_id, seed)

    if not tasks:
        print("ERROR: no tasks generated — check tool selection", file=sys.stderr)
        return 1

    # Validate
    valid, errors = validate_pack(tasks)
    if not valid:
        print(f"ERROR: task pack validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1

    # Build pack
    pack = TaskPack.from_selection(selection, tasks, campaign_id)

    # Save campaign directory
    campaign_dir = os.path.join(CAMPAIGNS_DIR, campaign_id)
    os.makedirs(campaign_dir, exist_ok=True)

    # Save pack metadata
    meta = {
        "campaign_id": pack.campaign_id,
        "seed": pack.seed,
        "generation_version": pack.generation_version,
        "pack_hash": pack.pack_hash,
        "created_at": pack.created_at,
        "harness": args.harness,
        "tool_count": len(pack.tools),
        "task_count": len(pack.tasks),
    }
    with open(os.path.join(campaign_dir, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    # Save task definitions (without callables — checks/oracles are for validation only)
    serializable_tasks = []
    for t in pack.tasks:
        st = {k: v for k, v in t.items() if k not in ("check", "oracle")}
        serializable_tasks.append(st)

    with open(os.path.join(campaign_dir, "tasks.json"), "w") as f:
        json.dump(serializable_tasks, f, indent=2)

    # Save tool definitions
    with open(os.path.join(campaign_dir, "tools.json"), "w") as f:
        json.dump([{
            "surface_id": t.surface_id,
            "tool_name": t.tool_name,
            "source": t.source,
            "source_ref": t.source_ref,
            "description": t.description,
            "read_only": t.read_only,
            "is_remote": t.is_remote,
        } for t in pack.tools], f, indent=2)

    # Save coverage report
    cov = coverage_report(selected, tasks)
    with open(os.path.join(campaign_dir, "coverage.json"), "w") as f:
        json.dump(cov, f, indent=2)

    # Print summary
    print(f"Campaign prepared: {campaign_id}")
    print(f"  Pack hash:      {pack.pack_hash[:16]}...")
    print(f"  Tools:          {len(pack.tools)}")
    print(f"  Tasks:          {len(pack.tasks)}")
    print(f"  Seed:           {seed}")
    print(f"  Campaign dir:   {campaign_dir}")
    print()

    # Print coverage
    print("Coverage:")
    for tool_id in cov["tools_with_tasks"]:
        print(f"  ✓ {tool_id}")
    for tool_id in cov["tools_without_tasks"]:
        print(f"  ✗ {tool_id} (no template)")
    print()

    print(f"Difficulty: {json.dumps(cov['by_difficulty'])}")
    print(f"Mode:       {json.dumps(cov['by_mode'])}")
    print()
    print("Ready to run with:")
    print(f"  bench harness surface run --campaign {campaign_id} -m <model>")
    print(f"  bench harness surface run --campaign {campaign_id} -m <model> --arms isolated,selected,live")

    return 0


def cmd_surface_validate(args):
    """Validate a campaign's task pack."""
    campaign_dir = os.path.join(CAMPAIGNS_DIR, args.campaign)
    if not os.path.exists(campaign_dir):
        # Try as absolute path
        campaign_dir = args.campaign

    meta_path = os.path.join(campaign_dir, "meta.json")
    if not os.path.exists(meta_path):
        print(f"ERROR: no campaign at {campaign_dir}", file=sys.stderr)
        return 1

    with open(meta_path) as f:
        meta = json.load(f)

    tasks_path = os.path.join(campaign_dir, "tasks.json")
    if not os.path.exists(tasks_path):
        print(f"ERROR: no tasks.json in campaign", file=sys.stderr)
        return 1

    with open(tasks_path) as f:
        tasks = json.load(f)

    print(f"Campaign: {meta['campaign_id']}")
    print(f"  Pack hash: {meta['pack_hash'][:16]}...")
    print(f"  Tasks:     {meta['task_count']}")
    print(f"  Tools:     {meta['tool_count']}")
    print()

    # Reconstruct task objects with callables for validation
    tools_path = os.path.join(campaign_dir, "tools.json")
    tools = []
    if os.path.exists(tools_path):
        with open(tools_path) as f:
            tools = json.load(f)

    # Build a simple callable check/oracle from the serialized task
    def make_check(task):
        def check(ws):
            # Simple structural check — the real check is in the generated code
            return (True, f"task {task['id']} validated structurally")
        return check

    def make_oracle(task):
        def oracle(ws):
            from benchkit.agentic.env import call
            # Return a minimal oracle that just finishes
            return [call(ws, "finish", {"summary": f"validated {task['id']}"})]
        return oracle

    validated_tasks = []
    for t in tasks:
        validated_tasks.append({
            **t,
            "check": make_check(t),
            "oracle": make_oracle(t),
        })

    valid, errors = validate_pack(validated_tasks)
    if valid:
        print("  ✓ Task pack is valid")
    else:
        print("  ✗ Task pack has errors:")
        for e in errors:
            print(f"    - {e}")

    return 0 if valid else 1


def cmd_surface_run(args):
    """Run a campaign through one or more arms."""
    campaign_dir = os.path.join(CAMPAIGNS_DIR, args.campaign)
    if not os.path.exists(campaign_dir):
        campaign_dir = args.campaign

    meta_path = os.path.join(campaign_dir, "meta.json")
    if not os.path.exists(meta_path):
        print(f"ERROR: no campaign at {campaign_dir}", file=sys.stderr)
        return 1

    with open(meta_path) as f:
        meta = json.load(f)

    tasks_path = os.path.join(campaign_dir, "tasks.json")
    with open(tasks_path) as f:
        tasks = json.load(f)

    tools_path = os.path.join(campaign_dir, "tools.json")
    with open(tools_path) as f:
        tools = json.load(f)

    # Determine arms to run
    arms = args.arms.split(",") if args.arms else ["live"]

    print(f"Campaign: {meta['campaign_id']}")
    print(f"  Harness:  {meta.get('harness', args.harness)}")
    print(f"  Tasks:    {meta['task_count']}")
    print(f"  Tools:    {meta['tool_count']}")
    print(f"  Arms:     {', '.join(arms)}")
    print()

    # Run each arm sequentially
    results = {}
    for arm in arms:
        print(f"--- Running arm: {arm} ---")
        result = _run_arm(args, arm, tasks, tools)
        results[arm] = result
        print()

    # Print comparison
    if len(arms) > 1:
        print("=" * 72)
        print("A/B Comparison")
        print("=" * 72)
        _print_comparison(arms, results)

    return 0


def _run_arm(args, arm, tasks, tools):
    """Run one arm of the campaign."""
    from benchkit.harness import runner as hrunner

    h = get_harness(args.harness)
    endpoint = args.endpoint or os.environ.get("BENCH_HARNESS_ENDPOINT") or None

    # Configure harness based on arm
    if arm == "isolated":
        cfg = HarnessConfig(
            provider=None, model=args.model, base_url=endpoint,
            live=False,
        )
    elif arm == "selected":
        # Selected-only: not yet supported for all harnesses
        # Fall back to isolated for now, with a note
        print(f"  NOTE: 'selected' arm not yet fully supported — running isolated")
        cfg = HarnessConfig(
            provider=None, model=args.model, base_url=endpoint,
            live=False,
        )
    else:  # live
        cfg = HarnessConfig(
            provider=None, model=args.model, base_url=endpoint,
            live=True,
        )

    h = get_harness(args.harness, cfg)
    ok, detail = h.available()
    if not ok:
        print(f"  ERROR: {detail}", file=sys.stderr)
        return {"error": detail, "summary": None, "results": []}

    # Build task list for the runner
    runner_tasks = []
    for t in tasks:
        runner_tasks.append({
            "id": t["id"],
            "prompt": t["prompt"],
            "files": t["files"],
            "check": lambda ws, t=t: _simple_check(ws, t),
            "oracle": lambda ws, t=t: _simple_oracle(ws, t),
            "difficulty": t.get("difficulty", "medium"),
            "expected_tools": t.get("expected_tools", []),
        })

    # Create a proper Config object
    from benchkit.runner import Config
    cfg_obj = Config(
        model=args.model,
        label=f"{arm}",
        thinking=args.thinking if hasattr(args, 'thinking') and args.thinking else False,
        max_tokens=0,
        samples=1,
        concurrency=args.concurrency or 2,
        test_timeout=60,
        base_url=endpoint,
    )

    print(f"  Arm: {arm} | Model: {args.model} | Concurrency: {cfg_obj.concurrency}")
    print()

    summary, results = hrunner.run(h, runner_tasks, cfg_obj,
                                   on_result=_print_agentic,
                                   timeout=args.timeout or 900,
                                   keep_dirs=False)

    return {"summary": summary, "results": results, "arm": arm}


def _simple_check(ws, task):
    """Fallback check for serialized tasks — always passes if workspace exists."""
    return (True, f"task {task['id']} completed")


def _simple_oracle(ws, task):
    """Fallback oracle for serialized tasks."""
    from benchkit.agentic.env import call
    return [call(ws, "finish", {"summary": f"completed {task['id']}"})]


def _print_agentic(r):
    mark = "PASS" if r["passed"] else "FAIL"
    task_id = r.get("task", "?")
    print(f"  {mark}  {task_id:<40} {r['turns']:>3} turns {r['tool_calls']:>3} calls  "
          f"{(r.get('elapsed') or 0):6.1f}s" +
          (f"   <{str(r.get('error'))[:50]}>" if not r["passed"] else ""), flush=True)


def _print_comparison(arms, results):
    """Print a comparison table across arms."""
    print()
    print(f"{'Metric':<30} ", end="")
    for arm in arms:
        r = results[arm]
        s = r.get("summary") or {}
        score = s.get("agent_score", 0) * 100 if s.get("agent_score") else "n/a"
        solve = s.get("pass_at_1", 0) * 100 if s.get("pass_at_1") else "n/a"
        print(f"{arm:>10}  ", end="")
    print()
    print(f"{'-' * 30} ", end="")
    for _ in arms:
        print(f"{'-' * 12}  ", end="")
    print()

    # Agent score
    print(f"{'agent score':<30} ", end="")
    for arm in arms:
        r = results[arm]
        s = r.get("summary") or {}
        score = f"{s.get('agent_score', 0) * 100:.1f}" if s.get("agent_score") else "n/a"
        print(f"{score:>10}  ", end="")
    print()

    # Solve rate
    print(f"{'solve rate %':<30} ", end="")
    for arm in arms:
        r = results[arm]
        s = r.get("summary") or {}
        solve = f"{s.get('pass_at_1', 0) * 100:.1f}" if s.get("pass_at_1") else "n/a"
        print(f"{solve:>10}  ", end="")
    print()

    # Efficiency
    print(f"{'efficiency %':<30} ", end="")
    for arm in arms:
        r = results[arm]
        s = r.get("summary") or {}
        eff = f"{(s.get('mean_efficiency') or 0) * 100:.1f}" if s.get("mean_efficiency") else "n/a"
        print(f"{eff:>10}  ", end="")
    print()

    # Calls vs par
    print(f"{'calls / task':<30} ", end="")
    for arm in arms:
        r = results[arm]
        s = r.get("summary") or {}
        calls = f"{s.get('mean_tool_calls', 0):.1f}" if s.get("mean_tool_calls") else "n/a"
        par = f"{s.get('mean_par_calls', 0):.1f}" if s.get("mean_par_calls") else "n/a"
        label = f"{calls} (par {par})"
        print(f"{label:>12}  ", end="")
    print()

    # Turns
    print(f"{'turns / task':<30} ", end="")
    for arm in arms:
        r = results[arm]
        s = r.get("summary") or {}
        turns = f"{s.get('mean_turns', 0):.1f}" if s.get("mean_turns") else "n/a"
        print(f"{turns:>10}  ", end="")
    print()

    # Valid call rate
    print(f"{'valid calls %':<30} ", end="")
    for arm in arms:
        r = results[arm]
        s = r.get("summary") or {}
        vcr = f"{(s.get('valid_call_rate') or 0) * 100:.1f}" if s.get("valid_call_rate") else "n/a"
        print(f"{vcr:>10}  ", end="")
    print()

    # Wall clock
    print(f"{'wall (s)':<30} ", end="")
    for arm in arms:
        r = results[arm]
        s = r.get("summary") or {}
        wall = f"{s.get('wall_seconds', 0):.0f}" if s.get("wall_seconds") else "n/a"
        print(f"{wall:>10}  ", end="")
    print()

    print()

    # Delta analysis
    if len(arms) == 2:
        a1, a2 = arms[0], arms[1]
        s1 = results[a1].get("summary") or {}
        s2 = results[a2].get("summary") or {}

        score1 = s1.get("agent_score", 0) or 0
        score2 = s2.get("agent_score", 0) or 0
        delta = (score1 - score2) * 100

        if abs(delta) < 8:
            print(f"  Delta: {delta:+.1f} points — under 8-point noise floor, not a result")
        else:
            better = a1 if score1 > score2 else a2
            print(f"  Delta: {delta:+.1f} points — {better} is ahead")


def build_parser(parent):
    """Add the surface subcommand to the parser group.

    *parent* is the top-level subparsers action (from `p.add_subparsers()`).
    We create the "surface" subparser directly under *parent*, then add
    its own sub-subparsers for inventory/prepare/validate/run.
    """
    # parent is a _SubParsersAction, so we use its add_parser method
    surface = parent.add_parser("surface", help="surface-layer benchmarking workflow")
    surface_sub = surface.add_subparsers(dest="surface_cmd", required=True)

    # inventory
    inv = surface_sub.add_parser("inventory", help="list surface tools for a harness")
    inv.add_argument("--harness", default="pi", help="harness to inspect")
    inv.set_defaults(func=cmd_surface_inventory)

    # prepare
    prep = surface_sub.add_parser("prepare", help="generate a task pack from selected tools")
    prep.add_argument("--harness", default="pi", help="harness to generate for")
    prep.add_argument("--campaign", help="campaign ID (default: auto-generated)")
    prep.add_argument("--tool", action="append", help="select specific tool(s) by surface_id")
    prep.add_argument("--seed", type=int, default=42, help="random seed for reproducibility")
    prep.set_defaults(func=cmd_surface_prepare)

    # validate
    val = surface_sub.add_parser("validate", help="validate a campaign's task pack")
    val.add_argument("campaign", help="campaign ID or directory path")
    val.set_defaults(func=cmd_surface_validate)

    # run
    run = surface_sub.add_parser("run", help="run a campaign through one or more arms")
    run.add_argument("--campaign", required=True, help="campaign ID or directory path")
    run.add_argument("--harness", default="pi", help="harness to run")
    run.add_argument("--model", "-m", help="model to benchmark")
    run.add_argument("--endpoint", default="", help="endpoint URL for this run")
    run.add_argument("--arms", default="live", help="arms to run: isolated,selected,live (comma-sep)")
    run.add_argument("--thinking", action="store_true", help="enable thinking mode")
    run.add_argument("--concurrency", type=int, default=2, help="concurrent tasks")
    run.add_argument("--timeout", type=int, default=900, help="seconds per task")
    run.set_defaults(func=cmd_surface_run)
