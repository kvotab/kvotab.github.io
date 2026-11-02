"""The ODE solvers, run natively (CPython with numpy and scipy): that each
name runs its own method, to its order, and what the methods take.

    python3 test_ode.py          (from any folder; needs numpy and scipy)

The solvers themselves (plab/odesolvers.py) are checked through SciPy's
solve_ivp against exact solutions and SciPy's own solvers; the MATLAB side
(options, mass matrices, DAEs, decic, events) through ode... calls.
"""
import asyncio
import math
import os
import sys
import warnings

import numpy as np
from scipy.integrate import solve_ivp

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab import odesolvers as S  # noqa: E402
from plab import vernertab as V  # noqa: E402

R.setup()
warnings.simplefilter('ignore')


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


check = Checks()


def run(code):
    """Run code in a fresh base workspace: the output text."""
    R.BASE.clear()
    R.take_output()
    asyncio.run(R.execute(code))
    return R.take_output()


def num(name):
    v = R.BASE[name]
    a = np.asarray(v.a if hasattr(v, 'a') else v)
    return a.reshape(-1).tolist() if a.size != 1 else a.reshape(-1)[0].item()


def error_of(code):
    """The Command Window's text after code (an error is written there)."""
    return run(code)


def order(errs):
    e = np.asarray(errs, float)
    return np.log2(e[:-1] / e[1:])


# ---- the tables of Verner's pairs ---------------------------------------------------------------
for name, p in (('VERN8', 8), ('VERN9', 9)):
    s, a, C, A, B, E, Rm, end = S._tableau(name)
    rows = all(abs(A[i, :i].sum() - C[i]) < 1e-14 * max(1.0, np.abs(A[i, :i]).sum()) for i in range(1, a))
    quad = max(abs(B @ C[:s] ** q - 1 / (q + 1)) for q in range(p))
    check(f'{name}: the weights sum to 1, the error weights to 0, each node is its row sum',
          abs(B.sum() - 1) < 1e-14 and abs(E.sum()) < 1e-13 and rows, (B.sum(), E.sum()))
    check(f'{name}: sum b c^q = 1/(q + 1) up to order {p}', quad < 1e-13, quad)
    size = np.abs(Rm).sum(1).max()       # its coefficients reach 1e5 and cancel
    check(f'{name}: the interpolant at the end of the step is the step', np.abs(Rm.sum(1)[:s] - B).max() < 1e-14 * size and np.abs(Rm.sum(1)[s:]).max() < 1e-14 * size)
    check(f'{name}: the first extra stage is f at the end of the step (it is not evaluated again)', bool(end))

# ---- orders, with fixed steps over [0, 20], on y' = cos(t) y (y = exp(sin t)) ---------------------
f = lambda t, y: np.cos(t) * y      # noqa: E731
for name, p in (('VERN8', 8), ('VERN9', 9)):
    s, a, C, A, B, E, Rm, end = S._tableau(name)
    glob, mids = [], []
    for n in (20, 40, 80):
        h, y, t, worst = 20.0 / n, np.array([1.0]), 0.0, 0.0
        for _ in range(n):
            K = np.zeros((a, 1))
            K[0] = f(t, y)
            for i in range(1, a):
                K[i] = f(t + C[i] * h, y + h * (A[i, :i] @ K[:i]))
            worst = max(worst, abs((y + h * ((K.T @ Rm) @ (0.37 ** np.arange(1, Rm.shape[1] + 1))))[0] - math.exp(math.sin(t + 0.37 * h))))
            y, t = y + h * (B @ K[:s]), t + h
        glob.append(abs(y[0] - math.exp(math.sin(20.0))))
        mids.append(worst)
    check(f'{name}: the solution of order {p}', order(glob).min() > p - 0.5, order(glob))
    check(f'{name}: the interpolant of order {p - 1} (an error O(h^{p}) in a step)', order(mids).min() > p - 0.5, order(mids))

# ---- ode113: Adams-Bashforth-Moulton ------------------------------------------------------------
g = lambda t, y: np.array([y[1], -y[0]])      # noqa: E731
errs, steps = [], []
for tol in (1e-4, 1e-7, 1e-10):
    sol = solve_ivp(g, (0, 20), [0.0, 1.0], method=S.Adams, rtol=tol, atol=tol * 1e-3, dense_output=True)
    tq = np.linspace(0, 20, 501)
    errs.append(np.abs(sol.y[0] - np.sin(sol.t)).max())
    steps.append(sol.t.size - 1)
    check(f'Adams at {tol:.0e}: two evaluations a step (PECE)', sol.nfev <= 2 * (sol.t.size - 1) + 6 + 2 * sol.t.size // 10, (sol.nfev, sol.t.size))
    check(f'Adams at {tol:.0e}: between the steps (INTRP) as accurate as at them', np.abs(sol.sol(tq)[0] - np.sin(tq)).max() < 5 * errs[-1] + 1e-12)
check('Adams: the error follows the tolerance', errs[0] < 1e-3 and 1e-8 < errs[0] / errs[2] < 1e9 and errs[2] < 1e-8, errs)
check('Adams: fewer steps than order 5 needs at a tight tolerance',
      steps[2] < solve_ivp(g, (0, 20), [0.0, 1.0], method='RK45', rtol=1e-10, atol=1e-13).t.size - 1, steps)

# ---- ode15s: SciPy's BDF exactly, when there is no mass matrix -----------------------------------
rob = lambda t, y: np.array([-0.04 * y[0] + 1e4 * y[1] * y[2], 0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] ** 2, 3e7 * y[1] ** 2])   # noqa: E731
a = solve_ivp(rob, (0, 40), [1, 0, 0], method='BDF', rtol=1e-6, atol=1e-10)
b = solve_ivp(rob, (0, 40), [1, 0, 0], method=S.NDF, rtol=1e-6, atol=1e-10)
check('NDF without a mass matrix takes the steps of SciPy\'s BDF, bit for bit',
      np.array_equal(a.t, b.t) and np.array_equal(a.y, b.y) and (a.nfev, a.njev, a.nlu) == (b.nfev, b.njev, b.nlu))

# ---- the stiff and DAE solvers on Robertson's problem ----------------------------------------------
rob_dae = lambda t, y: np.array([-0.04 * y[0] + 1e4 * y[1] * y[2], 0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] ** 2, y[0] + y[1] + y[2] - 1])  # noqa: E731
tt = np.array([0.4, 4, 40, 400, 4e3, 4e4])
truth = solve_ivp(rob, (0, 4e4), [1, 0, 0], method='Radau', rtol=1e-11, atol=1e-14, dense_output=True).sol(tt)
for cls, kind, fn, kw in ((S.NDF, 'DAE', rob_dae, {'mass': np.diag([1.0, 1, 0])}), (S.Trapezoid, 'DAE', rob_dae, {'mass': np.diag([1.0, 1, 0])}),
                          (S.TRBDF2, 'ODE', rob, {}), (S.Rosenbrock23, 'ODE', rob, {}), (S.Trapezoid, 'ODE', rob, {})):
    worst = []
    for tol in (1e-4, 1e-6):
        sol = solve_ivp(fn, (0, 4e4), [1, 0, 0], method=cls, rtol=tol, atol=[tol * 1e-2, tol * 1e-6, tol * 1e-2], t_eval=tt, **kw)
        worst.append(np.abs((sol.y - truth) / truth).max())
    # a method of order 2 that keeps its local error below tol has a global error near tol^(2/3)
    lim = (lambda tol: 30 * tol) if cls is S.NDF else (lambda tol: 3 * tol ** (2 / 3))
    check(f'{cls.__name__} on Robertson ({kind}): relative error near the tolerance and falling with it',
          worst[0] < lim(1e-4) and worst[1] < lim(1e-6) and worst[1] < worst[0], worst)
sol = solve_ivp(rob_dae, (0, 40), [1, 0, 0.5], method=S.NDF, rtol=1e-6, atol=[1e-8, 1e-12, 1e-8], mass=np.diag([1.0, 1, 0]), t_eval=[0, 40])
check('a DAE: the algebraic variable is moved until its equation holds at the start', np.abs(sol.y[:, 0] - [1, 0, 0]).max() < 1e-12, sol.y[:, 0])
sol = solve_ivp(lambda t, y: y, (0, 4e4), [1.0, 0, 0], method=S.NDF, bdf=True, rtol=1e-6, atol=[1e-8, 1e-12, 1e-8], t_eval=tt,
                residual=lambda t, y, yp: np.array([yp[0] - (-0.04 * y[0] + 1e4 * y[1] * y[2]), yp[1] - (0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] ** 2), y.sum() - 1]),
                yp0=np.array([-0.04, 0.04, 0.0]))
check('NDF on F(t, y, y\') = 0 (ode15i): Robertson in implicit form', np.abs((sol.y - truth) / truth).max() < 30e-6, np.abs((sol.y - truth) / truth).max())

# stiffness: van der Pol with mu = 1000 takes the stiff solvers few steps
vdp = lambda t, y: np.array([y[1], 1000 * (1 - y[0] ** 2) * y[1] - y[0]])    # noqa: E731
for cls in (S.NDF, S.Rosenbrock23, S.Trapezoid, S.TRBDF2):
    sol = solve_ivp(vdp, (0, 3000), [2, 0], method=cls, rtol=1e-4, atol=1e-6)
    check(f'{cls.__name__}: van der Pol (mu = 1000) over 3000 in under 3000 steps', sol.status == 0 and sol.t.size < 3000 and abs(sol.y[0, -1] + 1.5) < 0.2,
          (sol.status, sol.t.size, sol.y[0, -1]))

# ---- through ode...: the names, their options, mass matrices, DAEs ------------------------------
for s in ('ode45', 'ode23', 'ode113', 'ode78', 'ode89', 'ode15s', 'ode23s', 'ode23t', 'ode23tb'):
    run(f"o = odeset('RelTol', 1e-6, 'AbsTol', 1e-9); [t, y] = {s}(@(t, y) [y(2); -y(1)], [0 6], [0; 1], o); e = max(abs(y(:, 1) - sin(t))); "
        f"sol = {s}(@(t, y) -y, [0 2], 1, o); m = max(abs(deval(sol, linspace(0, 2, 41)) - exp(-linspace(0, 2, 41))));")
    check(f'{s}: the oscillator and an interpolated decay', num('e') < 2e-3 and num('m') < 5e-4, (num('e'), num('m')))
run("[t, y] = ode78(@(t, y) -y, [0 1], 1); a = numel(t); [t, y] = ode89(@(t, y) -y, [0 1], 1); b = numel(t); [t, y] = ode113(@(t, y) -y, [0 1], 1); c = numel(t); "
    "[t, y] = ode45(@(t, y) -y, [0 1], 1); d = numel(t);")
check('Refine: 8 points a step for ode78, 4 for ode89 and ode45, 1 for ode113', ((num('a') - 1) % 8, (num('b') - 1) % 4, (num('d') - 1) % 4, num('c') < num('a')) == (0, 0, 0, True))
run("o = odeset('Mass', [2 0; 0 4], 'RelTol', 1e-8, 'AbsTol', 1e-10); e = 0; "
    "for s = {'ode45', 'ode113', 'ode78', 'ode89', 'ode15s', 'ode23t', 'ode23tb'}, [t, y] = feval(s{1}, @(t, y) [-2*y(1); -4*y(2)], [0 1], [1; 1], o); e = max(e, max(abs(y(end, :) - exp(-1)))); end")
check('a constant mass matrix, explicit and implicit solvers alike', num('e') < 1e-5, num('e'))
run("o = odeset('Mass', @(t, y) 1 + y^2, 'RelTol', 1e-7, 'AbsTol', 1e-9); e = 0; "
    "for s = {'ode45', 'ode15s', 'ode23t', 'ode23tb'}, [t, y] = feval(s{1}, @(t, y) 1, [0 1], 0, o); x = y(end); e = max(e, abs(x + x^3/3 - 1)); end")
check('a mass matrix M(t, y): (1 + y^2) y\' = 1', num('e') < 1e-4, num('e'))
run("o = odeset('Mass', @(t) 1 + t); [t, y] = ode113(@(t, y) -y, [0 1], 1, o); e = abs(y(end) - 0.5);")
check('a mass matrix of t alone (one input)', num('e') < 1e-3, num('e'))
check('ode23s takes a constant mass matrix only', 'constant mass matrix' in error_of("ode23s(@(t, y) -y, [0 1], 1, odeset('Mass', @(t) 2));"))
check('a singular mass matrix is refused by the solvers that cannot take a DAE',
      all('ode15s and ode23t can' in error_of(f"{s}(@(t, y) [y(2); y(1) - 1], [0 1], [0; 1], odeset('Mass', diag([1 0])));") for s in ('ode45', 'ode113', 'ode23s', 'ode23tb')))
run("f = @(t, y) [-0.04*y(1) + 1e4*y(2)*y(3); 0.04*y(1) - 1e4*y(2)*y(3) - 3e7*y(2)^2; y(1) + y(2) + y(3) - 1]; "
    "o = odeset('Mass', diag([1 1 0]), 'RelTol', 1e-6, 'AbsTol', [1e-8 1e-12 1e-8]); [t, a] = ode15s(f, [0 40], [1; 0; 0], o); [t, b] = ode23t(f, [0 40], [1; 0; 0], o); "
    "a = a(end, :); b = b(end, :);")
want = solve_ivp(rob, (0, 40), [1, 0, 0], method='Radau', rtol=1e-11, atol=1e-14).y[:, -1]
check('ode15s and ode23t solve Robertson as a DAE (y3 from the conservation law)',
      np.abs(np.array(num('a')) / want - 1).max() < 1e-4 and np.abs(np.array(num('b')) / want - 1).max() < 1e-4 and abs(sum(num('a')) - 1) < 1e-12)
run("f = @(t, y) [-0.04*y(1) + 1e4*y(2)*y(3); 0.04*y(1) - 1e4*y(2)*y(3) - 3e7*y(2)^2; 3e7*y(2)^2]; n = zeros(1, 3); "
    "for m = [1 2 5], s = ode15s(f, [0 40], [1; 0; 0], odeset('MaxOrder', m, 'RelTol', 1e-6, 'AbsTol', 1e-10)); n(m == [1 2 5]) = s.stats.nsteps; end; "
    "s = ode15s(f, [0 40], [1; 0; 0], odeset('BDF', 'on', 'RelTol', 1e-6, 'AbsTol', 1e-10)); nb = s.stats.nsteps;")
n = num('n')
check('MaxOrder caps the order (order 1 takes many more steps); BDF on takes other steps', n[0] > 5 * n[2] and n[1] > n[2] and num('nb') != n[2], (n, num('nb')))
check('MaxOrder outside 1 to 5 is refused', 'MaxOrder must be' in error_of("ode15s(@(t, y) -y, [0 1], 1, odeset('MaxOrder', 6));"))

# ode15i and decic
run("o = odeset('RelTol', 1e-6, 'AbsTol', 1e-9); [t, y] = ode15i(@(t, y, yp) [yp(1) - y(2); y(1) + y(2)], [0 1], [1; -1], [-1; 0], o); e = max(abs(y(end, :) - [exp(-1), -exp(-1)]));")
check('ode15i: a DAE of index 1', num('e') < 1e-5, num('e'))
check('ode15i: an inconsistent start of a DAE is refused, naming decic',
      'decic finds' in error_of("ode15i(@(t, y, yp) [yp(1) - y(2); y(1) + y(2)], [0 1], [1; -0.5], [-1; 0]);"))
out = run("[t, y] = ode15i(@(t, y, yp) yp + y, [0 1], 1, 0); e = abs(y(end) - exp(-1));")
check('ode15i: an implicit ODE\'s yp0 is corrected to fit y0, with a warning', 'corrected to fit y0' in out and num('e') < 2e-3, (out, num('e')))
run("F = @(t, y, yp) yp + 2*y; [t, y] = ode15i(F, [0 1], 1, -2, odeset('Jacobian', {2, 1}, 'RelTol', 1e-6)); a = abs(y(end) - exp(-2)); "
    "[t, y] = ode15i(F, [0 1], 1, -2, odeset('Jacobian', @(t, y, yp) deal(2, 1), 'RelTol', 1e-6)); b = abs(y(end) - exp(-2));")
check('ode15i: the Jacobian as a cell {dFdy, dFdyp} or a function', num('a') < 1e-5 and num('b') < 1e-5, (num('a'), num('b')))
run("[y0, yp0, r] = decic(@(t, y, yp) [yp(1) - y(2); y(1) + y(2)], 0, [1; -0.5], [1; 0], [3; 3], [0; 1]);")
check('decic: held components kept, the others moved until F = 0', (num('y0'), num('yp0'), num('r') < 1e-12) == ([1.0, -1.0], [-1.0, 3.0], True),
      (num('y0'), num('yp0'), num('r')))
check('decic: more than n held components is refused', 'cannot all be met' in error_of("decic(@(t, y, yp) yp - y, 0, 1, 1, 1, 1);"))

# events, odextend, outputs, backwards and complex with the new methods
run("o = odeset('Events', @(t, y) deal(y(1), 1, -1), 'RelTol', 1e-8, 'AbsTol', 1e-10); e = 0; "
    "for s = {'ode113', 'ode78', 'ode89', 'ode23s', 'ode23t', 'ode23tb', 'ode15s'}, [t, y, te] = feval(s{1}, @(t, y) [y(2); -9.81], [0 5], [10; 0], o); e = max(e, abs(te - sqrt(20/9.81))); end")
check('a terminal event is found by each new method', num('e') < 1e-7, num('e'))
run("e = 0; for s = {'ode113', 'ode78', 'ode89', 'ode23s', 'ode23t', 'ode23tb', 'ode15s'}, sol = feval(s{1}, @(t, y) -y, [0 1], 1); sol = odextend(sol, [], 3); "
    "e = max(e, abs(deval(sol, 2.5) - exp(-2.5)) / exp(-2.5)); end")
check('odextend carries each method on', num('e') < 1e-2, num('e'))
run("[t, y] = ode113(@(t, y) -y, [1 0], exp(-1)); a = abs(y(end) - 1); [t, y] = ode23tb(@(t, y) -y, [1 0], exp(-1)); b = abs(y(end) - 1);")
check('backwards in time', num('a') < 1e-3 and num('b') < 1e-2, (num('a'), num('b')))
run("[t, y] = ode113(@(t, y) 1i*y, [0 pi], 1); a = abs(y(end) + 1); [t, y] = ode23t(@(t, y) 1i*y, [0 pi], 1, odeset('RelTol', 1e-6)); b = abs(y(end) + 1);")
check('a real start with a complex derivative stays complex', num('a') < 1e-2 and num('b') < 1e-3, (num('a'), num('b')))

sys.exit(check.done())
