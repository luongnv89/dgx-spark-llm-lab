"""Reference solutions for every task in every suite.

Each maps a task id to a self-contained implementation that passes that task's
hidden tests. `bench validate` runs them all: if a reference fails, the test is
broken, not the model.
"""

REFERENCES = {
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


REFERENCES["regex_match"] = '''
def is_match(s, p):
    from functools import lru_cache
    @lru_cache(None)
    def go(i, j):
        if j == len(p):
            return i == len(s)
        first = i < len(s) and p[j] in (s[i], '.')
        if j + 1 < len(p) and p[j+1] == '*':
            return go(i, j+2) or (first and go(i+1, j))
        return first and go(i+1, j+1)
    return go(0, 0)
'''

REFERENCES["weighted_intervals"] = '''
import bisect
def max_weight_schedule(jobs):
    if not jobs:
        return 0
    js = sorted(jobs, key=lambda x: x[1])
    ends = [j[1] for j in js]
    dp = [0] * (len(js) + 1)
    for i, (s, e, w) in enumerate(js, 1):
        k = bisect.bisect_right(ends, s, 0, i - 1)
        dp[i] = max(dp[i-1], dp[k] + w)
    return dp[-1]
'''

REFERENCES["json5_parse"] = r'''
def parse_relaxed(text):
    i = 0
    n = len(text)
    def err(msg='parse error'):
        raise ValueError(msg)
    def ws():
        nonlocal i
        while i < n:
            c = text[i]
            if c in ' \t\r\n':
                i += 1
            elif text.startswith('//', i):
                j = text.find('\n', i)
                i = n if j < 0 else j + 1
            elif text.startswith('/*', i):
                j = text.find('*/', i + 2)
                if j < 0:
                    err('unterminated comment')
                i = j + 2
            else:
                return
    def string():
        nonlocal i
        q = text[i]; i += 1
        out = []
        while True:
            if i >= n:
                err('unterminated string')
            c = text[i]
            if c == '\\':
                i += 1
                if i >= n:
                    err('bad escape')
                e = text[i]; i += 1
                out.append({'n':'\n','t':'\t','r':'\r','b':'\b','f':'\f','\\':'\\','/':'/','"':'"',"'":"'"}.get(e, e))
            elif c == q:
                i += 1
                return ''.join(out)
            else:
                out.append(c); i += 1
    def ident():
        nonlocal i
        j = i
        if i >= n or not (text[i].isalpha() or text[i] == '_'):
            err('expected key')
        while i < n and (text[i].isalnum() or text[i] == '_'):
            i += 1
        if j == i:
            err('expected key')
        return text[j:i]
    def number():
        nonlocal i
        j = i
        if i < n and text[i] in '+-':
            i += 1
        while i < n and (text[i].isdigit() or text[i] in '.eE' or (text[i] in '+-' and text[i-1] in 'eE')):
            i += 1
        raw = text[j:i]
        try:
            return int(raw)
        except ValueError:
            try:
                return float(raw)
            except ValueError:
                err('bad number')
    def value():
        nonlocal i
        ws()
        if i >= n:
            err('unexpected end')
        c = text[i]
        if c == '{':
            i += 1
            obj = {}
            ws()
            if i < n and text[i] == '}':
                i += 1; return obj
            while True:
                ws()
                if i >= n:
                    err('unexpected end')
                if text[i] in '"\'':
                    k = string()
                else:
                    k = ident()
                ws()
                if i >= n or text[i] != ':':
                    err('expected :')
                i += 1
                obj[k] = value()
                ws()
                if i < n and text[i] == ',':
                    i += 1
                    ws()
                    if i < n and text[i] == '}':
                        i += 1; return obj
                    continue
                if i < n and text[i] == '}':
                    i += 1; return obj
                err('expected , or }')
        if c == '[':
            i += 1
            arr = []
            ws()
            if i < n and text[i] == ']':
                i += 1; return arr
            while True:
                arr.append(value())
                ws()
                if i < n and text[i] == ',':
                    i += 1
                    ws()
                    if i < n and text[i] == ']':
                        i += 1; return arr
                    continue
                if i < n and text[i] == ']':
                    i += 1; return arr
                err('expected , or ]')
        if c in '"\'':
            return string()
        if text.startswith('true', i):
            i += 4; return True
        if text.startswith('false', i):
            i += 5; return False
        if text.startswith('null', i):
            i += 4; return None
        if c.isdigit() or c in '+-.':
            return number()
        err('unexpected char ' + repr(c))
    v = value()
    ws()
    if i != n:
        raise ValueError('trailing input')
    return v
'''

REFERENCES["topo_batches"] = '''
def topo_batches(deps):
    nodes = set(deps)
    for v in deps.values():
        nodes.update(v)
    if not nodes:
        return []
    pre = {k: set(deps.get(k, ())) for k in nodes}
    out = []
    done = set()
    while len(done) < len(nodes):
        batch = sorted(k for k in nodes if k not in done and pre[k] <= done)
        if not batch:
            raise ValueError('cycle')
        out.append(batch)
        done.update(batch)
    return out
'''

REFERENCES["wrap_min_raggedness"] = '''
def wrap_text(words, width):
    n = len(words)
    if n == 0:
        return []
    INF = float('inf')
    cost = [0] * (n + 1)
    brk = [n] * (n + 1)
    for i in range(n - 1, -1, -1):
        best = INF
        bestj = None
        ln = -1
        for j in range(i, n):
            ln += len(words[j]) + 1
            if ln > width and j > i:
                break
            if j == n - 1:
                c = 0.0
            elif ln > width:
                c = 0.0
            else:
                c = float((width - ln) ** 2)
            tot = c + cost[j + 1]
            if tot < best or (tot == best and j > (bestj if bestj is not None else -1)):
                best = tot
                bestj = j
        cost[i] = best
        brk[i] = bestj
    lines = []
    i = 0
    while i < n:
        j = brk[i]
        lines.append(' '.join(words[i:j + 1]))
        i = j + 1
    return lines
'''

REFERENCES["unify"] = '''
def unify(t1, t2):
    def is_var(t):
        return isinstance(t, tuple) and len(t) == 2 and t[0] == 'var' and isinstance(t[1], str)
    def walk(t, s):
        while is_var(t) and t[1] in s:
            t = s[t[1]]
        return t
    def occurs(name, t, s):
        t = walk(t, s)
        if is_var(t):
            return t[1] == name
        return any(occurs(name, a, s) for a in t[1:])
    def uni(a, b, s):
        a = walk(a, s); b = walk(b, s)
        if is_var(a) and is_var(b) and a[1] == b[1]:
            return s
        if is_var(a):
            if occurs(a[1], b, s):
                return None
            s = dict(s); s[a[1]] = b; return s
        if is_var(b):
            return uni(b, a, s)
        if a[0] != b[0] or len(a) != len(b):
            return None
        for x, y in zip(a[1:], b[1:]):
            s = uni(x, y, s)
            if s is None:
                return None
        return s
    def resolve(t, s):
        t = walk(t, s)
        if is_var(t):
            return t
        return (t[0],) + tuple(resolve(a, s) for a in t[1:])
    s = uni(t1, t2, {})
    if s is None:
        return None
    return {k: resolve(v, s) for k, v in s.items()}
'''

REFERENCES["range_module"] = '''
class RangeModule:
    def __init__(self):
        self.iv = []
    def add_range(self, left, right):
        out = []
        placed = False
        for a, b in self.iv:
            if b < left:
                out.append((a, b))
            elif right < a:
                if not placed:
                    out.append((left, right)); placed = True
                out.append((a, b))
            else:
                left = min(left, a); right = max(right, b)
        if not placed:
            out.append((left, right))
        out.sort()
        self.iv = out
    def query_range(self, left, right):
        for a, b in self.iv:
            if a <= left and right <= b:
                return True
        return False
    def remove_range(self, left, right):
        out = []
        for a, b in self.iv:
            if b <= left or a >= right:
                out.append((a, b))
                continue
            if a < left:
                out.append((a, left))
            if right < b:
                out.append((right, b))
        self.iv = sorted(out)
'''

REFERENCES["cron_next"] = '''
import datetime
def _field(spec, lo, hi):
    vals = set()
    for part in spec.split(','):
        step = 1
        if '/' in part:
            part, st = part.split('/', 1)
            step = int(st)
        if part == '*':
            a, b = lo, hi
        elif '-' in part.lstrip('-'):
            a, b = part.split('-', 1)
            a, b = int(a), int(b)
        else:
            a = b = int(part)
            if step != 1:
                b = hi
        vals.update(range(a, b + 1, step))
    return {v for v in vals if lo <= v <= hi}
def next_run(expr, after):
    f = expr.split()
    if len(f) != 5:
        raise ValueError('need 5 fields')
    mins = _field(f[0], 0, 59)
    hours = _field(f[1], 0, 23)
    doms = _field(f[2], 1, 31)
    months = _field(f[3], 1, 12)
    dows = _field(f[4], 0, 6)
    dom_r = f[2] != '*'
    dow_r = f[4] != '*'
    t = after.replace(second=0, microsecond=0) + datetime.timedelta(minutes=1)
    limit = after + datetime.timedelta(days=366 * 8)
    day = t.date()
    while t <= limit:
        if day.month in months:
            d = (day.weekday() + 1) % 7
            if (dom_r and dow_r and (day.day in doms or d in dows)) or \
               (not (dom_r and dow_r) and (day.day in doms and d in dows)):
                start = t if t.date() == day else datetime.datetime(day.year, day.month, day.day)
                for h in sorted(hours):
                    if h < start.hour:
                        continue
                    for m in sorted(mins):
                        cand = datetime.datetime(day.year, day.month, day.day, h, m)
                        if cand >= start:
                            return cand
        day = day + datetime.timedelta(days=1)
        t = datetime.datetime(day.year, day.month, day.day)
    raise ValueError('no match')
'''

REFERENCES["bigint_div"] = '''
def divmod_str(a, b):
    a = a.lstrip('0') or '0'
    b = b.lstrip('0') or '0'
    if b == '0':
        raise ZeroDivisionError('division by zero')
    bd = [int(c) for c in b]
    def cmp(x, y):
        x = x[next((i for i, d in enumerate(x) if d), len(x)):] or [0]
        if len(x) != len(y):
            return -1 if len(x) < len(y) else 1
        for p, q in zip(x, y):
            if p != q:
                return -1 if p < q else 1
        return 0
    def sub(x, y):
        r = list(x)
        y = [0] * (len(r) - len(y)) + list(y)
        borrow = 0
        for i in range(len(r) - 1, -1, -1):
            v = r[i] - y[i] - borrow
            borrow = 0
            if v < 0:
                v += 10; borrow = 1
            r[i] = v
        return r
    q = []
    rem = []
    for ch in a:
        rem.append(int(ch))
        while len(rem) > 1 and rem[0] == 0:
            rem.pop(0)
        d = 0
        while cmp(rem, bd) >= 0:
            rem = sub(rem, bd)
            while len(rem) > 1 and rem[0] == 0:
                rem.pop(0)
            d += 1
        q.append(d)
    qs = ''.join(map(str, q)).lstrip('0') or '0'
    rs = ''.join(map(str, rem)).lstrip('0') or '0'
    return qs, rs
'''

REFERENCES["tx_dict"] = '''
import contextlib
class TxDict:
    def __init__(self):
        self._d = {}
        self._stack = []
    def _journal(self, key):
        if self._stack:
            frame = self._stack[-1]
            if key not in frame:
                frame[key] = (True, self._d[key]) if key in self._d else (False, None)
    def __getitem__(self, k):
        return self._d[k]
    def __setitem__(self, k, v):
        self._journal(k)
        self._d[k] = v
    def __delitem__(self, k):
        self._journal(k)
        del self._d[k]
    def __contains__(self, k):
        return k in self._d
    def __len__(self):
        return len(self._d)
    def __iter__(self):
        return iter(self._d)
    def get(self, k, default=None):
        return self._d.get(k, default)
    def begin(self):
        self._stack.append({})
    def commit(self):
        if not self._stack:
            raise RuntimeError('no transaction')
        frame = self._stack.pop()
        if self._stack:
            outer = self._stack[-1]
            for k, v in frame.items():
                if k not in outer:
                    outer[k] = v
    def rollback(self):
        if not self._stack:
            raise RuntimeError('no transaction')
        frame = self._stack.pop()
        for k, (existed, val) in frame.items():
            if existed:
                self._d[k] = val
            else:
                self._d.pop(k, None)
    @contextlib.contextmanager
    def transaction(self):
        self.begin()
        try:
            yield self
        except BaseException:
            self.rollback()
            raise
        else:
            self.commit()
'''

REFERENCES["sql_select"] = r'''
import re
def run_query(sql, rows):
    toks = re.findall(r"'(?:[^']|'')*'|>=|<=|!=|[=<>,()*]|[A-Za-z_][A-Za-z_0-9]*|-?\d+\.\d+|-?\d+", sql)
    pos = 0
    def peek():
        return toks[pos] if pos < len(toks) else None
    def kw(*names):
        t = peek()
        return t is not None and t.upper() in names
    def take():
        nonlocal pos
        if pos >= len(toks):
            raise ValueError('unexpected end')
        pos += 1
        return toks[pos - 1]
    def expect_kw(name):
        if not kw(name):
            raise ValueError('expected ' + name)
        return take()
    expect_kw('SELECT')
    cols = []
    star = False
    if peek() == '*':
        take(); star = True
    else:
        while True:
            name = take()
            if not re.match(r'^[A-Za-z_]', name) or name.upper() in ('FROM',):
                raise ValueError('bad column')
            alias = name
            if kw('AS'):
                take(); alias = take()
            cols.append((name, alias))
            if peek() == ',':
                take(); continue
            break
    expect_kw('FROM')
    take()
    def literal(t):
        if t.startswith("'"):
            return t[1:-1].replace("''", "'")
        try:
            return int(t)
        except ValueError:
            return float(t)
    def parse_or():
        left = parse_and()
        while kw('OR'):
            take(); right = parse_and()
            l, r = left, right
            left = lambda row, l=l, r=r: l(row) or r(row)
        return left
    def parse_and():
        left = parse_atom()
        while kw('AND'):
            take(); right = parse_atom()
            l, r = left, right
            left = lambda row, l=l, r=r: l(row) and r(row)
        return left
    def parse_atom():
        if peek() == '(':
            take()
            e = parse_or()
            if peek() != ')':
                raise ValueError('expected )')
            take()
            return e
        col = take()
        if not re.match(r'^[A-Za-z_]', col):
            raise ValueError('bad condition')
        op = take()
        if op not in ('=', '!=', '<', '<=', '>', '>='):
            raise ValueError('bad operator')
        if peek() is None:
            raise ValueError('missing literal')
        val = literal(take())
        def f(row, col=col, op=op, val=val):
            v = row.get(col)
            if v is None:
                return False
            try:
                if op == '=': return v == val
                if op == '!=': return v != val
                if op == '<': return v < val
                if op == '<=': return v <= val
                if op == '>': return v > val
                return v >= val
            except TypeError:
                return False
        return f
    pred = None
    if kw('WHERE'):
        take()
        if peek() is None:
            raise ValueError('empty where')
        pred = parse_or()
    order = []
    if kw('ORDER'):
        take(); expect_kw('BY')
        while True:
            c = take()
            desc = False
            if kw('ASC'):
                take()
            elif kw('DESC'):
                take(); desc = True
            order.append((c, desc))
            if peek() == ',':
                take(); continue
            break
    limit = None
    if kw('LIMIT'):
        take()
        if peek() is None:
            raise ValueError('limit needs a number')
        limit = int(take())
    if peek() is not None:
        raise ValueError('trailing tokens')
    out = [r for r in rows if pred is None or pred(r)]
    for c, desc in reversed(order):
        out.sort(key=lambda r, c=c: r.get(c), reverse=desc)
    if limit is not None:
        out = out[:limit]
    if star:
        return [dict(r) for r in out]
    return [{alias: r.get(name) for name, alias in cols} for r in out]
'''

REFERENCES["running_median"] = '''
import heapq
from collections import Counter
class MedianStream:
    def __init__(self):
        self.lo = []   # max-heap (negated) lower half
        self.hi = []   # min-heap upper half
        self.present = Counter()
        self.dead = Counter()
        self.nlo = 0
        self.nhi = 0
    def _clean_lo(self):
        while self.lo and self.dead[(-self.lo[0], 0)] > 0:
            self.dead[(-self.lo[0], 0)] -= 1
            heapq.heappop(self.lo)
    def _clean_hi(self):
        while self.hi and self.dead[(self.hi[0], 1)] > 0:
            self.dead[(self.hi[0], 1)] -= 1
            heapq.heappop(self.hi)
    def _rebalance(self):
        while True:
            self._clean_lo(); self._clean_hi()
            if self.nlo > self.nhi + 1:
                v = -heapq.heappop(self.lo); self.nlo -= 1
                heapq.heappush(self.hi, v); self.nhi += 1
            elif self.nhi > self.nlo:
                v = heapq.heappop(self.hi); self.nhi -= 1
                heapq.heappush(self.lo, -v); self.nlo += 1
            else:
                break
        self._clean_lo(); self._clean_hi()
    def add(self, x):
        self.present[x] += 1
        self._clean_lo()
        if not self.lo or x <= -self.lo[0]:
            heapq.heappush(self.lo, -x); self.nlo += 1
        else:
            heapq.heappush(self.hi, x); self.nhi += 1
        self._rebalance()
    def remove(self, x):
        if self.present[x] <= 0:
            raise ValueError('not present: %r' % (x,))
        self.present[x] -= 1
        self._clean_lo()
        if self.lo and x <= -self.lo[0]:
            self.dead[(x, 0)] += 1; self.nlo -= 1
        else:
            self.dead[(x, 1)] += 1; self.nhi -= 1
        self._rebalance()
    def median(self):
        self._rebalance()
        if self.nlo + self.nhi == 0:
            raise ValueError('empty')
        if self.nlo > self.nhi:
            return -self.lo[0]
        return (-self.lo[0] + self.hi[0]) / 2
'''
