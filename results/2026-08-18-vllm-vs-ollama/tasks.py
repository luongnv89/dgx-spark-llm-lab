"""Coding benchmark tasks: prompt + hidden tests. Each test file gets the model's
code prepended, then runs asserts. Difficulty: easy / medium / hard."""

TASKS = [
    dict(
        id="two_sum", difficulty="easy",
        prompt="Write a Python function `two_sum(nums: list[int], target: int) -> list[int]` that returns the indices of the two numbers in `nums` that add up to `target`. Exactly one solution exists; you may not use the same element twice. Return the indices in ascending order.",
        tests="""
assert two_sum([2,7,11,15], 9) == [0,1]
assert two_sum([3,2,4], 6) == [1,2]
assert two_sum([3,3], 6) == [0,1]
assert two_sum([-1,-2,-3,-4,-5], -8) == [2,4]
""",
    ),
    dict(
        id="roman", difficulty="easy",
        prompt="Write a Python function `int_to_roman(num: int) -> str` converting an integer (1..3999) to a Roman numeral string.",
        tests="""
assert int_to_roman(1) == 'I'
assert int_to_roman(4) == 'IV'
assert int_to_roman(9) == 'IX'
assert int_to_roman(58) == 'LVIII'
assert int_to_roman(1994) == 'MCMXCIV'
assert int_to_roman(3999) == 'MMMCMXCIX'
""",
    ),
    dict(
        id="balanced", difficulty="easy",
        prompt="Write a Python function `is_balanced(s: str) -> bool` returning True if the brackets '()', '[]', '{}' in `s` are correctly balanced and nested. Non-bracket characters are ignored.",
        tests="""
assert is_balanced('') is True
assert is_balanced('()[]{}') is True
assert is_balanced('(]') is False
assert is_balanced('([{}])') is True
assert is_balanced('a(b[c]d)e') is True
assert is_balanced('(()') is False
assert is_balanced(')(') is False
""",
    ),
    dict(
        id="word_freq", difficulty="easy",
        prompt="Write a Python function `top_k_words(text: str, k: int) -> list[tuple[str, int]]` returning the k most frequent words (case-insensitive, words are maximal runs of [a-z0-9'] after lowercasing) as (word, count) pairs, sorted by count descending then word ascending.",
        tests="""
assert top_k_words('the cat the dog THE bird cat', 2) == [('the', 3), ('cat', 2)]
assert top_k_words("don't don't stop", 1) == [("don't", 2)]
assert top_k_words('a b c', 3) == [('a',1),('b',1),('c',1)]
assert top_k_words('', 3) == []
""",
    ),
    dict(
        id="lru_cache", difficulty="medium",
        prompt="Implement a Python class `LRUCache` with `__init__(self, capacity: int)`, `get(self, key) -> int` (returns -1 if missing) and `put(self, key, value) -> None`, evicting the least-recently-used entry when over capacity. Both operations must be O(1) average.",
        tests="""
c = LRUCache(2)
c.put(1,1); c.put(2,2)
assert c.get(1) == 1
c.put(3,3)
assert c.get(2) == -1
c.put(4,4)
assert c.get(1) == -1
assert c.get(3) == 3
assert c.get(4) == 4
c2 = LRUCache(1)
c2.put('a',5); c2.put('b',6)
assert c2.get('a') == -1 and c2.get('b') == 6
""",
    ),
    dict(
        id="merge_intervals", difficulty="medium",
        prompt="Write a Python function `merge_intervals(intervals: list[list[int]]) -> list[list[int]]` merging all overlapping or touching intervals and returning them sorted by start.",
        tests="""
assert merge_intervals([[1,3],[2,6],[8,10],[15,18]]) == [[1,6],[8,10],[15,18]]
assert merge_intervals([[1,4],[4,5]]) == [[1,5]]
assert merge_intervals([]) == []
assert merge_intervals([[5,6],[1,2]]) == [[1,2],[5,6]]
assert merge_intervals([[1,10],[2,3],[4,5]]) == [[1,10]]
""",
    ),
    dict(
        id="edit_distance", difficulty="medium",
        prompt="Write a Python function `edit_distance(a: str, b: str) -> int` computing the Levenshtein distance between two strings.",
        tests="""
assert edit_distance('', '') == 0
assert edit_distance('abc', '') == 3
assert edit_distance('horse', 'ros') == 3
assert edit_distance('intention', 'execution') == 5
assert edit_distance('kitten', 'sitting') == 3
""",
    ),
    dict(
        id="flatten_json", difficulty="medium",
        prompt="Write a Python function `flatten(obj, sep='.') -> dict` that flattens a nested dict/list structure into a single-level dict. Nested dict keys join with `sep`; list elements use their index as a key component. Scalars at the top level of a dict stay as-is.",
        tests="""
assert flatten({'a': 1}) == {'a': 1}
assert flatten({'a': {'b': 2}}) == {'a.b': 2}
assert flatten({'a': [1, 2]}) == {'a.0': 1, 'a.1': 2}
assert flatten({'a': {'b': [{'c': 3}]}}) == {'a.b.0.c': 3}
assert flatten({'a': {'b': 2}}, sep='/') == {'a/b': 2}
assert flatten({'a': {}}) in ({}, {'a': {}})
""",
    ),
    dict(
        id="version_cmp", difficulty="medium",
        prompt="Write a Python function `compare_versions(v1: str, v2: str) -> int` comparing dotted version strings numerically, returning -1, 0 or 1. Missing components count as 0 ('1.0' == '1').",
        tests="""
assert compare_versions('1.0', '1') == 0
assert compare_versions('1.2', '1.10') == -1
assert compare_versions('1.01', '1.001') == 0
assert compare_versions('2.0.1', '2.0') == 1
assert compare_versions('0.1', '1.1') == -1
""",
    ),
    dict(
        id="retry_decorator", difficulty="medium",
        prompt="Write a Python decorator factory `retry(times: int, exceptions=(Exception,))` that returns a decorator retrying the wrapped function up to `times` total attempts when it raises one of `exceptions`, re-raising the last exception if all attempts fail. Preserve the wrapped function's `__name__`. No sleeping.",
        tests="""
calls = {'n': 0}
@retry(3)
def flaky():
    calls['n'] += 1
    if calls['n'] < 3:
        raise ValueError('boom')
    return 'ok'
assert flaky() == 'ok' and calls['n'] == 3

@retry(2, exceptions=(KeyError,))
def always():
    raise KeyError('k')
try:
    always()
    raise AssertionError('should have raised')
except KeyError:
    pass

@retry(2, exceptions=(KeyError,))
def wrong():
    raise ValueError('v')
try:
    wrong()
    raise AssertionError('should have raised')
except ValueError:
    pass

@retry(1)
def named():
    return 1
assert named.__name__ == 'named'
""",
    ),
    dict(
        id="sql_parse", difficulty="medium",
        prompt="Write a Python function `parse_select(sql: str) -> dict` that parses a simple SQL SELECT statement of the form `SELECT a, b FROM t WHERE cond` (case-insensitive keywords, WHERE optional) and returns {'columns': [...], 'table': str, 'where': str|None}. Column names are stripped of whitespace; `SELECT *` yields ['*'].",
        tests="""
r = parse_select('SELECT a, b FROM users')
assert r == {'columns': ['a','b'], 'table': 'users', 'where': None}, r
r = parse_select('select * from t where id = 5')
assert r['columns'] == ['*'] and r['table'] == 't' and r['where'].strip() == 'id = 5', r
r = parse_select('SELECT  x  FROM   tbl   WHERE a > 1 AND b < 2')
assert r['columns'] == ['x'] and r['table'] == 'tbl' and r['where'].strip() == 'a > 1 AND b < 2', r
""",
    ),
    dict(
        id="topo_sort", difficulty="hard",
        prompt="Write a Python function `topo_sort(nodes: list, edges: list[tuple]) -> list` returning a topological ordering of `nodes` given directed edges (a, b) meaning a must come before b. Break ties by picking the smallest available node (nodes are comparable). Raise `ValueError` if a cycle exists.",
        tests="""
assert topo_sort(['a','b','c'], [('a','b'),('b','c')]) == ['a','b','c']
assert topo_sort(['c','b','a'], []) == ['a','b','c']
assert topo_sort([1,2,3,4], [(1,3),(2,3),(3,4)]) == [1,2,3,4]
try:
    topo_sort(['a','b'], [('a','b'),('b','a')])
    raise AssertionError('cycle not detected')
except ValueError:
    pass
""",
    ),
    dict(
        id="word_ladder", difficulty="hard",
        prompt="Write a Python function `ladder_length(begin: str, end: str, words: list[str]) -> int` returning the number of words in the shortest transformation sequence from `begin` to `end`, changing one letter at a time, where every intermediate word must be in `words`. Return 0 if impossible. `begin` need not be in `words`; `end` must be.",
        tests="""
assert ladder_length('hit','cog',['hot','dot','dog','lot','log','cog']) == 5
assert ladder_length('hit','cog',['hot','dot','dog','lot','log']) == 0
assert ladder_length('a','c',['a','b','c']) == 2
assert ladder_length('hot','hot',['hot']) == 1
""",
    ),
    dict(
        id="expr_eval", difficulty="hard",
        prompt="Write a Python function `evaluate(expr: str) -> float` that evaluates an arithmetic expression string supporting + - * / parentheses, unary minus, integers and decimals, with correct precedence. Do NOT use eval/exec. Raise `ValueError` on malformed input.",
        tests="""
assert evaluate('1+2*3') == 7
assert evaluate('(1+2)*3') == 9
assert evaluate('-4 + 2') == -2
assert abs(evaluate('10/4') - 2.5) < 1e-9
assert evaluate('2*(3+(4-1))') == 12
assert abs(evaluate('-(2.5 * 2)') + 5) < 1e-9
try:
    evaluate('1+')
    raise AssertionError('should raise')
except ValueError:
    pass
try:
    evaluate('(1+2')
    raise AssertionError('should raise')
except ValueError:
    pass
""",
    ),
    dict(
        id="diff_lines", difficulty="hard",
        prompt="Write a Python function `diff(a: list[str], b: list[str]) -> list[tuple[str, str]]` producing a line diff as a list of (op, line) where op is ' ' (common), '-' (only in a) or '+' (only in b), using an LCS so the number of common lines is maximised. Deletions for a given position come before insertions.",
        tests="""
assert diff([], []) == []
assert diff(['a'], ['a']) == [(' ','a')]
assert diff(['a'], ['b']) == [('-','a'), ('+','b')]
assert diff(['a','b','c'], ['a','c']) == [(' ','a'), ('-','b'), (' ','c')]
assert diff(['a','c'], ['a','b','c']) == [(' ','a'), ('+','b'), (' ','c')]
d = diff(['x','y','z'], ['y'])
assert [op for op,_ in d].count(' ') == 1 and d == [('-','x'), (' ','y'), ('-','z')]
""",
    ),
    dict(
        id="rate_limiter", difficulty="hard",
        prompt="Implement a Python class `SlidingWindowRateLimiter` with `__init__(self, max_calls: int, window: float)` and `allow(self, key: str, now: float) -> bool`. It permits at most `max_calls` per `key` within any window of `window` seconds ending at `now`, using an exact sliding log (calls exactly `window` old have expired). Rejected calls are not recorded.",
        tests="""
r = SlidingWindowRateLimiter(2, 10.0)
assert r.allow('a', 0.0) is True
assert r.allow('a', 1.0) is True
assert r.allow('a', 2.0) is False
assert r.allow('b', 2.0) is True
assert r.allow('a', 10.0) is True     # the 0.0 call expired
assert r.allow('a', 10.5) is False    # 1.0 and 10.0 still in window
assert r.allow('a', 11.0) is True     # 1.0 expired
""",
    ),
]
