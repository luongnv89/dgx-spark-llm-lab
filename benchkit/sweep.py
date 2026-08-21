"""Sweep an explicit matrix of setups — serving config x harness x thinking mode.

A "setup" on this machine is three things at once: which serving recipe the
endpoint runs, which harness wraps the model, and whether thinking is on. Only
the model axis was ever automated (`bench compare`), so a "best setup" verdict
was measuring one axis of three (issue #57).

Three deliberate choices shape this module.

**The matrix is explicit, never a cross-product.** Independent `--configs` and
`--harnesses` flags would multiply into combinations that cannot exist -- a
llama.cpp recipe driven by the vLLM systemd unit, a harness pointed at a model
its provider does not serve. Each `--setup` names one real combination.

**Iteration is grouped by serving config.** Engine init costs minutes, so the
endpoint is swapped once per distinct config and every setup that needs that
config runs while it is up -- not once per combination.

**Every swap is gated and every swap is undone.** Restarting a shared endpoint
needs explicit human approval (CLAUDE.md), so an un-approved sweep refuses to
start rather than asking forgiveness; and the launcher that was active when the
sweep began is put back on the way out, on success *and* on failure, without the
restore ever masking the exception that caused the failure (issue #37).
"""
import os
from dataclasses import dataclass, replace

#: label for runs that use benchkit's own tool-calling loop rather than a harness
BUILTIN = "built-in loop"

#: what the operator must type to approve restarting a shared endpoint
APPROVAL_WORD = "yes"

_KEYS = ("config", "harness", "model", "thinking", "label")
_TRUE = ("on", "1", "true", "yes", "y")
_FALSE = ("off", "0", "false", "no", "n")


@dataclass(frozen=True)
class Setup:
    """One row of the sweep: a serving config, a harness, a model, a mode."""

    config: str = ""    # serving-config name; "" means "whatever is running now"
    harness: str = ""   # harness name; "" means benchkit's built-in loop
    model: str = ""     # model spec for the harness, or the served alias
    thinking: bool = False
    label: str = ""

    @property
    def harness_name(self):
        return self.harness or BUILTIN

    @property
    def config_name(self):
        return self.config or "(active launcher)"

    def resolved_label(self, default_model=""):
        if self.label:
            return self.label
        model = (self.model or default_model or "?").split("/")[-1]
        return (f"{self.config or 'active'} {self.harness or 'builtin'} "
                f"{model} think-{'ON' if self.thinking else 'OFF'}")


def parse_setup(text):
    """`config=a,harness=opencode,model=x,thinking=both` -> [Setup, ...].

    `thinking=both` expands to two setups because thinking and non-thinking are
    different products and must never be collapsed into one row.
    """
    fields, thinking = {}, [False]
    for part in str(text).split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(
                f"bad --setup field {part!r}: expected key=value with keys "
                + ", ".join(_KEYS))
        key, _, value = part.partition("=")
        key, value = key.strip().lower(), value.strip()
        if key not in _KEYS:
            raise SystemExit(f"unknown --setup key {key!r}; have: " + ", ".join(_KEYS))
        if key in fields:
            raise SystemExit(f"--setup key {key!r} given twice in {text!r}")
        if key == "thinking":
            low = value.lower()
            if low == "both":
                thinking = [False, True]
            elif low in _TRUE:
                thinking = [True]
            elif low in _FALSE:
                thinking = [False]
            else:
                raise SystemExit(
                    f"bad thinking={value!r}; use on, off or both")
            fields[key] = value
        else:
            fields[key] = value
    base = Setup(config=fields.get("config", ""), harness=fields.get("harness", ""),
                 model=fields.get("model", ""), label=fields.get("label", ""))
    if len(thinking) > 1 and base.label:
        # one label cannot name two products
        return [replace(base, thinking=t, label=f"{base.label} think-{'ON' if t else 'OFF'}")
                for t in thinking]
    return [replace(base, thinking=t) for t in thinking]


def parse_setups(specs, known_harnesses=(), default_model=""):
    """Parse every --setup, validate harness names, and reject duplicate rows."""
    setups = []
    for spec in specs or []:
        setups.extend(parse_setup(spec))
    if not setups:
        raise SystemExit("a sweep needs at least one --setup "
                         "(e.g. --setup config=qwen3.6-35b-a3b-nvfp4,thinking=both)")
    if known_harnesses:
        for s in setups:
            if s.harness and s.harness not in known_harnesses:
                raise SystemExit(f"unknown harness {s.harness!r} in --setup; have: "
                                 + ", ".join(known_harnesses))
    seen_keys, seen_slugs = set(), set()
    for s in setups:
        key = (s.config, s.harness, s.model, s.thinking)
        label = s.resolved_label(default_model)
        # dedupe on the *slug*, because that is what becomes the filename: two
        # labels that differ only in punctuation would otherwise collide hours
        # into a sweep, after a restart nobody can take back.
        slug = _slug(label)
        if key in seen_keys or slug in seen_slugs:
            raise SystemExit(f"duplicate setup {label!r}: two rows of a sweep would "
                             "write the same result file. Give one of them label=...")
        seen_keys.add(key)
        seen_slugs.add(slug)
    return setups


def group_by_config(setups):
    """[(config_name, [setup, ...]), ...] -- one group per *distinct* config.

    First-appearance order is preserved so the operator can read the restart
    plan off their own command line. The grouping is what keeps a six-setup
    sweep down to one endpoint restart per config instead of six.
    """
    order, groups = [], {}
    for s in setups:
        if s.config not in groups:
            groups[s.config] = []
            order.append(s.config)
        groups[s.config].append(s)
    return [(c, groups[c]) for c in order]


def configs_needing_swap(setups):
    """Distinct serving configs this sweep would install, in visit order."""
    return [c for c, _ in group_by_config(setups) if c]


def check_sweepable(setups, serving):
    """Fail early, and by name, on setups naming a config the sweep cannot drive.

    `configs/` holds recipes for other engines and other units (llama.cpp, the
    secondary gemma backend, the env-tunable standalone server). They are
    perfectly good recipes; they are simply not drivable by the vLLM systemd
    machinery this sweep restarts, so naming one is a user error reported
    before anything is touched -- never a crash halfway through.
    """
    ok, skipped = serving.sweepable_configs()
    names = {n for n, _, _ in ok}
    reasons = {n: why for n, _, why in skipped}
    bad = []
    for c in configs_needing_swap(setups):
        if c in names:
            continue
        why = reasons.get(c) or "no such config"
        bad.append(f"  {c}: {why}")
    if bad:
        raise SystemExit(
            "these setups name serving configs this sweep cannot drive:\n"
            + "\n".join(bad)
            + "\n\nsweepable configs: " + (", ".join(sorted(names)) or "(none)")
            + "\nRun `bench configs` for the full list and each skip reason.")


def plan(setups, default_model=""):
    """Human-readable dry-run text: what would run, and what would restart."""
    lines = []
    groups = group_by_config(setups)
    swaps = [c for c, _ in groups if c]
    restarts = f"{_n(len(swaps), 'endpoint restart')}"
    if swaps:
        restarts += (f", plus one more to restore the original serving config"
                     f" — {len(swaps) + 1} in total")
    lines.append(f"{_n(len(setups), 'setup')} in "
                 f"{_n(len(groups), 'serving-config group')} "
                 f"({restarts})")
    for cname, group in groups:
        lines.append(f"\n  serving config: {cname or '(active launcher, no swap)'}")
        for s in group:
            lines.append(f"    - {s.resolved_label(default_model)}"
                         f"   [harness={s.harness_name}"
                         f" thinking={'ON' if s.thinking else 'OFF'}]")
    return "\n".join(lines)


def result_paths(setups, outdir, default_model=""):
    """Where every row of this matrix would write, in run order.

    Exposed so a caller can check the whole matrix against an existing campaign
    *before* the first restart: discovering a collision after an hour of runs
    throws away work that cost a shared endpoint two restarts to produce.
    """
    return [os.path.join(outdir, _slug(s.resolved_label(default_model)) + ".json")
            for s in setups]


def approve_restart(configs, assume_yes=False, stdin=None, stdout=None, log=print):
    """Gate every endpoint restart behind an explicit, recorded approval.

    CLAUDE.md: *never restart a shared serving endpoint without explicit human
    approval*. Default is to refuse -- a non-interactive sweep that was not
    given `--yes-restart-endpoint` stops before it writes a single byte to the
    launcher, rather than treating silence as consent.

    The number quoted to the operator is the *true* total: one restart per
    distinct config to install it, plus one final restart to put the original
    serving config back (see `_restore`) -- `len(configs) + 1`.
    """
    import sys
    if not configs:
        return True
    plan_txt = ", ".join(configs)
    if assume_yes:
        log(f"restart approved by --yes-restart-endpoint: {plan_txt}")
        return True
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    if not (hasattr(stdin, "isatty") and stdin.isatty()):
        raise SystemExit(
            f"this sweep would restart the shared serving endpoint "
            f"{len(configs) + 1} time(s): {len(configs)} to install "
            f"{plan_txt}, and one more to restore the original serving config "
            f"afterwards.\n"
            "Restarting a shared endpoint needs explicit human approval, and this "
            "session is not interactive.\n"
            "Re-run with --yes-restart-endpoint once the endpoint is genuinely "
            "yours to restart, or drop config= from every --setup to sweep only "
            "the harness and thinking axes against whatever is already serving.")
    print(f"\nThis sweep will restart the shared serving endpoint "
          f"{len(configs) + 1} time(s): {len(configs)} to install {plan_txt}, "
          f"and one more to restore the original serving config afterwards.",
          file=stdout)
    print("Anyone else using the endpoint will lose it for several minutes per "
          "restart.", file=stdout)
    print(f"Type {APPROVAL_WORD!r} to approve, anything else to abort: ",
          end="", file=stdout)
    stdout.flush()
    answer = (stdin.readline() or "").strip().lower()
    if answer != APPROVAL_WORD:
        raise SystemExit("endpoint restart not approved — nothing was changed.")
    log(f"restart approved interactively: {plan_txt}")
    return True


def snapshot_launcher(serving):
    """Remember the active launcher verbatim so it can be put back byte-for-byte."""
    with open(serving.LAUNCHER, "rb") as f:
        return f.read()


def restore_launcher(snapshot, serving):
    """Rewrite the launcher from the snapshot. True if it actually changed."""
    if snapshot is None:
        return False
    with open(serving.LAUNCHER, "rb") as f:
        if f.read() == snapshot:
            return False
    with open(serving.LAUNCHER, "wb") as f:
        f.write(snapshot)
    os.chmod(serving.LAUNCHER, 0o755)
    return True


def _restore(snapshot, serving, restart, log, swallow):
    """Put the original config back. `swallow` protects an in-flight exception.

    On the failure path the restore must never replace the exception the
    operator actually needs to read (issue #37), so it degrades to a loud
    warning instead of raising.
    """
    try:
        if restore_launcher(snapshot, serving) and restart:
            log("restarting the endpoint on the original serving config...")
            serving.restart()
    except BaseException as exc:  # noqa: BLE001 — see docstring
        if not swallow:
            raise
        log(f"WARNING: could not restore the original serving config: {exc!r}")
        log("  the endpoint may still be running a sweep config — check "
            "`bench configs` and restore it by hand.")
        return False
    return True


def run_sweep(setups, outdir, execute, serving, assume_yes=False, restart=True,
              stdin=None, stdout=None, log=print, default_model=""):
    """Execute every setup, one endpoint restart per distinct serving config.

    Plus one final restart to reinstate the original serving config, so a sweep
    over N distinct configs costs the shared endpoint N+1 restarts.

    `execute(setup, label)` runs one row and returns `(summary, results)`; the
    caller owns how a row is run so this function stays testable without an
    endpoint. Returns the list of result files written, in run order.

    `restart=False` is only meaningful for a matrix that swaps no config at all
    -- see the guard below.
    """
    import json

    check_sweepable(setups, serving)
    groups = group_by_config(setups)
    swaps = [c for c, _ in groups if c]
    if swaps and not restart:
        # Installing a recipe without restarting leaves the endpoint serving the
        # *previous* config while every result file claims the new one. Those
        # files would then be indelible: results/ is append-only.
        raise SystemExit(
            "a setup naming config= cannot run without restarting the endpoint: "
            "the launcher would change but the endpoint would keep serving the "
            "previous config, and every result file would name the wrong one.\n"
            "Use --dry-run to rehearse the matrix, or drop config= to measure "
            "whatever is already serving.")
    approve_restart(swaps, assume_yes=assume_yes, stdin=stdin, stdout=stdout, log=log)

    os.makedirs(outdir, exist_ok=True)
    snapshot = snapshot_launcher(serving) if swaps else None
    paths = []
    try:
        for cname, group in groups:
            if cname:
                log(f"\n=== installing serving config {cname} ===")
                path, model_id = serving.apply_config(cname)
                log(f"  {os.path.basename(path)} -> launcher, model {model_id}")
                if restart:
                    log("  restarting the service; engine init takes minutes...")
                    serving.restart()
            for s in group:
                label = s.resolved_label(default_model)
                log(f"\n--- {label} ---")
                summary, results = execute(s, label)
                p = os.path.join(outdir, _slug(label) + ".json")
                if os.path.exists(p):
                    # backstop: callers check the whole matrix up front (see
                    # result_paths), but results/ is append-only, so a colliding
                    # name is a bug, never a licence to overwrite a campaign.
                    raise SystemExit(f"refusing to overwrite an existing result "
                                     f"file: {p}")
                with open(p, "w") as f:
                    json.dump(dict(summary=summary, results=results), f, indent=2)
                paths.append(p)
                log(f"  -> written to {p}")
    except BaseException:
        if snapshot is not None:
            log("\nsweep failed — restoring the original serving config")
            _restore(snapshot, serving, restart, log, swallow=True)
        raise
    if snapshot is not None:
        log("\nrestoring the original serving config")
        _restore(snapshot, serving, restart, log, swallow=False)
    return paths


def _n(count, noun):
    return f"{count} {noun}" + ("" if count == 1 else "s")


def _slug(s):
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in s.lower()).strip("-")
