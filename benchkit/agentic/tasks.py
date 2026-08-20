"""Agentic tasks: a workspace, a goal, and a predicate over the final state.

A task is solved when `check(ws)` returns ok — never by what the model claims in
prose. Each task also carries an `oracle`, a scripted sequence of tool calls that
solves it, so `bench validate --suite agentic` can prove the task is winnable
before any model is blamed for losing.
"""
from .env import call


def _passes(ws, path="tests.py"):
    code, out = ws.check(path)
    return code == 0, (out.strip().splitlines() or [""])[-1]


TASKS = []


def task(**kw):
    TASKS.append(kw)
    return kw


# --- 1 -----------------------------------------------------------------------
task(
    id="fix_divide_bug", difficulty="easy",
    prompt=("The test suite in tests.py is failing. Find out why and fix the bug in the "
            "source file. Do not change tests.py."),
    files={
        "calc.py": '''def add(a, b):
    return a + b


def divide(a, b):
    return a / b


def average(values):
    return divide(add_all(values), len(values))


def add_all(values):
    total = 0
    for v in values:
        total = add(total, v)
    return total
''',
        "tests.py": '''from calc import divide, average

assert divide(10, 2) == 5
assert divide(9, 3) == 3
assert divide(1, 0) is None, "dividing by zero must return None, not raise"
assert average([1, 2, 3]) == 2
print("OK")
''',
    },
    check=lambda ws: _passes(ws) if ws.files.get("tests.py", "").count("assert") == 4
    else (False, "tests.py was modified"),
    oracle=lambda ws: [
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "read_file", {"path": "calc.py"}),
        call(ws, "edit_file", {"path": "calc.py",
                               "old_text": "def divide(a, b):\n    return a / b",
                               "new_text": "def divide(a, b):\n    if b == 0:\n        return None\n    return a / b"}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "guarded divide against zero"}),
    ],
)

# --- 2 -----------------------------------------------------------------------
task(
    id="add_missing_function", difficulty="easy",
    prompt=("tests.py imports a function that does not exist yet. Implement it in the "
            "module it is imported from, so the tests pass."),
    files={
        "textutil.py": '''def slugify(s):
    return "-".join(s.lower().split())
''',
        "tests.py": '''from textutil import slugify, titlecase

assert slugify("Hello World") == "hello-world"
assert titlecase("hello world") == "Hello World"
assert titlecase("the QUICK brown") == "The Quick Brown"
assert titlecase("") == ""
print("OK")
''',
    },
    check=lambda ws: _passes(ws),
    oracle=lambda ws: [
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "read_file", {"path": "tests.py"}),
        call(ws, "write_file", {"path": "textutil.py",
                                "content": 'def slugify(s):\n    return "-".join(s.lower().split())\n\n\n'
                                           'def titlecase(s):\n    return " ".join(w.capitalize() for w in s.split())\n'}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "added titlecase"}),
    ],
)

# --- 3 -----------------------------------------------------------------------
task(
    id="rename_across_files", difficulty="hard",
    prompt=("Rename the function `fetch_data` to `load_data` everywhere in this workspace, "
            "including every call site. tests.py already expects the new name; do not "
            "change tests.py."),
    files={
        "source.py": '''def fetch_data(name):
    """Return a fake record for name."""
    return {"name": name, "size": len(name)}
''',
        "pipeline.py": '''from source import fetch_data


def summarise(names):
    return [fetch_data(n)["size"] for n in names]
''',
        "report.py": '''from source import fetch_data
from pipeline import summarise


def describe(name):
    row = fetch_data(name)
    return f"{row['name']}={row['size']}"


def totals(names):
    return sum(summarise(names))
''',
        "tests.py": '''from source import load_data
from report import describe, totals

assert load_data("abc")["size"] == 3
assert describe("abcd") == "abcd=4"
assert totals(["a", "bb"]) == 3
print("OK")
''',
    },
    check=lambda ws: (False, "fetch_data still present") if any(
        "fetch_data" in v for k, v in ws.files.items() if k != "tests.py") else _passes(ws),
    oracle=lambda ws: [
        call(ws, "search", {"pattern": "fetch_data"}),
        call(ws, "edit_file", {"path": "source.py", "old_text": "def fetch_data(name):",
                               "new_text": "def load_data(name):"}),
        call(ws, "edit_file", {"path": "pipeline.py", "old_text": "from source import fetch_data",
                               "new_text": "from source import load_data"}),
        call(ws, "edit_file", {"path": "pipeline.py", "old_text": "fetch_data(n)",
                               "new_text": "load_data(n)"}),
        call(ws, "edit_file", {"path": "report.py", "old_text": "from source import fetch_data",
                               "new_text": "from source import load_data"}),
        call(ws, "edit_file", {"path": "report.py", "old_text": "row = fetch_data(name)",
                               "new_text": "row = load_data(name)"}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "renamed everywhere"}),
    ],
)

# --- 4 -----------------------------------------------------------------------
task(
    id="find_bug_by_search", difficulty="medium",
    prompt=("Customers report that shipping totals are too high. One constant in this "
            "workspace is wrong: standard shipping must cost 4.99, not 9.99. Find it and "
            "fix it so tests.py passes. Do not change tests.py."),
    files={
        "config/rates.py": '''TAX_RATE = 0.2
CURRENCY = "EUR"
''',
        "config/__init__.py": "",
        "shipping/costs.py": '''STANDARD = 9.99
EXPRESS = 14.99
FREE_THRESHOLD = 50.0
''',
        "shipping/__init__.py": "",
        "shipping/calc.py": '''from shipping.costs import STANDARD, EXPRESS, FREE_THRESHOLD


def shipping_for(subtotal, express=False):
    if subtotal >= FREE_THRESHOLD:
        return 0.0
    return EXPRESS if express else STANDARD
''',
        "tests.py": '''from shipping.calc import shipping_for

assert shipping_for(10) == 4.99
assert shipping_for(10, express=True) == 14.99
assert shipping_for(60) == 0.0
print("OK")
''',
    },
    check=lambda ws: _passes(ws),
    oracle=lambda ws: [
        call(ws, "search", {"pattern": "9\\.99"}),
        call(ws, "edit_file", {"path": "shipping/costs.py", "old_text": "STANDARD = 9.99",
                               "new_text": "STANDARD = 4.99"}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "fixed the standard rate"}),
    ],
)

# --- 5 -----------------------------------------------------------------------
task(
    id="recover_from_bad_path", difficulty="medium",
    prompt=("Read the retry limit out of config/settings.py and write it, as a bare number "
            "and nothing else, to answer.txt."),
    files={
        "settings.py": '''SERVICE_NAME = "billing"
RETRY_LIMIT = 7
TIMEOUT_SECONDS = 30
''',
        "notes.md": "The settings module lives at the top level of the project.\n",
    },
    check=lambda ws: ((ws.files.get("answer.txt", "").strip() == "7"),
                      f"answer.txt = {ws.files.get('answer.txt', '<missing>')!r}"),
    oracle=lambda ws: [
        call(ws, "read_file", {"path": "config/settings.py"}),   # fails on purpose
        call(ws, "list_files", {}),
        call(ws, "read_file", {"path": "settings.py"}),
        call(ws, "write_file", {"path": "answer.txt", "content": "7"}),
        call(ws, "finish", {"summary": "wrote the retry limit"}),
    ],
)

# --- 6 -----------------------------------------------------------------------
task(
    id="implement_from_spec", difficulty="hard",
    prompt=("Create csvlite.py implementing the behaviour that tests.py expects, then make "
            "the tests pass. Do not change tests.py."),
    files={
        "tests.py": '''from csvlite import parse_csv, to_csv

rows = parse_csv("name,age\\nann,30\\nbob,25\\n")
assert rows == [{"name": "ann", "age": "30"}, {"name": "bob", "age": "25"}], rows

# quoted fields may contain commas and escaped quotes ("" means a literal ")
rows = parse_csv('a,b\\n"x,y","he said ""hi"""\\n')
assert rows == [{"a": "x,y", "b": 'he said "hi"'}], rows

assert parse_csv("a,b\\n") == []
assert to_csv([{"a": "1", "b": "2"}]) == "a,b\\n1,2\\n"
assert to_csv([{"a": "x,y"}]) == 'a\\n"x,y"\\n'
assert to_csv([]) == ""
print("OK")
''',
    },
    check=lambda ws: _passes(ws),
    oracle=lambda ws: [
        call(ws, "read_file", {"path": "tests.py"}),
        call(ws, "write_file", {"path": "csvlite.py", "content": _CSVLITE}),
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "implemented csvlite"}),
    ],
)

# --- 7 -----------------------------------------------------------------------
task(
    id="verify_no_change_needed", difficulty="medium",
    prompt=("A colleague thinks parse_duration is broken. Check whether tests.py passes. "
            "If it already passes, change nothing and say so. Only edit source files if "
            "there is a real failure."),
    files={
        "duration.py": '''def parse_duration(s):
    """'1h30m' -> 5400 seconds."""
    units = {"h": 3600, "m": 60, "s": 1}
    total = 0
    num = ""
    for ch in s:
        if ch.isdigit():
            num += ch
        elif ch in units:
            total += int(num or 0) * units[ch]
            num = ""
        else:
            raise ValueError(f"bad duration: {s}")
    return total
''',
        "tests.py": '''from duration import parse_duration

assert parse_duration("1h30m") == 5400
assert parse_duration("45s") == 45
assert parse_duration("2h") == 7200
assert parse_duration("") == 0
try:
    parse_duration("5x")
except ValueError:
    pass
else:
    raise AssertionError("bad unit must raise")
print("OK")
''',
    },
    check=lambda ws: ((False, "source was modified when nothing was wrong")
                      if ws.files.get("duration.py") != ws.initial.get("duration.py")
                      else _passes(ws)),
    oracle=lambda ws: [
        call(ws, "run_python", {"path": "tests.py"}),
        call(ws, "finish", {"summary": "tests already pass; no change needed"}),
    ],
)

# --- 8 -----------------------------------------------------------------------
task(
    id="multi_step_pipeline", difficulty="hard",
    prompt=("sales.csv holds one order per line as region,amount. Write and run a script "
            "that computes the total amount per region, then write the results to "
            "totals.txt as one 'region=total' line per region, sorted by region, with "
            "totals formatted to two decimal places."),
    files={
        "sales.csv": "north,10.50\nsouth,3.25\nnorth,4.50\neast,7.00\nsouth,1.75\n",
        "README.md": "Amounts are decimal euros. Regions are lowercase.\n",
    },
    check=lambda ws: ((ws.files.get("totals.txt", "").strip()
                       == "east=7.00\nnorth=15.00\nsouth=5.00"),
                      f"totals.txt = {ws.files.get('totals.txt', '<missing>')!r}"),
    oracle=lambda ws: [
        call(ws, "read_file", {"path": "sales.csv"}),
        call(ws, "write_file", {"path": "sum.py", "content": _SUMSCRIPT}),
        call(ws, "run_python", {"path": "sum.py"}),   # the script writes totals.txt itself
        call(ws, "finish", {"summary": "wrote totals"}),
    ],
)


_CSVLITE = '''def parse_csv(text):
    lines = _split_rows(text)
    if not lines:
        return []
    header = lines[0]
    return [dict(zip(header, row)) for row in lines[1:]]


def _split_rows(text):
    rows, row, field, i, quoted = [], [], "", 0, False
    while i < len(text):
        c = text[i]
        if quoted:
            if c == '"':
                if i + 1 < len(text) and text[i + 1] == '"':
                    field += '"'
                    i += 1
                else:
                    quoted = False
            else:
                field += c
        elif c == '"':
            quoted = True
        elif c == ",":
            row.append(field)
            field = ""
        elif c == "\\n":
            row.append(field)
            rows.append(row)
            row, field = [], ""
        else:
            field += c
        i += 1
    if field or row:
        row.append(field)
        rows.append(row)
    return rows


def to_csv(rows):
    if not rows:
        return ""
    header = list(rows[0])
    out = [",".join(_quote(h) for h in header)]
    for r in rows:
        out.append(",".join(_quote(str(r[h])) for h in header))
    return "\\n".join(out) + "\\n"


def _quote(v):
    if any(c in v for c in ',"\\n'):
        return '"' + v.replace('"', '""') + '"'
    return v
'''

_SUMSCRIPT = '''totals = {}
for line in open("sales.csv"):
    line = line.strip()
    if not line:
        continue
    region, amount = line.split(",")
    totals[region] = totals.get(region, 0.0) + float(amount)
out = "\\n".join(f"{r}={totals[r]:.2f}" for r in sorted(totals))
open("totals.txt", "w").write(out)
print(out)
'''
