"""parfor: whether a loop's passes can run on the pool's workers, and how
each variable its body uses travels there and back.

The body is read when the loop is compiled, with the language's rule for
parfor: no pass may depend on another. Each variable is then one of

    the loop variable,
    broadcast   read and never set in the body: sent whole to every worker;
    sliced      indexed by the loop variable in one subscript, the same way
                wherever it appears (y(k), A(:, k), c{k}): each pass sets
                (and may read) its own slice, and the slices come back;
    reduction   set only as x = x op e or x = e op x (op + - .* * & |), as
                [x, e], [e, x], [x; e], [e; x], min(x, e) or max(x, e), and
                read nowhere else: each worker reduces its own passes and
                the parts are joined in order;
    temporary   set in a pass before it is read there: each pass's own.

Anything else, and eval, load without an output, clear, global and
persistent variables, break or return, make the loop run one pass at a
time; plan() then gives the reason, which is said once when the loop runs.
"""
from . import parser as P

FORBIDDEN = ('eval', 'evalin', 'evalc', 'assignin', 'clear', 'clearvars')
REDUCE_OPS = ('+', '-', '.*', '*', '&', '|')


class Plan:
    """How a parfor loop's variables travel (see the module's text)."""
    __slots__ = ('var', 'broadcast', 'sliced', 'reductions', 'red_stmts', 'dyn')

    def __init__(self, var):
        self.var = var
        self.broadcast = []       # names
        self.sliced = []          # (name, brace, pattern): pattern holds 'k', ':' or whole numbers
        self.reductions = []      # (name, op, prefix): op 'h' and 'v' are [x, e] and [x; e]
        self.red_stmts = {}       # id(statement) -> (name, op, prefix, the other operand's node)
        self.dyn = []             # names read that may be variables made while the code runs

    def literal(self):
        """What the runtime needs, as plain values for the compiled code."""
        return {'var': self.var, 'broadcast': self.broadcast, 'sliced': self.sliced,
                'reductions': self.reductions, 'dyn': self.dyn}


def _reads(e, out, skip=None):
    """Each name read in e, in order: (name, the Index node when it is the
    indexed name there, else None). skip is an Id node not to count."""
    if e is skip or e is None:
        return
    t = type(e)
    if t is P.Id:
        out.append((e.name, None))
    elif t is P.Index:
        if type(e.base) is P.Id and e.base is not skip:
            out.append((e.base.name, e))
        else:
            _reads(e.base, out, skip)
        for a in e.args:
            _reads(a, out, skip)
    elif t is P.Field:
        _reads(e.base, out, skip)
        if not isinstance(e.name, str):
            _reads(e.name, out, skip)
    elif t is P.Bin:
        _reads(e.a, out, skip)
        _reads(e.b, out, skip)
    elif t is P.Un or t is P.Post:
        _reads(e.a, out, skip)
    elif t is P.Paren:
        _reads(e.e, out, skip)
    elif t is P.Range:
        _reads(e.a, out, skip)
        _reads(e.s, out, skip)
        _reads(e.b, out, skip)
    elif t is P.Mat or t is P.CellLit:
        for r in e.rows:
            for x in r:
                _reads(x, out, skip)
    elif t is P.Anon:
        inner = []
        _reads(e.body, inner)
        # what an anonymous function uses is captured whole when it is made
        out.extend((n, None) for n, _ in inner if n not in e.params)


def _names(e):
    out = []
    _reads(e, out)
    return {n for n, _ in out}


def _is(e, x):
    return type(e) is P.Id and e.name == x


def _reduction(x, rhs):
    """(op, prefix, the operand that is x, the other operand) when x = rhs
    reduces x, else None."""
    while type(rhs) is P.Paren:
        rhs = rhs.e
    t = type(rhs)
    if t is P.Bin and rhs.op in REDUCE_OPS:
        if _is(rhs.a, x) and x not in _names(rhs.b):
            return rhs.op, False, rhs.a, rhs.b
        if _is(rhs.b, x) and rhs.op != '-' and x not in _names(rhs.a):
            return rhs.op, True, rhs.b, rhs.a
    elif t is P.Mat:
        rows = rhs.rows
        if len(rows) == 1 and len(rows[0]) >= 2:
            r = rows[0]
            if _is(r[0], x) and not any(x in _names(e) for e in r[1:]):
                return 'h', False, r[0], P.Mat([r[1:]], rhs.line)
            if _is(r[-1], x) and not any(x in _names(e) for e in r[:-1]):
                return 'h', True, r[-1], P.Mat([r[:-1]], rhs.line)
        elif len(rows) >= 2 and all(len(r) == 1 for r in rows):
            if _is(rows[0][0], x) and not any(x in _names(r[0]) for r in rows[1:]):
                return 'v', False, rows[0][0], P.Mat(rows[1:], rhs.line)
            if _is(rows[-1][0], x) and not any(x in _names(r[0]) for r in rows[:-1]):
                return 'v', True, rows[-1][0], P.Mat(rows[:-1], rhs.line)
    elif t is P.Index and not rhs.brace and type(rhs.base) is P.Id and rhs.base.name in ('min', 'max') and len(rhs.args) == 2:
        a, b = rhs.args
        if _is(a, x) and x not in _names(b):
            return rhs.base.name, False, a, b
        if _is(b, x) and x not in _names(a):
            return rhs.base.name, True, b, a
    return None


def _pattern(node, k):
    """The subscripts of x(...) or x{...} as a slice: (brace, pattern) with
    'k' for the loop variable (once), ':' and whole numbers; else None."""
    pat = []
    nk = 0
    for a in node.args:
        if _is(a, k):
            pat.append('k')
            nk += 1
        elif type(a) is P.Colon:
            pat.append(':')
        elif type(a) is P.Num and type(a.v) is float and a.v >= 1 and a.v == int(a.v) and not isinstance(a.cls, tuple):
            pat.append(a.v)
        else:
            return None
    return (node.brace, tuple(pat)) if nk == 1 else None


def _forbidden(body, is_var, in_loop=False):
    """Why the body cannot run as separate passes, or None."""
    for s in body:
        t = type(s)
        if t is P.Global:
            return 'it declares global or persistent variables'
        if t is P.Break and not in_loop:
            return 'it has break'
        if t is P.Return:
            return 'it has return'
        if t is P.Cmd and not is_var(s.name):
            if s.name in FORBIDDEN:
                return f'it calls {s.name}'
            if s.name == 'load':
                return 'it calls load without an output (the variables it makes cannot be known)'
        if t is P.ExprS and type(s.e) in (P.Id, P.Index):
            base = s.e if type(s.e) is P.Id else s.e.base
            if _is(base, 'load') and not is_var('load'):
                return 'it calls load without an output (the variables it makes cannot be known)'
        for e in _exprs(s):
            for n, _ in _reads_list(e):
                if n in FORBIDDEN and not is_var(n):
                    return f'it calls {n}'
                if n in ('nargin', 'nargout') and not is_var(n):
                    return f'it uses {n}'
        if t is P.If:
            for _, b in s.clauses:
                why = _forbidden(b, is_var, in_loop)
                if why:
                    return why
            if s.els is not None:
                why = _forbidden(s.els, is_var, in_loop)
                if why:
                    return why
        elif t is P.For or t is P.While:
            why = _forbidden(s.body, is_var, True)
            if why:
                return why
        elif t is P.Switch:
            for _, b in s.cases:
                why = _forbidden(b, is_var, in_loop)
                if why:
                    return why
            if s.other is not None:
                why = _forbidden(s.other, is_var, in_loop)
                if why:
                    return why
        elif t is P.Try:
            why = _forbidden(s.body, is_var, in_loop) or _forbidden(s.cbody, is_var, in_loop)
            if why:
                return why
    return None


def _reads_list(e):
    out = []
    _reads(e, out)
    return out


def _exprs(s):
    """The expressions a statement reads itself (not those of the blocks it holds)."""
    t = type(s)
    if t is P.ExprS:
        return [s.e]
    if t is P.Assign:
        out = [s.rhs]
        for x in s.lhs:
            # the subscripts of an indexed target are read
            while isinstance(x, (P.Index, P.Field)):
                if type(x) is P.Index:
                    out.extend(x.args)
                elif not isinstance(x.name, str):
                    out.append(x.name)
                x = x.base
        return out
    if t is P.If:
        return [c for c, _ in s.clauses]
    if t is P.For:
        return [s.it]
    if t is P.While:
        return [s.cond]
    if t is P.Switch:
        return [s.e] + [c for c, _ in s.cases]
    return []


def _all_stmts(body):
    for s in body:
        yield s
        t = type(s)
        if t is P.If:
            for _, b in s.clauses:
                yield from _all_stmts(b)
            if s.els is not None:
                yield from _all_stmts(s.els)
        elif t is P.For or t is P.While:
            yield from _all_stmts(s.body)
        elif t is P.Switch:
            for _, b in s.cases:
                yield from _all_stmts(b)
            if s.other is not None:
                yield from _all_stmts(s.other)
        elif t is P.Try:
            yield from _all_stmts(s.body)
            yield from _all_stmts(s.cbody)


def _root_name(x):
    while isinstance(x, (P.Index, P.Field)):
        x = x.base
    return x.name if type(x) is P.Id else None


def _first_unset(body, temps):
    """The first temporary a pass reads (or changes in part) before it sets
    it, or None: then each pass sets its temporaries itself."""
    def check(names, D):
        for n in names:
            if n in temps and n not in D:
                return n
        return None

    def run(stmts, D):
        for s in stmts:
            t = type(s)
            if t is P.Assign:
                r = check([n for e in _exprs(s) for n, _ in _reads_list(e)], D)
                if r:
                    return r
                for x in s.lhs:
                    if x is None or type(x) is P.Tilde:
                        continue
                    n = _root_name(x)
                    if type(x) is P.Id:
                        D.add(n)
                    elif n in temps and n not in D:
                        return n          # x(i) = v changes the value of an earlier pass
            elif t is P.ExprS:
                r = check([n for n, _ in _reads_list(s.e)], D)
                if r:
                    return r
            elif t is P.If or t is P.Switch:
                heads = [c for c, _ in s.clauses] if t is P.If else [s.e] + [c for c, _ in s.cases]
                r = check([n for e in heads for n, _ in _reads_list(e)], D)
                if r:
                    return r
                blocks = [b for _, b in (s.clauses if t is P.If else s.cases)]
                rest = s.els if t is P.If else s.other
                sets = []
                for b in blocks + ([rest] if rest is not None else []):
                    Db = set(D)
                    r = run(b, Db)
                    if r:
                        return r
                    sets.append(Db)
                if rest is None:
                    sets.append(set(D))
                D.update(set.intersection(*sets))
            elif t is P.For:
                r = check([n for n, _ in _reads_list(s.it)], D)
                if r:
                    return r
                r = run(s.body, set(D) | {_root_name(s.var)})
                if r:
                    return r
            elif t is P.While:
                r = check([n for n, _ in _reads_list(s.cond)], D) or run(s.body, set(D))
                if r:
                    return r
            elif t is P.Try:
                r = run(s.body, set(D)) or run(s.cbody, set(D) | ({s.var} if s.var else set()))
                if r:
                    return r
        return None

    return run(body, set())


def plan(loop, is_var, dynamic):
    """The Plan of a parfor loop, or the reason (text) its passes must run
    one at a time. is_var(name) tells the variables where the loop is;
    dynamic, that names which are not may be variables made while the code
    runs (scripts and command lines)."""
    if type(loop.var) is not P.Id:
        return 'its loop variable is not a plain name'
    k = loop.var.name
    body = loop.body
    why = _forbidden(body, is_var)
    if why:
        return why
    writes, reads, own = {}, {}, {}      # name -> [(kind, node)], [index node or None], [reduction statements]
    for s in _all_stmts(body):
        t = type(s)
        if t is P.Assign:
            red = None
            if not s.multi and len(s.lhs) == 1 and type(s.lhs[0]) is P.Id:
                red = _reduction(s.lhs[0].name, s.rhs)
            for x in s.lhs:
                if x is None or type(x) is P.Tilde:
                    continue
                n = _root_name(x)
                if n is None:
                    continue
                kind = 'set' if type(x) is P.Id else 'index' if type(x) is P.Index and type(x.base) is P.Id else 'other'
                writes.setdefault(n, []).append((kind, x))
            if red is not None:
                name = s.lhs[0].name
                op, prefix, operand, other = red
                own.setdefault(name, []).append((s, op, prefix, other))
                found = []
                _reads(s.rhs, found, skip=operand)
                for e in _exprs(s)[1:]:
                    _reads(e, found)
            else:
                found = [r for e in _exprs(s) for r in _reads_list(e)]
        elif t is P.For:
            writes.setdefault(_root_name(s.var), []).append(('set', s.var))
            found = _reads_list(s.it)
        elif t is P.Try and s.var:
            writes.setdefault(s.var, []).append(('set', None))
            found = []
        else:
            found = [r for e in _exprs(s) for r in _reads_list(e)]
        for n, node in found:
            reads.setdefault(n, []).append(node)

    p = Plan(k)
    temps = set()
    for n, ws in sorted(writes.items()):
        if n == 'ans':
            continue
        if n == k:
            return f'its loop variable {k} is set in the loop'
        rs = reads.get(n, [])
        stmts = own.get(n, [])
        if stmts and len(stmts) == len(ws) and all(kind == 'set' for kind, _ in ws) and not rs \
                and len({(op, prefix) for _, op, prefix, _ in stmts}) == 1 \
                and not (stmts[0][1] in ('min', 'max') and is_var(stmts[0][1])):
            _, op, prefix, _ = stmts[0]
            p.reductions.append((n, op, prefix))
            for s, op_, prefix_, other in stmts:
                p.red_stmts[id(s)] = (n, op_, prefix_, other)
            continue
        if stmts:
            # a reduction's own operand is a read of the variable after all
            rs = rs + [None] * len(stmts)
        pats = {_pattern(x, k) for kind, x in ws if kind == 'index'} | {_pattern(r, k) if r is not None else None for r in rs}
        if all(kind == 'index' for kind, _ in ws) and len(pats) == 1 and None not in pats:
            brace, pattern = pats.pop()
            p.sliced.append((n, brace, pattern))
            continue
        temps.add(n)
    first = _first_unset(body, temps)
    if first:
        return f'{first} is used in a pass before the pass sets it, so passes depend on each other'
    assigned = set(writes)
    for n in sorted(set(reads) - assigned - {k, 'ans'}):
        if is_var(n):
            p.broadcast.append(n)
        elif dynamic:
            p.dyn.append(n)
    return p
