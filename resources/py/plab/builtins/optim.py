"""Optimization on SciPy: optimoptions and its options objects; fminunc,
fmincon, fsolve, lsqnonlin, lsqcurvefit, lsqlin, lsqnonneg, linprog,
intlinprog, quadprog, fminimax and fgoalattain, with their exit flags,
output structures and Lagrange multipliers; the Display levels, output
functions and plot functions (optimplotfval and its kin).

Functions passed in are called synchronously from SciPy's loops, as in
funfun.py. Gradients not given are taken by finite differences here, so
that the function counts include them and the first-order optimality of
each iterate is known. Lagrange multipliers come from the KKT conditions
at the answer: the gradient against the gradients of the active
constraints, solved by least squares with the inequalities' multipliers
kept nonnegative (linprog's come from HiGHS).
"""
import math

import numpy as np

from . import bi
from ._util import err, darr, out, opt_str, opt_lower, num, is_str
from ..values import MError, Char, Cell, Struct, Str, FH, Obj, F64, numel, EMPTY, py_str
from .. import runtime as R

EPS = np.finfo(float).eps


def _lsq_takes_callback():
    """Whether scipy.optimize.least_squares takes a callback (SciPy 1.16 and on)."""
    import inspect
    from scipy import optimize
    return 'callback' in inspect.signature(optimize.least_squares).parameters


_LSQ_CALLBACK = _lsq_takes_callback()

# ---- options -----------------------------------------------------------------------------------------

# name: (default, kind); a text default naming numberOfVariables is worked out per problem
_COMMON = {
    'Display': ('final', 'display'), 'MaxIterations': (400, 'count'), 'MaxFunctionEvaluations': ('100*numberOfVariables', 'count'),
    'OptimalityTolerance': (1e-6, 'tol'), 'StepTolerance': (1e-6, 'tol'), 'FunctionTolerance': (1e-6, 'tol'),
    'ConstraintTolerance': (1e-6, 'tol'), 'SpecifyObjectiveGradient': (False, 'bool'), 'SpecifyConstraintGradient': (False, 'bool'),
    'FiniteDifferenceType': ('forward', ('forward', 'central')), 'FiniteDifferenceStepSize': ('sqrt(eps)', 'any'),
    'TypicalX': ('ones(numberOfVariables,1)', 'any'), 'OutputFcn': (None, 'fns'), 'PlotFcn': (None, 'fns'),
    'CheckGradients': (False, 'bool'), 'UseParallel': (False, 'bool'), 'ObjectiveLimit': (-1e20, 'num'),
    'HessianFcn': (None, 'any'), 'HessianApproximation': ('bfgs', 'any'), 'MaxTime': (math.inf, 'num'),
    'RelativeGapTolerance': (1e-4, 'tol'), 'AbsoluteGapTolerance': (0.0, 'num'), 'IntegerTolerance': (1e-5, 'tol'),
    'MaxNodes': (1e7, 'count'), 'AbsoluteMaxObjectiveCount': (0, 'count'), 'EqualityGoalCount': (0, 'count'),
    'Algorithm': (None, 'algorithm'),
}

# solver: (algorithms, the first the default; its options with their own defaults)
_SOLVERS = {
    'fminunc': (('quasi-newton', 'trust-region'),
                {'MaxIterations': 400, 'MaxFunctionEvaluations': '100*numberOfVariables', 'OptimalityTolerance': 1e-6, 'StepTolerance': 1e-6,
                 'FunctionTolerance': 1e-6, 'SpecifyObjectiveGradient': False, 'HessianFcn': None, 'ObjectiveLimit': -1e20,
                 'FiniteDifferenceType': 'forward', 'FiniteDifferenceStepSize': 'sqrt(eps)', 'TypicalX': 'ones(numberOfVariables,1)',
                 'CheckGradients': False, 'UseParallel': False}),
    'fmincon': (('interior-point', 'sqp', 'sqp-legacy', 'active-set', 'trust-region-reflective'),
                {'MaxIterations': 1000, 'MaxFunctionEvaluations': 3000, 'OptimalityTolerance': 1e-6, 'StepTolerance': 1e-10,
                 'ConstraintTolerance': 1e-6, 'SpecifyObjectiveGradient': False, 'SpecifyConstraintGradient': False, 'HessianFcn': None,
                 'HessianApproximation': 'bfgs', 'ObjectiveLimit': -1e20, 'FiniteDifferenceType': 'forward',
                 'FiniteDifferenceStepSize': 'sqrt(eps)', 'TypicalX': 'ones(numberOfVariables,1)', 'CheckGradients': False, 'UseParallel': False}),
    'fsolve': (('trust-region-dogleg', 'trust-region', 'levenberg-marquardt'),
               {'MaxIterations': 400, 'MaxFunctionEvaluations': '100*numberOfVariables', 'FunctionTolerance': 1e-6, 'OptimalityTolerance': 1e-6,
                'StepTolerance': 1e-6, 'SpecifyObjectiveGradient': False, 'FiniteDifferenceType': 'forward',
                'FiniteDifferenceStepSize': 'sqrt(eps)', 'TypicalX': 'ones(numberOfVariables,1)', 'CheckGradients': False, 'UseParallel': False}),
    'lsqnonlin': (('trust-region-reflective', 'levenberg-marquardt', 'interior-point'),
                  {'MaxIterations': 400, 'MaxFunctionEvaluations': '100*numberOfVariables', 'FunctionTolerance': 1e-6, 'OptimalityTolerance': 1e-6,
                   'StepTolerance': 1e-6, 'ConstraintTolerance': 1e-6, 'SpecifyObjectiveGradient': False, 'FiniteDifferenceType': 'forward',
                   'FiniteDifferenceStepSize': 'sqrt(eps)', 'TypicalX': 'ones(numberOfVariables,1)', 'CheckGradients': False, 'UseParallel': False}),
    'lsqlin': (('interior-point', 'trust-region-reflective', 'active-set'),
               {'MaxIterations': 200, 'OptimalityTolerance': 1e-8, 'StepTolerance': 1e-12, 'ConstraintTolerance': 1e-8}),
    'lsqnonneg': ((), {'StepTolerance': '10*eps*norm(C,1)*length(C)'}),
    'linprog': (('dual-simplex', 'interior-point', 'interior-point-legacy'),
                {'MaxIterations': '10*(numberOfEqualities+numberOfInequalities+numberOfVariables)', 'OptimalityTolerance': 1e-7,
                 'ConstraintTolerance': 1e-7, 'MaxTime': math.inf}),
    'intlinprog': (('highs',),
                   {'MaxTime': 7200.0, 'RelativeGapTolerance': 1e-4, 'AbsoluteGapTolerance': 0.0, 'IntegerTolerance': 1e-5,
                    'MaxNodes': 1e7, 'ConstraintTolerance': 1e-4}),
    'quadprog': (('interior-point-convex', 'trust-region-reflective', 'active-set'),
                 {'MaxIterations': 200, 'OptimalityTolerance': 1e-8, 'StepTolerance': 1e-12, 'ConstraintTolerance': 1e-8}),
    'fminimax': (('sqp',),
                 {'MaxIterations': 400, 'MaxFunctionEvaluations': '100*numberOfVariables', 'OptimalityTolerance': 1e-6, 'StepTolerance': 1e-6,
                  'FunctionTolerance': 1e-6, 'ConstraintTolerance': 1e-6, 'SpecifyObjectiveGradient': False,
                  'SpecifyConstraintGradient': False, 'AbsoluteMaxObjectiveCount': 0, 'FiniteDifferenceType': 'forward',
                  'FiniteDifferenceStepSize': 'sqrt(eps)', 'TypicalX': 'ones(numberOfVariables,1)', 'UseParallel': False}),
    'fgoalattain': (('sqp',),
                    {'MaxIterations': 400, 'MaxFunctionEvaluations': '100*numberOfVariables', 'OptimalityTolerance': 1e-6,
                     'StepTolerance': 1e-6, 'FunctionTolerance': 1e-6, 'ConstraintTolerance': 1e-6, 'SpecifyObjectiveGradient': False,
                     'SpecifyConstraintGradient': False, 'EqualityGoalCount': 0, 'FiniteDifferenceType': 'forward',
                     'FiniteDifferenceStepSize': 'sqrt(eps)', 'TypicalX': 'ones(numberOfVariables,1)', 'UseParallel': False}),
    'fminsearch': ((), {'MaxIterations': '200*numberOfVariables', 'MaxFunctionEvaluations': '200*numberOfVariables',
                        'FunctionTolerance': 1e-4, 'StepTolerance': 1e-4}),
    'fminbnd': ((), {'MaxIterations': 500, 'MaxFunctionEvaluations': 500, 'StepTolerance': 1e-4}),
    'fzero': ((), {'StepTolerance': 'eps'}),
}
_SOLVERS['lsqcurvefit'] = _SOLVERS['lsqnonlin']
for _s in ('fminsearch', 'fminbnd', 'fzero', 'lsqnonneg'):
    _SOLVERS[_s][1]['Display'] = 'notify'

# optimset's names
_OLD = {'maxiter': 'MaxIterations', 'maxfunevals': 'MaxFunctionEvaluations', 'tolx': 'StepTolerance', 'tolcon': 'ConstraintTolerance',
        'gradobj': 'SpecifyObjectiveGradient', 'gradconstr': 'SpecifyConstraintGradient', 'jacobian': 'SpecifyObjectiveGradient',
        'hessfcn': 'HessianFcn', 'plotfcns': 'PlotFcn', 'plotfcn': 'PlotFcn', 'outputfcn': 'OutputFcn', 'findifftype': 'FiniteDifferenceType',
        'derivativecheck': 'CheckGradients', 'typicalx': 'TypicalX', 'maxtime': 'MaxTime', 'algorithm': 'Algorithm', 'display': 'Display',
        'objectivelimit': 'ObjectiveLimit', 'maxnodes': 'MaxNodes'}
_DISPLAYS = ('off', 'none', 'iter', 'iter-detailed', 'final', 'final-detailed', 'notify', 'notify-detailed', 'testing')


def _canon(solver, name):
    """An option's name as solver knows it, from any case or optimset's name."""
    names = _SOLVERS[solver][1]
    low = name.lower()
    for k in list(names) + ['Display', 'OutputFcn', 'PlotFcn', 'Algorithm']:
        if k.lower() == low:
            return k
    k = _OLD.get(low)
    if k is not None and (k in names or k in ('Display', 'OutputFcn', 'PlotFcn', 'Algorithm')):
        return k
    if low == 'tolfun':
        return 'OptimalityTolerance' if 'OptimalityTolerance' in names else 'FunctionTolerance'
    return None


def _check_value(solver, k, v):
    kind = _COMMON[k][1]
    if kind == 'display':
        s = opt_str(v)
        if s is None or s.lower() not in _DISPLAYS:
            raise err('optimlib:options:checkfield:notADisplayType', f"Display must be one of: {', '.join(_DISPLAYS[:-1])}.", 'optimoptions')
        return Char.of(s.lower())
    if kind == 'algorithm':
        s = opt_str(v)
        algs = _SOLVERS[solver][0]
        if s is None or s.lower() not in algs:
            raise err('optimlib:options:checkfield:notAlgorithm', f"Algorithm for {solver} must be one of: {', '.join(algs)}.", 'optimoptions')
        return Char.of(s.lower())
    if kind == 'bool':
        s = opt_str(v)
        if s is not None:
            if s.lower() not in ('on', 'off', 'true', 'false'):
                raise err('optimlib:options:checkfield:notLogical', f'{k} must be true or false.', 'optimoptions')
            return s.lower() in ('on', 'true')
        return bool(num(v))
    if kind in ('tol', 'num', 'count'):
        if is_str(v):
            return Char.of(py_str(v))
        x = num(v)
        if kind != 'num' and not x >= 0:
            raise err('optimlib:options:checkfield:notNonNegReal', f'{k} must be a nonnegative number.', 'optimoptions')
        return x
    if isinstance(kind, tuple):
        s = opt_str(v)
        if s is None or s.lower() not in kind:
            raise err('optimlib:options:checkfield:notInList', f"{k} must be one of: {', '.join(kind)}.", 'optimoptions')
        return Char.of(s.lower())
    return v


def _show(v):
    if v is None:
        return '[]'
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, float):
        return f'{v:g}' if v == v and abs(v) != math.inf else ('Inf' if v > 0 else '-Inf' if v < 0 else 'NaN')
    if type(v) is Char:
        return f"'{v.str()}'"
    if isinstance(v, str):
        return f"'{v}'"
    if isinstance(v, FH):
        return '@' + v.name() if not v.text().startswith('@') else v.text()
    if type(v) is Cell:
        return '{' + ', '.join(_show(x) for x in v.a.reshape(-1, order='F')) + '}'
    if type(v) is np.ndarray:
        return '[' + ' '.join(f'{x:g}' for x in v.reshape(-1)) + ']' if v.size <= 6 else f'[{v.shape[0]}×{v.shape[1]} double]'
    return str(v)


class OptimOptions(Obj):
    """optimoptions' options for one solver: the values set, the rest
    their defaults. A value object: changing a copy leaves the original."""
    __slots__ = ('solver', 'vals')
    is_handle = False

    def __init__(self, solver, vals=None):
        self.solver = solver
        self.vals = dict(vals or {})

    @property
    def cls(self):
        return 'optim.options.' + self.solver[0].upper() + self.solver[1:]

    def value_copy(self):
        return OptimOptions(self.solver, self.vals)

    def default(self, k):
        if k == 'Algorithm':
            algs = _SOLVERS[self.solver][0]
            return Char.of(algs[0]) if algs else None
        d = _SOLVERS[self.solver][1].get(k, _COMMON[k][0] if k in _COMMON else None)
        return Char.of(d) if isinstance(d, str) else d

    def get(self, k):
        return self.vals[k] if k in self.vals else self.default(k)

    def names(self):
        base = list(_SOLVERS[self.solver][1])
        extra = [k for k in ('Algorithm', 'Display', 'OutputFcn', 'PlotFcn') if k not in base and (k != 'Algorithm' or _SOLVERS[self.solver][0])]
        return sorted(extra + base)

    def getprop(self, name):
        k = _canon(self.solver, name)
        if k is None:
            return super().getprop(name)
        v = self.get(k)
        return EMPTY() if v is None else v

    def setprop(self, name, value):
        k = _canon(self.solver, name)
        if k is None:
            raise err('optimlib:options:setProperty:invalidPropName', f"'{name}' is not an option for {self.solver}.")
        self.vals[k] = _check_value(self.solver, k, value)

    def propnames(self):
        return self.names()

    @property
    def opts(self):
        """As optimset's struct would hold them, for the solvers that read those."""
        d = {k: self.get(k) for k in self.names()}
        for old, new in (('TolX', 'StepTolerance'), ('MaxIter', 'MaxIterations'), ('MaxFunEvals', 'MaxFunctionEvaluations')):
            if new in self.vals:
                d[old] = self.vals[new]
        tol = self.vals.get('FunctionTolerance', self.vals.get('OptimalityTolerance'))
        if tol is not None:
            d['TolFun'] = tol
        return {k: (EMPTY() if v is None else v) for k, v in d.items()}

    def display_lines(self):
        lines = [f'  {self.solver} options:', '']
        algs = _SOLVERS[self.solver][0]
        if algs:
            lines.append(f"    Algorithm: '{py_str(self.get('Algorithm'))}' (of {', '.join(repr(a) for a in algs)})")
            lines.append('')
        names = self.names()
        w = max(len(k) for k in names)
        set_ = [k for k in names if k in self.vals and k != 'Algorithm']
        if set_:
            lines.append('    Set:')
            lines += [f'      {k.rjust(w)}: {_show(self.vals[k])}' for k in set_]
            lines.append('')
        lines.append('    Default:')
        lines += [f'      {k.rjust(w)}: {_show(self.default(k))}' for k in names if k not in self.vals and k != 'Algorithm']
        return lines


def _solver_name(v):
    if isinstance(v, FH):
        s = v.name()
    else:
        s = opt_str(v)
    if s is None:
        return None
    s = s.lstrip('@').strip()
    return s if s in _SOLVERS else None


@bi('optimoptions', arr=False)
def optimoptions(nargout, *args):
    if not args:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'optimoptions')
    rest = list(args)
    first = rest.pop(0)
    if isinstance(first, OptimOptions):
        o = first.value_copy()
    else:
        solver = _solver_name(first)
        if solver is None:
            raise err('optimlib:optimoptions:InvalidSolver', f"'{_show(first).strip(chr(39))}' is not a solver that optimoptions knows: "
                      f"use one of {', '.join(sorted(_SOLVERS))}.", 'optimoptions')
        o = OptimOptions(solver)
        # optimoptions(solver, oldoptions): the options that apply to this solver
        if rest and isinstance(rest[0], (OptimOptions, Struct)):
            src = rest.pop(0)
            items = src.vals.items() if isinstance(src, OptimOptions) else _struct_items(src)
            for k, v in items:
                kk = _canon(solver, k)
                if kk is not None and not (kk == 'Algorithm' and opt_str(v) is not None and opt_lower(v) not in _SOLVERS[solver][0]):
                    o.vals[kk] = _check_value(solver, kk, v) if not isinstance(src, OptimOptions) else v
    if len(rest) % 2:
        raise err('optimlib:options:NameValuePairs', 'Options must come in name-value pairs.', 'optimoptions')
    for i in range(0, len(rest), 2):
        name = opt_str(rest[i])
        if name is None:
            raise err('optimlib:options:NameValuePairs', 'Option names must be text.', 'optimoptions')
        o.setprop(name, rest[i + 1])
    return o


def _struct_items(s):
    return [(k, s.get1(k)) for k in s.f if not (type(s.get1(k)) is np.ndarray and s.get1(k).size == 0)]


@bi('resetoptions', arr=False)
def resetoptions(nargout, *args):
    if not args or not isinstance(args[0], OptimOptions):
        raise err('optimlib:resetoptions:NotOptions', 'The first input must be options made by optimoptions.', 'resetoptions')
    o = args[0].value_copy()
    for a in args[1:]:
        names = [py_str(x) for x in a.a.reshape(-1, order='F')] if type(a) is Cell else [py_str(a)]
        for n in names:
            k = _canon(o.solver, n)
            if k is None:
                raise err('optimlib:options:setProperty:invalidPropName', f"'{n}' is not an option for {o.solver}.", 'resetoptions')
            o.vals.pop(k, None)
    return o


class _Opts:
    """The options a solver runs with: from optimoptions, an optimset
    struct or none, as Python values."""

    def __init__(self, solver, v, n, fn):
        self.solver = solver
        self.n = n
        self.fn = fn
        if isinstance(v, OptimOptions):
            o = v if v.solver == solver else optimoptions(1, solver, v)
            self.o = o
        else:
            o = OptimOptions(solver)
            if type(v) is Struct and v.size == 1:
                for k, x in _struct_items(v):
                    kk = _canon(solver, k)
                    if kk is not None:
                        if kk == 'Algorithm' and opt_str(x) is not None and opt_lower(x) not in _SOLVERS[solver][0]:
                            continue
                        o.vals[kk] = _check_value(solver, kk, x)
                    if k.lower() == 'tolfun' and 'FunctionTolerance' in _SOLVERS[solver][1] and kk != 'FunctionTolerance':
                        o.vals['FunctionTolerance'] = _check_value(solver, 'FunctionTolerance', x)
            elif v is not None and not (type(v) is np.ndarray and v.size == 0):
                raise err('optimlib:commonMsgs:InvalidOptions', 'Options must be made by optimoptions or optimset.', fn)
            self.o = o

    def __getitem__(self, k):
        v = self.o.get(k)
        if type(v) is Char:
            s = v.str()
            if 'numberOfVariables' in s or s in ('sqrt(eps)', 'eps'):
                return self._expr(s)
            return s
        if type(v) is np.ndarray and v.size == 0:
            return None
        return v

    def _expr(self, s):
        n = self.n
        table = {'100*numberOfVariables': 100 * n, '200*numberOfVariables': 200 * n, 'sqrt(eps)': math.sqrt(EPS), 'eps': EPS}
        if s in table:
            return table[s]
        if s == 'ones(numberOfVariables,1)':
            return np.ones(n)
        return None

    def num(self, k, default=None):
        v = self[k]
        if v is None or isinstance(v, str):
            return default
        return float(num(v)) if not isinstance(v, (float, int, bool)) else float(v)

    def count(self, k, default):
        v = self.num(k, None)
        return default if v is None else (int(v) if math.isfinite(v) else 10 ** 9)

    def flag(self, k):
        return bool(self.o.get(k))

    def display(self):
        d = self['Display'] or 'final'
        d = d.replace('-detailed', '')
        return 'off' if d in ('none', 'testing') else d

    def fns(self, k):
        v = self.o.get(k)
        if v is None or (type(v) is np.ndarray and v.size == 0):
            return []
        items = list(v.a.reshape(-1, order='F')) if type(v) is Cell else [v]
        fs = []
        for f in items:
            if isinstance(f, FH):
                fs.append(f)
            elif is_str(f):
                fs.append(R.NamedFH(py_str(f)))
            else:
                raise err('optimlib:commonMsgs:InvalidFcn', f'{k} must hold function handles or names.', self.fn)
        return fs

    def algorithm(self):
        return py_str(self.o.get('Algorithm')) if _SOLVERS[self.solver][0] else ''


# ---- the problem's pieces ------------------------------------------------------------------------------------

def _arg(args, i):
    """args[i], or None when it is not there or is []."""
    if i < len(args):
        v = args[i]
        if isinstance(v, (FH, Obj, Struct)):
            return v
        if numel(v) == 0:
            return None
        return v
    return None


def _problem(args, fields, fn):
    """solver(problem): the struct's fields in the order the solver's
    arguments take them."""
    if len(args) == 1 and type(args[0]) is Struct and args[0].size == 1:
        s = args[0]
        lower = {k.lower(): k for k in s.f}
        return [s.get1(lower[f.lower()]) if f.lower() in lower else EMPTY() for f in fields], True
    return list(args), False


def _fh(f, fn, what='objective'):
    if isinstance(f, FH):
        return f
    if is_str(f):
        return R.NamedFH(py_str(f))
    raise err('optimlib:commonMsgs:InvalidFcn', f'The {what} must be a function handle or a function name.', fn)


def _vec(v, n=None, what='', fn=''):
    a = darr(v).reshape(-1)
    if n is not None and a.size != n:
        raise err('optimlib:commonMsgs:WrongSize', f'{what} must have {n} elements.', fn)
    return a


def _mat(v, n, what, fn):
    a = darr(v)
    if a.ndim != 2 or (a.size and a.shape[1] != n):
        raise err('optimlib:commonMsgs:WrongSize', f'{what} must have {n} columns, one for each variable.', fn)
    return a


class _Fun:
    """The objective (or the vector of residuals): its values and its
    gradient (or Jacobian) at the points asked, by the function's own
    gradient when it gives one, else by finite differences; the
    evaluations counted, the last ones kept."""

    def __init__(self, f, shape, opts, extra=(), vector=False, grad=False, map_x=None):
        self.f = f
        self.shape = shape
        self.extra = extra
        self.vector = vector
        self.user_grad = grad
        self.count = 0
        self.cache = {}
        self.out_shape = None
        self.central = opts['FiniteDifferenceType'] == 'central'
        step = opts['FiniteDifferenceStepSize']
        self.h = float(step) if isinstance(step, float) else math.sqrt(EPS) if not self.central else EPS ** (1 / 3)
        typ = opts['TypicalX']
        self.typ = np.abs(np.asarray(typ, float).reshape(-1)) if typ is not None and np.size(typ) == math.prod(shape) else np.ones(math.prod(shape))
        self.map_x = map_x

    def _call(self, x, nout):
        self.count += 1
        xs = out(x.reshape(self.shape).copy())
        r = self.f.scall(nout, xs, *self.extra)
        return r if nout > 1 else (r,)

    def _value(self, v):
        a = darr(v)
        if a.dtype.kind == 'c':
            raise err('optimlib:commonMsgs:ComplexValue', 'The function returned a complex value: it must be real.', '')
        if self.vector:
            if self.out_shape is None:
                self.out_shape = a.shape
            return a.reshape(-1).astype(F64)
        if a.size != 1:
            raise err('optimlib:commonMsgs:NotScalar', 'The objective must return a scalar value.', '')
        return float(a.reshape(-1)[0])

    def at(self, x):
        """(value, gradient or None) at x."""
        key = x.tobytes()
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        if self.user_grad:
            v, g = self._call(x, 2)
            g = darr(g)
            val = self._value(v)
            g = g.reshape(np.size(val), -1) if self.vector and g.ndim == 2 and g.shape[0] == np.size(val) else g.reshape(-1) if not self.vector else g
            res = (val, np.asarray(g, F64))
        else:
            res = (self._value(self._call(x, 1)[0]), None)
        if len(self.cache) > 8:
            self.cache.clear()
        self.cache[key] = res
        return res

    def value(self, x):
        return self.at(np.asarray(x, F64))[0]

    def grad(self, x):
        """The gradient (a vector) or the Jacobian (rows the residuals)."""
        x = np.asarray(x, F64)
        v, g = self.at(x)
        if g is not None:
            return g
        key = b'g' + x.tobytes()
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        n = x.size
        f0 = np.atleast_1d(v)
        J = np.empty((f0.size, n))
        for i in range(n):
            h = self.h * max(abs(x[i]), self.typ[i])
            xp = x.copy()
            xp[i] += h
            h = xp[i] - x[i]
            if self.central:
                xm = x.copy()
                xm[i] -= h
                J[:, i] = (np.atleast_1d(self.at(xp)[0]) - np.atleast_1d(self.at(xm)[0])) / (2 * h)
            else:
                J[:, i] = (np.atleast_1d(self.at(xp)[0]) - f0) / h
        g = J if self.vector else J.reshape(-1)
        self.cache[key] = g
        return g

    def grad_fine(self, x):
        """The gradient for judging an answer: the function's own, or by
        central differences (truncation error of order h^2, not h)."""
        x = np.asarray(x, F64)
        v, g = self.at(x)
        if g is not None or self.central:
            return self.grad(x)
        n = x.size
        J = np.empty((np.size(v), n))
        for i in range(n):
            h = EPS ** (1 / 3) * max(abs(x[i]), self.typ[i])
            xp, xm = x.copy(), x.copy()
            xp[i] += h
            xm[i] -= h
            J[:, i] = (np.atleast_1d(self.at(xp)[0]) - np.atleast_1d(self.at(xm)[0])) / (xp[i] - xm[i])
        return J if self.vector else J.reshape(-1)

    def hessian(self, x):
        """The Hessian at x by differences of the gradient."""
        x = np.asarray(x, F64)
        n = x.size
        H = np.empty((n, n))
        g0 = self.grad(x)
        for i in range(n):
            h = EPS ** (1 / 3) * max(abs(x[i]), 1.0)
            xp = x.copy()
            xp[i] += h
            H[:, i] = (self.grad(xp) - g0) / (xp[i] - x[i])
        return (H + H.T) / 2


class _Cons:
    """Linear inequalities and equalities, bounds and the nonlinear
    constraints [c, ceq] = nonlcon(x), c <= 0 and ceq = 0."""

    def __init__(self, n, shape, A=None, b=None, Aeq=None, beq=None, lb=None, ub=None, nonlcon=None, opts=None, fn=''):
        self.n = n
        self.shape = shape
        self.A = _mat(A, n, 'A', fn) if A is not None else np.zeros((0, n))
        self.b = _vec(b, self.A.shape[0], 'b', fn) if b is not None else np.zeros(0)
        if self.A.shape[0] != self.b.size:
            raise err('optimlib:commonMsgs:WrongSize', 'A and b must have as many rows.', fn)
        self.Aeq = _mat(Aeq, n, 'Aeq', fn) if Aeq is not None else np.zeros((0, n))
        self.beq = _vec(beq, self.Aeq.shape[0], 'beq', fn) if beq is not None else np.zeros(0)
        if self.Aeq.shape[0] != self.beq.size:
            raise err('optimlib:commonMsgs:WrongSize', 'Aeq and beq must have as many rows.', fn)
        lo = _vec(lb) if lb is not None else np.zeros(0)
        hi = _vec(ub) if ub is not None else np.zeros(0)
        # bounds shorter than x leave the rest free; longer ones are cut, as the language does
        self.lb = np.concatenate([lo[:n], np.full(max(0, n - lo.size), -np.inf)])
        self.ub = np.concatenate([hi[:n], np.full(max(0, n - hi.size), np.inf)])
        if np.any(self.lb > self.ub):
            self.bad_bounds = True
        else:
            self.bad_bounds = False
        self.nonlcon = None
        if nonlcon is not None:
            self.nonlcon = _fh(nonlcon, fn, 'nonlinear constraint function')
        self.grad = bool(opts and opts.flag('SpecifyConstraintGradient'))
        self.cache = {}
        self.nc = self.nceq = 0
        self.fd = _Fun(None, shape, opts, vector=True) if opts is not None else None

    def has_bounds(self):
        return bool(np.any(np.isfinite(self.lb)) or np.any(np.isfinite(self.ub)))

    def nl(self, x):
        """(c, ceq, gc, gceq): the constraint values and their Jacobians (rows the constraints)."""
        if self.nonlcon is None:
            z = np.zeros(0)
            return z, z, np.zeros((0, self.n)), np.zeros((0, self.n))
        key = x.tobytes()
        hit = self.cache.get(key)
        if hit is not None:
            return hit
        xs = out(x.reshape(self.shape).copy())
        if self.grad:
            c, ceq, gc, gceq = self.nonlcon.scall(4, xs)
            c, ceq = darr(c).reshape(-1), darr(ceq).reshape(-1)
            gc = darr(gc).reshape(self.n, -1).T if numel(gc) else np.zeros((0, self.n))
            gceq = darr(gceq).reshape(self.n, -1).T if numel(gceq) else np.zeros((0, self.n))
        else:
            c, ceq = self.nonlcon.scall(2, xs)
            c, ceq = darr(c).reshape(-1).astype(F64), darr(ceq).reshape(-1).astype(F64)
            gc = gceq = None
        if gc is None:
            base = np.concatenate([c, ceq])
            J = np.empty((base.size, self.n))
            for i in range(self.n):
                h = math.sqrt(EPS) * max(abs(x[i]), 1.0)
                xp = x.copy()
                xp[i] += h
                cp, ceqp = self.nonlcon.scall(2, out(xp.reshape(self.shape).copy()))
                J[:, i] = (np.concatenate([darr(cp).reshape(-1), darr(ceqp).reshape(-1)]) - base) / (xp[i] - x[i])
            gc, gceq = J[:c.size], J[c.size:]
        self.nc, self.nceq = c.size, ceq.size
        if len(self.cache) > 8:
            self.cache.clear()
        res = (c, ceq, gc, gceq)
        self.cache[key] = res
        return res

    def violation(self, x):
        v = 0.0
        if self.A.size:
            v = max(v, float(np.max(self.A @ x - self.b, initial=0)))
        if self.Aeq.size:
            v = max(v, float(np.max(np.abs(self.Aeq @ x - self.beq), initial=0)))
        v = max(v, float(np.max(self.lb - x, initial=0)), float(np.max(x - self.ub, initial=0)))
        if self.nonlcon is not None:
            c, ceq, _, _ = self.nl(x)
            v = max(v, float(np.max(c, initial=0)), float(np.max(np.abs(ceq), initial=0)))
        return v

    def scipy(self, slsqp=False):
        """The constraints as SciPy's minimize takes them."""
        from scipy import optimize as O
        cons = []
        if slsqp:
            if self.A.size:
                cons.append({'type': 'ineq', 'fun': lambda x: self.b - self.A @ x, 'jac': lambda x: -self.A})
            if self.Aeq.size:
                cons.append({'type': 'eq', 'fun': lambda x: self.Aeq @ x - self.beq, 'jac': lambda x: self.Aeq})
            if self.nonlcon is not None:
                cons.append({'type': 'ineq', 'fun': lambda x: -self.nl(x)[0], 'jac': lambda x: -self.nl(x)[2]})
                cons.append({'type': 'eq', 'fun': lambda x: self.nl(x)[1], 'jac': lambda x: self.nl(x)[3]})
            return [c for c in cons if c['type'] == 'eq' or True]
        if self.A.size:
            cons.append(O.LinearConstraint(self.A, -np.inf, self.b))
        if self.Aeq.size:
            cons.append(O.LinearConstraint(self.Aeq, self.beq, self.beq))
        if self.nonlcon is not None:
            c, ceq, _, _ = self.nl(np.zeros(self.n) if False else self.x0)
            if c.size:
                cons.append(O.NonlinearConstraint(lambda x: self.nl(x)[0], -np.inf, 0, jac=lambda x: self.nl(x)[2]))
            if ceq.size:
                cons.append(O.NonlinearConstraint(lambda x: self.nl(x)[1], 0, 0, jac=lambda x: self.nl(x)[3]))
        return cons

    def slsqp_list(self, x0):
        """SLSQP's constraints, leaving out empty nonlinear parts."""
        cons = self.scipy(slsqp=True)
        if self.nonlcon is not None:
            c, ceq, _, _ = self.nl(x0)
            cons = [k for k in cons if not ((k['type'] == 'ineq' and k['fun'].__code__ is cons[-2]['fun'].__code__ and c.size == 0) or
                                            (k['type'] == 'eq' and k['fun'].__code__ is cons[-1]['fun'].__code__ and ceq.size == 0))]
        return cons

    def lambdas(self, x, g, tol):
        """The Lagrange multipliers at x for the objective's gradient g:
        lower, upper, ineqlin, eqlin, ineqnonlin, eqnonlin, and the
        first-order optimality (the largest part of the Lagrangian's gradient)."""
        from scipy.optimize import lsq_linear
        n = self.n
        rows, kinds, where = [], [], []
        act = lambda r: r >= -tol * max(1.0, abs(r))
        for i in range(n):
            if np.isfinite(self.lb[i]) and x[i] - self.lb[i] <= tol * max(1.0, abs(self.lb[i])):
                e = np.zeros(n)
                e[i] = -1.0
                rows.append(e); kinds.append(True); where.append(('lower', i))
            if np.isfinite(self.ub[i]) and self.ub[i] - x[i] <= tol * max(1.0, abs(self.ub[i])):
                e = np.zeros(n)
                e[i] = 1.0
                rows.append(e); kinds.append(True); where.append(('upper', i))
        if self.A.size:
            r = self.A @ x - self.b
            for i in range(self.A.shape[0]):
                if act(r[i]):
                    rows.append(self.A[i]); kinds.append(True); where.append(('ineqlin', i))
        for i in range(self.Aeq.shape[0]):
            rows.append(self.Aeq[i]); kinds.append(False); where.append(('eqlin', i))
        c, ceq, gc, gceq = self.nl(x)
        for i in range(c.size):
            if act(c[i]):
                rows.append(gc[i]); kinds.append(True); where.append(('ineqnonlin', i))
        for i in range(ceq.size):
            rows.append(gceq[i]); kinds.append(False); where.append(('eqnonlin', i))
        sizes = {'lower': n, 'upper': n, 'ineqlin': self.A.shape[0], 'eqlin': self.Aeq.shape[0], 'ineqnonlin': c.size, 'eqnonlin': ceq.size}
        lam = {k: np.zeros(v) for k, v in sizes.items()}
        resid = g.copy()
        if rows:
            J = np.array(rows).T
            lo = np.array([0.0 if k else -np.inf for k in kinds])
            sol = lsq_linear(J, -g, bounds=(lo, np.full(len(rows), np.inf)), method='bvls' if len(rows) <= n else 'trf', lsmr_tol='auto')
            for (k, i), v in zip(where, sol.x):
                lam[k][i] = v
            resid = g + J @ sol.x
        return lam, float(np.max(np.abs(resid), initial=0.0))


def _lambda_struct(lam, which=('lower', 'upper', 'eqlin', 'eqnonlin', 'ineqlin', 'ineqnonlin')):
    return Struct.scalar({k: out(lam[k].reshape(-1, 1)) if lam[k].size else np.zeros((0, 1)) for k in which})


# ---- runs: the Display rows, output and plot functions ------------------------------------------------------------

class _Stop(Exception):
    pass


class _Run:
    """One solver run: its Display, the output functions and plot
    functions called at its start, each iteration and its end."""

    def __init__(self, solver, opts, shape, kind='min'):
        self.solver = solver
        self.opts = opts
        self.shape = shape
        self.kind = kind                # 'min', 'con' (with feasibility), 'lsq', 'eq'
        self.level = opts.display()
        self.outfns = opts.fns('OutputFcn')
        self.plotfns = opts.fns('PlotFcn')
        self.it = 0
        self.stopped = False
        self.prev = None
        self.plot_axes = []

    def values(self, x, fval, count, opt=None, feas=None, extra=None):
        d = {'iteration': float(self.it), 'funccount': float(count), 'fval': fval if np.ndim(fval) == 0 else out(np.asarray(fval).reshape(-1, 1)),
             'firstorderopt': float(opt) if opt is not None else EMPTY(), 'stepsize': float(np.linalg.norm(x - self.prev)) if self.prev is not None else EMPTY()}
        if self.kind in ('con',):
            d['constrviolation'] = float(feas) if feas is not None else 0.0
        if extra:
            d.update(extra)
        d['procedure'] = Char.of('')
        return Struct.scalar(d)

    def _row(self, x, fval, count, opt, feas):
        if self.level != 'iter':
            return
        if self.it == 0:
            head = ' Iter  F-count  ' + ('     Resnorm' if self.kind == 'lsq' else '        f(x)' if self.kind != 'eq' else '   sum(F.^2)')
            head += '   Optimality'
            if self.kind == 'con':
                head += '  Feasibility'
            head += '     Step'
            R.write(head + '\n')
        step = f'{np.linalg.norm(x - self.prev):9.3g}' if self.prev is not None else ' ' * 9
        f = fval if np.ndim(fval) == 0 else float(np.max(fval))
        line = f'{self.it:5d} {count:8d}  {f:12.6g}  ' + (f'{opt:11.3g}' if opt is not None else ' ' * 11)
        if self.kind == 'con':
            line += f'  {feas if feas is not None else 0.0:11.3g}'
        R.write(line + '  ' + step + '\n')

    def _call(self, x, vals, state):
        stop = False
        xs = out(np.asarray(x, F64).reshape(self.shape).copy())
        for f in self.outfns:
            r = f.scall(1, xs, vals, Char.of(state))
            if state != 'done' and r is not None and numel(r) and bool(np.any(darr(r))):
                stop = True
        if self.plotfns:
            from .graphics import set_current_axes
            if state == 'init':
                _plot_figure(self)
            for f, ax in zip(self.plotfns, self.plot_axes):
                if ax.valid:
                    set_current_axes(ax)
                    r = f.scall(1, xs, vals, Char.of(state))
                    if state != 'done' and r is not None and numel(r) and bool(np.any(darr(r))):
                        stop = True
        return stop

    def start(self, x, fval, count, opt=None, feas=None, extra=None):
        self._row(x, fval, count, opt, feas)
        if self.outfns or self.plotfns:
            if self._call(x, self.values(x, fval, count, opt, feas, extra), 'init'):
                self.stopped = True
            self._call(x, self.values(x, fval, count, opt, feas, extra), 'iter')
        self.prev = np.array(x, F64)

    def step(self, x, fval, count, opt=None, feas=None, extra=None):
        """An iteration done; raises _Stop when an output function says to stop."""
        self.it += 1
        self._row(x, fval, count, opt, feas)
        if self.outfns or self.plotfns:
            if self._call(x, self.values(x, fval, count, opt, feas, extra), 'iter'):
                self.stopped = True
        self.prev = np.array(x, F64)
        if self.stopped:
            raise _Stop()

    def done(self, x, fval, count, opt=None, feas=None, extra=None):
        if self.outfns or self.plotfns:
            self._call(x, self.values(x, fval, count, opt, feas, extra), 'done')

    def message(self, flag, text):
        if self.level == 'off' or (self.level == 'notify' and flag > 0):
            return
        R.write('\n' + text + '\n\n')


def _plot_figure(run):
    from .graphics import new_figure, subplot
    f = new_figure()
    f.props['Name'] = 'Optimization Plot Functions'
    f.props['NumberTitle'] = False
    k = len(run.plotfns)
    rows = 1 if k <= 1 else 2 if k <= 4 else 3
    cols = math.ceil(k / rows)
    run.plot_axes = [subplot(1, float(rows), float(cols), float(i + 1)) for i in range(k)]


def _finish(run, flag, msg):
    run.message(flag, msg)
    return flag


def _outstruct(run, fun_count, alg, msg, **more):
    d = {'iterations': float(run.it), 'funcCount': float(fun_count), 'algorithm': Char.of(alg)}
    for k, v in more.items():
        d[k] = v if not isinstance(v, (int, np.floating, np.integer)) or isinstance(v, bool) else float(v)
    d['message'] = Char.of(msg)
    return Struct.scalar(d)


def _cb_minimize(run, F, cons=None, xmap=None):
    """A callback for SciPy's minimize that reports each iterate."""
    def cb(intermediate_result):
        # a result with x (BFGS, trust-constr) or the point itself (SLSQP)
        x = np.asarray(getattr(intermediate_result, 'x', intermediate_result), F64)
        xx = xmap(x) if xmap else x
        fval = F.value(xx)
        g = F.grad(xx)
        opt = float(np.max(np.abs(g))) if cons is None else None
        feas = cons.violation(xx) if cons is not None else None
        if cons is not None and getattr(intermediate_result, 'optimality', None) is not None:
            opt = float(intermediate_result.optimality)
        try:
            run.step(xx, fval, F.count, opt, feas)
        except _Stop:
            raise StopIteration
    return cb


# ---- unconstrained minimum: fminunc ------------------------------------------------------------------------------

@bi('fminunc', nout=6)
def fminunc(nargout, *args):
    from scipy import optimize as O
    args, prob = _problem(args, ('objective', 'x0', 'options'), 'fminunc')
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'fminunc')
    f = _fh(args[0], 'fminunc')
    x0 = darr(args[1])
    shape, n = x0.shape, x0.size
    opts = _Opts('fminunc', _arg(args, 2), n, 'fminunc')
    F = _Fun(f, shape, opts, extra=tuple(args[3:]), grad=opts.flag('SpecifyObjectiveGradient'))
    run = _Run('fminunc', opts, shape)
    alg = opts.algorithm()
    x = x0.reshape(-1).astype(F64)
    if alg == 'trust-region' and not opts.flag('SpecifyObjectiveGradient'):
        R.write('Warning: the trust-region algorithm needs the gradient (SpecifyObjectiveGradient); quasi-newton is used instead.\n')
        alg = 'quasi-newton'
    f0, g0 = F.value(x), F.grad(x)
    # SciPy goes on to OptimalityTolerance itself; the exit flag takes it relative to the gradient at the start
    scale = max(1.0, float(np.max(np.abs(g0), initial=0)))
    run.start(x, f0, F.count, float(np.max(np.abs(g0), initial=0)))
    tol = opts.num('OptimalityTolerance', 1e-6)
    maxit = opts.count('MaxIterations', 400)
    maxfev = opts.count('MaxFunctionEvaluations', 100 * n)
    flim = opts.num('ObjectiveLimit', -1e20)
    res = None
    try:
        if not run.stopped:
            if alg == 'trust-region':
                hf = opts['HessianFcn']
                hess = (lambda z: darr(f.scall(3, out(z.reshape(shape).copy()))[2])) if hf is not None and opt_str(hf) == 'objective' else O.BFGS()
                res = O.minimize(F.value, x, jac=F.grad, hess=hess, method='trust-constr',
                                 options={'gtol': tol, 'xtol': opts.num('StepTolerance', 1e-6), 'maxiter': maxit}, callback=_cb_minimize(run, F))
            else:
                res = O.minimize(F.value, x, jac=F.grad, method='BFGS', options={'gtol': tol, 'maxiter': maxit,
                                                                                    'xrtol': opts.num('StepTolerance', 1e-6)},
                                 callback=_cb_minimize(run, F))
            x = np.asarray(res.x, F64)
    except _Stop:
        pass
    if run.stopped and res is None:
        pass
    fval, g = F.value(x), F.grad_fine(x)
    opt = float(np.max(np.abs(g), initial=0))
    if run.stopped:
        flag, msg = -1, 'Stopped by an output or plot function.'
    elif fval < flim:
        flag, msg = -3, f'The objective fell below ObjectiveLimit ({flim:g}): the problem seems unbounded below.'
    elif opt <= tol * scale:
        flag, msg = 1, (f'Local minimum found: the first-order optimality {opt:.3g} is below OptimalityTolerance ({tol:g}) '
                        f'times the largest part of the gradient at the start (or 1).')
    elif res is not None and res.get('nit', 0) >= maxit:
        flag, msg = 0, f'Stopped: MaxIterations ({maxit}) reached; the first-order optimality is {opt:.3g}.'
    elif F.count >= maxfev:
        flag, msg = 0, f'Stopped: MaxFunctionEvaluations ({maxfev}) reached; the first-order optimality is {opt:.3g}.'
    else:
        flag, msg = 2, (f'Local minimum possible: the steps became smaller than SciPy could resolve; the first-order optimality is {opt:.3g} '
                        f'(OptimalityTolerance {tol:g}).')
    run.done(x, fval, F.count, opt)
    _finish(run, flag, msg)
    xo = out(x.reshape(shape))
    if nargout <= 1:
        return xo
    output = _outstruct(run, F.count, alg, msg, firstorderopt=opt,
                        stepsize=float(np.linalg.norm(x - run.prev)) if run.prev is not None else 0.0)
    res_ = [xo, fval, float(flag), output]
    if nargout > 4:
        res_.append(out(g.reshape(-1, 1)))
    if nargout > 5:
        res_.append(out(F.hessian(x)))
    return tuple(res_[:nargout])


# ---- constrained minimum: fmincon -------------------------------------------------------------------------------------

def _con_min(F, cons, x0, opts, run, alg, maxit):
    """Minimize F subject to cons: trust-constr (an interior point method)
    then SLSQP from its answer, or SLSQP alone. The answer and SciPy's last result."""
    from scipy import optimize as O
    n = x0.size
    bounds = O.Bounds(cons.lb, cons.ub) if cons.has_bounds() else None
    tol = opts.num('OptimalityTolerance', 1e-6)
    x = x0.copy()
    res = None
    if alg in ('interior-point', 'trust-region-reflective'):
        cons.x0 = x
        hf = opts['HessianFcn']
        res = O.minimize(F.value, x, jac=F.grad, hess=O.BFGS() if hf is None else None, method='trust-constr', bounds=bounds,
                         constraints=cons.scipy(), callback=_cb_minimize(run, F, cons),
                         options={'gtol': tol, 'xtol': opts.num('StepTolerance', 1e-10), 'maxiter': maxit})
        x = np.asarray(res.x, F64)
    # SLSQP: alone, or from the interior point's answer so as to land on the active constraints
    left = max(1, maxit - run.it)
    res2 = O.minimize(F.value, x, jac=F.grad, method='SLSQP', bounds=bounds if bounds is not None else None,
                      constraints=cons.slsqp_list(x), callback=_cb_minimize(run, F, cons) if res is None else None,
                      options={'ftol': 1e-12 if res is not None else min(1e-10, tol * 1e-4), 'maxiter': left})
    x2 = np.asarray(res2.x, F64)
    if res is None or (cons.violation(x2) <= max(cons.violation(x), opts.num('ConstraintTolerance', 1e-6)) and F.value(x2) <= F.value(x) + 1e-8 * max(1.0, abs(F.value(x)))):
        x = x2
    return x, res2 if res is None else res


@bi('fmincon', nout=7)
def fmincon(nargout, *args):
    args, prob = _problem(args, ('objective', 'x0', 'Aineq', 'bineq', 'Aeq', 'beq', 'lb', 'ub', 'nonlcon', 'options'), 'fmincon')
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'fmincon')
    if len(args) < 4 and not prob:
        raise err('MATLAB:minrhs', 'fmincon needs at least fun, x0, A and b ([] when there are none).', 'fmincon')
    f = _fh(args[0], 'fmincon')
    x0 = darr(args[1])
    shape, n = x0.shape, x0.size
    opts = _Opts('fmincon', _arg(args, 9), n, 'fmincon')
    cons = _Cons(n, shape, _arg(args, 2), _arg(args, 3), _arg(args, 4), _arg(args, 5), _arg(args, 6), _arg(args, 7), _arg(args, 8), opts, 'fmincon')
    F = _Fun(f, shape, opts, extra=tuple(args[10:]), grad=opts.flag('SpecifyObjectiveGradient'))
    run = _Run('fmincon', opts, shape, 'con')
    alg = opts.algorithm()
    ctol = opts.num('ConstraintTolerance', 1e-6)
    tol = opts.num('OptimalityTolerance', 1e-6)
    maxit = opts.count('MaxIterations', 1000)
    maxfev = opts.count('MaxFunctionEvaluations', 3000)
    if cons.bad_bounds:
        msg = 'No feasible point: a lower bound is above its upper bound.'
        run.message(-2, msg)
        xo = out(x0)
        return (xo, F.value(x0.reshape(-1)), -2.0, _outstruct(run, F.count, alg, msg), _lambda_struct({k: np.zeros(0) for k in ('lower', 'upper', 'eqlin', 'eqnonlin', 'ineqlin', 'ineqnonlin')}))[:max(1, nargout)] if nargout > 1 else xo
    x = x0.reshape(-1).astype(F64)
    # a start outside the bounds moves inside them, as the interior point method needs
    x = np.clip(x, cons.lb, cons.ub)
    scale = max(1.0, float(np.max(np.abs(F.grad(x)), initial=0)))
    run.start(x, F.value(x), F.count, None, cons.violation(x))
    res = None
    try:
        if not run.stopped:
            x, res = _con_min(F, cons, x, opts, run, alg, maxit)
    except _Stop:
        x = run.prev if run.prev is not None else x
    fval, g = F.value(x), F.grad_fine(x)
    feas = cons.violation(x)
    lam, opt = cons.lambdas(x, g, max(ctol, 1e-8) * 10)
    flim = opts.num('ObjectiveLimit', -1e20)
    if run.stopped:
        flag, msg = -1, 'Stopped by an output or plot function.'
    elif feas > ctol * max(1.0, 1.0):
        flag, msg = -2, f'No feasible point found: the constraints are violated by {feas:.3g} (ConstraintTolerance {ctol:g}).'
    elif fval < flim:
        flag, msg = -3, f'The objective fell below ObjectiveLimit ({flim:g}) at a feasible point: the problem seems unbounded below.'
    elif opt <= tol * scale:
        flag, msg = 1, (f'Local minimum found that satisfies the constraints: the first-order optimality {opt:.3g} is below '
                        f'OptimalityTolerance ({tol:g}), and the constraints are met to within ConstraintTolerance ({ctol:g}).')
    elif run.it >= maxit:
        flag, msg = 0, f'Stopped: MaxIterations ({maxit}) reached; the first-order optimality is {opt:.3g}.'
    elif F.count >= maxfev:
        flag, msg = 0, f'Stopped: MaxFunctionEvaluations ({maxfev}) reached; the first-order optimality is {opt:.3g}.'
    else:
        flag, msg = 2, (f'Local minimum possible, the constraints met: the steps became small while the first-order optimality '
                        f'is {opt:.3g} (OptimalityTolerance {tol:g}).')
    run.done(x, fval, F.count, opt, feas)
    _finish(run, flag, msg)
    xo = out(x.reshape(shape))
    if nargout <= 1:
        return xo
    used = {'interior-point': 'interior-point (SciPy trust-constr, then SLSQP)', 'trust-region-reflective': 'trust-region-reflective (SciPy trust-constr, then SLSQP)'}.get(alg, f'{alg} (SciPy SLSQP)')
    output = _outstruct(run, F.count, used, msg, constrviolation=feas, firstorderopt=opt,
                        stepsize=float(np.linalg.norm(x - run.prev)) if run.prev is not None else 0.0)
    r = [xo, fval, float(flag), output, _lambda_struct(lam)]
    if nargout > 5:
        r.append(out(g.reshape(-1, 1)))
    if nargout > 6:
        r.append(out(F.hessian(x)))
    return tuple(r[:nargout])


# ---- equations: fsolve -------------------------------------------------------------------------------------------------

@bi('fsolve', nout=5)
def fsolve(nargout, *args):
    from scipy import optimize as O
    args, prob = _problem(args, ('objective', 'x0', 'options'), 'fsolve')
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'fsolve')
    f = _fh(args[0], 'fsolve')
    x0 = darr(args[1])
    shape, n = x0.shape, x0.size
    opts = _Opts('fsolve', _arg(args, 2), n, 'fsolve')
    F = _Fun(f, shape, opts, extra=tuple(args[3:]), vector=True, grad=opts.flag('SpecifyObjectiveGradient'))
    run = _Run('fsolve', opts, shape, 'eq')
    alg = opts.algorithm()
    x = x0.reshape(-1).astype(F64)
    v0 = F.value(x)
    J0 = F.grad(x)
    run.start(x, float(v0 @ v0), F.count, float(np.max(np.abs(J0.T @ v0), initial=0)), extra={'residual': out(v0.reshape(F.out_shape))})
    ftol = opts.num('FunctionTolerance', 1e-6)
    xtol = opts.num('StepTolerance', 1e-6)
    maxfev = opts.count('MaxFunctionEvaluations', 100 * n)
    maxit = opts.count('MaxIterations', 400)

    def cb(intermediate_result):
        z = np.asarray(getattr(intermediate_result, 'x', intermediate_result), F64)
        v = F.value(z)
        try:
            run.step(z, float(v @ v), F.count, float(np.max(np.abs(F.grad(z).T @ v), initial=0)), extra={'residual': out(v.reshape(F.out_shape))})
        except _Stop:
            raise StopIteration
    try:
        if not run.stopped:
            if v0.size == n and alg == 'trust-region-dogleg':
                res = O.root(F.value, x, jac=F.grad, method='hybr', options={'xtol': xtol, 'maxfev': maxfev})
                x = np.asarray(res.x, F64)
                # hybr has no iterations to report: one row for its answer
                if run.level == 'iter' or run.outfns or run.plotfns:
                    v = F.value(x)
                    run.step(x, float(v @ v), F.count, None, extra={'residual': out(v.reshape(F.out_shape))})
            else:
                method = 'lm' if alg == 'levenberg-marquardt' and v0.size >= n else 'trf'
                res = O.least_squares(F.value, x, jac=F.grad, method=method, ftol=max(ftol * 1e-6, EPS), xtol=max(xtol * 1e-3, EPS),
                                      gtol=max(opts.num('OptimalityTolerance', 1e-6) * 1e-6, EPS), max_nfev=maxfev,
                                      **({'callback': cb} if method != 'lm' and _LSQ_CALLBACK else {}))
                x = np.asarray(res.x, F64)
    except (_Stop, StopIteration):
        x = run.prev if run.prev is not None else x
    v = F.value(x)
    J = F.grad(x)
    ss = float(v @ v)
    opt = float(np.max(np.abs(J.T @ v), initial=0))
    if run.stopped:
        flag, msg = -1, 'Stopped by an output or plot function.'
    elif ss <= ftol ** 2 * 1e-0 or float(np.max(np.abs(v), initial=0)) <= ftol * 1e-2:
        flag, msg = 1, f'Equation solved: sum(F.^2) is {ss:.3g}.'
    elif F.count >= maxfev:
        flag, msg = 0, f'Stopped: MaxFunctionEvaluations ({maxfev}) reached; sum(F.^2) is {ss:.3g}.'
    elif opt <= opts.num('OptimalityTolerance', 1e-6):
        flag, msg = -2, (f'No solution found: the search stopped at a minimum of sum(F.^2) = {ss:.3g} that is not zero; '
                         'try another start.')
    else:
        flag, msg = -2, f'No solution found: sum(F.^2) is {ss:.3g} where the search could go no further.'
    run.done(x, ss, F.count, opt, extra={'residual': out(v.reshape(F.out_shape))})
    _finish(run, flag, msg)
    xo = out(x.reshape(shape))
    if nargout <= 1:
        return xo
    output = _outstruct(run, F.count, alg, msg, firstorderopt=opt)
    r = [xo, out(v.reshape(F.out_shape)), float(flag), output, out(J)]
    return tuple(r[:nargout])


# ---- least squares: lsqnonlin, lsqcurvefit --------------------------------------------------------------------------------

def _lsq(nargout, f, x0, extra, lb, ub, A, b, Aeq, beq, nonlcon, optarg, fn, resid=None):
    from scipy import optimize as O
    shape, n = x0.shape, x0.size
    opts = _Opts(fn, optarg, n, fn)
    F = _Fun(f, shape, opts, extra=extra, vector=True, grad=opts.flag('SpecifyObjectiveGradient'))
    if resid is not None:
        G = F
        F = _Fun(None, shape, opts, vector=True)
        F.f = None
        base_at = G.at

        def at(x, _G=G):
            v, J = base_at(x)
            return (v - resid, J)
        F.at = at
        F.count_src = G
    cons = _Cons(n, shape, A, b, Aeq, beq, lb, ub, nonlcon, opts, fn)
    run = _Run(fn, opts, shape, 'lsq')
    alg = opts.algorithm()
    count = lambda: (F.count_src.count if hasattr(F, 'count_src') else F.count)
    x = np.clip(x0.reshape(-1).astype(F64), cons.lb, cons.ub)
    v0 = F.value(x)
    run.start(x, float(v0 @ v0), count(), float(np.max(np.abs(F.grad(x).T @ v0), initial=0)),
              extra={'resnorm': float(v0 @ v0), 'residual': out(v0.reshape(-1, 1))})
    ftol = opts.num('FunctionTolerance', 1e-6)
    xtol = opts.num('StepTolerance', 1e-6)
    gtol = opts.num('OptimalityTolerance', 1e-6)
    maxfev = opts.count('MaxFunctionEvaluations', 100 * n)
    linear_or_nl = cons.A.size or cons.Aeq.size or cons.nonlcon is not None

    def cb(intermediate_result):
        z = np.asarray(getattr(intermediate_result, 'x', intermediate_result), F64)
        v = F.value(z)
        try:
            run.step(z, float(v @ v), count(), float(np.max(np.abs(F.grad(z).T @ v), initial=0)),
                     extra={'resnorm': float(v @ v), 'residual': out(v.reshape(-1, 1))})
        except _Stop:
            raise StopIteration
    lam = {k: np.zeros(s) for k, s in (('lower', n), ('upper', n), ('ineqlin', cons.A.shape[0]), ('eqlin', cons.Aeq.shape[0]), ('ineqnonlin', 0), ('eqnonlin', 0))}
    try:
        if not run.stopped:
            if linear_or_nl:
                # constraints beyond bounds: the sum of squares minimized as fmincon would
                S = _Fun(None, shape, opts)
                S.at = lambda z: (float(F.value(z) @ F.value(z)), 2 * F.grad(z).T @ F.value(z))
                x, _ = _con_min(S, cons, x, opts, run, 'interior-point' if alg == 'interior-point' else 'sqp', opts.count('MaxIterations', 400))
            else:
                method = 'lm' if alg == 'levenberg-marquardt' and not cons.has_bounds() and v0.size >= n else 'trf'
                res = O.least_squares(F.value, x, jac=F.grad, bounds=(cons.lb, cons.ub), method=method, ftol=max(ftol * 1e-2, EPS),
                                      xtol=max(xtol * 1e-2, EPS), gtol=max(gtol * 1e-2, EPS), max_nfev=maxfev,
                                      **({'callback': cb} if method != 'lm' and _LSQ_CALLBACK else {}))
                x = np.asarray(res.x, F64)
    except (_Stop, StopIteration):
        x = run.prev if run.prev is not None else x
    v = F.value(x)
    J = F.grad_fine(x)
    resnorm = float(v @ v)
    g = 2 * J.T @ v
    lam, opt = cons.lambdas(x, g, 1e-8)
    feas = cons.violation(x)
    if run.stopped:
        flag, msg = -1, 'Stopped by an output or plot function.'
    elif feas > opts.num('ConstraintTolerance', 1e-6):
        flag, msg = -2, f'No feasible point found: the constraints are violated by {feas:.3g}.'
    elif count() >= maxfev:
        flag, msg = 0, f'Stopped: MaxFunctionEvaluations ({maxfev}) reached; the sum of squares is {resnorm:.3g}.'
    elif opt <= gtol * max(1.0, resnorm):
        flag, msg = 1, f'Local minimum found: the first-order optimality {opt:.3g} is below OptimalityTolerance ({gtol:g}); the sum of squares is {resnorm:.6g}.'
    else:
        flag, msg = 3, f'Local minimum possible: the sum of squares {resnorm:.6g} changed by less than FunctionTolerance ({ftol:g}) relative to its size.'
    run.done(x, resnorm, count(), opt, extra={'resnorm': resnorm, 'residual': out(v.reshape(-1, 1))})
    _finish(run, flag, msg)
    xo = out(x.reshape(shape))
    if nargout <= 1:
        return xo
    src = F.count_src if hasattr(F, 'count_src') else F
    rshape = src.out_shape or (v.size, 1)
    output = _outstruct(run, count(), alg, msg, firstorderopt=opt,
                        **({'constrviolation': feas} if linear_or_nl else {}))
    r = [xo, resnorm, out(v.reshape(rshape)), float(flag), output, _lambda_struct(lam, ('lower', 'upper', 'ineqlin', 'eqlin', 'ineqnonlin', 'eqnonlin')
                                                                                 if linear_or_nl else ('lower', 'upper')), out(J)]
    return tuple(r[:nargout])


@bi('lsqnonlin', nout=7)
def lsqnonlin(nargout, *args):
    args, prob = _problem(args, ('objective', 'x0', 'lb', 'ub', 'Aineq', 'bineq', 'Aeq', 'beq', 'nonlcon', 'options'), 'lsqnonlin')
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'lsqnonlin')
    f = _fh(args[0], 'lsqnonlin')
    x0 = darr(args[1])
    # lsqnonlin(fun, x0, lb, ub, options) or with linear and nonlinear constraints before the options
    if len(args) == 5 and isinstance(args[4], (OptimOptions, Struct)):
        return _lsq(nargout, f, x0, (), _arg(args, 2), _arg(args, 3), None, None, None, None, None, args[4], 'lsqnonlin')
    return _lsq(nargout, f, x0, tuple(args[10:]), _arg(args, 2), _arg(args, 3), _arg(args, 4), _arg(args, 5), _arg(args, 6),
                _arg(args, 7), _arg(args, 8), _arg(args, 9), 'lsqnonlin')


@bi('lsqcurvefit', nout=7)
def lsqcurvefit(nargout, *args):
    args, prob = _problem(args, ('objective', 'x0', 'xdata', 'ydata', 'lb', 'ub', 'Aineq', 'bineq', 'Aeq', 'beq', 'nonlcon', 'options'), 'lsqcurvefit')
    if len(args) < 4:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'lsqcurvefit')
    f = _fh(args[0], 'lsqcurvefit')
    x0 = darr(args[1])
    xdata = args[2]
    ydata = darr(args[3]).reshape(-1).astype(F64)
    if len(args) == 7 and isinstance(args[6], (OptimOptions, Struct)):
        return _lsq(nargout, f, x0, (xdata,), _arg(args, 4), _arg(args, 5), None, None, None, None, None, args[6], 'lsqcurvefit', resid=ydata)
    return _lsq(nargout, f, x0, (xdata,), _arg(args, 4), _arg(args, 5), _arg(args, 6), _arg(args, 7), _arg(args, 8), _arg(args, 9),
                _arg(args, 10), _arg(args, 11), 'lsqcurvefit', resid=ydata)


# ---- quadratic programs: quadprog, lsqlin ---------------------------------------------------------------------------------

def _qp(H, f, cons, x0, opts, run):
    """min 1/2 x'Hx + f'x subject to cons: an interior point start
    (trust-constr), then the active set it finds solved exactly as a
    linear KKT system, kept when its multipliers have the right signs."""
    from scipy import optimize as O
    n = f.size
    obj = lambda x: 0.5 * x @ H @ x + f @ x
    grad = lambda x: H @ x + f
    count = [0]

    def fv(x):
        count[0] += 1
        return obj(x)
    tol = 1e-9
    has_ineq = cons.A.size or cons.has_bounds()
    if not has_ineq:
        x = _kkt_solve(H, f, [], cons)
        if x is not None:
            return x, 'direct'
    x = x0 if x0 is not None else np.zeros(n)
    x = np.clip(x, np.where(np.isfinite(cons.lb), cons.lb, -1e300), np.where(np.isfinite(cons.ub), cons.ub, 1e300))
    cons.x0 = x
    bounds = O.Bounds(cons.lb, cons.ub) if cons.has_bounds() else None
    res = O.minimize(fv, x, jac=grad, hess=lambda x: H, method='trust-constr', bounds=bounds, constraints=cons.scipy(),
                     options={'gtol': 1e-10, 'xtol': 1e-14, 'maxiter': max(1000, opts.count('MaxIterations', 200) * 5)})
    x = np.asarray(res.x, F64)
    # the active set at the interior point's answer, solved exactly
    for scale in (1e-6, 1e-4, 1e-3):
        act = []
        for i in range(n):
            if np.isfinite(cons.lb[i]) and x[i] - cons.lb[i] <= scale * max(1.0, abs(cons.lb[i])):
                act.append(('lb', i))
            elif np.isfinite(cons.ub[i]) and cons.ub[i] - x[i] <= scale * max(1.0, abs(cons.ub[i])):
                act.append(('ub', i))
        if cons.A.size:
            r = cons.A @ x - cons.b
            act += [('A', i) for i in range(r.size) if r[i] >= -scale * max(1.0, abs(cons.b[i]))]
        xs = _kkt_solve(H, f, act, cons)
        if xs is not None and cons.violation(xs) <= 1e-9 * max(1.0, float(np.max(np.abs(xs), initial=0))) and obj(xs) <= obj(x) + 1e-12 * max(1.0, abs(obj(x))):
            lam, opt = cons.lambdas(xs, grad(xs), 1e-9)
            if opt <= 1e-8 * max(1.0, float(np.max(np.abs(f), initial=0))):
                return xs, 'interior point, then its active set solved'
    return x, 'interior point'


def _kkt_solve(H, f, act, cons):
    """x with the constraints in act (and the equalities) held as equalities."""
    n = f.size
    rows, rhs = [], []
    for kind, i in act:
        e = np.zeros(n)
        if kind in ('lb', 'ub'):
            e[i] = 1.0
            rows.append(e)
            rhs.append(cons.lb[i] if kind == 'lb' else cons.ub[i])
        else:
            rows.append(cons.A[i])
            rhs.append(cons.b[i])
    for i in range(cons.Aeq.shape[0]):
        rows.append(cons.Aeq[i])
        rhs.append(cons.beq[i])
    m = len(rows)
    K = np.zeros((n + m, n + m))
    K[:n, :n] = H
    if m:
        C = np.array(rows)
        K[:n, n:] = C.T
        K[n:, :n] = C
    rhs_all = np.concatenate([-f, np.array(rhs, float)])
    try:
        sol, *_ = np.linalg.lstsq(K, rhs_all, rcond=None)
    except np.linalg.LinAlgError:
        return None
    if not np.allclose(K @ sol, rhs_all, rtol=1e-8, atol=1e-8 * max(1.0, float(np.max(np.abs(rhs_all), initial=0)))):
        return None
    return sol[:n]


@bi('quadprog', nout=5)
def quadprog(nargout, *args):
    args, prob = _problem(args, ('H', 'f', 'Aineq', 'bineq', 'Aeq', 'beq', 'lb', 'ub', 'x0', 'options'), 'quadprog')
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'quadprog')
    H = darr(args[0]).astype(F64)
    f = darr(args[1]).reshape(-1).astype(F64) if numel(args[1]) else np.zeros(H.shape[0])
    n = f.size
    if H.shape != (n, n):
        raise err('optim:quadprog:InvalidSizeH', 'H must be a square matrix with as many rows as f has elements.', 'quadprog')
    H = (H + H.T) / 2
    opts = _Opts('quadprog', _arg(args, 9), n, 'quadprog')
    cons = _Cons(n, (n, 1), _arg(args, 2), _arg(args, 3), _arg(args, 4), _arg(args, 5), _arg(args, 6), _arg(args, 7), None, opts, 'quadprog')
    x0 = _vec(args[8], n, 'x0', 'quadprog') if _arg(args, 8) is not None else None
    run = _Run('quadprog', opts, (n, 1), 'con')
    alg = opts.algorithm()
    if cons.bad_bounds:
        msg = 'No feasible point: a lower bound is above its upper bound.'
        run.message(-2, msg)
        return (EMPTY(), EMPTY(), -2.0, _outstruct(run, 0, alg, msg), _lambda_struct({k: np.zeros(0) for k in ('lower', 'upper', 'eqlin', 'ineqlin')}, ('lower', 'upper', 'eqlin', 'ineqlin')))[:max(1, nargout)] if nargout > 1 else EMPTY()
    convex = float(np.min(np.linalg.eigvalsh(H), initial=0.0)) >= -1e-10 * max(1.0, float(np.max(np.abs(H), initial=0)))
    x, how = _qp(H, f, cons, x0, opts, run)
    fval = float(0.5 * x @ H @ x + f @ x)
    feas = cons.violation(x)
    lam, opt = cons.lambdas(x, H @ x + f, 1e-7)
    ctol = opts.num('ConstraintTolerance', 1e-8)
    if feas > max(ctol, 1e-7) * max(1.0, float(np.max(np.abs(x), initial=0))):
        flag, msg = -2, f'No feasible point found: the constraints are violated by {feas:.3g}.'
    elif not convex and alg == 'interior-point-convex':
        flag, msg = -6, ('The problem is not convex (H has a negative eigenvalue): the answer is a local minimum at best. '
                         "The 'trust-region-reflective' or 'active-set' algorithm accepts such problems.")
    elif fval < -1e20 or not np.all(np.isfinite(x)):
        flag, msg = -3, 'The problem is unbounded below.'
    else:
        flag, msg = 1, f'Minimum found that satisfies the constraints: the first-order optimality is {opt:.3g}.'
    if not convex and flag == 1 and alg != 'interior-point-convex':
        msg = f'Local minimum found that satisfies the constraints (the problem is not convex): the first-order optimality is {opt:.3g}.'
    run.message(flag, msg)
    xo = out(x.reshape(-1, 1))
    if nargout <= 1:
        return xo
    output = _outstruct(run, 0, alg, msg, constrviolation=feas, firstorderopt=opt, cgiterations=0.0)
    output = Struct.scalar({k: output.get1(k) for k in output.f if k != 'funcCount'})
    r = [xo, fval, float(flag), output, _lambda_struct(lam, ('ineqlin', 'eqlin', 'lower', 'upper'))]
    return tuple(r[:nargout])


@bi('lsqlin', nout=6)
def lsqlin(nargout, *args):
    from scipy import optimize as O
    args, prob = _problem(args, ('C', 'd', 'Aineq', 'bineq', 'Aeq', 'beq', 'lb', 'ub', 'x0', 'options'), 'lsqlin')
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'lsqlin')
    C = darr(args[0]).astype(F64)
    d = darr(args[1]).reshape(-1).astype(F64)
    if C.shape[0] != d.size:
        raise err('optim:lsqlin:InvalidSizeCd', 'C must have as many rows as d has elements.', 'lsqlin')
    n = C.shape[1]
    opts = _Opts('lsqlin', _arg(args, 9), n, 'lsqlin')
    cons = _Cons(n, (n, 1), _arg(args, 2), _arg(args, 3), _arg(args, 4), _arg(args, 5), _arg(args, 6), _arg(args, 7), None, opts, 'lsqlin')
    x0 = _vec(args[8], n, 'x0', 'lsqlin') if _arg(args, 8) is not None else None
    run = _Run('lsqlin', opts, (n, 1), 'con')
    alg = opts.algorithm()
    if not cons.A.size and not cons.Aeq.size:
        res = O.lsq_linear(C, d, bounds=(cons.lb, cons.ub), method='bvls' if n <= 200 else 'trf', tol=1e-12)
        x = np.asarray(res.x, F64)
    else:
        x, _ = _qp(C.T @ C, -C.T @ d, cons, x0, opts, run)
    resid = C @ x - d
    resnorm = float(resid @ resid)
    lam, opt = cons.lambdas(x, C.T @ resid, 1e-7)
    feas = cons.violation(x)
    if feas > 1e-7 * max(1.0, float(np.max(np.abs(x), initial=0))):
        flag, msg = -2, f'No feasible point found: the constraints are violated by {feas:.3g}.'
    else:
        flag, msg = 1, f'Minimum found that satisfies the constraints: the first-order optimality is {opt:.3g}.'
    run.message(flag, msg)
    xo = out(x.reshape(-1, 1))
    if nargout <= 1:
        return xo
    output = _outstruct(run, 0, alg, msg, constrviolation=feas, firstorderopt=opt)
    output = Struct.scalar({k: output.get1(k) for k in output.f if k != 'funcCount'})
    r = [xo, resnorm, out(resid.reshape(-1, 1)), float(flag), output, _lambda_struct(lam, ('ineqlin', 'eqlin', 'lower', 'upper'))]
    return tuple(r[:nargout])


@bi('lsqnonneg', nout=6)
def lsqnonneg(nargout, *args):
    from scipy.optimize import nnls
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'lsqnonneg')
    C = darr(args[0]).astype(F64)
    d = darr(args[1]).reshape(-1).astype(F64)
    if C.ndim != 2 or C.shape[0] != d.size:
        raise err('MATLAB:lsqnonneg:InvalidSize', 'C must have as many rows as d has elements.', 'lsqnonneg')
    n = C.shape[1]
    opts = _Opts('lsqnonneg', _arg(args, 2), n, 'lsqnonneg')
    x, rnorm = nnls(C, d, maxiter=max(3 * n, 50))
    resid = d - C @ x
    w = C.T @ resid
    lam = np.where(x > 0, 0.0, w)
    msg = 'Optimization terminated.'
    if opts.display() in ('final', 'iter'):
        R.write(f'\n{msg}\n\n')
    xo = out(x.reshape(-1, 1))
    if nargout <= 1:
        return xo
    output = Struct.scalar({'iterations': 0.0, 'algorithm': Char.of('active-set (Lawson and Hanson, SciPy nnls)'), 'message': Char.of(msg)})
    r = [xo, float(rnorm ** 2), out(resid.reshape(-1, 1)), 1.0, output, out(lam.reshape(-1, 1))]
    return tuple(r[:nargout])


# ---- linear and mixed-integer programs: linprog, intlinprog -------------------------------------------------------------------

def _lin_cons(args, n, fn, i0):
    A = _mat(args[i0], n, 'A', fn) if _arg(args, i0) is not None else None
    b = _vec(args[i0 + 1]) if _arg(args, i0 + 1) is not None else None
    Aeq = _mat(args[i0 + 2], n, 'Aeq', fn) if _arg(args, i0 + 2) is not None else None
    beq = _vec(args[i0 + 3]) if _arg(args, i0 + 3) is not None else None
    lb = _vec(args[i0 + 4]) if _arg(args, i0 + 4) is not None else None
    ub = _vec(args[i0 + 5]) if _arg(args, i0 + 5) is not None else None
    if (A is None) != (b is None) or (A is not None and A.shape[0] != b.size):
        raise err('optimlib:commonMsgs:WrongSize', 'A and b must have as many rows.', fn)
    if (Aeq is None) != (beq is None) or (Aeq is not None and Aeq.shape[0] != beq.size):
        raise err('optimlib:commonMsgs:WrongSize', 'Aeq and beq must have as many rows.', fn)
    lo = np.full(n, -np.inf) if lb is None else np.concatenate([lb[:n], np.full(max(0, n - lb.size), -np.inf)])
    hi = np.full(n, np.inf) if ub is None else np.concatenate([ub[:n], np.full(max(0, n - ub.size), np.inf)])
    return A, b, Aeq, beq, lo, hi


@bi('linprog', nout=5)
def linprog(nargout, *args):
    from scipy import optimize as O
    args, prob = _problem(args, ('f', 'Aineq', 'bineq', 'Aeq', 'beq', 'lb', 'ub', 'options'), 'linprog')
    if len(args) < 3 and not prob:
        if len(args) < 1:
            raise err('MATLAB:minrhs', 'Not enough input arguments.', 'linprog')
    f = _vec(args[0])
    n = f.size
    args = list(args) + [EMPTY()] * (8 - len(args))
    A, b, Aeq, beq, lo, hi = _lin_cons(args, n, 'linprog', 1)
    opts = _Opts('linprog', _arg(args, 7), n, 'linprog')
    alg = opts.algorithm()
    method = 'highs-ipm' if alg.startswith('interior-point') else 'highs-ds'
    o = {'disp': False, 'primal_feasibility_tolerance': opts.num('ConstraintTolerance', 1e-7),
         'dual_feasibility_tolerance': opts.num('OptimalityTolerance', 1e-7)}
    mt = opts.num('MaxTime', math.inf)
    if math.isfinite(mt):
        o['time_limit'] = mt
    mi = opts['MaxIterations']
    if isinstance(mi, float) and math.isfinite(mi):
        o['maxiter'] = int(mi)
    res = O.linprog(f, A_ub=A, b_ub=b, A_eq=Aeq, b_eq=beq, bounds=np.column_stack([lo, hi]), method=method, options=o)
    flag = {0: 1, 1: 0, 2: -2, 3: -3, 4: -4}.get(res.status, -4)
    msg = {1: 'Optimal solution found.', 0: f'Stopped: the iteration or time limit was reached. ({res.message})',
           -2: 'No feasible point found: the constraints cannot all be met.', -3: 'The problem is unbounded: the objective has no minimum.',
           -4: f'Stopped: numerical difficulties. ({res.message})'}[flag]
    if opts.display() in ('final', 'iter') or (opts.display() == 'notify' and flag <= 0):
        R.write(f'\n{msg}\n\n')
    if res.x is None:
        x = EMPTY()
        fval = EMPTY()
        lam = Struct.scalar({k: EMPTY() for k in ('ineqlin', 'eqlin', 'upper', 'lower')})
        viol = EMPTY()
    else:
        xv = np.asarray(res.x, F64)
        x = out(xv.reshape(-1, 1))
        fval = float(res.fun)
        # HiGHS' marginals are the objective's change per unit of each right side; the multipliers are their negatives,
        # the lower bounds' as they are
        col = lambda m, k: out(np.asarray(m, F64).reshape(-1, 1)) if k else np.zeros((0, 1))
        lam = Struct.scalar({'ineqlin': col(-np.asarray(res.ineqlin.marginals), A is not None),
                             'eqlin': col(-np.asarray(res.eqlin.marginals), Aeq is not None),
                             'upper': col(-np.asarray(res.upper.marginals), True), 'lower': col(np.asarray(res.lower.marginals), True)})
        viol = max(float(np.max(A @ xv - b, initial=0)) if A is not None else 0.0,
                   float(np.max(np.abs(Aeq @ xv - beq), initial=0)) if Aeq is not None else 0.0,
                   float(np.max(lo - xv, initial=0)), float(np.max(xv - hi, initial=0)))
    if nargout <= 1:
        return x
    output = Struct.scalar({'iterations': float(res.nit), 'constrviolation': viol, 'message': Char.of(msg),
                            'algorithm': Char.of(f"{alg} (HiGHS {'interior point' if method == 'highs-ipm' else 'dual simplex'})"),
                            'firstorderopt': 0.0 if flag == 1 else EMPTY()})
    return (x, fval, float(flag), output, lam)[:nargout]


@bi('intlinprog', nout=4)
def intlinprog(nargout, *args):
    from scipy import optimize as O
    args, prob = _problem(args, ('f', 'intcon', 'Aineq', 'bineq', 'Aeq', 'beq', 'lb', 'ub', 'x0', 'options'), 'intlinprog')
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'intlinprog')
    f = _vec(args[0])
    n = f.size
    args = list(args) + [EMPTY()] * (10 - len(args))
    intcon = darr(args[1]).reshape(-1) if numel(args[1]) else np.zeros(0)
    if intcon.size and (np.any(intcon != np.round(intcon)) or np.any(intcon < 1) or np.any(intcon > n)):
        raise err('optim:intlinprog:InvalidIntcon', f'intcon must hold whole numbers from 1 to {n}: the variables that are integers.', 'intlinprog')
    A, b, Aeq, beq, lo, hi = _lin_cons(args, n, 'intlinprog', 2)
    optarg = _arg(args, 9) if not isinstance(_arg(args, 8), (OptimOptions, Struct)) else _arg(args, 8)
    opts = _Opts('intlinprog', optarg, n, 'intlinprog')
    integrality = np.zeros(n)
    integrality[intcon.astype(int) - 1] = 1
    cons = []
    if A is not None:
        cons.append(O.LinearConstraint(A, -np.inf, b))
    if Aeq is not None:
        cons.append(O.LinearConstraint(Aeq, beq, beq))
    o = {'disp': opts.display() == 'iter', 'time_limit': opts.num('MaxTime', 7200.0), 'mip_rel_gap': opts.num('RelativeGapTolerance', 1e-4),
         'node_limit': opts.count('MaxNodes', 10 ** 7)}
    res = O.milp(f, integrality=integrality, bounds=O.Bounds(lo, hi), constraints=cons, options=o)
    if res.status == 0:
        flag, msg = 1, 'Optimal solution found: the gap to the bound is within RelativeGapTolerance.'
    elif res.status == 1:
        flag, msg = (2, 'Stopped at a limit with a feasible point.') if res.x is not None else (0, 'Stopped at a limit with no feasible point found.')
    elif res.status == 2:
        flag, msg = -2, 'No feasible point found: the problem is infeasible.'
    elif res.status == 3:
        flag, msg = -3, 'The problem is unbounded.'
    else:
        flag, msg = -9, f'Stopped: {res.message}'
    if opts.display() in ('final', 'iter') or (opts.display() == 'notify' and flag <= 0):
        R.write(f'\n{msg}\n\n')
    if res.x is None:
        x, fval = EMPTY(), EMPTY()
        viol = EMPTY()
    else:
        xv = np.asarray(res.x, F64)
        xv[integrality == 1] = np.round(xv[integrality == 1])
        x = out(xv.reshape(-1, 1))
        fval = float(f @ xv)
        viol = max(float(np.max(A @ xv - b, initial=0)) if A is not None else 0.0,
                   float(np.max(np.abs(Aeq @ xv - beq), initial=0)) if Aeq is not None else 0.0,
                   float(np.max(lo - xv, initial=0)), float(np.max(xv - hi, initial=0)))
    if nargout <= 1:
        return x
    gap = getattr(res, 'mip_gap', None)
    bound = getattr(res, 'mip_dual_bound', None)
    output = Struct.scalar({'relativegap': float(gap) if gap is not None else EMPTY(),
                            'absolutegap': float(abs(fval - bound)) if bound is not None and res.x is not None else EMPTY(),
                            'numfeaspoints': 1.0 if res.x is not None else 0.0,
                            'numnodes': float(getattr(res, 'mip_node_count', 0) or 0), 'constrviolation': viol,
                            'message': Char.of(msg)})
    return (x, fval, float(flag), output)[:nargout]


# ---- several objectives: fminimax, fgoalattain ------------------------------------------------------------------------------

def _multi(fn, F, cons, x0, opts, run, make_obj):
    """min t over (x, t) with each objective's constraint F_i(x) <= g_i + w_i t
    (or |F_i| for the first ones), and the problem's own constraints, by SLSQP."""
    from scipy import optimize as O
    n = x0.size
    v0 = F.value(x0)
    m = v0.size
    rows = make_obj(v0)          # functions (x, t) -> list of g(x) - t*w >= 0 forms
    z0 = np.concatenate([x0, [rows['t0']]])

    def ineq(z):
        x, t = z[:n], z[n]
        return rows['g'](F.value(x), t)

    def ineq_jac(z):
        x, t = z[:n], z[n]
        return rows['gj'](F.value(x), F.grad(x), t)
    cons_list = [{'type': 'ineq', 'fun': ineq, 'jac': ineq_jac}]
    if cons.A.size:
        cons_list.append({'type': 'ineq', 'fun': lambda z: cons.b - cons.A @ z[:n], 'jac': lambda z: np.hstack([-cons.A, np.zeros((cons.A.shape[0], 1))])})
    if cons.Aeq.size:
        cons_list.append({'type': 'eq', 'fun': lambda z: cons.Aeq @ z[:n] - cons.beq, 'jac': lambda z: np.hstack([cons.Aeq, np.zeros((cons.Aeq.shape[0], 1))])})
    if cons.nonlcon is not None:
        c, ceq, _, _ = cons.nl(x0)
        if c.size:
            cons_list.append({'type': 'ineq', 'fun': lambda z: -cons.nl(z[:n])[0], 'jac': lambda z: np.hstack([-cons.nl(z[:n])[2], np.zeros((cons.nl(z[:n])[2].shape[0], 1))])})
        if ceq.size:
            cons_list.append({'type': 'eq', 'fun': lambda z: cons.nl(z[:n])[1], 'jac': lambda z: np.hstack([cons.nl(z[:n])[3], np.zeros((cons.nl(z[:n])[3].shape[0], 1))])})
    bounds = O.Bounds(np.concatenate([cons.lb, [-np.inf]]), np.concatenate([cons.ub, [np.inf]]))

    def cb(intermediate_result):
        z = np.asarray(getattr(intermediate_result, 'x', intermediate_result), F64)
        try:
            run.step(z[:n], F.value(z[:n]), F.count, None, cons.violation(z[:n]))
        except _Stop:
            raise StopIteration
    res = O.minimize(lambda z: z[n], z0, jac=lambda z: np.concatenate([np.zeros(n), [1.0]]), method='SLSQP', bounds=bounds,
                     constraints=cons_list, callback=cb, options={'ftol': 1e-12, 'maxiter': opts.count('MaxIterations', 400)})
    return np.asarray(res.x[:n], F64), float(res.x[n]), res


@bi('fminimax', nout=6)
def fminimax(nargout, *args):
    args, prob = _problem(args, ('objective', 'x0', 'Aineq', 'bineq', 'Aeq', 'beq', 'lb', 'ub', 'nonlcon', 'options'), 'fminimax')
    if len(args) < 2:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'fminimax')
    f = _fh(args[0], 'fminimax')
    x0 = darr(args[1])
    shape, n = x0.shape, x0.size
    opts = _Opts('fminimax', _arg(args, 9), n, 'fminimax')
    cons = _Cons(n, shape, _arg(args, 2), _arg(args, 3), _arg(args, 4), _arg(args, 5), _arg(args, 6), _arg(args, 7), _arg(args, 8), opts, 'fminimax')
    F = _Fun(f, shape, opts, extra=tuple(args[10:]), vector=True, grad=opts.flag('SpecifyObjectiveGradient'))
    run = _Run('fminimax', opts, shape, 'con')
    k = opts.count('AbsoluteMaxObjectiveCount', 0)
    x = np.clip(x0.reshape(-1).astype(F64), cons.lb, cons.ub)

    def make(v0):
        m = v0.size
        sign_rows = np.concatenate([np.ones(m), -np.ones(min(k, m))])
        idx = np.concatenate([np.arange(m), np.arange(min(k, m))])

        def g(v, t):
            return t - sign_rows * v[idx]

        def gj(v, J, t):
            return np.hstack([-(sign_rows[:, None] * J[idx]), np.ones((idx.size, 1))])
        return {'g': g, 'gj': gj, 't0': float(np.max(np.concatenate([v0, np.abs(v0[:k])])))}
    run.start(x, F.value(x), F.count, None, cons.violation(x))
    try:
        x, t, res = _multi('fminimax', F, cons, x, opts, run, make)
    except (_Stop, StopIteration):
        x = run.prev
        res = None
    v = F.value(x)
    feas = cons.violation(x)
    vals = np.concatenate([v, np.abs(v[:k])])
    if run.stopped:
        flag, msg = -1, 'Stopped by an output or plot function.'
    elif feas > opts.num('ConstraintTolerance', 1e-6):
        flag, msg = -2, f'No feasible point found: the constraints are violated by {feas:.3g}.'
    elif res is not None and res.status == 0:
        flag, msg = 4, f'Local minimum possible: the largest objective is {float(np.max(vals)):.6g}, the constraints met.'
    else:
        flag, msg = 0, f'Stopped: {res.message if res is not None else ""}'
    run.done(x, v, F.count, None, feas)
    _finish(run, flag, msg)
    xo = out(x.reshape(shape))
    if nargout <= 1:
        return xo
    fshape = F.out_shape or (v.size, 1)
    output = _outstruct(run, F.count, 'sqp (SciPy SLSQP on the problem with the largest objective as a variable)', msg, constrviolation=feas)
    r = [xo, out(v.reshape(fshape)), float(np.max(vals)), float(flag), output,
         _lambda_struct(cons.lambdas(x, np.zeros(n), 1e-7)[0])]
    return tuple(r[:nargout])


@bi('fgoalattain', nout=6)
def fgoalattain(nargout, *args):
    args, prob = _problem(args, ('objective', 'x0', 'goal', 'weight', 'Aineq', 'bineq', 'Aeq', 'beq', 'lb', 'ub', 'nonlcon', 'options'), 'fgoalattain')
    if len(args) < 4:
        raise err('MATLAB:minrhs', 'Not enough input arguments.', 'fgoalattain')
    f = _fh(args[0], 'fgoalattain')
    x0 = darr(args[1])
    shape, n = x0.shape, x0.size
    goal = _vec(args[2])
    weight = _vec(args[3])
    if weight.size != goal.size:
        raise err('optim:fgoalattain:InvalidWeightAndGoalSizes', 'goal and weight must have as many elements.', 'fgoalattain')
    opts = _Opts('fgoalattain', _arg(args, 11), n, 'fgoalattain')
    cons = _Cons(n, shape, _arg(args, 4), _arg(args, 5), _arg(args, 6), _arg(args, 7), _arg(args, 8), _arg(args, 9), _arg(args, 10), opts, 'fgoalattain')
    F = _Fun(f, shape, opts, extra=tuple(args[12:]), vector=True, grad=opts.flag('SpecifyObjectiveGradient'))
    run = _Run('fgoalattain', opts, shape, 'con')
    keq = opts.count('EqualityGoalCount', 0)
    x = np.clip(x0.reshape(-1).astype(F64), cons.lb, cons.ub)

    def make(v0):
        if v0.size != goal.size:
            raise err('optim:fgoalattain:InvalidFunSize', 'The objective must return as many values as goal has.', 'fgoalattain')
        m = v0.size
        # F_i - w_i t <= goal_i, and for the first keq also >= (as equalities by two sides)
        rows = np.concatenate([np.arange(m), np.arange(min(keq, m))])
        sgn = np.concatenate([np.ones(m), -np.ones(min(keq, m))])

        def g(v, t):
            return sgn * (goal[rows] - v[rows]) + weight[rows] * t * np.where(sgn > 0, 1, 1)

        def gj(v, J, t):
            return np.hstack([-(sgn[:, None] * J[rows]), weight[rows][:, None]])
        w = np.where(weight != 0, weight, np.inf)
        t0 = float(np.max(np.where(np.isfinite(w), (v0 - goal) / w, -np.inf), initial=0.0))
        return {'g': g, 'gj': gj, 't0': t0}
    run.start(x, F.value(x), F.count, None, cons.violation(x))
    try:
        x, t, res = _multi('fgoalattain', F, cons, x, opts, run, make)
    except (_Stop, StopIteration):
        x = run.prev
        t, res = math.nan, None
    v = F.value(x)
    feas = cons.violation(x)
    if run.stopped:
        flag, msg = -1, 'Stopped by an output or plot function.'
    elif feas > opts.num('ConstraintTolerance', 1e-6):
        flag, msg = -2, f'No feasible point found: the constraints are violated by {feas:.3g}.'
    elif res is not None and res.status == 0:
        flag, msg = 4, f'Local minimum possible: the attainment factor is {t:.6g}, the constraints met.'
    else:
        flag, msg = 0, f'Stopped: {res.message if res is not None else ""}'
    run.done(x, v, F.count, None, feas)
    _finish(run, flag, msg)
    xo = out(x.reshape(shape))
    if nargout <= 1:
        return xo
    fshape = F.out_shape or (v.size, 1)
    output = _outstruct(run, F.count, 'sqp (SciPy SLSQP on the problem with the attainment factor as a variable)', msg, constrviolation=feas)
    r = [xo, out(v.reshape(fshape)), t, float(flag), output, _lambda_struct(cons.lambdas(x, np.zeros(n), 1e-7)[0])]
    return tuple(r[:nargout])


# ---- plot functions --------------------------------------------------------------------------------------------------------

def _plot_point(name, x, y, ylabel, title, state, color=(0.0, 0.447, 0.741), bars=False):
    """One point more on the current axes' line (or bars) for a plot function."""
    from .graphics import gca_, plot, bar
    ax = gca_()
    line = next((c for c in ax.children if c.valid and c.props.get('Tag') == name), None)
    if state == 'init' or line is None:
        for c in list(ax.children):
            c.delete_handle()
        if bars:
            line = bar(1, np.atleast_1d(np.asarray(y, float)).reshape(1, -1))
        else:
            line = plot(1, np.array([[float(x)]]), np.array([[float(y)]]), Char.of('o'))
            line.props['MarkerFaceColor'] = color
            line.props['Color'] = color
            line.props['LineStyle'] = 'none'
        line.props['Tag'] = name
        ax.xlabel.props['String'] = 'Iteration' if not bars else 'Number of variables'
        ax.ylabel.props['String'] = ylabel
    elif not bars and state == 'iter':
        # a point for each iteration: the start's, given at 'init' and again at its 'iter', once
        X = np.asarray(line.props['XData'], float).reshape(-1)
        Y = np.asarray(line.props['YData'], float).reshape(-1)
        if X.size and X[-1] == float(x):
            Y[-1] = float(y)
        else:
            X, Y = np.append(X, float(x)), np.append(Y, float(y))
        line.props['XData'] = X.reshape(1, -1)
        line.props['YData'] = Y.reshape(1, -1)
    elif bars:
        yy = np.atleast_1d(np.asarray(y, float)).reshape(1, -1)
        line.props['XData'] = np.arange(1, yy.size + 1, dtype=float).reshape(1, -1)
        line.props['YData'] = yy
    ax.title.props['String'] = title
    ax.touch()
    return line


def _field(v, k):
    try:
        return v.get1(k)
    except Exception:
        return None


@bi('optimplotfval', arr=False)
def optimplotfval(nargout, *args):
    x, v, state = args[0], args[1], py_str(args[2])
    f = darr(_field(v, 'fval'))
    val = float(np.sum(f ** 2)) if f.size > 1 else float(f.reshape(-1)[0])
    _plot_point('optimplotfval', num(_field(v, 'iteration')), val, 'Function value', f'Current Function Value: {val:g}', state)
    return False if nargout else None


@bi('optimplotx', arr=False)
def optimplotx(nargout, *args):
    x, state = darr(args[0]).reshape(-1), py_str(args[2])
    _plot_point('optimplotx', 0, x, 'Current point', 'Current Point', state, bars=True)
    return False if nargout else None


@bi('optimplotfirstorderopt', arr=False)
def optimplotfirstorderopt(nargout, *args):
    v, state = args[1], py_str(args[2])
    o = _field(v, 'firstorderopt')
    if o is None or not numel(o):
        return False if nargout else None
    _plot_point('optimplotfirstorderopt', num(_field(v, 'iteration')), num(o), 'First-order optimality',
                f'First-order Optimality: {num(o):g}', state, color=(0.85, 0.325, 0.098))
    return False if nargout else None


@bi('optimplotfunccount', arr=False)
def optimplotfunccount(nargout, *args):
    v, state = args[1], py_str(args[2])
    n = num(_field(v, 'funccount'))
    _plot_point('optimplotfunccount', num(_field(v, 'iteration')), n, 'Function evaluations', f'Total Function Evaluations: {n:g}', state,
                color=(0.494, 0.184, 0.556))
    return False if nargout else None


@bi('optimplotconstrviolation', arr=False)
def optimplotconstrviolation(nargout, *args):
    v, state = args[1], py_str(args[2])
    c = _field(v, 'constrviolation')
    if c is None or not numel(c):
        return False if nargout else None
    _plot_point('optimplotconstrviolation', num(_field(v, 'iteration')), num(c), 'Constraint violation',
                f'Max Constraint Violation: {num(c):g}', state, color=(0.466, 0.674, 0.188))
    return False if nargout else None


@bi('optimplotstepsize', arr=False)
def optimplotstepsize(nargout, *args):
    v, state = args[1], py_str(args[2])
    s = _field(v, 'stepsize')
    if s is None or not numel(s):
        return False if nargout else None
    _plot_point('optimplotstepsize', num(_field(v, 'iteration')), num(s), 'Step size', f'Current Step Size: {num(s):g}', state,
                color=(0.301, 0.745, 0.933))
    return False if nargout else None


@bi('optimplotresnorm', arr=False)
def optimplotresnorm(nargout, *args):
    v, state = args[1], py_str(args[2])
    r = _field(v, 'resnorm')
    if r is None or not numel(r):
        return False if nargout else None
    _plot_point('optimplotresnorm', num(_field(v, 'iteration')), num(r), 'Sum of squares', f'Current Sum of Squares: {num(r):g}', state)
    return False if nargout else None
