"""Boundary value problems, delay equations, pdepe and the ode object, run
natively (CPython with numpy and scipy): bvp4c and bvp5c against exact
solutions (with an unknown parameter, a singular term), the Lobatto IIIA
tableau against its quadrature, the guesses and options; dde23 and ddesd
against the exact piecewise solution of y' = -y(t-1) and a state-dependent
delay against a fine reference, carrying a solution on, events; pdepe
against exact heat solutions in a slab, a cylinder and a sphere (and its
second order as the mesh halves), a Neumann end, a system with an elliptic
equation; the ode object, solve and solutionFcn.

    python3 test_odemore.py          (from any folder)
"""
import asyncio
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()


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
    return C(label, ok, f'got {np.round(g, 10).tolist() if g.size < 30 else g.shape}, want {np.round(w, 10).tolist() if w.size < 30 else w.shape}')


def below(label, got, limit):
    g = float(np.max(np.abs(a(got))))
    return C(label, g <= limit, f'got {g:.3g}, limit {limit:.3g}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


# ---- the Lobatto IIIA tableau of bvp5c -----------------------------------------------------------------------------------------------------
from plab.builtins.odemore import _LOB  # noqa: E402
c, ell, Lc, A = _LOB
near('Lobatto IIIA: the last row is the four-point Lobatto quadrature (1, 5, 5, 1)/12', A[3], [1 / 12, 5 / 12, 5 / 12, 1 / 12], 1e-14)
near('each row integrates the polynomials up to degree 3 exactly to c_j (the simplifying condition C(4))',
     [[sum(A[j, k] * c[k] ** (q - 1) for k in range(4)) - c[j] ** q / q for q in range(1, 5)] for j in range(4)], np.zeros((4, 4)), 1e-14)

# ---- boundary value problems ---------------------------------------------------------------------------------------------------------------
W, out = run("xs = linspace(0, pi/2, 60); ex = [sin(xs); cos(xs)]; si = bvpinit(linspace(0, pi/2, 4), [0.5 0.5]); "
             "f = @(x, y) [y(2); -y(1)]; bc = @(ya, yb) [ya(1); yb(1) - 1]; "
             "s4 = bvp4c(f, bc, si, bvpset('RelTol', 1e-6)); e4 = max(abs(deval(s4, xs) - ex), [], 'all'); "
             "s5 = bvp5c(f, bc, si, bvpset('RelTol', 1e-6)); e5 = max(abs(deval(s5, xs) - ex), [], 'all'); "
             "[y5, yp5] = deval(s5, xs); ep = max(abs(yp5 - [cos(xs); -sin(xs)]), [], 'all'); n4 = numel(s4.x); n5 = numel(s5.x); "
             "s5c = bvp5c(f, bc, si); e5c = max(abs(deval(s5c, xs) - ex), [], 'all'); flds = fieldnames(s5)'; st = s5.stats;")
below("bvp4c: y'' = -y, y(0) = 0, y(pi/2) = 1 gives sin x (RelTol 1e-6)", W['e4'], 1e-6)
below('bvp5c: the same', W['e5'], 1e-6)
below("deval's second output: y' of the solution", W['ep'], 1e-5)
C('bvp5c, fifth order, needs no more mesh points than bvp4c for the same tolerance', W['n5'] <= W['n4'], f"{W['n5']} vs {W['n4']}")
below('bvp5c at its default tolerance (1e-3)', W['e5c'], 1e-3)
same('the solution has solver, x, y, yp, stats, idata', [x.str() for x in W['flds'].a.reshape(-1)][:5], ['solver', 'x', 'y', 'yp', 'stats'])
W, out = run("sp = bvpinit(linspace(0, pi, 10), @(x) [sin(x); cos(x)], 0.9); f = @(x, y, l) [y(2); -l*y(1)]; bc = @(ya, yb, l) [ya(1); ya(2) - 1; yb(1)]; "
             "r4 = bvp4c(f, bc, sp, bvpset('RelTol', 1e-7)); r5 = bvp5c(f, bc, sp, bvpset('RelTol', 1e-7)); l4 = r4.parameters; l5 = r5.parameters; "
             "sp2 = bvpinit(linspace(0, pi, 10), @(x) [sin(2*x); 2*cos(2*x)], 3.5); r2 = bvp5c(f, @(ya, yb, l) [ya(1); ya(2) - 2; yb(1)], sp2, bvpset('RelTol', 1e-7)); l2 = r2.parameters;")
near('an unknown parameter: the eigenvalue of y\'\' + l y = 0 near 0.9 is 1 (bvp4c, bvp5c)', (W['l4'], W['l5']), (1, 1), 1e-5)
near('and near 3.5 it is 4', W['l2'], 4, 1e-5)
W, out = run("S = [0 0; 0 -2]; f = @(x, y) [y(2); -y(1)^5]; bc = @(ya, yb) [ya(2); yb(1) - sqrt(3/4)]; si = bvpinit(linspace(0, 1, 6), [1 0]); "
             "s = bvp4c(f, bc, si, bvpset('SingularTerm', S, 'RelTol', 1e-6)); xs = linspace(0, 1, 30); e = max(abs(deval(s, xs, 1) - 1./sqrt(1 + xs.^2/3)));")
below("bvp4c's SingularTerm: the Lane-Emden equation of index 5, y = (1 + x^2/3)^(-1/2)", W['e'], 1e-5)
W, out = run("si = bvpinit([0 1 2], @(x) [x; 1]); y = si.y; pa = bvpinit([0 1], [1 2], [3 4]); p = pa.parameters; "
             "s = bvp4c(@(x, y) [y(2); -y(1)], @(ya, yb) [ya(1); yb(1) - 1], bvpinit(linspace(0, 1, 5), [0 1])); "
             "w = bvpinit(s, [-1 2]); wx = w.x([1 end]); xt = bvpxtend(s, 1.5); xtx = xt.x(end); xty = xt.y(:, end); "
             "o = bvpset('RelTol', 1e-4, 'nmax', 100); r = bvpget(o, 'reltol'); nm = bvpget(o, 'NMax'); d = bvpget(o, 'AbsTol', 7);")
near('bvpinit: a guess from a function; parameters', (W['y'], W['p']), ([[0, 1, 2], [1, 1, 1]], [[3], [4]]))
near('bvpinit(sol, [anew bnew]) widens; bvpxtend carries the end on by its slope', (W['wx'], W['xtx']), ([-1, 2], 1.5))
C('bvpxtend: y beyond b is y(b) + yp(b)*(xnew - b)', np.allclose(a(W['xty']).reshape(-1), a(W['s'].get1('y'))[:, -1] + 0.5 * a(W['s'].get1('yp'))[:, -1]), W['xty'])
near('bvpset and bvpget (names in any case, a default)', (W['r'], W['nm'], W['d']), (1e-4, 100, 7))
W, out = run("s = bvp4c(@(x, y) [y(2); -y(1)], @(ya, yb) [ya(1); yb(1) - 1], bvpinit(linspace(0, 1, 5), [0 1]), bvpset('Stats', 'on'));")
same("'Stats' 'on' reports the mesh, the residual and the calls", all(t in out for t in ('mesh of', 'maximum residual', 'calls to the ODE function', 'calls to the BC function')), True)
W, out = run("s = bvp5c(@(x, y) [y(2); 1000*sinh(y(1))], @(ya, yb) [ya(1); yb(1) - 1], bvpinit(linspace(0, 1, 5), [0 1]), bvpset('NMax', 12));")
same('more points needed than NMax: a warning, and the last solution', 'Warning' in out and 'could not be met' in out, True)
raises("bvp4c(@(x, y) [y(2); -y(1)], @(ya, yb) [ya(1); ya(1)], bvpinit(linspace(0, 1, 5), [0 1]))", 'singular')
raises("bvp4c(@(x, y) y, @(ya, yb) ya, struct('x', 1))", 'struct with x and y')
raises("bvp4c(@(x, y) y, @(ya, yb) ya, bvpinit([0 1 1 2], 1))", 'interior points')
raises("bvp5c(@(x, y) y, @(ya, yb) ya - 1, bvpinit([0 1], 1), bvpset('SingularTerm', 0))", "no 'SingularTerm'")
raises("bvpinit([1 0], 1)", 'in order')

# ---- delay differential equations -------------------------------------------------------------------------------------------------------------
exact = "e = @(t) (t<=1).*(1-t) + (t>1 & t<=2).*(1-t+(t-1).^2/2) + (t>2).*(1-t+(t-1).^2/2-(t-2).^3/6);"
W, out = run(exact + " ts = linspace(0, 3, 61); o = ddeset('RelTol', 1e-6, 'AbsTol', 1e-9); "
             "s = dde23(@(t, y, Z) -Z, 1, 1, [0 3], o); ed = max(abs(deval(s, ts) - e(ts))); dc = s.discont; "
             "s2 = ddesd(@(t, y, Z) -Z, @(t, y) t - 1, 1, [0 3], o); es = max(abs(deval(s2, ts) - e(ts))); "
             "s3 = ddesd(@(t, y, Z) -Z, 1, 1, [0 3], o); ec = max(abs(deval(s3, ts) - e(ts))); "
             "[yy, yp] = deval(s, [0.5 2.5]); "
             "h = dde23(@(t, y, Z) -Z, 1, @(t) 1, [0 3], o); eh = max(abs(deval(h, ts) - e(ts))); "
             "a1 = dde23(@(t, y, Z) -Z, 1, 1, [0 1.5], o); a2 = dde23(@(t, y, Z) -Z, 1, a1, [1.5 3], o); ea = max(abs(deval(a2, ts(ts >= 1.5)) - e(ts(ts >= 1.5)))); "
             "st = s.stats; flds = fieldnames(s)';")
below("dde23: y' = -y(t-1), history 1, against the exact piecewise polynomials", W['ed'], 1e-12)
near('dde23 steps to the points the lag carries the start to', W['dc'], [[0, 1, 2]])
below('ddesd with the delay as a function d(t, y) = t - 1', W['es'], 1e-6)
below('ddesd with a constant delay, as dde23', W['ec'], 1e-12)
near("deval's derivative of a DDE solution: y' = -y(t - 1)", W['yp'], [[-1, -(1 - 1.5 + 0.5 ** 2 / 2)]], 1e-9)
below('a history function; carrying an earlier solution on as the history', (W['eh'], W['ea']), 1e-12)
same('the DDE solution: solver, history, discont, x, y, yp, stats', [x.str() for x in W['flds'].a.reshape(-1)][:7], ['solver', 'history', 'discont', 'x', 'y', 'yp', 'stats'])


def reference_sd(T=4.0, h=2e-4):
    """y'(t) = -y(t - 1 - y(t)^2/2), history 1 before 0: RK4 with cubic Hermite storage (a fine reference)."""
    ts, ys, fs = [0.0], [1.0], []

    def at(s):
        if s <= 0:
            return 1.0
        i = min(int(s / h), len(ts) - 2)
        t0, t1 = ts[i], ts[i + 1]
        th = (s - t0) / h
        return ((2 * th ** 3 - 3 * th ** 2 + 1) * ys[i] + (th ** 3 - 2 * th ** 2 + th) * h * fs[i]
                + (-2 * th ** 3 + 3 * th ** 2) * ys[i + 1] + (th ** 3 - th ** 2) * h * fs[i + 1])

    def f(t, y):
        return -at(t - 1 - y * y / 2)
    fs.append(f(0.0, 1.0))
    t, y = 0.0, 1.0
    while t < T - 1e-12:
        k1 = fs[-1]
        k2 = f(t + h / 2, y + h / 2 * k1)
        k3 = f(t + h / 2, y + h / 2 * k2)
        k4 = f(t + h, y + h * k3)
        y = y + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        t += h
        ts.append(t)
        ys.append(y)
        fs.append(f(t, y))
    return np.array(ts), np.array(ys)


rt, ry = reference_sd()
W, out = run("s = ddesd(@(t, y, Z) -Z, @(t, y) t - 1 - y^2/2, 1, [0 4], ddeset('RelTol', 1e-7, 'AbsTol', 1e-10)); v = deval(s, [1 2 3 4]);")
below('ddesd with a delay that depends on y, against a fine RK4 reference', a(W['v']).reshape(-1) - np.interp([1, 2, 3, 4], rt, ry), 1e-5)
W, out = run("o = ddeset('Events', @(t, y, Z) deal(y, 1, -1)); s = dde23(@(t, y, Z) -Z, 1, 1, [0 5], o); xe = s.xe; ie = s.ie; xend = s.x(end); "
             "o2 = ddeset('Events', @(t, y, Z) deal(y - 0.25, 0, 0)); s2 = dde23(@(t, y, Z) -Z, 1, 1, [0 3], o2); xe2 = s2.xe; "
             "si = dde23(@(t, y, Z) -Z, 1, 1, [0 1], ddeset('InitialY', 2)); y0 = si.y(1); yh = deval(si, -0.5);")
near('a terminal event: the solution stops where y crosses zero going down (t = 1)', (W['xe'], W['ie'], W['xend']), (1, 1, 1), 1e-9)
C('non-terminal events: y = 0.25 crossed at t = 0.75 first', abs(float(a(W['xe2']).reshape(-1)[0]) - 0.75) < 1e-6 and a(W['xe2']).size >= 1, W['xe2'])
near("'InitialY': y at the start differs from the history, which stays before it", (W['y0'], W['yh']), (2, 1))
W, out = run("o = ddeset('RelTol', 1e-5, 'events', 1); r = ddeget(o, 'RelTol'); d = ddeget(o, 'MaxStep', 3);")
near('ddeset and ddeget', (W['r'], W['d']), (1e-5, 3))
raises("dde23(@(t, y, Z) -Z, 0, 1, [0 1])", 'positive delays')
raises("dde23(@(t, y, Z) -Z, 1, 1, [1 0])", 'runs forward')
raises("ddesd(@(t, y, Z) -Z, @(t, y) t + 1, 1, [0 1])", 'after t')
W, out = run("s = dde23(@(t, y, Z) -Z, 0.1, 1, [0 2], ddeset('RelTol', 1e-7, 'AbsTol', 1e-10, 'MaxStep', 0.5)); v = deval(s, 2); "
             "r = ddesd(@(t, y, Z) -Z, 0.1, 1, [0 2], ddeset('RelTol', 1e-9, 'AbsTol', 1e-12, 'MaxStep', 0.05)); w = deval(r, 2);")
near('a delay shorter than the step: the step iterated on its own interpolant (dde23 against a fine ddesd)', W['v'], W['w'], 1e-5)

# ---- pdepe -----------------------------------------------------------------------------------------------------------------------------------
W, out = run("t = linspace(0, 0.1, 5); heat = @(x, t, u, dudx) deal(1, dudx, 0); "
             "x = linspace(0, 1, 21); s = pdepe(0, heat, @(x) sin(pi*x), @(xl, ul, xr, ur, t) deal(ul, 0, ur, 0), x, t, odeset('RelTol', 1e-8, 'AbsTol', 1e-10)); "
             "e1 = max(abs(s(end, :) - exp(-pi^2*0.1)*sin(pi*x))); "
             "x2 = linspace(0, 1, 41); s2 = pdepe(0, heat, @(x) sin(pi*x), @(xl, ul, xr, ur, t) deal(ul, 0, ur, 0), x2, t, odeset('RelTol', 1e-8, 'AbsTol', 1e-10)); "
             "e2 = max(abs(s2(end, :) - exp(-pi^2*0.1)*sin(pi*x2))); sz = size(s2); "
             "r = linspace(0, 1, 41); sp = pdepe(2, heat, @(x) sinc(x), @(xl, ul, xr, ur, t) deal(0, 1, ur, 0), r, t, odeset('RelTol', 1e-8, 'AbsTol', 1e-10)); "
             "es = max(abs(sp(end, :) - exp(-pi^2*0.1)*sinc(r))); "
             "nm = pdepe(0, heat, @(x) cos(pi*x), @(xl, ul, xr, ur, t) deal(0, 1, 0, 1), x2, t, odeset('RelTol', 1e-8, 'AbsTol', 1e-10)); "
             "en = max(abs(nm(end, :) - exp(-pi^2*0.1)*cos(pi*x2))); [sol, tt] = pdepe(0, heat, @(x) sin(pi*x), @(xl, ul, xr, ur, t) deal(ul, 0, ur, 0), x, t);")
below('pdepe, the heat equation in a slab: u = exp(-pi^2 t) sin(pi x)', W['e2'], 3e-4)
C('second order: halving the mesh divides the error by about four', 3.3 < W['e1'] / W['e2'] < 4.7, W['e1'] / W['e2'])
near('sol(i, j) for one equation: a time each row', W['sz'], [[5, 41]])
below('in a sphere (m = 2), symmetric at the centre: u = exp(-pi^2 t) sin(pi r)/(pi r)', W['es'], 5e-4)
below('a Neumann end (p = 0, q = 1): u = exp(-pi^2 t) cos(pi x)', W['en'], 5e-4)
near('[sol, t] gives the times', W['tt'], np.linspace(0, 0.1, 5).reshape(-1, 1), 1e-12)


def bessel_check():
    """In a cylinder (m = 1): u = exp(-j0^2 t) J0(j0 r), j0 the first zero of J0."""
    from scipy.special import j0, jn_zeros
    z = jn_zeros(0, 1)[0]
    W, out = run(f"r = linspace(0, 1, 41); t = linspace(0, 0.1, 5); s = pdepe(1, @(x, t, u, dudx) deal(1, dudx, 0), @(x) besselj(0, {z!r}*x), "
                 "@(xl, ul, xr, ur, t) deal(0, 1, ur, 0), r, t, odeset('RelTol', 1e-8, 'AbsTol', 1e-10)); u = s(end, :);")
    r = np.linspace(0, 1, 41)
    below('in a cylinder (m = 1): u = exp(-j0^2 t) J0(j0 r)', a(W['u']).reshape(-1) - np.exp(-z ** 2 * 0.1) * j0(z * r), 5e-4)


bessel_check()
W, out = run("x = linspace(0, 1, 21); t = linspace(0, 0.05, 4); "
             "pf = @(x, t, u, dudx) deal([1; 0], [dudx(1); dudx(2)], [0; 0]); "
             "ic = @(x) [sin(pi*x); x]; bc = @(xl, ul, xr, ur, t) deal([ul(1); ul(2)], [0; 0], [ur(1); ur(2) - 1], [0; 0]); "
             "s = pdepe(0, pf, ic, bc, x, t, odeset('RelTol', 1e-7, 'AbsTol', 1e-9)); sz = size(s); v = squeeze(s(end, :, 2)); "
             "eu = max(abs(squeeze(s(end, :, 1)) - exp(-pi^2*0.05)*sin(pi*x)));")
near('a system of two: sol(i, j, k), the elliptic one (c = 0) linear between its ends', (W['sz'], W['v']), ([[4, 21, 2]], np.linspace(0, 1, 21)), 1e-8)
below('and the parabolic one as alone', W['eu'], 1e-3)
W, out = run("x = linspace(0, 1, 5); [u, du] = pdeval(0, x, x.^2, [0.1 0.6]);")
near('pdeval: linear between mesh points, the slope', (W['u'], W['du']), ([0.025, 0.375], [0.25, 1.25]), 1e-12)
raises("pdepe(3, @(x, t, u, dudx) deal(1, dudx, 0), @(x) 0, @(xl, ul, xr, ur, t) deal(ul, 0, ur, 0), linspace(0, 1, 5), [0 1 2])", 'm is 0')
raises("pdepe(0, @(x, t, u, dudx) deal(1, dudx, 0), @(x) 0, @(xl, ul, xr, ur, t) deal(ul, 0, ur, 0), [0 1], [0 1 2])", 'three points')
raises("pdepe(0, @(x, t, u, dudx) deal(1, dudx, 0), @(x) 0, @(xl, ul, xr, ur, t) deal(ul, 0, ur, 0), [0 0.5 1], [0 1])", 'three times')

# ---- the ode object ---------------------------------------------------------------------------------------------------------------------------
W, out = run("F = ode(ODEFcn=@(t, y) -2*y, InitialValue=1); S = solve(F, 1); e = S.Solution(end) - exp(-2); "
             "S2 = solve(F, linspace(0, 1, 5)); t2 = S2.Time; y2 = S2.Solution; sel = F.SelectedSolver; F.Solver = 'stiff'; sel2 = F.SelectedSolver; "
             "F.Solver = 'ode89'; sel3 = F.SelectedSolver; S3 = solve(F, 0, 1); e3 = S3.Solution(end) - exp(-2); "
             "G = ode(ODEFcn=@(t, y, p) [y(2); -p*y(1)], InitialValue=[1; 0], Parameters=4); G.RelativeTolerance = 1e-9; G.AbsoluteTolerance = 1e-11; "
             "R2 = solve(G, 0, pi); fin = R2.Solution(:, end); f = solutionFcn(G, 0, 1); v = f([0.25 0.5]); "
             "M = ode(ODEFcn=@(t, y) [y(2); -y(1)], InitialValue=[0; 1], MassMatrix=[2 0; 0 2]); sm = M.SelectedSolver; RM = solve(M, pi); mf = RM.Solution(1, end); "
             "x = solve(sym('x') + 1 == 0); xs = char(x);")
below("ode: solve(F, tf) of y' = -2y (ode45 at its default tolerance)", W['e'], 1e-5)
near('solve(F, tspan): at those times', (W['t2'], W['y2']), ([np.linspace(0, 1, 5)], [np.exp(-2 * np.linspace(0, 1, 5))]), 1e-4)
same("Solver 'auto' (ode45), 'stiff' (ode15s), a solver by name; a mass matrix makes 'auto' ode15s",
     (W['sel'].str(), W['sel2'].str(), W['sel3'].str(), W['sm'].str()), ('ode45', 'ode15s', 'ode89', 'ode15s'))
below('solve(F, t0, tf) with ode89', W['e3'], 1e-6)
near('Parameters passed as the third input; solutionFcn a function of t', (W['fin'], W['v']), ([[1], [0]], [[math.cos(0.5), math.cos(1)], [-2 * math.sin(0.5), -2 * math.sin(1)]]), 1e-7)
near('a mass matrix: 2y\' = f halves the frequency, y = sin(t/2)', W['mf'], 1, 5e-3)
same('solve still solves equations symbolically', W['xs'].str(), '-1')
W, out = run("F = ode(ODEFcn=@(t, y) -y, InitialValue=1)")
same('the ode shown with its problem and its solver', all(t in out for t in ('ode with properties:', 'Problem definition', 'Solver properties', 'SelectedSolver')), True)
raises("F = ode(ODEFcn=@(t, y) -y); solve(F, 1)", 'no InitialValue')
raises("F = ode(InitialValue=1); solve(F, 1)", 'no ODEFcn')
raises("F = ode(ODEFcn=@(t, y) -y, InitialValue=1); F.Solver = 'magic'", "Solver is 'auto'")
raises("F = ode(ODEFcn=@(t, y) -y, InitialValue=1, InitialTime=1); solve(F, 0, 2)", 'InitialTime')
raises("F = ode(ODEFcn=@(t, y) -y, InitialValue=1); f = solutionFcn(F, 0, 1); f(2)", 'within')
raises("F = ode(ODEFcn=@(t, y) -y, InitialValue=1); F.SelectedSolver = 'ode45'", 'follows from Solver')

sys.exit(C.done())
