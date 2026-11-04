"""Tall arrays: arrays (and tables) whose computations wait until gather.

tall(A) or tall(ds) makes one; operators, indexing and the functions listed
in DEFERRED, given a tall array, give a tall array that remembers what to
compute; gather computes it (the datastore read whole, each step once) and
gives the value in memory. Plots of tall arrays gather their data first.
"""
import inspect

import numpy as np

from . import bi, REG
from ._util import err, nargchk, out
from ..values import MError, Obj, Char, Cell, Struct, FH, EMPTY, shape_of, class_of, size_str, share
from .. import runtime as R

_LIVE = [0]           # how many tall arrays have been made: no wrapper looks at its inputs before the first


class TNode:
    """One step: a function and its inputs (tall arrays among them), and once computed its outputs."""
    __slots__ = ('fn', 'W', 'ws', 'aw', 'nout', 'args', 'vals')

    def __init__(self, fn, args, nout=1, ws=False, aw=False, W=None, vals=None):
        self.fn, self.args, self.nout, self.ws, self.aw, self.W = fn, tuple(args), nout, ws, aw, W
        self.vals = vals

    async def run(self):
        if self.vals is None:
            args = [await value(a) for a in self.args]
            r = self.fn(self.W, self.nout, *args) if self.ws else self.fn(self.nout, *args)
            if self.aw or inspect.isawaitable(r):
                r = await r
            # held by every step that uses them: a change made later copies first
            self.vals = tuple(share(v) for v in (r if self.nout > 1 and isinstance(r, tuple) else (r,)))
        return self.vals


async def value(x):
    """A value in memory: a tall array's computed."""
    if type(x) is Tall:
        vals = await x.node.run()
        if x.k >= len(vals):
            raise err('MATLAB:TooManyOutputs', 'Too many output arguments.', 'gather')
        return vals[x.k]
    if type(x) is Cell and _LIVE[0] and any(type(c) is Tall for c in x.a.reshape(-1)):
        c = Cell(np.empty(x.a.shape, object))
        flat = x.a.reshape(-1)
        res = c.a.reshape(-1)
        for i, v in enumerate(flat):
            res[i] = await value(v)
        return c
    return x


def is_tall(v):
    return type(v) is Tall


class Tall(Obj):
    """A tall array: an output of a step not computed until gather."""
    __slots__ = ('node', 'k', 'known')
    is_handle = False
    cls = 'tall'

    def __init__(self, node, k=0, known=None):
        self.node, self.k = node, k
        self.known = known              # (shape, class) when they are known without computing
        _LIVE[0] += 1

    def value_copy(self):
        return Tall(self.node, self.k, self.known)

    def evaluated(self):
        return self.node.vals is not None

    def now(self):
        """The value, computed now (for end in an index)."""
        return R.run_sync(value(self))

    @property
    def shape(self):
        if self.known is not None:
            return self.known[0]
        return shape_of(self.now())

    # indexing: each makes a step
    def index(self, args):
        from ..index import idx
        return Tall(TNode(lambda n, A, *a: idx(A, a), (self,) + tuple(args)))

    def brace(self, args):
        from ..index import cidx
        from ..index import one

        def f(n, A, *a):
            return one(cidx(A, a))
        return [Tall(TNode(f, (self,) + tuple(args)))]

    def index_assign(self, args, V):
        from ..index import asgn
        return Tall(TNode(lambda n, A, v, *a: asgn(A, a, v), (self, V) + tuple(args)), 0, self.known)

    def getprop(self, name):
        from ..index import fld1
        return Tall(TNode(lambda n, A, nm: fld1(A, nm), (self, name)))

    def setprop(self, name, V):
        from ..index import fasgn
        old = Tall(self.node, self.k, self.known)
        self.node, self.k = TNode(lambda n, A, nm, v: fasgn(A, nm, v), (old, name, V)), 0

    def propnames(self):
        return []

    def display_lines(self):
        if self.node.vals is None:
            if self.known is not None:
                sh, cl = self.known
                return [f'  {size_str(sh)} tall {cl} {_kind(sh, cl)}'.rstrip(), '', '    Not computed yet: gather computes it.']
            return ['  M×N tall array', '', '    Not computed yet: gather computes it.']
        v = self.node.vals[self.k] if self.k < len(self.node.vals) else EMPTY()
        sh, cl = shape_of(v), class_of(v)
        head = [f'  {size_str(sh)} tall {cl} {_kind(sh, cl)}'.rstrip(), '']
        from ..display import body_lines
        from ..index import idx
        rows = sh[0] if sh else 0
        if rows > 8 and len(sh) == 2:
            part = idx(v, (out(np.arange(1, 9, dtype=float).reshape(1, -1)), Char.of(':')))
        else:
            part = v
        lines = body_lines(part)
        # the value's own heading (a table's size and class) gives way to the tall one
        while lines and (lines[0].strip() == '' or (lines[0].startswith('  ') and ('table' in lines[0] or cl in lines[0]) and '×' in lines[0])):
            lines = lines[1:]
        if rows > 8 and len(sh) == 2:
            lines.append('    :' + ('' if cl != 'table' else ''))
        return head + lines


def _kind(sh, cl):
    if cl in ('table', 'timetable'):
        return ''
    if len(sh) == 2 and sh[1] == 1 and sh[0] != 1:
        return 'column vector'
    if len(sh) == 2 and sh[0] == 1 and sh[1] != 1:
        return 'row vector'
    return 'array' if not (len(sh) == 2 and sh == (1, 1)) else ''


def _source(v):
    """A tall array over a value in memory: already computed."""
    return Tall(TNode(None, (), vals=(share(v),)), 0, (shape_of(v), class_of(v)))


@bi('tall', arr=False)
def tall(nargout, *args):
    """t = tall(A) or tall(ds): a tall array over an array (or table) in
    memory, or over everything a datastore reads (read when gathered)."""
    nargchk(args, 1, 1, 'tall')
    v = args[0]
    if type(v) is Tall:
        return v
    from .datastores import Datastore
    if isinstance(v, Datastore):
        async def readall(n, ds):
            c = ds.copy()
            c.reset()
            return await c.readall()
        return Tall(TNode(readall, (v.copy(),), aw=True))
    if isinstance(v, FH):
        raise err('MATLAB:bigdata:array:InvalidTallInput', 'tall takes an array, a table or a datastore.', 'tall')
    return _source(v)


@bi('gather', aw=True, nout=64, arr=False)
async def gather(nargout, *args):
    """[a, b, ...] = gather(ta, tb, ...): tall arrays computed, as values in
    memory; other values given back as they are."""
    nargchk(args, 1, 64, 'gather')
    if nargout > len(args) or (nargout <= 1 and len(args) > 1 and nargout != 0 and False):
        raise err('MATLAB:TooManyOutputs', 'Too many output arguments.', 'gather')
    vals = [await value(a) for a in args]
    if nargout <= 1:
        return vals[0]
    return tuple(vals[:nargout])


@bi('istall')
def istall(nargout, *args):
    """tf = istall(A): whether A is a tall array."""
    nargchk(args, 1, 1, 'istall')
    return type(args[0]) is Tall


@bi('classUnderlying', aw=True, arr=False)
async def classUnderlying(nargout, *args):
    """c = classUnderlying(t): the class of the values a tall array holds (of the value itself when it is not tall)."""
    nargchk(args, 1, 1, 'classUnderlying')
    v = args[0]
    if type(v) is Tall and v.known is not None:
        return Char.of(v.known[1])
    return Char.of(class_of(await value(v)))


@bi('isaUnderlying', aw=True, arr=False)
async def isaUnderlying(nargout, *args):
    """tf = isaUnderlying(t, classname): whether a tall array's values are of the class (or a kind: 'numeric', 'float', 'integer')."""
    nargchk(args, 2, 2, 'isaUnderlying')
    c = await classUnderlying(1, args[0])
    from ..values import py_str
    want = py_str(args[1])
    cl = c.str()
    groups = {'numeric': ('double', 'single', 'int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64'),
              'float': ('double', 'single'), 'integer': ('int8', 'int16', 'int32', 'int64', 'uint8', 'uint16', 'uint32', 'uint64')}
    return cl == want or cl in groups.get(want, ())


# ---- functions that defer -------------------------------------------------------------------------------------------------------

DEFERRED = """
abs sign sqrt exp expm1 log log1p log2 log10 nthroot realpow sin cos tan asin acos atan atan2 sinh cosh tanh asinh acosh atanh
sec csc cot sind cosd tand asind acosd atand atan2d deg2rad rad2deg hypot round floor ceil fix mod rem idivide real imag conj angle
gamma gammaln erf erfc erfinv erfcinv beta betaln power times plus minus rdivide ldivide
double single int8 int16 int32 int64 uint8 uint16 uint32 uint64 logical char string cellstr cast
isnan isinf isfinite ismissing standardizeMissing fillmissing rmmissing isoutlier filloutliers rmoutliers
sum prod mean median mode std var max min bounds cumsum cumprod cummax cummin any all nnz numel size height width length isempty
histcounts histcounts2 unique sort sortrows topkrows maxk mink quantile prctile iqr range skewness kurtosis cov corrcoef diff find
normalize rescale zscore movmean movmedian movsum
and or not xor ismember isrow iscolumn
head tail varfun rowfun groupsummary groupcounts findgroups splitapply removevars addvars renamevars movevars
table2array array2table table2cell table2timetable timetable2table innerjoin outerjoin join horzcat vertcat cat repmat
lower upper strtrim strcat strlength contains startsWith endsWith replace strrep extractBefore extractAfter erase pad split
regexprep strsplit num2str str2double
year month day hour minute second datetime duration days hours minutes seconds milliseconds years dateshift between isbetween
weekday timeofday quarter week
categorical categories countcats discretize iscategory mergecats removecats renamecats
arrayfun cellfun
""".split()

PLOTS = """plot plot3 scatter scatter3 histogram histogram2 bar barh line area binscatter boxchart boxplot stairs stem pie heatmap
plotmatrix gscatter ksdensity ecdf cdfplot""".split()


def _wrap_defer(name):
    info = REG.get(name)
    if info is None:
        return
    orig, ws, aw = info.fn, info.ws, info.aw

    def defer(a):
        nargout = a[1] if ws else a[0]
        args = a[2:] if ws else a[1:]
        n = max(nargout, 1)
        node = TNode(orig, args, n, ws, aw, a[0] if ws else None)
        if n > 1:
            return tuple(Tall(node, k) for k in range(n))
        known = None
        if name in _SAME_SHAPE and len(args) == 1 and type(args[0]) is Tall and args[0].known is not None:
            sh, cl = args[0].known
            known = (sh, cl if cl in ('double', 'single') else 'double') if name not in _LOGICAL else (sh, 'logical')
        return Tall(node, 0, known)

    if aw:
        async def f(*a):
            if _LIVE[0] and any(type(x) is Tall for x in (a[2:] if ws else a[1:])):
                return defer(a)
            return await orig(*a)
    else:
        def f(*a):
            if _LIVE[0] and any(type(x) is Tall for x in (a[2:] if ws else a[1:])):
                return defer(a)
            return orig(*a)
    f.__name__ = getattr(orig, '__name__', name)
    f.__doc__ = getattr(orig, '__doc__', None)
    info.fn = f


_SAME_SHAPE = set('abs sign sqrt exp expm1 log log1p log2 log10 sin cos tan asin acos atan sinh cosh tanh round floor ceil fix real imag conj angle '
                  'gamma gammaln erf erfc isnan isinf isfinite ismissing deg2rad rad2deg'.split())
_LOGICAL = {'isnan', 'isinf', 'isfinite', 'ismissing'}


def _wrap_gathered(name):
    """A plot of tall arrays: their values gathered, then plotted."""
    info = REG.get(name)
    if info is None:
        return
    orig, ws, aw = info.fn, info.ws, info.aw

    def gathered(a):
        lead = 2 if ws else 1
        return a[:lead] + tuple(R.run_sync(value(x)) if type(x) is Tall else x for x in a[lead:])

    if aw:
        async def f(*a):
            if _LIVE[0] and any(type(x) is Tall for x in a):
                a = gathered(a)
            return await orig(*a)
    else:
        def f(*a):
            if _LIVE[0] and any(type(x) is Tall for x in a):
                a = gathered(a)
            return orig(*a)
    f.__name__ = getattr(orig, '__name__', name)
    f.__doc__ = getattr(orig, '__doc__', None)
    info.fn = f


for _n in DEFERRED:
    _wrap_defer(_n)
for _n in PLOTS:
    _wrap_gathered(_n)


def _ops(op, *xs):
    from .. import ops
    if op in ('hcat', 'vcat'):
        f = getattr(ops, op)
        return Tall(TNode(lambda n, *v: f(list(v)), xs))
    f = getattr(ops, op)
    known = None
    if len(xs) == 1 and type(xs[0]) is Tall and xs[0].known is not None and op in ('uminus', 'uplus', 'not_'):
        known = (xs[0].known[0], 'logical' if op == 'not_' else xs[0].known[1])
    return Tall(TNode(lambda n, *v: f(*v), xs), 0, known)


def _install():
    from .. import ops
    ops.OBJ_OPS[Tall] = _ops


_install()


def classes():
    return (Tall,)
