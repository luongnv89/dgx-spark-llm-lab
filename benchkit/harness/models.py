"""Choosing which model a harness runs.

This benchmark is only useful to someone else if it can be pointed at *their*
setup: the providers and models they have already configured in opencode or pi,
authenticated however they authenticate. So model selection is a first-class
step rather than a hard-coded default.

Two modes, and the difference is worth stating plainly because it decides what
is being measured:

- **existing setup** (no `--endpoint`): the harness resolves the model through
  its own catalogue and credentials. `list_models()` enumerates it, so a typo is
  answered with the list of real choices instead of a `ProviderModelNotFound`
  error a second into every task.
- **explicit endpoint** (`--endpoint`): the harness is pointed at an
  OpenAI-compatible server for this run only. The catalogue does not apply — the
  model id is whatever that server reports — so the spec is taken literally.
"""
import sys

#: shown when a catalogue is long enough that dumping it would bury the message
MAX_LISTED = 60


class ModelSpecError(SystemExit):
    """Bad or absent model selection: a user error, reported before any run."""


def catalogue(harness):
    """[(provider, model)] the harness can reach, or [] if it cannot enumerate.

    Empty means "unknown", never "nothing available" — a harness that has no
    listing command still runs fine with an explicitly named model.
    """
    try:
        return [(str(p), str(m)) for p, m in harness.list_models()]
    except Exception:  # noqa: BLE001 — enumeration is best-effort by design
        return []


def spec(provider, model):
    return f"{provider}/{model}" if provider else model


def resolve(text, entries, provider=None):
    """Map a user-typed spec onto one (provider, model) from `entries`.

    Accepts `provider/model`, a bare model id, or any unique substring of
    either, so `--model qwen3-coder` finds `ollama/qwen3-coder:latest`.
    """
    text = (text or "").strip()
    if not text:
        raise ModelSpecError("no model selected")
    if not entries:
        return _split(text, provider)

    pool = entries
    if provider:
        scoped = [e for e in entries if e[0] == provider]
        if not scoped:
            raise ModelSpecError(
                f"provider {provider!r} is not configured here.\n"
                + _table(entries))
        pool = scoped

    exact = [e for e in pool if spec(*e) == text or e[1] == text]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        raise ModelSpecError(f"{text!r} matches several models — say which:\n"
                             + _table(exact))

    lowered = text.lower()
    near = [e for e in pool if lowered in spec(*e).lower()]
    if len(near) == 1:
        return near[0]
    if len(near) > 1:
        raise ModelSpecError(f"{text!r} matches several models — say which:\n"
                             + _table(near))
    raise ModelSpecError(f"no model matching {text!r} in this setup.\n"
                         + _table(pool))


def pick(harness_name, entries, stdin=None, stdout=None):
    """Ask for a model at benchmark time; fall back to a listing error.

    Interactive selection is the point of the feature — you run the benchmark,
    you choose which of *your* models it measures — but it must never hang a
    scripted or CI run, so a non-tty gets the list and a non-zero exit instead.
    """
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    hint = (f"pass --model <provider/model>, or set BENCH_HARNESS_MODEL "
            f"(see `bench harness models --harness {harness_name}`)")
    if not entries:
        raise ModelSpecError(f"no model selected for {harness_name}, and it "
                             f"cannot list its own models; {hint}")
    if not (hasattr(stdin, "isatty") and stdin.isatty()):
        raise ModelSpecError(f"no model selected for {harness_name}; {hint}\n"
                             + _table(entries))

    print(f"\nmodels available to {harness_name}:", file=stdout)
    for i, e in enumerate(entries[:MAX_LISTED], 1):
        print(f"  {i:>3}) {spec(*e)}", file=stdout)
    if len(entries) > MAX_LISTED:
        print(f"  ... and {len(entries) - MAX_LISTED} more", file=stdout)
    try:
        answer = input(f"select model [1-{min(len(entries), MAX_LISTED)}]: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise ModelSpecError("\nno model selected") from None
    if not answer:
        return entries[0]
    if answer.isdigit() and 1 <= int(answer) <= min(len(entries), MAX_LISTED):
        return entries[int(answer) - 1]
    return resolve(answer, entries)


def _split(text, provider=None):
    """No catalogue to match against: take the spec at its word."""
    if provider:
        return provider, text
    if "/" in text:
        head, tail = text.split("/", 1)
        return head, tail
    return None, text


def _table(entries):
    lines = [f"  {spec(*e)}" for e in entries[:MAX_LISTED]]
    if len(entries) > MAX_LISTED:
        lines.append(f"  ... and {len(entries) - MAX_LISTED} more")
    return "\n".join(lines) or "  (none)"
