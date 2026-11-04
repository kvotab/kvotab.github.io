"""Global optimization: ga, particleswarm, simulannealbnd, patternsearch,
surrogateopt, gamultiobj, and MultiStart and GlobalSearch with
createOptimProblem and run. All of them are PyLAB's own versions of the
standard methods (their help says which), drawing from the generator rng
sets; constraints other than bounds are handled by penalties (ga,
particleswarm, simulannealbnd and surrogateopt take bounds only, or
bounds and integers)."""
import math
import time

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, is_str, darr, out
from ..values import MError, Obj, FH, Char, Cell, Struct, EMPTY, numel, py_str
from .. import runtime as R
from . import optim as OP


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        return _register(*names, **kw)(f)
    return deco


def _rs():
    from .elmat import RNG
    return RNG.rs


# the solvers and their options, as optimoptions knows them
_NEW = {
    'ga': ((), {'PopulationSize': '50 when numberOfVariables <= 5, else 200', 'MaxGenerations': '100*numberOfVariables', 'MaxStallGenerations': 50,
                'FunctionTolerance': 1e-6, 'ConstraintTolerance': 1e-3, 'EliteCount': '0.05*PopulationSize', 'CrossoverFraction': 0.8,
                'InitialPopulationMatrix': None, 'InitialPopulationRange': None, 'FitnessLimit': -math.inf, 'MaxTime': math.inf,
                'HybridFcn': None, 'UseVectorized': False, 'UseParallel': False, 'MutationFcn': None, 'CrossoverFcn': None, 'SelectionFcn': None}),
    'particleswarm': ((), {'SwarmSize': 'min(100,10*numberOfVariables)', 'MaxIterations': '200*numberOfVariables', 'MaxStallIterations': 20,
                           'FunctionTolerance': 1e-6, 'InertiaRange': None, 'SelfAdjustmentWeight': 1.49, 'SocialAdjustmentWeight': 1.49,
                           'MinNeighborsFraction': 0.25, 'InitialSwarmMatrix': None, 'InitialSwarmSpan': 2000.0, 'ObjectiveLimit': -math.inf,
                           'MaxTime': math.inf, 'HybridFcn': None, 'UseVectorized': False, 'UseParallel': False}),
    'simulannealbnd': ((), {'InitialTemperature': 100.0, 'MaxIterations': math.inf, 'MaxFunctionEvaluations': '3000*numberOfVariables',
                            'MaxStallIterations': '500*numberOfVariables', 'FunctionTolerance': 1e-6, 'ReannealInterval': 100.0,
                            'ObjectiveLimit': -math.inf, 'MaxTime': math.inf, 'HybridFcn': None, 'TemperatureFcn': None, 'AnnealingFcn': None}),
    'patternsearch': ((), {'MeshTolerance': 1e-6, 'StepTolerance': 1e-6, 'FunctionTolerance': 1e-6, 'ConstraintTolerance': 1e-6,
                           'MaxIterations': '100*numberOfVariables', 'MaxFunctionEvaluations': '2000*numberOfVariables', 'InitialMeshSize': 1.0,
                           'MeshExpansionFactor': 2.0, 'MeshContractionFactor': 0.5, 'UseCompletePoll': False, 'PollMethod': 'GPSPositiveBasis2N',
                           'MaxTime': math.inf, 'UseParallel': False}),
    'surrogateopt': ((), {'MaxFunctionEvaluations': 200.0, 'MinSurrogatePoints': 'max(20,2*nvar)', 'InitialPoints': None, 'ObjectiveLimit': -math.inf,
                          'MaxTime': math.inf, 'UseParallel': False}),
    'gamultiobj': ((), {'PopulationSize': '50 when numberOfVariables <= 5, else 200', 'MaxGenerations': '200*numberOfVariables',
                        'MaxStallGenerations': 100, 'FunctionTolerance': 1e-4, 'ConstraintTolerance': 1e-3, 'ParetoFraction': 0.35,
                        'CrossoverFraction': 0.8, 'InitialPopulationMatrix': None, 'MaxTime': math.inf, 'UseVectorized': False}),
}
for _s, _v in _NEW.items():
    OP._SOLVERS[_s] = _v
    for _k, _d in _v[1].items():
        if _k not in OP._COMMON:
            OP._COMMON[_k] = (_d, 'num' if isinstance(_d, float) and _k not in ('InitialSwarmSpan',) else 'any')
for _k in ('PopulationSize', 'MaxGenerations', 'MaxStallGenerations', 'EliteCount', 'SwarmSize', 'MaxStallIterations', 'MinSurrogatePoints'):
    OP._COMMON[_k] = (OP._COMMON.get(_k, (None,))[0], 'any')


def _opt(opts, k, default):
    v = opts.o.get(k)
    if v is None or (isinstance(v, np.ndarray) and v.size == 0) or isinstance(v, Char):
        return default
    if isinstance(v, (float, int, bool)):
        return v
    a = np.asarray(darr(v), float)
    return float(a.reshape(-1)[0]) if a.size == 1 else a


class _Problem:
    """The objective and constraints as the global solvers see them: f(x) for a row, and a penalty for infeasibility."""

    def __init__(self, f, n, fn, A=None, b=None, Aeq=None, beq=None, lb=None, ub=None, nonlcon=None, intcon=None, opts=None, extra=()):
        self.f = OP._fh(f, fn)
        self.n = n
        self.fn = fn
        self.cons = OP._Cons(n, (1, n), A, b, Aeq, beq, lb, ub, nonlcon, opts, fn)
        if self.cons.bad_bounds:
            raise err(f'globaloptim:{fn}:bounds', 'A lower bound is above its upper bound.', fn)
        self.lb, self.ub = self.cons.lb, self.cons.ub
        self.intcon = [int(i) - 1 for i in np.asarray(darr(intcon)).reshape(-1)] if intcon is not None and numel(intcon) else []
        self.count = 0
        self.extra = extra
        self.vectorized = False

    def __call__(self, x):
        self.count += 1
        v = self.f.scall(1, out(np.asarray(x, float).reshape(1, -1)), *self.extra)
        a = np.asarray(darr(v), float).reshape(-1)
        if a.size != 1:
            raise err(f'globaloptim:{self.fn}:objective', 'The objective gives one number (a scalar).', self.fn)
        return float(a[0])

    def many(self, X):
        return np.array([self(x) for x in X])

    def violation(self, x):
        if not (self.cons.A.size or self.cons.Aeq.size or self.cons.nonlcon is not None):
            return float(np.max(np.concatenate([[0.0], self.lb - x, x - self.ub])))
        return float(self.cons.violation(np.asarray(x, float)))

    def fix(self, X):
        X = np.clip(X, self.lb, self.ub)
        if self.intcon:
            X[..., self.intcon] = np.round(X[..., self.intcon])
            X = np.clip(X, self.lb, self.ub)
        return X

    def span(self, default=1.0):
        lo = np.where(np.isfinite(self.lb), self.lb, np.where(np.isfinite(self.ub), self.ub - default, -default / 2))
        hi = np.where(np.isfinite(self.ub), self.ub, lo + default)
        return lo, hi


def _output(**kw):
    return Struct.scalar({k: (Char.of(v) if isinstance(v, str) else float(v) if isinstance(v, (int, float, np.floating)) else v) for k, v in kw.items()})


def _say(display, text):
    if display not in ('off', 'none'):
        R.write(text + '\n')


def _hybrid(opts, prob, x, fx, fn):
    h = opts.o.get('HybridFcn')
    if h is None or (isinstance(h, np.ndarray) and h.size == 0):
        return x, fx
    name = py_str(h) if is_str(h) else (h.name() if isinstance(h, FH) else '')
    name = name.lstrip('@')
    if name not in ('fminsearch', 'fminunc', 'fmincon', 'patternsearch'):
        raise err(f'globaloptim:{fn}:HybridFcn', "HybridFcn is 'fminsearch', 'fminunc', 'fmincon' or 'patternsearch'.", fn)
    x0 = out(np.asarray(x, float).reshape(1, -1))
    quiet = OP.optimoptions(1, Char.of(name), Char.of('Display'), Char.of('off')) if name != 'fminsearch' else Struct.scalar({'Display': Char.of('off')})
    if name in ('fminsearch', 'fminunc'):
        r = R._builtin(name, prob.f, x0, quiet)
    elif name == 'fmincon':
        r = R._builtin('fmincon', prob.f, x0, EMPTY(), EMPTY(), EMPTY(), EMPTY(), out(prob.lb.reshape(1, -1)), out(prob.ub.reshape(1, -1)), EMPTY(), quiet)
    else:
        r = patternsearch(1, prob.f, x0, EMPTY(), EMPTY(), EMPTY(), EMPTY(), out(prob.lb.reshape(1, -1)), out(prob.ub.reshape(1, -1)), EMPTY(), quiet)
    xn = np.asarray(darr(r), float).reshape(-1)
    fn_ = prob(xn)
    return (xn, fn_) if fn_ <= fx and prob.violation(xn) <= 1e-6 else (x, fx)


# ---- the genetic algorithm ---------------------------------------------------------------------------------------------------------------

def _ga_args(args, fn):
    nargchk(args, 2, 11, fn)
    a = list(args) + [None] * (11 - len(args))
    f, n = a[0], int(num(a[1]))
    A, b, Aeq, beq, lb, ub, nonlcon, intcon, options = (OP._arg(a, i) for i in range(2, 11))
    if isinstance(intcon, (OP.OptimOptions, Struct)) and options is None:
        intcon, options = None, intcon
    return f, n, A, b, Aeq, beq, lb, ub, nonlcon, intcon, options


def _scores(prob, X, fx):
    """Fitness with constraints: feasible points by their value, infeasible ones after all of them by their violation (Deb's rule)."""
    viol = np.array([prob.violation(x) for x in X])
    worst = np.max(fx[viol <= 1e-12]) if np.any(viol <= 1e-12) else 0.0
    return np.where(viol <= 1e-12, fx, worst + 1 + viol), viol


@bi('ga', nout=6)
def ga(nargout, *args):
    """[x, fval, exitflag, output, population, scores] = ga(fun, nvars, A, b, Aeq, beq, lb, ub, nonlcon, intcon, options): a minimum by a genetic algorithm."""
    f, n, A, b, Aeq, beq, lb, ub, nonlcon, intcon, options = _ga_args(args, 'ga')
    opts = OP._Opts('ga', options, n, 'ga')
    prob = _Problem(f, n, 'ga', A, b, Aeq, beq, lb, ub, nonlcon, intcon, opts)
    rs = _rs()
    P = int(_opt(opts, 'PopulationSize', 50 if n <= 5 else 200))
    G = int(_opt(opts, 'MaxGenerations', 100 * n))
    stall = int(_opt(opts, 'MaxStallGenerations', 50))
    ftol = float(_opt(opts, 'FunctionTolerance', 1e-6))
    elite = int(_opt(opts, 'EliteCount', math.ceil(0.05 * P)))
    xfrac = float(_opt(opts, 'CrossoverFraction', 0.8))
    flim = float(_opt(opts, 'FitnessLimit', -math.inf))
    tmax = float(_opt(opts, 'MaxTime', math.inf))
    display = opts.display()
    lo, hi = prob.span()
    rng_ = opts.o.get('InitialPopulationRange')
    if rng_ is not None and numel(rng_):
        R0 = np.asarray(darr(rng_), float)
        lo, hi = np.broadcast_to(R0[0], (n,)), np.broadcast_to(R0[1], (n,))
    lo = np.where(np.isfinite(prob.lb), np.maximum(lo, prob.lb), lo)
    hi = np.where(np.isfinite(prob.ub), np.minimum(hi, prob.ub), hi)
    X = lo + rs.random_sample((P, n)) * (hi - lo)
    ip = opts.o.get('InitialPopulationMatrix')
    if ip is not None and numel(ip):
        I0 = np.asarray(darr(ip), float).reshape(-1, n)
        X[:I0.shape[0]] = I0[:P]
    X = prob.fix(X)
    fx = prob.many(X)
    t0 = time.time()
    best_hist = []
    exitflag, msg = 0, 'The maximum number of generations was reached.'
    gen = 0
    for gen in range(1, G + 1):
        sc, viol = _scores(prob, X, fx)
        order = np.argsort(sc, kind='stable')
        best_hist.append(sc[order[0]])
        if fx[order[0]] <= flim and viol[order[0]] <= 1e-12:
            exitflag, msg = 5, 'The fitness value reached FitnessLimit.'
            break
        if len(best_hist) > stall:
            old = best_hist[-stall - 1]
            if abs(old - best_hist[-1]) / max(1.0, abs(best_hist[-1])) <= ftol:
                exitflag, msg = 1, 'The average change in the best fitness value is less than FunctionTolerance.'
                break
        if time.time() - t0 > tmax:
            exitflag, msg = -5, 'The time limit was exceeded.'
            break
        # rank scaling, then stochastic uniform selection
        ranks = np.empty(P)
        ranks[order] = np.arange(1, P + 1)
        expect = 1 / np.sqrt(ranks)
        expect = expect * (2 * (P - elite)) / expect.sum()
        cum = np.cumsum(expect)
        step = cum[-1] / (2 * (P - elite))
        ptrs = rs.random_sample() * step + step * np.arange(2 * (P - elite))
        parents = np.searchsorted(cum, ptrs)
        parents = rs.permutation(np.minimum(parents, P - 1))
        nx = int(round(xfrac * (P - elite)))
        kids = [X[order[:elite]]]
        # scattered crossover
        p1, p2 = X[parents[0:2 * nx:2]], X[parents[1:2 * nx:2]]
        mask = rs.random_sample((nx, n)) < 0.5
        kids.append(np.where(mask, p1, p2))
        # Gaussian mutation, its scale shrinking to nothing by the last generation
        nm = P - elite - nx
        pm = X[parents[2 * nx:2 * nx + nm]]
        scale = (hi - lo) * (1 - gen / G) if np.all(np.isfinite(hi - lo)) else np.ones(n) * (1 - gen / G)
        kids.append(pm + rs.standard_normal((nm, n)) * scale)
        Xn = prob.fix(np.vstack(kids))
        fn_ = np.concatenate([fx[order[:elite]], prob.many(Xn[elite:])])
        X, fx = Xn, fn_
    sc, viol = _scores(prob, X, fx)
    i = int(np.argmin(sc))
    x, fval = X[i], fx[i]
    if viol[i] > float(_opt(opts, 'ConstraintTolerance', 1e-3)):
        exitflag, msg = -2, 'No feasible point was found.'
    x, fval = _hybrid(opts, prob, x, fval, 'ga')
    _say(display, f'Optimization finished: {msg}')
    output = _output(problemtype='nonlinearconstr' if nonlcon is not None else ('integerconstraints' if prob.intcon else 'boundconstraints'),
                     generations=gen, funccount=prob.count, message=msg, maxconstraint=float(viol[i]))
    res = (out(np.asarray(x).reshape(1, -1)), float(fval), float(exitflag), output, out(X), out(fx.reshape(-1, 1)))
    return res[:nargout] if nargout > 1 else res[0]


# ---- particle swarm ---------------------------------------------------------------------------------------------------------------------------

@bi('particleswarm', nout=4)
def particleswarm(nargout, *args):
    """[x, fval, exitflag, output] = particleswarm(fun, nvars, lb, ub, options): a minimum within bounds by a particle swarm."""
    nargchk(args, 2, 5, 'particleswarm')
    a = list(args) + [None] * (5 - len(args))
    n = int(num(a[1]))
    opts = OP._Opts('particleswarm', OP._arg(a, 4), n, 'particleswarm')
    prob = _Problem(a[0], n, 'particleswarm', lb=OP._arg(a, 2), ub=OP._arg(a, 3), opts=opts)
    rs = _rs()
    S = int(_opt(opts, 'SwarmSize', min(100, 10 * n)))
    maxit = int(_opt(opts, 'MaxIterations', 200 * n))
    stall = int(_opt(opts, 'MaxStallIterations', 20))
    ftol = float(_opt(opts, 'FunctionTolerance', 1e-6))
    inr = _opt(opts, 'InertiaRange', np.array([0.1, 1.1]))
    inr = np.asarray(inr, float).reshape(-1) if np.size(inr) == 2 else np.array([0.1, 1.1])
    y1, y2 = float(_opt(opts, 'SelfAdjustmentWeight', 1.49)), float(_opt(opts, 'SocialAdjustmentWeight', 1.49))
    minN = max(2, int(math.floor(S * float(_opt(opts, 'MinNeighborsFraction', 0.25)))))
    span = float(_opt(opts, 'InitialSwarmSpan', 2000.0))
    olim = float(_opt(opts, 'ObjectiveLimit', -math.inf))
    lo, hi = prob.span(span)
    X = lo + rs.random_sample((S, n)) * (hi - lo)
    ism = opts.o.get('InitialSwarmMatrix')
    if ism is not None and numel(ism):
        I0 = np.asarray(darr(ism), float).reshape(-1, n)
        X[:I0.shape[0]] = I0[:S]
    X = prob.fix(X)
    V = (hi - lo) * (rs.random_sample((S, n)) * 2 - 1) if np.all(np.isfinite(hi - lo)) else rs.standard_normal((S, n))
    fx = prob.many(X)
    P, fp = X.copy(), fx.copy()
    W = inr[1]
    N = minN
    c = 0
    gbest = int(np.argmin(fp))
    hist = [fp[gbest]]
    exitflag, msg = 0, 'The maximum number of iterations was reached.'
    it = 0
    for it in range(1, maxit + 1):
        prev = fp[gbest]
        for i in range(S):
            nb = rs.choice(S, N, replace=False) if N < S else np.arange(S)
            g = nb[np.argmin(fp[nb])]
            u1, u2 = rs.random_sample(n), rs.random_sample(n)
            V[i] = W * V[i] + y1 * u1 * (P[i] - X[i]) + y2 * u2 * (P[g] - X[i])
            xn = X[i] + V[i]
            out_lo, out_hi = xn < prob.lb, xn > prob.ub
            V[i][out_lo | out_hi] = 0
            X[i] = prob.fix(xn)
            fx[i] = prob(X[i])
            if fx[i] < fp[i]:
                P[i], fp[i] = X[i].copy(), fx[i]
        gbest = int(np.argmin(fp))
        # the stall counter c falls with each improvement and grows otherwise; the inertia doubles while c is under 2 and
        # halves once it passes 5, so a swarm that stops improving slows down and settles
        if fp[gbest] < prev:
            c = max(0, c - 1)
            N = minN
        else:
            c += 1
            N = min(N + minN, S)
        if c < 2:
            W = min(2 * W, inr[1])
        elif c > 5:
            W = max(W / 2, inr[0])
        hist.append(fp[gbest])
        if fp[gbest] <= olim:
            exitflag, msg = -3, 'The objective reached ObjectiveLimit.'
            break
        if len(hist) > stall and abs(hist[-stall - 1] - hist[-1]) / max(1.0, abs(hist[-1])) <= ftol:
            exitflag, msg = 1, 'The relative change in the objective over MaxStallIterations iterations is less than FunctionTolerance.'
            break
    x, fval = _hybrid(opts, prob, P[gbest], fp[gbest], 'particleswarm')
    _say(opts.display(), f'Optimization ended: {msg}')
    output = _output(rngstate=Struct.scalar({}), iterations=it, funccount=prob.count, message=msg, hybridflag=EMPTY())
    res = (out(np.asarray(x).reshape(1, -1)), float(fval), float(exitflag), output)
    return res[:nargout] if nargout > 1 else res[0]


# ---- simulated annealing -------------------------------------------------------------------------------------------------------------------

@bi('simulannealbnd', nout=4)
def simulannealbnd(nargout, *args):
    """[x, fval, exitflag, output] = simulannealbnd(fun, x0, lb, ub, options): a minimum within bounds by simulated annealing."""
    nargchk(args, 2, 5, 'simulannealbnd')
    a = list(args) + [None] * (5 - len(args))
    x0 = np.asarray(darr(a[1]), float).reshape(-1)
    n = x0.size
    opts = OP._Opts('simulannealbnd', OP._arg(a, 4), n, 'simulannealbnd')
    prob = _Problem(a[0], n, 'simulannealbnd', lb=OP._arg(a, 2), ub=OP._arg(a, 3), opts=opts)
    rs = _rs()
    T0 = np.broadcast_to(np.asarray(_opt(opts, 'InitialTemperature', 100.0), float).reshape(-1), (n,)).astype(float)
    maxfev = int(_opt(opts, 'MaxFunctionEvaluations', 3000 * n))
    maxit = _opt(opts, 'MaxIterations', math.inf)
    stall = int(_opt(opts, 'MaxStallIterations', 500 * n))
    ftol = float(_opt(opts, 'FunctionTolerance', 1e-6))
    olim = float(_opt(opts, 'ObjectiveLimit', -math.inf))
    reanneal = int(_opt(opts, 'ReannealInterval', 100.0))
    x = prob.fix(x0.copy())
    fx = prob(x)
    best, fbest = x.copy(), fx
    k = 0
    accepted = 0
    hist = []
    exitflag, msg = 0, 'The maximum number of function evaluations was reached.'
    it = 0
    while prob.count < maxfev and it < maxit:
        it += 1
        T = T0 * 0.95 ** k
        k += 1
        # a step in a random direction, its length the temperature ('annealingfast'), kept within the bounds
        d = rs.standard_normal(n)
        d /= max(np.linalg.norm(d), 1e-300)
        xn = x + T * d
        out_ = (xn < prob.lb) | (xn > prob.ub)
        if out_.any():
            lo_, hi_ = np.where(np.isfinite(prob.lb), prob.lb, x - T), np.where(np.isfinite(prob.ub), prob.ub, x + T)
            xn[out_] = lo_[out_] + rs.random_sample(out_.sum()) * (hi_[out_] - lo_[out_])
        xn = prob.fix(xn)
        fn_ = prob(xn)
        delta = fn_ - fx
        if delta <= 0 or rs.random_sample() < 1 / (1 + math.exp(min(delta / max(np.max(T), 1e-300), 700))):
            x, fx = xn, fn_
            accepted += 1
            if accepted % reanneal == 0:
                k = 0
        if fx < fbest:
            best, fbest = x.copy(), fx
        hist.append(fbest)
        if fbest <= olim:
            exitflag, msg = 5, 'The objective reached ObjectiveLimit.'
            break
        if len(hist) > stall and abs(hist[-stall - 1] - hist[-1]) / max(1.0, abs(hist[-1])) <= ftol:
            exitflag, msg = 1, 'The average change in the best value over MaxStallIterations iterations is less than FunctionTolerance.'
            break
    x, fval = _hybrid(opts, prob, best, fbest, 'simulannealbnd')
    _say(opts.display(), f'Optimization terminated: {msg}')
    output = _output(iterations=it, funccount=prob.count, message=msg, temperature=out(T0 * 0.95 ** k), totaltime=0.0, problemtype='boundconstraints')
    res = (out(np.asarray(x).reshape(1, -1)), float(fval), float(exitflag), output)
    return res[:nargout] if nargout > 1 else res[0]


# ---- pattern search --------------------------------------------------------------------------------------------------------------------------

@bi('patternsearch', nout=4)
def patternsearch(nargout, *args):
    """[x, fval, exitflag, output] = patternsearch(fun, x0, A, b, Aeq, beq, lb, ub, nonlcon, options): a minimum by a generalized pattern search (polls along +-each coordinate, the mesh doubling after a success and halving after a failure)."""
    nargchk(args, 2, 10, 'patternsearch')
    a = list(args) + [None] * (10 - len(args))
    x0 = np.asarray(darr(a[1]), float).reshape(-1)
    n = x0.size
    options = OP._arg(a, 9)
    opts = OP._Opts('patternsearch', options, n, 'patternsearch')
    prob = _Problem(a[0], n, 'patternsearch', OP._arg(a, 2), OP._arg(a, 3), OP._arg(a, 4), OP._arg(a, 5), OP._arg(a, 6), OP._arg(a, 7), OP._arg(a, 8), opts=opts)
    meshtol = float(_opt(opts, 'MeshTolerance', 1e-6))
    maxit = int(_opt(opts, 'MaxIterations', 100 * n))
    maxfev = int(_opt(opts, 'MaxFunctionEvaluations', 2000 * n))
    delta0 = float(_opt(opts, 'InitialMeshSize', 1.0))
    expand = float(_opt(opts, 'MeshExpansionFactor', 2.0))
    contract = float(_opt(opts, 'MeshContractionFactor', 0.5))
    complete = bool(_opt(opts, 'UseCompletePoll', False))
    ctol = float(_opt(opts, 'ConstraintTolerance', 1e-6))
    cons = prob.cons
    constrained = bool(cons.A.size or cons.Aeq.size or cons.nonlcon is not None)

    def cvals(x):
        """The inequality (<= 0) and equality constraint values at x."""
        c = [cons.A @ x - cons.b] if cons.A.size else []
        ceq = [cons.Aeq @ x - cons.beq] if cons.Aeq.size else []
        if cons.nonlcon is not None:
            r = cons.nonlcon.scall(2, out(x.reshape(1, -1)))
            c.append(np.asarray(darr(r[0]), float).reshape(-1))
            ceq.append(np.asarray(darr(r[1]), float).reshape(-1))
        return (np.concatenate(c) if c else np.zeros(0)), (np.concatenate(ceq) if ceq else np.zeros(0))
    dirs = np.vstack([np.eye(n), -np.eye(n)])

    def gps(phi, x, delta, tol, budget):
        """The pattern search on phi within the bounds, from x with mesh delta, until the mesh is below tol."""
        fx = phi(x)
        its = 0
        while delta >= tol and prob.count < budget and its < maxit:
            its += 1
            best = None
            for d in dirs:
                y = x + delta * d
                if np.any(y < prob.lb - 1e-15) or np.any(y > prob.ub + 1e-15):
                    continue
                fy = phi(y)
                if fy < fx - 1e-15 * max(1, abs(fx)) and (best is None or fy < best[0]):
                    best = (fy, y)
                    if not complete:
                        break
            if best is not None:
                fx, x = best
                delta *= expand
            else:
                delta *= contract
        return x, fx, delta, its
    x = np.clip(x0, prob.lb, prob.ub)
    it = 0
    if not constrained:
        x, fx, delta, it = gps(prob, x, delta0, meshtol, maxfev)
        exitflag, msg = (1, 'The mesh size is less than MeshTolerance.') if delta < meshtol else (0, 'The maximum number of function evaluations or iterations was reached.')
    else:
        # the augmented Lagrangian (Powell, Hestenes, Rockafellar), each subproblem by the pattern search, tighter each time
        c, ceq = cvals(x)
        lam, lameq, mu = np.zeros(c.size), np.zeros(ceq.size), 10.0
        delta = delta0
        tol = max(meshtol, 1e-2)
        exitflag, msg = 0, 'The maximum number of function evaluations was reached.'
        for outer in range(60):
            def phi(z, lam=lam, lameq=lameq, mu=mu):
                cz, ceqz = cvals(z)
                return prob(z) + mu / 2 * float(np.sum(np.maximum(0, cz + lam / mu) ** 2) - np.sum((lam / mu) ** 2)) + float(lameq @ ceqz) + mu / 2 * float(ceqz @ ceqz)
            x, _, delta, its = gps(phi, x, max(delta, tol * 10), tol, maxfev)
            it += its
            c, ceq = cvals(x)
            viol = max(float(np.max(c, initial=0)), float(np.max(np.abs(ceq), initial=0)))
            lam = np.maximum(0, lam + mu * c)
            lameq = lameq + mu * ceq
            if viol > ctol:
                mu *= 5
            if tol <= meshtol and viol <= ctol:
                exitflag, msg = 1, 'The mesh size is less than MeshTolerance and the constraints are met.'
                break
            tol = max(meshtol, tol / 10)
            if prob.count >= maxfev:
                break
        fx = prob(x)
    if constrained and prob.violation(x) > ctol and exitflag == 1:
        exitflag, msg = -2, 'No feasible point was found.'
    _say(opts.display(), f'Optimization terminated: {msg}')
    output = _output(function=a[0] if isinstance(a[0], FH) else EMPTY(), problemtype='nonlinearconstr' if constrained else 'boundconstraints',
                     pollmethod='gpspositivebasis2n', maxconstraint=prob.violation(x), searchmethod=EMPTY(), iterations=it, funccount=prob.count,
                     meshsize=delta, message=msg)
    res = (out(x.reshape(1, -1)), float(fx), float(exitflag), output)
    return res[:nargout] if nargout > 1 else res[0]


# ---- a surrogate of radial basis functions -------------------------------------------------------------------------------------------------

def _rbf_fit(X, y):
    """A cubic radial basis function interpolant with a linear tail."""
    n, d = X.shape
    D = np.sqrt(np.sum((X[:, None] - X[None]) ** 2, -1))
    Phi = D ** 3
    P = np.column_stack([np.ones(n), X])
    M = np.block([[Phi, P], [P.T, np.zeros((d + 1, d + 1))]])
    rhs = np.concatenate([y, np.zeros(d + 1)])
    coef = np.linalg.lstsq(M, rhs, rcond=None)[0]
    lam, c = coef[:n], coef[n:]

    def s(Z):
        Dz = np.sqrt(np.sum((Z[:, None] - X[None]) ** 2, -1))
        return Dz ** 3 @ lam + np.column_stack([np.ones(Z.shape[0]), Z]) @ c
    return s


@bi('surrogateopt', nout=4)
def surrogateopt(nargout, *args):
    """[x, fval, exitflag, output] = surrogateopt(fun, lb, ub), surrogateopt(fun, lb, ub, intcon, options): a minimum of an expensive function within finite bounds, by a radial basis surrogate."""
    nargchk(args, 3, 5, 'surrogateopt')
    a = list(args) + [None] * (5 - len(args))
    lb, ub = np.asarray(darr(a[1]), float).reshape(-1), np.asarray(darr(a[2]), float).reshape(-1)
    n = lb.size
    intcon, options = OP._arg(a, 3), OP._arg(a, 4)
    if isinstance(intcon, (OP.OptimOptions, Struct)):
        intcon, options = None, intcon
    if not (np.all(np.isfinite(lb)) and np.all(np.isfinite(ub))):
        raise err('globaloptim:surrogateopt:bounds', 'surrogateopt takes finite bounds.', 'surrogateopt')
    opts = OP._Opts('surrogateopt', options, n, 'surrogateopt')
    prob = _Problem(a[0], n, 'surrogateopt', lb=out(lb), ub=out(ub), intcon=intcon, opts=opts)
    rs = _rs()
    maxfev = int(_opt(opts, 'MaxFunctionEvaluations', 200.0))
    m0 = int(_opt(opts, 'MinSurrogatePoints', max(20, 2 * n)))
    olim = float(_opt(opts, 'ObjectiveLimit', -math.inf))
    m0 = min(m0, maxfev)
    X = lb + rs.random_sample((m0, n)) * (ub - lb)
    ip = opts.o.get('InitialPoints')
    if ip is not None and numel(ip):
        I0 = np.asarray(darr(ip), float).reshape(-1, n)
        X = np.vstack([I0, X])[:max(m0, I0.shape[0])]
    X = prob.fix(X)
    y = prob.many(X)
    weights = [0.3, 0.5, 0.8, 0.95]
    k = 0
    exitflag, msg = 0, 'The maximum number of function evaluations was reached.'
    # the sampling radius about the best point: halved after three failures in a row, kept after a success, back to a
    # fifth of the box when it has shrunk to nothing
    sigma = 0.2 * (ub - lb)
    fails = 0
    while prob.count < maxfev:
        s = _rbf_fit(X, y)
        ib = int(np.argmin(y))
        # candidates about the best point (every fourth time, over the whole box), as Regis and Shoemaker's stochastic RBF method
        if k % 4 == 3:
            C = lb + rs.random_sample((1000, n)) * (ub - lb)
        else:
            C = X[ib] + rs.standard_normal((1000, n)) * sigma
        C = prob.fix(C)
        sv = s(C)
        dist = np.min(np.sqrt(np.sum((C[:, None] - X[None]) ** 2, -1)), axis=1)
        if np.max(dist) <= 1e-12:
            break
        w = weights[k % len(weights)]
        vs = (sv - sv.min()) / max(np.ptp(sv), 1e-300)
        vd = 1 - (dist - dist.min()) / max(np.ptp(dist), 1e-300)
        merit = w * vs + (1 - w) * vd
        merit[dist <= 1e-9 * np.max(ub - lb)] = np.inf
        j = int(np.argmin(merit))
        xn = C[j]
        X = np.vstack([X, xn])
        y = np.append(y, prob(xn))
        k += 1
        if y[-1] < y[ib] - 1e-3 * abs(y[ib]):
            fails = 0
        else:
            fails += 1
            if fails >= 3:
                sigma = sigma / 2
                fails = 0
                if np.all(sigma < 1e-5 * (ub - lb)):
                    sigma = 0.2 * (ub - lb)
        if y[-1] <= olim:
            exitflag, msg = 1, 'The objective reached ObjectiveLimit.'
            break
    ib = int(np.argmin(y))
    _say(opts.display(), f'surrogateopt stopped: {msg}')
    output = _output(elapsedtime=0.0, funccount=prob.count, message=msg, rngstate=Struct.scalar({}), ineq=EMPTY())
    res = (out(X[ib].reshape(1, -1)), float(y[ib]), float(exitflag), output)
    return res[:nargout] if nargout > 1 else res[0]


# ---- many objectives ------------------------------------------------------------------------------------------------------------------------

def _nondominated_sort(F):
    n = F.shape[0]
    dom = [[] for _ in range(n)]
    cnt = np.zeros(n, int)
    for i in range(n):
        le = np.all(F[i] <= F, axis=1) & np.any(F[i] < F, axis=1)
        ge = np.all(F <= F[i], axis=1) & np.any(F < F[i], axis=1)
        dom[i] = list(np.flatnonzero(le))
        cnt[i] = int(np.sum(ge))
    ranks = np.zeros(n, int)
    front = list(np.flatnonzero(cnt == 0))
    r = 0
    while front:
        nxt = []
        for i in front:
            ranks[i] = r
            for j in dom[i]:
                cnt[j] -= 1
                if cnt[j] == 0:
                    nxt.append(j)
        front = nxt
        r += 1
    return ranks


def _crowding(F):
    n, m = F.shape
    d = np.zeros(n)
    for k in range(m):
        o = np.argsort(F[:, k], kind='stable')
        d[o[0]] = d[o[-1]] = np.inf
        span = F[o[-1], k] - F[o[0], k]
        if span > 0 and n > 2:
            d[o[1:-1]] += (F[o[2:], k] - F[o[:-2], k]) / span
    return d


@bi('gamultiobj', nout=6)
def gamultiobj(nargout, *args):
    """[x, fval, exitflag, output, population, scores] = gamultiobj(fun, nvars, A, b, Aeq, beq, lb, ub, nonlcon, options): points on the Pareto front of several objectives (fun gives a row of them), by a genetic algorithm in the manner of NSGA-II."""
    nargchk(args, 2, 10, 'gamultiobj')
    a = list(args) + [None] * (10 - len(args))
    n = int(num(a[1]))
    options = OP._arg(a, 9)
    if isinstance(OP._arg(a, 8), (OP.OptimOptions, Struct)):
        options, a[8] = a[8], None
    opts = OP._Opts('gamultiobj', options, n, 'gamultiobj')
    f = OP._fh(a[0], 'gamultiobj')
    prob = _Problem(f, n, 'gamultiobj', OP._arg(a, 2), OP._arg(a, 3), OP._arg(a, 4), OP._arg(a, 5), OP._arg(a, 6), OP._arg(a, 7), OP._arg(a, 8), opts=opts)
    rs = _rs()
    P = int(_opt(opts, 'PopulationSize', 50 if n <= 5 else 200))
    G = int(_opt(opts, 'MaxGenerations', 200 * n))
    pf = float(_opt(opts, 'ParetoFraction', 0.35))
    count = [0]

    def objs(x):
        count[0] += 1
        return np.asarray(darr(f.scall(1, out(x.reshape(1, -1)))), float).reshape(-1)
    lo, hi = prob.span()
    X = prob.fix(lo + rs.random_sample((P, n)) * (hi - lo))
    F = np.array([objs(x) for x in X])
    viol = np.array([prob.violation(x) for x in X])

    def ranked(F, viol):
        r = _nondominated_sort(F).astype(float)
        return np.where(viol > 1e-12, r.max() + 1 + viol, r)
    gen = 0
    for gen in range(1, G + 1):
        r = ranked(F, viol)
        cd = _crowding(F)
        # binary tournaments by rank, then crowding
        i1, i2 = rs.randint(0, P, P), rs.randint(0, P, P)
        better = (r[i1] < r[i2]) | ((r[i1] == r[i2]) & (cd[i1] > cd[i2]))
        par = np.where(better, i1, i2)
        p1, p2 = X[par], X[np.roll(par, 1)]
        # intermediate crossover, Gaussian mutation shrinking over the run
        alpha = rs.random_sample((P, n))
        kids = p1 + alpha * (p2 - p1)
        mut = rs.random_sample(P) > float(_opt(opts, 'CrossoverFraction', 0.8))
        scale = (hi - lo) * 0.1 * (1 - gen / G) if np.all(np.isfinite(hi - lo)) else 0.1 * (1 - gen / G)
        kids[mut] = p1[mut] + rs.standard_normal((mut.sum(), n)) * scale
        kids = prob.fix(kids)
        Fk = np.array([objs(x) for x in kids])
        vk = np.array([prob.violation(x) for x in kids])
        XX, FF, VV = np.vstack([X, kids]), np.vstack([F, Fk]), np.concatenate([viol, vk])
        rr = ranked(FF, VV)
        cdd = _crowding(FF)
        # the Pareto front limited to ParetoFraction of the population, then the next fronts by crowding
        order = np.lexsort((-cdd, rr))
        first = order[rr[order] == 0]
        keep = list(first[:max(int(round(pf * P)), 1)]) if first.size > pf * P and first.size < P else []
        rest = [i for i in order if i not in set(keep)]
        sel = (keep + rest)[:P]
        X, F, viol = XX[sel], FF[sel], VV[sel]
    r = ranked(F, viol)
    front = np.flatnonzero(r == 0)
    msg = 'The maximum number of generations was reached.'
    _say(opts.display(), f'Optimization terminated: {msg}')
    output = _output(problemtype='boundconstraints', generations=gen, funccount=count[0], message=msg, averagedistance=0.0, spread=0.0, maxconstraint=float(viol[front].max(initial=0)))
    res = (out(X[front]), out(F[front]), 0.0, output, out(X), out(F))
    return res[:nargout] if nargout > 1 else res[0]


# ---- many starts of a local solver -------------------------------------------------------------------------------------------------------------

@bi('createOptimProblem')
def createOptimProblem(nargout, *args):
    """problem = createOptimProblem(solverName, 'objective', fun, 'x0', x0, 'lb', lb, 'ub', ub, 'Aineq', A, 'bineq', b, 'Aeq', Aeq, 'beq', beq, 'nonlcon', nonlcon, 'options', options): a problem for MultiStart and GlobalSearch (and for the solver itself)."""
    nargchk(args, 1, 30, 'createOptimProblem')
    solver = py_str(args[0])
    if solver not in ('fmincon', 'fminunc', 'lsqnonlin', 'lsqcurvefit', 'fminsearch'):
        raise err('globaloptim:createOptimProblem:solver', "The solver is 'fmincon', 'fminunc', 'lsqnonlin', 'lsqcurvefit' or 'fminsearch'.", 'createOptimProblem')
    names = ('objective', 'x0', 'Aineq', 'bineq', 'Aeq', 'beq', 'lb', 'ub', 'nonlcon', 'options', 'xdata', 'ydata')
    d = {k: EMPTY() for k in names}
    for i in range(1, len(args) - 1, 2):
        k = py_str(args[i])
        kk = next((n for n in names if n.lower() == k.lower()), None)
        if kk is None:
            raise err('globaloptim:createOptimProblem:field', f"'{k}' is not a field of an optimization problem.", 'createOptimProblem')
        d[kk] = args[i + 1]
    d['solver'] = Char.of(solver)
    if not numel(d['options']) and not isinstance(d['options'], OP.OptimOptions) and solver != 'fminsearch':
        d['options'] = OP.optimoptions(1, Char.of(solver))
    return Struct.scalar(d)


class _Starter(Obj):
    is_handle = False

    def __init__(self, kind, opts):
        self.kind = kind
        self.opts = opts

    @property
    def cls(self):
        return self.kind

    def value_copy(self):
        return _Starter(self.kind, dict(self.opts))

    def getprop(self, name):
        for k, v in self.opts.items():
            if k.lower() == name.lower():
                return v
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.kind}'.")

    def setprop(self, name, value):
        for k in self.opts:
            if k.lower() == name.lower():
                self.opts[k] = value
                return
        raise MError('MATLAB:noPublicFieldForClass', f"Unrecognized property '{name}' for class '{self.kind}'.")

    def propnames(self):
        return list(self.opts)

    def display_lines(self):
        from ..display import summary
        w = max(len(k) for k in self.opts)
        return [f'  {self.kind} with properties:', ''] + [f'    {k.rjust(w)}: {summary(v)}' for k, v in self.opts.items()]


def _starter(kind, defaults):
    def f(nargout, *args):
        o = dict(defaults)
        a = list(args)
        if a and isinstance(a[0], _Starter):
            src = a.pop(0)
            for k in o:
                if k in src.opts:
                    o[k] = src.opts[k]
        for i in range(0, len(a) - 1, 2):
            k = py_str(a[i])
            kk = next((x for x in o if x.lower() == k.lower()), None)
            if kk is None:
                raise err(f'globaloptim:{kind}:option', f"'{k}' is not an option of {kind}.", kind)
            o[kk] = a[i + 1]
        return _Starter(kind, o)
    return f


_ms_defaults = {'Display': Char.of('final'), 'FunctionTolerance': 1e-6, 'XTolerance': 1e-6, 'MaxTime': math.inf, 'StartPointsToRun': Char.of('all'),
                'UseParallel': False}
_gs_defaults = {'Display': Char.of('final'), 'FunctionTolerance': 1e-6, 'XTolerance': 1e-6, 'MaxTime': math.inf, 'NumTrialPoints': 1000.0,
                'NumStageOnePoints': 200.0, 'BasinRadiusFactor': 0.2, 'DistanceThresholdFactor': 0.75, 'MaxWaitCycle': 20.0, 'PenaltyThresholdFactor': 0.2,
                'StartPointsToRun': Char.of('all')}
_f = _starter('MultiStart', _ms_defaults)
_f.__doc__ = "ms = MultiStart, MultiStart('Name', value, ...): a solver that runs a local solver from many start points (run(ms, problem, k))."
bi('MultiStart')(_f)
_f = _starter('GlobalSearch', _gs_defaults)
_f.__doc__ = "gs = GlobalSearch, GlobalSearch('Name', value, ...): a solver that runs a local solver from the best of many trial points (run(gs, problem))."
bi('GlobalSearch')(_f)


class _Solution(Obj):
    cls = 'GlobalOptimSolution'

    def __init__(self, x, f, flag, output, x0s):
        self.p = {'X': x, 'Fval': f, 'Exitflag': flag, 'Output': output, 'X0': x0s}

    def getprop(self, name):
        for k, v in self.p.items():
            if k.lower() == name.lower():
                return v
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'GlobalOptimSolution'.")

    def propnames(self):
        return list(self.p)


def _call(name, nargout, *args):
    info = REG[name]
    r = info.fn(R.BASE, nargout, *args) if info.ws else info.fn(nargout, *args)
    return R.run_sync(r) if info.aw else r


def _local(problem, x0):
    solver = py_str(problem.get1('solver'))
    g = problem.get1
    x0v = out(np.asarray(x0, float).reshape(np.asarray(darr(g('x0'))).shape))
    if solver == 'fmincon':
        r = _call('fmincon', 4, g('objective'), x0v, g('Aineq'), g('bineq'), g('Aeq'), g('beq'), g('lb'), g('ub'), g('nonlcon'), g('options'))
    elif solver == 'fminunc':
        r = _call('fminunc', 4, g('objective'), x0v, g('options'))
    elif solver == 'fminsearch':
        r = _call('fminsearch', 4, g('objective'), x0v, g('options') if numel(g('options')) or isinstance(g('options'), Struct) else Struct.scalar({'Display': Char.of('off')}))
    elif solver == 'lsqnonlin':
        r = _call('lsqnonlin', 4, g('objective'), x0v, g('lb'), g('ub'), g('options'))
    else:
        r = _call('lsqcurvefit', 4, g('objective'), x0v, g('xdata'), g('ydata'), g('lb'), g('ub'), g('options'))
    return r


def _quiet(problem):
    o = problem.get1('options')
    solver = py_str(problem.get1('solver'))
    if isinstance(o, OP.OptimOptions):
        q = o.value_copy()
        q.vals['Display'] = Char.of('off')
        return q
    if solver == 'fminsearch':
        return Struct.scalar({'Display': Char.of('off')})
    return OP.optimoptions(1, Char.of(solver), Char.of('Display'), Char.of('off'))


def _start_points(problem, k, rs, artificial=1000.0):
    x0 = np.asarray(darr(problem.get1('x0')), float).reshape(-1)
    n = x0.size
    lb = np.asarray(darr(problem.get1('lb')), float).reshape(-1) if numel(problem.get1('lb')) else np.full(n, -np.inf)
    ub = np.asarray(darr(problem.get1('ub')), float).reshape(-1) if numel(problem.get1('ub')) else np.full(n, np.inf)
    lo = np.where(np.isfinite(lb), lb, np.where(np.isfinite(ub), ub - 2 * artificial, -artificial))
    hi = np.where(np.isfinite(ub), ub, lo + 2 * artificial)
    pts = [x0] + [lo + rs.random_sample(n) * (hi - lo) for _ in range(max(k - 1, 0))]
    return pts, lo, hi


def _run_starts(nargout, ms, problem, *rest):
    if not isinstance(problem, Struct) or 'solver' not in problem.keys:
        raise err('globaloptim:run:problem', 'run takes a problem from createOptimProblem.', 'run')
    rs = _rs()
    q = Struct(problem.shape, {k: v.copy() for k, v in problem.f.items()})
    q.f['options'][0, 0] = _quiet(problem)
    if ms.kind == 'MultiStart':
        k = int(num(rest[0])) if rest and not isinstance(rest[0], Obj) else 1
        if rest and isinstance(rest[0], _Starter) is False and isinstance(rest[0], np.ndarray) and rest[0].ndim == 2 and rest[0].shape[0] > 1:
            pts = [row for row in np.asarray(darr(rest[0]), float)]
        else:
            pts, _, _ = _start_points(problem, k, rs)
    else:
        # GlobalSearch: trial points scored by the objective (and any constraint violation), local runs from x0 and then from the
        # best of them that do not fall inside the basin of a solution already found
        nt = int(num(ms.opts['NumTrialPoints']))
        trial, lo, hi = _start_points(problem, nt, rs)
        f = q.get1('objective')

        def score(x):
            v = np.asarray(darr(f.scall(1, out(np.asarray(x).reshape(np.asarray(darr(q.get1('x0'))).shape)))), float).reshape(-1)
            return float(np.sum(v ** 2)) if py_str(q.get1('solver')).startswith('lsq') else float(v[0])
        scores = np.array([score(x) for x in trial[1:]])
        order = np.argsort(scores, kind='stable')
        pts = [trial[0]] + [trial[1:][i] for i in order[:int(num(ms.opts['NumStageOnePoints']))]]
    sols = []
    basins = []          # (solution, radius): a trial point inside one leads there again (GlobalSearch)
    factor = float(num(ms.opts.get('BasinRadiusFactor', 0.2))) if ms.kind == 'GlobalSearch' else 0.0
    for x0 in pts:
        if ms.kind == 'GlobalSearch' and any(np.linalg.norm(x0 - b_) < r_ for b_, r_ in basins):
            continue
        try:
            r = _local(q, x0)
        except MError:
            continue
        fv = float(np.sum(np.asarray(darr(r[1]), float) ** 2)) if py_str(q.get1('solver')).startswith('lsq') else float(num(r[1]))
        sols.append((r[0], fv, float(num(r[2])), r[3], x0))
        xs = np.asarray(darr(r[0]), float).reshape(-1)
        basins.append((xs, factor * max(np.linalg.norm(x0 - xs), 1e-6)))
        if ms.kind == 'GlobalSearch' and len(sols) >= 50:
            break
    good = [s for s in sols if s[2] > 0] or sols
    if not good:
        raise err('globaloptim:run:noSolution', 'No local run finished.', 'run')
    # distinct solutions, best first
    ftol = float(num(ms.opts['FunctionTolerance']))
    xtol = float(num(ms.opts['XTolerance']))
    distinct = []
    for s in sorted(good, key=lambda s: s[1]):
        xs = np.asarray(darr(s[0]), float).reshape(-1)
        for d in distinct:
            xd = np.asarray(darr(d[0]), float).reshape(-1)
            if abs(d[1] - s[1]) <= ftol * max(1, abs(s[1])) and np.linalg.norm(xs - xd) <= xtol * max(1, np.linalg.norm(xd)):
                d[4].append(s[4])
                break
        else:
            distinct.append([s[0], s[1], s[2], s[3], [s[4]]])
    best = distinct[0]
    nconv = sum(1 for s in sols if s[2] > 0)
    flag = 1.0 if nconv == len(sols) else (2.0 if nconv else -2.0)
    msg = f'{ms.kind} {"completed" if flag > 0 else "found no"} local solver runs that converged: {nconv} of {len(sols)}.'
    disp = py_str(ms.opts['Display']).lower()
    if disp != 'off':
        R.write(f'\n{msg}\n\n')
    output = _output(funcCount=0.0, localSolverTotal=float(len(sols)), localSolverSuccess=float(nconv), localSolverIncomplete=float(len(sols) - nconv),
                     localSolverNoSolution=0.0, message=msg)
    solutions = Cell.of_list([_Solution(d[0], d[1], d[2], d[3], Cell.of_list([out(np.asarray(x).reshape(1, -1)) for x in d[4]], (1, len(d[4])))) for d in distinct], (1, len(distinct)))
    res = (best[0], best[1], flag, output, solutions)
    return res[:nargout] if nargout > 1 else res[0]


def _wrap_run():
    info = REG['run']
    orig = info.fn

    async def f(W, nargout, *args):
        if args and isinstance(args[0], _Starter):
            return _run_starts(nargout, *args)
        return await orig(W, nargout, *args)
    info.fn = f
    info.nout = max(info.nout, 5)


_wrap_run()
