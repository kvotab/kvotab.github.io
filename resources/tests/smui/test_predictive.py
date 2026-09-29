#!/usr/bin/env python3
"""The predictive platforms' shared backend (resources/py/smui/predictive.py
and profile.py): the sets a Validation column or a validation portion
makes, the predictor matrix with Informative Missing, the Measures of Fit,
confusion matrices and ROC and lift curves (against scikit-learn's metrics
and the formulas written out here), the saved predictions, the model cache,
the profiler's traces (through registry.dispatch, as the page calls them),
and the Python P.code() writes, run on a CSV export of the table.

    python3 resources/tests/smui/test_predictive.py
"""
import json
import math
import os
import subprocess
import sys
import tempfile

import numpy as np
import pandas as pd

from backend import FAILED, Checks, call, table


# ---- the graphs' matplotlib code, natively -------------------------------------------------------
# Shared by the predictive platforms' suites (test_partition.py and the others import these): a
# graph's code (predictive.graph_codes: a head and a tail, joined by SEP) is run with matplotlib's
# Agg backend on a CSV export of the whole table, as the page exports it (a date as YYYY-MM-DD
# text), and its figure is checked against the report's numbers.

SEP = '\n\n# ----\n'
PALETTE = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']


def export_frame(tid):
    """The table as File > Export CSV writes it: every column by name, a date column as its text."""
    from smui import data
    t = data.TABLES[tid]
    out = {}
    for name, v in t['cols'].items():
        m = t['meta'][name]
        kind = (m.get('format') or {}).get('kind')
        if m.get('dataType') == 'numeric' and kind in ('date', 'datetime'):
            fmt_ = '%Y-%m-%d' if kind == 'date' else '%Y-%m-%d %H:%M:%S'
            out[name] = pd.Series(['' if not np.isfinite(x) else pd.Timestamp(x, unit='ms').strftime(fmt_) for x in np.asarray(v, dtype=float)], dtype=object)
        elif m.get('dataType') == 'numeric':
            out[name] = np.asarray(v, dtype=float)
        else:
            out[name] = pd.Series(list(v), dtype=object)
    return pd.DataFrame(out)


def run_graph(code, tid, tmp, name='data'):
    """A graph's code run on the table's CSV: (the figure, as test_charts.PROBE gives it, or None; an error)."""
    from test_charts import run_snippet
    figs, err = run_snippet(code, export_frame(tid), name, tmp)
    if err is None and len(figs or []) != 1:
        err = f'{len(figs or [])} figures'
    return (figs[0] if figs and not err else None), err


def joined(plots, key, sub=None):
    """The whole code of one graph: the head of plots, then the graph's own lines."""
    tail = plots[key] if sub is None else plots[key][sub]
    return plots['head_code'] + SEP + tail


def subset_in_order(want, got, tol=1e-9):
    """Every point of want is a point of got, in the same order (a curve the report thinned)."""
    i = 0
    for w_ in want:
        while i < len(got) and not (abs(got[i][0] - w_[0]) <= tol * max(1, abs(w_[0])) and abs(got[i][1] - w_[1]) <= tol * max(1, abs(w_[1]))):
            i += 1
        if i == len(got):
            return False
        i += 1
    return True


def scatter_pts(ax):
    return [tuple(p) for sc in ax['scatter'] for p in sc['xy']]


def check_shared_native(check, label, fit, tid, tmp, head=None):
    """The graphs of predictive.report's plots, run on the table's CSV: every set's ROC and lift curves
    (the report's points on each curve, its AUC in the legend) or actual by predicted (the rows'
    points). Returns how many graphs were run."""
    from test_charts import find_line
    P = dict(fit['plots'])
    if head is not None:
        P['head_code'] = head
    n = 0
    if fit['kind'] == 'categorical':
        for kind in ('roc', 'lift'):
            if kind not in P:
                continue
            for s in fit['sets']:
                F, err = run_graph(joined(P, kind, s), tid, tmp)
                check(f'{label}: {kind} {s}: the code runs, ending in plt.show()', (err, P[kind][s].rstrip().split('\n')[-1]), (None, 'plt.show()'))
                if not F:
                    continue
                n += 1
                ax = F['axes'][0]
                want = [c for c in fit[kind] if c['set'] == s]
                ok = []
                for i, c in enumerate(want):
                    name = f'{c["level"]} ({c["auc"]:.4f})' if kind == 'roc' else c['level']
                    ln = next((q for q in ax['lines'] if q['label'] == name), None)
                    pts = list(zip(c['fpr'], c['tpr'])) if kind == 'roc' else list(zip(c['portion'], c['lift']))
                    ok.append(bool(ln) and subset_in_order(pts, list(zip(ln['x'], ln['y']))) and ln['color'][:7] == PALETTE[i % len(PALETTE)])
                check(f'{label}: {kind} {s}: every level\'s curve is the report\'s, in the palette\'s colours', (len(want) > 0, ok), (True, [True] * len(want)))
                check(f'{label}: {kind} {s}: the legend', ax['legend'], [f'{c["level"]} ({c["auc"]:.4f})' if kind == 'roc' else c['level'] for c in want])
                check(f'{label}: {kind} {s}: the reference line, the titles', (find_line(ax, [0, 1], [0, 1] if kind == 'roc' else [1, 1]) is not None, ax['xlabel'], ax['ylabel'], ax['title']),
                      (True, '1 - Specificity' if kind == 'roc' else 'Portion', 'Sensitivity' if kind == 'roc' else 'Lift', f'{"ROC" if kind == "roc" else "Lift"} {s}'))
    else:
        r = fit['residuals']
        for k, s in enumerate(('Training', 'Validation', 'Test')):
            if s not in fit['sets']:
                continue
            F, err = run_graph(joined(P, 'abp', s), tid, tmp)
            check(f'{label}: actual by predicted {s}: the code runs', err, None)
            if not F:
                continue
            n += 1
            ax = F['axes'][0]
            want = [(p, a) for p, a, st in zip(r['predicted'], r['actual'], r['set']) if st == k]
            got = scatter_pts(ax)
            check(f'{label}: actual by predicted {s}: the rows\' points', len(got) == len(want) and all(abs(a - c) <= 1e-9 * max(1, abs(c)) and abs(b - d) <= 1e-9 * max(1, abs(d)) for (a, b), (c, d) in zip(got, want)), True)
            v = [q for p in want for q in p]
            check(f'{label}: actual by predicted {s}: the line of equality, the titles', (find_line(ax, [min(v), max(v)], [min(v), max(v)]) is not None, ax['xlabel'], ax['ylabel'], ax['title']),
                  (True, 'Predicted', 'Actual', f'Actual by predicted {s}'))
    return n


def check_contrib_native(check, label, contrib, head, tid, tmp, title='Column Contributions'):
    """The Column Contributions' bars, from the model the code fits: a bar per column, largest first, its portion."""
    F, err = run_graph(head + SEP + contrib['plot_code'], tid, tmp)
    check(f'{label}: {title}: the code runs', err, None)
    if not F:
        return 0
    ax = F['axes'][0]
    check(f'{label}: {title}: the columns, largest first', [t for t in ax['yticklabels'] if t], [r['column'] for r in contrib['rows']])
    check(f'{label}: {title}: their portions', all(abs(b['w'] - (r['portion'] or 0.0)) <= 1e-9 for b, r in zip(ax['bars'], contrib['rows'])) and len(ax['bars']) == len(contrib['rows']), True)
    check(f'{label}: {title}: the titles', (ax['xlabel'], ax['title']), ('Portion', title))
    return 1


def main():

    check = Checks()
    check('predictive.py and profile.py import', ('predictive' in FAILED, 'profile' in FAILED), (False, False))
    from smui import predictive as pv, profile, registry  # noqa: E402

    try:
        import sklearn  # noqa: F401
        from sklearn import metrics
        from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
    except ImportError:
        print('scikit-learn 1.8 is needed for these tests (Pyodide 314.0.7 has 1.8.0)')
        sys.exit(1)

    rng = np.random.default_rng(20260927)
    n = 240
    x1 = rng.normal(10, 3, n)
    x2 = rng.uniform(0, 1, n)
    g = rng.choice(['a', 'b', 'c'], n, p=[0.5, 0.3, 0.2])
    y = 2 + 0.8 * x1 - 3 * x2 + np.where(g == 'b', 1.5, np.where(g == 'c', -1.0, 0.0)) + rng.normal(0, 1, n)
    cls = np.where(y + rng.normal(0, 1.5, n) > np.median(y), 'high', 'low')
    three = np.where(y < np.quantile(y, 0.3), 'lo', np.where(y < np.quantile(y, 0.75), 'mid', 'hi'))
    w = rng.uniform(0.5, 2.0, n).round(3)
    fq = rng.integers(1, 4, n).astype(float)
    vnum = rng.choice([0.0, 1.0, 2.0], n, p=[0.6, 0.25, 0.15])
    vtxt = np.array(['Training', 'Validation', 'Test'])[vnum.astype(int)]
    x1m = x1.copy()
    x1m[rng.choice(n, 12, replace=False)] = np.nan
    gm = g.astype(object).copy()
    gm[rng.choice(n, 9, replace=False)] = None
    ym = y.copy()
    ym[[3, 17]] = np.nan
    vnm = vnum.copy()
    vnm[[5, 6]] = np.nan
    vtx_odd = vtxt.astype(object).copy()
    vtx_odd[4] = 'holdout'
    cols = {'y': list(ym), 'x1': list(x1), 'x1m': [None if np.isnan(v) else v for v in x1m], 'x2': list(x2), 'g': list(g), 'gm': list(gm),
            'cls': list(cls), 'three': list(three), 'w': list(w), 'f': list(fq), 'v': [None if np.isnan(v) else v for v in vnm], 'vt': list(vtxt), 'vodd': list(vtx_odd)}
    T = table(cols, types={'g': 'nominal', 'gm': 'nominal', 'cls': 'nominal', 'three': 'ordinal', 'vt': 'nominal', 'vodd': 'nominal'},
              levels={'three': ['lo', 'mid', 'hi'], 'cls': ['high', 'low']})

    # ---- the sets -------------------------------------------------------------------------------
    P = pv.prepare(T, 'y', ['x1', 'x2', 'g'], validation='v')
    keep = (~np.isnan(ym)) & (~np.isnan(vnm))
    check('rows with no response or no validation value are left out', (len(P.index), P.index.tolist()[:4]), (int(keep.sum()), np.flatnonzero(keep).tolist()[:4]))
    check('a numeric Validation column: 0 training, 1 validation, 2 test', P.sets.tolist(), vnm[keep].astype(int).tolist())
    check('the notes say what was left out', any('no y' in s for s in P.notes) and any('no v value' in s for s in P.notes), True)
    Pt = pv.prepare(T, 'y', ['x1'], validation='vt')
    check('a character Validation column by its names', Pt.sets.tolist(), vnum[~np.isnan(ym)].astype(int).tolist())
    try:
        pv.prepare(T, 'y', ['x1'], validation='vodd')
        check('an unknown validation value is an error', 'no error', 'error')
    except ValueError as e:
        check('an unknown validation value is an error that names it', 'holdout' in str(e), True)
    try:
        pv.prepare(T, 'y', ['x1'], validation='x2')
        check('a numeric column other than 0/1/2 is refused', 'no error', 'error')
    except ValueError as e:
        check('a numeric column other than 0/1/2 is refused', 'holds 0 (training)' in str(e), True)
    Pp = pv.prepare(T, 'y', ['x1'], portion=0.25, seed=42)
    nn = len(Pp.index)
    want = np.zeros(nn, dtype=int)
    want[np.random.default_rng(42).permutation(nn)[:int(round(0.25 * nn))]] = 1
    check('a validation portion: that share, drawn from the seed', Pp.sets.tolist(), want.tolist())
    check('the same seed draws the same rows', pv.prepare(T, 'y', ['x1'], portion=0.25, seed=42).sets.tolist(), Pp.sets.tolist())
    check('no validation: every row trains', set(pv.prepare(T, 'y', ['x1']).sets.tolist()), {0})
    try:
        pv.prepare(T, 'y', ['x1'], portion=0.3)
        check('a portion without a seed is refused', 'no error', 'error')
    except ValueError:
        check('a portion without a seed is refused', True, True)

    # ---- the predictor matrix ---------------------------------------------------------------------
    Pi = pv.prepare(T, 'y', ['x1m', 'x2', 'gm'])
    check('Informative Missing: a Missing column after a continuous one, a Missing level after the levels',
          Pi.features, ['x1m', 'x1m Missing', 'x2', 'gm[a]', 'gm[b]', 'gm[c]', 'gm[Missing]'])
    idx = Pi.index
    tr = Pi.train()
    fill = float(np.nanmean(x1m[idx][tr]))
    check.near('a missing value is the training mean', float(Pi.X[np.isnan(x1m[idx]), 0][0]), fill, 1e-12)
    check('... and its Missing column is 1', Pi.X[:, 1].tolist(), np.isnan(x1m[idx]).astype(float).tolist())
    gv = gm[idx]
    check('one 0/1 column per level', Pi.X[:, 3].tolist(), [1.0 if v == 'a' else 0.0 for v in gv])
    check('a missing level is its own column', Pi.X[:, 6].tolist(), [1.0 if v is None else 0.0 for v in gv])
    check('groups map each column to its columns of X', Pi.groups, {'x1m': [0, 1], 'x2': [2], 'gm': [3, 4, 5, 6]})
    Pd = pv.prepare(T, 'y', ['x1m', 'x2', 'gm'], missing='drop')
    okd = (~np.isnan(ym)) & (~np.isnan(x1m)) & np.array([v is not None for v in gm])
    check('Informative Missing off: rows missing a factor are left out', (len(Pd.index), Pd.features), (int(okd.sum()), ['x1m', 'x2', 'gm[a]', 'gm[b]', 'gm[c]']))
    Po = pv.prepare(T, 'y', ['x2', 'three'], coding='ordinal')
    check('ordinal coding: the level number', Po.X[:5, 1].tolist(), [float(['lo', 'mid', 'hi'].index(v)) for v in three[Po.index][:5]])

    # ---- the response and weights ---------------------------------------------------------------
    Pc = pv.prepare(T, 'three', ['x1', 'x2', 'g'], weight='w', freq='f')
    check('a categorical response: its levels in the table\'s order', (Pc.kind, Pc.levels, Pc.labels), ('categorical', ['lo', 'mid', 'hi'], ['lo', 'mid', 'hi']))
    check('the target is the level index', Pc.target[:6].tolist(), [['lo', 'mid', 'hi'].index(v) for v in three[Pc.index][:6]])
    check.near('the case weights are weight times frequency', float(Pc.w.sum()), float((w * fq)[Pc.index].sum()), 1e-12)
    check('counts are the frequencies alone', Pc.counts().tolist(), fq[Pc.index].tolist())
    try:
        pv.prepare(T, 'y', ['y', 'x1'], weight='y')
        check('a role column cannot be the response too', 'no error', 'error')
    except ValueError:
        check('a role column cannot be the response too', True, True)

    # ---- the measures of fit ----------------------------------------------------------------------
    Pm = pv.prepare(T, 'y', ['x1', 'x2', 'g'], validation='v', weight='w')
    mdl = DecisionTreeRegressor(max_depth=4, random_state=0).fit(Pm.X[Pm.train()], Pm.target[Pm.train()], sample_weight=Pm.w[Pm.train()])
    fit = mdl.predict(Pm.X)
    M = {r['set']: r for r in pv.measures(Pm, fit)}
    check('a row per set present', list(M), ['Training', 'Validation', 'Test'])
    for k, name in enumerate(pv.SETS):
        m = Pm.mask(k)
        ww, yy, ff = Pm.w[m], Pm.target[m], fit[m]
        check.near(f'{name}: RSquare as sklearn r2_score', M[name]['rsquare'], metrics.r2_score(yy, ff, sample_weight=ww), 1e-10)
        check.near(f'{name}: RASE', M[name]['rase'], math.sqrt(metrics.mean_squared_error(yy, ff, sample_weight=ww)), 1e-10)
        check.near(f'{name}: Mean Abs Dev', M[name]['mad'], metrics.mean_absolute_error(yy, ff, sample_weight=ww), 1e-10)
        sse = float(np.sum(ww * (yy - ff) ** 2)); N = float(ww.sum())
        check.near(f'{name}: -LogLikelihood of the normal with variance SSE/N', M[name]['neg_loglik'], N / 2 * (math.log(2 * math.pi * sse / N) + 1), 1e-10)

    Pk = pv.prepare(T, 'three', ['x1', 'x2', 'g'], validation='v', freq='f')
    clf = DecisionTreeClassifier(max_depth=3, random_state=0).fit(Pk.X[Pk.train()], Pk.target[Pk.train()], sample_weight=Pk.w[Pk.train()])
    pr = Pk.proba(clf, Pk.X)
    check('proba: one column per level, rows summing to 1', (pr.shape[1], bool(np.allclose(pr.sum(1), 1))), (3, True))
    M = {r['set']: r for r in pv.measures(Pk, pr)}
    wt = Pk.w[Pk.train()]
    share = np.array([wt[Pk.target[Pk.train()] == j].sum() for j in range(3)]) / wt.sum()
    for k, name in enumerate(pv.SETS):
        m = Pk.mask(k)
        yy, pp, ww = Pk.target[m], pr[m], Pk.w[m]
        N = ww.sum()
        pt = np.clip(pp[np.arange(len(yy)), yy], 1e-15, 1)
        ll = np.sum(ww * np.log(pt)); ll0 = np.sum(ww * np.log(share[yy]))
        check.near(f'{name}: Mean -Log p as sklearn log_loss', M[name]['mean_neg_log_p'], metrics.log_loss(yy, np.clip(pp, 1e-15, 1), sample_weight=ww, labels=[0, 1, 2]), 1e-9)
        check.near(f'{name}: Misclassification Rate as 1 - accuracy', M[name]['misclassification'], 1 - metrics.accuracy_score(yy, pp.argmax(1), sample_weight=ww), 1e-12)
        check.near(f'{name}: Entropy RSquare 1 - LL/LL0 (LL0 the training shares)', M[name]['entropy_rsquare'], 1 - ll / ll0, 1e-10)
        check.near(f'{name}: Generalized RSquare (Nagelkerke)', M[name]['generalized_rsquare'], (1 - math.exp(2 * (ll0 - ll) / N)) / (1 - math.exp(2 * ll0 / N)), 1e-10)
        check.near(f'{name}: RASE of 1 - p(actual)', M[name]['rase'], math.sqrt(np.sum(ww * (1 - pt) ** 2) / N), 1e-10)

    # binary: AUC, ROC, lift and confusion against sklearn
    Pb = pv.prepare(T, 'cls', ['x1', 'x2', 'g'], validation='v', freq='f')
    cb = DecisionTreeClassifier(max_depth=4, random_state=1).fit(Pb.X[Pb.train()], Pb.target[Pb.train()], sample_weight=Pb.w[Pb.train()])
    pb = Pb.proba(cb, Pb.X)
    M = {r['set']: r for r in pv.measures(Pb, pb)}
    R = pv.roc(Pb, pb)
    L = pv.lift(Pb, pb)
    C = {c['set']: c for c in pv.confusion(Pb, pb)}
    for k, name in enumerate(pv.SETS):
        m = Pb.mask(k)
        yy, pp, ff = Pb.target[m], pb[m], Pb.counts(m)
        check.near(f'{name}: AUC as sklearn roc_auc_score (frequencies as weights)', M[name]['auc'], metrics.roc_auc_score(yy, pp[:, 1], sample_weight=Pb.w[m]), 1e-12)
        for j, lab in enumerate(Pb.labels):
            r = next(x for x in R if x['set'] == name and x['level'] == lab)
            check.near(f'{name} {lab}: the ROC curve\'s AUC', r['auc'], metrics.roc_auc_score(yy == j, pp[:, j], sample_weight=ff), 1e-12)
            fpr, tpr, _ = metrics.roc_curve(yy == j, pp[:, j], sample_weight=ff, drop_intermediate=False)
            check(f'{name} {lab}: the ROC points are sklearn\'s', bool(np.allclose(r['fpr'], fpr) and np.allclose(r['tpr'], tpr)), True)
            li = next(x for x in L if x['set'] == name and x['level'] == lab)
            check.near(f'{name} {lab}: the lift is 1 when every row is taken', li['lift'][-1], 1.0, 1e-12)
        check(f'{name}: the confusion matrix is sklearn\'s (counted by frequency)', C[name]['matrix'], metrics.confusion_matrix(yy, pp.argmax(1), sample_weight=ff, labels=[0, 1]).tolist())
    # lift at the top rows, by hand
    m = Pb.mask(0)
    yy, pp, ff = Pb.target[m], pb[m], Pb.counts(m)
    order = np.argsort(-pp[:, 0], kind='mergesort')
    cw = np.cumsum(ff[order]); hits = np.cumsum(ff[order] * (yy[order] == 0))
    li = next(x for x in L if x['set'] == 'Training' and x['level'] == Pb.labels[0])
    check.near('lift at the first point, by hand', li['lift'][0], (hits[0] / cw[0]) / (ff[yy == 0].sum() / ff.sum()), 1e-12)
    # ties: AUC counts them half
    check.near('AUC with ties counts them half', pv._auc(np.array([0.5, 0.5, 0.2, 0.9]), np.array([True, False, False, True]), np.ones(4)), metrics.roc_auc_score([1, 0, 0, 1], [0.5, 0.5, 0.2, 0.9]), 1e-12)
    # a big ROC curve is thinned
    big = pv.roc(Pb, np.column_stack([1 - np.linspace(0, 1, len(Pb.index)), np.linspace(0, 1, len(Pb.index))]), most=50)
    check('a ROC curve keeps at most the points asked for', max(len(r['fpr']) for r in big) <= 50, True)
    rep = pv.report(Pb, pb)
    check('report(): measures, confusion, ROC and lift for a categorical response', sorted(k for k in rep if rep[k] is not None), sorted(['kind', 'measures', 'measure_columns', 'sets', 'n', 'notes', 'features', 'levels', 'confusion', 'roc', 'lift']))
    check('report(): actual by predicted for a continuous one', 'residuals' in pv.report(Pm, fit), True)

    # ---- contributions, saved predictions, the cache ------------------------------------------------
    con = pv.contributions(Pi, np.arange(7, dtype=float) + 1)
    check('contributions sum a column\'s features, largest first', [(r['column'], r['value']) for r in con['rows']], [('gm', 4 + 5 + 6 + 7.0), ('x1m', 3.0), ('x2', 3.0)])
    check.near('... and their portions add to 1', sum(r['portion'] for r in con['rows']), 1.0, 1e-12)
    Pd2 = pv.prepare(T, 'y', ['x1m', 'x2'], missing='drop', rows=list(range(0, 200)))
    reg = DecisionTreeRegressor(max_depth=3, random_state=0).fit(Pd2.X, Pd2.target)
    sv = pv.saved(Pd2, reg.predict)
    check('Save Predicteds: every row of the table with its factors, excluded rows too', sv['rows'], np.flatnonzero(~np.isnan(x1m)).tolist())
    X_all = np.column_stack([x1m, x2])[sv['rows']]
    check('... predicted by the model', bool(np.allclose(sv['values'], reg.predict(X_all))), True)
    svc = pv.saved(Pb, None, lambda X: Pb.proba(cb, X))
    check('Save Probabilities: a column per level and the most likely level', (svc['names'], svc['most_name'], len(svc['rows'])), (['Prob[high]', 'Prob[low]'], 'Most Likely cls', n))
    built = []
    a = pv.cached('test', T, None, {'k': 1}, lambda: built.append(1) or object())
    b = pv.cached('test', T, None, {'k': 1}, lambda: built.append(1) or object())
    c = pv.cached('test', T, None, {'k': 2}, lambda: built.append(1) or object())
    check('the cache builds a model once per spec', (a is b, a is c, len(built)), (True, False, 2))

    # ---- the profiler, through dispatch --------------------------------------------------------------
    def build(tid, rows=None, y=None, x=(), depth=3):
        Q = pv.prepare(tid, y, list(x), rows=rows)
        if Q.kind == 'continuous':
            model = pv.cached('ptest', tid, rows, {'y': y, 'x': list(x), 'd': depth}, lambda: DecisionTreeRegressor(max_depth=depth, random_state=0).fit(Q.X, Q.target))
        else:
            model = pv.cached('ptest', tid, rows, {'y': y, 'x': list(x), 'd': depth}, lambda: DecisionTreeClassifier(max_depth=depth, random_state=0).fit(Q.X, Q.target))
        return pv.predictor(Q, model)


    profile.expose('ptest', build, packages=pv.SK)
    check('expose() registers <area>.profile, needing scikit-learn', ('ptest.profile' in registry.names(), json.loads(registry.packages_for('ptest.profile'))), (True, ['scikit-learn']))
    check('a function with no extra packages needs none', json.loads(registry.packages_for('distribution.continuous')), [])
    r = call('ptest.profile', table=T, y='y', x=['x1', 'x2', 'g'], current={'x1': 12.0, 'g': 'b'}, grid=11)
    check('the factors: ranges and levels', [(f['name'], f['type']) for f in r['factors']], [('x1', 'continuous'), ('x2', 'continuous'), ('g', 'categorical')])
    f0 = r['factors'][0]
    check('the current values: as set, or the mean', (f0['current'], r['factors'][1]['current'], r['factors'][2]['current']), (12.0, float(np.mean(x2[~np.isnan(ym)])), 'b'))
    Q = pv.prepare(T, 'y', ['x1', 'x2', 'g'])
    tree = DecisionTreeRegressor(max_depth=3, random_state=0).fit(Q.X, Q.target)
    tr0 = r['responses'][0]['traces'][0]
    grid = np.linspace(f0['min'], f0['max'], 11)
    Xg = Q.encode_settings([{'x1': v, 'x2': r['factors'][1]['current'], 'g': 'b'} for v in grid])
    check('a trace: the prediction over the factor, the others at their current values', bool(np.allclose(tr0['pred'], tree.predict(Xg))), True)
    check('a categorical factor\'s trace runs over its labels', r['responses'][0]['traces'][2]['x'], ['a', 'b', 'c'])
    check.near('the current prediction', r['responses'][0]['current']['pred'], float(tree.predict(Q.encode_settings([{'x1': 12.0, 'x2': r['factors'][1]['current'], 'g': 'b'}]))[0]), 1e-12)
    r2 = call('ptest.profile', table=T, y='x1', x=['x2'], current={'x2': 99})
    check('a value beyond the range is kept at its end', r2['factors'][0]['current'], float(np.max(x2)))
    rc = call('ptest.profile', table=T, y='three', x=['x1', 'g'])
    check('a categorical response: one bounded row per level', [(p['name'], p['bounded']) for p in rc['responses']], [('Prob[lo]', True), ('Prob[mid]', True), ('Prob[hi]', True)])
    check('... whose probabilities add to 1', bool(np.allclose(np.sum([p['traces'][0]['pred'] for p in rc['responses']], axis=0), 1)), True)

    # ---- the code under a report, on a CSV export ------------------------------------------------------
    def run_code(P, rows=None):
        with tempfile.TemporaryDirectory() as tmp:
            pd.DataFrame(cols).to_csv(os.path.join(tmp, 'data.csv'), index=False)
            lines = P.code('data', rows=rows) + [
                'import json',
                'print(json.dumps({"X": X.tolist(), "y": np.asarray(y, float).tolist(), "sets": sets.tolist(), "w": None if w is None else w.tolist(), "index": d.index.tolist()}))']
            with open(os.path.join(tmp, 'code.py'), 'w') as fh:
                fh.write('\n'.join(lines))
            out = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=120)
            if out.returncode:
                print(out.stderr[-2000:])
                return None
            return json.loads(out.stdout.strip().splitlines()[-1])


    for label, Q, rows in [
            ('Informative Missing, a character Validation column, weight and frequency', pv.prepare(T, 'three', ['x1m', 'x2', 'gm'], validation='vt', weight='w', freq='f'), None),
            ('rows of the report, a validation portion', pv.prepare(T, 'y', ['x1', 'g'], portion=0.3, seed=7, rows=list(range(10, 230))), list(range(10, 230))),
            ('Informative Missing off, a numeric Validation column', pv.prepare(T, 'cls', ['x1m', 'gm', 'x2'], validation='v', missing='drop'), None),
            ('ordinal coding', pv.prepare(T, 'y', ['three', 'x2'], coding='ordinal'), None)]:
        got = run_code(Q, rows)
        if got is None:
            check(f'the code runs: {label}', False, True)
            continue
        same = (np.allclose(got['X'], Q.X) and np.allclose(got['y'], Q.target) and got['sets'] == Q.sets.tolist() and got['index'] == Q.index.tolist()
                and ((got['w'] is None and Q.w is None) or (got['w'] is not None and Q.w is not None and np.allclose(got['w'], Q.w))))
        check(f'the code builds the same X, y, weights and sets: {label}', bool(same), True)

    # a level named None (or NA): text in the CSV, and a level to the code as to the page (the Churn
    # example's internet has one); pandas' defaults would read it as missing
    Tn = table({'y': list(y[:60]), 'net': (['None', 'DSL', 'Fiber'] * 20), 'q': ['NA'] * 30 + ['x'] * 30}, types={'net': 'nominal', 'q': 'nominal'}, levels={'net': ['None', 'DSL', 'Fiber']})
    Qn = pv.prepare(Tn, 'y', ['net', 'q'])
    with tempfile.TemporaryDirectory() as tmp:
        export_frame(Tn).to_csv(os.path.join(tmp, 'data.csv'), index=False)
        with open(os.path.join(tmp, 'code.py'), 'w') as fh:
            fh.write('\n'.join(Qn.code('data') + ['import json', 'print(json.dumps(X.tolist()))']))
        out = subprocess.run([sys.executable, 'code.py'], cwd=tmp, capture_output=True, text=True, timeout=120)
    check('a level named None or NA is a level to the code too: the same X', out.returncode == 0 and np.allclose(json.loads(out.stdout.strip().splitlines()[-1]), Qn.X), True)

    # ---- the shared graphs' code (predictive.graph_codes), run on the CSV: every set's ROC and lift
    # curves, or actual by predicted, from the model the head fits
    from smui import util
    tmp = tempfile.mkdtemp(prefix='smui-predict-charts-')

    def tree_head(Q, rows, cls, extra=''):
        lines = Q.code('data', rows=rows, extra_imports=[pv.PLT, f'from sklearn.tree import {cls}'])
        lines.append(f'model = {cls}(max_depth=4, random_state=1{extra}).fit(X[train], y[train], sample_weight=None if w is None else w[train])')
        return '\n'.join(lines + pv.fitted_line(Q))

    runs = 0
    for label, Q, rows in [
            ('two levels, a Validation column, Freq', pv.prepare(T, 'cls', ['x1', 'x2', 'g'], validation='v', freq='f'), None),
            ('three levels, a validation portion, weight and Freq', pv.prepare(T, 'three', ['x1m', 'x2', 'gm'], portion=0.3, seed=5, weight='w', freq='f'), None),
            ('three levels, rows left out, a character Validation column', pv.prepare(T, 'three', ['x1', 'g'], validation='vt', rows=list(range(12, 236))), list(range(12, 236))),
            ('a continuous response, a Validation column, a weight', pv.prepare(T, 'y', ['x1', 'x2', 'g'], validation='v', weight='w'), None),
            ('a continuous response, rows left out', pv.prepare(T, 'y', ['x1m', 'gm'], rows=list(range(0, 200))), list(range(0, 200)))]:
        cat = Q.kind == 'categorical'
        head = tree_head(Q, rows, 'DecisionTreeClassifier' if cat else 'DecisionTreeRegressor')
        mdl = (DecisionTreeClassifier if cat else DecisionTreeRegressor)(max_depth=4, random_state=1).fit(Q.X[Q.train()], Q.target[Q.train()], sample_weight=None if Q.w is None else Q.w[Q.train()])
        rep = pv.report(Q, Q.proba(mdl, Q.X) if cat else mdl.predict(Q.X), head=head)
        check(f'graphs: {label}: the code of every set\'s graphs', sorted((k, sorted(v)) if isinstance(v, dict) else (k, None) for k, v in rep['plots'].items()),
              sorted([('head_code', None)] + ([('roc', sorted(rep['sets'])), ('lift', sorted(rep['sets']))] if cat else [('abp', sorted(rep['sets']))])))
        if rows is not None:
            drop = sorted(set(range(n)) - set(rows))
            check(f'graphs: {label}: the head leaves out the rows the report leaves out', f'df = df.drop(index={drop})   # the rows the report leaves out' in head, True)
        runs += check_shared_native(check, f'graphs: {label}', rep, T, tmp)
    # a curve of more than 400 points is thinned in the report: its points lie on the code's curve
    big_n = 900
    bx = rng.normal(0, 1, big_n)
    by_ = np.where(bx + rng.normal(0, 1, big_n) > 0, 'yes', 'no')
    Tb = table({'b': list(by_), 'bx': list(bx), 'bx2': list(rng.normal(0, 1, big_n))}, types={'b': 'nominal'}, levels={'b': ['no', 'yes']})
    Qb = pv.prepare(Tb, 'b', ['bx', 'bx2'])
    from sklearn.linear_model import LogisticRegression
    lr = LogisticRegression(max_iter=1000).fit(Qb.X, Qb.target)
    headb = '\n'.join(Qb.code('data', extra_imports=[pv.PLT, 'from sklearn.linear_model import LogisticRegression']) + ['model = LogisticRegression(max_iter=1000).fit(X, y)'] + pv.fitted_line(Qb))
    repb = pv.report(Qb, Qb.proba(lr, Qb.X), head=headb)
    check('graphs: 900 rows: the report\'s ROC curve is thinned to 400 points', max(len(c['fpr']) for c in repb['roc']), 400)
    runs += check_shared_native(check, 'graphs: 900 rows, a thinned ROC curve', repb, Tb, tmp)
    # a date factor: text in the CSV, the page's number (milliseconds since 1970) in the code
    days = (np.datetime64('2024-01-01') + rng.integers(0, 700, 150).astype('timedelta64[D]')).astype('datetime64[ms]').astype(np.int64).astype(float)
    Td = table({'yd': list(2 + 1e-9 * (days - days.mean()) + rng.normal(0, 0.3, 150)), 'day': list(days), 'k': list(rng.normal(0, 1, 150))})
    from smui import data as sdata
    sdata.TABLES[Td]['meta']['day']['format'] = {'kind': 'date'}
    Qd = pv.prepare(Td, 'yd', ['day', 'k'])
    rg = DecisionTreeRegressor(max_depth=3, random_state=0).fit(Qd.X, Qd.target)
    headd = util.dated_code('\n'.join(Qd.code('data', extra_imports=[pv.PLT, 'from sklearn.tree import DecisionTreeRegressor']) + ['model = DecisionTreeRegressor(max_depth=3, random_state=0).fit(X, y)'] + pv.fitted_line(Qd)), util.date_columns(Td))
    check('graphs: a date factor: the head turns its text back into the page\'s number', 'df["day"] = (pd.to_datetime(df["day"]) - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)' in headd, True)
    runs += check_shared_native(check, 'graphs: a date factor', pv.report(Qd, rg.predict(Qd.X), head=headd), Td, tmp)
    # Column Contributions' bars
    Qc = pv.prepare(T, 'y', ['x1m', 'x2', 'gm'])
    rt = DecisionTreeRegressor(max_depth=3, random_state=0).fit(Qc.X, Qc.target)
    con = pv.contributions(Qc, rt.feature_importances_, 'Importance', code=[f'groups = {json.dumps(Qc.groups)}   # the columns of X of each X column',
                                                                           'contrib = {c: float(model.feature_importances_[j].sum()) for c, j in groups.items()}'])
    headc = '\n'.join(Qc.code('data', extra_imports=[pv.PLT, 'from sklearn.tree import DecisionTreeRegressor']) + ['model = DecisionTreeRegressor(max_depth=3, random_state=0).fit(X, y)'])
    runs += check_contrib_native(check, 'graphs: a tree\'s importances', con, headc, T, tmp)
    check('graphs: every graph\'s code ran and drew the report\'s graph', runs, 24)

    return check.done()


if __name__ == '__main__':
    sys.exit(main())
