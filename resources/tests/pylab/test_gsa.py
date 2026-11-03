"""Global sensitivity analysis and sampling, run natively (CPython with
numpy and scipy): builtins/gsa.py against Kompartment's own functions
(kompartment/src/domain/gsa.js and salib.js, through gsa-kompartment.mjs
and node) on the same designs, draws and outputs; and against what is known
exactly: the elementary effects, regression coefficients, main effects and
derivatives of a linear model, the Sobol indices of the Ishigami function,
the strata of a Latin hypercube, the first points of Sobol's and Halton's
sequences.

    python3 test_gsa.py          (from any folder; node runs the comparison)
"""
import asyncio
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char, Cell  # noqa: E402
from plab.builtins import gsa as G  # noqa: E402

R.setup()
TMP = tempfile.mkdtemp(prefix='pylab-gsa-')


def run(code):
    R.BASE.clear()
    R.BASE.gnames.clear()
    R.take_output()
    asyncio.run(R.execute(f"cd('{TMP}');\n" + code))
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


def v(x):
    if isinstance(x, (bool, float, int)):
        return np.array([float(x)])
    return np.asarray(x, dtype=float).reshape(-1, order='F')


def near(label, got, want, tol=1e-9, rel=None):
    g = np.concatenate([v(x) for x in got]) if isinstance(got, tuple) else v(got)
    w = np.asarray(want, dtype=float).reshape(-1, order='F')
    ok = g.shape == w.shape and np.allclose(g, w, rtol=rel if rel is not None else tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {g.tolist()[:8]}, want {w.tolist()[:8]}')


def col(T, name):
    return np.asarray(T.vars[T.names.index(name)], float).reshape(-1)


def err_of(code):
    W, _ = run(f"try\n{code}\nm = 'none';\ncatch e\nm = e.message;\nend")
    return W['m'].str() if isinstance(W['m'], Char) else str(W['m'])


# ---- against Kompartment ----------------------------------------------------------------------------------

class Stream:
    """Uniforms handed out one at a time, the ones used kept for node."""
    def __init__(self, seed):
        self.vals = np.random.default_rng(seed).random(400000)
        self.i = 0

    def __call__(self):
        self.i += 1
        return float(self.vals[self.i - 1])

    def used(self):
        return self.vals[:self.i].tolist()


def ishigami(U):
    X = -math.pi + 2 * math.pi * np.asarray(U)
    return np.sin(X[:, 0]) + 7 * np.sin(X[:, 1]) ** 2 + 0.1 * X[:, 2] ** 4 * np.sin(X[:, 0])


rs = np.random.default_rng(11)
cases, mine = [], []

# Morris, random walks
s = Stream(1)
U = G.morris_walks(3, 5, 6, 8, s)
y = ishigami(U)
mean, star, var, count, effects = G.morris_indices(y, U, 5, 6)
idx = [rs.integers(0, max(len(e), 1), size=(50, len(e))).reshape(-1).tolist() for e in effects]
ci = []
for k, e in enumerate(effects):
    e = np.abs(np.array(e))
    ci.append(1.959963984540054 * e[np.array(idx[k]).reshape(50, len(e))].mean(axis=1).std(ddof=1) if len(e) >= 2 else math.nan)
cases.append({'method': 'morris', 'K': 3, 'trajectories': 5, 'points': 6, 'levels': 8, 'stream': s.used(), 'y': y.tolist(), 'R': 50, 'idx': idx})
mine.append({'u': U, 'mean': mean, 'meanStar': star, 'variance': var, 'count': count, 'ci': ci})

# Morris, SALib's trajectories with the optimal selection
s = Stream(2)
cands = [G.morris_trajectory(4, 4, s) for _ in range(9)]
keep = G.optimal_trajectories(cands, 4)
U = np.vstack([(cands[c] + 0.5) / 4 for c in keep])
y = ishigami(U[:, :3]) + U[:, 3]
mean, star, var, count, _ = G.morris_indices(y, U, 4, 5)
cases.append({'method': 'morrisTraj', 'K': 4, 'trajectories': 4, 'levels': 4, 'candidates': 9, 'stream': s.used(), 'y': y.tolist()})
mine.append({'u': U, 'mean': mean, 'meanStar': star, 'variance': var, 'count': count})

# Sobol: pairs, blocks, every estimator, SALib's bootstrap
for second, blocks, est in ((True, 1, 'jansen1999'), (False, 3, 'sobol2007'), (True, 2, 'homma1996'), (False, 1, 'janon2014')):
    K, n = 3, 64
    draws, parts = {}, []
    for b in range(blocks):
        A, B = rs.random((n, K)), rs.random((n, K))
        for k in range(K):
            draws[f'{k}A{b}'] = A[:, k].tolist()
            draws[f'{k}B{b}'] = B[:, k].tolist()
        parts.append(G.sobol_layout(K, n, A, B, second))
    U = np.vstack(parts)
    y = ishigami(U)
    S1, ST, S2, S1ci, STci, S2ci = G.sobol_indices(y, K, n, second, blocks, est)
    case = {'method': 'sobol', 'K': K, 'n': n, 'second': second, 'blocks': blocks, 'estimator': est, 'draws': draws, 'y': y.tolist()}
    got = {'u': U, 'S1': S1, 'ST': ST, 'S2': S2, 'S1ci': S1ci, 'STci': STci, 'S2ci': S2ci}
    if blocks == 1:
        bidx = rs.integers(0, n, size=(n, 40))
        b1, b2, b3 = G.sobol_bootstrap(y, K, n, second, bidx)
        case.update(boot=bidx.reshape(-1).tolist(), R=40)
        got.update(bS1ci=b1, bSTci=b2, bS2ci=b3)
    cases.append(case)
    mine.append(got)

# eFAST
N = G.efast_samples(101, 4)
phases = (2 * rs.random(3)).tolist()
U, omega = G.efast_design(3, N, 4, phases)
y = ishigami(U)
S1, ST = G.efast_indices(y, 3, N, 4, omega)
cases.append({'method': 'efast', 'K': 3, 'n': 101, 'M': 4, 'phases': phases, 'y': y.tolist()})
mine.append({'N': N, 'u': U, 'S1': S1, 'ST': ST})

# RBD-FAST
s = Stream(3)
perms = [G._perm(200, s) for _ in range(3)]
U, Smat = G.rbdfast_design(3, 200, perms)
y = ishigami(U)
S1 = G.rbdfast_indices(y, Smat, 6)
cases.append({'method': 'rbdfast', 'K': 3, 'N': 200, 'H': 6, 'perms': perms, 'y': y.tolist()})
mine.append({'u': U, 'S1': S1, 'S1c': G.unskew(S1, 6, 200)})

# fractional factorial
U, signs = G.ff_design(5, 0.1, 0.8)
y = ishigami(U[:, :3]) + 3 * U[:, 3] * U[:, 4]
main = signs.T @ y / signs.shape[0]
pairs = [[a, b, float(np.sum(y * signs[:, a] * signs[:, b]) / signs.shape[0])] for b in range(5) for a in range(b)]
cases.append({'method': 'ff', 'K': 5, 'low': 0.1, 'high': 0.8, 'y': y.tolist()})
mine.append({'u': U, 'main': main, 'pairs': pairs})

# DGSM, with the cross terms
base = rs.random((20, 3))
base[0, 1] = 0.9995           # a step back from the top
U, h, per = G.dgsm_design(base, 1e-3, True)
y = ishigami(U)
g, Hm, y0 = G.dgsm_derivatives(y, 20, 3, per, True, h)
a, absa, asq, sigma, tao, bound = G.dgsm_statistics(g, base, y0)
didx = [rs.integers(0, 20, size=(30, 20)).reshape(-1).tolist() for _ in range(3)]
dci = [1.959963984540054 * (g[:, k] ** 2)[np.array(didx[k]).reshape(30, 20)].mean(axis=1).std(ddof=1) for k in range(3)]
cases.append({'method': 'dgsm', 'K': 3, 'base': base.T.tolist(), 'step': 1e-3, 'crossed': True, 'y': y.tolist(), 'R': 30, 'idx': didx})
mine.append({'u': U, 'a': a, 'absa': absa, 'asq': asq, 'sigma': sigma, 'tao': tao, 'bound': bound,
             'crossSq': (Hm * Hm).mean(axis=0), 'sd': (g * g).std(axis=0), 'ci': dci})

# radial
base, step = rs.random((30, 3)), rs.random((30, 3))
U = np.repeat(base, 4, axis=0)
for j in range(30):
    for k in range(3):
        U[j * 4 + 1 + k, k] = step[j, k]
y = ishigami(U)
ridx = rs.integers(0, 30, size=(40, 30))
mu, mstar, sg, mci, ST, sci = G.radial_indices(y, base, step, ridx)
cases.append({'method': 'radial', 'K': 3, 'base': base.T.tolist(), 'step': step.T.tolist(), 'y': y.tolist(), 'R': 40, 'idx': ridx.reshape(-1).tolist()})
mine.append({'u': U, 'mu': mu, 'muStar': mstar, 'sigma': sg, 'muStarCi': mci, 'ST': ST, 'STci': sci})

# Shapley: all orders, independent; random orders, correlated
import itertools  # noqa: E402
for perms_, corr in ((-1, None), (4, np.array([[1, 0.5, 0.2], [0.5, 1, -0.3], [0.2, -0.3, 1.0]]))):
    s = Stream(5)
    orders = [list(p) for p in itertools.permutations(range(3))] if perms_ == -1 else [G._perm(3, s) for _ in range(perms_)]
    U = G.shapley_design(3, orders, 40, 3, 3, corr, s)
    y = ishigami(U)
    eff, se = G.shapley_indices(y, 3, orders, 40, 3, 3)
    cases.append({'method': 'shapley', 'K': 3, 'perms': perms_, 'nVar': 40, 'nOuter': 3, 'nInner': 3,
                  'corr': None if corr is None else corr.reshape(-1).tolist(), 'stream': s.used(), 'y': y.tolist()})
    mine.append({'u': U, 'orders': orders, 'effects': eff, 'stdErr': se})

node = shutil.which('node')
if C('node runs Kompartment\'s functions', node is not None, 'node not found'):
    path = os.path.join(TMP, 'cases.json')
    with open(path, 'w') as f:
        json.dump(cases, f)
    res = json.loads(subprocess.run([node, os.path.join(HERE, 'gsa-kompartment.mjs'), path], capture_output=True, text=True, check=True).stdout)
    for c, theirs, ours in zip(cases, res, mine):
        label = c['method'] + (f" ({c.get('estimator')}, {'pairs, ' if c.get('second') else ''}{c.get('blocks')} block)" if c['method'] == 'sobol' else '')
        for key, val in ours.items():
            t = theirs.get(key)
            if key == 'u':
                near(f'{label}: the design', np.asarray(val).reshape(-1), t, 1e-15)
            elif key == 'orders':
                C(f'{label}: the orders', val == t, (val, t))
            elif key == 'pairs':
                near(f'{label}: interactions', [p[2] for p in val], [p[2] for p in t], 1e-12)
            elif key == 'N':
                C(f'{label}: runs per curve', val == t, (val, t))
            elif val is None:
                C(f'{label}: {key} absent', t is None, t)
            else:
                w = np.asarray(val, float)
                if key in ('S2', 'S2ci', 'bS2ci'):
                    K = w.shape[0]
                    w = np.where(np.isnan(w), 0 if key == 'S2' else np.nan, w)
                    tt = np.asarray([np.nan if x is None else x for x in t], float).reshape(K, K)
                    iu = np.triu_indices(K, 1)
                    near(f'{label}: {key}', w[iu], tt[iu], 1e-9, 1e-9)
                    continue
                near(f'{label}: {key}', w, [np.nan if x is None else x for x in t], 1e-9, 1e-9)

# ---- in the language: known answers ----------------------------------------------------------------------
W, o = run("""rng(3); a = [2 -1 0.5];
f = @(X) X * a';
[X, D] = morrisdesign(3, 'Trajectories', 6); T = morrisindices(D, f(X)); ms = T.MuStar; mu = T.Mu; sg = T.Sigma; cnt = sum(T.Count);
[X, D] = morrisdesign(3, 'Design', 'trajectories', 'Levels', 4, 'Trajectories', 5, 'Candidates', 12); T2 = morrisindices(D, f(X)); ms2 = T2.MuStar; rows2 = size(X, 1);
[X, D] = ffdesign(3); T3 = ffindices(D, f(X)); main = T3.Main;
[X, D] = dgsmdesign(50, 3); T4 = dgsmindices(D, f(X)); nu = T4.Nu; dm = T4.Mean;
[X, D] = radialdesign(40, 3); T5 = radialindices(D, f(X)); rmu = T5.Mu;
U = rand(500, 3); [s, r2] = src(U, f(U)); p = pcc(U, f(U) + 0.01*randn(500, 1));
[sr, r2r] = srrc(U, f(U));
""")
near('Morris: the elementary effects of a linear model are its coefficients', (W['ms'], W['mu']), [2, 1, 0.5, 2, -1, 0.5], 1e-9)
near('... with no spread', W['sg'], [0, 0, 0], 1e-9)
near('... one effect a step', W['cnt'], 6 * 9)
near("Morris's trajectories: the same, K + 1 runs each", (W['ms2'], W['rows2']), [2, 1, 0.5, 20], 1e-9)
near('fractional factorial: the main effect is the coefficient times half the spread of the levels', W['main'], np.array([2, -1, 0.5]) * 0.45, 1e-12)
near('DGSM: the derivative is the coefficient, nu its square', (W['dm'], W['nu']), [2, -1, 0.5, 4, 1, 0.25], 1e-6)
near('radial: the effects are the coefficients', W['rmu'], [2, -1, 0.5], 1e-9)
sw = np.array([2, -1, 0.5]) / np.sqrt(np.array([2, -1, 0.5]) ** 2 @ np.ones(3))
C('src: R² of an exact linear model is one, the coefficients its standardized ones', abs(W['r2'] - 1) < 1e-12 and np.allclose(v(W['s']), sw, atol=0.05), (W['s'], W['r2']))
C('pcc: near one in magnitude for a nearly exact model, with the signs', np.all(np.abs(v(W['p'])) > 0.99) and np.array_equal(np.sign(v(W['p'])), [1, -1, 1]), W['p'])
C('srrc: ranks of a linear model, R² near one', W['r2r'] > 0.95 and np.array_equal(np.sign(v(W['sr'])), [1, -1, 1]), (W['sr'], W['r2r']))

W, o = run("""rng(5); ishi = @(X) sin(X(:,1)) + 7*sin(X(:,2)).^2 + 0.1*X(:,3).^4.*sin(X(:,1)); tox = @(U) -pi + 2*pi*U;
[X, D] = soboldesign(8192, 3, 'Sampling', 'sobol'); [T, S2] = sobolindices(D, ishi(tox(X)), 'Resamples', 0); s1 = T.S1; st = T.ST; w = width(T);
[X, D] = soboldesign(4096, 3, 'Second', true); [T2, S2b, S2c] = sobolindices(D, ishi(tox(X)), 'Resamples', 20); s13 = S2b(1, 3); s2conf = S2c(1, 3); w2 = width(T2);
[X, D] = efastdesign(2000, 3); T3 = efastindices(D, ishi(tox(X))); e1 = T3.S1; et = T3.ST; eruns = D.Runs; eN = D.N;
[X, D] = rbdfastdesign(4000, 3); T4 = rbdfastindices(D, ishi(tox(X))); r1 = T4.S1Corrected;
[X, D] = shapleydesign(3, 'NVar', 4000, 'NOuter', 30); T5 = shapleyindices(D, ishi(tox(X))); sh = T5.Shapley;
U = lhsdesign(4000, 3); Y = ishi(tox(U)); [c1, ~] = easi(U, Y); f1 = firstorderindex(U, Y);
""")
s1w, stw = [0.3139, 0.4424, 0.0], [0.5576, 0.4424, 0.2437]
near("Sobol on Ishigami's function (Sobol sequence, 8192 runs a sample): S1", W['s1'], s1w, 0.02)
near('... ST', W['st'], stw, 0.02)
C('... resamples 0: no interval columns', W['w'] == 2, W['w'])
C("Sobol's pairs: x1 and x3 interact (S13 about 0.24), with an interval", abs(W['s13'] - 0.2437) < 0.1 and W['s2conf'] > 0 and W['w2'] == 4, (W['s13'], W['s2conf']))
near('eFAST: S1', W['e1'], s1w, 0.03)
near('... ST', W['et'], stw, 0.04)
C('... N raised to fit the harmonics, K curves', W['eN'] >= 2000 and W['eruns'] == 3 * W['eN'], (W['eN'], W['eruns']))
near('RBD-FAST (corrected): S1', W['r1'], s1w, 0.03)
C('Shapley effects add up to one', abs(float(np.sum(v(W['sh']))) - 1) < 1e-9 and np.all(v(W['sh']) > 0), W['sh'])
near('EASI on a Latin hypercube: S1', W['c1'], s1w, 0.03)
near('S1 by binning', W['f1'], s1w, 0.04)

# ---- sampling -------------------------------------------------------------------------------------------
W, o = run("""rng(1); X = lhsdesign(20, 4); strata = all(all(sort(ceil(X*20)) == repmat((1:20)', 1, 4)));
M = lhsdesign(10, 2, 'smooth', 'off'); mids = all(all(sort(M) == repmat(((1:10)' - 0.5)/10, 1, 2)));
C = lhsdesign(50, 3, 'criterion', 'correlation', 'iterations', 20); cc = max(max(abs(triu(corrcoef(C), 1))));
N = lhsdesign(40, 3, 'criterion', 'none');
[Z, Z0] = lhsnorm([1 2], [1 0.6; 0.6 2], 1000); m = mean(Z); r = corrcoef(Z); pz = normcdf(Z(:,1), 1, 1); zs = all(sort(ceil(pz*1000)) == (1:1000)');
p = sobolset(2); P = net(p, 4); q = p(5:6, :);
h = haltonset(2); H = net(h, 4);
ps = sobolset(3, 'Skip', 1, 'Leap', 1); PS = net(ps, 2);
sp = scramble(sobolset(2)); SP = net(sp, 256); spread = all(all(sort(ceil(SP*256)) == repmat((1:256)', 1, 2)));
nd = p.Dimensions; k = class(p);
""")
C('lhsdesign: one point in each of the 20 slices of every column', W['strata'] is True, W['strata'])
C("'smooth', 'off': the slices' middles", W['mids'] is True, W['mids'])
C("'correlation': the columns nearly uncorrelated", W['cc'] < 0.15, W['cc'])
C('lhsnorm: one point in each slice of probability', W['zs'] is True, W['zs'])
near('... the mean', W['m'], [1, 2], 0.05)
near('... the correlation kept', np.asarray(W['r'])[0, 1], 0.6 / math.sqrt(2), 0.05)
near("sobolset: the sequence's first points", W['P'], np.array([[0, 0], [0.5, 0.5], [0.75, 0.25], [0.25, 0.75]]), 1e-15)
near('... indexing reads further on', W['q'], np.array([[0.375, 0.375], [0.875, 0.875]]), 1e-15)
near("haltonset: bases 2 and 3", W['H'], np.array([[0, 0], [0.5, 1 / 3], [0.25, 2 / 3], [0.75, 1 / 9]]), 1e-15)
near("'Skip' and 'Leap'", W['PS'], np.array([[0.5, 0.5, 0.5], [0.25, 0.75, 0.75]]), 1e-15)
C('scramble: a scrambled Sobol net of 256 points is still one in each slice', W['spread'] is True, W['spread'])
C('Dimensions and class', W['nd'] == 2 and W['k'].str() == 'sobolset', (W['nd'], W['k']))

# ---- the sample-based measures --------------------------------------------------------------------------
W, o = run("""rng(2); U = rand(600, 3); Y = 4*U(:,1) + U(:,2).^2 + 0*U(:,3);
D = deltamoment(U, Y, 'Resamples', 10); d = D.Adjusted;
M = mutualinfo(U, Y, 'Shuffles', 30); ab = M.Above;
P = pawn(U, Y); pm = P.Median;
q = discrepancyshares(U(1:200,:), Y(1:200)); qs = sum(q);
[R, ch] = rsa(U, Y); ks = R.KS;
Rn = rsa(U, Y, 3, 'Names', {'a', 'b', 'c'}); rn = Rn.Properties.RowNames;
""")
C('δ: the input the output follows most is first, the unused one least', np.argmax(v(W['d'])) == 0 and np.argmin(v(W['d'])) == 2, W['d'])
C('mutual information above chance: the unused input has none', v(W['ab'])[0] > 0.5 and v(W['ab'])[2] < 0.1, W['ab'])
C('PAWN: largest for the input that drives the output', np.argmax(v(W['pm'])) == 0 and np.argmin(v(W['pm'])) == 2, W['pm'])
near('discrepancy shares add up to one', W['qs'], 1, 1e-12)
C('rsa: the KS distance largest for the driving input, the unused one near chance', np.argmax(v(W['ks'])) == 0 and v(W['ks'])[2] < v(W['ch'])[0] + 4 * v(W['ch'])[1], (W['ks'], W['ch']))
C("'Names' name the rows", [x.str() for x in W['rn'].a.reshape(-1)] == ['a', 'b', 'c'], W['rn'])

for code, words in [("[X, D] = soboldesign(10, 2); sobolindices(D, rand(5, 1))", 'runs'),
                    ("[X, D] = soboldesign(10, 2); efastindices(D, rand(40, 1))", "efastdesign"),
                    ("[X, D] = morrisdesign(2); y = ones(size(X,1),1); y(3) = NaN; morrisindices(D, y)", 'finite'),
                    ("lhsdesign(10)", 'not enough input'),
                    ("src(rand(10, 2), rand(9, 1))", 'one value per row'),
                    ("rsa(rand(10, 2), (1:10)', 20)", 'one side'),
                    ("shapleydesign(3, 'Correlation', eye(2))", 'K-by-K'),
                    ("soboldesign(100, 3, 'Sampling', 'grid')", 'Sampling'),
                    ("morrisdesign(3, 'Levels', 1)", 'at least 2'),
                    ("p = sobolset(2); p(:, 1)", 'no end')]:
    m = err_of(code)
    C(f'error: {code}', words.lower() in m.lower(), m)

W, o = run("[X, D] = soboldesign(4, {'k', 'theta'}); T = sobolindices(D, X(:,1) + 2*X(:,2)); rn = T.Properties.RowNames; n = D.Names; r = D.Runs;")
C('input names given in place of their number name the rows', [x.str() for x in W['rn'].a.reshape(-1)] == ['k', 'theta'] and W['r'] == 16, (W['rn'], W['r']))

sys.exit(C.done())
