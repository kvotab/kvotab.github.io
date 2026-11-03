"""The optimization functions, run natively (CPython with numpy and scipy):
answers against closed forms (projections, KKT conditions worked by hand)
and SciPy, the Lagrange multipliers, exit flags and output structures,
optimoptions' objects, the Display levels, output functions that stop a
solver, plot functions and problem structures.

    python3 test_optim.py          (from any folder; needs numpy and scipy)
"""
import asyncio
import itertools
import os
import sys

import numpy as np
from scipy import optimize as O

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char, Cell, Struct  # noqa: E402
from plab.graphics_base import STORE  # noqa: E402

R.setup()


def mat(v):
    if isinstance(v, (Char, Cell, Struct)):
        return v
    a = np.asarray(v, float)
    if a.ndim == 0:
        return float(a)
    return a.reshape(-1, 1) if a.ndim == 1 else a


def run(code, **values):
    """Run code in a fresh base workspace holding values: (workspace, output)."""
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    for k, v in values.items():
        R.BASE[k] = mat(v)
    asyncio.run(R.execute(code))
    return R.BASE, R.take_output()


def arr(v):
    if isinstance(v, (bool, float, int)):
        return np.array([float(v)])
    if isinstance(v, (list, tuple)):
        return np.concatenate([arr(x) for x in v]) if v else np.zeros(0)
    return np.asarray(v, float).reshape(-1)


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def near(label, got, want, tol=1e-6):
    g, w = arr(got), arr(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol)
    return C(label, ok, f'got {g.tolist()}, want {w.tolist()}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def text(v):
    return v.str() if isinstance(v, Char) else str(v)


def field(s, k):
    return s.get1(k)


# ---- fminunc --------------------------------------------------------------------------------------------------
ROSEN = "f = @(x) 100*(x(2)-x(1)^2)^2 + (1-x(1))^2;"
W, outp = run(ROSEN + "[x, fval, flag, output, grad, hessian] = fminunc(f, [-1.2 1]);")
near('fminunc: the Rosenbrock minimum', W['x'], [1, 1], 1e-5)
same('fminunc: exit flag 1, and the shape of x0', (W['flag'], W['x'].shape), (1.0, (1, 2)))
near('fminunc: the Hessian at the minimum, by differences of the gradient', W['hessian'], [[802, -400], [-400, 200]], 1e-3)
same('fminunc: output fields', sorted(W['output'].f), sorted(['iterations', 'funcCount', 'algorithm', 'firstorderopt', 'stepsize', 'message']))
C('fminunc: the default Display tells the outcome', 'Local minimum found' in outp, outp)
W, outp = run("f = @(x) deal(sum((x - [1; 2; 3]).^2), 2*(x - [1; 2; 3])); o = optimoptions('fminunc', 'SpecifyObjectiveGradient', true, 'Display', 'off');"
              "[x, fval, flag, output] = fminunc(f, [0; 0; 0], o);")
near('fminunc with the gradient given', W['x'], [1, 2, 3], 1e-8)
same("Display 'off' says nothing", outp, '')
W, outp = run(ROSEN + "o = optimoptions('fminunc', 'Algorithm', 'trust-region', 'SpecifyObjectiveGradient', true, 'Display', 'off');"
              "g = @(x) deal(f(x), [-400*x(1)*(x(2)-x(1)^2) - 2*(1-x(1)); 200*(x(2)-x(1)^2)]); x = fminunc(g, [-1.2; 1], o);")
near("fminunc 'trust-region'", W['x'], [1, 1], 1e-5)
W, outp = run(ROSEN + "o = optimoptions('fminunc', 'Display', 'iter', 'MaxIterations', 4); [x, fval, flag, output] = fminunc(f, [-1.2 1], o);")
same('MaxIterations stops it: flag 0 after that many iterations', (W['flag'], field(W['output'], 'iterations')), (0.0, 4.0))
rows = [ln for ln in outp.splitlines() if ln.strip()[:1].isdigit()]
C("Display 'iter': a header and a row for the start and each iteration", ' Iter  F-count' in outp and len(rows) == 5, outp)
# an output function in a file of its own
TMP = os.path.join(os.path.dirname(os.path.abspath(__file__)), '_optim_tmp')
os.makedirs(TMP, exist_ok=True)
with open(os.path.join(TMP, 'halt.m'), 'w') as fh:
    fh.write("function stop = halt(x, v, state)\nglobal seen\nseen{end+1} = state;\nstop = v.iteration >= 3;\nend\n")
try:
    W, outp = run(f"addpath('{TMP}'); global seen; seen = {{}};" + ROSEN + "o = optimoptions('fminunc', 'OutputFcn', @halt, 'Display', 'off');"
                  "[x, fval, flag, output] = fminunc(f, [-1.2 1], o); n = numel(seen); first = seen{1}; last = seen{end};")
    same('an output function that says stop: exit flag -1 after its iteration', (W['flag'], field(W['output'], 'iterations')), (-1.0, 3.0))
    same("its states: 'init' first, 'done' last", (text(W['first']), text(W['last'])), ('init', 'done'))
finally:
    run(f"rmpath('{TMP}');")
    os.remove(os.path.join(TMP, 'halt.m'))
    os.rmdir(TMP)

# ---- fmincon: answers and multipliers worked by hand --------------------------------------------------------------
for alg in ('interior-point', 'sqp'):
    o = f"o = optimoptions('fmincon', 'Algorithm', '{alg}', 'Display', 'off');"
    W, _ = run(o + "[x, fval, flag, output, lambda] = fmincon(@(x) sum(x.^2), [3; -1], [], [], [1 1], 1, [], [], [], o);")
    near(f'fmincon {alg}: x1 + x2 = 1 nearest the origin', W['x'], [0.5, 0.5], 1e-6)
    near(f'fmincon {alg}: its equality multiplier', field(W['lambda'], 'eqlin'), [-1], 1e-5)
    W, _ = run(o + "[x, fval, flag, output, lambda] = fmincon(@(x) (x(1)-2)^2 + (x(2)-1)^2, [0 0], [1 1], 1, [], [], [], [], [], o);")
    near(f'fmincon {alg}: (2, 1) projected on x1 + x2 <= 1', W['x'], [1, 0], 1e-6)
    near(f'fmincon {alg}: the inequality multiplier', field(W['lambda'], 'ineqlin'), [2], 1e-5)
    same(f'fmincon {alg}: exit flag 1', W['flag'], 1.0)
    W, _ = run(o + "[x, fval, flag, output, lambda] = fmincon(@(x) (x-3)^2, 0, [], [], [], [], -5, 1, [], o);")
    near(f'fmincon {alg}: an upper bound', (W['x'], field(W['lambda'], 'upper'), field(W['lambda'], 'lower')), [1, 4, 0], 1e-5)
    W, _ = run(o + "nl = @(x) deal(x(1)^2 + x(2)^2 - 2, []); [x, fval, flag, output, lambda] = fmincon(@(x) x(1) + x(2), [0.5 0.5], [], [], [], [], [], [], nl, o);")
    near(f'fmincon {alg}: a nonlinear inequality, and its multiplier', (W['x'], field(W['lambda'], 'ineqnonlin')), [-1, -1, 0.5], 1e-5)
W, _ = run("o = optimoptions('fmincon', 'Display', 'off', 'SpecifyConstraintGradient', true, 'SpecifyObjectiveGradient', true);"
           "nl = @(x) deal([], x(1)*x(2) - 1, [], [x(2); x(1)]); f = @(x) deal(x(1)^2 + 4*x(2)^2, [2*x(1); 8*x(2)]);"
           "[x, fval, flag] = fmincon(f, [2; 2], [], [], [], [], [0; 0], [], nl, o);")
near('fmincon: a nonlinear equality with the gradients given', W['x'], [np.sqrt(2), 1 / np.sqrt(2)], 1e-6)
W, outp = run("[x, fval, flag, output] = fmincon(@(x) x^2, 0, 1, 1, [], [], 2, []);")
same('fmincon: x <= 1 and x >= 2 cannot both hold: exit flag -2', W['flag'], -2.0)
C('and says so', 'No feasible point' in outp, outp)
W, _ = run("p.objective = @(x) (x(1)-1)^2 + (x(2)-2)^2; p.x0 = [0 0]; p.Aineq = [1 1]; p.bineq = 2; p.solver = 'fmincon';"
           "p.options = optimoptions('fmincon', 'Display', 'off'); x = fmincon(p);")
near('fmincon(problem)', W['x'], [0.5, 1.5], 1e-6)
W, _ = run("o = optimset('Display', 'off', 'TolX', 1e-12, 'Algorithm', 'sqp'); x = fmincon(@(x) (x-2)^2, 0, [], [], [], [], [], 1, [], o);")
near('fmincon with optimset options', W['x'], [1], 1e-8)

# ---- fsolve ------------------------------------------------------------------------------------------------------
W, _ = run("F = @(x) [2*x(1) - x(2) - exp(-x(1)); -x(1) + 2*x(2) - exp(-x(2))]; [x, fval, flag, output, J] = fsolve(F, [-5; -5], optimoptions('fsolve', 'Display', 'off'));")
r = O.root(lambda x: [2 * x[0] - x[1] - np.exp(-x[0]), -x[0] + 2 * x[1] - np.exp(-x[1])], [-5, -5]).x
near('fsolve: a system of two equations', W['x'], r, 1e-8)
near('fsolve: its Jacobian at the root', W['J'], [[2 + np.exp(-r[0]), -1], [-1, 2 + np.exp(-r[1])]], 1e-5)
same('fsolve: flag 1', W['flag'], 1.0)
for alg in ('trust-region', 'levenberg-marquardt'):
    W, _ = run(f"F = @(x) [x(1)^2 + x(2)^2 - 4; x(1) - x(2)]; x = fsolve(F, [1; 0.5], optimoptions('fsolve', 'Algorithm', '{alg}', 'Display', 'off'));")
    near(f"fsolve '{alg}'", W['x'], [np.sqrt(2), np.sqrt(2)], 1e-7)
W, outp = run("[x, fval, flag] = fsolve(@(x) x^2 + 1, 3);")
same('fsolve: x^2 + 1 = 0 has no real root: flag -2', W['flag'], -2.0)

# ---- least squares ------------------------------------------------------------------------------------------------
xd = np.linspace(0, 4, 9)
W, _ = run("fun = @(p, x) p(1)*exp(p(2)*x); [p, resnorm, residual, flag] = lsqcurvefit(fun, [1 0], xd, yd, [], [], optimoptions('lsqcurvefit', 'Display', 'off'));",
           xd=xd.reshape(1, -1), yd=(2 * np.exp(-0.5 * xd)).reshape(1, -1))
near('lsqcurvefit: exact data give the parameters back', W['p'], [2, -0.5], 1e-6)
same('lsqcurvefit: the residual has the shape of ydata', W['residual'].shape, (1, 9))
rng = np.random.default_rng(7)
yn = 3 * np.exp(-0.7 * xd) + 0.05 * rng.standard_normal(xd.size)
ref, _ = O.curve_fit(lambda x, a, b: a * np.exp(b * x), xd, yn, p0=[1, 0])
W, _ = run("fun = @(p, x) p(1)*exp(p(2)*x); p = lsqcurvefit(fun, [1 0], xd, yd, [], [], optimoptions('lsqcurvefit', 'Display', 'off'));",
           xd=xd.reshape(1, -1), yd=yn.reshape(1, -1))
near('lsqcurvefit: noisy data as SciPy curve_fit fits them', W['p'], ref, 1e-5)
W, _ = run("r = @(x) [x(1) - 3; 10*(x(2) - x(1)^2)]; [x, resnorm, res, flag, output, lambda] = lsqnonlin(r, [0 0], [-1 -1], [2 2], optimoptions('lsqnonlin', 'Display', 'off'));")
# x2 held at its bound 2, x1 then minimizes (x1 - 3)^2 + 100*(2 - x1^2)^2
x1 = O.brentq(lambda s: 2 * (s - 3) - 400 * s * (2 - s * s), 1.3, 1.6)
near('lsqnonlin with bounds: x2 held at 2, x1 where the rest is least', W['x'], [x1, 2], 1e-6)
C("and the multiplier of x2's upper bound is positive", arr(field(W['lambda'], 'upper'))[1] > 0, str(field(W['lambda'], 'upper')))
W, _ = run("r = @(x) x - [1 2]; x = lsqnonlin(r, [0 0], [], [], [1 1], 2, [], [], [], optimoptions('lsqnonlin', 'Display', 'off'));")
near('lsqnonlin with a linear inequality', W['x'], [0.5, 1.5], 1e-6)
Cm = rng.standard_normal((8, 3))
dm = rng.standard_normal(8)
W, _ = run("[x, resnorm, residual, flag, output, lambda] = lsqnonneg(Cm, dm);", Cm=Cm, dm=dm)
xr, rn = O.nnls(Cm, dm)
near('lsqnonneg as SciPy nnls', (W['x'], W['resnorm']), list(xr) + [rn ** 2], 1e-10)
lam = arr(W['lambda'])
C('lsqnonneg: lambda zero where x is positive, not above zero where x is 0', np.all(lam[xr > 0] == 0) and np.all(lam[xr == 0] <= 1e-12), str(lam))
W, _ = run("x = lsqlin(Cm, dm, [], [], [], [], -0.2*ones(3,1), 0.2*ones(3,1), [], optimoptions('lsqlin', 'Display', 'off'));", Cm=Cm, dm=dm)
near('lsqlin with bounds as SciPy lsq_linear', W['x'], O.lsq_linear(Cm, dm, bounds=(-0.2, 0.2), method='bvls').x, 1e-8)
W, _ = run("p = [3; -1; 2]; [x, resnorm, residual, flag, output, lambda] = lsqlin(eye(3), p, [1 1 1], 1, [], [], [], [], [], optimoptions('lsqlin', 'Display', 'off'));")
near('lsqlin: p projected on sum(x) <= 1', W['x'], np.array([3, -1, 2]) - 1.0, 1e-8)
near('and the multiplier', field(W['lambda'], 'ineqlin'), [1], 1e-8)

# ---- quadratic, linear and integer programs ------------------------------------------------------------------------------
W, _ = run("H = [1 -1; -1 2]; f = [-2; -6]; A = [1 1; -1 2; 2 1]; b = [2; 2; 3];"
           "[x, fval, flag, output, lambda] = quadprog(H, f, A, b, [], [], [0; 0], [], [], optimoptions('quadprog', 'Display', 'off'));")
near('quadprog: the textbook problem', (W['x'], W['fval']), [2 / 3, 4 / 3, -74 / 9], 1e-9)
near('quadprog: its multipliers exactly', field(W['lambda'], 'ineqlin'), [28 / 9, 4 / 9, 0], 1e-9)
W, _ = run("[x, fval, flag, output, lambda] = quadprog(2*eye(2), [0; 0], [], [], [1 2], 5);")
near('quadprog with an equality: the nearest point of x1 + 2 x2 = 5', (W['x'], field(W['lambda'], 'eqlin')), [1, 2, -2], 1e-12)
W, outp = run("[x, fval, flag] = quadprog([1 0; 0 -1], [0; 0], [], [], [], [], [-1; -1], [1; 1]);")
same('quadprog: a non-convex H with the default algorithm: flag -6', W['flag'], -6.0)

rng = np.random.default_rng(3)
f = rng.standard_normal(4)
A = rng.uniform(0, 1, (5, 4))
b = rng.uniform(1, 2, 5)
W, _ = run("[x, fval, flag, output, lambda] = linprog(f, A, b, [1 1 1 1], 1, zeros(4,1), []);", f=f, A=A, b=b)
ref = O.linprog(f, A_ub=A, b_ub=b, A_eq=np.ones((1, 4)), b_eq=[1], bounds=(0, None), method='highs')
near('linprog as HiGHS solves it', (W['x'], W['fval']), list(ref.x) + [ref.fun], 1e-9)
lam = W['lambda']
kkt = f + A.T @ arr(field(lam, 'ineqlin')) + np.ones(4) * arr(field(lam, 'eqlin'))[0] - arr(field(lam, 'lower')) + arr(field(lam, 'upper'))
near("linprog's multipliers satisfy the KKT conditions", kkt, np.zeros(4), 1e-9)
C('and the inequalities\' are nonnegative', np.all(arr(field(lam, 'ineqlin')) >= -1e-12), str(field(lam, 'ineqlin')))
W, _ = run("[x, fval, flag] = linprog([1; 1], [1 1], -1, [], [], [0; 0], []);")
same('linprog: infeasible: flag -2', W['flag'], -2.0)
W, _ = run("[x, fval, flag] = linprog([-1; 0], [], [], [], [], [0; 0], []);")
same('linprog: unbounded: flag -3', W['flag'], -3.0)
W, _ = run("f = [8 1]; intcon = 2; A = [-1 -2; -4 -1; 2 1]; b = [14; -33; 20]; [x, fval, flag, output] = intlinprog(f, intcon, A, b);")
near('intlinprog: the textbook problem', (W['x'], W['fval']), [6.5, 7, 59], 1e-9)
values = rng.integers(5, 30, 8).astype(float)
weights = rng.integers(3, 15, 8).astype(float)
best = max((sum(values[i] for i in s), s) for k in range(9) for s in itertools.combinations(range(8), k) if sum(weights[i] for i in s) <= 30)
W, _ = run("x = intlinprog(-v, 1:8, w, 30, [], [], zeros(8,1), ones(8,1)); total = v*x;", v=values.reshape(1, -1), w=weights.reshape(1, -1))
near('intlinprog: a knapsack, against every subset', W['total'], best[0], 1e-9)

# ---- several objectives -------------------------------------------------------------------------------------------------
W, _ = run("fun = @(x) [2*x(1)^2+x(2)^2-48*x(1)-40*x(2)+304; -x(1)^2-3*x(2)^2; x(1)+3*x(2)-18; -x(1)-x(2); x(1)+x(2)-8];"
           "[x, fval, maxfval, flag] = fminimax(fun, [0.1; 0.1], [], [], [], [], [], [], [], optimoptions('fminimax', 'Display', 'off'));")
near('fminimax: the textbook problem', (W['x'], W['maxfval']), [4, 4, 0], 1e-6)
W, _ = run("fun = @(x) [x - 1, -x - 1]; [x, fval, maxfval] = fminimax(fun, 3, [], [], [], [], [], [], [], optimoptions('fminimax', 'Display', 'off'));")
near('fminimax: max(x - 1, -x - 1) is least at 0', (W['x'], W['maxfval']), [0, -1], 1e-7)
W, _ = run("fun = @(x) [2+(x(1)-3)^2; 5+x(2)^2/4]; [x, fval, af, flag] = fgoalattain(fun, [1 1], [3 6], [1 1], [], [], [], [], [], [], [], optimoptions('fgoalattain', 'Display', 'off'));")
near('fgoalattain: both goals beaten by 1', (W['x'], W['af']), [3, 0, -1], 1e-6)
W, _ = run("fun = @(x) [x(1); x(2)]; [x, fval, af] = fgoalattain(fun, [5 5], [0 0], [1 2], [-1 -1], -3, [], [], [], [], [], optimoptions('fgoalattain', 'Display', 'off'));")
near('fgoalattain: the weights share the shortfall (x1 + x2 >= 3)', (W['x'], W['af']), [1, 2, 1], 1e-6)

# ---- options --------------------------------------------------------------------------------------------------------------
W, outp = run("o = optimoptions('fmincon', 'Display', 'iter', 'MaxIterations', 50)")
C('optimoptions shows the options set apart from the defaults', 'Set:' in outp and 'Default:' in outp and "Display: 'iter'" in outp, outp)
W, _ = run("o = optimoptions('fmincon'); o2 = o; o2.Display = 'off'; a = o.Display; b = o2.Display; c = class(o);")
same('options are values: a copy changed leaves the original', (text(W['a']), text(W['b']), text(W['c'])), ('final', 'off', 'optim.options.Fmincon'))
W, _ = run("o = optimoptions('fminunc', optimoptions('fmincon', 'MaxIterations', 7, 'Algorithm', 'sqp')); m = o.MaxIterations; a = o.Algorithm;")
same("options of another solver carried over where they apply", (W['m'], text(W['a'])), (7.0, 'quasi-newton'))
W, _ = run("o = optimoptions('fmincon', 'TolFun', 1e-9, 'MaxIter', 9); a = o.OptimalityTolerance; b = o.MaxIterations;")
same("optimset's names set the newer ones", (W['a'], W['b']), (1e-9, 9.0))
W, _ = run("o = resetoptions(optimoptions('fmincon', 'MaxIterations', 9), 'MaxIterations'); m = o.MaxIterations;")
same('resetoptions', W['m'], 1000.0)
for code, msg in (("optimoptions('fmincon', 'Bogus', 1)", "'Bogus' is not an option for fmincon"),
                  ("optimoptions('fmincon', 'Algorithm', 'nope')", 'Algorithm for fmincon must be one of'),
                  ("optimoptions('nosuchsolver')", 'is not a solver')):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    C(f'refused: {code}', msg in text(W['e']), text(W['e']))
W, _ = run("o = optimoptions('fminsearch', 'TolX', 1e-10, 'TolFun', 1e-10); x = fminsearch(@(x) (x - 2)^2, 0, o);")
near('fminsearch reads optimoptions too', W['x'], [2], 1e-6)

# ---- plot functions -------------------------------------------------------------------------------------------------------
W, _ = run("close all force;" + ROSEN + "o = optimoptions('fminunc', 'PlotFcn', {@optimplotfval, @optimplotx}, 'Display', 'off', 'MaxIterations', 6);"
           "[x, fval, flag, output] = fminunc(f, [-1.2 1], o); fig = gcf; nm = get(fig, 'Name'); n = numel(findobj(fig, 'Type', 'axes'));"
           "h = findobj(fig, 'Tag', 'optimplotfval'); np = numel(get(h, 'XData')); t = get(get(get(h, 'Parent'), 'Title'), 'String'); close all force;")
same('PlotFcn: a window with an axes for each plot function', (text(W['nm']), W['n']), ('Optimization Plot Functions', 2.0))
same("optimplotfval: a point for the start and each iteration", W['np'], 7.0)
C('and the current value in its title', text(W['t']).startswith('Current Function Value'), text(W['t']))

sys.exit(C.done())
