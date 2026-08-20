"""Harder coding tasks to discriminate models that saturate the 2026-08-17 suite.

Same schema as coding-bench-2026-08-17/tasks.py: id / difficulty / prompt / tests.
Every task's tests are proven passable by validate_hard.py.
"""

TASKS = [
    dict(
        id="regex_match", difficulty="hard",
        prompt=(
            "Write a Python function `is_match(s: str, p: str) -> bool` implementing regular "
            "expression matching over the *entire* string `s` with support for '.' (matches any "
            "single character) and '*' (matches zero or more of the *preceding* element). "
            "Do not use the `re` module."
        ),
        tests="""
assert is_match('aa', 'a') is False
assert is_match('aa', 'a*') is True
assert is_match('ab', '.*') is True
assert is_match('aab', 'c*a*b') is True
assert is_match('mississippi', 'mis*is*p*.') is False
assert is_match('mississippi', 'mis*is*ip*i') is True
assert is_match('', '.*') is True
assert is_match('', 'a*b*c*') is True
assert is_match('abc', '') is False
assert is_match('', '') is True
assert is_match('aaa', 'a*a') is True
assert is_match('ab', '.*c') is False
""",
    ),
    dict(
        id="weighted_intervals", difficulty="hard",
        prompt=(
            "Write a Python function `max_weight_schedule(jobs: list[tuple[int, int, int]]) -> int` "
            "where each job is (start, end, weight) with start < end. Select a subset of "
            "non-overlapping jobs maximising total weight and return that maximum weight. "
            "A job ending at time t and another starting at t do NOT overlap. Must run in "
            "O(n log n); an O(2^n) search will time out on the tests."
        ),
        tests="""
assert max_weight_schedule([]) == 0
assert max_weight_schedule([(1,2,5)]) == 5
assert max_weight_schedule([(1,3,5),(2,5,6),(4,6,5)]) == 10
assert max_weight_schedule([(1,2,50),(3,5,20),(6,19,100),(2,100,200)]) == 250
assert max_weight_schedule([(0,1,1),(1,2,1),(2,3,1),(3,4,1)]) == 4
assert max_weight_schedule([(1,10,1),(2,3,5),(4,5,5),(6,7,5)]) == 15
import random
random.seed(7)
big = []
for _ in range(4000):
    a = random.randint(0, 100000); b = a + random.randint(1, 500)
    big.append((a, b, random.randint(1, 100)))
r = max_weight_schedule(big)
assert isinstance(r, int) and r > 0
""",
    ),
    dict(
        id="json5_parse", difficulty="hard",
        prompt=(
            "Write a Python function `parse_relaxed(text: str)` that parses a relaxed JSON dialect "
            "into Python objects. On top of standard JSON it must accept: // line comments and "
            "/* block */ comments anywhere whitespace is allowed; trailing commas in objects and "
            "arrays; single-quoted strings; and unquoted object keys matching [A-Za-z_][A-Za-z0-9_]*. "
            "Standard escapes (\\n, \\t, \\\\, \\\", \\', \\/) must work inside strings. Raise "
            "`ValueError` on malformed input or on trailing non-whitespace after the top-level value. "
            "Do not use the `json` module."
        ),
        tests="""
assert parse_relaxed('{"a": 1}') == {'a': 1}
assert parse_relaxed("{a: 1, b: [1,2,3,],}") == {'a': 1, 'b': [1,2,3]}
assert parse_relaxed("// lead\\n{ 'x' : 'y' } // tail") == {'x': 'y'}
assert parse_relaxed('{ /* c */ "k" /* c */ : /* c */ true }') == {'k': True}
assert parse_relaxed('[1, -2.5, 1e3, null, false]') == [1, -2.5, 1000.0, None, False]
assert parse_relaxed('"a\\\\nb"') == 'a\\nb'
assert parse_relaxed("'it\\\\'s'") == "it's"
assert parse_relaxed('  {}  ') == {}
assert parse_relaxed('[]') == []
for bad in ['{a: }', '[1,,2]', '{1: 2}', '{"a": 1} junk', '{"a" 1}', "'unterminated", '[1']:
    try:
        parse_relaxed(bad)
    except ValueError:
        pass
    else:
        raise AssertionError('should have raised: ' + bad)
""",
    ),
    dict(
        id="topo_batches", difficulty="hard",
        prompt=(
            "Write a Python function `topo_batches(deps: dict[str, list[str]]) -> list[list[str]]`. "
            "`deps` maps a node to the list of nodes it depends on (its prerequisites). Return the "
            "nodes grouped into the minimum number of sequential batches such that every node appears "
            "after all of its prerequisites; each batch is sorted alphabetically and the batches are "
            "in execution order. Nodes that appear only inside dependency lists are also part of the "
            "graph. Raise `ValueError` if the graph has a cycle."
        ),
        tests="""
assert topo_batches({}) == []
assert topo_batches({'a': []}) == [['a']]
assert topo_batches({'b': ['a'], 'c': ['a'], 'd': ['b','c']}) == [['a'], ['b','c'], ['d']]
assert topo_batches({'x': ['y']}) == [['y'], ['x']]
assert topo_batches({'a': [], 'b': [], 'c': []}) == [['a','b','c']]
assert topo_batches({'d': ['c'], 'c': ['b'], 'b': ['a'], 'a': []}) == [['a'],['b'],['c'],['d']]
try:
    topo_batches({'a': ['b'], 'b': ['a']})
except ValueError:
    pass
else:
    raise AssertionError('cycle not detected')
try:
    topo_batches({'a': ['a']})
except ValueError:
    pass
else:
    raise AssertionError('self cycle not detected')
""",
    ),
    dict(
        id="wrap_min_raggedness", difficulty="hard",
        prompt=(
            "Write a Python function `wrap_text(words: list[str], width: int) -> list[str]` that "
            "breaks `words` into lines of at most `width` characters (words joined by single spaces) "
            "minimising the sum over all lines *except the last* of (width - len(line))**2. Return the "
            "lines. Any word longer than `width` goes alone on its own line and contributes no cost. "
            "Break ties by preferring the packing whose first line is longest."
        ),
        tests="""
assert wrap_text([], 10) == []
assert wrap_text(['hello'], 10) == ['hello']
assert wrap_text(['aaa','bb','cc','ddddd'], 6) == ['aaa', 'bb cc', 'ddddd']
assert wrap_text(['supercalifragilistic','a'], 5) == ['supercalifragilistic', 'a']
out = wrap_text('the quick brown fox jumps over the lazy dog'.split(), 12)
assert all(len(l) <= 12 for l in out)
assert ' '.join(out).split() == 'the quick brown fox jumps over the lazy dog'.split()
assert out == ['the quick', 'brown fox', 'jumps over', 'the lazy dog']
""",
    ),
    dict(
        id="unify", difficulty="hard",
        prompt=(
            "Implement first-order unification. Terms are: a variable, represented as "
            "`('var', name)`; or a compound, represented as `(functor_name, arg1, arg2, ...)` where "
            "functor_name is a str that is not 'var' and args are terms (a constant is a compound "
            "with no args). Write `unify(t1, t2) -> dict | None` returning the most general unifier "
            "as a dict mapping variable names to terms, fully resolved (no variable in a substituted "
            "value may itself be bound by the unifier), or None if the terms do not unify. "
            "Implement the occurs check: unifying ('var','X') with ('f', ('var','X')) returns None."
        ),
        tests="""
V = lambda n: ('var', n)
assert unify(('a',), ('a',)) == {}
assert unify(('a',), ('b',)) is None
assert unify(V('X'), ('a',)) == {'X': ('a',)}
assert unify(('f', V('X')), ('f', ('a',))) == {'X': ('a',)}
assert unify(('f', V('X'), V('Y')), ('f', ('a',), ('b',))) == {'X': ('a',), 'Y': ('b',)}
assert unify(('f', V('X'), V('X')), ('f', ('a',), ('b',))) is None
assert unify(('f', V('X')), ('g', V('X'))) is None
assert unify(('f', V('X'), ('a',)), ('f', ('a',), V('Y'))) == {'X': ('a',), 'Y': ('a',)}
assert unify(V('X'), ('f', V('X'))) is None
assert unify(('f', V('X'), V('Y')), ('f', V('Y'), ('a',))) == {'X': ('a',), 'Y': ('a',)}
assert unify(('f', V('X')), ('f', V('X'))) == {}
assert unify(('f', ('a',)), ('f', ('a',), ('b',))) is None
u = unify(('f', V('X'), V('Z')), ('f', ('g', V('Y')), ('h', V('X'))))
assert u == {'X': ('g', V('Y')), 'Z': ('h', ('g', V('Y')))}
""",
    ),
    dict(
        id="range_module", difficulty="hard",
        prompt=(
            "Implement a Python class `RangeModule` tracking a set of half-open intervals [left, right). "
            "Methods: `add_range(left, right)`, `query_range(left, right) -> bool` (True iff every real "
            "number in [left, right) is currently tracked), and `remove_range(left, right)`. Ranges must "
            "be kept merged internally; adjacent added ranges coalesce."
        ),
        tests="""
r = RangeModule()
r.add_range(10, 20)
r.remove_range(14, 16)
assert r.query_range(10, 14) is True
assert r.query_range(13, 15) is False
assert r.query_range(16, 17) is True
r2 = RangeModule()
r2.add_range(1, 5); r2.add_range(5, 10)
assert r2.query_range(1, 10) is True
r2.remove_range(3, 4)
assert r2.query_range(1, 10) is False
assert r2.query_range(1, 3) is True and r2.query_range(4, 10) is True
r3 = RangeModule()
assert r3.query_range(1, 2) is False
r3.add_range(1, 100); r3.remove_range(50, 60); r3.add_range(55, 58)
assert r3.query_range(55, 58) is True
assert r3.query_range(54, 58) is False
assert r3.query_range(1, 50) is True
r3.remove_range(0, 1000)
assert r3.query_range(1, 2) is False
""",
    ),
    dict(
        id="cron_next", difficulty="hard",
        prompt=(
            "Write a Python function `next_run(expr: str, after: datetime.datetime) -> datetime.datetime` "
            "that returns the earliest datetime strictly after `after` matching a 5-field cron expression "
            "`minute hour day-of-month month day-of-week` (day-of-week: 0=Sunday..6=Saturday). Each field "
            "supports `*`, a number, comma lists, `a-b` ranges and `*/n` or `a-b/n` steps. When both "
            "day-of-month and day-of-week are restricted (neither is `*`) a day matches if EITHER "
            "matches, per Vixie cron. Seconds and microseconds of the result are always 0."
        ),
        tests="""
from datetime import datetime as DT
assert next_run('* * * * *', DT(2024,1,1,0,0,0)) == DT(2024,1,1,0,1)
assert next_run('* * * * *', DT(2024,1,1,0,0,30)) == DT(2024,1,1,0,1)
assert next_run('0 * * * *', DT(2024,1,1,0,0)) == DT(2024,1,1,1,0)
assert next_run('30 4 * * *', DT(2024,1,1,5,0)) == DT(2024,1,2,4,30)
assert next_run('*/15 * * * *', DT(2024,1,1,0,0)) == DT(2024,1,1,0,15)
assert next_run('0 0 1 * *', DT(2024,1,15,0,0)) == DT(2024,2,1,0,0)
assert next_run('0 0 * * 1', DT(2024,1,1,0,0)) == DT(2024,1,8,0,0)
assert next_run('0 0 29 2 *', DT(2024,3,1,0,0)) == DT(2028,2,29,0,0)
assert next_run('0 0 13 * 5', DT(2024,1,1,0,0)) == DT(2024,1,5,0,0)
assert next_run('0 12 1-7/3 * *', DT(2024,1,1,13,0)) == DT(2024,1,4,12,0)
assert next_run('5,35 8 * * *', DT(2024,6,10,8,10)) == DT(2024,6,10,8,35)
""",
    ),
    dict(
        id="bigint_div", difficulty="hard",
        prompt=(
            "Write a Python function `divmod_str(a: str, b: str) -> tuple[str, str]` performing long "
            "division on arbitrarily large non-negative integers given as decimal strings, returning "
            "(quotient, remainder) as decimal strings with no leading zeros ('0' for zero). You must "
            "implement the schoolbook algorithm digit by digit: converting the whole operand with "
            "`int(a)` is forbidden (converting a single character is fine). Raise `ZeroDivisionError` "
            "if `b` is zero."
        ),
        tests="""
assert divmod_str('0', '5') == ('0', '0')
assert divmod_str('10', '3') == ('3', '1')
assert divmod_str('100', '10') == ('10', '0')
assert divmod_str('7', '9') == ('0', '7')
assert divmod_str('000123', '3') == ('41', '0')
a = '9' * 200
b = '123456789'
import subprocess, sys
q, r = divmod_str(a, b)
assert (int(q), int(r)) == divmod(int(a), int(b))
q, r = divmod_str('1' + '0' * 100, '7')
assert (int(q), int(r)) == divmod(int('1' + '0' * 100), 7)
try:
    divmod_str('5', '0')
except ZeroDivisionError:
    pass
else:
    raise AssertionError('no ZeroDivisionError')
""",
    ),
    dict(
        id="tx_dict", difficulty="hard",
        prompt=(
            "Implement a Python class `TxDict` that behaves like a dict (support `__getitem__`, "
            "`__setitem__`, `__delitem__`, `__contains__`, `__len__`, `__iter__`, and `get`) and "
            "additionally supports nestable transactions via `begin()`, `commit()` and `rollback()`, "
            "plus use as a context manager: `with d.transaction():` commits on normal exit and rolls "
            "back if the block raises (the exception must still propagate). `commit()` or `rollback()` "
            "with no active transaction raises `RuntimeError`. Inner commits merge into the enclosing "
            "transaction, so rolling back an outer transaction also undoes committed inner ones."
        ),
        tests="""
d = TxDict()
d['a'] = 1
assert d['a'] == 1 and len(d) == 1 and 'a' in d
d.begin(); d['b'] = 2; d.rollback()
assert 'b' not in d and len(d) == 1
d.begin(); d['b'] = 2; d.commit()
assert d['b'] == 2
d.begin()
d['c'] = 3
d.begin(); d['d'] = 4; d.commit()
assert d['d'] == 4
d.rollback()
assert 'c' not in d and 'd' not in d
try:
    d.commit()
except RuntimeError:
    pass
else:
    raise AssertionError('commit outside tx should raise')
try:
    with d.transaction():
        d['x'] = 9
        raise ValueError('boom')
except ValueError:
    pass
assert 'x' not in d
with d.transaction():
    d['y'] = 10
assert d['y'] == 10
d.begin(); del d['a']; d.rollback()
assert d['a'] == 1
assert d.get('nope', 'dflt') == 'dflt'
assert sorted(d) == sorted(['a', 'b', 'y'])
""",
    ),
    dict(
        id="sql_select", difficulty="hard",
        prompt=(
            "Write a Python function `run_query(sql: str, rows: list[dict]) -> list[dict]` evaluating a "
            "tiny SQL SELECT over `rows`. Grammar: "
            "SELECT (* | col [AS alias] [, ...]) FROM t [WHERE cond] [ORDER BY col [ASC|DESC] [, ...]] "
            "[LIMIT n]. Conditions support comparisons =, !=, <, <=, >, >= against integer, float or "
            "single-quoted string literals, combined with AND / OR and grouped with parentheses; AND "
            "binds tighter than OR. Keywords are case-insensitive, column names are case-sensitive. "
            "The FROM table name is ignored. Output dicts contain only the selected columns, keyed by "
            "alias when given, in the order they were selected. Raise `ValueError` on a parse error."
        ),
        tests="""
R = [
    {'id': 1, 'name': 'ann', 'age': 30, 'city': 'paris'},
    {'id': 2, 'name': 'bob', 'age': 25, 'city': 'rome'},
    {'id': 3, 'name': 'cid', 'age': 35, 'city': 'paris'},
    {'id': 4, 'name': 'dee', 'age': 25, 'city': 'oslo'},
]
assert run_query('SELECT * FROM t WHERE age > 28', R) == [R[0], R[2]]
assert run_query('select name from t where city = \\'paris\\' order by name desc', R) == [{'name':'cid'},{'name':'ann'}]
assert run_query('SELECT id AS k FROM t LIMIT 2', R) == [{'k':1},{'k':2}]
assert run_query('SELECT name FROM t WHERE age = 25 OR city = \\'paris\\' ORDER BY id', R) == [{'name':'ann'},{'name':'bob'},{'name':'cid'},{'name':'dee'}]
assert run_query("SELECT name FROM t WHERE (city = 'paris' OR city = 'oslo') AND age < 31 ORDER BY id", R) == [{'name':'ann'},{'name':'dee'}]
assert run_query("SELECT name FROM t WHERE city = 'paris' AND age < 31 OR city = 'oslo' ORDER BY id", R) == [{'name':'ann'},{'name':'dee'}]
assert run_query('SELECT name, age FROM t ORDER BY age ASC, name DESC LIMIT 3', R) == [{'name':'dee','age':25},{'name':'bob','age':25},{'name':'ann','age':30}]
assert run_query('SELECT * FROM t WHERE age != 25 AND age != 35', R) == [R[0]]
assert run_query('SELECT * FROM t WHERE id >= 99', R) == []
for bad in ['SELECT FROM t', 'SELECT * t', 'SELECT * FROM t WHERE', 'SELECT * FROM t WHERE age >', 'SELECT * FROM t LIMIT']:
    try:
        run_query(bad, R)
    except ValueError:
        pass
    else:
        raise AssertionError('should raise: ' + bad)
""",
    ),
    dict(
        id="running_median", difficulty="medium",
        prompt=(
            "Implement a Python class `MedianStream` with `add(self, x: float) -> None` and "
            "`median(self) -> float` returning the median of all values added so far (mean of the two "
            "middle values when the count is even), and `remove(self, x: float) -> None` removing one "
            "occurrence of `x` (raise `ValueError` if absent). `add` and `median` must be efficient "
            "enough for 200000 additions; a full re-sort on every call will time out."
        ),
        tests="""
import random, time
m = MedianStream()
m.add(1); assert m.median() == 1
m.add(3); assert m.median() == 2
m.add(2); assert m.median() == 2
m.add(4); assert m.median() == 2.5
m.remove(1); assert m.median() == 3
try:
    m.remove(99)
except ValueError:
    pass
else:
    raise AssertionError('remove missing should raise')
random.seed(1)
m2 = MedianStream()
vals = []
t0 = time.time()
for _ in range(200000):
    v = random.random()
    m2.add(v); vals.append(v)
    if len(vals) % 20000 == 0:
        s = sorted(vals); n = len(s)
        exp = s[n//2] if n % 2 else (s[n//2-1]+s[n//2])/2
        assert abs(m2.median() - exp) < 1e-9
assert time.time() - t0 < 20
""",
    ),
]
