"""Control systems, run natively (CPython with numpy and scipy): models made
every way and shown, their algebra (products, sums, feedback, inverses,
MIMO indexing and concatenation, delays), conversions against SciPy,
time responses against closed forms and scipy.signal, frequency responses,
margins (a textbook loop), norms, LQR, pole placement, Kalman filters and
the matrix equations against SciPy's solvers, reductions (minreal,
balanced realizations), root loci, PID controllers and discretization.

    python3 test_control.py          (from any folder)
"""
import asyncio
import math
import os
import sys

import numpy as np
import scipy.linalg as sla
import scipy.signal as ss

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
        return np.concatenate([np.asarray(v, dtype=complex if np.iscomplexobj(v) else float).reshape(-1) for v in x])
    return np.asarray(x, dtype=complex if np.iscomplexobj(x) else float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if w.size < 30 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def sortc(v):
    v = np.asarray(v, complex).reshape(-1)
    return v[np.lexsort((v.imag, v.real))]


# ---- making and showing models -----------------------------------------------------------------------------------------------------------
W, out = run("G = tf([1 2], [1 3 2])\nZ = zpk(-1, [-2 -3], 5)\nS = ss([-1 0; 1 -2], [1; 0], [0 1], 0)\n"
             "s = tf('s'); H = (s + 1)/(s^2 + 2*s + 4); [n, d] = tfdata(H, 'v'); [z, p, k] = zpkdata(Z, 'v'); [A, B, Cm, D] = ssdata(S); cl = class(H); vz = class(zpk(H));")
same('tf, zpk and ss shown as the language shows them', all(t in out for t in ('s + 2', 's^2 + 3 s + 2', '5 (s+1)', '(s+2) (s+3)', 'Continuous-time transfer function.',
                                                                              'Continuous-time zero/pole/gain model.', 'Continuous-time state-space model.', 'x1')), True)
near("tf('s') builds a model by arithmetic; tfdata, zpkdata, ssdata", (W['n'], W['d'], W['z'], sortc(a(W['p'])).real, W['k'], W['A']),
     ([[0, 1, 1]], [[1, 2, 4]], [[-1]], [-3, -2], 5, [[-1, 0], [1, -2]]))
same('the classes', (W['cl'].str(), W['vz'].str()), ('tf', 'zpk'))

# ---- algebra -----------------------------------------------------------------------------------------------------------------------------------
W, _ = run("s = tf('s'); G1 = 1/(s + 1); G2 = 2/(s + 3); P = G1*G2; [pn, pd] = tfdata(P, 'v'); Sm = G1 + G2; [sn, sd] = tfdata(Sm, 'v'); "
           "F = feedback(G1, G2); [fn, fd] = tfdata(F, 'v'); Fp = feedback(G1, 1, +1); [gn, gd] = tfdata(Fp, 'v'); I = inv(G1); [in_, id] = tfdata(I, 'v'); "
           "Q = G1^2; [qn, qd] = tfdata(Q, 'v'); Df = G1 - G1; [dn, dd] = tfdata(minreal(Df), 'v'); se = series(G1, G2); [en, ed] = tfdata(se, 'v'); pa = parallel(G1, G2); [an, ad] = tfdata(pa, 'v');")
near('G1*G2: 2/((s + 1)(s + 3))', (W['pn'], W['pd']), ([[0, 0, 2]], [[1, 4, 3]]))
near('G1 + G2: (3s + 5)/((s + 1)(s + 3))', (W['sn'], W['sd']), ([[0, 3, 5]], [[1, 4, 3]]))
near('feedback(G1, G2): G1/(1 + G1 G2) = (s + 3)/(s^2 + 4s + 5)', (W['fn'], W['fd']), ([[0, 1, 3]], [[1, 4, 5]]))
near('positive feedback with 1: 1/s', (W['gn'], W['gd']), ([[0, 1]], [[1, 0]]))
near('inv, powers', (W['in_'], W['id'], W['qn'], W['qd']), ([[1, 1]], [[0, 1]], [[0, 0, 1]], [[1, 2, 1]]))
near('G1 - G1 is zero; series and parallel', (W['dn'], W['en'], W['ed'], W['an']), (0, [[0, 0, 2]], [[1, 4, 3]], [[0, 3, 5]]))
W, _ = run("A = [-1 1; 0 -2]; B = eye(2); Cm = [1 0; 1 1]; S = ss(A, B, Cm, zeros(2)); S12 = S(1, 2); [n12, d12] = tfdata(tf(S12), 'v'); "
           "T = tf(S); g = dcgain(S); H = [tf(1, [1 1]), tf(2, [1 2])]; sz = size(H); V = [H; H]; szv = size(V); h = freqresp(H, 1); "
           "M = S * [1; 1]; szm = size(M); pM = sort(pole(M));")
near('a MIMO state-space model: an entry by indexing, its transfer function', (W['n12'], W['d12']), ([[0, 0, 1]], [[1, 3, 2]]))
near('dcgain of a MIMO model: -C A^-1 B', W['g'], -np.array([[1, 0], [1, 1]]) @ np.linalg.inv([[-1, 1], [0, -2]]))
near('concatenation side by side and one above another; the response', (W['sz'], W['szv'], W['h']), ([[1, 2]], [[2, 2]], [[1 / (1j + 1), 2 / (1j + 2)]]))
near('a MIMO model times a column: one input', (W['szm'], W['pM']), ([[2, 1]], [[-2], [-1]]))

# ---- conversions ---------------------------------------------------------------------------------------------------------------------------
num, den = [2, 3], [1, 4, 6, 2]
W, _ = run(f"G = tf({num}, {den}); S = ss(G); [A, B, Cm, D] = ssdata(S); G2 = tf(S); [n2, d2] = tfdata(G2, 'v'); Z = zpk(G); [z, p, k] = zpkdata(Z, 'v'); "
           f"[b, aa] = ss2tf(A, B, Cm, D); [A3, B3, C3, D3] = tf2ss({num}, {den});")
Ar, Br, Cr, Dr = ss.tf2ss(num, den)
near('ss of a tf: the controller canonical form (scipy.signal.tf2ss)', (W['A'], W['B'], W['Cm'], W['A3']), (Ar, Br, Cr, Ar))
near('and back: the same polynomials; ss2tf', (W['n2'], W['d2'], W['b'], W['aa']), ([[0, 0, 2, 3]], [den], [[0, 0, 2, 3]], [den]), 1e-10)
near('zpk of a tf: the roots', (sortc(a(W['p'])), a(W['z']).real, W['k']), (sortc(np.roots(den)), [-1.5], 2), 1e-10)

# ---- time responses --------------------------------------------------------------------------------------------------------------------------------
W, _ = run("G = tf(1, [1 1]); t = (0:0.5:5)'; y = step(G, t); yi = impulse(G, t); H = tf(4, [1 2 4]); [y2, t2] = step(H, t); "
           "S = ss(-1, 1, 1, 0); yo = initial(S, 2, t); u = sin(t); yl = lsim(G, u, t);")
tt = np.arange(0, 5.01, 0.5)
near('step of 1/(s + 1): 1 - exp(-t); impulse exp(-t)', (W['y'], W['yi']), ((1 - np.exp(-tt)).reshape(-1, 1), np.exp(-tt).reshape(-1, 1)), 1e-12)
wd = math.sqrt(3)
near('step of a second-order system (zeta 1/2, wn 2): the closed form', W['y2'], (1 - np.exp(-tt) * (np.cos(wd * tt) + np.sin(wd * tt) / wd)).reshape(-1, 1), 1e-12)
near('initial from x0 = 2: 2 exp(-t)', W['yo'], (2 * np.exp(-tt)).reshape(-1, 1), 1e-12)
_, yref, _ = ss.lsim(([1], [1, 1]), np.sin(tt), tt)
near('lsim of a sine (linear between samples): scipy.signal.lsim', a(W['yl']).reshape(-1), yref, 1e-8)
W, _ = run("Gd = c2d(tf(1, [1 1]), 0.5); [yd, td] = step(Gd, 3); n = numel(td);")
near('a discrete step: samples every Ts, the zoh discretization exact at them', (a(W['yd']).reshape(-1), W['n']), (1 - np.exp(-np.arange(0, 3.01, 0.5)), 7), 1e-12)
W, _ = run("H = tf(4, [1 2 4]); S = stepinfo(H); D = exp(-0.5*tf('s')) * tf(1, [1 1]); y = step(D, [0 0.25 0.5 1.5]);")
Sd = W['S']
over = 100 * math.exp(-math.pi * 0.5 / math.sqrt(0.75))
near('stepinfo: the overshoot exp(-pi zeta/sqrt(1 - zeta^2)), the peak time pi/wd', (Sd.get1('Overshoot'), Sd.get1('PeakTime')), (over, math.pi / wd), 2e-3)
near('a delay shifts the response', W['y'], [[0], [0], [0], [1 - math.exp(-1)]], 1e-9)

# ---- frequency responses, margins, norms ------------------------------------------------------------------------------------------------------
W, _ = run("H = tf(4, [1 2 4]); [m, p] = bode(H, [0.5 2 8]); f = evalfr(H, 2i); L = tf(4, [1 3 2 0]); [Gm, Pm, Wcg, Wcp] = margin(L); "
           "M = allmargin(L); b = bandwidth(tf(1, [1 1])); n2 = norm(H); ninf = norm(H, Inf); [gp, fp] = getPeakGain(H); dc = dcgain(H); "
           "[wn, z] = damp(H); st = isstable(H); us = isstable(tf(1, [1 -1]));")
Hj = 4 / ((1j * np.array([0.5, 2, 8])) ** 2 + 2j * np.array([0.5, 2, 8]) + 4)
near('bode: the gain and the phase in degrees', (a(W['m']).reshape(-1), a(W['p']).reshape(-1)), (np.abs(Hj), np.degrees(np.angle(Hj))), 1e-12)
near('evalfr', W['f'], 4 / ((2j) ** 2 + 4j + 4), 1e-12)
near('margin of 4/(s(s + 1)(s + 2)): Gm 1.5 at sqrt(2); Pm and Wcp from |L(jw)| = 1', (W['Gm'], W['Wcg']), (1.5, math.sqrt(2)), 1e-8)
wc = __import__('scipy.optimize', fromlist=['brentq']).brentq(lambda w: abs(4 / (1j * w * (1j * w + 1) * (1j * w + 2))) - 1, 0.5, 2)
near(' ', (W['Wcp'], W['Pm']), (wc, 180 + math.degrees(np.angle(4 / (1j * wc * (1j * wc + 1) * (1j * wc + 2))))), 1e-8)
same('allmargin agrees, the loop stable when closed', (bool(W['M'].get1('Stable')), round(float(a(W['M'].get1('GainMargin')).reshape(-1)[0]), 8)), (True, 1.5))
near('bandwidth of 1/(s + 1): 1 rad/s (the -3 dB point, 10^(-3/20))', W['b'], math.sqrt(10 ** 0.3 - 1), 1e-8)
near('norms of 4/(s^2 + 2s + 4): H2 = 1, Hinf = 1/(2 zeta sqrt(1 - zeta^2)) at wn sqrt(1 - 2 zeta^2)', (W['n2'], W['ninf'], W['gp'], W['fp']), (1.0, 1 / (2 * 0.5 * math.sqrt(0.75)), 1 / (2 * 0.5 * math.sqrt(0.75)), 2 * math.sqrt(0.5)), 1e-8)
near('dcgain, damp, isstable', (W['dc'], W['wn'], W['z'], W['st'], W['us']), (1, [[2], [2]], [[0.5], [0.5]], 1, 0), 1e-12)

# ---- design and the matrix equations ------------------------------------------------------------------------------------------------------
A = np.array([[0, 1], [-2, -3]])
B = np.array([[0], [1]])
Cm = np.array([[1, 0]])
Q, Rm = np.diag([2.0, 1.0]), np.array([[0.5]])
W, _ = run(f"A = [0 1; -2 -3]; B = [0; 1]; Cm = [1 0]; Q = diag([2 1]); R = 0.5; [K, S, P] = lqr(A, B, Q, R); X = care(A, B, Q, R); "
           f"Kp = place(A, B, [-4 -5]); ka = acker(A, B, [-4 -5]); Xl = lyap(A, Q); Xd = dlyap(A/4, Q); Xs = dare(A/4, B, Q, R); "
           f"Co = ctrb(A, B); Ob = obsv(A, Cm); sys = ss(A, B, Cm, 0); Wc = gram(sys, 'c'); [L, Pe] = lqe(A, B, Cm, 1, 0.1); "
           f"[kest, Lk] = kalman(ss(A, [B B], Cm, [0 0]), 1, 0.1); Pc = covar(sys, 1); [Kd, Sd] = dlqr(A/4, B, Q, R);")
Xr = sla.solve_continuous_are(A, B, Q, Rm)
near('lqr: K = R^-1 B\'X, X the stabilizing CARE solution (scipy)', (W['K'], W['S'], W['X']), (np.linalg.solve(Rm, B.T @ Xr), Xr, Xr), 1e-9)
near('place and acker put the poles at -4 and -5', (sortc(np.linalg.eigvals(A - B @ a(W['Kp']))).real, sortc(np.linalg.eigvals(A - B @ a(W['ka']))).real), ([-5, -4], [-5, -4]), 1e-9)
near('lyap: A X + X A\' + Q = 0; dlyap: A X A\' - X + Q = 0', (A @ a(W['Xl']) + a(W['Xl']) @ A.T + Q, (A / 4) @ a(W['Xd']) @ (A / 4).T - a(W['Xd']) + Q), (np.zeros((2, 2)), np.zeros((2, 2))), 1e-10)
near('dare (scipy); dlqr', (W['Xs'], W['Sd']), (sla.solve_discrete_are(A / 4, B, Q, Rm),) * 2, 1e-9)
near('ctrb, obsv, the controllability Gramian', (W['Co'], W['Ob'], W['Wc']), (np.hstack([B, A @ B]), np.vstack([Cm, Cm @ A]), sla.solve_continuous_lyapunov(A, -B @ B.T)), 1e-10)
Pk = sla.solve_continuous_are(A.T, Cm.T, B @ B.T, np.array([[0.1]]))
near('lqe and kalman: the estimator gain P C\'/R', (W['L'], W['Lk']), (Pk @ Cm.T / 0.1, Pk @ Cm.T / 0.1), 1e-9)
near('covar: C P C\', P the state covariance', W['Pc'], (Cm @ sla.solve_continuous_lyapunov(A, -B @ B.T) @ Cm.T).item(), 1e-10)

# ---- reduction and realizations ---------------------------------------------------------------------------------------------------------------
W, _ = run("s = tf('s'); G = (s + 1)/((s + 1)*(s + 2)); Gm = minreal(G); [n, d] = tfdata(Gm, 'v'); S = ss([-1 0 0; 0 -2 0; 0 0 -3], [1; 1; 0], [1 0 1], 0); Sm = minreal(S); ns = size(Sm.A, 1); "
           "H = ss(tf(1, [1 6 11 6]) + tf(0.001, [1 10])); [Hb, g] = balreal(H); Wc = gram(Hb, 'c'); Wo = gram(Hb, 'o'); hs = hsvd(H); "
           "Hr = balred(H, 3); d1 = dcgain(Hr) - dcgain(H); Hm = modred(Hb, 4); d2 = dcgain(Hm) - dcgain(H); [Mc, T] = canon(ss(tf(1, [1 3 2])), 'modal'); Am = Mc.A;")
near('minreal cancels (s + 1); drops an uncontrollable and an unobservable state', (W['n'], W['d'], W['ns']), ([[0, 1]], [[1, 2]], 1), 1e-9)
g = a(W['g']).reshape(-1)
near('balreal: both Gramians diag(g), the Hankel singular values', (W['Wc'], W['Wo'], W['hs']), (np.diag(g), np.diag(g), g.reshape(-1, 1)), 1e-8)
near('balred and modred keep the DC gain (MatchDC)', (W['d1'], W['d2']), (0, 0), 1e-10)
near('canon modal: diagonal A, the poles', np.sort(np.diag(a(W['Am']))), [-2, -1], 1e-10)
W, _ = run("[n, d] = pade(0.5, 3); P = pade(exp(-0.2*tf('s'))*tf(1, [1 1]), 2); pd = sort(pole(P));")
near('pade(0.5, 3): the Pade coefficients, the numerator D(-s)', (W['n'], W['d']), ([[-1, 24, -240, 960]], [[1, 24, 240, 960]]), 1e-10)
near('pade of a model: its delay replaced', a(W['pd']).reshape(-1).real.shape, (3,))

# ---- root locus, PID, discretization -------------------------------------------------------------------------------------------------------------
W, _ = run("L = tf([1 3], [1 3 2 0]); [r, k] = rlocus(L, [0.5 2 10]); C = pid(2, 1, 0.5, 0.1); [cn, cd] = tfdata(C, 'v'); kp = C.Kp; cls = class(C); "
           "Gd = c2d(tf(1, [1 1]), 0.1); [dn, dd] = tfdata(Gd, 'v'); Gt = c2d(tf(1, [1 1]), 0.1, 'tustin'); [tn, td] = tfdata(Gt, 'v'); "
           "Gb = d2c(Gd); [bn, bd] = tfdata(Gb, 'v'); Gm = c2d(zpk(-2, [-1 -3], 1), 0.1, 'matched'); [zm, pm] = zpkdata(Gm, 'v');")
r = a(W['r'])
for kk, col in zip([0.5, 2, 10], r.T):
    near(f'rlocus: the roots of den + {kk} num', sortc(col), sortc(np.roots(np.polyadd([1, 3, 2, 0], kk * np.array([1, 3])))), 1e-9)
near('pid(2, 1, 0.5, 0.1): Kp + Ki/s + Kd s/(Tf s + 1) = (7 s^2 + 21 s + 10)/(s^2 + 10 s)', (W['cn'], W['cd'], W['kp']), ([[7, 21, 10]], [[1, 10, 0]], 2), 1e-10)
same('its class', W['cls'].str(), 'pid')
nd, dd, _ = ss.cont2discrete(([1], [1, 1]), 0.1, method='zoh')
near('c2d zoh and tustin (scipy cont2discrete); d2c gives the model back', (a(W['dn']).reshape(-1)[-1], W['dd'], a(W['tn']).reshape(-1), W['bn'], W['bd']),
     (np.asarray(nd).reshape(-1)[-1], [dd], np.asarray(ss.cont2discrete(([1], [1, 1]), 0.1, method='bilinear')[0]).reshape(-1), [[0, 1]], [[1, 1]]), 1e-9)
near("c2d 'matched': poles and zeros mapped by exp(s Ts)", (sortc(a(W['pm'])).real, np.real(a(W['zm'])).reshape(-1)[:1]), (sortc(np.exp(np.array([-3, -1]) * 0.1)).real, [math.exp(-0.2)]), 1e-10)
raises("tf([1 2], 0)", 'denominator is zero')
raises("feedback(tf(1, [1 1]), ss(eye(2)))", 'inner dimensions')
raises("margin(ss(eye(2)))", 'one input and one output')
raises("c2d(c2d(tf(1, [1 1]), 0.1), 0.1)", 'continuous-time')

W, _ = run("[y, t] = impulse(tf(4, [1 3 3 1])); T = t(end); [m, i] = max(y); tp = t(i); [y2, t2] = step(tf(1, [1 0.2 1])); T2 = t2(end);")
near('impulse of a triple pole: to (7 + 3*2) time constants, not out to where root finding\'s split poles would oscillate; peak 8/e^2', (W['T'], W['m']), (13, 8 / math.e ** 2), 1e-3)
C('  at t = 2, to the time step', abs(W['tp'] - 2) < 13 / 399, W['tp'])
near('a lightly damped pair: seven time constants', W['T2'], 70, 1e-9)

W, _ = run("pzmap(tf([1 0.5], conv([1 0.4 4], [1 2]))); xl = xlim; yl = ylim; close all")
near('pzmap: limits a tenth beyond the poles and zeros (rounded-out ones put the poles on the edge)', (W['xl'], W['yl']),
     ([[-2 - 0.18, -0.2 + 0.18]], [[-1.99 * 1.2, 1.99 * 1.2]]), 1e-2)
W, _ = run("rlocus(tf([1 3], [1 3 2 0])); xl = xlim; yl = ylim; close all; nyquist(tf(4, conv([1 1], [1 2 2]))); nx = xlim; close all")
near('rlocus: limits about the poles and zeros (gains to 1e4 made them reach 125), a tenth beyond', W['xl'], [[-3.3, 0.3]], 1e-12)
C('  the branches along the asymptotes shown to 2.5 spreads from the middle', 7 < W['yl'][0, 1] < 9.5, W['yl'])
C('nyquist: the critical point -1 inside the box, not on its edge', W['nx'][0, 0] < -1.05, W['nx'])
W, _ = run("margin(tf(4, conv([1 1], [1 2 2]))); h = findobj(gcf, 'Type', 'line'); n = numel(h); "
           "x = {}; y = {}; for i = 1:n, x{i} = get(h(i), 'XData'); y{i} = get(h(i), 'YData'); end; close all")
segs = sorted((tuple(np.round(a(x).reshape(-1), 4)), tuple(np.round(a(y).reshape(-1), 4))) for x, y in zip(W['x'].a.reshape(-1), W['y'].a.reshape(-1)) if a(x).size == 2)
near('margin draws the margins: a gain line at Wcg from -Gm dB to 0, a phase line at Wcp from -180 by Pm, and the 0 dB and -180 lines',
     (W['n'], [s_ for s_ in segs if s_[0][0] == s_[0][1]]), (6, [((1.2357, 1.2357), (-180, -130.1833)), ((2.0, 2.0), (-7.9588, 0.0))]), 1e-3)
W, _ = run("g = dcgain(feedback(2, 3)); p = dcgain(parallel(2, 3));")
near('feedback and parallel of two numbers: static gains, 2/(1 + 6) and 5', (W['g'], W['p']), (2 / 7, 5))
sys.exit(C.done())
