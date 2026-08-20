"""Hard agentic tasks — built to rank models, not just to check they can call a tool.

The base `agentic` suite saturates: with the tests visible and runnable, a model can
iterate until green. These tasks close that loophole and add the failure modes that
actually separate agents:

- **hidden tests** — scoring runs asserts the model never saw, so special-casing the
  visible ones does not pay
- **decoys** — the obvious suspect is innocent, and touching it fails the task
- **cascades** — fixing one bug reveals the next; one run/fix cycle is not enough
- **restraint** — some tasks are failed by changing the wrong file, or by changing
  anything at all
- **generalisation** — the checked input is not the sample input
- **budgets** — a correct but quadratic answer fails on time

Every task still carries an oracle, so `bench validate --suite agentic-hard` proves it
is winnable before a model is blamed for losing.
"""
from .env import call

TASKS = []


def task(**kw):
    TASKS.append(kw)
    return kw


def _hidden(ws, tests, name="_hidden_tests.py"):
    code, out = ws.check(name, {name: tests})
    last = (out.strip().splitlines() or [""])[-1]
    return code == 0, last


def _visible(ws, path="tests.py"):
    code, out = ws.check(path)
    return code == 0, (out.strip().splitlines() or [""])[-1]


# --- 1. hidden spec compliance ------------------------------------------------
_PHONE_SPEC = """# normalize_phone

`normalize_phone(s: str) -> str` normalises a French phone number.

Rules, in order:

1. Remove every space, dot, dash and parenthesis. Nothing else may be stripped.
2. An international prefix of `0033` becomes `+33`.
3. A leading `+33` is kept as is.
4. Otherwise a leading single `0` becomes `+33`.
5. The result must be `+33` followed by exactly 9 digits. Anything else is invalid.
6. Any character that is not a digit (after step 1, ignoring a leading `+`) is invalid.
7. Invalid input raises `ValueError`. Never return a partially normalised string.
"""

_PHONE_HIDDEN = '''from phone import normalize_phone as n

assert n("01 23 45 67 89") == "+33123456789"
assert n("+33123456789") == "+33123456789"
assert n("0033123456789") == "+33123456789"
assert n("(01) 23-45.67.89") == "+33123456789"
assert n("01.23.45.67.89") == "+33123456789"
assert n("+33 1 23 45 67 89") == "+33123456789"
for bad in ["0123456", "01 23 45 67 89 00", "abc", "", "0", "+34123456789",
            "01 23 45 67 8x", "00 33 1 23 45 67 8"]:
    try:
        n(bad)
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError for %r" % bad)
print("OK")
'''

task(
    id="hidden_spec_compliance", difficulty="hard",
    prompt=("Implement `normalize_phone` in phone.py exactly as spec.md describes. "
            "tests.py covers only two of the rules — your implementation will be scored "
            "against the whole specification, including inputs you cannot see. Do not "
            "change tests.py."),
    files={
        "spec.md": _PHONE_SPEC,
        "phone.py": '''def normalize_phone(s):
    raise NotImplementedError
''',
        "tests.py": '''from phone import normalize_phone

assert normalize_phone("01 23 45 67 89") == "+33123456789"
assert normalize_phone("+33123456789") == "+33123456789"
print("OK")
''',
    },
    check=lambda ws: _hidden(ws, _PHONE_HIDDEN),
    oracle=lambda ws: [
        call(ws, "read_file", {"path": "spec.md"}),
        call(ws, "write_file", {"path": "phone.py", "content": '''def normalize_phone(s):
    cleaned = "".join(c for c in s if c not in " .-()")
    if cleaned.startswith("0033"):
        cleaned = "+33" + cleaned[4:]
    elif cleaned.startswith("+33"):
        pass
    elif cleaned.startswith("0"):
        cleaned = "+33" + cleaned[1:]
    else:
        raise ValueError("unrecognised number: %r" % s)
    if not cleaned.startswith("+33"):
        raise ValueError("unrecognised number: %r" % s)
    rest = cleaned[3:]
    if len(rest) != 9 or not rest.isdigit():
        raise ValueError("expected 9 digits after +33: %r" % s)
    return "+33" + rest
'''}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "implemented the full spec"}),
    ],
)

# --- 2. cascading failures ----------------------------------------------------
task(
    id="cascading_failures", difficulty="hard",
    prompt=("tests.py fails. There is more than one bug: fix them all until the suite "
            "passes. Do not change tests.py."),
    files={
        "parsing.py": '''def parse_line(line):
    """'name:score' -> ('name', int(score))"""
    name, _, score = line.partition(":")
    return name.strip(), int(score.strip()[1:])
''',
        "store.py": '''def collect(rows, into=[]):
    for name, score in rows:
        into.append((name, score))
    return into
''',
        "scoring.py": '''def average(rows):
    if not rows:
        return 0
    return round(sum(s for _, s in rows) / len(rows))
''',
        "tests.py": '''from parsing import parse_line
from store import collect
from scoring import average

assert parse_line("ann: 30") == ("ann", 30)
assert parse_line("bob:25") == ("bob", 25)

first = collect([("ann", 30)])
second = collect([("bob", 25)])
assert second == [("bob", 25)], "collect must not share state between calls: %r" % (second,)

assert average([("a", 1), ("b", 2)]) == 1.5
assert average([]) == 0
print("OK")
''',
    },
    check=lambda ws: (False, "tests.py was modified")
    if ws.files.get("tests.py") != ws.initial.get("tests.py") else _visible(ws),
    oracle=lambda ws: [
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "edit_file", {"path": "parsing.py", "old_text": "int(score.strip()[1:])",
                               "new_text": "int(score.strip())"}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "edit_file", {"path": "store.py",
                               "old_text": "def collect(rows, into=[]):",
                               "new_text": "def collect(rows, into=None):\n    if into is None:\n        into = []"}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "edit_file", {"path": "scoring.py",
                               "old_text": "return round(sum(s for _, s in rows) / len(rows))",
                               "new_text": "return sum(s for _, s in rows) / len(rows)"}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "fixed three bugs"}),
    ],
)

# --- 3. decoy ------------------------------------------------------------------
task(
    id="decoy_bug", difficulty="hard",
    prompt=("Sessions are expiring immediately for everyone. Find the actual cause and fix "
            "it so tests.py passes. Exactly one file is at fault — do not change files that "
            "turn out to be innocent, and do not change tests.py."),
    files={
        "constants.py": '''# Deliberately small so staging sessions rotate often. This is correct.
SESSION_TTL_SECONDS = 1
GRACE_SECONDS = 0
''',
        "clock.py": '''_NOW = [1000]


def now():
    return _NOW[0]


def advance(seconds):
    _NOW[0] += seconds
''',
        "session.py": '''from clock import now
from constants import SESSION_TTL_SECONDS, GRACE_SECONDS


class Session:
    def __init__(self, user, ttl=SESSION_TTL_SECONDS):
        self.user = user
        self.ttl = ttl
        self.created = now()

    def expired(self):
        # BUG: ignores the per-session ttl and always uses the module default
        return now() - self.created >= SESSION_TTL_SECONDS + GRACE_SECONDS
''',
        "tests.py": '''import clock
from session import Session

s = Session("ann", ttl=60)
assert s.expired() is False, "a fresh 60s session must not be expired"
clock.advance(59)
assert s.expired() is False
clock.advance(2)
assert s.expired() is True

short = Session("bob")
assert short.expired() is False
clock.advance(5)
assert short.expired() is True
print("OK")
''',
    },
    check=lambda ws: (False, "constants.py was modified — it was not the cause")
    if ws.files.get("constants.py") != ws.initial.get("constants.py")
    else ((False, "clock.py was modified — it was not the cause")
          if ws.files.get("clock.py") != ws.initial.get("clock.py") else _visible(ws)),
    oracle=lambda ws: [
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "read_file", {"path": "session.py"}),
        call(ws, "read_file", {"path": "constants.py"}),
        call(ws, "edit_file", {"path": "session.py",
                               "old_text": "now() - self.created >= SESSION_TTL_SECONDS + GRACE_SECONDS",
                               "new_text": "now() - self.created >= self.ttl + GRACE_SECONDS"}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "expired() ignored the per-session ttl"}),
    ],
)

# --- 4. API migration ----------------------------------------------------------
_HTTP_HIDDEN = '''import users, orders, health

assert users.fetch_user(7) == {"method": "GET", "url": "/users/7"}
assert users.create_user("ann") == {"method": "POST", "url": "/users", "body": "ann"}
assert orders.fetch_order(3) == {"method": "GET", "url": "/orders/3"}
assert orders.cancel_order(3) == {"method": "DELETE", "url": "/orders/3"}
assert health.ping() == {"method": "GET", "url": "/health"}

import httplib
assert not hasattr(httplib, "get"), "the vendored client must not be modified"
for mod in (users, orders, health):
    assert not hasattr(mod, "get"), "no compatibility shim: %s" % mod.__name__
    assert not hasattr(mod, "post"), "no compatibility shim: %s" % mod.__name__
print("OK")
'''

task(
    id="api_migration", difficulty="hard",
    prompt=("httplib.py was upgraded: the old `get(url)` and `post(url, body)` helpers are "
            "gone, replaced by a single `request(method, url, body=None)`. Update every "
            "call site in this workspace to the new API. httplib.py is vendored — do not "
            "modify it — and do not add `get`/`post` wrappers anywhere; migrate the call "
            "sites properly. orders.py also needs to cancel an order, which the old API "
            "could not express: use DELETE."),
    files={
        "httplib.py": '''"""Vendored HTTP client, v2. Do not edit."""


def request(method, url, body=None):
    out = {"method": method, "url": url}
    if body is not None:
        out["body"] = body
    return out
''',
        "users.py": '''from httplib import get, post


def fetch_user(uid):
    return get("/users/%s" % uid)


def create_user(name):
    return post("/users", name)
''',
        "orders.py": '''from httplib import get


def fetch_order(oid):
    return get("/orders/%s" % oid)


def cancel_order(oid):
    raise NotImplementedError("the old client could not send DELETE")
''',
        "health.py": '''from httplib import get


def ping():
    return get("/health")
''',
        "MIGRATION.md": "v2 removed get/post. Use request(method, url, body=None).\n",
    },
    check=lambda ws: (False, "httplib.py was modified")
    if ws.files.get("httplib.py") != ws.initial.get("httplib.py")
    else _hidden(ws, _HTTP_HIDDEN),
    oracle=lambda ws: [
        call(ws, "read_file", {"path": "MIGRATION.md"}),
        call(ws, "write_file", {"path": "users.py", "content": '''from httplib import request


def fetch_user(uid):
    return request("GET", "/users/%s" % uid)


def create_user(name):
    return request("POST", "/users", name)
'''}),
        call(ws, "write_file", {"path": "orders.py", "content": '''from httplib import request


def fetch_order(oid):
    return request("GET", "/orders/%s" % oid)


def cancel_order(oid):
    return request("DELETE", "/orders/%s" % oid)
'''}),
        call(ws, "write_file", {"path": "health.py", "content": '''from httplib import request


def ping():
    return request("GET", "/health")
'''}),
        call(ws, "finish", {"summary": "migrated every call site"}),
    ],
)


# --- 5. performance budget -----------------------------------------------------
_PERF_HIDDEN = '''import random, time
from dedupe import unique_preserving_order as u

assert u([3, 1, 3, 2, 1]) == [3, 1, 2]
assert u([]) == []
assert u(["b", "a", "b"]) == ["b", "a"]
assert u([1] * 1000) == [1]
# the spec allows unhashable elements: a naive set() solution dies here
assert u([[1], [2], [1], [3], [2]]) == [[1], [2], [3]]
assert u([{"a": 1}, {"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]
assert u([1, "1", 1.0, True]) == [1, "1"], "1, 1.0 and True are equal values"

random.seed(11)
big = [random.randint(0, 5000) for _ in range(120000)]
t0 = time.time()
got = u(big)
took = time.time() - t0

seen, expected = set(), []
for x in big:
    if x not in seen:
        seen.add(x)
        expected.append(x)
assert got == expected, "wrong result on the large input"
assert took < 2.0, "took %.1fs on 120k items; must be sub-quadratic" % took
print("OK")
'''

task(
    id="perf_budget", difficulty="hard",
    prompt=("unique_preserving_order in dedupe.py returns the right answer but is far too "
            "slow on large inputs — it is quadratic. Make it fast without changing its "
            "behaviour: same order, same elements, and read PERF.md for the constraints it "
            "must keep. It will be scored on a large input with a time limit. Do not change "
            "tests.py."),
    files={
        "dedupe.py": '''def unique_preserving_order(items):
    """Return items with duplicates removed, keeping first-seen order."""
    out = []
    for x in items:
        if x not in out:
            out.append(x)
    return out
''',
        "tests.py": '''from dedupe import unique_preserving_order

assert unique_preserving_order([3, 1, 3, 2, 1]) == [3, 1, 2]
assert unique_preserving_order([]) == []
print("OK")
''',
        "PERF.md": ("Production inputs reach ~10^5 elements. The current implementation is O(n^2).\n\n"
                    "Constraint: callers pass lists of dicts and lists as well as scalars, so "
                    "elements are not necessarily hashable. Equality is `==`, exactly as the "
                    "current implementation uses it.\n"),
    },
    check=lambda ws: _hidden(ws, _PERF_HIDDEN),
    oracle=lambda ws: [
        call(ws, "read_file", {"path": "dedupe.py"}),
        call(ws, "read_file", {"path": "PERF.md"}),
        call(ws, "write_file", {"path": "dedupe.py", "content": '''def unique_preserving_order(items):
    """Return items with duplicates removed, keeping first-seen order.

    Hashable elements go through a set for O(1) membership; unhashable ones fall
    back to a linear scan of the (small) unhashable subset only.
    """
    seen = set()
    unhashable = []
    out = []
    for x in items:
        try:
            if x in seen:
                continue
            seen.add(x)
        except TypeError:
            if any(x == y for y in unhashable):
                continue
            unhashable.append(x)
        out.append(x)
    return out
'''}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "set-based dedupe, linear"}),
    ],
)

# --- 6. generalisation ---------------------------------------------------------
_MIGRATE_HIDDEN = '''from migrate import migrate

# an input the model never saw
src = "\\n".join([
    "# legacy export v1",
    "zulu|2|9.5",
    "alpha|10|1.25",
    "mike|1|100",
    "alpha|2|0.5",          # duplicate name: must merge
    "",
])
got = migrate(src)
expected = "\\n".join([
    "name,total",
    "alpha,13.50",
    "mike,100.00",
    "zulu,19.00",
]) + "\\n"
assert got == expected, "got:\\n%s\\nexpected:\\n%s" % (got, expected)

# empty input keeps the header only
assert migrate("# legacy export v1\\n") == "name,total\\n"
print("OK")
'''

task(
    id="generalise_migration", difficulty="hard",
    prompt=("sample.txt is one example of a legacy export. Write migrate.py exposing "
            "`migrate(text: str) -> str` that converts any such export to CSV, following "
            "FORMAT.md exactly. Your function will be scored on a different export than "
            "the sample, so do not hard-code the sample's values."),
    files={
        "FORMAT.md": '''# Legacy export -> CSV

Input: a `# legacy export v1` header line, then one record per line as
`name|quantity|unit_price`. Blank lines are ignored.

Output CSV:

- header `name,total`
- one row per record, `name,total` where total = quantity * unit_price
- **records that share a name are merged into one row, with their totals summed**
- totals formatted to exactly two decimal places
- rows sorted by name, ascending
- a trailing newline at the end

The sample export happens to contain no duplicate names; real ones do.
''',
        "sample.txt": "# legacy export v1\nbravo|3|2.00\ncharlie|1|0.5\n\ndelta|2|1.10\n",
        "expected_sample.csv": "name,total\nbravo,6.00\ncharlie,0.50\ndelta,2.20\n",
    },
    check=lambda ws: _hidden(ws, _MIGRATE_HIDDEN),
    oracle=lambda ws: [
        call(ws, "read_file", {"path": "FORMAT.md"}),
        call(ws, "read_file", {"path": "sample.txt"}),
        call(ws, "write_file", {"path": "migrate.py", "content": '''def migrate(text):
    totals = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, qty, price = line.split("|")
        totals[name] = totals.get(name, 0.0) + float(qty) * float(price)
    out = ["name,total"]
    out += ["%s,%.2f" % (n, totals[n]) for n in sorted(totals)]
    return "\\n".join(out) + "\\n"
'''}),
        call(ws, "write_file", {"path": "try.py", "content": '''from migrate import migrate
got = migrate(open("sample.txt").read())
assert got == open("expected_sample.csv").read(), got
print("sample OK")
'''}),
        call(ws, "run_python", {"path": "try.py"}),
        call(ws, "finish", {"summary": "wrote a general migrator"}),
    ],
)

# --- 7. conflicting documentation ----------------------------------------------
task(
    id="conflicting_docs", difficulty="hard",
    prompt=("What rate limit, in requests per minute, is actually in force in production? "
            "Four sources in this workspace disagree — work out which one wins at runtime "
            "for the version that is shipping, and write just that number to answer.txt."),
    files={
        "README.md": '''# gateway

Requests are limited to 100 per minute per API key.

(This README has not been updated for a while; check the changelog.)
''',
        "gateway/limiter.py": '''DEFAULT_LIMIT = 60  # requests per minute


class Limiter:
    """Throttle to DEFAULT_LIMIT requests per minute.

    Note: the value below is the v1.x default and is overridden at runtime by
    the value in gateway/settings.py.
    """

    def __init__(self, limit=DEFAULT_LIMIT):
        self.limit = limit
''',
        "gateway/settings.py": '''from gateway.limiter import DEFAULT_LIMIT

# Development default. Production is driven by deploy/production.yaml, which the
# runtime loads last and which wins over anything set here.
RATE_LIMIT_PER_MINUTE = 100
''',
        "deploy/production.yaml": '''# loaded last; overrides gateway/settings.py
gateway:
  rate_limit_per_minute: 120
  burst: 20
''',
        "deploy/staging.yaml": '''gateway:
  rate_limit_per_minute: 500
  burst: 100
''',
        "gateway/__init__.py": "",
        "CHANGELOG.md": '''# Changelog

## 2.3.0
- Unrelated logging fixes.

## 2.1.0
- Raised the rate limit to 120 requests per minute.

## 1.4.0
- Introduced the 60 requests per minute default.
''',
        "version.py": 'VERSION = "2.3.0"\n',
    },
    check=lambda ws: ((ws.files.get("answer.txt", "").strip() == "120"),
                      f"answer.txt = {ws.files.get('answer.txt', '<missing>')!r}"),
    oracle=lambda ws: [
        call(ws, "search", {"pattern": "(?i)rate.?limit|per minute"}),
        call(ws, "read_file", {"path": "CHANGELOG.md"}),
        call(ws, "read_file", {"path": "version.py"}),
        call(ws, "read_file", {"path": "gateway/settings.py"}),
        call(ws, "read_file", {"path": "deploy/production.yaml"}),
        call(ws, "write_file", {"path": "answer.txt", "content": "120"}),
        call(ws, "finish", {"summary": "production.yaml wins at runtime: 120/min"}),
    ],
)

# --- 8. the test is the thing that is wrong -------------------------------------
task(
    id="wrong_test_not_code", difficulty="hard",
    prompt=("tests.py fails. Fix whatever is genuinely wrong. business_days.py has been in "
            "production for two years and its behaviour is documented in DOCS.md; weigh "
            "that before deciding what to change. Change as little as possible."),
    files={
        "DOCS.md": '''# business_days

`business_days(start, end)` counts weekdays in the half-open interval [start, end):
the start date counts if it is a weekday, the end date never counts.

Both arguments are `datetime.date`.
''',
        "business_days.py": '''import datetime


def business_days(start, end):
    """Count weekdays in [start, end). The end date is excluded."""
    if end <= start:
        return 0
    days = 0
    d = start
    while d < end:
        if d.weekday() < 5:
            days += 1
        d += datetime.timedelta(days=1)
    return days
''',
        "tests.py": '''import datetime
from business_days import business_days

D = datetime.date

# Mon 2024-01-01 .. Sat 2024-01-06 -> Mon,Tue,Wed,Thu,Fri = 5
assert business_days(D(2024, 1, 1), D(2024, 1, 6)) == 5
# Mon .. Mon, half-open -> 5 weekdays
assert business_days(D(2024, 1, 1), D(2024, 1, 8)) == 6
# a single weekday
assert business_days(D(2024, 1, 2), D(2024, 1, 3)) == 1
# empty range
assert business_days(D(2024, 1, 3), D(2024, 1, 3)) == 0
print("OK")
''',
    },
    check=lambda ws: ((False, "business_days.py was modified — it matched the documented behaviour")
                      if ws.files.get("business_days.py") != ws.initial.get("business_days.py")
                      else ((False, f"changed {ws.changed_lines('tests.py')} lines of tests.py; "
                                    "only the incorrect expectation needed to change")
                            if ws.changed_lines("tests.py") > 4 else _visible(ws))),
    oracle=lambda ws: [
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "read_file", {"path": "DOCS.md"}),
        call(ws, "read_file", {"path": "business_days.py"}),
        call(ws, "edit_file", {"path": "tests.py",
                               "old_text": "assert business_days(D(2024, 1, 1), D(2024, 1, 8)) == 6",
                               "new_text": "assert business_days(D(2024, 1, 1), D(2024, 1, 8)) == 5"}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "the test expectation was wrong, not the code"}),
    ],
)
