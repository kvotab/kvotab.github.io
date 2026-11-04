"""Global optimization, run natively (CPython with numpy and scipy): ga,
particleswarm, simulannealbnd, patternsearch (bounds, linear and
nonlinear constraints), surrogateopt and gamultiobj on problems whose
answers are known; MultiStart and GlobalSearch finding a global minimum
among local ones; their options through optimoptions; reproducibility
under rng.

    python3 test_globalopt.py          (from any folder)
"""
import asyncio
import math
import os
import sys
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
warnings.filterwarnings('ignore')


def run(code):
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(code))
    return dict(R.BASE), R.take_output()


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


def a(x):
    if isinstance(x, tuple):
        return np.concatenate([np.asarray(v, dtype=float).reshape(-1) for v in x])
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if w.size < 30 else w.shape}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


RASTR = "rastr = @(x) 10*numel(x) + sum(x.^2 - 10*cos(2*pi*x));"
W, out = run(RASTR + " o = optimoptions('ga', 'Display', 'off', 'PopulationSize', 100, 'MaxGenerations', 300); rng(1); [x, f, flag, op] = ga(rastr, 2, [], [], [], [], [-5 -5], [5 5], [], o); "
             "rng(1); x2 = ga(rastr, 2, [], [], [], [], [-5 -5], [5 5], [], o); same = isequal(x, x2); g = op.generations;")
near('ga: the global minimum of Rastrigin\'s function (0 at the origin), from rng(1)', (W['x'], W['f']), ([[0, 0]], 0), 0.05)
C('ga: the same seed gives the same answer; its output struct', bool(W['same']) and W['g'] >= 1, (W['same'], W['g']))
W, _ = run("o = optimoptions('ga', 'Display', 'off'); rng(2); [x, f] = ga(@(x) (x(1) - 3)^2 + (x(2) + 1)^2, 2, [1 1], 1, [], [], [-5 -5], [5 5], [], o); "
           "rng(3); [xi, fi] = ga(@(x) (x(1) - 2.6)^2 + (x(2) - 1.4)^2, 2, [], [], [], [], [0 0], [5 5], [], [1 2], o);")
C('ga with a linear constraint: near (2.5, -1.5), x1 + x2 <= 1 met', np.allclose(a(W['x']), [[2.5, -1.5]], atol=0.1) and a(W['x']).sum() <= 1 + 1e-3, W['x'])
near('ga with integer variables: the nearest integer point (3, 1)', W['xi'], [[3, 1]], 1e-12)
W, _ = run(RASTR + " rng(4); [x, f, flag, op] = particleswarm(rastr, 2, -5*ones(1, 2), 5*ones(1, 2), optimoptions('particleswarm', 'Display', 'off')); "
           "rng(11); [xs, fs] = particleswarm(@(x) sum((x - (1:5)).^2), 5, -10*ones(1, 5), 10*ones(1, 5), optimoptions('particleswarm', 'Display', 'off'));")
near('particleswarm: Rastrigin in two dimensions; a bowl in five, centred at 1:5', (W['x'], W['f'], W['xs']), ([[0, 0]], 0, [[1, 2, 3, 4, 5]]), 1e-4)
C('particleswarm stops when the swarm stalls', W['flag'] == 1, W['flag'])
W, _ = run("rng(5); [x, f] = simulannealbnd(@(x) (x(1) - 1)^2 + 10*(x(2) - x(1)^2)^2, [-1 2], [-3 -3], [3 3], optimoptions('simulannealbnd', 'Display', 'off'));")
near('simulannealbnd: a Rosenbrock-like valley, minimum at (1, 1)', W['x'], [[1, 1]], 0.15)
W, _ = run("o = optimoptions('patternsearch', 'Display', 'off'); [x, f, e] = patternsearch(@(x) (x(1) - 1)^2 + (x(2) + 2)^2, [0 0], [], [], [], [], [], [], [], o); "
           "[xl, fl] = patternsearch(@(x) (x(1) - 2)^2 + (x(2) - 1)^2, [0 0], [1 1], 2, [], [], [], [], [], o); "
           "[xn, fn] = patternsearch(@(x) x(1) + x(2), [0 0], [], [], [], [], [], [], @(x) deal(x(1)^2 + x(2)^2 - 1, []), o); "
           "[xe, fe] = patternsearch(@(x) x(1)^2 + x(2)^2, [3 1], [], [], [1 1], 2, [], [], [], o); [xb, fb] = patternsearch(@(x) -x(1)*x(2), [0.5 0.5], [], [], [], [], [0 0], [1 2], [], o);")
near('patternsearch: an unconstrained bowl, exactly (the mesh hits the minimum)', (W['x'], W['f'], W['e']), ([[1, -2]], 0, 1), 1e-6)
near('with a linear inequality: (1.5, 0.5)', (W['xl'], W['fl']), ([[1.5, 0.5]], 0.5), 1e-4)
near('with a nonlinear constraint (augmented Lagrangian): -sqrt(2) at (-1, -1)/sqrt(2)', (W['xn'], W['fn']), ([[-1, -1] / np.sqrt(2)], -math.sqrt(2)), 1e-3)
near('with an equality: (1, 1); within bounds: the corner (1, 2)', (W['xe'], W['xb']), ([[1, 1]], [[1, 2]]), 1e-3)
W, _ = run("rng(6); [x, f] = surrogateopt(@(x) (x(1) - 0.3)^2 + (x(2) + 0.7)^2 + 1, [-2 -2], [2 2], optimoptions('surrogateopt', 'Display', 'off', 'MaxFunctionEvaluations', 60)); "
           "rng(7); [xi, fi] = surrogateopt(@(x) (x(1) - 0.3)^2 + (x(2) - 2.2)^2, [-3 -3], [3 3], [1 2], optimoptions('surrogateopt', 'Display', 'off', 'MaxFunctionEvaluations', 60));")
near('surrogateopt: a smooth bowl in 60 evaluations', (W['x'], W['f']), ([[0.3, -0.7]], 1), 0.02)
near('surrogateopt with integers', W['xi'], [[0, 2]], 1e-12)
W, _ = run("rng(8); [x, f] = gamultiobj(@(x) [x(1)^2, (x(1) - 2)^2], 1, [], [], [], [], -5, 5, optimoptions('gamultiobj', 'Display', 'off'));")
xs = a(W['x']).reshape(-1)
F = a(W['f'])
C('gamultiobj: the Pareto set of Schaffer\'s problem is [0, 2]; the front f2 = (sqrt(f1) - 2)^2', np.all(xs > -0.05) and np.all(xs < 2.05) and np.ptp(xs) > 1.5
  and np.allclose(F[:, 1], (np.sqrt(F[:, 0]) - 2) ** 2, atol=1e-6), (xs.min(), xs.max()))
W, out = run("p = createOptimProblem('fmincon', 'objective', @(x) -sinc(x(1)) * sinc(x(2)), 'x0', [3 3], 'lb', [-5 -5], 'ub', [5 5]); "
             "rng(9); [x, f, e, o, sols] = run(MultiStart('Display', 'off'), p, 15); n = numel(sols); f1 = sols{1}.Fval; "
             "rng(10); [xg, fg] = run(GlobalSearch('Display', 'off'), p); [xl, fl] = fmincon(p);")
near('MultiStart: the global maximum of sinc(x) sinc(y) among its local ones, the solutions best first', (W['x'], W['f'], W['f1']), ([[0, 0]], -1, -1), 1e-5)
C('several distinct local solutions found', W['n'] >= 2, W['n'])
near('GlobalSearch finds it too; fmincon alone from (3, 3) does not', (W['xg'], W['fg']), ([[0, 0]], -1), 1e-5)
C(' ', W['fl'] > -0.5, W['fl'])
W, _ = run("o = optimoptions('ga', 'PopulationSize', 30, 'MaxGenerations', 5); ps = o.PopulationSize; ms = MultiStart('XTolerance', 1e-3); xt = ms.XTolerance;")
near('optimoptions takes the new solvers\' options; MultiStart its own', (W['ps'], W['xt']), (30, 1e-3))
raises("particleswarm(@(x) x, 1, 1, 0)", 'lower bound is above')
raises("surrogateopt(@(x) x, -Inf, 1)", 'finite bounds')
raises("createOptimProblem('ga', 'objective', @(x) x)", "The solver is")

sys.exit(C.done())
