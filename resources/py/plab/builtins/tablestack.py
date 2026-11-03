"""Tables between their wide and long forms: stack and unstack."""
import numpy as np

from . import bi as _register
from ._util import err, nargchk, opt_str, is_str
from ..values import MError, Char, Cell, Str, FH, numel, py_str
from .. import runtime as R
from .tables import Table, TimeTable, _take_rows, _cat_rows, _missing_like, _row_keys, _texts, _valid_name, _call


def bi(*names, **kw):
    def deco(f):
        async def g(*a):
            try:
                return await f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError) as e:
                raise err(f'MATLAB:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, aw=True, arr=False, **kw)(g)
    return deco


def _opts(args, names):
    low = {n.lower(): n for n in names}
    got, rest = {}, []
    i = 0
    while i < len(args):
        s = opt_str(args[i])
        if s is not None and s.lower() in low and i + 1 < len(args):
            got[low[s.lower()]] = args[i + 1]
            i += 2
            continue
        rest.append(args[i])
        i += 1
    return got, rest


def _tab(v, fn):
    if not isinstance(v, Table):
        raise err(f'MATLAB:{fn}:table', f'{fn} takes a table or timetable.', fn)
    return v


def _new(T, vars_, names, times_rows=None, n=None):
    """A table (or a timetable with the rows' times taken at times_rows) of the variables."""
    if isinstance(T, TimeTable) and times_rows is not None:
        return TimeTable(vars_, names, _take_rows(T.times, list(times_rows)))
    return Table(vars_, names, None, n)


@bi('stack')
async def stack(nargout, *args):
    """S = stack(T, vars, 'NewDataVariableName', name, 'IndexVariableName', name, 'ConstantVariables', vars): the variables vars stacked into one, a row for each of them in each row of T."""
    nargchk(args, 2, 8, 'stack')
    T = _tab(args[0], 'stack')
    opts, _ = _opts(list(args[2:]), ('NewDataVariableName', 'IndexVariableName', 'ConstantVariables'))
    dv = T.var_index(args[1])
    if not dv:
        raise err('MATLAB:stack:vars', 'Give the variables to stack.', 'stack')
    cv = T.var_index(opts['ConstantVariables']) if 'ConstantVariables' in opts else [k for k in range(len(T.vars)) if k not in dv]
    cv = [k for k in cv if k not in dv]
    data_name = py_str(opts['NewDataVariableName']) if 'NewDataVariableName' in opts else '_'.join(T.names[k] for k in dv)
    index_name = py_str(opts['IndexVariableName']) if 'IndexVariableName' in opts else data_name + '_Indicator'
    n, k = T.n, len(dv)
    rep = list(np.repeat(np.arange(n), k))
    from .categoricals import Categorical
    ind = Categorical(np.tile(np.arange(1, k + 1), n).reshape(-1, 1).astype(float), [T.names[j] for j in dv])
    allv = _cat_rows([T.vars[j] for j in dv])
    perm = [int((r % k) * n + r // k) for r in range(n * k)]
    vars_ = [_take_rows(T.vars[j], rep) for j in cv] + [ind, _take_rows(allv, perm)]
    names = [T.names[j] for j in cv] + [index_name, data_name]
    return _new(T, vars_, names, rep, n * k)


def _level_texts(v, n):
    """Each row's indicator as text, and the levels in order (categories in theirs; text and numbers sorted)."""
    from .categoricals import Categorical
    if isinstance(v, Categorical):
        names = list(np.asarray(v.names(), object).reshape(-1))
        levels = [c for c in v.cats if c in set(names)]
        return names, levels
    if type(v) in (Cell, Str, Char):
        t = _texts(v, 'unstack')
        return t, sorted(set(t))
    a = np.asarray(v, float).reshape(-1)
    vals = sorted(set(a.tolist()))
    fmt = lambda x: str(int(x)) if float(x).is_integer() else repr(float(x))  # noqa: E731
    return [fmt(x) for x in a], [fmt(x) for x in vals]


def _name(s):
    if _valid_name(s):
        return s
    return py_str(R.BUILTINS['matlab.lang.makeValidName'].fn(1, Char.of(s)))


@bi('unstack')
async def unstack(nargout, *args):
    """W = unstack(S, vars, ivar, 'GroupingVariables', g, 'AggregationFunction', f, 'NewDataVariableNames', names): the variables vars spread into a variable for each value of ivar, a row for each group."""
    nargchk(args, 3, 13, 'unstack')
    S = _tab(args[0], 'unstack')
    opts, _ = _opts(list(args[3:]), ('GroupingVariables', 'ConstantVariables', 'AggregationFunction', 'NewDataVariableNames', 'VariableNamingRule'))
    dv = S.var_index(args[1])
    iv = S.var_index(args[2])
    if len(iv) != 1:
        raise err('MATLAB:unstack:ivar', 'The indicator is one variable.', 'unstack')
    iv = iv[0]
    cv = S.var_index(opts['ConstantVariables']) if 'ConstantVariables' in opts else []
    gv = S.var_index(opts['GroupingVariables']) if 'GroupingVariables' in opts else [k for k in range(len(S.vars)) if k not in dv and k != iv and k not in cv]
    texts, levels = _level_texts(S.vars[iv], S.n)
    rule = py_str(opts['VariableNamingRule']).lower() if 'VariableNamingRule' in opts else 'modify'
    if 'NewDataVariableNames' in opts:
        newnames = _texts(opts['NewDataVariableNames'], 'unstack')
        if len(newnames) != len(levels) * len(dv):
            raise err('MATLAB:unstack:names', f'Give {len(levels) * len(dv)} new variable names.', 'unstack')
    else:
        base = [lv if rule == 'preserve' else _name(lv) for lv in levels]
        newnames = base if len(dv) == 1 else [f'{S.names[d]}_{b}' for d in dv for b in base]
    # the groups: rows of the same grouping values (and the same row times), in sorted order
    keys = []
    for i in range(S.n):
        k = tuple(x for g in gv for x in _row_keys(S.vars[g], S.n)[i])
        if isinstance(S, TimeTable):
            k = tuple(_row_keys(S.times, S.n)[i]) + k
        keys.append(k)
    uniq = sorted(set(keys), key=lambda t: tuple((0, x) if not isinstance(x, str) else (1, x) for x in t))
    gid = {k: i for i, k in enumerate(uniq)}
    G = len(uniq)
    first = [None] * G
    for i, k in enumerate(keys):
        if first[gid[k]] is None:
            first[gid[k]] = i
    lev = {lv: j for j, lv in enumerate(levels)}
    agg = opts.get('AggregationFunction')
    new_vars = []
    for d in dv:
        v = S.vars[d]
        numeric = type(v) is np.ndarray and v.dtype.kind in 'fiub' or type(v) in (float, bool)
        for j in range(len(levels)):
            rows_per = [[] for _ in range(G)]
            for i in range(S.n):
                if lev.get(texts[i]) == j:
                    rows_per[gid[keys[i]]].append(i)
            cols = []
            for g in range(G):
                rs = rows_per[g]
                if not rs:
                    cols.append(_missing_like(v, 1) if not numeric else np.array([[np.nan]]))
                    continue
                part = _take_rows(v, rs)
                if isinstance(agg, FH):
                    r = await _call(agg, part)
                    cols.append(r if numel(r) == 1 else _take_rows(part, [0]))
                elif len(rs) == 1:
                    cols.append(part)
                elif numeric:
                    cols.append(np.array([[float(np.sum(np.asarray(part, float)))]]))
                else:
                    t = _texts(part, 'unstack') if type(part) in (Cell, Str, Char) else None
                    if t is not None and len(set(t)) == 1:
                        cols.append(_take_rows(part, [0]))
                    else:
                        raise err('MATLAB:unstack:multiple', f"Several values of '{S.names[d]}' fall in one group and level: give an AggregationFunction.", 'unstack')
            new_vars.append(_cat_rows(cols) if G else _take_rows(v, []))
    keep = [k for k in range(len(S.vars)) if k in gv or k in cv]
    vars_ = [_take_rows(S.vars[k], first) for k in keep] + new_vars
    names = [S.names[k] for k in keep] + list(newnames)
    return _new(S, vars_, names, first, G)
