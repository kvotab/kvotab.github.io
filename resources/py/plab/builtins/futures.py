"""Futures, memoized functions, timing and preferences: parfeval,
parfevalOnAll, backgroundPool, fetchOutputs, fetchNext, afterEach,
afterAll, wait and cancel of futures; memoize; timeit; getpref, setpref,
addpref, ispref and rmpref.

PyLAB runs a function given to parfeval in the engine when parfeval is
called (a program's computations run one at a time here), so its future
is finished at once: its outputs, or its error, are waiting to be fetched.
"""
import json
import os
import time

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, out, num, opt_str, is_str, darr
from ..values import MError, Obj, Char, Cell, Struct, FH, EMPTY, numel, py_str, class_of
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        aw = kw.get('aw', False)
        if aw:
            async def g(*a):
                try:
                    return await f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        else:
            def g(*a):
                try:
                    return f(*a)
                except MError:
                    raise
                except (ValueError, TypeError, IndexError) as e:
                    raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


# ---- futures ------------------------------------------------------------------------------------------------------------------

_IDS = [0]


class Future(Obj):
    cls = 'parallel.FevalFuture'
    is_handle = True

    def __init__(self, fn, nout, ins):
        _IDS[0] += 1
        self.id = _IDS[0]
        self.fn, self.nout, self.ins = fn, nout, ins
        self.outs = ()
        self.error = None
        self.read = False
        self.state = 'queued'
        self.started = self.finished = None

    async def run(self):
        self.state = 'running'
        self.started = time.time()
        try:
            r = await _call(self.fn, self.nout, self.ins)
            self.outs = tuple(r)
        except MError as e:
            self.error = e
        self.finished = time.time()
        self.state = 'finished'

    def props(self):
        return {'ID': float(self.id), 'Function': self.fn, 'InputArguments': Cell.of_list(list(self.ins)),
                'NumOutputArguments': float(self.nout), 'OutputArguments': Cell.of_list(list(self.outs)),
                'State': Char.of(self.state), 'Read': self.read,
                'Error': R.as_mexception(self.error) if self.error is not None and hasattr(R, 'as_mexception') else (Char.of(self.error.message) if self.error else EMPTY()),
                'CreateDateTime': EMPTY(), 'RunningDuration': EMPTY()}

    def getprop(self, name):
        d = self.props()
        for k, v in d.items():
            if k.lower() == name.lower():
                return v
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'FevalFuture'.")

    def propnames(self):
        return list(self.props())

    def display_lines(self):
        return ['  FevalFuture with properties:', '', f'                   ID: {self.id}', f'             Function: {_fname(self.fn)}',
                f'               State: {self.state}' + (' (Error)' if self.error else ''), f'                 Read: {"true" if self.read else "false"}',
                f'   NumOutputArguments: {self.nout}']


def _fname(f):
    if isinstance(f, FH):
        return f.text() if hasattr(f, 'text') else '@function'
    return py_str(f) if is_str(f) else '?'


async def _call(fn, nout, ins):
    if is_str(fn):
        fn = R._builtin('str2func', fn)
    if not isinstance(fn, FH):
        raise err('MATLAB:parfeval:function', 'parfeval takes a function handle (or name).', 'parfeval')
    r = await fn.acall(nout, *ins)
    if nout == 0:
        return ()
    if nout == 1:
        return (r,)
    return tuple(r)[:nout]


class FutureArray(Obj):
    """Several futures, as afterEach and the concatenation of futures make them."""
    cls = 'parallel.FevalFuture'
    is_handle = True

    def __init__(self, items):
        self.items = list(items)

    @property
    def shape(self):
        return (len(self.items), 1)

    def display_lines(self):
        lines = [f'  {len(self.items)}x1 FevalFuture array:', '', '         ID              State  FinishDateTime  Function  Error']
        for i, f in enumerate(self.items):
            lines.append(f'   {i + 1:>3} {f.id:>6}  {f.state:>17}  {"":14}  {_fname(f.fn)}  {"Error" if f.error else ""}')
        return lines

    def getprop(self, name):
        vals = [f.getprop(name) for f in self.items]
        if all(isinstance(v, (float, bool)) for v in vals):
            return np.array([[float(v) for v in vals]]).T
        return Cell.of_list(vals, (len(vals), 1))


def _futures(v, fn):
    if isinstance(v, Future):
        return [v]
    if isinstance(v, FutureArray):
        return v.items
    from ..graphics_base import HArr
    if isinstance(v, (Cell, HArr)):
        items = [x for x in v.a.reshape(-1, order='F')]
        if all(isinstance(x, Future) for x in items):
            return items
    raise err(f'MATLAB:{fn}:future', f'{fn} takes futures (from parfeval).', fn)


def _join(op, *xs):
    if op in ('hcat', 'vcat'):
        items = []
        for x in xs:
            if numel(x) == 0 and not isinstance(x, (Future, FutureArray)):
                continue
            items += _futures(x, 'concatenation')
        return FutureArray(items)
    if op in ('eq', 'ne'):
        a, b = xs
        same = a is b
        return same if op == 'eq' else not same
    raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for futures.")


def _register_ops():
    from ..ops import OBJ_OPS
    OBJ_OPS[Future] = _join
    OBJ_OPS[FutureArray] = _join


_register_ops()


class BackgroundPool(Obj):
    cls = 'parallel.BackgroundPool'
    is_handle = True

    def getprop(self, name):
        if name.lower() == 'numworkers':
            return 1.0
        if name.lower() == 'busy':
            return False
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'BackgroundPool'.")

    def display_lines(self):
        return ['  BackgroundPool with properties:', '', '    NumWorkers: 1', '          Busy: false']


_BG = []


@bi('backgroundPool')
def backgroundPool(nargout, *args):
    """pool = backgroundPool: the pool parfeval runs in (here, the engine itself)."""
    if not _BG:
        _BG.append(BackgroundPool())
    return _BG[0]


@bi('parfeval', aw=True)
async def parfeval(nargout, *args):
    """F = parfeval(fcn, nout, X1, ..., Xm), parfeval(pool, fcn, nout, ...): fcn run with the inputs for nout outputs; F holds them (fetchOutputs)."""
    a = list(args)
    if a and (isinstance(a[0], BackgroundPool) or type(a[0]).__name__ == 'PoolObj'):
        a.pop(0)
    if len(a) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'parfeval')
    fn, nout = a[0], int(num(a[1]))
    f = Future(fn, nout, a[2:])
    await f.run()
    return f


@bi('parfevalOnAll', aw=True)
async def parfevalOnAll(nargout, *args):
    """F = parfevalOnAll(fcn, nout, X1, ...): fcn run once for each worker (here once) for nout outputs."""
    return await parfeval(nargout, *args)


def _outs(fs, uniform=True):
    for f in fs:
        if f.error is not None:
            raise MError('parallel:fevalqueue:ExecutionErrors', f'One or more futures resulted in an error: {f.error.message}')
        f.read = True
    if not fs:
        return ()
    nout = fs[0].nout
    if len(fs) == 1:
        return fs[0].outs
    from ..ops import vcat
    res = []
    for k in range(nout):
        vals = [f.outs[k] for f in fs]
        if uniform:
            try:
                res.append(vcat(vals))
            except MError:
                raise MError('parallel:future:FetchOutputsUniformOutput', 'The outputs cannot be put together: use fetchOutputs(F, "UniformOutput", false).')
        else:
            res.append(Cell.of_list(vals, (len(vals), 1)))
    return tuple(res)


@bi('fetchOutputs', nout=99)
def fetchOutputs(nargout, *args):
    """[B1, ..., Bn] = fetchOutputs(F), fetchOutputs(F, 'UniformOutput', false): the outputs of futures (each output put together down the futures)."""
    nargchk(args, 1, 3, 'fetchOutputs')
    fs = _futures(args[0], 'fetchOutputs')
    uniform = not (len(args) > 2 and not bool(num(args[2])))
    r = _outs(fs, uniform)
    if nargout <= 1:
        return r[0] if r else None
    if nargout > len(r):
        raise err('MATLAB:maxlhs', 'Too many output arguments.', 'fetchOutputs')
    return r[:nargout]


@bi('fetchNext', nout=99)
def fetchNext(nargout, *args):
    """[idx, B1, ..., Bn] = fetchNext(F): the next future not yet read, its place in F and its outputs."""
    nargchk(args, 1, 2, 'fetchNext')
    fs = _futures(args[0], 'fetchNext')
    for i, f in enumerate(fs):
        if not f.read:
            if f.error is not None:
                f.read = True
                raise MError('parallel:fevalqueue:ExecutionErrors', f'The future resulted in an error: {f.error.message}')
            f.read = True
            return (float(i + 1),) + tuple(f.outs[:max(nargout - 1, 0)]) if nargout > 1 else float(i + 1)
    raise err('parallel:fevalqueue:NoMoreResults', 'All the futures have been read.', 'fetchNext')


@bi('afterEach', aw=True)
async def afterEach(nargout, *args):
    """F2 = afterEach(F, fcn, nout): fcn run on the outputs of each future in F (in order), each run a future of F2."""
    nargchk(args, 3, 5, 'afterEach')
    fs = _futures(args[0], 'afterEach')
    fn, nout = args[1], int(num(args[2]))
    res = []
    for f in fs:
        g = Future(fn, nout, list(f.outs))
        if f.error is not None:
            g.error = f.error
            g.state = 'finished'
        else:
            await g.run()
        res.append(g)
    return res[0] if len(res) == 1 else FutureArray(res)


@bi('afterAll', aw=True)
async def afterAll(nargout, *args):
    """F2 = afterAll(F, fcn, nout): fcn run once on the outputs of all the futures in F, each output put together."""
    nargchk(args, 3, 5, 'afterAll')
    fs = _futures(args[0], 'afterAll')
    ins = list(_outs(fs, True))
    g = Future(args[1], int(num(args[2])), ins)
    await g.run()
    return g


def _wrap(name, test, handler):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f


def _is_future(v):
    if isinstance(v, (Future, FutureArray)):
        return True
    from ..graphics_base import HArr
    return isinstance(v, (HArr, Cell)) and v.a.size > 0 and all(isinstance(x, Future) for x in v.a.reshape(-1))


_wrap('wait', _is_future, lambda nargout, F, *rest: True if nargout else None)


@bi('cancel')
def cancel(nargout, *args):
    """cancel(F): futures stopped (here they have already finished)."""
    nargchk(args, 1, 1, 'cancel')
    _futures(args[0], 'cancel')
    return None


# ---- memoize ------------------------------------------------------------------------------------------------------------------

class Memoized(FH, Obj):
    """Called as a function handle is (mf(x)); its properties read and set as an object's."""
    cls = 'matlab.lang.MemoizedFunction'
    is_handle = True

    def text(self):
        return _fname(self.fn)

    async def acall(self, nargout, *args):
        return await self.call(nargout, list(args))

    def scall(self, nargout, *args):
        return R.run_sync(self.call(nargout, list(args)))

    def __init__(self, fn):
        self.fn = fn
        self.cache = {}
        self.order = []
        self.size = 10
        self.enabled = True
        self.hits = self.misses = 0

    def getprop(self, name):
        n = name.lower()
        if n == 'function':
            return self.fn
        if n == 'enabled':
            return self.enabled
        if n == 'cachesize':
            return float(self.size)
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'MemoizedFunction'.")

    def setprop(self, name, value):
        n = name.lower()
        if n == 'enabled':
            self.enabled = bool(num(value))
            return
        if n == 'cachesize':
            self.size = max(int(num(value)), 1)
            while len(self.order) > self.size:
                self.cache.pop(self.order.pop(0), None)
            return
        raise MError('MATLAB:class:SetProhibited', f"The property '{name}' of MemoizedFunction cannot be set.")

    def propnames(self):
        return ['Function', 'Enabled', 'CacheSize']

    def display_lines(self):
        return ['  MemoizedFunction with properties:', '', f'     Function: {_fname(self.fn)}', f'      Enabled: {"true" if self.enabled else "false"}',
                f'    CacheSize: {self.size}']

    async def call(self, nargout, args):
        if not self.enabled:
            return await self.fn.acall(nargout, *args)
        key = (nargout, _key(args))
        if key in self.cache:
            self.hits += 1
            self.order.remove(key)
            self.order.append(key)
            return self.cache[key]
        self.misses += 1
        r = await self.fn.acall(nargout, *args)
        self.cache[key] = r
        self.order.append(key)
        while len(self.order) > self.size:
            self.cache.pop(self.order.pop(0), None)
        return r


def _key(args):
    """A key for the inputs: their classes, sizes and bytes."""
    parts = []
    for a in args:
        try:
            from .parallel import dumps
            parts.append(dumps(a))
        except Exception:
            parts.append(repr(type(a)) + str(id(a)))
    return tuple(parts)


_MEMO = {}


@bi('memoize')
def memoize(nargout, *args):
    """mf = memoize(fh): a function that keeps its results for inputs it has had (the last 10 unless CacheSize says), calling fh only for new ones."""
    nargchk(args, 1, 1, 'memoize')
    fh = args[0]
    if not isinstance(fh, FH):
        raise err('MATLAB:memoize:handle', 'memoize takes a function handle.', 'memoize')
    key = _fname(fh)
    if key in _MEMO and not key.startswith('@('):
        return _MEMO[key]
    m = Memoized(fh)
    if not key.startswith('@('):
        _MEMO[key] = m
    return m


@bi('clearAllMemoizedCaches')
def clearAllMemoizedCaches(nargout, *args):
    """clearAllMemoizedCaches: every memoized function's results forgotten."""
    for m in _MEMO.values():
        m.cache.clear()
        m.order.clear()
    return None


@bi('stats')
def memo_stats(nargout, *args):
    """s = stats(mf): how often a memoized function was called and found its result kept (Cache.TotalHits, TotalMisses)."""
    nargchk(args, 1, 1, 'stats')
    m = args[0]
    if not isinstance(m, Memoized):
        raise err('MATLAB:stats:memo', 'stats takes a memoized function (from memoize).', 'stats')
    return Struct.scalar({'Cache': Struct.scalar({'TotalHits': float(m.hits), 'TotalMisses': float(m.misses), 'Size': float(len(m.cache))})})


def _clear_cache(nargout, m, *rest):
    m.cache.clear()
    m.order.clear()
    return None


_wrap('clearCache', lambda v: isinstance(v, Memoized), _clear_cache)
if 'clearCache' not in REG:
    @bi('clearCache')
    def clearCache(nargout, *args):
        """clearCache(mf): a memoized function's kept results forgotten."""
        nargchk(args, 1, 1, 'clearCache')
        if not isinstance(args[0], Memoized):
            raise err('MATLAB:clearCache:memo', 'clearCache takes a memoized function.', 'clearCache')
        return _clear_cache(0, args[0])


# ---- timeit -----------------------------------------------------------------------------------------------------------------------

@bi('timeit', aw=True)
async def timeit(nargout, *args):
    """t = timeit(f), timeit(f, numOutputs): the typical time (s) f takes, the median of several runs after a warm-up."""
    nargchk(args, 1, 2, 'timeit')
    f = args[0]
    if not isinstance(f, FH):
        raise err('MATLAB:timeit:handle', 'timeit takes a function handle of no inputs.', 'timeit')
    nout = int(num(args[1])) if len(args) > 1 else 1
    try:
        t0 = time.perf_counter()
        await f.acall(nout)
        first = time.perf_counter() - t0
    except MError as e:
        if nout == 1 and 'Too many output' in e.message:
            nout = 0
            t0 = time.perf_counter()
            await f.acall(0)
            first = time.perf_counter() - t0
        else:
            raise
    reps = int(min(max(0.2 / max(first, 1e-6), 3), 1000))
    times = []
    for _ in range(min(reps, 11)):
        k = max(1, reps // 11)
        t0 = time.perf_counter()
        for _ in range(k):
            await f.acall(nout)
        times.append((time.perf_counter() - t0) / k)
    return float(np.median(times))


# ---- preferences --------------------------------------------------------------------------------------------------------------------

def _pref_file():
    # the page's home folder; outside the page, the current folder (never this computer's own home)
    home = R.STATE.get('home') or R.STATE['cwd']
    return os.path.join(home, '.pylab-prefs.json')


def _load():
    try:
        with open(_pref_file(), encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _save(d):
    try:
        with open(_pref_file(), 'w', encoding='utf-8') as f:
            json.dump(d, f)
    except OSError as e:
        raise err('MATLAB:setpref:write', f'The preferences cannot be saved: {e}.', 'setpref')


def _enc(v):
    from .parallel import dumps
    import base64
    return base64.b64encode(dumps(v)).decode('ascii')


def _dec(s):
    from .parallel import loads
    import base64
    return loads(base64.b64decode(s))


def _names(v):
    if isinstance(v, Cell):
        return [py_str(x) for x in v.a.reshape(-1, order='F')]
    return [py_str(v)]


@bi('setpref')
def setpref(nargout, *args):
    """setpref(group, pref, value): a preference kept from one session to the next (in the home folder); several prefs with a cell of names and of values."""
    nargchk(args, 3, 3, 'setpref')
    d = _load()
    g = py_str(args[0])
    names = _names(args[1])
    vals = list(args[2].a.reshape(-1, order='F')) if isinstance(args[1], Cell) and isinstance(args[2], Cell) else [args[2]]
    grp = d.setdefault(g, {})
    for n, v in zip(names, vals):
        grp[n] = _enc(v)
    _save(d)
    return None


@bi('addpref')
def addpref(nargout, *args):
    """addpref(group, pref, value): a preference added (an error when it is there already)."""
    nargchk(args, 3, 3, 'addpref')
    d = _load()
    g = py_str(args[0])
    for n in _names(args[1]):
        if n in d.get(g, {}):
            raise err('MATLAB:addpref:exists', f"The preference '{g}.{n}' is there already: use setpref.", 'addpref')
    return setpref(nargout, *args)


@bi('getpref')
def getpref(nargout, *args):
    """value = getpref(group, pref), getpref(group, pref, default), s = getpref(group), s = getpref: preferences kept."""
    nargchk(args, 0, 3, 'getpref')
    d = _load()
    if not args:
        return Struct.scalar({g: Struct.scalar({n: _dec(v) for n, v in grp.items()}) for g, grp in d.items()})
    g = py_str(args[0])
    grp = d.get(g)
    if len(args) == 1:
        if grp is None:
            raise err('MATLAB:getpref:group', f"There is no preference group '{g}'.", 'getpref')
        return Struct.scalar({n: _dec(v) for n, v in grp.items()})
    names = _names(args[1])
    vals = []
    for i, n in enumerate(names):
        if grp is not None and n in grp:
            vals.append(_dec(grp[n]))
        elif len(args) > 2:
            dv = args[2].a.reshape(-1, order='F')[i] if isinstance(args[1], Cell) and isinstance(args[2], Cell) else args[2]
            vals.append(dv)
            grp = d.setdefault(g, {})
            grp[n] = _enc(dv)
            _save(d)
        else:
            raise err('MATLAB:getpref:pref', f"There is no preference '{g}.{n}'.", 'getpref')
    return vals[0] if not isinstance(args[1], Cell) else Cell.of_list(vals)


@bi('ispref')
def ispref(nargout, *args):
    """tf = ispref(group), ispref(group, pref): whether a preference (group) is there."""
    nargchk(args, 1, 2, 'ispref')
    d = _load()
    g = py_str(args[0])
    if len(args) == 1:
        return g in d
    names = _names(args[1])
    vals = [g in d and n in d[g] for n in names]
    return vals[0] if not isinstance(args[1], Cell) else out(np.array([vals], bool))


@bi('rmpref')
def rmpref(nargout, *args):
    """rmpref(group), rmpref(group, pref): preferences taken away."""
    nargchk(args, 1, 2, 'rmpref')
    d = _load()
    g = py_str(args[0])
    if g not in d:
        raise err('MATLAB:rmpref:group', f"There is no preference group '{g}'.", 'rmpref')
    if len(args) == 1:
        del d[g]
    else:
        for n in _names(args[1]):
            if n not in d[g]:
                raise err('MATLAB:rmpref:pref', f"There is no preference '{g}.{n}'.", 'rmpref')
            del d[g][n]
    _save(d)
    return None
