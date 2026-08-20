#!/usr/bin/env python3
"""Verify every task's hidden tests pass against a reference solution."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "scratchpad"))
from tasks import TASKS  # noqa: E402
from bench import run_tests  # noqa: E402

REF = {
"two_sum": """
def two_sum(nums, target):
    seen = {}
    for i, n in enumerate(nums):
        if target - n in seen:
            return sorted([seen[target - n], i])
        seen[n] = i
""",
"roman": """
def int_to_roman(num):
    vals = [(1000,'M'),(900,'CM'),(500,'D'),(400,'CD'),(100,'C'),(90,'XC'),
            (50,'L'),(40,'XL'),(10,'X'),(9,'IX'),(5,'V'),(4,'IV'),(1,'I')]
    out = []
    for v, s in vals:
        while num >= v:
            out.append(s); num -= v
    return ''.join(out)
""",
"balanced": """
def is_balanced(s):
    pairs = {')':'(', ']':'[', '}':'{'}
    stack = []
    for c in s:
        if c in '([{':
            stack.append(c)
        elif c in pairs:
            if not stack or stack.pop() != pairs[c]:
                return False
    return not stack
""",
"word_freq": """
import re
from collections import Counter
def top_k_words(text, k):
    words = re.findall(r"[a-z0-9']+", text.lower())
    c = Counter(words)
    return sorted(c.items(), key=lambda kv: (-kv[1], kv[0]))[:k]
""",
"lru_cache": """
from collections import OrderedDict
class LRUCache:
    def __init__(self, capacity):
        self.cap = capacity
        self.d = OrderedDict()
    def get(self, key):
        if key not in self.d:
            return -1
        self.d.move_to_end(key)
        return self.d[key]
    def put(self, key, value):
        if key in self.d:
            self.d.move_to_end(key)
        self.d[key] = value
        if len(self.d) > self.cap:
            self.d.popitem(last=False)
""",
"merge_intervals": """
def merge_intervals(intervals):
    out = []
    for s, e in sorted(intervals):
        if out and s <= out[-1][1]:
            out[-1][1] = max(out[-1][1], e)
        else:
            out.append([s, e])
    return out
""",
"edit_distance": """
def edit_distance(a, b):
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j-1] + 1, prev[j-1] + (ca != cb)))
        prev = cur
    return prev[-1]
""",
"flatten_json": """
def flatten(obj, sep='.'):
    out = {}
    def rec(o, prefix):
        if isinstance(o, dict):
            if not o and prefix:
                return
            for k, v in o.items():
                rec(v, f"{prefix}{sep}{k}" if prefix else str(k))
        elif isinstance(o, list):
            for i, v in enumerate(o):
                rec(v, f"{prefix}{sep}{i}" if prefix else str(i))
        else:
            out[prefix] = o
    rec(obj, '')
    return out
""",
"version_cmp": """
def compare_versions(v1, v2):
    a = [int(x) for x in v1.split('.')]
    b = [int(x) for x in v2.split('.')]
    n = max(len(a), len(b))
    a += [0] * (n - len(a)); b += [0] * (n - len(b))
    return (a > b) - (a < b)
""",
"retry_decorator": """
import functools
def retry(times, exceptions=(Exception,)):
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*a, **kw):
            last = None
            for _ in range(times):
                try:
                    return fn(*a, **kw)
                except exceptions as e:
                    last = e
            raise last
        return wrapper
    return deco
""",
"sql_parse": """
import re
def parse_select(sql):
    m = re.match(r"\\s*select\\s+(.*?)\\s+from\\s+(\\S+)(?:\\s+where\\s+(.*))?\\s*$",
                 sql, re.I | re.S)
    if not m:
        raise ValueError('bad sql')
    cols = [c.strip() for c in m.group(1).split(',')]
    return {'columns': cols, 'table': m.group(2), 'where': m.group(3)}
""",
"topo_sort": """
import heapq
def topo_sort(nodes, edges):
    indeg = {n: 0 for n in nodes}
    adj = {n: [] for n in nodes}
    for a, b in edges:
        adj[a].append(b)
        indeg[b] += 1
    h = [n for n in nodes if indeg[n] == 0]
    heapq.heapify(h)
    out = []
    while h:
        n = heapq.heappop(h)
        out.append(n)
        for m in adj[n]:
            indeg[m] -= 1
            if indeg[m] == 0:
                heapq.heappush(h, m)
    if len(out) != len(nodes):
        raise ValueError('cycle')
    return out
""",
"word_ladder": """
from collections import deque
import string
def ladder_length(begin, end, words):
    ws = set(words)
    if end not in ws:
        return 0
    q = deque([(begin, 1)])
    seen = {begin}
    while q:
        w, d = q.popleft()
        if w == end:
            return d
        for i in range(len(w)):
            for c in string.ascii_lowercase:
                nxt = w[:i] + c + w[i+1:]
                if nxt in ws and nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, d + 1))
    return 0
""",
"expr_eval": """
import re
def evaluate(expr):
    toks = re.findall(r"\\d+\\.\\d+|\\d+|[()+\\-*/]|\\S", expr.replace(' ', ''))
    for t in toks:
        if not re.fullmatch(r"\\d+\\.\\d+|\\d+|[()+\\-*/]", t):
            raise ValueError('bad token')
    pos = [0]
    def peek():
        return toks[pos[0]] if pos[0] < len(toks) else None
    def eat(t=None):
        c = peek()
        if c is None or (t and c != t):
            raise ValueError('unexpected')
        pos[0] += 1
        return c
    def atom():
        c = peek()
        if c is None:
            raise ValueError('eof')
        if c == '-':
            eat(); return -atom()
        if c == '(':
            eat('('); v = expr_(); eat(')'); return v
        if re.fullmatch(r"\\d+\\.\\d+|\\d+", c):
            eat(); return float(c) if '.' in c else int(c)
        raise ValueError('bad atom')
    def term():
        v = atom()
        while peek() in ('*', '/'):
            op = eat()
            r = atom()
            v = v * r if op == '*' else v / r
        return v
    def expr_():
        v = term()
        while peek() in ('+', '-'):
            op = eat()
            r = term()
            v = v + r if op == '+' else v - r
        return v
    v = expr_()
    if pos[0] != len(toks):
        raise ValueError('trailing')
    return v
""",
"diff_lines": """
def diff(a, b):
    n, m = len(a), len(b)
    dp = [[0]*(m+1) for _ in range(n+1)]
    for i in range(n-1, -1, -1):
        for j in range(m-1, -1, -1):
            dp[i][j] = dp[i+1][j+1] + 1 if a[i] == b[j] else max(dp[i+1][j], dp[i][j+1])
    out = []
    i = j = 0
    while i < n and j < m:
        if a[i] == b[j]:
            out.append((' ', a[i])); i += 1; j += 1
        elif dp[i+1][j] >= dp[i][j+1]:
            out.append(('-', a[i])); i += 1
        else:
            out.append(('+', b[j])); j += 1
    out += [('-', x) for x in a[i:]]
    out += [('+', x) for x in b[j:]]
    return out
""",
"rate_limiter": """
from collections import defaultdict, deque
class SlidingWindowRateLimiter:
    def __init__(self, max_calls, window):
        self.max_calls = max_calls
        self.window = window
        self.log = defaultdict(deque)
    def allow(self, key, now):
        q = self.log[key]
        while q and q[0] <= now - self.window:
            q.popleft()
        if len(q) < self.max_calls:
            q.append(now)
            return True
        return False
""",
}

fails = 0
for t in TASKS:
    ref = REF.get(t["id"])
    if ref is None:
        print(f"NO REF   {t['id']}")
        fails += 1
        continue
    ok, err = run_tests(t, ref)
    print(f"{'ok  ' if ok else 'BAD '} {t['id']:<18} {err[:100]}")
    fails += (not ok)
print(f"\n{len(TASKS)-fails}/{len(TASKS)} task test-suites validated")
sys.exit(1 if fails else 0)
