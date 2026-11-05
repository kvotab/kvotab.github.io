"""The symbolic math functions, on SymPy (symbolic.py holds sym itself).

New functions are registered as builtins (sym, syms, int, solve, dsolve,
...). The functions that numbers have too (sin, diff, sum, det, fplot,
...) keep their numeric code: install() puts a dispatcher in front of each
that hands the call here when an argument is symbolic. sym, syms, str2sym,
symfun, vpa, poly2sym and piecewise make symbolic values from scratch, so
they wait for SymPy (in the page Pyodide loads it the first time); the rest
are given a symbolic value, so SymPy is there.
"""
import math
import os

import numpy as np

from . import bi, REG
from ._util import err, darr, out, opt_str, opt_lower, num, is_str
from ..values import MError, Char, Cell, Struct, Str, FH, Obj, EMPTY, F64, C128, numel, py_str, class_of
from .. import runtime as R
from .. import symbolic as Y
from ..symbolic import Sym, S, sp, arr_of, to_expr, text, fresh, symbol, NAMES, RELS, DIGITS

OVERLOADS = {}


def _over(*names):
    def deco(fn):
        for n in names:
            OVERLOADS[n] = fn
        return fn
    return deco


def _is(v):
    return type(v) is Sym


def _fa(v):
    """A symbolic function's arguments, kept by what rewrites its formula."""
    return v.fargs if type(v) is Sym else None


def ex(v):
    """A value's expressions, brought up to date with the assumptions."""
    a = arr_of(v)
    out_ = np.empty(a.shape, object)
    for i in np.ndindex(a.shape):
        out_[i] = fresh(a[i])
    return out_


def _each(fn, A):
    r = np.empty(A.shape, object)
    for i in np.ndindex(A.shape):
        r[i] = fn(A[i])
    return r


def _sym(a, like=None):
    return Sym(np.asarray(a, object) if isinstance(a, np.ndarray) else Y.of_array(a).a, like.fargs if _is(like) else None)


def _flat(v):
    return [fresh(e) for e in arr_of(v).reshape(-1, order='F')]


def _opts(args, names):
    """Name-value options (case-insensitive) off the end of args: (the rest, {name: value})."""
    args = list(args)
    found = {}
    i = 0
    rest = []
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() in names and i + 1 < len(args):
            found[s.lower()] = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return rest, found


def _flag(v):
    s = opt_str(v)
    if s is not None:
        return s.lower() in ('true', 'on')
    return bool(np.all(darr(v))) if not _is(v) else bool(Y.decide(to_expr(v)))


# ---- which variable --------------------------------------------------------------------------------------------

def _closeness(name):
    """symvar's order of preference: x first, then by distance from x in the
    alphabet (the later letter first on a tie)."""
    c = name[0].lower()
    d = abs(ord(c) - ord('x'))
    return (d, 0 if c > 'x' else 1, name)


def symvars(exprs, n=None):
    s = sp()
    names = set()
    for e in exprs:
        for x in getattr(e, 'free_symbols', ()):
            if isinstance(x, s.Symbol) and not isinstance(x, s.Dummy):
                names.add(x.name)
    if n is None:
        return [symbol(nm) for nm in sorted(names, key=lambda t: (t.lower(), t))]
    return [symbol(nm) for nm in sorted(names, key=_closeness)[:n]]


def _default_var(exprs, fargs=None):
    if fargs:
        return fargs[0]
    v = symvars(exprs, 1)
    return v[0] if v else symbol('x')


def _var(v):
    e = to_expr(v, 'variable')
    s = sp()
    if not isinstance(e, (s.Symbol, s.core.function.AppliedUndef)):
        raise MError('symbolic:sym:NotVariable', f"'{text(e)}' is not a symbolic variable.")
    return e


# ---- making symbolic values -------------------------------------------------------------------------------------

_ASSUME_WORDS = {'real': {'real': True}, 'positive': {'positive': True}, 'integer': {'integer': True}, 'rational': {'rational': True},
                 'nonnegative': {'nonnegative': True}, 'negative': {'negative': True}}


def _make_symbol(name, words=()):
    s = sp()
    kw = {}
    for w in words:
        w = w.lower()
        if w == 'clear':
            kw = {}
            _forget(name)
            continue
        if w not in _ASSUME_WORDS:
            raise MError('symbolic:sym:BadAssumption', f"'{w}' is not an assumption: use real, positive, integer, rational or clear.")
        kw.update(_ASSUME_WORDS[w])
    x = s.Symbol(name, **kw)
    NAMES[name] = x
    _forget(name)
    return x


@bi('sym', aw=True, arr=False)
async def sym_(nargout, *args):
    await Y.ensure()
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'sym')
    v = args[0]
    if _is(v):
        return v
    rest = list(args[1:])
    if is_str(v):
        name = py_str(v).strip()
        if rest and not is_str(rest[0]):
            # sym('a', [m n]): a matrix of symbols a1_1, ... (a1, a2, ... for a vector)
            dims = [int(d) for d in darr(rest[0]).reshape(-1)]
            if len(dims) == 1:
                dims = [dims[0], dims[0]]
            words = [py_str(w) for w in rest[1:]]
            a = np.empty(tuple(dims), object)
            vec = 1 in dims
            for i in np.ndindex(a.shape):
                nm = f'{name}{max(i) + 1}' if vec else f'{name}{i[0] + 1}_{i[1] + 1}'
                a[i] = _make_symbol(nm, words) if words else symbol(nm)
            return Sym(a)
        if Y._NAME.match(name) and name not in ('pi', 'Inf', 'inf', 'NaN', 'nan', 'i', 'j'):
            return S(_make_symbol(name, [py_str(w) for w in rest]) if rest else symbol(name))
        return S(Y.parse_text(name))
    flag = opt_lower(rest[0]) if rest and opt_str(rest[0]) is not None else 'r'
    if flag not in ('r', 'f', 'd', 'e'):
        raise err('symbolic:sym:BadFlag', "The flag must be 'r', 'f', 'd' or 'e'.", 'sym')
    if type(v) is Cell:
        return Sym(_each(lambda x: to_expr(x), v.a))
    a = darr(v) if not isinstance(v, (float, complex, bool)) else np.array([[v]])
    out_ = np.empty(a.shape, object)
    for i in np.ndindex(a.shape):
        out_[i] = Y.num2sym(a[i], 'r' if flag == 'e' else flag)
    return Sym(out_)


@bi('syms', ws=True, aw=True, arr=False)
async def syms(W, nargout, *args):
    await Y.ensure()
    words = [py_str(a) if is_str(a) else a for a in args]
    if not words:
        names = sorted(k for k in W.keys() if type(W.get(k)) is Sym) if hasattr(W, 'keys') else []
        if nargout:
            return Cell.of_list([Char.of(n) for n in names], (len(names), 1)) if hasattr(Cell, 'of_list') else Cell(np.array([[Char.of(n)] for n in names], object))
        if names:
            R.write('\n' + '  '.join(names) + '\n\n')
        return None
    # syms a [1 3]: the size given after a name, in words of its own
    joined = []
    i = 0
    while i < len(words):
        w = words[i]
        if isinstance(w, str) and w.startswith('[') and not w.endswith(']'):
            j = i
            parts = [w]
            while j + 1 < len(words) and not str(parts[-1]).endswith(']'):
                j += 1
                parts.append(words[j])
            joined.append(' '.join(map(str, parts)))
            i = j + 1
            continue
        joined.append(w)
        i += 1
    assume = [w for w in joined if isinstance(w, str) and w.lower() in tuple(_ASSUME_WORDS) + ('clear',)]
    items = [w for w in joined if not (isinstance(w, str) and w.lower() in tuple(_ASSUME_WORDS) + ('clear',))]
    made = []
    k = 0
    while k < len(items):
        w = items[k]
        size = None
        if k + 1 < len(items) and (not isinstance(items[k + 1], str) or str(items[k + 1]).startswith('[')):
            nxt = items[k + 1]
            size = [int(float(t)) for t in str(nxt).strip('[]').replace(',', ' ').split()] if isinstance(nxt, str) else [int(d) for d in darr(nxt).reshape(-1)]
            k += 1
        k += 1
        w = str(w)
        if '(' in w:
            fname, rest_ = w.split('(', 1)
            argn = [t.strip() for t in rest_.rstrip(')').split(',') if t.strip()]
            xs = []
            for a in argn:
                x = _make_symbol(a, assume) if assume else symbol(a)
                W[a] = S(x)
                xs.append(x)
            F = sp().Function(fname.strip())(*xs)
            W[fname.strip()] = S(F, tuple(xs))
            made.append(fname.strip())
            continue
        if not Y._NAME.match(w):
            raise err('symbolic:syms:BadName', f"'{w}' is not a valid variable name.", 'syms')
        if size is not None:
            W[w] = await sym_(1, Char.of(w), np.array([size], float), *[Char.of(a) for a in assume])
        else:
            W[w] = S(_make_symbol(w, assume) if assume else symbol(w))
        made.append(w)
    return None


@bi('str2sym', aw=True, arr=False)
async def str2sym(nargout, *args):
    await Y.ensure()
    if not args or not (is_str(args[0]) or type(args[0]) is Cell):
        raise err('symbolic:str2sym:Input', 'The input must be text.', 'str2sym')
    v = args[0]
    if type(v) is Cell:
        return Sym(_each(lambda t: Y.from_language(py_str(t)), v.a))
    if type(v) is Str and v.a.size != 1:
        return Sym(_each(lambda t: Y.from_language(t), v.a))
    return S(Y.from_language(py_str(v)))


@bi('symfun', aw=True, arr=False)
async def symfun_(nargout, *args):
    await Y.ensure()
    if len(args) != 2:
        raise err('MATLAB:minrhs', 'symfun takes a formula and its input variables.', 'symfun')
    xs = tuple(fresh(e) for e in arr_of(args[1]).reshape(-1))
    return Sym(arr_of(args[0]).copy(), xs)


@bi('vpa', aw=True, arr=False)
async def vpa(nargout, *args):
    await Y.ensure()
    d = int(num(args[1])) if len(args) > 1 else DIGITS[0]
    if class_of(args[0]) == 'logical':
        args = (out(np.asarray(darr(args[0]), dtype=F64)),) + tuple(args[1:])
    A = ex(args[0]) if _is(args[0]) else arr_of(args[0]) if not isinstance(args[0], (float, complex)) else arr_of(args[0])
    # a number is first recognized as sym recognizes it (vpa(pi) is pi to d digits)
    return Sym(_each(lambda e: e.evalf(d), A))


@bi('digits', arr=False)
def digits(nargout, *args):
    old = float(DIGITS[0])
    if args:
        d = int(num(args[0]))
        if d < 1:
            raise err('symbolic:digits:Bad', 'digits must be a positive whole number.', 'digits')
        DIGITS[0] = d
        return old if nargout else None
    if nargout:
        return old
    R.write(f'\nDigits = {int(old)}\n\n')
    return None


@bi('poly2sym', aw=True, arr=False)
async def poly2sym(nargout, *args):
    await Y.ensure()
    c = list(arr_of(args[0]).reshape(-1))
    x = to_expr(args[1]) if len(args) > 1 else symbol('x')
    n = len(c)
    return S(sum((ci * x ** (n - 1 - i) for i, ci in enumerate(c)), sp().Integer(0)))


def _piecewise_numbers(args):
    """piecewise on numbers (a plot of a piecewise expression calls it so): element by element, the first condition that holds."""
    conds = [darr(c, 'piecewise') != 0 for c in args[0:len(args) - 1:2]]
    vals = [darr(v, 'piecewise') for v in args[1::2]]
    other = darr(args[-1], 'piecewise') if len(args) % 2 else np.array([[np.nan]])
    try:
        shape = np.broadcast_shapes(*(a.shape for a in conds + vals + [other]))
    except ValueError:
        raise err('MATLAB:sizeDimensionsMustMatch', 'The conditions and values of piecewise must be the same size (or scalars).', 'piecewise')
    r = np.broadcast_to(other, shape).copy() if other.dtype.kind != 'c' and not any(v.dtype.kind == 'c' for v in vals) \
        else np.broadcast_to(other, shape).astype(complex)
    done = np.zeros(shape, bool)
    for c, v in zip(conds, vals):
        pick = np.broadcast_to(c, shape) & ~done
        r[pick] = np.broadcast_to(v, shape)[pick]
        done |= pick
    return out(r)


@bi('piecewise', aw=True, arr=False)
async def piecewise(nargout, *args):
    if args and not any(_is(a) for a in args):
        return _piecewise_numbers(args)
    s = await Y.ensure()
    pairs = []
    i = 0
    while i + 1 < len(args):
        pairs.append((to_expr(args[i + 1]), Y._boolean(to_expr(args[i]))))
        i += 2
    if i < len(args):
        pairs.append((to_expr(args[i]), s.true))
    else:
        pairs.append((s.nan, s.true))
    # the conditions as written (SymPy would shorten each by the ones before it)
    return S(s.Piecewise(*pairs, evaluate=False))


# ---- calculus ------------------------------------------------------------------------------------------------------

@_over('diff')
def diff_(nargout, *args):
    s = sp()
    f = args[0]
    A = ex(f)
    rest = list(args[1:])
    spec = []
    n_only = None
    for r in rest:
        if _is(r):
            spec.append(_var(r))
        else:
            k = int(num(r))
            if spec:
                spec.append(k)
            else:
                n_only = k
    if not spec:
        v = _default_var(A.reshape(-1), f.fargs if _is(f) else None)
        spec = [v, n_only or 1]
    elif n_only:
        spec.append(n_only)
    return Sym(_each(lambda e: s.diff(e, *spec), A), f.fargs if _is(f) else None)


@bi('int', arr=False)
def int_(nargout, *args):
    s = sp()
    args, o = _opts(args, ('hold', 'ignoreanalyticconstraints', 'principalvalue'))
    f = args[0]
    A = ex(f)
    rest = args[1:]
    if rest and _is(rest[0]) and isinstance(to_expr(rest[0]), (s.Symbol,)) and (len(rest) in (1, 3)):
        x = to_expr(rest[0])
        lims = rest[1:]
    else:
        x = _default_var(A.reshape(-1), f.fargs if _is(f) else None)
        lims = rest
    hold = 'hold' in o and _flag(o['hold'])
    if lims and len(lims) != 2:
        raise err('MATLAB:int:Limits', 'Give the variable and both limits, or just the limits a and b.', 'int')
    if lims:
        a, b = to_expr(lims[0]), to_expr(lims[1])
        g = (lambda e: s.Integral(e, (x, a, b))) if hold else (lambda e: _clean(s.integrate(e, (x, a, b), conds='none')))
    else:
        g = (lambda e: s.Integral(e, x)) if hold else (lambda e: s.integrate(e, x))
    return Sym(_each(g, A), f.fargs if _is(f) else None)


def _clean(e):
    return e


def _tidy(e):
    """The shortest of an expression's simplified forms (a transform's result
    in complex exponentials comes back in sines and cosines, a rational one
    factored)."""
    s = sp()
    forms = [e]
    for f in (s.simplify, s.factor):
        try:
            forms.append(f(e))
        except Exception:
            pass
    if e.has(s.exp) and e.has(s.I):
        for f in (lambda q: s.simplify(q.rewrite(s.cos)), lambda q: s.simplify(s.expand_complex(q))):
            try:
                forms.append(f(e))
            except Exception:
                pass
    for q in list(forms[1:]):
        try:
            forms.append(s.factor(q))
        except Exception:
            pass
    return min(forms, key=lambda q: (s.count_ops(q), len(str(q))))


@bi('limit', arr=False)
def limit(nargout, *args):
    s = sp()
    args = list(args)
    side = None
    if args and opt_str(args[-1]) is not None and opt_lower(args[-1]) in ('left', 'right'):
        side = opt_lower(args.pop())
    f = args[0]
    A = ex(f)
    if len(args) >= 3:
        x, a = _var(args[1]), to_expr(args[2])
    elif len(args) == 2:
        x, a = _default_var(A.reshape(-1)), to_expr(args[1])
    else:
        x, a = _default_var(A.reshape(-1)), s.Integer(0)

    def lim(e):
        if side:
            return s.limit(e, x, a, dir='-' if side == 'left' else '+')
        if a in (s.oo, -s.oo):
            return s.limit(e, x, a)
        # from both sides: NaN when they differ
        lo, hi = s.limit(e, x, a, dir='-'), s.limit(e, x, a, dir='+')
        return hi if lo == hi or s.simplify(lo - hi) == 0 else s.nan
    return Sym(_each(lim, A))


def _series(args, name):
    s = sp()
    args, o = _opts(args, ('order', 'expansionpoint', 'orderMode'.lower()))
    f = args[0]
    A = ex(f)
    x = _var(args[1]) if len(args) > 1 and _is(args[1]) and isinstance(to_expr(args[1]), s.Symbol) else _default_var(A.reshape(-1))
    a = to_expr(args[2]) if len(args) > 2 else (to_expr(o['expansionpoint']) if 'expansionpoint' in o else s.Integer(0))
    n = int(num(o['order'])) if 'order' in o else 6
    if a in (s.oo, -s.oo):
        return Sym(_each(lambda e: s.series(e, x, a, n).removeO(), A))
    return Sym(_each(lambda e: s.series(e, x, a, n).removeO(), A))


@bi('taylor', arr=False)
def taylor(nargout, *args):
    return _series(args, 'taylor')


@bi('series', arr=False)
def series(nargout, *args):
    return _series(args, 'series')


def _sum_prod(args, fn, name):
    s = sp()
    f = args[0]
    A = ex(f)
    rest = args[1:]
    if rest and _is(rest[0]) and isinstance(to_expr(rest[0]), s.Symbol) and len(rest) != 2:
        k = to_expr(rest[0])
        lims = rest[1:]
    else:
        k = _default_var(A.reshape(-1))
        lims = rest
    if lims and len(lims) != 2:
        raise err(f'MATLAB:{name}:Limits', 'Give the variable and both limits, or just the limits a and b.', name)
    if lims:
        a, b = to_expr(lims[0]), to_expr(lims[1])
    else:
        a, b = s.Integer(0), k - 1
    return Sym(_each(lambda e: _closed(fn, e, k, a, b), A))


def _closed(fn, e, k, a, b):
    """A sum or product in closed form where SymPy can be brought to one: an infinite one left unevaluated as the
    limit of the finite one, simplified; rising and falling factorials (which the language has no names for)
    simplified away through gamma functions."""
    s = sp()
    r = fn(e, (k, a, b))
    if isinstance(r, (s.Product, s.Sum)) and b == s.oo:
        m = s.Dummy('m', integer=True, positive=True)
        part = s.simplify(fn(e, (k, a, m)))
        if not part.has(s.Product, s.Sum):
            lim = s.limit(part, m, s.oo)
            if not lim.has(s.AccumBounds, s.Limit):
                r = lim
    if r.has(s.RisingFactorial, s.FallingFactorial):
        r = s.gammasimp(r)
    return r


@bi('symsum', arr=False)
def symsum(nargout, *args):
    return _sum_prod(args, sp().summation, 'symsum')


@bi('symprod', arr=False)
def symprod(nargout, *args):
    return _sum_prod(args, sp().product, 'symprod')


def _vars_arg(v):
    if v is None:
        return None
    return [fresh(e) for e in arr_of(v).reshape(-1, order='F')]


@bi('jacobian', arr=False)
def jacobian(nargout, *args):
    s = sp()
    f = _flat(args[0])
    xs = _vars_arg(args[1]) if len(args) > 1 else symvars(f)
    M = s.Matrix(f).jacobian(xs)
    return Sym(Y._np(M))


@bi('hessian', arr=False)
def hessian(nargout, *args):
    s = sp()
    f = to_expr(args[0])
    xs = _vars_arg(args[1]) if len(args) > 1 else symvars([f])
    return Sym(Y._np(s.hessian(fresh(f), xs)))


@_over('gradient')
def gradient_(nargout, *args):
    s = sp()
    f = fresh(to_expr(args[0]))
    xs = _vars_arg(args[1]) if len(args) > 1 else symvars([f])
    a = np.empty((len(xs), 1), object)
    for i, x in enumerate(xs):
        a[i, 0] = s.diff(f, x)
    return Sym(a)


def _field_parts(args, fn, n_in):
    """A numeric vector field's coordinates (or None) and components: from
    (X, Y, [Z,] U, V, [W]) or (U, V, [W])."""
    from ._util import darr
    a = [darr(x).astype(float) for x in args]
    if any(x.shape != a[0].shape for x in a) or a[0].ndim != n_in or min(a[0].shape) < 2:
        raise err(f'MATLAB:{fn}:Size', f'The arrays of a field in {n_in} dimensions must be {n_in}-D, all of one size, at least 2 along each dimension.', fn)
    if len(a) == 2 * n_in:
        return a[:n_in], a[n_in:]
    if len(a) == n_in:
        return None, a
    raise err(f'MATLAB:{fn}:nargin', f'{fn} takes U, V (and W), with their X, Y (and Z) first if given.', fn)


def _partial(F, coords, d):
    """dF along dimension d of the field (x the second, y the first, z the third)."""
    from .funfun import _grad_along
    axis = {0: 1, 1: 0, 2: 2}[d]
    if coords is None:
        h = 1.0
    else:
        C = coords[d]
        idx = [0] * C.ndim
        idx[axis] = slice(None)
        h = C[tuple(idx)].reshape(-1)
    return _grad_along(F, h, axis)


def _numeric_field(args):
    return args and not any(isinstance(a, Sym) for a in args) and all(not is_str(a) for a in args)


@bi('divergence', arr=False)
def divergence(nargout, *args):
    if _numeric_field(args) and len(args) in (2, 3, 4, 6):
        from ._util import out
        n = 2 if len(args) in (2, 4) else 3
        coords, comps = _field_parts(args, 'divergence', n)
        return out(sum(_partial(F, coords, d) for d, F in enumerate(comps)))
    s = sp()
    V = _flat(args[0])
    xs = _vars_arg(args[1]) if len(args) > 1 else symvars(V)
    if len(xs) != len(V):
        raise err('symbolic:divergence:Size', 'The field and the variables must have as many elements.', 'divergence')
    return S(sum((s.diff(v, x) for v, x in zip(V, xs)), s.Integer(0)))


@bi('curl', nout=4, arr=False)
def curl(nargout, *args):
    if _numeric_field(args) and len(args) in (2, 3, 4, 6):
        from ._util import out
        n = 2 if len(args) in (2, 4) else 3
        coords, comps = _field_parts(args, 'curl', n)
        if n == 2:
            U, V = comps
            cz = _partial(V, coords, 0) - _partial(U, coords, 1)
            # one output: the angular velocity
            return (out(cz), out(cz / 2)) if nargout > 1 else out(cz / 2)
        U, V, W = comps
        cx = _partial(W, coords, 1) - _partial(V, coords, 2)
        cy = _partial(U, coords, 2) - _partial(W, coords, 0)
        cz = _partial(V, coords, 0) - _partial(U, coords, 1)
        with np.errstate(all='ignore'):
            speed = np.sqrt(U ** 2 + V ** 2 + W ** 2)
            cav = 0.5 * (cx * U + cy * V + cz * W) / speed
        res = (out(cx), out(cy), out(cz), out(cav))
        return res[3] if nargout <= 1 else res[:nargout]
    s = sp()
    V = _flat(args[0])
    xs = _vars_arg(args[1]) if len(args) > 1 else symvars(V)
    if len(V) != 3 or len(xs) != 3:
        raise err('symbolic:curl:Size', 'curl takes a field of three components in three variables.', 'curl')
    (P, Q, Rr), (x, y, z) = V, xs
    a = np.empty((3, 1), object)
    a[0, 0] = s.diff(Rr, y) - s.diff(Q, z)
    a[1, 0] = s.diff(P, z) - s.diff(Rr, x)
    a[2, 0] = s.diff(Q, x) - s.diff(P, y)
    return Sym(a)


@bi('laplacian', arr=False)
def laplacian(nargout, *args):
    s = sp()
    f = fresh(to_expr(args[0]))
    xs = _vars_arg(args[1]) if len(args) > 1 else symvars([f])
    return S(sum((s.diff(f, x, 2) for x in xs), s.Integer(0)))


# ---- algebra ---------------------------------------------------------------------------------------------------------

@bi('simplify', arr=False)
def simplify(nargout, *args):
    s = sp()
    args, o = _opts(args, ('steps', 'ignoreanalyticconstraints', 'seconds', 'criterion', 'all'))
    f = args[0]
    ign = 'ignoreanalyticconstraints' in o and _flag(o['ignoreanalyticconstraints'])

    def simp(e):
        if ign:
            e = s.powdenest(s.expand_log(e, force=True), force=True)
            e = s.logcombine(e, force=True)
        return s.simplify(Y.settle(e))
    return Sym(_each(simp, ex(f)), f.fargs if _is(f) else None)


@bi('simplifyFraction', arr=False)
def simplifyFraction(nargout, *args):
    s = sp()
    return Sym(_each(lambda e: s.cancel(s.together(e)), ex(args[0])), _fa(args[0]))


@bi('expand', arr=False)
def expand(nargout, *args):
    s = sp()
    args, o = _opts(args, ('arithmeticonly', 'ignoreanalyticconstraints'))
    only = 'arithmeticonly' in o and _flag(o['arithmeticonly'])
    force = 'ignoreanalyticconstraints' in o and _flag(o['ignoreanalyticconstraints'])
    f = args[0]
    g = (lambda e: s.expand(e, power_exp=False, power_base=False, log=False, multinomial=True, mul=True)) if only else \
        (lambda e: s.expand(e, trig=True, force=force))
    return Sym(_each(g, ex(f)), f.fargs if _is(f) else None)


@_over('factor')
def factor_(nargout, *args):
    s = sp()
    e = fresh(to_expr(args[0]))
    if e.is_Integer or (e.is_Rational and not e.free_symbols):
        parts = []
        for which, num_ in ((1, e.p), (-1, e.q)):
            for p_, m in sorted(s.factorint(abs(num_)).items()):
                parts += [s.Integer(p_) ** which] * m
        if e < 0:
            parts = [s.Integer(-1)] + parts
        return Y.of_array(parts or [s.Integer(1)])
    xs = _vars_arg(args[1]) if len(args) > 1 and _is(args[1]) else None
    n, d = s.fraction(s.together(e))
    parts = []
    for which, part in ((1, n), (-1, d)):
        if part == 1:
            continue
        c, fl = s.factor_list(part, *(xs or []))
        if c != 1 and which == 1:
            parts.append(c)
        elif c != 1:
            parts.append(1 / c)
        for f_, m in fl:
            parts += [f_ ** which] * m
    return Y.of_array(parts or [s.Integer(1)])


@bi('collect', arr=False)
def collect(nargout, *args):
    s = sp()
    f = args[0]
    A = ex(f)
    x = _vars_arg(args[1]) if len(args) > 1 else [_default_var(A.reshape(-1))]
    return Sym(_each(lambda e: s.collect(s.expand(e), x), A), _fa(f))


@bi('combine', arr=False)
def combine(nargout, *args):
    s = sp()
    args, o = _opts(args, ('ignoreanalyticconstraints',))
    target = opt_lower(args[1]) if len(args) > 1 and opt_str(args[1]) is not None else 'powers'
    force = 'ignoreanalyticconstraints' in o and _flag(o['ignoreanalyticconstraints'])
    g = {'sincos': lambda e: s.trigsimp(s.TR8(e)) if hasattr(s, 'TR8') else s.trigsimp(e), 'log': lambda e: s.logcombine(e, force=force),
         'exp': lambda e: s.powsimp(e, combine='exp'), 'powers': lambda e: s.powsimp(e, force=force),
         'sqrt': lambda e: s.powsimp(e, force=force), 'gamma': lambda e: s.gammasimp(e), 'atan': lambda e: s.simplify(e),
         'sinhcosh': lambda e: s.trigsimp(e)}.get(target)
    if g is None:
        raise err('symbolic:combine:Target', f"'{target}' is not something combine knows: use sincos, log, exp, powers, sqrt, gamma or atan.", 'combine')
    if target == 'sincos':
        from sympy.simplify.fu import TR8
        g = lambda e: TR8(e)
    return Sym(_each(g, ex(args[0])), _fa(args[0]))


@bi('horner', arr=False)
def horner(nargout, *args):
    s = sp()
    xs = _vars_arg(args[1]) if len(args) > 1 else None
    return Sym(_each(lambda e: s.horner(e, *(xs or [])), ex(args[0])), _fa(args[0]))


_REWRITE = {'exp': 'exp', 'log': 'log', 'sin': 'sin', 'cos': 'cos', 'tan': 'tan', 'cot': 'cot', 'sqrt': 'sqrt', 'heaviside': 'Heaviside',
            'piecewise': 'Piecewise', 'asin': 'asin', 'acos': 'acos', 'atan': 'atan', 'acot': 'acot', 'sinh': 'sinh', 'cosh': 'cosh',
            'tanh': 'tanh', 'asinh': 'asinh', 'acosh': 'acosh', 'atanh': 'atanh', 'sincos': 'cos', 'sinhcosh': 'cosh'}


@bi('rewrite', arr=False)
def rewrite(nargout, *args):
    s = sp()
    target = opt_lower(args[1]) if len(args) > 1 and opt_str(args[1]) is not None else None
    if target not in _REWRITE:
        raise err('symbolic:rewrite:Target', f"rewrite knows these targets: {', '.join(sorted(_REWRITE))}.", 'rewrite')
    fn = getattr(s, _REWRITE[target])
    if target == 'sincos':
        def sc(e):
            return e.replace(s.tan, lambda u: s.sin(u) / s.cos(u)).replace(s.cot, lambda u: s.cos(u) / s.sin(u)) \
                    .replace(s.sec, lambda u: 1 / s.cos(u)).replace(s.csc, lambda u: 1 / s.sin(u))
        return Sym(_each(sc, ex(args[0])), _fa(args[0]))
    return Sym(_each(lambda e: e.rewrite(fn), ex(args[0])), _fa(args[0]))


@bi('partfrac', arr=False)
def partfrac(nargout, *args):
    s = sp()
    args, o = _opts(args, ('factormode',))
    A = ex(args[0])
    x = _var(args[1]) if len(args) > 1 else _default_var(A.reshape(-1))
    full = 'factormode' in o and opt_str(o['factormode']) and opt_lower(o['factormode']) in ('full', 'complex')
    return Sym(_each(lambda e: s.apart(e, x, full=bool(full)).doit() if full else s.apart(e, x), A), _fa(args[0]))


@bi('numden', nout=2, arr=False)
def numden(nargout, *args):
    s = sp()
    A = ex(args[0])
    nums = np.empty(A.shape, object)
    dens = np.empty(A.shape, object)
    for i in np.ndindex(A.shape):
        n, d = s.fraction(s.together(A[i]))
        nums[i], dens[i] = n, d
    return (Sym(nums), Sym(dens))[:max(1, nargout)] if nargout > 1 else Sym(nums)


@bi('coeffs', nout=2, arr=False)
def coeffs(nargout, *args):
    s = sp()
    args = list(args)
    all_ = False
    if args and opt_str(args[-1]) is not None and opt_lower(args[-1]) == 'all':
        all_ = True
        args.pop()
    p = fresh(to_expr(args[0]))
    xs = _vars_arg(args[1]) if len(args) > 1 else symvars([p])
    if not xs:
        c, t = [p], [s.Integer(1)]
    else:
        P = s.Poly(p, *xs)
        if all_ and len(xs) == 1:
            c = P.all_coeffs()
            n = len(c) - 1
            t = [xs[0] ** (n - i) for i in range(n + 1)]
        else:
            terms = sorted(P.terms(), key=lambda mt: mt[0])
            c = [ct for _, ct in terms]
            t = [s.Mul(*(x ** k for x, k in zip(xs, m))) for m, _ in terms]
            if all_:
                c, t = c[::-1], t[::-1]
    C = Y.of_array(c)
    return (C, Y.of_array(t)) if nargout > 1 else C


@bi('sym2poly', arr=False)
def sym2poly(nargout, *args):
    s = sp()
    p = fresh(to_expr(args[0]))
    xs = symvars([p])
    if len(xs) > 1:
        raise err('symbolic:sym2poly:Variables', 'sym2poly takes a polynomial in one variable.', 'sym2poly')
    if not xs:
        return float(p)
    c = s.Poly(p, xs[0]).all_coeffs()
    try:
        return out(np.array([[complex(x) if not x.is_real else float(x) for x in c]]))
    except TypeError:
        raise err('symbolic:sym2poly:Coefficients', 'The coefficients must be numbers.', 'sym2poly')


@bi('children', arr=False)
def children(nargout, *args):
    e = fresh(to_expr(args[0]))
    kids = list(e.args) if e.args else [e]
    if isinstance(e, sp().core.relational.Relational):
        kids = [e.lhs, e.rhs]
    return Cell(np.array([[S(k) for k in kids]], object))


@bi('has', arr=False)
def has(nargout, *args):
    A = ex(args[0])
    subs_ = _flat(args[1])
    r = np.zeros(A.shape, bool)
    for i in np.ndindex(A.shape):
        r[i] = any(A[i].has(x) for x in subs_)
    return bool(r[0, 0]) if r.size == 1 else r


@bi('lhs', arr=False)
def lhs(nargout, *args):
    return Sym(_each(lambda e: e.lhs if hasattr(e, 'lhs') else e, ex(args[0])))


@bi('rhs', arr=False)
def rhs(nargout, *args):
    return Sym(_each(lambda e: e.rhs if hasattr(e, 'rhs') else sp().Integer(0), ex(args[0])))


@bi('isolate', arr=False)
def isolate(nargout, *args):
    s = sp()
    eq = fresh(to_expr(args[0]))
    # a variable or an expression (diff(y(t), t, 2), sin(x), ...)
    x = fresh(to_expr(args[1], 'expression'))
    if getattr(x, 'is_number', True) or isinstance(x, (s.core.relational.Relational, s.logic.boolalg.BooleanFunction)):
        raise err('symbolic:isolate:Input', f"isolate takes a variable or an expression to isolate, not '{text(x)}'.", 'isolate')
    e = eq.lhs - eq.rhs if isinstance(eq, s.Eq) else eq
    sols = s.solve(e, x)
    if not sols:
        raise err('symbolic:isolate:NoSolution', f'Unable to isolate {text(x)}.', 'isolate')
    return S(s.Eq(x, sols[0], evaluate=False))


@bi('argnames', arr=False)
def argnames(nargout, *args):
    f = args[0]
    if not _is(f) or f.fargs is None:
        raise err('symbolic:argnames:NotSymfun', 'argnames takes a symbolic function.', 'argnames')
    return Y.of_array(list(f.fargs))


@bi('formula', arr=False)
def formula(nargout, *args):
    f = args[0]
    return Sym(f.a) if _is(f) else f


@_over('compose')
def compose_(nargout, *args):
    s = sp()
    f, g = fresh(to_expr(args[0])), fresh(to_expr(args[1]))
    x = _var(args[2]) if len(args) > 2 else _default_var([f])
    y = _var(args[3]) if len(args) > 3 else _default_var([g])
    r = f.subs(x, g)
    if len(args) > 4:
        r = r.subs(y, to_expr(args[4]))
    return S(r)


@bi('finverse', arr=False)
def finverse(nargout, *args):
    s = sp()
    f = fresh(to_expr(args[0]))
    x = _var(args[1]) if len(args) > 1 else _default_var([f])
    y = s.Dummy('y')
    sols = s.solve(s.Eq(y, f), x)
    if not sols:
        raise err('symbolic:finverse:NoInverse', 'No inverse found.', 'finverse')
    if len(sols) > 1:
        # the branch that is real where f is (at a positive point), then the simplest
        def real_at(g):
            try:
                v = complex(g.subs(y, s.Rational(5, 2)).evalf())
                return abs(v.imag) < 1e-12
            except (TypeError, ValueError):
                return False
        sols.sort(key=lambda g: (not real_at(g), s.count_ops(g)))
        if sum(map(real_at, sols)) != 1:
            # several real inverses (x^2), or none: the one given is a choice (exp's other inverses are complex)
            R.write('Warning: the function has more than one inverse; finverse gives one.\n')
    return S(sols[0].subs(y, x))


# ---- substitution -------------------------------------------------------------------------------------------------------

@bi('subs', ws=True, arr=False)
def subs(W, nargout, *args):
    s = sp()
    f = args[0]
    A = ex(f)
    if len(args) == 1:
        rep = {}
        for e in A.flat:
            for x in getattr(e, 'free_symbols', ()):
                v = W.get(x.name) if hasattr(W, 'get') else None
                if v is not None and not (_is(v) and v.a.size == 1 and v.a[0, 0] == x):
                    rep[x] = v
        olds = [S(x) for x in rep]
        news = list(rep.values())
    elif len(args) == 2:
        olds = [S(_default_var(A.reshape(-1), f.fargs if _is(f) else None))]
        news = [args[1]]
    else:
        old, new = args[1], args[2]
        if type(old) is Cell:
            olds = list(old.a.reshape(-1, order='F'))
            news = list(new.a.reshape(-1, order='F')) if type(new) is Cell else [new]
        elif numel(old) > 1:
            olds = [S(e) for e in arr_of(old).reshape(-1, order='F')]
            na = arr_of(new) if type(new) is not Cell else None
            news = [S(e) for e in na.reshape(-1, order='F')] if na is not None and na.size == len(olds) else list(new.a.reshape(-1, order='F'))
        else:
            olds, news = [old], [new]
    pairs = [(fresh(to_expr(o)), arr_of(n)) for o, n in zip(olds, news)]
    big = [n for _, n in pairs if n.size != 1]
    if big and A.size == 1:
        shape = big[0].shape
        out_ = np.empty(shape, object)
        for i in np.ndindex(shape):
            out_[i] = _subs_one(A[0, 0], {o: (n[i] if n.size != 1 else n[0, 0]) for o, n in pairs})
        return Sym(out_)
    if big and any(n.shape != A.shape for n in big):
        raise err('symbolic:subs:Size', 'The values must be scalars, or arrays the size of the expression.', 'subs')
    out_ = np.empty(A.shape, object)
    for i in np.ndindex(A.shape):
        out_[i] = _subs_one(A[i], {o: (n[i] if n.size != 1 else n[0, 0]) for o, n in pairs})
    return Sym(out_, f.fargs if _is(f) else None)


def _subs_one(e, rep):
    s = sp()
    # SymPy's subs passes over a Subs (an initial value such as subs(diff(x(t), t), t, 0)): xreplace finds it
    held = {o: v for o, v in rep.items() if isinstance(o, s.Subs)}
    if held:
        e = e.xreplace(held)
    return Y.settle(e.subs({o: v for o, v in rep.items() if o not in held}, simultaneous=True))


# ---- equations -------------------------------------------------------------------------------------------------------------

def _as_zero(e):
    s = sp()
    if isinstance(e, s.Eq):
        return e.lhs - e.rhs
    return e


def _sol_out(nargout, xs, sols, extra=None):
    """Solutions for the variables: a column for one variable, a struct of
    columns or one output for each variable for several."""
    s = sp()
    if len(xs) == 1 and nargout <= 1:
        return Y.of_array([[v] for v in sols[0]]) if sols[0] else Sym(np.empty((0, 1), object))
    cols = [Sym(np.array([[v] for v in col], object).reshape(-1, 1)) if col else Sym(np.empty((0, 1), object)) for col in sols]
    if nargout <= 1:
        d = {x.name if hasattr(x, 'name') else text(x): c for x, c in zip(xs, cols)}
        if extra:
            d.update(extra)
        return Struct.scalar(d)
    outs = cols + (list(extra.values()) if extra else [])
    return tuple(outs[:nargout])


def _assumed_ok(x, v):
    """Whether a solution v for x satisfies x's assumptions (and relations assumed)."""
    s = sp()
    xs = NAMES.get(x.name, x) if hasattr(x, 'name') else x
    for k, req in (('real', v.is_real), ('positive', v.is_positive), ('negative', v.is_negative), ('integer', v.is_integer),
                   ('nonnegative', v.is_nonnegative), ('rational', v.is_rational)):
        if getattr(xs, f'is_{k}', None) and req is False:
            return False
    for rel in RELS.get(getattr(x, 'name', ''), []):
        try:
            r = rel.subs(xs, v)
            if r is s.false:
                return False
        except Exception:
            pass
    return True


@bi('solve', nout=10, arr=False)
def solve(nargout, *args):
    s = sp()
    args, o = _opts(args, ('real', 'returnconditions', 'principalvalue', 'ignoreanalyticconstraints', 'maxdegree', 'ignoreproperties'))
    eqs = []
    xs = []
    for a in args:
        if not _is(a):
            raise err('symbolic:solve:Input', 'solve takes symbolic equations and variables.', 'solve')
    # the equations first, then the variables (symbols)
    k = len(args)
    while k > 1 and all(isinstance(e, s.Symbol) for e in arr_of(args[k - 1]).reshape(-1)) and not any(
            isinstance(e, (s.Eq, s.core.relational.Relational)) for e in arr_of(args[k - 1]).reshape(-1)):
        k -= 1
    for a in args[:k]:
        eqs += _flat(a)
    for a in args[k:]:
        xs += _flat(a)
    if not xs:
        xs = symvars(eqs, 1) if len(eqs) == 1 else symvars(eqs)[:max(len(eqs), 1)] if len(symvars(eqs)) > len(eqs) else symvars(eqs)
    real = 'real' in o and _flag(o['real'])
    cond = 'returnconditions' in o and _flag(o['returnconditions'])
    principal = 'principalvalue' in o and _flag(o['principalvalue'])
    maxdeg = int(num(o['maxdegree'])) if 'maxdegree' in o else 3
    rels = [e for e in eqs if isinstance(e, s.core.relational.Relational) and not isinstance(e, (s.Eq, s.Ne))]
    if real:
        xs_r = [s.Symbol(x.name, real=True) for x in xs]
        eqs = [e.subs(dict(zip(xs, xs_r))) for e in eqs]
        back = dict(zip(xs_r, xs))
        xs_solve = xs_r
    else:
        back = {}
        xs_solve = xs
    if cond and len(xs) == 1 and len(eqs) == 1 and not rels:
        return _solve_conditions(nargout, eqs[0], xs_solve[0], xs[0], back, real)
    if rels and len(xs) == 1:
        r = s.solve([e if e in rels else _as_zero(e) for e in eqs], xs_solve[0])
        r = r.xreplace(back) if back else r
        if cond:
            return _sol_out(nargout, xs, [[xs[0]]], {'parameters': S(xs[0]), 'conditions': S(r)})
        return S(r)
    zeros = [_as_zero(e) for e in eqs]
    try:
        sols = s.solve(zeros, xs_solve, dict=True, cubics=maxdeg >= 3, quartics=maxdeg >= 4, quintics=False)
    except NotImplementedError:
        sols = []
    cols = [[] for _ in xs]
    seen = set()
    for d in sols:
        vals = []
        for x, xr in zip(xs, xs_solve):
            v = d.get(xr, xr)
            v = v.xreplace(back) if back else v
            vals.append(v)
        if not all(_assumed_ok(x, v) for x, v in zip(xs, vals)):
            continue
        if real and not all(v.is_real is not False for v in vals):
            continue
        key = tuple(s.srepr(v) for v in vals)
        if key in seen:
            continue
        seen.add(key)
        for c, v in zip(cols, vals):
            c.append(v)
    if principal:
        cols = [c[:1] for c in cols]
    if not sols or not cols[0]:
        if not sols:
            R.write('Warning: Unable to find explicit solution. For options, see help.\n') if not zeros or True else None
    if cond:
        return _sol_out(nargout, xs, cols, {'parameters': Sym(np.empty((1, 0), object)), 'conditions': Y.of_array([[s.true]] * len(cols[0])) if cols[0] else Sym(np.empty((0, 1), object))})
    return _sol_out(nargout, xs, cols)


def _solve_conditions(nargout, eq, x, x0, back, real):
    """solve(..., 'ReturnConditions', true) for one equation: solveset's sets
    as solutions with a parameter k and its conditions."""
    s = sp()
    k = symbol('k')
    dom = s.S.Reals if real else s.S.Complexes
    try:
        st = s.solveset(_as_zero(eq), x, domain=dom)
    except Exception:
        st = s.ConditionSet(x, eq, dom)
    sols, conds, params = [], [], []

    def add_set(t):
        if isinstance(t, s.FiniteSet):
            for v in t:
                sols.append(v.xreplace(back) if back else v)
                conds.append(s.true)
        elif isinstance(t, s.ImageSet):
            lam = t.lamda
            n = lam.variables[0]
            sols.append(lam.expr.subs(n, k))
            conds.append(s.Contains(k, s.Integers))
            if k not in params:
                params.append(k)
        elif isinstance(t, s.Union):
            for u in t.args:
                add_set(u)
        elif isinstance(t, (s.Interval,)):
            sols.append(x0)
            conds.append(t.as_relational(x0))
            if x0 not in params:
                params.append(x0)
        elif isinstance(t, s.Intersection):
            for u in t.args:
                if not (u is s.S.Reals):
                    add_set(u)
        elif isinstance(t, s.Complement):
            add_set(t.args[0])
        else:
            sols.append(x0)
            conds.append(eq)
            params.append(x0)
    add_set(st)
    sol = Y.of_array([[v] for v in sols]) if sols else Sym(np.empty((0, 1), object))
    cnd = Y.of_array([[c] for c in conds]) if conds else Sym(np.empty((0, 1), object))
    par = Y.of_array(params) if params else Sym(np.empty((1, 0), object))
    if nargout <= 1:
        return Struct.scalar({x0.name: sol, 'parameters': par, 'conditions': cnd})
    return (sol, par, cnd)[:nargout]


@bi('vpasolve', nout=10, arr=False)
def vpasolve(nargout, *args):
    s = sp()
    args, o = _opts(args, ('random',))
    eqs, xs, guess = [], [], None
    syms_args = []
    for a in args:
        if _is(a):
            syms_args.append(a)
        else:
            guess = darr(a)
    k = len(syms_args)
    while k > 1 and all(isinstance(e, s.Symbol) for e in arr_of(syms_args[k - 1]).reshape(-1)):
        k -= 1
    for a in syms_args[:k]:
        eqs += [_as_zero(e) for e in _flat(a)]
    for a in syms_args[k:]:
        xs += _flat(a)
    if not xs:
        xs = symvars(eqs)
    d = DIGITS[0]
    if len(eqs) == 1 and len(xs) == 1:
        e, x = eqs[0], xs[0]
        try:
            P = s.Poly(e, x)
            if guess is None:
                roots = [r for r in P.nroots(n=d, maxsteps=200)]
                return Y.of_array([[r] for r in roots]) if roots else Sym(np.empty((0, 1), object))
        except (s.PolynomialError, s.polys.polyerrors.GeneratorsNeeded):
            pass
        if guess is not None and guess.size == 2 and guess.shape[-1] == 2 and guess.ndim == 2 and guess.shape[0] == 1:
            a, b = float(guess[0, 0]), float(guess[0, 1])
            try:
                r = s.nsolve(e, x, (a, b), solver='bisect', prec=d)
            except Exception:
                r = s.nsolve(e, x, (a + b) / 2, prec=d)
        else:
            x0 = float(guess.reshape(-1)[0]) if guess is not None else 0.0
            try:
                r = s.nsolve(e, x, x0, prec=d)
            except Exception:
                r = None
                for start in (1.0, -1.0, 0.5, 2.0, -2.0, 10.0):
                    try:
                        r = s.nsolve(e, x, start, prec=d)
                        break
                    except Exception:
                        continue
                if r is None:
                    return Sym(np.empty((0, 1), object))
        return S(r)
    x0 = list(guess.reshape(-1)) if guess is not None and guess.size == len(xs) else [0.5] * len(xs)
    try:
        r = s.nsolve(eqs, xs, x0, prec=d)
        cols = [[r[i]] for i in range(len(xs))]
    except Exception:
        cols = [[] for _ in xs]
    return _sol_out(nargout, xs, cols)


@bi('dsolve', nout=10, arr=False)
def dsolve(nargout, *args):
    s = sp()
    args, o = _opts(args, ('ignoreanalyticconstraints', 'maxdegree', 'expansionpoint', 'order'))
    rels = []
    for a in args:
        if not _is(a):
            raise err('symbolic:dsolve:Input', 'dsolve takes symbolic equations and conditions.', 'dsolve')
        rels += _flat(a)
    eqs = [r for r in rels if r.has(s.Derivative)]
    conds = [r for r in rels if not r.has(s.Derivative) or isinstance(getattr(r, 'lhs', None), s.Subs)]
    eqs = [r for r in eqs if r not in conds]
    if not eqs:
        raise err('symbolic:dsolve:NoEquation', 'No differential equation given: write it with diff, as diff(y, t) == y.', 'dsolve')
    funcs = []
    for e in eqs:
        for f in e.atoms(s.core.function.AppliedUndef):
            if f.args and all(isinstance(a, s.Symbol) for a in f.args) and f not in funcs:
                funcs.append(f)
    funcs.sort(key=lambda f: str(f.func))
    ics = {}
    for c in conds:
        if not isinstance(c, s.Eq):
            raise err('symbolic:dsolve:Condition', f"The condition '{text(c)}' must be an equation, as y(0) == 1.", 'dsolve')
        ics[c.lhs] = c.rhs
    eq_list = [e if isinstance(e, s.Eq) else s.Eq(e, 0) for e in eqs]
    try:
        if len(eq_list) == 1 and len(funcs) == 1:
            sol = s.dsolve(eq_list[0], funcs[0], ics=ics or None)
        else:
            sol = s.dsolve(eq_list, funcs, ics=ics or None)
    except (NotImplementedError, ValueError) as e:
        R.write('Warning: Unable to find symbolic solution.\n')
        return Sym(np.empty((0, 0), object))
    sols = sol if isinstance(sol, list) else [sol]
    if len(funcs) == 1:
        vals = [q.rhs for q in sols]
        return Y.of_array([[v] for v in vals]) if len(vals) > 1 else S(vals[0])
    by = {}
    for q in sols:
        by.setdefault(q.lhs, []).append(q.rhs)
    cols = [by.get(f, []) for f in funcs]
    if nargout <= 1:
        return Struct.scalar({str(f.func): (S(c[0]) if len(c) == 1 else Y.of_array([[v] for v in c])) for f, c in zip(funcs, cols)})
    return tuple(S(c[0]) if len(c) == 1 else Y.of_array([[v] for v in c]) for c in cols)[:nargout]


# ---- transforms ---------------------------------------------------------------------------------------------------------

def _tvars(args, A, first, second, alt):
    """The transform's variable and the new one: given, or the defaults."""
    if len(args) > 2:
        return _var(args[1]), _var(args[2])
    if len(args) == 2:
        x = symbol(first) if any(e.has(symbol(first)) for e in A.flat) else _default_var(A.reshape(-1))
        return x, _var(args[1])
    x = symbol(first) if any(e.has(symbol(first)) for e in A.flat) else _default_var(A.reshape(-1))
    y = symbol(second) if x.name != second else symbol(alt)
    return x, y


@bi('laplace', arr=False)
def laplace(nargout, *args):
    s = sp()
    A = ex(args[0])
    t, z = _tvars(args, A, 't', 's', 'z')
    tp = s.Symbol(t.name, positive=True)

    def lt(e):
        # the variable back as it was, inside the initial values too (subs(diff(x(t), t), t, 0))
        r = _tidy(s.laplace_transform(e.subs(t, tp), tp, z, noconds=True)).xreplace({tp: t})
        if r.has(s.I) and not e.has(s.I) and not r.has(s.LaplaceTransform):
            # a real function's transform in conjugate pairs (t^2*sin(t)): one fraction over the rationals
            q = s.factor(s.cancel(s.together(r)))
            if not q.has(s.I):
                r = q
        return r
    return Sym(_each(lt, A))


@bi('ilaplace', arr=False)
def ilaplace(nargout, *args):
    s = sp()
    A = ex(args[0])
    z, t = _tvars(args, A, 's', 't', 'x')
    tp = s.Symbol(t.name, positive=True)
    return Sym(_each(lambda e: _tidy(s.inverse_laplace_transform(e, z, tp)).xreplace({tp: t}), A))


@bi('fourier', arr=False)
def fourier(nargout, *args):
    s = sp()
    A = ex(args[0])
    x, w = _tvars(args, A, 'x', 'w', 'v')
    k = s.Dummy('k')

    def ft(e):
        r = s.fourier_transform(e, x, k)
        if isinstance(r, s.FourierTransform):
            r = s.integrate(e * s.exp(-s.I * w * x), (x, -s.oo, s.oo), conds='none')
            return r
        return _tidy(r.subs(k, w / (2 * s.pi)))
    return Sym(_each(ft, A))


@bi('ifourier', arr=False)
def ifourier(nargout, *args):
    s = sp()
    A = ex(args[0])
    w, x = _tvars(args, A, 'w', 'x', 't')
    k = s.Dummy('k')

    def ift(e):
        r = s.inverse_fourier_transform(e.subs(w, 2 * s.pi * k), k, x)
        if isinstance(r, s.InverseFourierTransform):
            return s.integrate(e * s.exp(s.I * w * x), (w, -s.oo, s.oo), conds='none') / (2 * s.pi)
        return _tidy(r)
    return Sym(_each(ift, A))


@bi('ztrans', arr=False)
def ztrans(nargout, *args):
    s = sp()
    A = ex(args[0])
    n, z = _tvars(args, A, 'n', 'z', 'w')
    m = s.Symbol(n.name, integer=True, nonnegative=True)

    def zt(e):
        r = s.summation(e.subs(n, m) * z ** (-m), (m, 0, s.oo))
        if isinstance(r, s.Piecewise):
            r = r.args[0][0]
        return s.simplify(r)
    return Sym(_each(zt, A))


@bi('iztrans', arr=False)
def iztrans(nargout, *args):
    """The inverse z-transform of a rational function: the residues of
    F(z)*z^(n-1) at its poles for n >= 1, and F at infinity for n = 0."""
    s = sp()
    A = ex(args[0])
    z, n = _tvars(args, A, 'z', 'n', 'k')
    m = s.Symbol(n.name, integer=True, positive=True)

    def izt(F):
        F = s.together(F)
        num_, den = s.fraction(F)
        if not (s.Poly(num_, z).is_polynomial if hasattr(s.Poly(num_, z), 'is_polynomial') else True) or den.free_symbols - {z} - F.free_symbols:
            pass
        G = F * z ** (m - 1)
        total = s.Integer(0)
        for p, mult in s.roots(s.Poly(den, z)).items():
            h = s.simplify((z - p) ** mult * G)
            total += s.diff(h, z, mult - 1).subs(z, p) / s.factorial(mult - 1)
        f0 = s.limit(F, z, s.oo)
        g0 = s.simplify(total.subs(m, 0))
        r = s.simplify(total)
        if s.simplify(f0 - g0) != 0:
            r = r + (f0 - g0) * s.KroneckerDelta(m, 0)
        return r.subs(m, n)
    return Sym(_each(izt, A))


# ---- assumptions and truth ----------------------------------------------------------------------------------------------

def _forget(name):
    """Drops the relations that mention a variable from those kept for the others."""
    for k in list(RELS):
        keep = [r for r in RELS[k] if all(f.name != name for f in r.free_symbols)]
        if keep:
            RELS[k] = keep
        else:
            RELS.pop(k)


def _refresh_rels():
    """The relations kept, on the variables as now assumed (built unevaluated, so that none settles itself)."""
    Rel = sp().core.relational.Relational
    for k in RELS:
        RELS[k] = [type(r)(fresh(r.lhs), fresh(r.rhs), evaluate=False) if isinstance(r, Rel) else fresh(r) for r in RELS[k]]


def _apply_assumption(x, words_or_rel, also):
    s = sp()
    name = x.name
    if not also or 'clear' in [w.lower() for w in words_or_rel if isinstance(w, str)]:
        _forget(name)
    cur = NAMES.get(name, x)
    kw = dict(cur._assumptions0) if also else {}
    rels = list(RELS.get(name, [])) if also else []
    for w in words_or_rel:
        if isinstance(w, str):
            w = w.lower()
            if w == 'clear':
                kw, rels = {}, []
                continue
            if w not in _ASSUME_WORDS:
                raise MError('symbolic:assume:BadAssumption', f"'{w}' is not an assumption: use real, positive, integer, rational or clear.")
            kw.update(_ASSUME_WORDS[w])
        else:
            rel = w
            other = rel.rhs if rel.lhs.has(x) else rel.lhs
            flip = not rel.lhs.has(x)
            op = type(rel)
            if flip:
                op = {s.Gt: s.Lt, s.Lt: s.Gt, s.Ge: s.Le, s.Le: s.Ge}.get(op, op)
            if other == 0 and rel.lhs in (x,) or (other == 0 and rel.rhs in (x,)):
                kw.update({s.Gt: {'positive': True}, s.Lt: {'negative': True}, s.Ge: {'nonnegative': True}, s.Le: {'nonpositive': True},
                           s.Ne: {'nonzero': True}}.get(op, {}))
                if op is s.Eq:
                    kw.update({'zero': True})
            else:
                kw['real'] = True
                rels.append(rel)
    new = s.Symbol(name, **kw)
    NAMES[name] = new
    if rels:
        RELS[name] = rels
    else:
        RELS.pop(name, None)


def _assume(args, also):
    s = sp()
    if len(args) == 1:
        c = fresh(to_expr(args[0])) if _is(args[0]) else None
        if c is None:
            raise err('symbolic:assume:Input', 'assume takes a condition, or variables and an assumption.', 'assume')
        Rel = s.core.relational.Relational
        parts = c.args if isinstance(c, s.And) else (c,)
        # (a Symbol is a Boolean in SymPy)
        if not all(isinstance(p, (Rel, s.logic.boolalg.BooleanFunction, s.logic.boolalg.BooleanAtom)) for p in parts):
            raise err('symbolic:assume:Input', 'assume takes a condition, or variables and an assumption.', 'assume')
        if not also:
            # assume replaces what was assumed of the variables in the condition
            for x in c.free_symbols:
                _apply_assumption(x, ['clear'], False)
        for part in parts:
            if isinstance(part, s.Contains):
                x, st = part.args
                word = {s.Integers: 'integer', s.Reals: 'real', s.Rationals: 'rational'}.get(st, None)
                _apply_assumption(x, [word], True)
                continue
            xs = sorted(part.free_symbols, key=lambda x: x.name)
            if len(xs) != 1 or not isinstance(part, Rel):
                for x in xs:
                    if part not in RELS.get(x.name, []):
                        RELS.setdefault(x.name, []).append(part)
                continue
            _apply_assumption(xs[0], [part], True)
        _refresh_rels()
        return
    xs = _flat(args[0])
    words = [py_str(a).lower() for a in args[1:]]
    for x in xs:
        _apply_assumption(x, words, also)
    _refresh_rels()


@bi('assume', arr=False)
def assume(nargout, *args):
    _assume(args, False)
    return None


@bi('assumeAlso', arr=False)
def assumeAlso(nargout, *args):
    _assume(args, True)
    return None


@bi('assumptions', arr=False)
def assumptions(nargout, *args):
    s = sp()
    if args and not (_is(args[0]) and all(isinstance(x, s.Symbol) for x in _flat(args[0]))):
        raise err('MATLAB:assumptions:NotVariable', 'assumptions takes symbolic variables.', 'assumptions')
    names = [x.name for x in _flat(args[0])] if args else sorted(NAMES)
    conds = []
    for nm in names:
        x = NAMES.get(nm)
        if x is None:
            continue
        a = dict(x._assumptions0)
        if any(isinstance(r, s.core.relational.Relational) and not isinstance(r, (s.Eq, s.Ne)) for r in RELS.get(nm, [])):
            # an inequality says real already
            a.pop('real', None)
        # shown on a plain symbol of the name, so that they do not settle themselves
        p = s.Symbol(nm)
        for k, rel in (('positive', s.Gt(p, 0, evaluate=False)), ('negative', s.Lt(p, 0, evaluate=False)),
                       ('nonnegative', s.Ge(p, 0, evaluate=False)), ('nonpositive', s.Le(p, 0, evaluate=False)),
                       ('nonzero', s.Ne(p, 0, evaluate=False))):
            if a.get(k):
                conds.append(rel)
                break
        else:
            for k, st in (('integer', s.Integers), ('rational', s.Rationals), ('real', s.Reals)):
                if a.get(k):
                    conds.append(s.Contains(p, st, evaluate=False))
                    break
        if a.get('integer') and any(a.get(k) for k in ('positive', 'negative', 'nonnegative', 'nonpositive')):
            conds.append(s.Contains(p, s.Integers, evaluate=False))
        conds += [r for r in RELS.get(nm, []) if r not in conds]
    return Y.of_array(conds) if conds else Sym(np.empty((1, 0), object))


@bi('isAlways', arr=False)
def isAlways(nargout, *args):
    args, o = _opts(args, ('unknown',))
    unknown = opt_lower(o['unknown']) if 'unknown' in o else 'falsewithwarning'
    A = ex(args[0])
    r = np.zeros(A.shape, bool)
    for i in np.ndindex(A.shape):
        d = Y.decide(A[i])
        if d is None:
            if unknown == 'error':
                raise err('symbolic:isAlways:TruthUnknown', f"Unable to prove '{text(A[i])}'.", 'isAlways')
            if unknown == 'falsewithwarning':
                R.write(f"Warning: Unable to prove '{text(A[i])}'.\n")
            d = unknown == 'true'
        r[i] = d
    return bool(r[0, 0]) if r.size == 1 else r


# ---- conversions and output -------------------------------------------------------------------------------------------------

def _sym_char(v):
    a = v.a
    if a.size == 1:
        return text(a[0, 0])
    rows = ['; '.join([])]
    return '[' + '; '.join(', '.join(text(a[i, j]) for j in range(a.shape[1])) for i in range(a.shape[0])) + ']'


@_over('char')
def char_(nargout, *args):
    return Char.of(_sym_char(args[0]))


@_over('string')
def string_(nargout, *args):
    a = args[0].a
    r = np.empty(a.shape, object)
    for i in np.ndindex(a.shape):
        r[i] = text(a[i])
    return Str(r)


@_over('num2str', 'mat2str')
def num2str_(nargout, *args):
    return Char.of(_sym_char(args[0]))


def _to_number(e):
    s = sp()
    e = fresh(e)
    if e.free_symbols:
        raise MError('symbolic:double:cantconvert', "Unable to convert expression containing symbolic variables into double array. "
                     "Apply 'subs' function first to substitute values for variables.")
    if e is s.true or e is s.false:
        return 1.0 if e is s.true else 0.0
    if isinstance(e, (s.core.relational.Relational, s.logic.boolalg.Boolean)):
        d = Y.decide(e)
        if d is None:
            raise MError('symbolic:double:cantconvert', f"Unable to convert '{text(e)}' into a number.")
        return 1.0 if d else 0.0
    v = complex(e.evalf(17))
    return v.real if v.imag == 0 else v


@_over('double')
def double_(nargout, *args):
    a = args[0].a
    vals = [_to_number(e) for e in a.reshape(-1)]
    cplx = any(isinstance(v, complex) for v in vals)
    r = np.array(vals, C128 if cplx else F64).reshape(a.shape)
    return out(r)


@_over('single')
def single_(nargout, *args):
    r = darr(double_(1, *args))
    return r.astype(np.complex64 if r.dtype.kind == 'c' else np.float32)


@_over('logical')
def logical_(nargout, *args):
    A = ex(args[0])
    r = np.zeros(A.shape, bool)
    for i in np.ndindex(A.shape):
        d = Y.decide(A[i])
        if d is None:
            raise err('symbolic:logical:unknown', f"Unable to prove '{text(A[i])}' literally. Use isAlways to test the statement mathematically.", 'logical')
        r[i] = d
    return bool(r[0, 0]) if r.size == 1 else r


@_over('isequal', 'isequaln')
def isequal_(nargout, *args):
    s = sp()
    first = arr_of(args[0])
    for b in args[1:]:
        B = arr_of(b)
        if B.shape != first.shape:
            return False
        for x, y in zip(first.reshape(-1), B.reshape(-1)):
            x, y = fresh(x), fresh(y)
            if x == y:
                continue
            try:
                if s.simplify(x - y) == 0:
                    continue
            except TypeError:
                pass
            return False
    return True


@bi('latex', arr=False)
def latex(nargout, *args):
    s = sp()
    v = args[0]
    if not _is(v):
        raise err('MATLAB:latex:NotSym', 'latex takes a symbolic expression.', 'latex')
    if v.a.size == 1:
        return Char.of(s.latex(fresh(v.a[0, 0])))
    return Char.of(s.latex(s.Matrix(ex(v).tolist())))


@bi('pretty', arr=False)
def pretty(nargout, *args):
    s = sp()
    v = args[0]
    if not _is(v):
        raise err('MATLAB:pretty:NotSym', 'pretty takes a symbolic expression.', 'pretty')
    e = fresh(v.a[0, 0]) if v.a.size == 1 else s.Matrix(ex(v).tolist())
    R.write('\n' + s.pretty(e, use_unicode=True) + '\n\n')
    return None


@_over('symvar')
def symvar_(nargout, *args):
    exprs = _flat(args[0])
    n = int(num(args[1])) if len(args) > 1 else None
    xs = symvars(exprs, n)
    return Y.of_array(xs) if xs else Sym(np.empty((1, 0), object))


# ---- functions of numbers made from symbolic expressions ----------------------------------------------------------------------

def _numeric_text(e):
    """An expression as code for numbers: element-wise operators."""
    import re
    t = text(e)
    return re.sub(r'(?<![.])([*/^])', r'.\1', t)


def _fh_of(exprs, xs):
    """A function handle @(x, y) ... computing the expressions (a matrix in brackets)."""
    params = ', '.join(x.name for x in xs)
    if len(exprs) == 1 and exprs[0].shape == (1, 1):
        body = _numeric_text(exprs[0][0, 0])
    else:
        A = exprs[0]
        body = '[' + '; '.join(', '.join(_numeric_text(A[i, j]) for j in range(A.shape[1])) for i in range(A.shape[0])) + ']'
    code = f'@({params}) {body}'
    from .core import anon_from_text
    return anon_from_text(code), code


@bi('matlabFunction', arr=False)
def matlabFunction(nargout, *args):
    s = sp()
    args, o = _opts(args, ('vars', 'file', 'outputs', 'optimize', 'sparse', 'comments'))
    exprs = [ex(a) for a in args if _is(a)]
    if not exprs:
        raise err('symbolic:matlabFunction:Input', 'matlabFunction takes symbolic expressions.', 'matlabFunction')
    fargs = next((a.fargs for a in args if _is(a) and a.fargs), None)
    if 'vars' in o:
        v = o['vars']
        xs = [to_expr(x) for x in v.a.reshape(-1)] if type(v) is Cell else _flat(v)
    elif fargs:
        xs = list(fargs)
    else:
        xs = symvars([e for A in exprs for e in A.reshape(-1)])
    for e in (e for A in exprs for e in A.reshape(-1)):
        if e.has(s.Piecewise):
            raise err('symbolic:matlabFunction:Piecewise', 'An expression with piecewise cannot become code here.', 'matlabFunction')
    if 'file' in o:
        path = py_str(o['file'])
        name = os.path.splitext(os.path.basename(path))[0]
        if not path.endswith('.m'):
            path += '.m'
        outs = [py_str(x) for x in o['outputs'].a.reshape(-1)] if 'outputs' in o and type(o['outputs']) is Cell else [f'out{i + 1}' for i in range(len(exprs))]
        lines = [f"function [{', '.join(outs)}] = {name}({', '.join(x.name for x in xs)})",
                 f'%{name.upper()}  made by matlabFunction from symbolic expressions.']
        for nm, A in zip(outs, exprs):
            if A.shape == (1, 1):
                lines.append(f'{nm} = {_numeric_text(A[0, 0])};')
            else:
                lines.append(f"{nm} = [{'; '.join(', '.join(_numeric_text(A[i, j]) for j in range(A.shape[1])) for i in range(A.shape[0]))}];")
        lines.append('end')
        from .iofun import abspath, files_changed
        with open(abspath(path), 'w', encoding='utf-8') as fh:
            fh.write('\n'.join(lines) + '\n')
        files_changed()
        return R.NamedFH(name)
    if len(exprs) > 1:
        raise err('symbolic:matlabFunction:Outputs', "Several outputs need a file: give 'File', name.", 'matlabFunction')
    fh, _ = _fh_of(exprs, xs)
    return fh


# ---- plots of symbolic expressions --------------------------------------------------------------------------------------------

def _plot_fh(v, nvars, fargs=None):
    A = ex(v)
    xs = list(fargs) if fargs else symvars(A.reshape(-1))
    if len(xs) < nvars:
        names = ['x', 'y', 'z'][:nvars]
        for nm in names:
            if all(x.name != nm for x in xs) and len(xs) < nvars:
                xs.append(symbol(nm))
        xs = sorted(xs[:nvars], key=lambda x: x.name)
    fh, _ = _fh_of([A], xs[:nvars])
    return fh


def _with_fhs(name, nvars, args):
    new = []
    for a in args:
        if _is(a):
            e = a.a[0, 0] if a.a.size == 1 else None
            if e is not None and isinstance(e, sp().Eq) and name in ('fimplicit',):
                a = S(e.lhs - e.rhs)
            new.append(_plot_fh(a, nvars, a.fargs if _is(a) else None))
        else:
            new.append(a)
    return new


@_over('fplot')
def fplot_(nargout, *args):
    first = next((i for i, a in enumerate(args) if _is(a)), None)
    if first is not None and args[first].a.size > 1:
        # a vector of expressions: a line for each, in the same axes
        from .graphics import gca_
        from ..graphics_base import HArr
        A = args[first]
        hs, ax, keep = [], None, None
        for e in A.a.reshape(-1, order='F'):
            one = list(args)
            one[first] = Sym(np.array([[e]], object), A.fargs)
            hs.append(OVERLOADS['_orig_fplot'](1, *_with_fhs('fplot', 1, one)))
            if ax is None:
                ax = gca_()
                keep = ax.props['NextPlot']
                ax.props['NextPlot'] = 'add'
        ax.props['NextPlot'] = keep
        return HArr(np.array(hs, object).reshape(-1, 1)) if nargout else None
    return OVERLOADS['_orig_fplot'](nargout, *_with_fhs('fplot', 1, args))


@_over('fpolarplot')
def fpolarplot_(nargout, *args):
    return OVERLOADS['_orig_fpolarplot'](nargout, *_with_fhs('fpolarplot', 1, args))


@_over('ezplot')
def ezplot_(nargout, *args):
    vars_ = symvars([e for a in args if _is(a) for e in ex(a).reshape(-1)])
    if len(vars_) >= 2 and len([a for a in args if _is(a)]) == 1:
        return fimplicit(nargout, *args)
    return OVERLOADS['_orig_ezplot'](nargout, *_with_fhs('ezplot', 1, args))


@_over('fsurf', 'fmesh', 'fcontour')
def fsurf_(nargout, *args):
    raise AssertionError('replaced in install')


@bi('fimplicit', arr=False)
def fimplicit(nargout, *args):
    """The curve f(x, y) = 0: the zero contour of f on a grid."""
    from .graphics import split_axes_arg
    ax, rest = split_axes_arg(args)
    if not rest:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'fimplicit')
    f = rest[0]
    if _is(f):
        f = _with_fhs('fimplicit', 2, [f])[0]
    elif is_str(f):
        f = R.NamedFH(py_str(f))
    if not isinstance(f, FH):
        raise err('MATLAB:fimplicit:InvalidFunction', 'The first input must be a function of x and y.', 'fimplicit')
    lim = darr(rest[1]).reshape(-1) if len(rest) > 1 and not is_str(rest[1]) else np.array([-5.0, 5.0])
    if lim.size not in (2, 4):
        raise err('MATLAB:fimplicit:InvalidLimits', 'The limits are [min max] for both, or [xmin xmax ymin ymax].', 'fimplicit')
    if lim.size == 2:
        lim = np.concatenate([lim, lim])
    x = np.linspace(lim[0], lim[1], 201)
    y = np.linspace(lim[2], lim[3], 201)
    X, Y_ = np.meshgrid(x, y)
    Z = darr(f.scall(1, out(X), out(Y_)))
    if Z.shape != X.shape:
        Z = np.array([[float(np.asarray(darr(f.scall(1, float(a), float(b)))).reshape(-1)[0]) for a, b in zip(ra, rb)] for ra, rb in zip(X, Y_)])
    pairs = [rest[i:i + 2] for i in range(2 if len(rest) > 1 and not is_str(rest[1]) else 1, len(rest) - 1, 2)]
    cargs = ([ax] if ax is not None else []) + [out(X), out(Y_), out(Z), np.array([[0.0, 0.0]])]
    h = REG['contour'].fn(2, *cargs)
    h = h[1] if isinstance(h, tuple) else h
    from ..graphics_base import COLOR_ORDER
    col = h.parent.next_color() if hasattr(h, 'parent') and hasattr(h.parent, 'next_color') else tuple(COLOR_ORDER[0])
    h.props['EdgeColor'] = col
    h.props['LineColor'] = col if 'LineColor' in h.props else col
    for p in pairs:
        if len(p) == 2 and is_str(p[0]):
            REG['set'].fn(0, h, *p)
    return h if nargout else None


@bi('fplot3', arr=False)
def fplot3(nargout, *args):
    from .graphics import split_axes_arg
    ax, rest = split_axes_arg(args)
    fs = []
    if len(rest) < 3:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'fplot3')
    for a in rest[:3]:
        fs.append(_with_fhs('fplot3', 1, [a])[0] if _is(a) else (R.NamedFH(py_str(a)) if is_str(a) else a))
    if not all(isinstance(f, FH) for f in fs):
        raise err('MATLAB:fplot3:InvalidFunction', 'The first three inputs are functions of t.', 'fplot3')
    lim = darr(rest[3]).reshape(-1) if len(rest) > 3 and not is_str(rest[3]) else np.array([-5.0, 5.0])
    if lim.size != 2:
        raise err('MATLAB:fplot3:InvalidLimits', 'The limits are [tmin tmax].', 'fplot3')
    t = np.linspace(lim[0], lim[1], 400).reshape(1, -1)
    vals = []
    for f in fs:
        v = darr(f.scall(1, out(t)))
        if v.size == 1:
            v = np.full(t.shape, float(v.reshape(-1)[0]))
        vals.append(out(v.reshape(1, -1)))
    opts = list(rest[4:]) if len(rest) > 4 else []
    return REG['plot3'].fn(nargout, *(([ax] if ax is not None else []) + vals + opts))


# ---- element by element -----------------------------------------------------------------------------------------------------------

def _unary_table():
    s = sp()
    half = s.Rational(1, 2)
    return {
        'sin': s.sin, 'cos': s.cos, 'tan': s.tan, 'sec': s.sec, 'csc': s.csc, 'cot': s.cot, 'asin': s.asin, 'acos': s.acos,
        'atan': s.atan, 'acot': s.acot, 'asec': s.asec, 'acsc': s.acsc, 'sinh': s.sinh, 'cosh': s.cosh, 'tanh': s.tanh,
        'coth': s.coth, 'sech': s.sech, 'csch': s.csch, 'asinh': s.asinh, 'acosh': s.acosh, 'atanh': s.atanh, 'acoth': s.acoth,
        'asech': s.asech, 'acsch': s.acsch, 'exp': s.exp, 'log': s.log, 'sqrt': s.sqrt, 'abs': s.Abs, 'sign': s.sign,
        'real': s.re, 'imag': s.im, 'conj': s.conjugate, 'angle': s.arg, 'floor': s.floor, 'ceil': s.ceiling,
        'gamma': s.gamma, 'factorial': s.factorial, 'erf': s.erf, 'erfc': s.erfc, 'erfinv': s.erfinv,
        'log2': lambda x: s.log(x) / s.log(2), 'log10': lambda x: s.log(x) / s.log(10), 'log1p': lambda x: s.log(1 + x),
        'expm1': lambda x: s.exp(x) - 1, 'heaviside': lambda x: s.Heaviside(x, half), 'dirac': s.DiracDelta,
        'round': lambda x: (s.sign(x) * s.floor(s.Abs(x) + half)) if x.is_number else s.Function('round')(x),
        'fix': lambda x: (s.sign(x) * s.floor(s.Abs(x))) if x.is_number else s.Function('fix')(x),
        'sinc': lambda x: s.sin(s.pi * x) / (s.pi * x) if x != 0 else s.Integer(1), 'lambertw': s.LambertW, 'zeta': s.zeta,
        'psi': s.digamma, 'isprime': None,
    }


def _make_unary(name):
    def f(nargout, *args):
        fn = _unary_table()[name]
        a = args[0]
        if len(args) > 1:
            return _binary_fn(name, args)
        return Sym(_each(lambda e: fn(e), ex(a)))
    return f


def _binary_fn(name, args):
    s = sp()
    table = {'atan2': s.atan2, 'mod': s.Mod, 'rem': lambda a, b: a - b * s.Function('fix')(a / b) if not (a / b).is_number else a - b * (s.sign(a / b) * s.floor(s.Abs(a / b))),
             'nchoosek': s.binomial, 'besselj': s.besselj, 'bessely': s.bessely, 'besseli': s.besseli, 'besselk': s.besselk,
             'nthroot': lambda x, n: s.real_root(x, n) if x.is_number and x.is_real else s.root(x, n),
             'gcd': s.gcd, 'lcm': s.lcm, 'max': s.Max, 'min': s.Min, 'lambertw': lambda k, x: s.LambertW(x, k),
             'zeta': lambda n, x: s.zeta(x) if n == 0 else s.diff(s.zeta(s.Symbol('_z')), s.Symbol('_z'), n).subs(s.Symbol('_z'), x),
             'psi': lambda k, x: s.polygamma(k, x), 'dirac': lambda n, x: s.DiracDelta(x, n), 'log': lambda b, x: s.log(x, b),
             'power': lambda a, b: a ** b, 'kroneckerDelta': s.KroneckerDelta}
    fn = table[name]
    A, B = arr_of(args[0]), arr_of(args[1])
    X, Yb = Y._bcast(A, B, name)
    r = np.empty(X.shape, object)
    for i in np.ndindex(X.shape):
        r[i] = fn(fresh(X[i]), fresh(Yb[i]))
    return Sym(r)


for _n in ('sin cos tan sec csc cot asin acos atan acot asec acsc sinh cosh tanh coth sech csch asinh acosh atanh acoth asech '
           'acsch exp log sqrt abs sign real imag conj angle floor ceil gamma factorial erf erfc erfinv log2 log10 log1p expm1 '
           'round fix').split():
    OVERLOADS[_n] = _make_unary(_n)
for _n in ('atan2', 'mod', 'rem', 'nchoosek', 'besselj', 'bessely', 'besseli', 'besselk', 'nthroot', 'gcd', 'lcm'):
    OVERLOADS[_n] = (lambda nm: lambda nargout, *args: _binary_fn(nm, args))(_n)


@_over('max', 'min')
def maxmin_(nargout, *args):
    raise AssertionError('replaced in install')


def _maxmin(name, nargout, args):
    s = sp()
    if len(args) >= 2 and numel(args[1]) > 0:
        return _binary_fn(name, args)
    A = ex(args[0])
    v = list(A.reshape(-1, order='F')) if 1 in A.shape else None
    fn = s.Max if name == 'max' else s.Min
    if v is not None:
        m = fn(*v)
        if nargout > 1:
            k = next((i for i, e in enumerate(v) if e == m), 0)
            return S(m), float(k + 1)
        return S(m)
    cols = [fn(*A[:, j]) for j in range(A.shape[1])]
    return Y.of_array(cols)


# the special functions numbers lack here, for numbers and symbols alike
def _num_or_sym(name, numeric, lo=1, hi=1):
    def f(nargout, *args):
        if not lo <= len(args) <= hi:
            raise err('MATLAB:minrhs' if len(args) < lo else 'MATLAB:TooManyInputs',
                      'Not enough input arguments.' if len(args) < lo else 'Too many input arguments.', name)
        if any(_is(a) for a in args):
            return _make_unary(name)(nargout, *args) if len(args) == 1 else _binary_fn(name, args)
        return numeric(*args)
    return f


def _heaviside_num(x):
    a = darr(x)
    return out(np.where(a > 0, 1.0, np.where(a < 0, 0.0, np.where(a == 0, 0.5, np.nan))))


def _dirac_num(*args):
    a = darr(args[-1])
    n = darr(args[0]) if len(args) > 1 else None
    return out(np.where(a == 0, np.inf, np.where(np.isnan(a), np.nan, 0.0)) * (1 if n is None else np.where(n == 0, 1.0, np.where(a == 0, np.nan, 1.0))))


def _sinc_num(x):
    a = darr(x)
    with np.errstate(invalid='ignore', divide='ignore'):
        return out(np.where(a == 0, 1.0, np.sin(np.pi * a) / (np.pi * np.where(a == 0, 1.0, a))))


def _lambertw_num(*args):
    from scipy.special import lambertw as lw
    k = int(num(args[0])) if len(args) > 1 else 0
    r = lw(darr(args[-1]), k)
    return out(r.real if np.all(r.imag == 0) else r)


def _zeta_num(*args):
    from scipy.special import zeta as zt
    if len(args) > 1:
        raise err('symbolic:zeta:Derivative', 'zeta(n, x) for numbers is not available here: use sym.', 'zeta')
    return out(zt(darr(args[0])))


def _kron_delta_num(*args):
    a, b = darr(args[0]), darr(args[1]) if len(args) > 1 else np.zeros((1, 1))
    return out((a == b).astype(float))


bi('heaviside', arr=False)(_num_or_sym('heaviside', _heaviside_num))
bi('dirac', arr=False)(_num_or_sym('dirac', _dirac_num, 1, 2))
bi('sinc', arr=False)(_num_or_sym('sinc', _sinc_num))
bi('lambertw', arr=False)(_num_or_sym('lambertw', _lambertw_num, 1, 2))
bi('zeta', arr=False)(_num_or_sym('zeta', _zeta_num, 1, 2))
bi('kroneckerDelta', arr=False)(lambda nargout, *args: _binary_fn('kroneckerDelta', args) if any(_is(a) for a in args) else _kron_delta_num(*args))


# ---- arrays ---------------------------------------------------------------------------------------------------------------------

def _dim(args, A):
    if len(args) > 1 and not is_str(args[1]):
        return int(num(args[1]))
    return 1 if A.shape[0] != 1 else 2


@_over('sum', 'prod', 'cumsum', 'cumprod')
def _reduce(nargout, *args):
    raise AssertionError('replaced in install')


def _reduce_fn(name):
    def f(nargout, *args):
        s = sp()
        A = ex(args[0])
        d = _dim(args, A)
        axis = d - 1
        if name in ('sum', 'prod'):
            fn = (lambda v: s.Add(*v)) if name == 'sum' else (lambda v: s.Mul(*v))
            if axis == 0:
                r = np.array([[fn(A[:, j]) for j in range(A.shape[1])]], object)
            else:
                r = np.array([[fn(A[i, :])] for i in range(A.shape[0])], object)
            return Sym(r)
        r = A.copy()
        if axis == 0:
            for i in range(1, A.shape[0]):
                r[i] = [r[i - 1, j] + A[i, j] if name == 'cumsum' else r[i - 1, j] * A[i, j] for j in range(A.shape[1])]
        else:
            for j in range(1, A.shape[1]):
                for i in range(A.shape[0]):
                    r[i, j] = r[i, j - 1] + A[i, j] if name == 'cumsum' else r[i, j - 1] * A[i, j]
        return Sym(r)
    return f


def _matrix_fn(name):
    def f(nargout, *args):
        s = sp()
        A = ex(args[0])
        M = s.Matrix(A.tolist())
        if name == 'det':
            return S(s.simplify(M.det()) if M.shape[0] <= 4 else M.det())
        if name == 'inv':
            if M.shape[0] != M.shape[1]:
                raise err('MATLAB:square', 'Matrix must be square.', 'inv')
            if M.det() == 0:
                R.write('Warning: The matrix is singular to working precision.\n')
                return Sym(_each(lambda e: s.oo, A))
            return Sym(Y._np(s.simplify(M.inv())))
        if name == 'trace':
            return S(M.trace())
        if name == 'rank':
            return float(M.rank())
        if name == 'null':
            vs = M.nullspace()
            return Sym(Y._np(s.Matrix.hstack(*vs))) if vs else Sym(np.empty((M.shape[1], 0), object))
        if name == 'rref':
            return Sym(Y._np(M.rref()[0]))
        if name == 'expm':
            return Sym(Y._np(s.simplify(M.exp())))
        if name == 'transpose':
            return Sym(A.T.copy())
        if name == 'eig':
            if nargout <= 1:
                vals = []
                for v, m in M.eigenvals().items():
                    vals += [v] * m
                return Y.of_array([[v] for v in vals])
            vecs = M.eigenvects()
            V = [vec for _, m, basis in vecs for vec in basis]
            D = [val for val, m, basis in vecs for _ in basis]
            Vm = s.Matrix.hstack(*V)
            return Sym(Y._np(Vm)), Sym(Y._np(s.diag(*D)))
        raise AssertionError(name)
    return f


for _n in ('det', 'inv', 'trace', 'rank', 'null', 'rref', 'expm', 'eig'):
    OVERLOADS[_n] = _matrix_fn(_n)
for _n in ('sum', 'prod', 'cumsum', 'cumprod'):
    OVERLOADS[_n] = _reduce_fn(_n)


@_over('kron')
def kron_(nargout, *args):
    A, B = ex(args[0]), ex(args[1])
    r = np.empty((A.shape[0] * B.shape[0], A.shape[1] * B.shape[1]), object)
    for i in range(A.shape[0]):
        for j in range(A.shape[1]):
            r[i * B.shape[0]:(i + 1) * B.shape[0], j * B.shape[1]:(j + 1) * B.shape[1]] = _each(lambda e: A[i, j] * e, B)
    return Sym(r)


@_over('dot')
def dot_(nargout, *args):
    s = sp()
    a, b = _flat(args[0]), _flat(args[1])
    if len(a) != len(b):
        raise err('MATLAB:dot:InputSizeMismatch', 'A and B must be the same size.', 'dot')
    return S(s.Add(*[s.conjugate(x) * y for x, y in zip(a, b)]))


@_over('cross')
def cross_(nargout, *args):
    a, b = _flat(args[0]), _flat(args[1])
    if len(a) != 3 or len(b) != 3:
        raise err('MATLAB:cross:InputSizeMismatch', 'A and B must be vectors of 3 elements.', 'cross')
    c = [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
    shape = arr_of(args[0]).shape
    return Sym(np.array(c, object).reshape(shape))


@_over('norm')
def norm_(nargout, *args):
    s = sp()
    A = ex(args[0])
    p = args[1] if len(args) > 1 else 2.0
    if 1 in A.shape:
        v = list(A.reshape(-1))
        if is_str(p) and py_str(p).lower() == 'inf' or (not is_str(p) and num(p) == math.inf):
            return S(s.Max(*[s.Abs(x) for x in v]))
        pp = num(p) if not is_str(p) else 2.0
        if pp == 1:
            return S(s.Add(*[s.Abs(x) for x in v]))
        return S(s.Add(*[s.Abs(x) ** int(pp) if pp == int(pp) else s.Abs(x) ** pp for x in v]) ** (s.Integer(1) / int(pp) if pp == int(pp) else 1 / pp))
    M = s.Matrix(A.tolist())
    if not is_str(p) and num(p) == 2:
        return S(s.sqrt(s.Max(*[ev for ev, m in (M.H * M).eigenvals().items()])))
    return S(M.norm(s.oo if (is_str(p) and py_str(p).lower() == 'inf') else ('fro' if is_str(p) else int(num(p)))))


@_over('reshape')
def reshape_(nargout, *args):
    A = arr_of(args[0])
    dims = [int(num(d)) for d in args[1:]] if len(args) > 2 else [int(x) for x in darr(args[1]).reshape(-1)]
    if len(dims) != 2 or dims[0] * dims[1] != A.size:
        raise err('MATLAB:getReshapeDims:notSameNumel', 'Number of elements must not change.', 'reshape')
    return Sym(A.reshape(-1, order='F').reshape(dims, order='F'))


@_over('repmat')
def repmat_(nargout, *args):
    A = arr_of(args[0])
    reps = [int(num(d)) for d in args[1:]] if len(args) > 2 else [int(x) for x in darr(args[1]).reshape(-1)]
    if len(reps) == 1:
        reps = reps * 2
    return Sym(np.tile(A, reps))


@_over('fliplr')
def fliplr_(nargout, *args):
    return Sym(np.fliplr(arr_of(args[0])).copy())


@_over('flipud')
def flipud_(nargout, *args):
    return Sym(np.flipud(arr_of(args[0])).copy())


@_over('diag')
def diag_(nargout, *args):
    s = sp()
    A = arr_of(args[0])
    k = int(num(args[1])) if len(args) > 1 else 0
    if 1 in A.shape:
        v = A.reshape(-1)
        n = v.size + abs(k)
        r = np.empty((n, n), object)
        r[:] = s.Integer(0)
        for i, e in enumerate(v):
            r[i + max(0, -k), i + max(0, k)] = e
        return Sym(r)
    return Sym(np.diagonal(A, k).reshape(-1, 1).copy())


@_over('triu', 'tril')
def tri_(nargout, *args):
    raise AssertionError('replaced in install')


def _tri(name):
    def f(nargout, *args):
        s = sp()
        A = arr_of(args[0]).copy()
        k = int(num(args[1])) if len(args) > 1 else 0
        for i, j in np.ndindex(A.shape):
            if (name == 'triu' and j - i < k) or (name == 'tril' and j - i > k):
                A[i, j] = s.Integer(0)
        return Sym(A)
    return f


OVERLOADS['triu'] = _tri('triu')
OVERLOADS['tril'] = _tri('tril')


@_over('isreal')
def isreal_(nargout, *args):
    return all(fresh(e).is_real for e in arr_of(args[0]).reshape(-1))


@_over('disp')
def disp_(nargout, *args):
    R.write(Y.disp_text(args[0]))
    return None


@_over('isprime')
def isprime_(nargout, *args):
    s = sp()
    A = ex(args[0])
    r = np.zeros(A.shape, bool)
    for i in np.ndindex(A.shape):
        r[i] = bool(A[i].is_Integer and s.isprime(int(A[i])))
    return bool(r[0, 0]) if r.size == 1 else r


# ---- the dispatchers --------------------------------------------------------------------------------------------------------------

def install():
    """Put a dispatcher in front of each numeric builtin that has a symbolic
    version: a symbolic argument sends the call here."""
    for name, fn in list(OVERLOADS.items()):
        if name.startswith('_'):
            continue
        info = REG.get(name)
        if info is None:
            continue
        orig = info.fn
        if getattr(orig, '_sym', False):
            continue
        if name in ('fplot', 'ezplot', 'fpolarplot'):
            OVERLOADS['_orig_' + name] = orig
        if name in ('fsurf', 'fmesh', 'fcontour'):
            fn = (lambda o: lambda nargout, *args: o(nargout, *_with_fhs('fsurf', 2, args)))(orig)
        if name in ('max', 'min'):
            fn = (lambda nm: lambda nargout, *args: _maxmin(nm, nargout, args))(name)

        def make(orig, fn):
            def d(nargout, *args):
                for a in args:
                    if type(a) is Sym:
                        return fn(nargout, *args)
                return orig(nargout, *args)
            d._sym = True
            d.__name__ = getattr(orig, '__name__', name)
            return d
        info.fn = make(orig, fn)
        info.nout = max(info.nout, 2 if name in ('eig', 'max', 'min') else info.nout)


install()


def _sympy_input_errors():
    """An exception raised inside SymPy is its refusal of an input (a
    logical value, a number where a variable belongs, a matrix where an
    expression does): it reaches the program as the language's error. One
    raised in this module's own code is left as it is, to be fixed here."""
    import traceback

    def convert(e, name, args):
        tb = traceback.extract_tb(e.__traceback__)
        in_sympy = bool(tb) and '/sympy/' in tb[-1].filename.replace('\\', '/')
        no_sympy = isinstance(e, ModuleNotFoundError) and 'sympy' in str(e)
        if not (in_sympy or no_sympy):
            return None
        if not any(isinstance(a, Sym) for a in args):
            # (in the page SymPy is loaded when the first symbolic value is made)
            return err('MATLAB:sym:NotSymbolic', f'{name} works on symbolic values: make one with sym or syms.', name)
        return err('MATLAB:sym:InvalidInput', f'Invalid input: {e}', name)

    def wrap(info):
        fn, name = info.fn, info.name
        if info.aw:
            async def f(*a):
                try:
                    return await fn(*a)
                except MError:
                    raise
                except Exception as e:
                    c = convert(e, name, a)
                    if c is None:
                        raise
                    raise c from None
        else:
            def f(*a):
                try:
                    return fn(*a)
                except MError:
                    raise
                except Exception as e:
                    c = convert(e, name, a)
                    if c is None:
                        raise
                    raise c from None
        f._sym = getattr(fn, '_sym', False)
        return f
    for name, info in list(REG.items()):
        if getattr(info.fn, '__module__', None) == __name__ or getattr(info.fn, '_sym', False):
            info.fn = wrap(info)


_sympy_input_errors()


# plots of symbolic numbers (subs of an expression at a grid): drawn as doubles
_PLOTS = ('plot plot3 line scatter scatter3 stairs stem stem3 bar barh bar3 bar3h area errorbar semilogx semilogy loglog fill fill3 '
          'patch histogram histogram2 quiver quiver3 feather compass surf surfc mesh meshc meshz waterfall contour contourf contour3 '
          'pcolor image imagesc polarplot polarscatter polarhistogram comet comet3 ribbon pie pie3 text xline yline').split()


def wrap_plots(reg):
    """Called once every module is loaded: a plotting function given a symbolic value with no variables
    left draws its numbers."""
    def numbers(args):
        if not any(type(a) is Sym for a in args):
            return args
        return tuple(double_(1, a) if type(a) is Sym and not any(getattr(e, 'free_symbols', None) for e in a.a.flat) else a
                     for a in args)

    for name in _PLOTS:
        info = reg.get(name)
        if info is None:
            continue
        orig, k = info.fn, 2 if info.ws else 1
        if info.aw:
            async def f(*a, orig=orig, k=k):
                return await orig(*a[:k], *numbers(a[k:]))
        else:
            def f(*a, orig=orig, k=k):
                return orig(*a[:k], *numbers(a[k:]))
        f.__name__ = getattr(orig, '__name__', name)
        info.fn = f


# applied to each side of an equation: log(a == b) is log(a) == log(b), diff(a == b, x) is diff(a, x) == diff(b, x)
_SIDEWISE = ('sin cos tan cot sec csc asin acos atan sinh cosh tanh asinh acosh atanh exp log log2 log10 sqrt nthroot '
             'collect combine expand diff int partfrac horner simplifyFraction rewrite laplace ilaplace fourier ifourier ztrans iztrans').split()


def _sidewise(fn):
    def f(nargout, *args):
        a = args[0] if args else None
        if type(a) is Sym and a.a.size:
            s = sp()
            if all(isinstance(e, s.Eq) for e in a.a.flat):
                L = fn(1, Sym(_each(lambda e: e.lhs, a.a), a.fargs), *args[1:])
                Rr = fn(1, Sym(_each(lambda e: e.rhs, a.a), a.fargs), *args[1:])
                la, ra = arr_of(L), arr_of(Rr)
                if la.shape == ra.shape:
                    out_ = np.empty(la.shape, object)
                    for i in np.ndindex(la.shape):
                        out_[i] = s.Eq(la[i], ra[i], evaluate=False)
                    return Sym(out_, L.fargs if _is(L) else a.fargs)
        return fn(nargout, *args)
    f._sym = getattr(fn, '_sym', False)
    f.__name__ = getattr(fn, '__name__', 'f')
    return f


for _n in _SIDEWISE:
    if _n in REG and not REG[_n].aw and not getattr(REG[_n], 'ws', False):
        REG[_n].fn = _sidewise(REG[_n].fn)
