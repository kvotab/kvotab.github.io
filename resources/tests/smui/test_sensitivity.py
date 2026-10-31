#!/usr/bin/env python3
"""Analyze > Screening > Sensitivity Analysis, the backend
(resources/py/smui/sensitivity.py), through the page's dispatch and JSON
round trip, checked against:

  - Kompartment's own functions (kompartment/src/domain sensitivity.js,
    gsa.js and salib.js, which its tests check against GlobalSensitivity.jl
    and SALib), run by node on the same samples with the same random draws
    (sensitivity-kompartment.mjs): every measure, on samples with log-scaled
    and normal inputs, ties, a constant input, an output over decades, an
    odd number of rows and few of them;
  - statsmodels' OLS for SRC, PCC, SRRC, PRCC and the R²s (the partial
    correlations from the residuals); scipy's pearsonr, spearmanr and
    ks_2samp; SALib's PAWN and discrepancy (skipped without SALib);
  - known answers: a linear model's first-order indices, and the Ishigami
    function's (0.3139, 0.4424, 0), which no correlation sees for x2;
  - the code under each result, run on a CSV export of its table.

    python3 resources/tests/smui/test_sensitivity.py
"""
import contextlib
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import warnings

import numpy as np
import pandas as pd
from scipy import stats

from backend import FAILED, Checks, call, table

check = Checks()
if 'sensitivity' in FAILED:
    print('sensitivity did not import:', FAILED['sensitivity'])
    sys.exit(1)
from smui import sensitivity as G  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
KOMPARTMENT = os.path.join(HERE, 'sensitivity-kompartment.mjs')
rng = np.random.default_rng(20261031)


def close(a, b, rel=1e-9, abs_=1e-12):
    """Numbers (or sequences, None or NaN for missing) equal within rel."""
    a = np.asarray([np.nan if v is None else v for v in np.atleast_1d(a)], dtype=float)
    b = np.asarray([np.nan if v is None else v for v in np.atleast_1d(b)], dtype=float)
    if a.shape != b.shape:
        return False
    both = np.isnan(a) & np.isnan(b)
    return bool(np.all(both | (np.abs(a - b) <= np.maximum(abs_, rel * np.maximum(np.abs(a), np.abs(b))))))


def kompartment(X, y, resamples, shuffles, threshold=None):
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as f:
        json.dump({'X': X.T.tolist(), 'y': list(map(float, y)), 'resamples': resamples.tolist(), 'shuffles': [s.tolist() for s in shuffles],
                   'slides': 10, 'threshold': threshold}, f)
    try:
        out = subprocess.run(['node', KOMPARTMENT, f.name], capture_output=True, text=True, timeout=600)
    finally:
        os.unlink(f.name)
    if out.returncode:
        raise RuntimeError(out.stderr[-2000:])
    return json.loads(out.stdout)


# ---- the port against Kompartment's functions ------------------------------------
def against_kompartment():
    n = 500
    U = rng.uniform(-np.pi, np.pi, size=(n, 3))
    kd = 10 ** rng.uniform(-4, -1, n)
    z = rng.normal(size=n)
    ishigami = np.sin(U[:, 0]) + 7 * np.sin(U[:, 1]) ** 2 + 0.1 * U[:, 2] ** 4 * np.sin(U[:, 0])
    samples = {
        'Ishigami and a log-scaled input': (np.column_stack([U, kd, z]), ishigami + 2 * np.log10(kd)),
        'a dose over decades': (np.column_stack([kd, 10 ** rng.uniform(-1, 1, n), z]), 1e-4 * 10 ** rng.uniform(-1, 1, n) / (1 + 1e3 * kd) * np.exp(0.3 * z)),
        'ties: an input of five values': (np.column_stack([rng.integers(0, 5, n).astype(float), z]), rng.integers(0, 5, n) + z + rng.normal(size=n)),
        'a constant input': (np.column_stack([np.full(n, 3.0), U[:, 0]]), np.sin(U[:, 0]) + 0.1 * z),
        'an odd number of rows (101)': (np.column_stack([U[:101, 0], U[:101, 1]]), ishigami[:101]),
        'few rows (25)': (np.column_stack([U[:25, 0], z[:25]]), U[:25, 0] + z[:25]),
    }
    for label, (X, y) in samples.items():
        m = len(y)
        res = rng.integers(0, m, size=(30, m))
        shf = [rng.permutation(m) for _ in range(30)]
        ref = kompartment(X, y, res, shf)
        src, pcc, r2 = G.regression_measures(X, y)
        srrc, prcc, r2r = G.regression_measures(stats.rankdata(X, axis=0), stats.rankdata(y))
        scores = stats.norm.ppf((stats.rankdata(y) - 0.5) / m)
        ry = stats.rankdata(y)
        varying = [k for k in range(X.shape[1]) if np.ptp(X[:, k]) > 0]
        shares = np.full(X.shape[1], np.nan)
        shares[varying] = G.discrepancy_shares(X[:, varying], y)
        K = range(X.shape[1])
        R = ref['inputs']
        check(f'{label}: R² and R² on ranks as Kompartment\'s', close([ref['r2'], ref['r2_rank']], [r2, r2r]), True)
        check(f'{label}: SRC, PCC, SRRC, PRCC as Kompartment\'s', close([[r[k] for k in ('src', 'pcc', 'srrc', 'prcc')] for r in R], np.column_stack([src, pcc, srrc, prcc])), True)
        live = [k for k in K if k in varying]
        check(f'{label}: Pearson and Spearman as Kompartment\'s', close([[R[k]['pearson'], R[k]['spearman']] for k in live],
                                                                         [[stats.pearsonr(X[:, k], y)[0], stats.spearmanr(X[:, k], y)[0]] for k in live]), True)
        check(f'{label}: S1 by binning as Kompartment\'s', close([R[k]['s1'] for k in K], [G.first_order_index(X[:, k], y) for k in K]), True)
        check(f'{label}: EASI and its correction as Kompartment\'s', close([[R[k]['easi'], R[k]['easi_c']] for k in live], [G.easi(X[:, k], y) for k in live]), True)
        check(f'{label}: δ, adjusted, and its interval (the same resamples) as Kompartment\'s',
              close([[R[k][f] for f in ('delta', 'delta_adjusted', 'delta_low', 'delta_high')] for k in live], [G.delta_moment(X[:, k], scores, resamples=res) for k in live], rel=1e-8), True)
        check(f'{label}: mutual information, its chance level (the same shuffles), above it, as Kompartment\'s',
              close([[R[k][f] for f in ('mi', 'mi_bound', 'mi_above')] for k in live], [G.mutual_information(stats.rankdata(X[:, k]), ry, shuffles=shf) for k in live], rel=1e-8), True)
        check(f'{label}: PAWN\'s statistics over the slices as Kompartment\'s', close([[R[k]['pawn'][f] for f in ('minimum', 'mean', 'median', 'maximum', 'stdev', 'cv')] for k in live],
                                                                                      [[G.pawn(X[:, k], y)[f] for f in ('minimum', 'mean', 'median', 'maximum', 'stdev', 'cv')] for k in live]), True)
        check(f'{label}: the discrepancy shares as Kompartment\'s', close([R[k]['discrepancy'] for k in live], shares[live], rel=1e-8), True)
        above = y > y.mean()
        cont = [k for k in live if len(np.unique(X[:, k])) == m]
        check(f'{label}: the regional KS distance (scipy\'s) as Kompartment\'s, inputs without ties', close([R[k]['ks'] for k in cont], [stats.ks_2samp(X[above, k], X[~above, k]).statistic for k in cont]), True)
        check(f'{label}: δ\'s classes as Kompartment\'s', G.delta_classes(m), ref['delta_classes'])
    # ties: scipy's distance is the right one; Kompartment's reads inside a run of ties too
    X, y = samples['ties: an input of five values']
    above = y > y.mean()
    ref = kompartment(X, y, np.zeros((0, len(y)), dtype=int), [])
    check('ties: scipy\'s KS distance is at most Kompartment\'s (which reads inside a run of ties)', stats.ks_2samp(X[above, 0], X[~above, 0]).statistic <= ref['inputs'][0]['ks'] + 1e-12, True)


# ---- independent references ------------------------------------------------------------
def references():
    import statsmodels.api as sm
    n = 400
    X = np.column_stack([rng.uniform(0, 1, n), 10 ** rng.uniform(-2, 0, n), rng.normal(size=n), rng.uniform(0, 1, n)])
    y = 2 * X[:, 0] + np.log(X[:, 1]) + 0.5 * X[:, 2] + 0.3 * rng.normal(size=n)
    src, pcc, r2 = G.regression_measures(X, y)
    Z = (X - X.mean(0)) / X.std(0, ddof=1)
    fit = sm.OLS((y - y.mean()) / y.std(ddof=1), sm.add_constant(Z)).fit()
    check('SRC: the coefficients of statsmodels\' OLS on the standardized columns', close(src, fit.params[1:], rel=1e-10), True)
    check('R²: statsmodels\' rsquared', close(r2, fit.rsquared, rel=1e-10), True)

    def partial(X, y, k):
        others = sm.add_constant(np.delete(X, k, axis=1))
        return stats.pearsonr(sm.OLS(X[:, k], others).fit().resid, sm.OLS(y, others).fit().resid)[0]
    check('PCC: the correlation of the residuals of x and y on the other inputs', close(pcc, [partial(X, y, k) for k in range(4)], rel=1e-9), True)
    R, Ry = stats.rankdata(X, axis=0), stats.rankdata(y)
    srrc, prcc, r2r = G.regression_measures(R, Ry)
    fitr = sm.OLS((Ry - Ry.mean()) / Ry.std(ddof=1), sm.add_constant((R - R.mean(0)) / R.std(0, ddof=1))).fit()
    check('SRRC, PRCC and R² on ranks: the same on the ranks', (close(srrc, fitr.params[1:], rel=1e-10), close(prcc, [partial(R, Ry, k) for k in range(4)], rel=1e-9), close(r2r, fitr.rsquared, rel=1e-10)),
          (True, True, True))
    check('a perfect fit: R² 1, every input with a coefficient a PCC of ±1', (close(G.regression_measures(X[:, :2], X[:, 0] - 3 * X[:, 1])[2], 1.0, rel=1e-12),
                                                                              close(np.abs(G.regression_measures(X[:, :2], X[:, 0] - 3 * X[:, 1])[1]), [1, 1], rel=1e-9)), (True, True))
    check('two inputs the same numbers: no regression (NaN)', np.isnan(G.regression_measures(np.column_stack([X[:, 0], X[:, 0], X[:, 1]]), y)[2]), True)
    check('more inputs than rows allow: NaN', np.isnan(G.regression_measures(X[:5], y[:5])[2]), True)
    # SALib, PAWN and discrepancy
    try:
        from SALib.analyze import discrepancy as sd
        from SALib.analyze import pawn as sp
    except ImportError:
        print('(SALib is not installed: its checks are skipped)')
        return
    problem = {'num_vars': 4, 'names': ['a', 'b', 'c', 'd'], 'bounds': [[X[:, k].min(), X[:, k].max()] for k in range(4)]}
    with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
        warnings.simplefilter('ignore')
        sal = sp.analyze(problem, X, y, S=10, print_to_console=False)
    ours = [G.pawn(X[:, k], y) for k in range(4)]
    check('PAWN: SALib\'s median and maximum (10 slices)', (close([o['median'] for o in ours], sal['median']), close([o['maximum'] for o in ours], sal['maximum'])), (True, True))
    P = (stats.rankdata(X, axis=0) - 0.5) / n
    unit = {'num_vars': 4, 'names': ['a', 'b', 'c', 'd'], 'bounds': [[0, 1]] * 4}
    with contextlib.redirect_stdout(io.StringIO()):
        dis = sd.analyze(unit, P, (stats.rankdata(y) - 0.5) / n, method='WD', print_to_console=False)
    check('discrepancy: SALib\'s shares, on the ranks of both', close(G.discrepancy_shares(X, y), dis['s_discrepancy'], rel=1e-10), True)


# ---- known answers -------------------------------------------------------------------------
def known():
    n = 1 << 13
    X = rng.uniform(-np.pi, np.pi, size=(n, 4))
    y = np.sin(X[:, 0]) + 7 * np.sin(X[:, 1]) ** 2 + 0.1 * X[:, 2] ** 4 * np.sin(X[:, 0])
    want = [0.3139, 0.4424, 0.0, 0.0]
    e = [G.easi(X[:, k], y)[1] for k in range(4)]
    b = [G.first_order_index(X[:, k], y) for k in range(4)]
    check('Ishigami: EASI\'s first-order indices within 0.02 of 0.3139, 0.4424, 0, 0', bool(np.all(np.abs(np.array(e) - want) < 0.02)), True)
    check('Ishigami: S1 by binning within 0.03 of them', bool(np.all(np.abs(np.array(b) - want) < 0.03)), True)
    check('Ishigami: x2 matters most and is not monotone, so no correlation sees it', (abs(stats.spearmanr(X[:, 1], y)[0]) < 0.05, e[1] > 0.4), (True, True))
    a = np.array([1.0, 2.0, 0.0])
    Xl = rng.uniform(0, 1, size=(n, 3))
    yl = Xl @ a
    want = a ** 2 / (a ** 2).sum()
    check('a linear model: S1 = a_k² var x_k / var y both ways; SRC exactly a_k sd(x_k) / sd(y)', (bool(np.all(np.abs([G.easi(Xl[:, k], yl)[1] for k in range(3)] - want) < 0.02)),
                                                                                                    bool(np.all(np.abs([G.first_order_index(Xl[:, k], yl) for k in range(3)] - want) < 0.03)),
                                                                                                    close(G.regression_measures(Xl, yl)[0], a * Xl.std(0, ddof=1) / yl.std(ddof=1), rel=1e-9, abs_=1e-12)),
          (True, True, True))
    m = 1000
    X = np.column_stack([rng.uniform(0, 1, m), rng.uniform(0, 1, m)])
    y = np.exp(4 * X[:, 0]) * (1 + 0.1 * rng.normal(size=m))
    scores = stats.norm.ppf((stats.rankdata(y) - 0.5) / m)
    r = np.random.default_rng(3)
    d0, d1 = (G.delta_moment(X[:, k], scores, r, boots=50) for k in range(2))
    check('δ: the input y is made of far above the one it is not, whose interval holds 0 or nearly', (d0[1] > 0.5, d1[1] < 0.05, d1[2] < 0.03), (True, True, True))
    mi0, mi1 = (G.mutual_information(stats.rankdata(X[:, k]), stats.rankdata(y), r, boots=50) for k in range(2))
    check('mutual information: above chance for the input that matters, not for the other', (mi0[2] > 1, mi1[2] < 0.05), (True, True))
    above, ks, p, dm, dsd = G.regional(X, y, np.median(y), np.random.default_rng([1, 2]))
    check('regional: the input that matters splits the realisations, the other sits with the dummies', (ks[0] > 0.9, p[0] < 1e-10, abs(ks[1] - dm) < 4 * dsd + 0.05), (True, True, True))


# ---- the page's calls --------------------------------------------------------------------------
def calls():
    n = 300
    U = rng.uniform(-np.pi, np.pi, size=(n, 3))
    kd = 10 ** rng.uniform(-3, -1, n)
    dose = 1e-5 / (1 + 1e3 * kd) * np.exp(U[:, 0])
    cols = {'x1': U[:, 0].tolist(), 'x2': U[:, 1].tolist(), 'kd': kd.tolist(), 'flat': [2.0] * n,
            'y': (np.sin(U[:, 0]) + 7 * np.sin(U[:, 1]) ** 2).tolist(), 'dose': dose.tolist()}
    cols['y'][5] = None                      # a missing output
    cols['x2'][7] = None                     # a missing input
    cols['dose'][9] = 0.0                    # no logarithm
    cols['dose'][11] = -1.0
    tid = table(cols)
    inputs = ['x1', 'x2', 'kd', 'flat']
    r = call('sensitivity.measures', table=tid, y='y', x=inputs)
    keep = np.array([i for i in range(n) if i not in (5, 7)])
    X = np.column_stack([np.asarray(cols[c], dtype=float)[keep] for c in inputs])
    y = np.asarray([cols['y'][i] for i in keep], dtype=float)
    src, pcc, r2 = G.regression_measures(X, y)
    srrc, prcc, r2r = G.regression_measures(stats.rankdata(X, axis=0), stats.rankdata(y))
    check('measures: the realisations with the output and every input, and what was left out', (r['n'], r['left_out'], r['index'] == keep.tolist()),
          (n - 2, '2 with the output or an input missing', True))
    rows = {x['input']: x for x in r['rows']}
    live = ['x1', 'x2', 'kd']
    check('measures: Pearson and Spearman (and their p) as scipy\'s', close([[rows[c]['pearson'], rows[c]['pearson_p'], rows[c]['spearman'], rows[c]['spearman_p']] for c in live],
                                                                             [[*stats.pearsonr(X[:, k], y), *stats.spearmanr(X[:, k], y)] for k in range(3)]), True)
    check('measures: SRC, PCC, SRRC, PRCC, S1 and the R²s', (close([[rows[c][f] for f in ('src', 'pcc', 'srrc', 'prcc')] for c in inputs], np.column_stack([src, pcc, srrc, prcc])),
                                                            close([rows[c]['s1'] for c in live], [G.first_order_index(X[:, k], y) for k in range(3)]), close([r['r2'], r['r2_rank']], [r2, r2r])),
          (True, True, True))
    check('measures: a constant input is said to be, its measures missing', (rows['flat']['constant'], [rows['flat'][f] for f in ('pearson', 'spearman', 'src', 'prcc', 's1')]),
          (True, [None] * 5))
    lg = call('sensitivity.measures', table=tid, y='dose', x=inputs, log_y=True)
    keep2 = np.array([i for i in range(n) if i not in (7, 9, 11)])
    yl = np.log(np.asarray(cols['dose'], dtype=float)[keep2])
    X2 = np.column_stack([np.asarray(cols[c], dtype=float)[keep2] for c in inputs])
    check('Log Output: the realisations not above zero left out and said so', (lg['n'], lg['left_out']), (n - 3, '1 with the output or an input missing; 2 with dose not above zero, which has no logarithm'))
    rl = {x['input']: x for x in lg['rows']}
    check('Log Output: Pearson, SRC, S1 on the logarithms; the rank measures as on the values', (
        close([rl[c]['pearson'] for c in live], [stats.pearsonr(X2[:, k], yl)[0] for k in range(3)]),
        close([rl[c]['src'] for c in inputs], G.regression_measures(X2, yl)[0]),
        close([rl[c]['s1'] for c in live], [G.first_order_index(X2[:, k], yl) for k in range(3)]),
        close([rl[c]['prcc'] for c in inputs], G.regression_measures(stats.rankdata(X2, axis=0), stats.rankdata(np.exp(yl)))[1])), (True, True, True, True))
    sub = call('sensitivity.measures', table=tid, y='y', x=inputs, rows=list(range(0, n, 2)))
    check('measures: the report\'s rows only (a By group, rows excluded)', sub['n'], len([i for i in range(0, n, 2) if i not in (5, 7)]))
    few = call('sensitivity.measures', table=tid, y='y', x=inputs, rows=list(range(11)))
    check('measures: fewer than 10 realisations is refused with the reason', few.get('error'), '9 realisations with y and every input present: at least 10 are needed')
    # the distribution-based measures: the same numbers as the functions with the seed's draws
    d = call('sensitivity.distribution', table=tid, y='y', x=inputs, boots=40, seed=5)
    scores = stats.norm.ppf((stats.rankdata(y) - 0.5) / len(y))
    want = []
    for k in range(3):
        g = np.random.default_rng([5, k])
        dm = G.delta_moment(X[:, k], scores, g, boots=40)
        mi = G.mutual_information(stats.rankdata(X[:, k]), stats.rankdata(y), g, boots=40)
        pw = G.pawn(X[:, k], y)
        want.append([G.easi(X[:, k], y)[1], dm[1], dm[2], dm[3], pw['median'], pw['maximum'], *mi])
    rows = {x['input']: x for x in d['rows']}
    check('distribution: EASI, δ, PAWN and mutual information, each input\'s draws from [seed, k]',
          close([[rows[c][f] for f in ('easi', 'delta', 'delta_low', 'delta_high', 'pawn', 'pawn_max', 'mi', 'mi_bound', 'mi_above')] for c in live], want), True)
    check('distribution: the discrepancy shares, over the inputs that vary', close([rows[c]['discrepancy'] for c in live], G.discrepancy_shares(X[:, :3], y)), True)
    check('distribution: a constant input has none', (rows['flat']['constant'], rows['flat']['delta'], rows['flat']['discrepancy']), (True, None, None))
    saved = G.DISCREPANCY_WORK
    G.DISCREPANCY_WORK = 1000
    try:
        dd = call('sensitivity.distribution', table=tid, y='y', x=inputs, boots=5)
    finally:
        G.DISCREPANCY_WORK = saved
    check('distribution: past the discrepancy\'s budget it is left out, and said so', (dd['discrepancy'], dd['rows'][0]['discrepancy']), (False, None))
    # regional
    for split, value, t in [('mean', None, y.mean()), ('median', None, np.median(y)), ('quantile', 0.9, np.quantile(y, 0.9)), ('value', 3.0, 3.0)]:
        g = call('sensitivity.regional', table=tid, y='y', x=inputs, split=split, value=value, seed=4)
        above = y > t
        ks = [stats.ks_2samp(X[above, k], X[~above, k]) for k in range(4)]
        dummies = [stats.ks_2samp(u[above], u[~above]).statistic for u in np.random.default_rng([4, 4]).random((10, len(y)))]
        check(f'regional ({split}): the threshold, the two groups, each KS and p, the dummies\' level',
              (close(g['threshold'], t), g['above'], g['below'], close([x['ks'] for x in g['rows']], [k.statistic for k in ks]), close([x['p'] for x in g['rows']], [k.pvalue for k in ks]),
               close([g['dummy_mean'], g['dummy_sd']], [np.mean(dummies), np.std(dummies, ddof=1)]), g['above_rows'] == keep[above].tolist()),
              (True, int(above.sum()), int((~above).sum()), True, True, True, True))
    gm = call('sensitivity.regional', table=tid, y='dose', x=inputs, log_y=True)
    check('regional with Log Output: split at the geometric mean, said in the output\'s units', (close(gm['threshold'], math.exp(yl.mean())), gm['how']), (True, 'the geometric mean'))
    bad = call('sensitivity.regional', table=tid, y='y', x=inputs, split='value', value=1e9)
    check('regional: a threshold above every realisation is refused with the reason', bad.get('error', '').startswith('every realisation is at or below the threshold'), True)
    return tid, cols


# ---- the code under each result ----------------------------------------------------------------
def code_ns(columns, code, label):
    """Run a result's code on a CSV export of its table; its variables."""
    import matplotlib
    matplotlib.use('Agg')
    with tempfile.TemporaryDirectory() as tmp:
        pd.DataFrame(columns).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        here = os.getcwd()
        os.chdir(tmp)
        ns = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                exec(compile(code, label, 'exec'), ns)
        except Exception as e:   # the check below reports it
            ns['__error__'] = f'{type(e).__name__}: {e}'
        finally:
            os.chdir(here)
    check(f'the code of {label} runs', ns.get('__error__', True), True)
    return ns


def codes(tid, cols):
    inputs = ['x1', 'x2', 'kd', 'flat']
    for log_y, y, rows in [(False, 'y', None), (True, 'dose', list(range(0, 300, 3)))]:
        tag = f'{y}{", Log Output" if log_y else ""}{", a third of the rows" if rows else ""}'
        r = call('sensitivity.measures', table=tid, y=y, x=inputs, log_y=log_y, rows=rows)
        ns = code_ns(cols, r['code'], f'Measures ({tag})')
        if 'table' in ns:
            t = ns['table']
            check(f'Measures ({tag}): the code gives the report\'s numbers', (close(t[['SRC', 'PCC', 'SRRC', 'PRCC']].to_numpy(), [[x[f] for f in ('src', 'pcc', 'srrc', 'prcc')] for x in r['rows']]),
                                                                              close(t['S1'].to_numpy()[:3], [x['s1'] for x in r['rows'][:3]]), close(t['Spearman'].to_numpy()[:3], [x['spearman'] for x in r['rows'][:3]]),
                                                                              close([ns['r2'], ns['r2_rank']], [r['r2'], r['r2_rank']]), len(ns['y']) == r['n']), (True, True, True, True, True))
        code_ns(cols, r['plots_code'], f'the scatterplots ({tag})')
        d = call('sensitivity.distribution', table=tid, y=y, x=inputs, log_y=log_y, rows=rows, boots=20, seed=9)
        ns = code_ns(cols, d['code'], f'the distribution-based measures ({tag})')
        if 'table' in ns:
            t = ns['table']
            cols3 = ['S1 (EASI)', 'δ', 'δ Lower', 'δ Upper', 'PAWN', 'PAWN Max', 'MI', 'MI Chance', 'MI Above', 'Discrepancy']
            keys = ['easi', 'delta', 'delta_low', 'delta_high', 'pawn', 'pawn_max', 'mi', 'mi_bound', 'mi_above']
            check(f'the distribution-based measures ({tag}): the code gives the report\'s numbers', (close(t[cols3[:-1]].to_numpy()[:3], [[x[f] for f in keys] for x in d['rows'][:3]], rel=1e-8),
                                                                                                    close(t['Discrepancy'].to_numpy()[:3], [x['discrepancy'] for x in d['rows'][:3]])), (True, True))
        g = call('sensitivity.regional', table=tid, y=y, x=inputs, log_y=log_y, rows=rows, split='quantile', value=0.75, seed=2)
        code_ns(cols, g['plots_code'], f'the regional analysis\'s distributions ({tag})')
        ns = code_ns(cols, g['code'], f'the regional analysis ({tag})')
        if 'ks' in ns:
            check(f'the regional analysis ({tag}): the code gives the report\'s numbers', (close(ns['ks'], [x['ks'] for x in g['rows']]), close(ns['p'], [x['p'] for x in g['rows']]),
                                                                                           close([ns['dummy_mean'], ns['dummy_sd']], [g['dummy_mean'], g['dummy_sd']])), (True, True, True))
    # names that need quoting, in the code as string literals
    odd = {'it\'s "x"': cols['x1'], 'a\\b': cols['x2'], 'y #2': cols['y']}
    t2 = table(odd)
    r = call('sensitivity.measures', table=t2, y='y #2', x=['it\'s "x"', 'a\\b'])
    ns = code_ns(odd, r['code'], 'Measures (names with quotes, a backslash and a #)')
    check('names with quotes, a backslash and a # come through the code', ns.get('inputs'), ['it\'s "x"', 'a\\b'])


def main():
    against_kompartment()
    references()
    known()
    tid, cols = calls()
    codes(tid, cols)
    return check.done()


if __name__ == '__main__':
    sys.exit(main())
