"""Fuzzy logic, run natively (CPython with numpy): the membership functions
against their formulas written out here; Mamdani and Sugeno evaluation
against inference written out here (min, product, max, sum, probabilistic
or; centroid, bisector and the maxima); rules from text, symbols and
matrices; changes to systems as values; .fis files there and back.

    python3 test_fuzzy.py          (from any folder)
"""
import asyncio
import math
import os
import shutil
import sys
import tempfile
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()
warnings.filterwarnings('ignore')
TMP = tempfile.mkdtemp(prefix='plab-fuzzy-')


def run(code):
    R.BASE.clear()
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


def a(x):
    if isinstance(x, tuple):
        return np.concatenate([np.asarray(v, float).reshape(-1) for v in x])
    return np.asarray(x, float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if np.size(w) < 30 else np.shape(w)}')


def text(v):
    if isinstance(v, Char):
        return v.str()
    if hasattr(v, 'a') and getattr(v, 'a').size == 1:
        return str(v.a.reshape(-1)[0])
    return str(v)


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = text(W['e'])
    return C(f'refused: {code}', words in msg, msg)


# ---- membership functions -----------------------------------------------------------------------------------------------------

x = np.linspace(-2, 12, 141)
sig = lambda v, a_, c: 1 / (1 + np.exp(-a_ * (v - c)))


def smf(v, a_, b):
    m = (a_ + b) / 2
    return np.where(v <= a_, 0, np.where(v <= m, 2 * ((v - a_) / (b - a_)) ** 2, np.where(v < b, 1 - 2 * ((v - b) / (b - a_)) ** 2, 1)))


ref = {
    'trimf': ([1, 4, 8], np.clip(np.minimum((x - 1) / 3, (8 - x) / 4), 0, 1)),
    'trapmf': ([0, 2, 5, 9], np.clip(np.minimum(np.minimum((x - 0) / 2, 1), (9 - x) / 4), 0, 1)),
    'gaussmf': ([1.5, 4], np.exp(-(x - 4) ** 2 / (2 * 1.5 ** 2))),
    'gauss2mf': ([1, 3, 2, 6], np.where(x < 3, np.exp(-(x - 3) ** 2 / 2), 1) * np.where(x > 6, np.exp(-(x - 6) ** 2 / 8), 1)),
    'gbellmf': ([2, 3, 5], 1 / (1 + np.abs((x - 5) / 2) ** 6)),
    'sigmf': ([2, 4], sig(x, 2, 4)),
    'dsigmf': ([5, 2, 5, 7], np.abs(sig(x, 5, 2) - sig(x, 5, 7))),
    'psigmf': ([2, 3, -5, 8], sig(x, 2, 3) * sig(x, -5, 8)),
    'smf': ([1, 8], smf(x, 1, 8)),
    'zmf': ([1, 8], 1 - smf(x, 1, 8)),
    'pimf': ([1, 4, 5, 10], smf(x, 1, 4) * (1 - smf(x, 5, 10))),
    'linsmf': ([2, 6], np.clip((x - 2) / 4, 0, 1)),
    'linzmf': ([2, 6], np.clip((6 - x) / 4, 0, 1)),
}
code = f"x = {x.tolist()};" + ''.join(f"y_{k} = {k}(x, {p}); e_{k} = evalmf(x, {p}, '{k}');" for k, (p, _) in ref.items())
W, _ = run(code)
for k, (p, want) in ref.items():
    near(f'{k}: the formula, and evalmf alike', (W[f'y_{k}'], W[f'e_{k}']), (want.reshape(1, -1), want.reshape(1, -1)), 1e-12)
W, _ = run("y = trimf([0 1 2 3], [1 1 3]); z = trapmf([0 1 2 3 4], [1 1 3 3]);")
near('trimf and trapmf with vertical sides', (W['y'], W['z']), ([[0, 1, 0.5, 0]], [[0, 1, 1, 1, 0]]))

# ---- Mamdani ---------------------------------------------------------------------------------------------------------------------

BUILD = """fis = mamfis('Name', 'tip');
fis = addInput(fis, [0 10], 'Name', 'service');
fis = addMF(fis, 'service', 'gaussmf', [1.5 0], 'Name', 'poor');
fis = addMF(fis, 'service', 'gaussmf', [1.5 5], 'Name', 'good');
fis = addMF(fis, 'service', 'gaussmf', [1.5 10], 'Name', 'excellent');
fis = addInput(fis, [0 10], 'Name', 'food');
fis = addMF(fis, 'food', 'trapmf', [-2 0 1 3], 'Name', 'rancid');
fis = addMF(fis, 'food', 'trapmf', [7 9 10 12], 'Name', 'delicious');
fis = addOutput(fis, [0 30], 'Name', 'tip');
fis = addMF(fis, 'tip', 'trimf', [0 5 10], 'Name', 'cheap');
fis = addMF(fis, 'tip', 'trimf', [10 15 20], 'Name', 'average');
fis = addMF(fis, 'tip', 'trimf', [20 25 30], 'Name', 'generous');
fis = addRule(fis, ["If service is poor or food is rancid then tip is cheap"; "If service is good then tip is average (0.8)"; "If service is excellent and food is not rancid then tip is generous"]);
"""
g = lambda v, s, c: math.exp(-(v - c) ** 2 / (2 * s * s))
tr = lambda v, a_, b, c, d: max(0.0, min((v - a_) / (b - a_), 1.0, (d - v) / (d - c)))
ys = np.linspace(0, 30, 101)
tri = lambda v, a_, b, c: np.clip(np.minimum((v - a_) / (b - a_), (c - v) / (c - b)), 0, 1)


def mamdani(sv, fd, imp='min', agg='max', andm='min', orm='max', defz='centroid', npts=101):
    yy = np.linspace(0, 30, npts)
    poor, good, exc = g(sv, 1.5, 0), g(sv, 1.5, 5), g(sv, 1.5, 10)
    ran = tr(fd, -2, 0, 1, 3)
    w1 = max(poor, ran) if orm == 'max' else poor + ran - poor * ran
    w2 = 0.8 * good
    w3 = min(exc, 1 - ran) if andm == 'min' else exc * (1 - ran)
    outs = [tri(yy, 0, 5, 10), tri(yy, 10, 15, 20), tri(yy, 20, 25, 30)]
    clip = [np.minimum(o, w) if imp == 'min' else o * w for o, w in zip(outs, (w1, w2, w3))]
    if agg == 'max':
        A = np.maximum.reduce(clip)
    elif agg == 'sum':
        A = sum(clip)
    else:
        A = clip[0]
        for c in clip[1:]:
            A = A + c - A * c
    if defz == 'centroid':
        return yy @ A / A.sum(), (w1, w2, w3)
    if defz == 'bisector':
        return yy[np.searchsorted(np.cumsum(A), A.sum() / 2)], (w1, w2, w3)
    at = yy[np.isclose(A, A.max(), rtol=0, atol=1e-12)]
    return {'mom': at.mean(), 'lom': at[np.argmax(np.abs(at))], 'som': at[np.argmin(np.abs(at))]}[defz], (w1, w2, w3)


W, out = run(BUILD + "t = evalfis(fis, [3 8; 7 2; 9.5 9]); [t1, fz, ro, ag, rf] = evalfis(fis, [3 8]); fis")
near('evalfis Mamdani: min, max, clipping, centroid on 101 points (written out here)', W['t'], [[mamdani(3, 8)[0]], [mamdani(7, 2)[0]], [mamdani(9.5, 9)[0]]], 1e-12)
near('evalfis: each rule\'s firing strength, its weight included', W['rf'], np.array(mamdani(3, 8)[1]).reshape(-1, 1), 1e-12)
C('evalfis: fuzzified inputs (rules by inputs), rule outputs and the aggregate on the output points', a(W['fz']).shape == (3, 2) and a(W['ro']).shape == (101, 3) and a(W['ag']).shape == (101, 1))
C('a system shows its rules', 'If service is good then tip is average (0.8)' in out and 'If service is excellent and food is not rancid then tip is generous (1)' in out)
for opts, kw in (("fis.ImplicationMethod = 'prod'; fis.AggregationMethod = 'sum';", dict(imp='prod', agg='sum')),
                 ("fis.AndMethod = 'prod'; fis.OrMethod = 'probor'; fis.AggregationMethod = 'probor';", dict(andm='prod', orm='probor', agg='probor')),
                 ("fis.DefuzzificationMethod = 'bisector';", dict(defz='bisector')), ("fis.DefuzzificationMethod = 'mom';", dict(defz='mom')),
                 ("fis.DefuzzificationMethod = 'lom';", dict(defz='lom')), ("fis.DefuzzificationMethod = 'som';", dict(defz='som'))):
    W, _ = run(BUILD + opts + "t = evalfis(fis, [6 4]);")
    near(f'evalfis Mamdani with {", ".join(f"{k} {v}" for k, v in kw.items())}', W['t'], mamdani(6, 4, **kw)[0], 1e-12)
W, _ = run(BUILD + "t = evalfis(fis, [3 8], evalfisOptions('NumSamplePoints', 501)); t2 = evalfis([3 8], fis);")
near('evalfisOptions: more points; the older argument order', (W['t'], W['t2']), (mamdani(3, 8, npts=501)[0], mamdani(3, 8)[0]), 1e-12)
W, out = run(BUILD + "t = evalfis(fis, [-5 20]); t0 = evalfis(fis, [0 10]);")
near('evalfis: inputs outside the ranges held at their ends, with a warning', W['t'], W['t0'], 1e-12)
C('evalfis: the out-of-range warning', 'outside its range' in out)
W, out = run("f = mamfis; f = addInput(f, [0 1], 'Name', 'x'); f = addMF(f, 'x', 'trimf', [0 0 0.2], 'Name', 'lo'); f = addOutput(f, [0 10], 'Name', 'y');"
             "f = addMF(f, 'y', 'trimf', [0 1 2], 'Name', 'a'); f = addRule(f, 'If x is lo then y is a'); t = evalfis(f, 0.9);")
C('evalfis: no rule firing gives the middle of the output range, with a warning', W['t'] == 5.0 and 'No rule fired' in out)

# ---- Sugeno -----------------------------------------------------------------------------------------------------------------------

S = """s = sugfis('Name', 'lin'); s = addInput(s, [0 1], 'Name', 'x'); s = addMF(s, 'x', 'trimf', [-1 0 1], 'Name', 'lo'); s = addMF(s, 'x', 'trimf', [0 1 2], 'Name', 'hi');
s = addInput(s, [0 2], 'Name', 'z'); s = addMF(s, 'z', 'gaussmf', [0.5 0], 'Name', 'small'); s = addMF(s, 'z', 'gaussmf', [0.5 2], 'Name', 'big');
s = addOutput(s, [0 5], 'Name', 'y'); s = addMF(s, 'y', 'constant', 1, 'Name', 'one'); s = addMF(s, 'y', 'linear', [2 -1 3], 'Name', 'plane');
s = addRule(s, [1 1 1 1 1; 2 2 2 0.5 2]);
"""
W, _ = run(S + "y = evalfis(s, [0.3 0.5; 0.8 1.6]); s.DefuzzificationMethod = 'wtsum'; ys = evalfis(s, [0.3 0.5]);")


def sugeno(xv, zv, wtsum=False):
    lo, hi = max(0, 1 - xv), max(0, xv)
    sm, bg = g(zv, 0.5, 0), g(zv, 0.5, 2)
    w1 = lo * sm                      # sugfis: AndMethod prod
    w2 = 0.5 * (hi + bg - hi * bg)     # OrMethod probor, weight 0.5
    z1, z2 = 1.0, 2 * xv - zv + 3
    return (w1 * z1 + w2 * z2) if wtsum else (w1 * z1 + w2 * z2) / (w1 + w2)


near('evalfis Sugeno: product and probabilistic or, constant and linear outputs, the weighted average', W['y'], [[sugeno(0.3, 0.5)], [sugeno(0.8, 1.6)]], 1e-12)
near("evalfis Sugeno 'wtsum'", W['ys'], sugeno(0.3, 0.5, True), 1e-12)

# ---- rules, changes, files ---------------------------------------------------------------------------------------------------------

W, out = run(BUILD + "f2 = addRule(fis, 'service==good & food~=delicious => tip=average (0.5)'); r = f2.Rules(4); an = r.Antecedent; co = r.Consequent; w = r.Weight; cn = r.Connection;"
             "n0 = numel(fis.Rules); n2 = numel(f2.Rules); showrule(f2, 4, 'indexed'); s = showrule(f2, [1 4]);")
near('addRule symbolic: indices, not as negative, the weight and the connection', (W['an'], W['co'], W['w'], W['cn']), ([[2, -2]], [[2]], 0.5, 1))
C('addRule gives a new system (the old one unchanged); showrule formats', W['n0'] == 3.0 and W['n2'] == 4.0 and '2 -2, 2 (0.5) : 1' in out and
  text(W['s'].a[1, 0]).startswith('4. If service is good and food is not delicious then tip is average (0.5)'))
W, _ = run(BUILD + "f2 = fis; f2.Inputs(1).MembershipFunctions(2).Parameters = [2 5]; p1 = fis.Inputs(1).MembershipFunctions(2).Parameters; p2 = f2.Inputs(1).MembershipFunctions(2).Parameters;"
           "f2.Inputs(2).Name = 'meal'; nm = f2.Inputs(2).Name; f2.Rules(2).Weight = 0.3; w = f2.Rules(2).Weight; t = evalfis(f2, [3 8]);")
near('nested assignment changes the copy only', (W['p1'], W['p2'], W['w']), ([[1.5, 5]], [[2, 5]], 0.3))
C('nested assignment: a variable renamed', text(W['nm']) == 'meal')
W, _ = run(BUILD + "f = removeMF(fis, 'food', 'rancid'); a1 = f.Rules(1).Antecedent; a3 = f.Rules(3).Antecedent; f = removeInput(fis, 'food'); n = numel(f.Inputs); a = f.Rules(1).Antecedent;")
near('removeMF: the rules that used it lose the clause; removeInput: its column', (W['a1'], W['a3'], W['n'], W['a']), ([[1, 0]], [[3, 0]], 1, [[1]]))
W, _ = run(BUILD + "writefis(fis, 'tipper'); f = readfis('tipper.fis'); t = evalfis(fis, [3 8; 6 4]); t2 = evalfis(f, [3 8; 6 4]); s = fileread('tipper.fis');")
near('writefis and readfis: the same system back', W['t2'], W['t'], 1e-12)
ftxt = text(W['s'])
C('the .fis file: sections, membership functions and rules', "[System]" in ftxt and "Type='mamdani'" in ftxt and "MF1='poor':'gaussmf',[1.5 0]" in ftxt and '3 -1, 3 (1) : 1' in ftxt)
W, _ = run("f = mamfis('NumInputs', 2, 'NumInputMFs', 3, 'NumOutputs', 1, 'NumOutputMFs', 3); n = numel(f.Rules); p = f.Inputs(1).MembershipFunctions(2).Parameters;"
           "g = newfis('old'); g = addvar(g, 'input', 'x', [0 10]); g = addmf(g, 'input', 1, 'lo', 'trimf', [0 0 10]); g = addvar(g, 'output', 'y', [0 1]);"
           "g = addmf(g, 'output', 1, 'up', 'trimf', [0 1 1]); g = addrule(g, [1 1 1 1]); y = evalfis(g, 5);")
near("mamfis 'AddRules' 'allcombinations': 9 rules; default triangles over [0 1]", (W['n'], W['p']), (9, [[0, 0.5, 1]]))
yy = np.linspace(0, 1, 101)
A = np.minimum(np.clip(yy, 0, 1), 0.5)
near('newfis, addvar, addmf and addrule (the older functions) evaluate', W['y'], yy @ A / A.sum(), 1e-12)
W, _ = run(BUILD + "[X, Y, Z] = gensurf(fis, [1 2], 1, 5); z = evalfis(fis, [X(2,3) Y(2,3)]); [xm, ym] = plotmf(fis, 'input', 1, 11); figure; gensurf(fis); figure; plotmf(fis, 'output', 1);"
           "dz = defuzz(0:10, [0 0 1 1 1 0 0 0 0 0 0], 'centroid'); dm = defuzz(-5:5, [0 1 1 0 0 0 0 0 1 1 0], 'som');")
near('gensurf: evalfis over the grid', a(W['Z'])[1, 2], W['z'], 1e-12)
near('plotmf: the membership values', a(W['ym'])[:, 1], np.exp(-(np.linspace(0, 10, 11) - 5) ** 2 / (2 * 1.5 ** 2)), 1e-12)
near("defuzz: centroid; 'som' the smallest maximizer by magnitude", (W['dz'], W['dm']), (3.0, -3.0))

# ---- refusals -------------------------------------------------------------------------------------------------------------------

raises(BUILD + "addRule(fis, 'If service is awful then tip is cheap')", "no membership function 'awful'")
raises(BUILD + "addRule(fis, 'If speed is poor then tip is cheap')", "no input named 'speed'")
raises(BUILD + "addRule(fis, 'If service is poor and food is rancid or food is delicious then tip is cheap')", 'all by and or all by or')
raises(BUILD + "addMF(fis, 'tip', 'trimf', [1 2])", 'trimf takes 3 parameters')
raises("s = sugfis; s = addOutput(s, [0 1]); addMF(s, 'output1', 'trimf', [0 1 2])", "'constant' or 'linear'")
raises(BUILD + "fis.DefuzzificationMethod = 'wtaver'", 'DefuzzificationMethod is')
raises(BUILD + "evalfis(fis, [1 2 3])", 'a column for each of the 2 inputs')
raises("evalfis(mamfis, 1)", 'has no rules')
raises("trimf(1:3, [1 2])", 'trimf takes 3 parameters')
raises("readfis('nothere.fis')", 'Unable to find')

shutil.rmtree(TMP, ignore_errors=True)
sys.exit(C.done())
