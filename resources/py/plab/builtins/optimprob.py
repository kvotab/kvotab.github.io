"""Problem-based optimization: optimvar, optimexpr, optimconstr, optimineq,
optimeq, optimproblem, eqnproblem, solve, evaluate, infeasibility,
fcn2optimexpr, varindex and show; and paretosearch.

An expression is a tree of array operations on optimization variables
(each node knows its shape and its degree: 0 constant, 1 linear, 2
quadratic, inf otherwise). It is evaluated at many points at once: every
value carries a last dimension for the points, so the coefficients of a
linear expression come from one evaluation at the identity, and those of a
quadratic one from evaluations at pairs of unit vectors. solve looks at
the degrees: linear (with integer variables) goes to intlinprog, linear to
linprog, a quadratic objective with linear constraints to quadprog,
anything else to fminunc or fmincon (ga with integer variables);
equations to a linear solve or fsolve. The variables sit in the solver's
vector in alphabetical order of their names."""
import math

import numpy as np

from . import bi as _register
from . import REG
from ._util import err, nargchk, out, num, opt_str, opt_lower, is_str, darr
from ..values import MError, Char, Cell, Struct, Str, Obj, FH, numel, py_str, text_list, share, EMPTY, F64, shape_of
from .. import runtime as R

INF = float('inf')


def bi(*names, **kw):
    def deco(f):
        if kw.get('aw'):
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                    raise err(f'optim:{names[0]}:InvalidInput', f'{names[0]}: {e}', names[0]) from None
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
                    raise err(f'optim:{names[0]}:InvalidInput', f'{names[0]}: {e}', names[0]) from None
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _outs(nargout, *vals):
    return vals[:max(nargout, 1)] if nargout > 1 else vals[0]


def _shape2(s):
    s = tuple(int(x) for x in s)
    return s if len(s) >= 2 else (s + (1, 1))[:2] if s else (1, 1)


# ---- variables ------------------------------------------------------------------------------------------------------

class VarInfo:
    _n = [0]

    def __init__(self, name, shape, kind, names):
        VarInfo._n[0] += 1
        self.uid = VarInfo._n[0]
        self.name = name
        self.shape = shape
        self.kind = kind
        self.index_names = names            # a list (per dimension) of lists of names, or Nones
        self.lb = np.full(shape, -INF)
        self.ub = np.full(shape, INF)

    @property
    def n(self):
        return int(np.prod(self.shape))


class OVar(Obj):
    """An optimization variable (a handle: its bounds are shared)."""
    cls = 'optim.problemdef.OptimizationVariable'
    is_handle = True

    def __init__(self, info):
        self.info = info

    @property
    def shape(self):
        return self.info.shape

    @property
    def valid(self):
        return True

    def node(self):
        return NVar(self.info)

    def index(self, args):
        return OExpr(_index_node(NVar(self.info), args, self.info))

    def getprop(self, name):
        k = name.lower()
        i = self.info
        if k == 'name':
            return Char.of(i.name)
        if k == 'type':
            return Char.of(i.kind)
        if k == 'indexnames':
            items = [Cell.of_list([Char.of(s) for s in nm], (1, len(nm))) if nm else Cell.empty((0, 0)) for nm in i.index_names]
            return Cell.of_list(items, (1, len(items)))
        if k == 'lowerbound':
            return out(i.lb.copy())
        if k == 'upperbound':
            return out(i.ub.copy())
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'OptimizationVariable'.")

    def setprop(self, name, value):
        k = name.lower()
        i = self.info
        if k in ('lowerbound', 'upperbound'):
            v = np.asarray(darr(value), F64)
            if v.size == 1:
                v = np.full(i.shape, float(v.reshape(-1)[0]))
            elif v.shape != i.shape and v.size == i.n:
                v = v.reshape(i.shape, order='F')
            elif v.shape != i.shape:
                raise err('optim:problemdef:OptimizationVariable:BoundSize', f'The bound is a number or an array the size of {i.name}.', 'optimvar')
            if k == 'lowerbound':
                i.lb = v.copy()
            else:
                i.ub = v.copy()
            return
        if k == 'type':
            t = opt_lower(value)
            if t not in ('continuous', 'integer'):
                raise err('optim:problemdef:OptimizationVariable:Type', "Type is 'continuous' or 'integer'.", 'optimvar')
            i.kind = t
            return
        raise MError('MATLAB:class:SetProhibited', f"You cannot set the property '{name}' of an OptimizationVariable.")

    def propnames(self):
        return ['Name', 'Type', 'IndexNames', 'LowerBound', 'UpperBound']

    def display_lines(self):
        i = self.info
        sz = '×'.join(str(x) for x in i.shape)
        b = lambda a: f'{a.reshape(-1)[0]:g}' if a.size == 1 else f'[{sz} double]'  # noqa: E731
        lines = [f'  {sz} OptimizationVariable array with properties:' if i.n > 1 else '  OptimizationVariable with properties:', '',
                 f"          Name: '{i.name}'", f"          Type: '{i.kind}'",
                 '    IndexNames: {' + '  '.join('{}' if not nm else '{' + '  '.join(f"'{s}'" for s in nm) + '}' for nm in i.index_names) + '}',
                 f'    LowerBound: {b(i.lb)}', f'    UpperBound: {b(i.ub)}', '', '  See variables with show.', '  See bounds with showbounds.']
        return lines


@bi('optimvar', arr=False)
def optimvar(nargout, *args):
    """x = optimvar(name, n, m, ..., 'Type', type, 'LowerBound', lb, 'UpperBound', ub):
    an optimization variable (an array n-by-m-by-..., a scalar by
    default); a dimension may be given by names (a cell array of text),
    which then index it. Type 'continuous' or 'integer'."""
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'optimvar')
    name = opt_str(args[0])
    if name is None or not name.isidentifier():
        raise err('optim:problemdef:OptimizationVariable:InvalidName', 'The name is a valid variable name, as text.', 'optimvar')
    rest = list(args[1:])
    dims, names = [], []
    while rest and not (is_str(rest[0]) and opt_lower(rest[0]) in ('type', 'lowerbound', 'upperbound')):
        v = rest.pop(0)
        if isinstance(v, (Cell, Str)):
            nm = [str(x) for x in text_list(v)]
            dims.append(len(nm))
            names.append(nm)
        else:
            a = np.asarray(darr(v), F64).reshape(-1)
            for x in a:
                if x < 0 or x != int(x):
                    raise err('optim:problemdef:OptimizationVariable:InvalidSize', 'The sizes are whole numbers from 0.', 'optimvar')
                dims.append(int(x))
                names.append(None)
    if len(dims) == 1:
        dims.append(1)
        names.append(None)
    if not dims:
        dims, names = [1, 1], [None, None]
    kind, lb, ub = 'continuous', None, None
    if len(rest) % 2:
        raise err('optim:problemdef:OptimizationVariable:nargin', 'The options come as names and values.', 'optimvar')
    for i in range(0, len(rest), 2):
        k = opt_lower(rest[i])
        if k == 'type':
            kind = opt_lower(rest[i + 1])
            if kind not in ('continuous', 'integer'):
                raise err('optim:problemdef:OptimizationVariable:Type', "Type is 'continuous' or 'integer'.", 'optimvar')
        elif k == 'lowerbound':
            lb = rest[i + 1]
        elif k == 'upperbound':
            ub = rest[i + 1]
        else:
            raise err('optim:problemdef:OptimizationVariable:Option', f"'{py_str(rest[i])}' is not an option of optimvar.", 'optimvar')
    v = OVar(VarInfo(name, tuple(dims), kind, names))
    if lb is not None:
        v.setprop('LowerBound', lb)
    if ub is not None:
        v.setprop('UpperBound', ub)
    return v


# ---- expression nodes -----------------------------------------------------------------------------------------------

class Node:
    deg = 0
    shape = (1, 1)

    def vars(self, acc):
        for c in self.children():
            c.vars(acc)
        return acc

    def children(self):
        return ()


class NVar(Node):
    def __init__(self, info):
        self.info = info
        self.shape = info.shape
        self.deg = 1

    def vars(self, acc):
        acc[self.info.uid] = self.info
        return acc

    def ev(self, V, memo):
        return V[self.info.uid]

    def text(self):
        return self.info.name


class NConst(Node):
    def __init__(self, a):
        a = np.asarray(a, F64)
        self.a = a.reshape(1, 1) if a.ndim == 0 else a.reshape(1, -1) if a.ndim == 1 else a
        self.shape = self.a.shape
        self.deg = 0

    def ev(self, V, memo):
        return self.a[..., None]

    def text(self):
        return _num_text(self.a)


def _num_text(a):
    if a.size == 1:
        return f'{float(a.reshape(-1)[0]):g}'
    return f'[{"×".join(str(s) for s in a.shape)} double]'


class NIndex(Node):
    def __init__(self, child, flat, shape, label):
        self.child = child
        self.flat = np.asarray(flat, int)
        self.shape = _shape2(shape)
        self.deg = child.deg
        self.label = label

    def children(self):
        return (self.child,)

    def ev(self, V, memo):
        c = _ev(self.child, V, memo)
        K = c.shape[-1]
        flat = c.reshape((-1, K), order='F')
        return flat[self.flat].reshape(self.shape + (K,), order='F')

    def text(self):
        return f'{_wrap(self.child)}({self.label})'


class NUn(Node):
    def __init__(self, op, child):
        self.op, self.child = op, child
        self.deg = child.deg
        self.shape = child.shape if op == '-' else (child.shape[1], child.shape[0]) + tuple(child.shape[2:])

    def children(self):
        return (self.child,)

    def ev(self, V, memo):
        c = _ev(self.child, V, memo)
        if self.op == '-':
            return -c
        axes = (1, 0) + tuple(range(2, c.ndim))
        return np.transpose(c, axes)

    def text(self):
        return f'-{_wrap(self.child)}' if self.op == '-' else f"{_wrap(self.child)}'"


def _bshape(a, b, op):
    sa, sb = a.shape, b.shape
    n = max(len(sa), len(sb))
    sa, sb = sa + (1,) * (n - len(sa)), sb + (1,) * (n - len(sb))
    res = []
    for x, y in zip(sa, sb):
        if x == y or y == 1:
            res.append(x)
        elif x == 1:
            res.append(y)
        else:
            raise err('MATLAB:sizeDimensionsMustMatch', f'Arrays have incompatible sizes for this operation ({op}).', op)
    return tuple(res)


def _align(v, nd):
    """A value (shape + points) with its array dimensions padded to nd."""
    if v.ndim - 1 < nd:
        v = v.reshape(v.shape[:-1] + (1,) * (nd - (v.ndim - 1)) + (v.shape[-1],))
    return v


class NBin(Node):
    def __init__(self, op, a, b):
        self.op, self.a, self.b = op, a, b
        self.shape = _bshape(a, b, op)
        da, db = a.deg, b.deg
        if op in ('+', '-'):
            self.deg = max(da, db)
        elif op == '.*':
            self.deg = da + db
        elif op == './':
            self.deg = da if db == 0 else INF
        elif op == '.^':
            if db == 0 and isinstance(b, NConst) and b.a.size == 1:
                p = float(b.a.reshape(-1)[0])
                self.deg = 0 if da == 0 else (int(da * p) if p == int(p) and p >= 0 and da < INF else INF)
            else:
                self.deg = 0 if (da == 0 and db == 0) else INF
        else:
            self.deg = INF

    def children(self):
        return (self.a, self.b)

    def ev(self, V, memo):
        nd = len(self.shape)
        x, y = _align(_ev(self.a, V, memo), nd), _align(_ev(self.b, V, memo), nd)
        with np.errstate(all='ignore'):
            if self.op == '+':
                return x + y
            if self.op == '-':
                return x - y
            if self.op == '.*':
                return x * y
            if self.op == './':
                return x / y
            return np.power(x, y)

    def text(self):
        sym = {'+': ' + ', '-': ' - ', '.*': '.*', './': './', '.^': '.^'}[self.op]
        return f'{_wrap(self.a, self.op)}{sym}{_wrap(self.b, self.op, right=True)}'


class NMtimes(Node):
    def __init__(self, a, b):
        if a.shape[1] != b.shape[0]:
            raise err('MATLAB:innerdim', 'Incorrect dimensions for matrix multiplication.', 'mtimes')
        self.a, self.b = a, b
        self.shape = (a.shape[0], b.shape[1])
        self.deg = a.deg + b.deg

    def children(self):
        return (self.a, self.b)

    def ev(self, V, memo):
        x, y = _ev(self.a, V, memo), _ev(self.b, V, memo)
        if x.shape[-1] == 1 and y.shape[-1] != 1:
            return np.einsum('ip,pjk->ijk', x[..., 0], y)
        if y.shape[-1] == 1 and x.shape[-1] != 1:
            return np.einsum('ipk,pj->ijk', x, y[..., 0])
        return np.einsum('ipk,pjk->ijk', x, y)

    def text(self):
        return f'{_wrap(self.a, "*")}*{_wrap(self.b, "*", right=True)}'


_ELEMENTWISE = {'exp': np.exp, 'log': np.log, 'sqrt': np.sqrt, 'sin': np.sin, 'cos': np.cos, 'tan': np.tan,
                'sinh': np.sinh, 'cosh': np.cosh, 'tanh': np.tanh, 'asin': np.arcsin, 'acos': np.arccos, 'atan': np.arctan,
                'abs': np.abs, 'log1p': np.log1p, 'expm1': np.expm1, 'log10': np.log10, 'log2': np.log2,
                'asinh': np.arcsinh, 'acosh': np.arccosh, 'atanh': np.arctanh, 'sec': lambda x: 1 / np.cos(x),
                'csc': lambda x: 1 / np.sin(x), 'cot': lambda x: 1 / np.tan(x)}


class NFunc(Node):
    def __init__(self, name, child):
        self.name, self.child = name, child
        self.shape = child.shape
        self.deg = 0 if child.deg == 0 else INF

    def children(self):
        return (self.child,)

    def ev(self, V, memo):
        with np.errstate(all='ignore'):
            return _ELEMENTWISE[self.name](_ev(self.child, V, memo))

    def text(self):
        return f'{self.name}({self.child.text()})'


class NReduce(Node):
    """sum, prod, cumsum along a dimension (0-based)."""

    def __init__(self, name, child, dim):
        self.name, self.child, self.dim = name, child, dim
        sh = list(child.shape) + [1] * max(0, dim + 1 - len(child.shape))
        if name in ('sum', 'prod'):
            sh[dim] = 1
        self.shape = _shape2(sh)
        self.deg = child.deg if name in ('sum', 'cumsum') else (0 if child.deg == 0 else (child.deg * child.shape[dim] if child.deg < INF else INF))

    def children(self):
        return (self.child,)

    def ev(self, V, memo):
        c = _align(_ev(self.child, V, memo), self.dim + 1)
        if self.name == 'sum':
            r = c.sum(axis=self.dim, keepdims=True)
        elif self.name == 'prod':
            r = c.prod(axis=self.dim, keepdims=True)
        else:
            r = np.cumsum(c, axis=self.dim)
        return r.reshape(self.shape + (r.shape[-1],))

    def text(self):
        return f'{self.name}({self.child.text()})'


class NCat(Node):
    def __init__(self, axis, parts):
        self.axis, self.parts = axis, parts
        sh = list(parts[0].shape)
        for p in parts[1:]:
            for d in range(2):
                if d != axis and p.shape[d] != sh[d]:
                    raise err('MATLAB:catenate:dimensionMismatch', 'Dimensions of arrays being concatenated are not consistent.', 'cat')
            sh[axis] += p.shape[axis]
        self.shape = tuple(sh)
        self.deg = max(p.deg for p in parts)

    def children(self):
        return tuple(self.parts)

    def ev(self, V, memo):
        vals = [_ev(p, V, memo) for p in self.parts]
        K = max(v.shape[-1] for v in vals)
        vals = [np.broadcast_to(v, v.shape[:-1] + (K,)) for v in vals]
        return np.concatenate(vals, axis=self.axis)

    def text(self):
        sep = ', ' if self.axis == 1 else '; '
        return '[' + sep.join(p.text() for p in self.parts) + ']'


class NReshape(Node):
    def __init__(self, child, shape):
        self.child = child
        self.shape = _shape2(shape)
        self.deg = child.deg

    def children(self):
        return (self.child,)

    def ev(self, V, memo):
        c = _ev(self.child, V, memo)
        K = c.shape[-1]
        return c.reshape((-1, K), order='F').reshape(self.shape + (K,), order='F')

    def text(self):
        return f'reshape({self.child.text()})'


class NAssign(Node):
    """An expression array filled element by element (optimexpr, then e(i) = ...)."""

    def __init__(self, base, pieces):
        self.base, self.pieces = base, pieces
        self.shape = base.shape
        self.deg = max([base.deg] + [p.deg for _, p in pieces])

    def children(self):
        return (self.base,) + tuple(p for _, p in self.pieces)

    def ev(self, V, memo):
        b = _ev(self.base, V, memo)
        vals = [(f, _ev(p, V, memo)) for f, p in self.pieces]
        K = max([b.shape[-1]] + [v.shape[-1] for _, v in vals])
        res = np.array(np.broadcast_to(b, b.shape[:-1] + (K,))).reshape((-1, K), order='F').copy()
        for f, v in vals:
            res[f] = np.broadcast_to(v.reshape((-1, v.shape[-1]), order='F'), (len(f), K)) if v.size else 0
        return res.reshape(self.shape + (K,), order='F')

    def text(self):
        return 'expression'


class NCall(Node):
    """fcn2optimexpr: a function of the language evaluated at each point."""

    def __init__(self, fh, inputs, shape, which, nout, label):
        self.fh, self.inputs, self.shape, self.which, self.nout, self.label = fh, inputs, _shape2(shape), which, nout, label
        self.deg = INF

    def children(self):
        return tuple(self.inputs)

    def ev(self, V, memo):
        vals = [_ev(p, V, memo) for p in self.inputs]
        K = max(v.shape[-1] for v in vals) if vals else 1
        res = np.zeros(self.shape + (K,))
        for k in range(K):
            xs = [out(np.ascontiguousarray(v[..., min(k, v.shape[-1] - 1)])) for v in vals]
            r = self.fh.scall(self.nout, *xs)
            r = r[self.which] if self.nout > 1 else r
            a = np.asarray(darr(r), F64)
            res[..., k] = a.reshape(self.shape, order='F') if a.size == int(np.prod(self.shape)) else np.broadcast_to(a, self.shape)
        return res

    def text(self):
        nm = _CALLNAMES.get(id(self.fh))
        if nm is None:
            nm = self.fh.text()[1:] if self.fh.text().startswith('@') and not self.fh.text().startswith('@(') else 'anonymousFunction'
        return f'{nm}({", ".join(p.text() for p in self.inputs)})' + (f'[{self.which + 1}]' if self.nout > 1 else '')


_CALLNAMES = {}             # id of an anonymous function -> its name in the text being written


def _named_calls(nodes):
    """Name the anonymous functions under the nodes anonymousFunction1, 2, ...; the 'where:' lines that say what they are."""
    _CALLNAMES.clear()
    seen, lines = [], []

    def walk(n):
        if isinstance(n, NCall) and n.fh.text().startswith('@(') and id(n.fh) not in _CALLNAMES:
            _CALLNAMES[id(n.fh)] = f'anonymousFunction{len(seen) + 1}'
            seen.append(n.fh)
        for c in n.children():
            walk(c)
    for n in nodes:
        walk(n)
    for k, fh in enumerate(seen):
        lines.append(f'      anonymousFunction{k + 1} = {fh.text()}')
    return ['', '  where:', ''] + lines if lines else []


def _ev(node, V, memo):
    key = id(node)
    hit = memo.get(key)
    if hit is None:
        hit = node.ev(V, memo)
        memo[key] = hit
    return hit


_PREC = {'+': 1, '-': 1, '*': 2, '.*': 2, './': 2, '.^': 3}


def _wrap(node, op=None, right=False):
    t = node.text()
    if isinstance(node, NBin) and op is not None and (_PREC[node.op] < _PREC.get(op, 0) or (right and _PREC[node.op] == _PREC.get(op, 0) and op in ('-', './'))):
        return f'({t})'
    if isinstance(node, NUn) and node.op == '-' and op is not None:
        return f'({t})'
    return t


# ---- expression objects ------------------------------------------------------------------------------------------------

class OExpr(Obj):
    """An optimization expression (a value)."""
    cls = 'optim.problemdef.OptimizationExpression'
    is_handle = False

    def __init__(self, node):
        self.node = node

    @property
    def shape(self):
        return self.node.shape

    def value_copy(self):
        return self

    def index(self, args):
        return OExpr(_index_node(self.node, args, None))

    def index_assign(self, args, V):
        n = int(np.prod(self.shape))
        flat, shape = _flat_index(self.shape, args, None)
        pv = _as_node(V)
        if int(np.prod(pv.shape)) not in (1, flat.size):
            raise err('MATLAB:subsassignnumelmismatch', 'Unable to perform assignment because the left and right sides have different numbers of elements.', 'optimexpr')
        if np.any(flat >= n):
            raise err('optim:problemdef:OptimizationExpression:Grow', 'An optimization expression does not grow by assignment; make it the size it needs (optimexpr).', 'optimexpr')
        base = self.node
        pieces = []
        if isinstance(base, NAssign):
            pieces = list(base.pieces)
            base = base.base
        pieces.append((flat, pv))
        return OExpr(NAssign(base, pieces))

    def getprop(self, name):
        k = name.lower()
        if k == 'indexnames':
            return Cell.of_list([Cell.empty((0, 0)), Cell.empty((0, 0))], (1, 2))
        if k == 'variables':
            return _vars_struct(self.node.vars({}))
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class 'OptimizationExpression'.")

    def propnames(self):
        return ['IndexNames', 'Variables']

    def display_lines(self):
        return _expr_lines(self.node, '  ')


class OConstr(Obj):
    """Constraints: pieces of (flat indices, lhs - rhs node, relation), filling an array."""
    is_handle = False

    def __init__(self, shape, pieces, kind=None):
        self._shape = _shape2(shape)
        self.pieces = pieces              # [(flat, node, rel)] with rel '<=', '>=' or '=='
        self.kind = kind                  # 'ineq', 'eq' or None (either)

    @property
    def cls(self):
        if self.kind == 'eq' or (self.pieces and all(r == '==' for _, _, r in self.pieces)):
            return 'optim.problemdef.OptimizationEquality'
        if self.kind == 'ineq' or (self.pieces and all(r != '==' for _, _, r in self.pieces)):
            return 'optim.problemdef.OptimizationInequality'
        return 'optim.problemdef.OptimizationConstraint'

    @property
    def shape(self):
        return self._shape

    def value_copy(self):
        return self

    def deg(self):
        return max([p.deg for _, p, _ in self.pieces], default=0)

    def index(self, args):
        flat, shape = _flat_index(self._shape, args, None)
        pieces = []
        pos = {int(f): k for k, f in enumerate(flat)}
        for f, node, rel in self.pieces:
            hit = [(pos[int(x)], j) for j, x in enumerate(f) if int(x) in pos]
            if hit:
                dst = np.array([h[0] for h in hit])
                src = np.array([h[1] for h in hit])
                pieces.append((dst, _take(node, src), rel))
        return OConstr(shape, pieces, self.kind)

    def index_assign(self, args, V):
        if not isinstance(V, OConstr):
            if isinstance(V, np.ndarray) and V.size == 0:
                raise err('optim:problemdef:OptimizationConstraint:Delete', 'Constraints are not deleted by assignment here.', 'optimconstr')
            raise err('optim:problemdef:OptimizationConstraint:Assign', 'Only constraints are assigned into a constraint array.', 'optimconstr')
        flat, _ = _flat_index(self._shape, args, None)
        n = int(np.prod(self._shape))
        if np.any(flat >= n):
            raise err('optim:problemdef:OptimizationConstraint:Grow', 'A constraint array does not grow by assignment; make it the size it needs.', 'optimconstr')
        vn = int(np.prod(V.shape))
        if vn != flat.size and vn != 1:
            raise err('MATLAB:subsassignnumelmismatch', 'Unable to perform assignment because the left and right sides have different numbers of elements.', 'optimconstr')
        if self.kind == 'eq' and any(r != '==' for _, _, r in V.pieces):
            raise err('optim:problemdef:OptimizationEquality:Assign', 'An equality array holds equalities only.', 'optimeq')
        if self.kind == 'ineq' and any(r == '==' for _, _, r in V.pieces):
            raise err('optim:problemdef:OptimizationInequality:Assign', 'An inequality array holds inequalities only.', 'optimineq')
        keep = []
        drop = set(int(x) for x in flat)
        for f, node, rel in self.pieces:
            mask = np.array([int(x) not in drop for x in f], bool)
            if mask.any():
                keep.append((f[mask], _take(node, np.flatnonzero(mask)) if not mask.all() else node, rel))
        for f, node, rel in V.pieces:
            dst = flat[f] if vn == flat.size else flat
            keep.append((dst, node if vn == flat.size else _take(node, np.zeros(flat.size, int)), rel))
        return OConstr(self._shape, keep, self.kind)

    def getprop(self, name):
        k = name.lower()
        if k == 'indexnames':
            return Cell.of_list([Cell.empty((0, 0)), Cell.empty((0, 0))], (1, 2))
        if k == 'variables':
            acc = {}
            for _, node, _ in self.pieces:
                node.vars(acc)
            return _vars_struct(acc)
        if k == 'relation' and self.pieces:
            return Char.of(self.pieces[0][2])
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls.split('.')[-1]}'.")

    def propnames(self):
        return ['IndexNames', 'Variables']

    def display_lines(self):
        return _constr_lines(self, '  ')

    def residual(self, V):
        """(values of lhs - rhs as a flat array (n, K), relation codes per element)."""
        n = int(np.prod(self._shape))
        K = next(iter(V.values())).shape[-1] if V else 1
        vals = np.zeros((n, K))
        rels = np.array([''] * n, object)
        memo = {}
        for f, node, rel in self.pieces:
            v = _ev(node, V, memo)
            vals[f] = np.broadcast_to(v.reshape((-1, v.shape[-1]), order='F'), (len(f), K))
            rels[f] = rel
        return vals, rels


def _take(node, src):
    """The elements src (flat, 0-based) of a node, as a column."""
    return NIndex(node, np.asarray(src, int), (len(src), 1), '...')


def _vars_struct(acc):
    s = Struct.scalar({})
    for info in sorted(acc.values(), key=lambda i: i.name):
        a = np.empty((1, 1), object)
        a[0, 0] = OVar(info)
        s.f[info.name] = a
    return s


def _as_node(v):
    if isinstance(v, OExpr):
        return v.node
    if isinstance(v, OVar):
        return v.node()
    if isinstance(v, (Char, Str, Cell, Struct)) or isinstance(v, Obj):
        raise err('optim:problemdef:OptimizationExpression:Operand', 'Optimization expressions combine with numbers and other expressions.', 'optimexpr')
    a = np.asarray(darr(v), F64)
    return NConst(a)


def _flat_index(shape, args, info):
    """(flat 0-based indices, result shape) of an index on an array of that shape."""
    from .. import index as I
    n = int(np.prod(shape))
    conv = []
    for d, a in enumerate(args):
        if isinstance(a, (Char, Str, Cell)) and not (isinstance(a, Char) and py_str(a) == ':'):
            names = [str(x) for x in text_list(a)]
            if info is None:
                raise err('optim:problemdef:IndexNames', 'Index names need a variable with names along that dimension.', 'optimvar')
            nd = d if len(args) > 1 else next((k for k, s in enumerate(shape) if s > 1), 0)
            table = info.index_names[nd] if nd < len(info.index_names) else None
            if not table:
                raise err('optim:problemdef:IndexNames', 'That dimension has no index names.', 'optimvar')
            try:
                pos = [table.index(s) + 1.0 for s in names]
            except ValueError:
                raise err('optim:problemdef:IndexNames', f"'{next(s for s in names if s not in table)}' is not an index name of {info.name}.", 'optimvar') from None
            conv.append(np.array(pos).reshape(1, -1) if len(pos) > 1 else pos[0])
        else:
            conv.append(a)
    ids = np.arange(n, dtype=F64).reshape(shape, order='F') + 1
    r = I.idx(ids, tuple(conv))
    r = np.asarray(r, F64)
    shp = r.shape if r.ndim >= 2 else (1, 1) if r.ndim == 0 else (1, r.size)
    return (r.reshape(-1, order='F').astype(int) - 1), shp


def _index_label(flat, shape, info):
    if flat.size != 1:
        return '...'
    k = int(flat[0])
    if info is not None and int(np.prod(info.shape)) > 1:
        return _elem_label(info, k).split('(', 1)[1][:-1]
    return str(k + 1)


def _index_node(node, args, info):
    flat, shp = _flat_index(node.shape, args, info)
    return NIndex(node, flat, shp, _index_label(flat, node.shape, info))


def _elem_label(info, k):
    """The text of element k (flat, 0-based) of a variable: x, x(3), x(2,1) or x('a')."""
    if info.n == 1:
        return info.name
    sub = np.unravel_index(k, info.shape, order='F')
    parts = []
    vec = sum(1 for s in info.shape if s > 1) == 1
    for d, s in enumerate(sub):
        nm = info.index_names[d] if d < len(info.index_names) else None
        if vec and info.shape[d] == 1:
            continue
        parts.append(f"'{nm[s]}'" if nm else str(s + 1))
    return f"{info.name}({', '.join(parts)})"


# ---- operators -----------------------------------------------------------------------------------------------------------

def _rel(op, a, b):
    na, nb = _as_node(a), _as_node(b)
    d = NBin('-', na, nb)
    d.sides = (na, nb)
    rel = {'le': '<=', 'lt': '<=', 'ge': '>=', 'gt': '>=', 'eq': '=='}[op]
    n = int(np.prod(d.shape))
    return OConstr(d.shape, [(np.arange(n), d, rel)])


def _ops(op, *xs):
    if op in ('le', 'lt', 'ge', 'gt', 'eq'):
        return _rel(op, *xs)
    if op == 'ne':
        raise err('optim:problemdef:NotEqual', '~= is not a constraint: use ==, <= or >=.', 'optimexpr')
    if op in ('uminus',):
        return OExpr(NUn('-', _as_node(xs[0])))
    if op == 'uplus':
        return OExpr(_as_node(xs[0]))
    if op in ('transpose', 'ctranspose'):
        return OExpr(NUn("'", _as_node(xs[0])))
    if op in ('hcat', 'vcat'):
        parts = [_as_node(x) for x in xs if not (isinstance(x, np.ndarray) and x.size == 0)]
        return OExpr(NCat(1 if op == 'hcat' else 0, parts))
    a, b = _as_node(xs[0]), _as_node(xs[1])
    if op == 'plus':
        return OExpr(NBin('+', a, b))
    if op == 'minus':
        return OExpr(NBin('-', a, b))
    if op == 'times':
        return OExpr(NBin('.*', a, b))
    if op == 'rdivide':
        return OExpr(NBin('./', a, b))
    if op == 'ldivide':
        return OExpr(NBin('./', b, a))
    if op == 'power':
        return OExpr(NBin('.^', a, b))
    if op == 'mtimes':
        if a.shape == (1, 1) or b.shape == (1, 1):
            return OExpr(NBin('.*', a, b))
        return OExpr(NMtimes(a, b))
    if op == 'mrdivide':
        if b.shape == (1, 1):
            return OExpr(NBin('./', a, b))
        raise err('optim:problemdef:Divide', 'An expression is divided by a scalar here.', 'mrdivide')
    if op == 'mldivide':
        if a.shape == (1, 1):
            return OExpr(NBin('./', b, a))
        raise err('optim:problemdef:Divide', 'An expression is divided by a scalar here.', 'mldivide')
    if op == 'mpower':
        if a.shape == (1, 1) and b.shape == (1, 1):
            return OExpr(NBin('.^', a, b))
        if isinstance(b, NConst) and b.a.size == 1 and float(b.a.reshape(-1)[0]) == 2 and a.shape[0] == a.shape[1]:
            return OExpr(NMtimes(a, a))
        raise err('optim:problemdef:Power', 'A matrix power of an expression is a square matrix squared here.', 'mpower')
    raise err('optim:problemdef:Operator', f"The operator '{op}' is not defined for optimization expressions.", 'optimexpr')


def _install_ops():
    from .. import ops
    for cls in (OVar, OExpr):
        ops.OBJ_OPS[cls] = _ops

    def cops(op, *xs):
        if op in ('hcat', 'vcat'):
            cs = [x for x in xs if not (isinstance(x, np.ndarray) and x.size == 0)]
            if all(isinstance(c, OConstr) for c in cs):
                axis = 1 if op == 'hcat' else 0
                shapes = [c.shape for c in cs]
                total = list(shapes[0])
                total[axis] = sum(s[axis] for s in shapes)
                ids = np.arange(int(np.prod(total))).reshape(total, order='F')
                pieces, off = [], 0
                for c in cs:
                    sl = [slice(None), slice(None)]
                    sl[axis] = slice(off, off + c.shape[axis])
                    block = ids[tuple(sl)].reshape(-1, order='F')
                    for f, node, rel in c.pieces:
                        pieces.append((block[f], node, rel))
                    off += c.shape[axis]
                return OConstr(tuple(total), pieces)
        raise err('optim:problemdef:Operator', f"The operator '{op}' is not defined for constraints.", 'optimconstr')
    ops.OBJ_OPS[OConstr] = cops


_install_ops()


# ---- making arrays ---------------------------------------------------------------------------------------------------------

def _size_args(args, fn):
    dims = []
    for v in args:
        if isinstance(v, (Cell, Str)):
            dims.append(len(text_list(v)))
        else:
            dims += [int(x) for x in np.asarray(darr(v), F64).reshape(-1)]
    if len(dims) == 1:
        dims.append(1)
    return tuple(dims) if dims else (1, 1)


@bi('optimexpr', arr=False)
def optimexpr(nargout, *args):
    """expr = optimexpr(n, m, ...): an optimization expression array of zeros, to fill element by element (expr(i) = ...)."""
    return OExpr(NConst(np.zeros(_size_args(args, 'optimexpr'))))


def _empty_constr(args, kind, fn):
    return OConstr(_size_args(args, fn), [], kind)


@bi('optimconstr', arr=False)
def optimconstr(nargout, *args):
    """constr = optimconstr(n, m, ...): an empty array of constraints, to fill element by element (constr(i) = x(i) <= i)."""
    return _empty_constr(args, None, 'optimconstr')


@bi('optimineq', arr=False)
def optimineq(nargout, *args):
    """constr = optimineq(n, m, ...): an empty array of inequalities, to fill element by element."""
    return _empty_constr(args, 'ineq', 'optimineq')


@bi('optimeq', arr=False)
def optimeq(nargout, *args):
    """constr = optimeq(n, m, ...): an empty array of equalities, to fill element by element."""
    return _empty_constr(args, 'eq', 'optimeq')


# ---- functions of expressions -------------------------------------------------------------------------------------------

def _is_opt(v):
    return isinstance(v, (OVar, OExpr))


def _wrap_fn(name, fn):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn

    def f(*a):
        args = a[2:] if info.ws else a[1:]
        if any(_is_opt(x) for x in args[:2]):
            return fn(a[1] if info.ws else a[0], *args)
        return orig(*a)
    if info.aw:
        async def g(*a):
            args = a[2:] if info.ws else a[1:]
            if any(_is_opt(x) for x in args[:2]):
                return fn(a[1] if info.ws else a[0], *args)
            return await orig(*a)
        info.fn = g
    else:
        info.fn = f


def _elementwise(name):
    def f(nargout, *args):
        return OExpr(NFunc(name, _as_node(args[0])))
    return f


def _reduce(name):
    def f(nargout, *args):
        node = _as_node(args[0])
        if len(args) > 1:
            d = args[1]
            if is_str(d) and opt_lower(d) == 'all':
                node = NReshape(node, (int(np.prod(node.shape)), 1))
                dim = 0
            else:
                dim = int(num(d)) - 1
        else:
            dim = next((k for k, s in enumerate(node.shape) if s != 1), 0)
        return OExpr(NReduce(name, node, dim))
    return f


def _dot(nargout, *args):
    a, b = _as_node(args[0]), _as_node(args[1])
    if int(np.prod(a.shape)) != int(np.prod(b.shape)):
        raise err('MATLAB:dot:InputSizeMismatch', 'A and B must be the same size.', 'dot')
    if a.shape != b.shape:
        b = NReshape(b, a.shape)
    p = NBin('.*', a, b)
    dim = next((k for k, s in enumerate(p.shape) if s != 1), 0)
    return OExpr(NReduce('sum', p, dim))


def _norm(nargout, *args):
    a = _as_node(args[0])
    p = 2.0 if len(args) < 2 else float(num(args[1]))
    if p != 2 or min(a.shape) != 1:
        raise err('optim:problemdef:norm', 'norm of an optimization expression is the 2-norm of a vector here.', 'norm')
    sq = NReduce('sum', NReshape(NBin('.^', a, NConst(2.0)), (int(np.prod(a.shape)), 1)), 0)
    return OExpr(NFunc('sqrt', sq))


def _reshape(nargout, *args):
    a = _as_node(args[0])
    dims = []
    for v in args[1:]:
        arr_ = np.asarray(darr(v), F64).reshape(-1)
        dims += [int(x) if x == x else -1 for x in arr_] if arr_.size else [-1]
    n = int(np.prod(a.shape))
    if -1 in dims:
        k = dims.index(-1)
        rest = int(np.prod([d for d in dims if d != -1]))
        dims[k] = n // rest
    if int(np.prod(dims)) != n:
        raise err('MATLAB:getReshapeDims:notSameNumel', 'Number of elements must not change.', 'reshape')
    return OExpr(NReshape(a, dims))


def _size(nargout, *args):
    s = args[0].shape
    if len(args) > 1:
        d = int(num(args[1]))
        return float(s[d - 1]) if d <= len(s) else 1.0
    if nargout > 1:
        vals = [float(x) for x in s] + [1.0] * max(0, nargout - len(s))
        return tuple(vals[:nargout - 1] + [float(np.prod(s[nargout - 1:]))])
    return np.array([[float(x) for x in s]])


def _numel(nargout, *args):
    return float(np.prod(args[0].shape))


def _length(nargout, *args):
    s = args[0].shape
    return float(max(s)) if min(s) > 0 else 0.0


def _isempty(nargout, *args):
    return int(np.prod(args[0].shape)) == 0


for _n in _ELEMENTWISE:
    _wrap_fn(_n, _elementwise(_n))
for _n in ('sum', 'prod', 'cumsum'):
    _wrap_fn(_n, _reduce(_n))
for _n, _f in (('dot', _dot), ('norm', _norm), ('reshape', _reshape)):
    _wrap_fn(_n, _f)


def _shape_wrap(name, fn):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn

    def f(*a):
        args = a[2:] if info.ws else a[1:]
        if args and isinstance(args[0], (OVar, OExpr, OConstr)):
            return fn(a[1] if info.ws else a[0], *args)
        return orig(*a)
    info.fn = f


for _n, _f in (('size', _size), ('numel', _numel), ('length', _length), ('isempty', _isempty)):
    _shape_wrap(_n, _f)


# ---- coefficients ------------------------------------------------------------------------------------------------------

class Layout:
    """The solver's vector: the variables in alphabetical order of their names, each flattened by columns."""

    def __init__(self, infos):
        names = {}
        for i in infos:
            if i.name in names and names[i.name] is not i:
                raise err('optim:problemdef:SameName', f"Two different variables are named '{i.name}'.", 'solve')
            names[i.name] = i
        self.infos = [names[k] for k in sorted(names)]
        self.off = {}
        o = 0
        for i in self.infos:
            self.off[i.uid] = o
            o += i.n
        self.n = o

    def V(self, X):
        """Variable values from points X (n-by-K)."""
        res = {}
        for i in self.infos:
            o = self.off[i.uid]
            res[i.uid] = X[o:o + i.n].reshape(i.shape + (X.shape[1],), order='F')
        return res

    def lb(self):
        return np.concatenate([i.lb.reshape(-1, order='F') for i in self.infos]) if self.infos else np.zeros(0)

    def ub(self):
        return np.concatenate([i.ub.reshape(-1, order='F') for i in self.infos]) if self.infos else np.zeros(0)

    def intcon(self):
        idx = []
        for i in self.infos:
            if i.kind == 'integer':
                idx += list(range(self.off[i.uid], self.off[i.uid] + i.n))
        return np.array(idx, int)

    def labels(self):
        return [_elem_label(i, k) for i in self.infos for k in range(i.n)]


def _eval_flat(node, L, X):
    """A node's values (flattened, rows) at points X (columns)."""
    v = _ev(node, L.V(X), {})
    v = np.broadcast_to(v, v.shape[:-1] + (X.shape[1],))
    return v.reshape((-1, X.shape[1]), order='F')


class _NoForm(Exception):
    """A node the forms do not follow (its coefficients are then found by evaluation)."""


class Form:
    """Values of a node's elements (rows) as sparse forms in the solver's
    vector v: A*v + b plus, for each term, G*((P*v + p) .* (R*v + r))."""

    def __init__(self, A, b, terms=()):
        self.A, self.b, self.terms = A, b, list(terms)

    def mapped(self, M):
        """M times the elements (a sparse matrix: picking, summing, scaling them)."""
        return Form(M @ self.A, M @ self.b, [(M @ G, P, p, R, r) for G, P, p, R, r in self.terms])

    def __add__(self, o):
        return Form(self.A + o.A, self.b + o.b, self.terms + o.terms)

    def scaled(self, c):
        from scipy import sparse
        return self.mapped(sparse.diags(np.asarray(c, F64)))


def _spsel(rows, ncols):
    """The sparse matrix that picks elements rows (one per output row) of ncols."""
    from scipy import sparse
    rows = np.asarray(rows, int)
    return sparse.csr_matrix((np.ones(rows.size), (np.arange(rows.size), rows)), shape=(rows.size, ncols))


def _bcast_rows(shape, out_shape):
    """For each element of out_shape, the element of shape it comes from by broadcasting."""
    nd = max(len(shape), len(out_shape))
    sh = tuple(shape) + (1,) * (nd - len(shape))
    ids = np.arange(int(np.prod(shape))).reshape(sh, order='F')
    return np.broadcast_to(ids, tuple(out_shape) + (1,) * (nd - len(out_shape))).reshape(-1, order='F')


def _const_value(node, L):
    v = _ev(node, L.V(np.zeros((L.n, 1))), {})
    return np.asarray(v[..., 0], F64).reshape(-1, order='F')


def _form(node, L, memo):
    key = id(node)
    hit = memo.get(key)
    if hit is None:
        hit = _form1(node, L, memo)
        memo[key] = hit
    return hit


def _form1(node, L, memo):
    from scipy import sparse
    n = L.n
    N = int(np.prod(node.shape))
    if node.deg == 0:
        return Form(sparse.csr_matrix((N, n)), _const_value(node, L))
    if node.deg > 2:
        raise _NoForm()
    if isinstance(node, NVar):
        o = L.off[node.info.uid]
        return Form(_spsel(np.arange(o, o + N), n), np.zeros(N))
    if isinstance(node, NIndex):
        c = _form(node.child, L, memo)
        return c.mapped(_spsel(node.flat, int(np.prod(node.child.shape))))
    if isinstance(node, (NReshape,)):
        return _form(node.child, L, memo)
    if isinstance(node, NUn):
        c = _form(node.child, L, memo)
        if node.op == '-':
            return c.scaled(-np.ones(N))
        sh = node.child.shape
        perm = np.arange(int(np.prod(sh))).reshape(sh, order='F').T.reshape(-1, order='F')
        return c.mapped(_spsel(perm, N))
    if isinstance(node, NBin):
        a, b = node.a, node.b
        if node.op in ('+', '-'):
            fa = _form(a, L, memo).mapped(_spsel(_bcast_rows(a.shape, node.shape), int(np.prod(a.shape))))
            fb = _form(b, L, memo).mapped(_spsel(_bcast_rows(b.shape, node.shape), int(np.prod(b.shape))))
            return fa + (fb.scaled(-np.ones(N)) if node.op == '-' else fb)
        if node.op in ('.*', './'):
            if node.op == './' and b.deg != 0:
                raise _NoForm()
            ra, rb = _bcast_rows(a.shape, node.shape), _bcast_rows(b.shape, node.shape)
            if b.deg == 0 or a.deg == 0:
                var, const, rv, rc = (a, b, ra, rb) if b.deg == 0 else (b, a, rb, ra)
                c = _const_value(const, L)[rc]
                if node.op == './':
                    with np.errstate(divide='ignore'):
                        c = 1.0 / c
                return _form(var, L, memo).mapped(_spsel(rv, int(np.prod(var.shape)))).scaled(c)
            return _product(_form(a, L, memo).mapped(_spsel(ra, int(np.prod(a.shape)))),
                            _form(b, L, memo).mapped(_spsel(rb, int(np.prod(b.shape)))), N, n)
        if node.op == '.^' and isinstance(b, NConst) and b.a.size == 1:
            pw = float(b.a.reshape(-1)[0])
            fa = _form(a, L, memo)
            if pw == 1:
                return fa
            if pw == 2:
                return _product(fa, fa, N, n)
        raise _NoForm()
    if isinstance(node, NMtimes):
        a, b = node.a, node.b
        m, p = a.shape
        q = b.shape[1]
        if a.deg == 0:
            C = sparse.csr_matrix(_const_value(a, L).reshape(a.shape, order='F'))
            return _form(b, L, memo).mapped(sparse.kron(sparse.identity(q), C, format='csr'))
        if b.deg == 0:
            C = sparse.csr_matrix(_const_value(b, L).reshape(b.shape, order='F'))
            return _form(a, L, memo).mapped(sparse.kron(C.T, sparse.identity(m), format='csr'))
        # (i, j) = sum over k of a(i, k)*b(k, j): products of elements, then summed over k
        ii, kk, jj = np.meshgrid(np.arange(m), np.arange(p), np.arange(q), indexing='ij')
        ia = (ii + m * kk).reshape(-1)
        ib = (kk + p * jj).reshape(-1)
        outrow = (ii + m * jj).reshape(-1)
        prod = _product(_form(a, L, memo).mapped(_spsel(ia, m * p)), _form(b, L, memo).mapped(_spsel(ib, p * q)), ia.size, n)
        S = sparse.csr_matrix((np.ones(outrow.size), (outrow, np.arange(outrow.size))), shape=(m * q, outrow.size))
        return prod.mapped(S)
    if isinstance(node, NReduce):
        c = node.child
        sh = tuple(c.shape) + (1,) * max(0, node.dim + 1 - len(c.shape))
        if node.name == 'sum':
            return _form(c, L, memo).mapped(_sum_matrix(sh, node.dim))
        if node.name == 'cumsum':
            return _form(c, L, memo).mapped(_cumsum_matrix(sh, node.dim))
        if node.name == 'prod' and sh[node.dim] == 1:
            return _form(c, L, memo)
        raise _NoForm()
    if isinstance(node, NCat):
        forms = [_form(pt, L, memo) for pt in node.parts]
        ids = np.arange(N).reshape(node.shape, order='F')
        pos, off = [], 0
        for pt in node.parts:
            sl = [slice(None)] * len(node.shape)
            sl[node.axis] = slice(off, off + pt.shape[node.axis])
            pos.append(ids[tuple(sl)].reshape(-1, order='F'))
            off += pt.shape[node.axis]
        total = None
        for f, ps in zip(forms, pos):
            S = sparse.csr_matrix((np.ones(ps.size), (ps, np.arange(ps.size))), shape=(N, ps.size))
            g = f.mapped(S)
            total = g if total is None else total + g
        return total
    if isinstance(node, NAssign):
        cur = _form(node.base, L, memo)
        for flat, pc in node.pieces:
            keep = np.ones(N)
            keep[flat] = 0.0
            fp = _form(pc, L, memo)
            k = int(np.prod(pc.shape))
            src = np.arange(flat.size) if k == flat.size else np.zeros(flat.size, int)
            S = sparse.csr_matrix((np.ones(flat.size), (flat, src)), shape=(N, k))
            cur = cur.scaled(keep) + fp.mapped(S)
        return cur
    raise _NoForm()


def _sum_matrix(sh, dim):
    """The sparse matrix summing an array of shape sh (column-major) along dim."""
    from scipy import sparse
    ids = np.arange(int(np.prod(sh))).reshape(sh, order='F')
    osh = list(sh)
    osh[dim] = 1
    oid = np.arange(int(np.prod(osh))).reshape(osh, order='F')
    rows = np.broadcast_to(oid, sh).reshape(-1, order='F')
    cols = ids.reshape(-1, order='F')
    return sparse.csr_matrix((np.ones(cols.size), (rows, cols)), shape=(oid.size, ids.size))


def _cumsum_matrix(sh, dim):
    from scipy import sparse
    ids = np.arange(int(np.prod(sh))).reshape(sh, order='F')
    rows, cols = [], []
    for k in range(sh[dim]):
        tgt = np.take(ids, [k], axis=dim)
        for j in range(k + 1):
            rows.append(tgt.reshape(-1, order='F'))
            cols.append(np.take(ids, [j], axis=dim).reshape(-1, order='F'))
    rows, cols = np.concatenate(rows), np.concatenate(cols)
    return sparse.csr_matrix((np.ones(rows.size), (rows, cols)), shape=(ids.size, ids.size))


def _product(fa, fb, N, n):
    """The elementwise product of two forms of degree at most 1."""
    from scipy import sparse
    if fa.terms or fb.terms:
        raise _NoForm()
    return Form(sparse.csr_matrix((N, n)), np.zeros(N), [(sparse.identity(N, format='csr'), fa.A.tocsr(), fa.b, fb.A.tocsr(), fb.b)])


def _quad_parts(f, e, n):
    """(H, g, c) of element e of a form: 0.5*v'*H*v + g'*v + c."""
    from scipy import sparse
    H = sparse.csr_matrix((n, n))
    g = np.asarray(f.A[e].toarray()).reshape(-1)
    c = float(f.b[e])
    for G, P, p, Q, r in f.terms:
        d = np.asarray(G[e].toarray()).reshape(-1)
        if not d.any():
            continue
        D = sparse.diags(d)
        PD, QD = P.T @ D, Q.T @ D
        H = H + PD @ Q + QD @ P
        g = g + PD @ r + QD @ p
        c += float(p @ (d * r))
    return H, g, c


def _clean(M):
    M = np.asarray(M, F64)
    if M.size:
        M[np.abs(M) < 1e-14 * max(1.0, np.abs(M).max())] = 0.0
    return M


def _linear(node, L):
    """(A, b): node = A*v + b, for a node of degree at most 1."""
    try:
        f = _form(node, L, {})
        if not f.terms:
            return np.asarray(f.A.toarray(), F64), np.asarray(f.b, F64)
    except _NoForm:
        pass
    return _linear_ev(node, L)


def _quadratic(node, L):
    """(H, g, c): a scalar node = 0.5*v'*H*v + g'*v + c (degree at most 2)."""
    try:
        f = _form(node, L, {})
        H, g, c = _quad_parts(f, 0, L.n)
        return _clean(H.toarray()), _clean(g), c
    except _NoForm:
        return _quadratic_ev(node, L)


def _linear_ev(node, L):
    """_linear by evaluation: at zero, then at the unit vectors a block at a time."""
    n = L.n
    b = _eval_flat(node, L, np.zeros((n, 1)))[:, 0]
    A = np.zeros((b.size, n))
    for s0 in range(0, n, 256):
        E = np.zeros((n, min(256, n - s0)))
        E[np.arange(s0, s0 + E.shape[1]), np.arange(E.shape[1])] = 1.0
        A[:, s0:s0 + E.shape[1]] = _eval_flat(node, L, E) - b[:, None]
    return _clean(A), b


def _quadratic_ev(node, L):
    """_quadratic by evaluation: at zero, at plus and minus the unit vectors and at the sums of pairs of them."""
    n = L.n
    c = float(_eval_flat(node, L, np.zeros((n, 1)))[0, 0])
    E = np.eye(n)
    fp = _eval_flat(node, L, E)[0] - c
    fm = _eval_flat(node, L, -E)[0] - c
    g = (fp - fm) / 2
    H = np.diag(fp + fm)
    pairs = [(i, j) for i in range(n) for j in range(i + 1, n)]
    for s0 in range(0, len(pairs), 4096):
        chunk = pairs[s0:s0 + 4096]
        P = np.zeros((n, len(chunk)))
        for k, (i, j) in enumerate(chunk):
            P[i, k] = P[j, k] = 1.0
        vals = _eval_flat(node, L, P)[0] - c
        for k, (i, j) in enumerate(chunk):
            H[i, j] = H[j, i] = vals[k] - fp[i] - fp[j]
    return _clean(H), g, c


# ---- text --------------------------------------------------------------------------------------------------------------

def _coef(c, first):
    if c == 1:
        return '' if first else ' + '
    if c == -1:
        return '-' if first else ' - '
    if first:
        return f'{c:g}*'
    return f' + {c:g}*' if c > 0 else f' - {-c:g}*'


def _linear_text(row, b, labels, bare=False):
    parts = []
    for j in np.flatnonzero(row):
        parts.append(_coef(float(row[j]), not parts) + labels[j])
    t = ''.join(parts)
    return t if bare else _joined(t, b)


def _quad_text(H, g, c, labels, bare=False):
    parts = []
    n = len(labels)
    for i in range(n):
        for j in range(i, n):
            v = H[i, i] / 2 if i == j else H[i, j]
            if v != 0:
                term = f'{labels[i]}^2' if i == j else f'{labels[i]}*{labels[j]}'
                parts.append(_coef(float(v), not parts) + term)
    for j in np.flatnonzero(g):
        parts.append(_coef(float(g[j]), not parts) + labels[j])
    t = ''.join(parts)
    return t if bare else _joined(t, c)


def _element_parts(node):
    """Each element as (its terms' text, its constant), for a node of degree at most 2; None otherwise."""
    L = Layout(node.vars({}).values())
    n = int(np.prod(node.shape))
    labels = L.labels()
    if node.deg <= 1:
        A, b = _linear(node, L)
        return [(_linear_text(A[k], 0.0, labels, True), float(b[k])) for k in range(n)]
    if node.deg == 2 and n <= 200 and L.n <= 200:
        try:
            f = _form(node, L, {})
        except _NoForm:
            return None
        parts = []
        for k in range(n):
            H, g, c = _quad_parts(f, k, L.n)
            parts.append((_quad_text(_clean(H.toarray()), _clean(g), 0.0, labels, True), c))
        return parts
    return None


def _joined(terms, c):
    if not terms:
        return f'{c:g}'
    return terms if c == 0 else terms + (f' + {c:g}' if c > 0 else f' - {-c:g}')


def _kind_word(deg):
    return 'Linear' if deg <= 1 else 'Quadratic' if deg == 2 else 'Nonlinear'


def _expr_lines(node, ind):
    n = int(np.prod(node.shape))
    sz = '×'.join(str(s) for s in node.shape)
    head = f'{ind}{_kind_word(node.deg)} OptimizationExpression' + ('' if n == 1 else f' ({sz})')
    parts = _element_parts(node)
    if parts is None:
        where = _named_calls([node])
        return [head, '', f'{ind}  {node.text()}'] + where
    texts = [_joined(t, c) for t, c in parts]
    if n == 1:
        return [head, '', f'{ind}  {texts[0]}']
    return [head, ''] + [f'{ind}  {_sub_label(node.shape, k)} {t}' for k, t in enumerate(texts)]


def _constr_lines(c, ind):
    """lhs rel rhs for each element: the variables' terms on the left, the constant on the right."""
    n = int(np.prod(c.shape))
    sz = '×'.join(str(s) for s in c.shape)
    kind = c.cls.split('.')[-1]
    head = f'{ind}{_kind_word(c.deg())} {kind}' + ('' if n == 1 else f' ({sz})')
    rows = []
    _named_calls([nd for _, nd, _ in c.pieces])
    for f, node, rel in c.pieces:
        parts = _element_parts(node)
        if parts is None:
            lr = getattr(node, 'sides', None)
            t = f'{lr[0].text()} {rel} {lr[1].text()}' if lr else f'{node.text()} {rel} 0'
            rows.append((int(f.min()) if f.size else 0, ('' if n == 1 or f.size == 1 else f'({", ".join(str(int(k) + 1) for k in f[:6])}{", ..." if f.size > 6 else ""}) ') + t, f.size == 1 and n > 1))
            continue
        for j, k in enumerate(f):
            terms, const = parts[j]
            rows.append((int(k), f'{terms or "0"} {rel} {-const + 0.0:g}', n > 1))
    rows.sort(key=lambda r: r[0])
    lines = [head, ''] + [f'{ind}  ' + (f'{_sub_label(c.shape, k)} ' if numbered else '') + t for k, t, numbered in rows]
    if not c.pieces:
        lines.append(f'{ind}  (empty)')
    return lines + _named_calls([nd for _, nd, _ in c.pieces])


def _sub_label(shape, k):
    """(k) in a vector, (i, j) in a matrix."""
    if sum(1 for s in shape if s > 1) <= 1:
        return f'({k + 1})'
    return '(' + ', '.join(str(i + 1) for i in np.unravel_index(k, shape, order='F')) + ')'



# ---- problems ------------------------------------------------------------------------------------------------------------

class OProblem(Obj):
    is_handle = False

    def __init__(self, kind):
        self.kind = kind                    # 'optim' or 'eqn'
        self.objective = None
        self.sense = 'minimize'
        self.constraints = Struct.scalar({}) if kind == 'optim' else None
        self.equations = Struct.scalar({}) if kind == 'eqn' else None
        self.description = ''

    @property
    def cls(self):
        return 'optim.problemdef.OptimizationProblem' if self.kind == 'optim' else 'optim.problemdef.EquationProblem'

    @property
    def shape(self):
        return (1, 1)

    def value_copy(self):
        import copy
        o = copy.copy(self)
        return o

    def _all_constraints(self):
        holder = self.constraints if self.kind == 'optim' else self.equations
        if isinstance(holder, OConstr):
            return [('', holder)]
        if holder is None:
            return []
        res = []
        for k in holder.keys:
            v = holder.get1(k)
            if isinstance(v, OConstr):
                res.append((k, v))
            elif not (isinstance(v, np.ndarray) and v.size == 0):
                raise err('optim:problemdef:Constraints', f"The field '{k}' is not a constraint.", 'optimproblem')
        return res

    def variables(self):
        acc = {}
        if self.objective is not None:
            self.objective.vars(acc)
        for _, c in self._all_constraints():
            for _, node, _ in c.pieces:
                node.vars(acc)
        return acc

    def getprop(self, name):
        k = name.lower()
        if k == 'description':
            return Char.of(self.description)
        if k == 'variables':
            return _vars_struct(self.variables())
        if self.kind == 'optim':
            if k == 'objectivesense':
                return Char.of(self.sense)
            if k == 'objective':
                return OExpr(self.objective) if self.objective is not None else OExpr(NConst(np.zeros((0, 0))))
            if k == 'constraints':
                # shared with the problem's copies: a change made through it copies it first
                return share(self.constraints) if isinstance(self.constraints, Struct) else self.constraints
        else:
            if k == 'equations':
                return share(self.equations) if isinstance(self.equations, Struct) else self.equations
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized method, property, or field '{name}' for class '{self.cls.split('.')[-1]}'.")

    def setprop(self, name, value):
        k = name.lower()
        if k == 'description':
            self.description = py_str(value)
        elif k == 'objective' and self.kind == 'optim':
            node = _as_node(value)
            self.objective = node
        elif k == 'objectivesense' and self.kind == 'optim':
            s = opt_lower(value)
            s = {'min': 'minimize', 'max': 'maximize', 'minimise': 'minimize', 'maximise': 'maximize'}.get(s, s)
            if s not in ('minimize', 'maximize'):
                raise err('optim:problemdef:ObjectiveSense', "ObjectiveSense is 'minimize' or 'maximize'.", 'optimproblem')
            self.sense = s
        elif k == 'constraints' and self.kind == 'optim':
            self.constraints = _constraint_holder(value)
        elif k == 'equations' and self.kind == 'eqn':
            v = _constraint_holder(value)
            if isinstance(v, OConstr) and any(r != '==' for _, _, r in v.pieces):
                raise err('optim:problemdef:Equations', 'Equations are equalities.', 'eqnproblem')
            self.equations = v
        else:
            raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class '{self.cls.split('.')[-1]}'.")

    def propnames(self):
        if self.kind == 'optim':
            return ['Description', 'ObjectiveSense', 'Variables', 'Objective', 'Constraints']
        return ['Description', 'Variables', 'Equations']

    def display_lines(self):
        nv = len(self.variables())
        lines = [f'  {self.cls.split(".")[-1]} with properties:', '', f"       Description: '{self.description}'"]
        if self.kind == 'optim':
            lines.append(f"    ObjectiveSense: '{self.sense}'")
        lines.append(f'         Variables: [1×1 struct] containing {nv} OptimizationVariable{"s" if nv != 1 else ""}')
        if self.kind == 'optim':
            lines.append('         Objective: ' + ('[0×0 OptimizationExpression]' if self.objective is None else
                                                    f'[{"×".join(str(s) for s in self.objective.shape)} OptimizationExpression]'))
        n = len(self._all_constraints())
        word = 'Constraints' if self.kind == 'optim' else 'Equations'
        lines.append(f'{word.rjust(18)}: [1×1 struct] containing {n} {"OptimizationConstraint" if self.kind == "optim" else "OptimizationEquality"}{"s" if n != 1 else ""}')
        lines += ['', '  See problem formulation with show.']
        return lines


def _constraint_holder(v):
    if isinstance(v, OConstr):
        return v
    if isinstance(v, Struct):
        for k in v.keys:
            x = v.get1(k)
            if not isinstance(x, OConstr):
                raise err('optim:problemdef:Constraints', f"The field '{k}' is not a constraint.", 'optimproblem')
        return v
    if isinstance(v, np.ndarray) and v.size == 0:
        return Struct.scalar({})
    raise err('optim:problemdef:Constraints', 'Constraints are a constraint array or a struct of them.', 'optimproblem')


def _problem(kind, args, fn):
    p = OProblem(kind)
    if len(args) % 2:
        raise err(f'optim:{fn}:nargin', 'The options come as names and values.', fn)
    for i in range(0, len(args), 2):
        k = opt_str(args[i])
        if k is None:
            raise err(f'optim:{fn}:option', 'Each option is named by text.', fn)
        p.setprop(k, args[i + 1])
    return p


@bi('optimproblem', arr=False)
def optimproblem(nargout, *args):
    """prob = optimproblem('Objective', expr, 'ObjectiveSense', 'minimize', 'Constraints', constr, 'Description', text): an optimization problem; constraints can be added as fields: prob.Constraints.name = expr <= value."""
    return _problem('optim', args, 'optimproblem')


@bi('eqnproblem', arr=False)
def eqnproblem(nargout, *args):
    """prob = eqnproblem('Equations', eqn, 'Description', text): a system of equations to solve; equations can be added as fields: prob.Equations.name = expr == value."""
    return _problem('eqn', args, 'eqnproblem')


# ---- solving ------------------------------------------------------------------------------------------------------------

class _NodeFH(FH):
    """An expression as a function of the solver's vector (with its gradient by finite differences in the solver)."""

    def __init__(self, node, L, sign=1.0, vector=False):
        self.node, self.L, self.sign, self.vector = node, L, sign, vector

    def text(self):
        return '@(x) problem'

    def name(self):
        return 'problem'

    def scall(self, nargout, *args):
        x = np.asarray(darr(args[0]), F64).reshape(-1, 1)
        v = _eval_flat(self.node, self.L, x)[:, 0] * self.sign
        return out(v.reshape(-1, 1)) if self.vector else float(v[0])

    async def acall(self, nargout, *args):
        return self.scall(nargout, *args)


class _NonlconFH(FH):
    def __init__(self, ineq, eq, L):
        self.ineq, self.eq, self.L = ineq, eq, L

    def text(self):
        return '@(x) constraints'

    def name(self):
        return 'constraints'

    def scall(self, nargout, *args):
        x = np.asarray(darr(args[0]), F64).reshape(-1, 1)
        V = self.L.V(x)
        c = [(_flat_values(node, V) * s) for node, s in self.ineq]
        ceq = [_flat_values(node, V) for node in self.eq]
        cv = np.concatenate(c) if c else np.zeros(0)
        ceqv = np.concatenate(ceq) if ceq else np.zeros(0)
        r = (out(cv.reshape(-1, 1)) if cv.size else np.zeros((0, 0)), out(ceqv.reshape(-1, 1)) if ceqv.size else np.zeros((0, 0)))
        return r if nargout > 1 else r[0]

    async def acall(self, nargout, *args):
        return self.scall(nargout, *args)


def _flat_values(node, V):
    v = _ev(node, V, {})
    return v.reshape((-1, v.shape[-1]), order='F')[:, 0]


def _x0_vector(x0, L, fn):
    x = np.zeros(L.n)
    given = np.zeros(L.n, bool)
    if x0 is None:
        return None
    if not isinstance(x0, Struct):
        raise err(f'optim:{fn}:x0', 'The initial point is a struct with a field for each variable.', fn)
    for i in L.infos:
        if i.name in x0.keys:
            v = np.asarray(darr(x0.get1(i.name)), F64)
            if v.size != i.n:
                raise err(f'optim:{fn}:x0', f"The initial point's field {i.name} has {i.n} elements.", fn)
            o = L.off[i.uid]
            x[o:o + i.n] = v.reshape(-1, order='F')
            given[o:o + i.n] = True
    if not given.all():
        missing = [i.name for i in L.infos if not given[L.off[i.uid]]]
        raise err(f'optim:{fn}:x0', f"The initial point has no value for {', '.join(missing)}.", fn)
    return x


def _sol_struct(x, L):
    s = Struct.scalar({})
    for i in L.infos:
        o = L.off[i.uid]
        a = np.empty((1, 1), object)
        a[0, 0] = out(x[o:o + i.n].reshape(i.shape, order='F'))
        s.f[i.name] = a
    return s


def _split_constraints(cons, L, where=None):
    """Linear rows (A, b, Aeq, beq) and the nonlinear constraints [(node, sign)], [node];
    where, a list, is given (name, shape, flat indices, kind, first row) for each piece."""
    A, b, Aeq, beq = [], [], [], []
    nl_in, nl_eq = [], []
    rows = {'ineqlin': 0, 'eqlin': 0, 'ineqnonlin': 0, 'eqnonlin': 0}
    for name, c in cons:
        for f, node, rel in c.pieces:
            kind = ('ineqlin' if rel != '==' else 'eqlin') if node.deg <= 1 else ('ineqnonlin' if rel != '==' else 'eqnonlin')
            if where is not None:
                where.append((name, c.shape, f, kind, rows[kind]))
            rows[kind] += f.size
            if node.deg <= 1:
                M, m = _linear(node, L)
                if rel == '<=':
                    A.append(M)
                    b.append(-m)
                elif rel == '>=':
                    A.append(-M)
                    b.append(m)
                else:
                    Aeq.append(M)
                    beq.append(-m)
            else:
                if rel == '==':
                    nl_eq.append(node)
                else:
                    nl_in.append((node, 1.0 if rel == '<=' else -1.0))
    cat = lambda xs, n: np.vstack(xs) if xs else np.zeros((0, n))  # noqa: E731
    cv = lambda xs: np.concatenate(xs) if xs else np.zeros(0)  # noqa: E731
    return cat(A, L.n), cv(b), cat(Aeq, L.n), cv(beq), nl_in, nl_eq


def _m(a):
    return out(np.asarray(a, F64)) if np.size(a) else np.zeros((0, 0))


def solve(nargout, *args):
    """[sol, fval, exitflag, output, lambda] = solve(prob, x0, 'Solver', s,
    'Options', opts): an optimization or equation problem solved. The
    solver follows the problem: intlinprog (linear with integer
    variables), linprog (linear), quadprog (a quadratic objective, linear
    constraints), fminunc (nonlinear, no constraints or bounds), fmincon
    (nonlinear), ga (nonlinear with integers); for equations a linear solve
    or fsolve. x0 is a struct of the variables' starting values (nonlinear
    problems need it). sol is a struct of the variables' values; fval the
    objective (a struct of the equations' residuals for an equation
    problem); output.solver names the solver used."""
    nargchk(args, 1, 8, 'solve')
    prob = args[0]
    rest = list(args[1:])
    x0s = None
    if rest and isinstance(rest[0], Struct):
        x0s = rest.pop(0)
    solver, opts = None, None
    if len(rest) % 2:
        raise err('optim:solve:nargin', 'The options come as names and values.', 'solve')
    for i in range(0, len(rest), 2):
        k = opt_lower(rest[i])
        if k == 'solver':
            solver = opt_lower(rest[i + 1])
        elif k == 'options':
            opts = rest[i + 1]
        elif k in ('objectivederivative', 'constraintderivative', 'equationderivative'):
            pass
        else:
            raise err('optim:solve:option', f"'{py_str(rest[i])}' is not an option of solve.", 'solve')
    L = Layout(prob.variables().values())
    if L.n == 0:
        raise err('optim:solve:NoVariables', 'The problem has no variables.', 'solve')
    if prob.kind == 'eqn':
        return _solve_eqn(nargout, prob, L, x0s, solver, opts)
    cons = prob._all_constraints()
    obj = prob.objective if prob.objective is not None else NConst(0.0)
    if int(np.prod(obj.shape)) != 1:
        raise err('optim:solve:ObjectiveNotScalar', 'The objective is a scalar expression.', 'solve')
    sign = -1.0 if prob.sense == 'maximize' else 1.0
    where = []
    A, b, Aeq, beq, nl_in, nl_eq = _split_constraints(cons, L, where)
    lb, ub = L.lb(), L.ub()
    intcon = L.intcon()
    deg = obj.deg
    x0 = _x0_vector(x0s, L, 'solve')
    if solver is None:
        solver = _choose(deg, bool(nl_in or nl_eq), bool(A.size or Aeq.size), lb, ub, intcon)
    lbv, ubv = _m(lb.reshape(-1, 1)), _m(ub.reshape(-1, 1))
    extra = [opts] if opts is not None else []
    _check_solver(solver, deg, bool(nl_in or nl_eq), bool(A.size or Aeq.size), lb, ub, intcon, x0)
    _announce(solver, opts)
    lam_s = None
    if solver in ('linprog', 'intlinprog'):
        f, c0 = _linear(obj, L)
        f = f[0] * sign
        if solver == 'linprog':
            x, fv, flag, outp, lam_s = REG['linprog'].fn(5, _m(f.reshape(-1, 1)), _m(A), _m(b.reshape(-1, 1)), _m(Aeq), _m(beq.reshape(-1, 1)), lbv, ubv, *extra)
        else:
            res = REG['intlinprog'].fn(4, _m(f.reshape(-1, 1)), out((intcon + 1.0).reshape(1, -1)) if intcon.size else np.zeros((0, 0)), _m(A), _m(b.reshape(-1, 1)),
                                       _m(Aeq), _m(beq.reshape(-1, 1)), lbv, ubv, *([np.zeros((0, 0))] + extra if extra else []))
            x, fv, flag, outp = res
        xv = np.asarray(darr(x), F64).reshape(-1) if numel(x) else np.full(L.n, np.nan)
        fval = (float(np.asarray(darr(fv)).reshape(-1)[0]) * sign + float(c0[0])) if numel(fv) else np.nan
    elif solver == 'quadprog':
        H, g, c0 = _quadratic(obj, L)
        res = REG['quadprog'].fn(5, _m(H * sign), _m((g * sign).reshape(-1, 1)), _m(A), _m(b.reshape(-1, 1)), _m(Aeq), _m(beq.reshape(-1, 1)), lbv, ubv,
                                 _m(x0.reshape(-1, 1)) if x0 is not None else np.zeros((0, 0)), *extra)
        x, fv, flag, outp, lam_s = res
        xv = np.asarray(darr(x), F64).reshape(-1)
        fval = float(np.asarray(darr(fv)).reshape(-1)[0]) * sign + c0
    elif solver in ('fmincon', 'fminunc', 'fminsearch'):
        fh = _NodeFH(obj, L, sign)
        if solver == 'fminunc':
            x, fv, flag, outp = REG['fminunc'].fn(4, fh, _m(x0.reshape(-1, 1)), *extra)
        elif solver == 'fminsearch':
            x, fv, flag, outp = REG['fminsearch'].fn(4, fh, _m(x0.reshape(-1, 1)), *extra)
        else:
            nl = _NonlconFH(nl_in, nl_eq, L) if (nl_in or nl_eq) else np.zeros((0, 0))
            x, fv, flag, outp, lam_s = REG['fmincon'].fn(5, fh, _m(x0.reshape(-1, 1)), _m(A), _m(b.reshape(-1, 1)), _m(Aeq), _m(beq.reshape(-1, 1)), lbv, ubv, nl, *extra)
        xv = np.asarray(darr(x), F64).reshape(-1)
        fval = float(np.asarray(darr(fv)).reshape(-1)[0]) * sign
    elif solver in ('ga', 'particleswarm', 'patternsearch', 'surrogateopt'):
        fh = _NodeFH(obj, L, sign)
        nl = _NonlconFH(nl_in, nl_eq, L) if (nl_in or nl_eq) else np.zeros((0, 0))
        if solver == 'ga':
            res = REG['ga'].fn(4, fh, float(L.n), _m(A), _m(b.reshape(-1, 1)), _m(Aeq), _m(beq.reshape(-1, 1)), lbv, ubv, nl,
                               out((intcon + 1.0).reshape(1, -1)) if intcon.size else np.zeros((0, 0)), *extra)
        elif solver == 'particleswarm':
            res = REG['particleswarm'].fn(4, fh, float(L.n), lbv, ubv, *extra)
        elif solver == 'patternsearch':
            res = REG['patternsearch'].fn(4, fh, _m(x0.reshape(-1, 1)), _m(A), _m(b.reshape(-1, 1)), _m(Aeq), _m(beq.reshape(-1, 1)), lbv, ubv, nl, *extra)
        else:
            res = REG['surrogateopt'].fn(4, fh, lbv, ubv, *extra)
        x, fv, flag, outp = res
        xv = np.asarray(darr(x), F64).reshape(-1)
        fval = float(np.asarray(darr(fv)).reshape(-1)[0]) * sign
    sol = _sol_struct(xv, L)
    if isinstance(outp, Struct):
        outp.f['solver'] = np.empty((1, 1), object)
        outp.f['solver'][0, 0] = Char.of(solver)
    else:
        outp = Struct.scalar({'solver': Char.of(solver)})
    return _outs(nargout, sol, fval, flag, outp, _lambdas(lam_s, where, prob, L))


def _lambdas(lam_s, where, prob, L):
    """The solver's multipliers by constraint and by variable: Constraints (a field for
    each named constraint, or one array) and Variables.name.Lower and .Upper."""
    def part(k):
        if isinstance(lam_s, Struct) and k in lam_s.keys:
            v = lam_s.get1(k)
            return np.asarray(darr(v), F64).reshape(-1) if numel(v) else np.zeros(0)
        return np.zeros(0)
    vals = {k: part(k) for k in ('ineqlin', 'eqlin', 'ineqnonlin', 'eqnonlin', 'lower', 'upper')}
    per, shapes = {}, {}
    for name, shape, f, kind, start in where:
        shapes[name] = shape
        arr_ = per.setdefault(name, np.zeros(int(np.prod(shape))))
        v = vals[kind]
        if v.size >= start + f.size:
            arr_[f] = v[start:start + f.size]
    if isinstance(prob.constraints, OConstr):
        c = prob.constraints
        cons = out(per.get('', np.zeros(int(np.prod(c.shape)))).reshape(c.shape, order='F'))
    else:
        cons = Struct.scalar({k: out(v.reshape(shapes[k], order='F')) for k, v in per.items()})
    vs = Struct.scalar({})
    for i in L.infos:
        o = L.off[i.uid]
        lo = vals['lower'][o:o + i.n] if vals['lower'].size >= o + i.n else np.zeros(i.n)
        hi = vals['upper'][o:o + i.n] if vals['upper'].size >= o + i.n else np.zeros(i.n)
        a = np.empty((1, 1), object)
        a[0, 0] = Struct.scalar({'Lower': out(lo.reshape(i.shape, order='F')), 'Upper': out(hi.reshape(i.shape, order='F'))})
        vs.f[i.name] = a
    return Struct.scalar({'Variables': vs, 'Constraints': cons})


def _choose(deg, nonlin, linear, lb, ub, intcon):
    """The solver for a problem of this kind."""
    if deg <= 1 and not nonlin:
        return 'intlinprog' if intcon.size else 'linprog'
    if deg == 2 and not nonlin and not intcon.size:
        return 'quadprog'
    if intcon.size:
        return 'ga'
    if not nonlin and not linear and np.all(np.isinf(lb)) and np.all(np.isinf(ub)):
        return 'fminunc'
    return 'fmincon'


_SOLVE_WITH = ('linprog', 'intlinprog', 'quadprog', 'fmincon', 'fminunc', 'fminsearch', 'ga', 'particleswarm', 'patternsearch', 'surrogateopt')


def _check_solver(solver, deg, nonlin, linear, lb, ub, intcon, x0):
    """The request refused before anything runs: a solver that cannot take this problem."""
    if solver not in _SOLVE_WITH:
        raise err('optim:solve:Solver', f"'{solver}' is not a solver solve uses for an optimization problem ({', '.join(_SOLVE_WITH)}).", 'solve')
    if solver in ('linprog', 'intlinprog') and (deg > 1 or nonlin):
        raise err('optim:solve:Solver', f'{solver} solves linear problems; this one is not.', 'solve')
    if solver == 'quadprog' and (deg > 2 or nonlin):
        raise err('optim:solve:Solver', 'quadprog takes a quadratic objective and linear constraints; this problem is not one.', 'solve')
    if solver in ('quadprog', 'fmincon', 'fminunc', 'fminsearch', 'patternsearch', 'particleswarm') and intcon.size:
        raise err('optim:solve:Integer', f'{solver} does not take integer variables; ga and intlinprog do.', 'solve')
    if solver in ('fmincon', 'fminunc', 'fminsearch', 'patternsearch') and x0 is None:
        raise err('optim:solve:NoX0', f"{solver} needs an initial point: solve(prob, x0) with x0 a struct of the variables' values.", 'solve')
    bounded = bool(np.any(np.isfinite(lb)) or np.any(np.isfinite(ub)))
    if solver in ('fminunc', 'fminsearch') and (nonlin or linear or bounded):
        raise err('optim:solve:Solver', f'{solver} takes no constraints or bounds.', 'solve')
    if solver in ('particleswarm', 'surrogateopt') and (nonlin or linear):
        raise err('optim:solve:Solver', f'{solver} takes bounds only here.', 'solve')
    if solver in ('particleswarm', 'surrogateopt') and not (np.all(np.isfinite(lb)) and np.all(np.isfinite(ub))):
        raise err('optim:solve:Bounds', f'{solver} needs finite bounds on every variable.', 'solve')


def _announce(solver, opts):
    d = 'final'
    if isinstance(opts, Obj):
        try:
            d = opt_lower(opts.getprop('Display')) or d
        except MError:
            pass
    if d not in ('off', 'none'):
        R.write(f'Solving problem using {solver}.\n')


def _solve_eqn(nargout, prob, L, x0s, solver, opts):
    eqs = prob._all_constraints()
    nodes = [node for _, c in eqs for _, node, rel in c.pieces]
    if not nodes:
        raise err('optim:solve:NoEquations', 'The problem has no equations.', 'solve')
    x0 = _x0_vector(x0s, L, 'solve')
    extra = [opts] if opts is not None else []
    lin = all(nd.deg <= 1 for nd in nodes)
    lb, ub = L.lb(), L.ub()
    bounded = bool(np.any(np.isfinite(lb)) or np.any(np.isfinite(ub)))
    if lin and solver in (None, 'lsqlin', 'linsolve', 'mldivide'):
        rows = [_linear(nd, L) for nd in nodes]
        A = np.vstack([r[0] for r in rows])
        b = -np.concatenate([r[1] for r in rows])
        _announce('lsqlin' if bounded or solver == 'lsqlin' else 'linsolve', opts)
        if bounded or solver == 'lsqlin':
            used = 'lsqlin'
            x, _rn, _res, flag, outp = REG['lsqlin'].fn(5, _m(A), _m(b.reshape(-1, 1)), np.zeros((0, 0)), np.zeros((0, 0)), np.zeros((0, 0)), np.zeros((0, 0)),
                                                       _m(lb.reshape(-1, 1)), _m(ub.reshape(-1, 1)), *([np.zeros((0, 0))] + extra if extra else []))
            xv = np.asarray(darr(x), F64).reshape(-1)
        else:
            used = 'linsolve'
            xv, *_ = np.linalg.lstsq(A, b, rcond=None)
            ok = np.allclose(A @ xv, b, atol=1e-8 * max(1.0, np.abs(b).max() if b.size else 1.0))
            flag = 1.0 if ok else -2.0
            R.write('\nEquation solved.\n\n' if ok else '\nNo exact solution: the least-squares one is given.\n\n')
            outp = Struct.scalar({})
    else:
        if x0 is None:
            raise err('optim:solve:NoX0', 'Nonlinear equations need an initial point: solve(prob, x0) with x0 a struct of the variables\' values.', 'solve')
        stack = [NReshape(nd, (int(np.prod(nd.shape)), 1)) for nd in nodes]
        fh = _NodeFH(NCat(0, stack) if len(stack) > 1 else stack[0], L, 1.0, True)
        used = solver or ('lsqnonlin' if bounded else 'fsolve')
        if used not in ('fsolve', 'lsqnonlin'):
            raise err('optim:solve:Solver', f"'{used}' does not solve equations here (fsolve or lsqnonlin).", 'solve')
        if used == 'fsolve' and bounded:
            raise err('optim:solve:Bounds', 'fsolve takes no bounds; lsqnonlin does.', 'solve')
        _announce(used, opts)
        if used == 'fsolve':
            x, fv, flag, outp = REG['fsolve'].fn(4, fh, _m(x0.reshape(-1, 1)), *extra)
        else:
            x, _r, fv, flag, outp = REG['lsqnonlin'].fn(5, fh, _m(x0.reshape(-1, 1)), _m(lb.reshape(-1, 1)), _m(ub.reshape(-1, 1)), *extra)
        xv = np.asarray(darr(x), F64).reshape(-1)
    if not isinstance(outp, Struct):
        outp = Struct.scalar({})
    outp.f['solver'] = np.empty((1, 1), object)
    outp.f['solver'][0, 0] = Char.of(used)
    sol = _sol_struct(xv, L)
    V = L.V(xv.reshape(-1, 1))
    fval = Struct.scalar({})
    for name, c in eqs:
        vals, _ = c.residual(V)
        a = np.empty((1, 1), object)
        a[0, 0] = out(vals[:, 0].reshape(c.shape, order='F'))
        fval.f[name or 'equations'] = a
    return _outs(nargout, sol, fval, flag, outp, Struct.scalar({}))


def _wrap_solve():
    """solve of a problem; anything else goes on to the solve already there (symbolic equations, ode objects)."""
    info = REG.get('solve')
    if info is None:
        bi('solve', nout=10, arr=False)(solve)
        return
    orig, ws, aw = info.fn, info.ws, info.aw

    def run(nargout, args):
        try:
            return solve(nargout, *args)
        except MError:
            raise
        except (ValueError, TypeError, IndexError, ZeroDivisionError, np.linalg.LinAlgError) as e:
            raise err('optim:solve:InvalidInput', f'solve: {e}', 'solve') from None
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and isinstance(args[0], OProblem):
                return run(a[1] if ws else a[0], args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and isinstance(args[0], OProblem):
                return run(a[1] if ws else a[0], args)
            return orig(*a)
    info.fn = f
    info.nout = max(info.nout, 5)


_wrap_solve()


@bi('prob2struct', arr=False)
def prob2struct(nargout, *args):
    """problem = prob2struct(prob, x0, 'Solver', s, 'Options', opts): a
    problem as the solver solve would use takes it, a struct for
    linprog(problem), quadprog(problem), fmincon(problem) and the others:
    f (or H and f) with f0, the constant left out, then Aineq, bineq, Aeq,
    beq, lb, ub, intcon, x0, objective and nonlcon (function handles of
    the solver's vector, the variables in alphabetical order of their
    names, see varindex), solver and options. A maximization becomes the
    minimization of the objective's negative."""
    nargchk(args, 1, 8, 'prob2struct')
    prob = args[0]
    if not isinstance(prob, OProblem):
        raise err('optim:prob2struct:Problem', 'The first input is an optimization or equation problem.', 'prob2struct')
    rest = list(args[1:])
    x0s = rest.pop(0) if rest and isinstance(rest[0], Struct) else None
    solver, opts = None, None
    if len(rest) % 2:
        raise err('optim:prob2struct:nargin', 'The options come as names and values.', 'prob2struct')
    for i in range(0, len(rest), 2):
        k = opt_lower(rest[i])
        if k == 'solver':
            solver = opt_lower(rest[i + 1])
        elif k == 'options':
            opts = rest[i + 1]
        elif k in ('objectivederivative', 'constraintderivative', 'equationderivative', 'objectivefunctionname', 'constraintfunctionname',
                   'equationfunctionname', 'filelocation'):
            pass
        else:
            raise err('optim:prob2struct:option', f"'{py_str(rest[i])}' is not an option of prob2struct.", 'prob2struct')
    L = Layout(prob.variables().values())
    if L.n == 0:
        raise err('optim:prob2struct:NoVariables', 'The problem has no variables.', 'prob2struct')
    x0 = _x0_vector(x0s, L, 'prob2struct')
    lb, ub = L.lb(), L.ub()
    col = lambda v: _m(np.asarray(v, F64).reshape(-1, 1))  # noqa: E731
    d = {}
    if prob.kind == 'eqn':
        nodes = [node for _, c in prob._all_constraints() for _, node, _ in c.pieces]
        if not nodes:
            raise err('optim:prob2struct:NoEquations', 'The problem has no equations.', 'prob2struct')
        bounded = bool(np.any(np.isfinite(lb)) or np.any(np.isfinite(ub)))
        if all(nd.deg <= 1 for nd in nodes) and solver in (None, 'lsqlin'):
            rows = [_linear(nd, L) for nd in nodes]
            solver = 'lsqlin'
            d.update(C=_m(np.vstack([r[0] for r in rows])), d=col(-np.concatenate([r[1] for r in rows])), Aineq=EMPTY(), bineq=EMPTY(), Aeq=EMPTY(), beq=EMPTY(),
                     lb=col(lb), ub=col(ub))
        else:
            solver = solver or ('lsqnonlin' if bounded else 'fsolve')
            stack = [NReshape(nd, (int(np.prod(nd.shape)), 1)) for nd in nodes]
            d.update(objective=_NodeFH(NCat(0, stack) if len(stack) > 1 else stack[0], L, 1.0, True), x0=col(x0) if x0 is not None else EMPTY())
            if solver == 'lsqnonlin':
                d.update(lb=col(lb), ub=col(ub))
    else:
        obj = prob.objective if prob.objective is not None else NConst(0.0)
        sign = -1.0 if prob.sense == 'maximize' else 1.0
        A, b, Aeq, beq, nl_in, nl_eq = _split_constraints(prob._all_constraints(), L)
        intcon = L.intcon()
        if solver is None:
            solver = _choose(obj.deg, bool(nl_in or nl_eq), bool(A.size or Aeq.size), lb, ub, intcon)
        # (an initial point is not needed here: the struct goes without one)
        _check_solver(solver, obj.deg, bool(nl_in or nl_eq), bool(A.size or Aeq.size), lb, ub, intcon, np.zeros(L.n))
        lin = dict(Aineq=_m(A), bineq=col(b), Aeq=_m(Aeq), beq=col(beq), lb=col(lb), ub=col(ub))
        if solver in ('linprog', 'intlinprog'):
            f, c0 = _linear(obj, L)
            d.update(f=col(f[0] * sign), f0=float(c0[0]) * sign)
            if solver == 'intlinprog':
                d['intcon'] = out((intcon + 1.0).reshape(1, -1)) if intcon.size else EMPTY()
            d.update(lin)
            if solver == 'intlinprog':
                d['x0'] = col(x0) if x0 is not None else EMPTY()
        elif solver == 'quadprog':
            H, g, c0 = _quadratic(obj, L)
            d.update(H=_m(H * sign), f=col(g * sign), f0=c0 * sign, **lin)
            d['x0'] = col(x0) if x0 is not None else EMPTY()
        else:
            d.update(objective=_NodeFH(obj, L, sign), x0=col(x0) if x0 is not None else EMPTY(), **lin)
            d['nonlcon'] = _NonlconFH(nl_in, nl_eq, L) if (nl_in or nl_eq) else EMPTY()
            if intcon.size:
                d['intcon'] = out((intcon + 1.0).reshape(1, -1))
            d['nvars'] = float(L.n)
    d['solver'] = Char.of(solver)
    d['options'] = opts if opts is not None else REG['optimoptions'].fn(1, Char.of(solver))
    return Struct.scalar(d)


# ---- evaluating, showing ---------------------------------------------------------------------------------------------------

def _point(pt, node, fn):
    acc = node.vars({}) if not isinstance(node, list) else {k: v for n in node for k, v in n.vars({}).items()}
    L = Layout(acc.values())
    x = _x0_vector(pt, L, fn)
    return L, (x if x is not None else np.zeros(L.n))


@bi('evaluate', arr=False)
def evaluate(nargout, *args):
    """val = evaluate(expr, pt): an expression's value at a point, a struct with a field for each of its variables (solve's sol)."""
    nargchk(args, 2, 2, 'evaluate')
    node = _as_node(args[0])
    L, x = _point(args[1], node, 'evaluate')
    v = _ev(node, L.V(x.reshape(-1, 1)), {})
    return out(v[..., 0].reshape(node.shape))


@bi('infeasibility', arr=False)
def infeasibility(nargout, *args):
    """infeas = infeasibility(constr, pt): how far each constraint is from holding at the point: max(0, lhs - rhs) for <=, max(0, rhs - lhs) for >=, abs(lhs - rhs) for ==."""
    nargchk(args, 2, 2, 'infeasibility')
    c = args[0]
    if not isinstance(c, OConstr):
        raise err('optim:infeasibility:Constraint', 'The first input is a constraint.', 'infeasibility')
    L, x = _point(args[1], [node for _, node, _ in c.pieces], 'infeasibility')
    vals, rels = c.residual(L.V(x.reshape(-1, 1)))
    v = vals[:, 0]
    res = np.where(rels == '<=', np.maximum(v, 0), np.where(rels == '>=', np.maximum(-v, 0), np.abs(v)))
    return out(res.reshape(c.shape, order='F').astype(F64))


@bi('varindex', arr=False)
def varindex(nargout, *args):
    """idx = varindex(prob) or varindex(prob, varname): where each variable sits in the solver's vector (a struct of index vectors, or one)."""
    nargchk(args, 1, 2, 'varindex')
    prob = args[0]
    if not isinstance(prob, OProblem):
        raise err('optim:varindex:Problem', 'The first input is an optimization or equation problem.', 'varindex')
    L = Layout(prob.variables().values())
    s = Struct.scalar({})
    for i in L.infos:
        a = np.empty((1, 1), object)
        a[0, 0] = (np.arange(i.n, dtype=F64) + L.off[i.uid] + 1).reshape(1, -1)
        s.f[i.name] = a
    if len(args) > 1:
        nm = py_str(args[1])
        if nm not in s.keys:
            raise err('optim:varindex:Name', f"The problem has no variable '{nm}'.", 'varindex')
        return s.get1(nm)
    return s


@bi('show', arr=False)
def show(nargout, *args):
    """show(obj): an optimization variable, expression, constraint or problem written out (a problem's variables, objective, constraints and bounds)."""
    nargchk(args, 1, 2, 'show')
    o = args[0]
    lines = []
    if isinstance(o, OVar):
        i = o.info
        lines = [f'  {"×".join(str(s) for s in i.shape)} OptimizationVariable array' if i.n > 1 else '  OptimizationVariable', '']
        lines += [f'    {_elem_label(i, k)}' for k in range(i.n)]
    elif isinstance(o, OExpr):
        lines = _expr_lines(o.node, '  ')
    elif isinstance(o, OConstr):
        lines = _constr_lines(o, '  ')
    elif isinstance(o, OProblem):
        word = 'OptimizationProblem' if o.kind == 'optim' else 'EquationProblem'
        L = Layout(o.variables().values())
        lines = [f'  {word} : ', '', '\tSolve for:', '       ' + ', '.join(i.name for i in L.infos)]
        ints = [i.name for i in L.infos if i.kind == 'integer']
        if ints:
            lines.append('       where: ' + ', '.join(ints) + ' integer')
        if o.kind == 'optim':
            lines += ['', f'\t{o.sense} :']
            lines += [('     ' + ln.strip()) if ln.strip() else '' for ln in (_expr_lines(o.objective, '') if o.objective is not None else ['', '', '0'])[2:]]
        for name, c in o._all_constraints():
            lines += ['', f'\tsubject to {name}:' if name else '\tsubject to:']
            lines += [('     ' + ln.strip()) if ln.strip() else '' for ln in _constr_lines(c, '')[2:]]
        bnds = []
        for i in L.infos:
            for k in range(i.n):
                lo, hi = i.lb.reshape(-1, order='F')[k], i.ub.reshape(-1, order='F')[k]
                lab = _elem_label(i, k)
                if np.isfinite(lo) and np.isfinite(hi):
                    bnds.append(f'       {lo:g} <= {lab} <= {hi:g}')
                elif np.isfinite(lo):
                    bnds.append(f'       {lo:g} <= {lab}')
                elif np.isfinite(hi):
                    bnds.append(f'       {lab} <= {hi:g}')
        if bnds:
            lines += ['', '\tvariable bounds:'] + bnds
    else:
        raise err('optim:show:Input', 'show takes an optimization variable, expression, constraint or problem.', 'show')
    R.write('\n'.join(lines) + '\n')
    return None


@bi('showbounds', arr=False)
def showbounds(nargout, *args):
    """showbounds(x): an optimization variable's finite bounds written out."""
    nargchk(args, 1, 1, 'showbounds')
    v = args[0]
    if not isinstance(v, OVar):
        raise err('optim:showbounds:Input', 'showbounds takes an optimization variable.', 'showbounds')
    i = v.info
    lines = []
    for k in range(i.n):
        lo, hi = i.lb.reshape(-1, order='F')[k], i.ub.reshape(-1, order='F')[k]
        lab = _elem_label(i, k)
        if np.isfinite(lo) and np.isfinite(hi):
            lines.append(f'  {lo:g} <= {lab} <= {hi:g}')
        elif np.isfinite(lo):
            lines.append(f'  {lo:g} <= {lab}')
        elif np.isfinite(hi):
            lines.append(f'  {lab} <= {hi:g}')
    R.write(('\n'.join(lines) if lines else f'  {i.name} is unbounded.') + '\n')
    return None


@bi('fcn2optimexpr', nout=99, aw=True, arr=False)
async def fcn2optimexpr(nargout, *args):
    """[out1, out2, ...] = fcn2optimexpr(fun, in1, in2, ..., 'OutputSize', sz,
    'Analysis', 'on'): a function of the language as an optimization
    expression: first fun is called with the expressions themselves, which
    gives an expression when it uses operations expressions support; else
    (or with 'Analysis' 'off') it is evaluated at each point the solver
    asks for, its output size taken from OutputSize or from one call at
    zeros."""
    nargchk(args, 2, None, 'fcn2optimexpr')
    f = args[0]
    if is_str(f):
        f = R.NamedFH(py_str(f))
    if not isinstance(f, FH):
        raise err('optim:fcn2optimexpr:Function', 'The first input is a function handle.', 'fcn2optimexpr')
    rest = list(args[1:])
    opts = {}
    while len(rest) >= 2 and is_str(rest[-2]) and opt_lower(rest[-2]) in ('outputsize', 'reuseevaluation', 'analysis', 'display'):
        opts[opt_lower(rest[-2])] = rest[-1]
        rest = rest[:-2]
    nout = max(nargout, 1)
    analysis = opt_lower(opts['analysis']) if 'analysis' in opts else 'on'
    if analysis != 'off':
        try:
            r = await f.acall(nout, *rest)
            vals = r if nout > 1 else (r,)
            if all(_is_opt(v) for v in vals):
                res = tuple(v if isinstance(v, OExpr) else OExpr(v.node()) for v in vals)
                return res[0] if nout == 1 else res
        except MError:
            pass
    inputs = [_as_node(v) for v in rest]
    if 'outputsize' in opts:
        sz = opts['outputsize']
        sizes = [tuple(int(x) for x in np.asarray(darr(c)).reshape(-1)) for c in sz.a.reshape(-1)] if isinstance(sz, Cell) else \
            [tuple(int(x) for x in np.asarray(darr(sz)).reshape(-1))] * nout
    else:
        zs = [out(np.zeros(n.shape)) for n in inputs]
        r = await f.acall(nout, *zs)
        vals = r if nout > 1 else (r,)
        sizes = [tuple(shape_of(v)) for v in vals]
    res = tuple(OExpr(NCall(f, inputs, sizes[k], k, nout, '')) for k in range(nout))
    return res[0] if nout == 1 else res


# ---- paretosearch --------------------------------------------------------------------------------------------------------

def _weights(m, count):
    """About count weight vectors spread evenly inside the simplex of m objectives (its corners left out: those are the objectives alone)."""
    if m == 1:
        return np.ones((0, 1))
    if m == 2:
        t = np.linspace(0, 1, max(count - m, 1) + 2)[1:-1]
        return np.column_stack([t, 1 - t])
    h = 1
    while math.comb(h + m - 1, m - 1) - m < count - m:
        h += 1
    pts = []

    def rec(prefix, left, k):
        if k == m - 1:
            pts.append(prefix + [left])
            return
        for i in range(left + 1):
            rec(prefix + [i], left - i, k + 1)
    rec([], h, 0)
    W = np.array(pts, F64) / h
    return W[(W > 0).sum(axis=1) > 1]


class _ScalarFH(FH):
    def __init__(self, fn):
        self.fn = fn

    def text(self):
        return '@(x) scalarized'

    def name(self):
        return 'scalarized'

    def scall(self, nargout, *args):
        return float(self.fn(np.asarray(darr(args[0]), F64).reshape(-1)))

    async def acall(self, nargout, *args):
        return self.scall(nargout, *args)


from . import optim as OP  # noqa: E402
from . import globalopt as GO  # noqa: E402

OP._SOLVERS['paretosearch'] = ((), {'ParetoSetSize': '60', 'MaxIterations': '100*numberOfVariables', 'MaxFunctionEvaluations': '3000*(numberOfVariables+numberOfObjectives)',
                                    'MeshTolerance': 1e-6, 'ConstraintTolerance': 1e-6, 'MaxTime': math.inf, 'InitialPoints': None, 'UseParallel': False})
for _k in ('ParetoSetSize', 'InitialPoints'):
    OP._COMMON.setdefault(_k, (None, 'any'))


@bi('paretosearch', nout=5, arr=False)
def paretosearch(nargout, *args):
    """[x, fval, exitflag, output, residuals] = paretosearch(fun, nvars, A, b,
    Aeq, beq, lb, ub, nonlcon, options): points on the Pareto front of the
    objectives fun returns (a row): each objective minimized alone first,
    then for weights spread evenly (a quarter more than ParetoSetSize, 60) a smooth
    maximum of the weighted objectives (each scaled to its range above its
    minimum), mu*log(sum(exp(w.*v/mu))) with mu 0.02, each by
    patternsearch from the last one's answer; the points no other
    dominates are kept, the most crowded dropped down to ParetoSetSize,
    sorted by the first objective. PyLAB's own scalarization method."""
    nargchk(args, 2, 10, 'paretosearch')
    a = list(args) + [None] * (10 - len(args))
    f = OP._fh(a[0], 'paretosearch')
    n = int(num(a[1]))
    options = OP._arg(a, 9)
    if isinstance(OP._arg(a, 8), (OP.OptimOptions, Struct)):
        options, a[8] = a[8], None
    opts = OP._Opts('paretosearch', options, n, 'paretosearch')
    size = int(GO._opt(opts, 'ParetoSetSize', 60))
    mesh = float(GO._opt(opts, 'MeshTolerance', 1e-6))
    none = np.zeros((0, 0))
    cons = [a[k] if a[k] is not None else none for k in range(2, 9)]
    lb, ub = cons[4], cons[5]
    lbv = np.asarray(darr(lb), F64).reshape(-1) if numel(lb) else np.full(n, -INF)
    ubv = np.asarray(darr(ub), F64).reshape(-1) if numel(ub) else np.full(n, INF)
    count = [0]

    def objs(x):
        count[0] += 1
        return np.asarray(darr(f.scall(1, out(x.reshape(1, -1)))), F64).reshape(-1)
    x0 = np.where(np.isfinite(lbv) & np.isfinite(ubv), (lbv + ubv) / 2, np.where(np.isfinite(lbv), lbv, np.where(np.isfinite(ubv), ubv, 0.0)))
    m = objs(x0).size
    quiet = REG['optimoptions'].fn(1, Char.of('patternsearch'), Char.of('Display'), Char.of('off'), Char.of('MeshTolerance'), mesh)
    ps = REG['patternsearch'].fn

    def run(fn, start):
        r = ps(4, _ScalarFH(fn), out(start.reshape(1, -1)), *cons, quiet)
        return np.asarray(darr(r[0]), F64).reshape(-1)
    ideal_x = [run(lambda x, i=i: objs(x)[i], x0) for i in range(m)]
    F = np.array([objs(x) for x in ideal_x])
    z = F.min(axis=0)
    scale = np.maximum(F.max(axis=0) - z, 1e-12)
    xs = list(ideal_x)
    start = ideal_x[0]
    mu = 0.02
    for w in _weights(m, size + max(2, size // 4)):

        def smoothmax(x, w=w):
            # mu*log(sum(exp(w.*v/mu))): smooth, increasing in every objective (so its minima are Pareto optimal), near max(w.*v)
            t = w * (objs(x) - z) / scale
            top = float(np.max(t))
            return top + mu * math.log(float(np.sum(np.exp((t - top) / mu))))
        start = run(smoothmax, start)
        xs.append(start)
    X = np.array(xs)
    FV = np.array([objs(x) for x in X])
    keep = []
    tol = 1e-6 * scale
    for i in range(len(X)):
        dom = np.any(np.all(FV <= FV[i] + 1e-12, axis=1) & np.any(FV < FV[i] - 1e-12, axis=1))
        dup = any(np.all(np.abs(FV[i] - FV[j]) <= tol) for j in keep)
        if not dom and not dup:
            keep.append(i)
    while len(keep) > size:
        # the most crowded point goes, never an end of the front
        cd = GO._crowding(FV[keep])
        keep.pop(int(np.argmin(cd)))
    order = sorted(keep, key=lambda i: FV[i, 0])
    X, FV = X[order], FV[order]
    msg = 'Pareto set found that satisfies the constraints.'
    GO._say(opts.display(), f'\n{msg}\n')
    outp = GO._output(iterations=len(xs), funccount=count[0], volume=np.nan, averagedistance=np.nan, spread=np.nan, maxconstraint=0.0, message=msg)
    resid = Struct.scalar({'lower': out(np.maximum(lbv - X, 0)) if X.size else EMPTY(), 'upper': out(np.maximum(X - ubv, 0)) if X.size else EMPTY(),
                           'ineqlin': EMPTY(), 'eqlin': EMPTY(), 'ineqnonlin': EMPTY(), 'eqnonlin': EMPTY()})
    return _outs(nargout, out(X), out(FV), 1.0, outp, resid)
