"""Missing data in the value classes, and the missing value.

ismissing, rmmissing, fillmissing and standardizeMissing of datetimes
(NaT), durations and calendarDurations (NaN), categoricals (undefined) and
tables (each variable by its own kind of missing), on top of datatools.py's
numeric and text versions: the elements' numbers (seconds, codes) go through
those, or, for the methods that move elements ('previous', 'next',
'nearest') and for rmmissing, their positions do, and the elements follow.

missing is a value that becomes the missing value of whatever it meets: NaN
in a double array, <missing> in a string array, NaT, undefined; in
arithmetic, NaN."""
import numpy as np

from . import bi
from ._util import err, nargchk, out, opt_str, is_str
from ..values import MError, Char, Cell, Str, Struct, numel, shape_of, class_of, text_list
from ..vobj import VObj
from .. import runtime as R


# ---- the missing value ---------------------------------------------------------------------------------

class Missing(VObj):
    """missing: as many elements as its shape, each the missing value of what it becomes."""
    cls = 'missing'
    is_missing = True
    ARRAYS = ('a',)
    FILLS = {'a': np.nan}
    FUNCS = {}

    def __init__(self, a):
        self.a = np.asarray(a, float).reshape(np.shape(a) if np.ndim(a) >= 2 else (1, -1))

    def elem_strings(self):
        return np.full(self.a.shape, '<missing>', object)

    def coerce(self, v):
        if isinstance(v, Missing):
            return v
        raise MError('MATLAB:invalidConversion', f'Unable to convert a value of class {class_of(v)} to missing.')

    def like(self, other):
        """This value as the missing value of other's class (its own shape)."""
        sh = self.a.shape
        if isinstance(other, VObj) and not isinstance(other, Missing):
            return other.empty_like(sh)
        if isinstance(other, Str):
            return Str(np.full(sh, None, object))
        if isinstance(other, (Char, Cell, Struct)):
            raise MError('MATLAB:invalidConversion', f'Conversion to {class_of(other)} from missing is not possible.')
        a = np.asarray(other)
        if a.dtype == np.float32:
            return np.full(sh, np.nan, np.float32)
        if a.dtype.kind in 'iub':
            raise MError('MATLAB:invalidConversion', f'Conversion to {class_of(other)} from missing is not possible.')
        return np.full(sh, np.nan, complex if a.dtype.kind == 'c' else float)

    def binop(self, op, a, b):
        from .. import ops
        a2 = a.like(b) if isinstance(a, Missing) and not isinstance(b, Missing) else (np.full(a.a.shape, np.nan) if isinstance(a, Missing) else a)
        b2 = b.like(a) if isinstance(b, Missing) and not isinstance(a, Missing) else (np.full(b.a.shape, np.nan) if isinstance(b, Missing) else b)
        if isinstance(a2, VObj) or isinstance(b2, VObj):
            return (a2 if isinstance(a2, VObj) else b2).binop(op, a2, b2)
        name = _OPS.get(op)
        if name is None:
            raise MError('MATLAB:UndefinedFunction', f"Operator '{op}' is not supported for missing.")
        return R.BUILTINS[name].fn(1, a2, b2)

    def unop(self, op):
        if op in ('-', '+'):
            return self
        return VObj.unop(self, op)

    @classmethod
    def concat(cls, axis, vals):
        """[missing, x]: the values of x's class, missing where missing was."""
        from .. import ops
        other = next((v for v in vals if not isinstance(v, Missing) and not (type(v) is np.ndarray and v.size == 0)), None)
        if other is None:
            return VObj.concat.__func__(cls, axis, vals)
        return ops.cat(axis, [v.like(other) if isinstance(v, Missing) else v for v in vals])


_OPS = {'+': 'plus', '-': 'minus', '.*': 'times', './': 'rdivide', '.^': 'power', '*': 'mtimes', '/': 'mrdivide',
        '\\': 'mldivide', '^': 'mpower', '==': 'eq', '~=': 'ne', '<': 'lt', '<=': 'le', '>': 'gt', '>=': 'ge',
        '&': 'and', '|': 'or'}


@bi('missing', arr=False)
def missing_(nargout, *args):
    """missing: the missing value, which becomes NaN, <missing>, NaT or undefined where it is put."""
    nargchk(args, 0, 0, 'missing')
    return Missing(np.full((1, 1), np.nan))


def _missing_to(fn_name, make):
    def fn(nargout, args):
        m = args[0]
        if not isinstance(m, Missing):
            return NotImplemented
        if len(args) > 1:
            return NotImplemented
        return make(m.a.shape)
    return fn


def _setup_missing():
    from .timetypes import DateTime, Duration, CalDuration
    from .categoricals import Categorical
    nan = lambda sh: np.full(sh, np.nan)  # noqa: E731
    Missing.FUNCS.update({
        'double': _missing_to('double', lambda sh: out(nan(sh))),
        'single': _missing_to('single', lambda sh: out(nan(sh).astype(np.float32))),
        'string': _missing_to('string', lambda sh: Str(np.full(sh, None, object))),
        'datetime': _missing_to('datetime', lambda sh: DateTime(nan(sh))),
        'duration': _missing_to('duration', lambda sh: Duration(nan(sh))),
        'calendarDuration': _missing_to('calendarDuration', lambda sh: CalDuration(nan(sh), nan(sh), nan(sh))),
        'categorical': _missing_to('categorical', lambda sh: Categorical(np.zeros(sh), [])),
        'ismissing': _missing_to('ismissing', lambda sh: out(np.ones(sh, bool))),
    })


# ---- the value classes' missing elements -----------------------------------------------------------------

def _mask(v):
    """Where a value's elements are missing (a logical array of its shape)."""
    from .timetypes import CalDuration
    from .categoricals import Categorical
    from .tables import Table
    if isinstance(v, Missing):
        return np.ones(v.a.shape, bool)
    if isinstance(v, Categorical):
        return np.asarray(v.a) == 0
    if isinstance(v, CalDuration):
        return np.isnan(v.mo) | np.isnan(v.d) | np.isnan(v.t)
    if isinstance(v, Table):
        parts = [_var_mask(x, v.n) for x in v.vars]
        return np.concatenate(parts, axis=1) if parts else np.zeros((v.n, 0), bool)
    if isinstance(v, VObj):
        return np.isnan(np.asarray(v.a, float))
    r = R.BUILTINS['ismissing'].fn(1, v)
    return np.asarray(r, bool).reshape(shape_of(v))


def _var_mask(x, n):
    """A table variable's missing elements, n rows; variables of kinds with no missing value have none."""
    try:
        m = _mask(x)
    except MError:
        m = np.zeros(shape_of(x), bool)
    return m.reshape(n, -1) if m.size or n == 0 else np.zeros((n, 0), bool)


def _positions(v, miss):
    """The elements' positions (column-major) as numbers, NaN where missing."""
    pos = np.arange(miss.size, dtype=float).reshape(miss.shape, order='F')
    pos[miss] = np.nan
    return pos


def _take(v, pos):
    """The elements of v at the positions (an array of them)."""
    pos = np.asarray(pos, float)
    idx = pos.astype(np.intp)
    return v.mapped(lambda a: a.reshape(-1, order='F')[idx.reshape(-1, order='F')].reshape(idx.shape, order='F'))


def _ismissing(nargout, args):
    v = args[0]
    if not isinstance(v, VObj):
        return NotImplemented
    if len(args) > 1:
        raise err('MATLAB:ismissing:Indicators', 'Indicators of missing values are not supported for this class here.', 'ismissing')
    return out(_mask(v))


def _rmmissing(nargout, args):
    from .tables import Table, _split_opts, _tab
    v = args[0]
    if not isinstance(v, VObj):
        return NotImplemented
    if isinstance(v, Table):
        _, opts, _ = _split_opts(list(args[1:]), ('minnummissing', 'datavariables'))
        cols = v.var_index(opts['datavariables']) if 'datavariables' in opts else list(range(len(v.vars)))
        k = int(np.asarray(opts['minnummissing']).reshape(-1)[0]) if 'minnummissing' in opts else 1
        m = np.concatenate([_var_mask(v.vars[c], v.n) for c in cols], axis=1) if cols else np.zeros((v.n, 0), bool)
        drop = m.sum(axis=1) >= k if m.shape[1] else np.zeros(v.n, bool)
        r = v.sub_rows(np.flatnonzero(~drop))
        return (r, out(drop.reshape(-1, 1))) if nargout > 1 else r
    miss = _mask(v)
    res = R.BUILTINS['rmmissing'].fn(max(nargout, 1), out(_positions(v, miss)), *args[1:])
    pos, tf = (res if isinstance(res, tuple) else (res, None))
    r = _take(v, np.asarray(pos, float).reshape(shape_of(pos)))
    return (r, tf) if nargout > 1 else r


def _seconds_like(v, c):
    """A fill value for v as v's numbers: a datetime or duration in seconds."""
    from .timetypes import DateTime, Duration
    if isinstance(v, (DateTime, Duration)):
        cv = v.coerce(c) if isinstance(c, VObj) or is_str(c) else None
        if cv is None:
            raise err('MATLAB:fillmissing:InvalidConstant', f'The fill value must be a {v.cls}.', 'fillmissing')
        return out(np.asarray(cv.a, float))
    return c


def _fillmissing(nargout, args):
    from .timetypes import DateTime, Duration
    from .categoricals import Categorical
    from .tables import Table
    v = args[0]
    if not isinstance(v, VObj):
        return NotImplemented
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'fillmissing')
    method = (opt_str(args[1]) or '').lower()
    if isinstance(v, Table):
        return _fill_table(nargout, v, args[1:])
    if method in ('previous', 'next', 'nearest'):
        miss = _mask(v)
        rest = list(args[2:])
        res = R.BUILTINS['fillmissing'].fn(2, out(_positions(v, miss)), *([args[1]] + rest))
        pos, tf = res
        pos = np.asarray(pos, float).reshape(miss.shape)
        still = np.isnan(pos)
        r = _take(v, np.where(still, 0, pos))
        if still.any():
            r = _blank(r, still)
        return (r, tf) if nargout > 1 else r
    if method == 'constant':
        if len(args) < 3:
            raise err('MATLAB:fillmissing:ConstantMissing', "'constant' needs a value.", 'fillmissing')
        miss = _mask(v)
        c = v.coerce(args[2]) if not isinstance(args[2], Missing) else v.empty_like(miss.shape)
        if numel(c) != 1:
            raise err('MATLAB:fillmissing:SizeConstant', 'Give one fill value.', 'fillmissing')
        merged = v.merged(c) if hasattr(v, 'merged') else v
        c = merged.coerce(args[2]) if not isinstance(args[2], Missing) else c
        fills = {k: np.where(miss, np.asarray(getattr(c, k)).reshape(-1)[0], getattr(merged, k)) for k in v.ARRAYS}
        r = merged.with_arrays(**fills)
        return (r, out(miss)) if nargout > 1 else r
    if isinstance(v, (DateTime, Duration)):
        rest = [_seconds_like(v, x) if isinstance(x, VObj) else x for x in args[2:]]
        res = R.BUILTINS['fillmissing'].fn(2, out(np.asarray(v.a, float)), args[1], *rest)
        a, tf = res
        r = v.with_arrays(a=np.asarray(a, float).reshape(v.a.shape))
        return (r, tf) if nargout > 1 else r
    if isinstance(v, Categorical):
        raise err('MATLAB:fillmissing:InvalidMethodForCategorical', "A categorical array is filled by 'constant', 'previous', 'next' or 'nearest'.", 'fillmissing')
    raise err('MATLAB:fillmissing:InvalidMethod', f"'{method}' does not fill a {v.cls} array.", 'fillmissing')


def _blank(v, where):
    """v with the elements at where made missing."""
    return v.with_arrays(**{k: np.where(where, v.FILLS[k], getattr(v, k)) for k in v.ARRAYS})


def _fill_table(nargout, T, rest):
    from .tables import _split_opts, _var_value
    from ..values import share
    data, opts, _ = _split_opts(list(rest), ('datavariables', 'endvalues', 'maxgap'))
    cols = T.var_index(opts['datavariables']) if 'datavariables' in opts else list(range(len(T.vars)))
    method = (opt_str(data[0]) or '').lower()
    extra = list(data[1:])
    per_var = None
    if method == 'constant':
        if not extra:
            raise err('MATLAB:fillmissing:ConstantMissing', "'constant' needs a value.", 'fillmissing')
        c = extra.pop(0)
        if isinstance(c, Cell) and c.a.size == len(cols) and len(cols) > 1:
            per_var = list(c.a.reshape(-1, order='F'))
        else:
            per_var = [c] * len(cols)
    named = []
    for k in ('endvalues', 'maxgap'):
        if k in opts:
            named += [Char.of({'endvalues': 'EndValues', 'maxgap': 'MaxGap'}[k]), opts[k]]
    R2 = T.value_copy()
    tfs = []
    for j, ci in enumerate(cols):
        x = T.vars[ci]
        call = [x, data[0]] + ([per_var[j]] if per_var is not None else []) + extra + named
        try:
            f, tf = R.BUILTINS['fillmissing'].fn(2, *call)
        except MError as e:
            raise err(e.identifier, f"Variable '{T.names[ci]}': {e.message}", 'fillmissing')
        R2.vars[ci] = share(_var_value(f))
        tfs.append(np.asarray(tf, bool).reshape(T.n, -1))
    if nargout > 1:
        full = []
        for ci in range(len(T.vars)):
            full.append(tfs[cols.index(ci)] if ci in cols else np.zeros((T.n, shape_of(T.vars[ci])[1] if len(shape_of(T.vars[ci])) > 1 else 1), bool))
        return R2, out(np.concatenate(full, axis=1) if full else np.zeros((T.n, 0), bool))
    return R2


def _standardize(nargout, args):
    from .tables import Table, _split_opts
    from .categoricals import Categorical
    from ..values import share
    v = args[0]
    if not isinstance(v, VObj):
        return NotImplemented
    if isinstance(v, Table):
        data, opts, _ = _split_opts(list(args[1:]), ('datavariables',))
        if not data:
            raise err('MATLAB:minrhs', 'Not enough input arguments.', 'standardizeMissing')
        cols = v.var_index(opts['datavariables']) if 'datavariables' in opts else list(range(len(v.vars)))
        T = v.value_copy()
        for ci in cols:
            try:
                T.vars[ci] = share(R.BUILTINS['standardizeMissing'].fn(1, T.vars[ci], data[0]))
            except MError:
                pass        # an indicator of another kind than the variable leaves it alone
        return T
    if len(args) != 2:
        raise err('MATLAB:standardizeMissing:Inputs', 'Give the array and the indicators.', 'standardizeMissing')
    ind = args[1]
    if isinstance(v, Categorical):
        names = set(text_list(ind)) if is_str(ind) or isinstance(ind, (Cell, Str)) else set()
        drop = [i + 1 for i, c in enumerate(v.cats) if c in names]
        a = np.where(np.isin(v.a, drop), 0.0, v.a)
        return v.with_arrays(a=a)
    try:
        iv = v.coerce(ind)
    except MError:
        return v
    keys = np.asarray(iv.key(), float).reshape(-1)
    hit = np.isin(np.asarray(v.key(), float), keys[~np.isnan(keys)])
    return _blank(v, hit)


def _setup_classes():
    from .timetypes import DateTime, Duration, CalDuration
    from .categoricals import Categorical
    from .tables import Table
    for c in (DateTime, Duration, CalDuration, Categorical, Table):
        c.FUNCS.update({'ismissing': _ismissing, 'rmmissing': _rmmissing, 'fillmissing': _fillmissing, 'standardizeMissing': _standardize})


def classes():
    _setup_missing()
    _setup_classes()
    return (Missing,)
