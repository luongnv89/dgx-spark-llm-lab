"""Task suites. A suite is a list of dicts: id, difficulty, prompt, tests.

`tests` is Python source appended after the model's code and executed; it must
raise on failure. Every task has a reference solution in benchkit.references,
so `bench validate` can prove the tests are passable before blaming a model.
"""
from .core16 import TASKS as CORE16
from .hard12 import TASKS as HARD12

SUITES = {
    "core16": CORE16,
    "hard12": HARD12,
    "all": CORE16 + HARD12,
}

DESCRIPTIONS = {
    "core16": "16 general coding tasks — algorithms, data structures, parsing, Python idiom",
    "hard12": "12 hard tasks — built when core16 saturated; parsers, DP, cron, bigint, transactions",
    "all": "core16 + hard12, 28 tasks",
}


def get(name):
    if name not in SUITES:
        raise SystemExit(f"unknown suite {name!r}; choose from {', '.join(SUITES)}")
    return SUITES[name]
