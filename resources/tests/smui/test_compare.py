#!/usr/bin/env python3
"""Analyze > Predictive Modeling > Model Comparison (resources/py/smui/compare.py),
through registry.dispatch as the page calls it, on tables of our own.

The Measures of Fit of every model in every group against scikit-learn's
metrics with the frequencies as sample weights (r2, MSE, MAE, MAPE, log
loss, accuracy, ROC AUC, the confusion matrix) and against the rows
repeated by their frequencies (the correlation), Entropy and Generalized
RSquare by their formulas (the constant model of each group's own shares);
the rows every model is measured on (a missing prediction leaves the row
out of all); the best of each measure; a probability column left out (1
minus the others) against the model given it; a column of predicted levels;
Model Averaging against the mean of the models; three levels; the ROC
curves against scikit-learn's roc_curve, the lift and gains by hand; the
AUC Comparison against DeLong et al.'s structural components computed
here from the pairs of rows (the rows repeated by their frequencies), and
the overall test against another set of contrasts; the Decision
Threshold's data (the groups as the validation sets, the counts at a
cut); the groups' value labels; the errors and notes; and every code block
(the measures, the AUC Comparison, each graph's matplotlib) run on a CSV
export of the table, giving the report's numbers.

    python3 resources/tests/smui/test_compare.py
"""
import contextlib
import io
import json
import math
import os
import tempfile

import numpy as np
import pandas as pd
from sklearn import metrics as skm

from backend import FAILED, Checks, call, data, table
from test_charts import run_snippet

check = Checks()
check('compare.py imports', FAILED.get('compare'), None)
tmp = tempfile.mkdtemp(prefix='smui-compare-')
SEP = '\n\n# ----\n'
COLORS = ['#2f6690', '#c46a12', '#3a7d44', '#b0413e', '#6c5b7b', '#1a8a78', '#8f7600', '#8c564b', '#b8428f', '#666666', '#107f8f', '#7b5bb5']


def frame(tid):
    """The table as File > Export CSV writes it."""
    t = data.TABLES[tid]
    return pd.DataFrame({k: (np.asarray(v, dtype=float) if t['meta'][k]['dataType'] == 'numeric' else pd.Series(list(v), dtype=object)) for k, v in t['cols'].items()})


def run_code(code, tid, name):
    """A code block run in a folder holding the table's CSV: the JSON lines it prints."""
    frame(tid).to_csv(os.path.join(tmp, f'{name}.csv'), index=False)
    here = os.getcwd()
    os.chdir(tmp)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            exec(code, {'__name__': '__main__'})
    finally:
        os.chdir(here)
    return [json.loads(ln) for ln in buf.getvalue().split('\n') if ln.startswith('{')]


def graph(r, kind, g, tid, name):
    figs, err = run_snippet(r['plots']['head_code'] + SEP + r['plots'][kind][g], frame(tid), name, tmp)
    return (figs[0] if figs and len(figs) == 1 else None), err


def M(key, label, kind, cols, creator=''):
    return {'key': key, 'label': label, 'creator': creator, 'kind': kind, 'columns': cols}


def close_all(label, got, want, tol=1e-10):
    ok = len(got) == len(want) and all((a is None and b is None) or (a is not None and b is not None and abs(a - b) <= tol * max(1.0, abs(b))) for a, b in zip(got, want))
    return check(label, ok, True) or print('      got ', got, '\n      want', want)


# =================================================================================================
# a continuous response
# =================================================================================================
rng = np.random.default_rng(914)
n = 900
x1, x2 = rng.normal(size=n), rng.uniform(-2, 2, n)
g = rng.choice(['a', 'b', 'c'], n)
y = 1 + 2 * x1 - x2 + 0.5 * (g == 'b') + rng.normal(size=n)
y[5] = 0.0                                  # a zero response: MAPE leaves it out
lin = 1 + 1.9 * x1 - 1.05 * x2 + 0.45 * (g == 'b') + rng.normal(scale=0.3, size=n)
tree = np.round(y * 0.8 + rng.normal(scale=0.9, size=n), 0)
bad = 1 + x1 + rng.normal(scale=0.5, size=n)
tree[7] = np.nan                            # a missing prediction: the row leaves every model
yv = y.copy()
yv[11] = np.nan                             # a missing response
sets = rng.choice(['Training', 'Validation', 'Test'], n, p=[0.6, 0.2, 0.2])
freq = rng.integers(1, 4, n).astype(float)
tid = table({'y': yv, 'Lin': lin, 'Tree': tree, 'Bad': bad, 'V': list(sets), 'f': freq, 'g': list(g), 'x1': x1},
            levels={'V': ['Training', 'Validation', 'Test']}, tid='cont')
models = [M('m1', 'Lin', 'pred', [{'name': 'Lin'}], 'Fit Least Squares'), M('m2', 'Tree', 'pred', [{'name': 'Tree'}], 'Partition'), M('m3', 'Bad', 'pred', [{'name': 'Bad'}])]
r = call('compare.fit', table=tid, y='y', models=models, group='V', freq='f', average=True, table_name='cont')
check('continuous: the groups in the column\'s order, a note per rows left out', (r['groups'], len(r['notes']) >= 3), (['Training', 'Validation', 'Test'], True))
check('... the rows left out: no response, a missing prediction, MAPE\'s zero', (any('1 rows with no y' in s for s in r['notes']), any('1 rows missing a model' in s for s in r['notes']), any('MAPE leaves out the 1 rows' in s for s in r['notes'])), (True, True, True))
keep = np.isfinite(yv) & np.isfinite(tree)
check('... every model on the same rows: 898', r['n_rows'], int(keep.sum()))
avg = (lin + tree + bad) / 3
fits = {'Lin': lin, 'Tree': tree, 'Bad': bad, 'Model Average': avg}
worst = {}
for row in r['measures']:
    m = keep & (sets == row['group'])
    yy, ff, ww = y[m], fits[row['label']][m], freq[m]
    want = {'rsquare': skm.r2_score(yy, ff, sample_weight=ww), 'rase': math.sqrt(skm.mean_squared_error(yy, ff, sample_weight=ww)),
            'mad': skm.mean_absolute_error(yy, ff, sample_weight=ww), 'mse': skm.mean_squared_error(yy, ff, sample_weight=ww),
            'mape': 100 * skm.mean_absolute_percentage_error(yy[yy != 0], ff[yy != 0], sample_weight=ww[yy != 0]),
            'corr': float(np.corrcoef(np.repeat(yy, ww.astype(int)), np.repeat(ff, ww.astype(int)))[0, 1]), 'n': float(ww.sum()),
            'medae': float(np.median(np.abs(np.repeat(yy - ff, ww.astype(int)))))}
    for k, v in want.items():
        worst[k] = max(worst.get(k, 0.0), abs(row[k] - v) / max(1.0, abs(v)))
for k, lab in (('rsquare', 'RSquare = sklearn r2_score (weights = Freq), about the group\'s own mean'), ('rase', 'RASE = √ sklearn MSE'), ('mad', 'AAE = sklearn MAE'),
               ('mse', 'MSE'), ('mape', 'MAPE = 100 sklearn MAPE on the rows with a response other than 0'), ('corr', 'Correlation = numpy\'s on the rows repeated by Freq'),
               ('n', 'Freq = the frequencies\' sum'), ('medae', 'Median Abs Error on the rows repeated by Freq')):
    check.near(f'continuous: {lab}, every model and group', worst[k], 0, 1e-10)
check('continuous: the models, the Model Average last', [x['label'] for x in r['models']], ['Lin', 'Tree', 'Bad', 'Model Average'])
check('continuous: the measure columns (JMP\'s, then MSE, MAPE, Correlation; more hidden)', [(c['label'], bool(c.get('hidden'))) for c in r['measure_columns']],
      [('RSquare', False), ('RASE', False), ('AAE', False), ('MSE', False), ('MAPE', False), ('Correlation', False), ('Freq', False),
       ('Mean Error', True), ('MPE', True), ('Median Abs Error', True), ('-LogLikelihood', True), ('SSE', True)])
# the best of each measure, found here
ok = True
for gi, gname in enumerate(r['groups']):
    rows = [x for x in r['measures'] if x['group'] == gname]
    for k, higher in (('rsquare', True), ('rase', False), ('mad', False), ('mape', False), ('corr', True), ('medae', False)):
        vals = [x[k] for x in rows]
        b = max(vals) if higher else min(vals)
        ok &= r['best'][str(gi)][k] == [x['model'] for x in rows if x[k] == b]
    ok &= 'n' not in r['best'][str(gi)] and 'me' not in r['best'][str(gi)]
check('continuous: the best of each measure within each group (not N, not the signed Mean Error)', ok, True)
# the code under the Measures of Fit
lines = run_code(r['code'], tid, 'cont')
key = {'RSquare': 'rsquare', 'RASE': 'rase', 'AAE': 'mad', 'MSE': 'mse', 'MAPE': 'mape', 'Correlation': 'corr', 'Freq': 'n'}
rep = {(x['group'], x['label']): x for x in r['measures']}
d = max(abs(ln[k] - rep[(ln['group'], ln['model'])][v]) / max(1.0, abs(rep[(ln['group'], ln['model'])][v])) for ln in lines for k, v in key.items())
check('continuous: the code prints every model in every group', sorted((ln['group'], ln['model']) for ln in lines), sorted(rep))
check.near('continuous: ... with the report\'s measures', d, 0, 1e-12)
# the graphs' code: actual by predicted and residual by row, every group
res = r['residuals']
for gi, gname in enumerate(r['groups']):
    for kind in ('abp', 'resid'):
        F, err = graph(r, kind, str(gi), tid, 'cont')
        lab = f'continuous: {kind} {gname}'
        check(f'{lab}: the code runs, one figure, ending in plt.show()', (err, F is not None, r['plots'][kind][str(gi)].rstrip().split('\n')[-1]), (None, True, 'plt.show()'))
        if not F:
            continue
        ax = F['axes'][0]
        idx = [i for i, s in enumerate(res['group']) if s == gi]
        want, got = [], [tuple(p) for sc in ax['scatter'] for p in sc['xy']]
        for m_ in r['models']:
            pr = res['predicted'][m_['key']]
            want += [(pr[i], res['actual'][i]) if kind == 'abp' else (res['rows'][i] + 1, res['actual'][i] - pr[i]) for i in idx]
        check.near(f'{lab}: every model\'s points, the page\'s', max(abs(a - b) for p, q in zip(got, want) for a, b in zip(p, q)) + abs(len(got) - len(want)), 0, 1e-12)
        check(f'{lab}: a colour per model (the Model Average in the text\'s), the legend beside', ([sc['colors'][0][:7] for sc in ax['scatter']], F['legend']),
              (COLORS[:3] + ['#352921'], ['Lin', 'Tree', 'Bad', 'Model Average']))
        check(f'{lab}: the titles, the size', (ax['title'], ax['xlabel'], ax['ylabel'], F['size']),
              (f'{"Actual by predicted" if kind == "abp" else "Residual by row"} {gname}', 'Predicted' if kind == 'abp' else 'Row', 'y' if kind == 'abp' else 'Residual', [4.8, 3.3]))

# no group, no frequency, some rows only (a By group): the code keeps those rows
rows = [i for i in range(n) if g[i] == 'a']
r2 = call('compare.fit', table=tid, y='y', models=models[:2], rows=rows, table_name='cont')
check('no Group: one group, no Group column in the code', (r2['groups'], 'gid = np.zeros(len(d), dtype=int)' in r2['code']), ([None], True))
m = keep & (g == 'a')
check.near('... RSquare of the rows given (no weights)', r2['measures'][0]['rsquare'], skm.r2_score(y[m], lin[m]), 1e-12)
lines = run_code(r2['code'], tid, 'cont')
check.near('... its code on the whole CSV keeps the report\'s rows', max(abs(ln['RSquare'] - x['rsquare']) for ln, x in zip(lines, r2['measures'])), 0, 1e-12)
check('... and says which', 'the rows of the report' in r2['code'] or 'the rows the report leaves out' in r2['code'], True)

# =================================================================================================
# a categorical response: probabilities, a left-out level, predicted levels, Model Averaging
# =================================================================================================
rng = np.random.default_rng(29)
n = 1200
x = rng.normal(size=n)
eta = 1.4 * x - 0.4
cls = np.where(rng.random(n) < 1 / (1 + np.exp(-eta)), 'yes', 'no')
pa = 1 / (1 + np.exp(-(1.3 * x - 0.3 + rng.normal(scale=0.4, size=n))))
pb = 1 / (1 + np.exp(-(0.7 * x + rng.normal(scale=0.9, size=n))))
pc = np.clip(0.5 + 0.3 * np.tanh(x) + rng.normal(scale=0.15, size=n), 0.01, 0.99)
most = np.where(pb >= 0.5, 'yes', 'no')
vnum = rng.choice([0.0, 1.0, 2.0], n, p=[0.6, 0.25, 0.15])
vtxt = np.array(['Training', 'Validation', 'Test'])[vnum.astype(int)]
freq = rng.integers(1, 4, n).astype(float)
cols = {'cls': list(cls), 'Prob[no]': 1 - pa, 'Prob[yes]': pa, 'Prob[yes] 2': pb, 'Prob[no] 3': 1 - pc, 'Prob[yes] 3': pc, 'Most': list(most),
        'V': list(vtxt), 'Vn': vnum, 'f': freq, 'x': x}
tid = table(cols, types={'Vn': 'nominal'}, levels={'V': ['Training', 'Validation', 'Test']}, tid='cat')
PA = M('a', 'Logistic', 'prob', [{'name': 'Prob[no]', 'level': 0}, {'name': 'Prob[yes]', 'level': 1}], 'Nominal Logistic Fit')
PB = M('b', 'Forest', 'prob', [{'name': 'Prob[yes] 2', 'level': 1}], 'Bootstrap Forest')
PC = M('c', 'Tree', 'prob', [{'name': 'Prob[no] 3', 'level': 0}, {'name': 'Prob[yes] 3', 'level': 1}], 'Partition')
PL = M('l', 'Most', 'level', [{'name': 'Most'}])
r = call('compare.fit', table=tid, y='cls', models=[PA, PB, PC, PL], group='V', freq='f', average=True, table_name='cat', plot={'level': 1})
check('categorical: the levels, the groups, the models', (r['levels'], r['groups'], [m_['label'] for m_ in r['models']]),
      (['no', 'yes'], ['Training', 'Validation', 'Test'], ['Logistic', 'Forest', 'Tree', 'Most', 'Model Average']))
check('... Forest\'s level without a column is 1 minus the other', next(m_ for m_ in r['models'] if m_['key'] == 'b').get('complement'), 'no')
check('... Model Averaging leaves out the predicted levels', (any('leaves out the models that give only a predicted level' in s for s in r['notes']), next(m_ for m_ in r['models'] if m_['label'] == 'Model Average')['of']), (True, ['a', 'b', 'c']))
Y = (cls == 'yes').astype(int)
P = {'Logistic': pa, 'Forest': pb, 'Tree': pc, 'Model Average': (pa + pb + pc) / 3}
worst = {}
for row in r['measures']:
    mk = vtxt == row['group']
    yy, ww = Y[mk], freq[mk]
    if row['label'] == 'Most':
        pred = (most[mk] == 'yes').astype(int)
        worst['level'] = max(worst.get('level', 0), abs(row['misclassification'] - (1 - skm.accuracy_score(yy, pred, sample_weight=ww))))
        check(f'categorical: the predicted levels ({row["group"]}): only the misclassification rate and N', sorted(k for k, v in row.items() if v is not None and k not in ('group', 'model', 'label', 'creator')), ['misclassification', 'n'])
        continue
    p1 = P[row['label']][mk]
    pr = np.column_stack([1 - p1, p1])
    pt = pr[np.arange(len(yy)), yy]
    N = ww.sum()
    ll = np.sum(ww * np.log(pt))
    share = np.array([ww[yy == 0].sum(), ww[yy == 1].sum()]) / N
    ll0 = np.sum(ww * np.log(share[yy]))
    want = {'mean_neg_log_p': skm.log_loss(yy, pr, sample_weight=ww, labels=[0, 1]), 'entropy_rsquare': 1 - ll / ll0,
            'generalized_rsquare': (1 - math.exp(2 * (ll0 - ll) / N)) / (1 - math.exp(2 * ll0 / N)),
            'misclassification': 1 - skm.accuracy_score(yy, pr.argmax(1), sample_weight=ww), 'auc': skm.roc_auc_score(yy, p1, sample_weight=ww),
            'rase': math.sqrt(np.sum(ww * (1 - pt) ** 2) / N), 'mad': np.sum(ww * (1 - pt)) / N, 'n': N}
    for k, v in want.items():
        worst[k] = max(worst.get(k, 0.0), abs(row[k] - v))
for k, lab in (('mean_neg_log_p', 'Mean -Log p = sklearn log_loss (weights = Freq)'), ('entropy_rsquare', 'Entropy RSquare, against the group\'s own shares'),
               ('generalized_rsquare', 'Generalized RSquare (Nagelkerke)'), ('misclassification', 'Misclassification = 1 - sklearn accuracy'), ('auc', 'AUC = sklearn roc_auc_score'),
               ('rase', 'RASE of 1 - p(actual)'), ('mad', 'Mean Abs Dev of 1 - p(actual)'), ('n', 'N = the frequencies\' sum'), ('level', 'the predicted levels\' misclassification = 1 - sklearn accuracy')):
    check.near(f'categorical: {lab}, every model and group', worst[k], 0, 1e-10)
# the confusion matrices
ok = True
for key, pred_of in (('a', lambda mk: (pa[mk] > 0.5).astype(int)), ('l', lambda mk: (most[mk] == 'yes').astype(int))):
    for cm in r['confusion'][key]:
        mk = vtxt == cm['set']
        want = skm.confusion_matrix(Y[mk], pred_of(mk), sample_weight=freq[mk], labels=[0, 1])
        ok &= np.allclose(cm['matrix'], want, atol=1e-12)
check('categorical: the confusion matrices = sklearn\'s (rows by Freq), of probabilities and of predicted levels', ok, True)
# a left-out level against the model given both columns
r1 = call('compare.fit', table=tid, y='cls', models=[M('b2', 'Forest', 'prob', [{'name': 'Prob[yes] 2', 'level': 1}])], group='V', freq='f', table_name='cat')
tid2 = table({**cols, 'Prob[no] 2': 1 - pb}, types={'Vn': 'nominal'}, levels={'V': ['Training', 'Validation', 'Test']}, tid='cat2')
r1b = call('compare.fit', table=tid2, y='cls', models=[M('b2', 'Forest', 'prob', [{'name': 'Prob[no] 2', 'level': 0}, {'name': 'Prob[yes] 2', 'level': 1}])], group='V', freq='f', table_name='cat2')
check.near('a level without its column = the model given 1 minus the other', max(abs(a[k] - b[k]) for a, b in zip(r1['measures'], r1b['measures']) for k in ('entropy_rsquare', 'misclassification', 'auc', 'rase')), 0, 1e-12)
# the best of each measure
ok = True
for gi, gname in enumerate(r['groups']):
    rows = [x_ for x_ in r['measures'] if x_['group'] == gname]
    for k, higher in (('entropy_rsquare', True), ('mean_neg_log_p', False), ('misclassification', False), ('auc', True)):
        vals = [(x_['model'], x_[k]) for x_ in rows if x_.get(k) is not None]
        b = max(v for _, v in vals) if higher else min(v for _, v in vals)
        ok &= sorted(r['best'][str(gi)][k]) == sorted(mm for mm, v in vals if abs(v - b) <= 1e-12 * max(1, abs(b)))
check('categorical: the best of each measure within each group (the predicted levels too, where they have one)', ok, True)
# the code under the Measures of Fit
lines = run_code(r['code'], tid, 'cat')
key = {'Entropy RSquare': 'entropy_rsquare', 'Generalized RSquare': 'generalized_rsquare', 'Mean -Log p': 'mean_neg_log_p', 'RASE': 'rase', 'Mean Abs Dev': 'mad',
       'Misclassification Rate': 'misclassification', 'N': 'n', 'AUC': 'auc'}
rep = {(x_['group'], x_['label']): x_ for x_ in r['measures']}
d = max(abs(ln[k] - rep[(ln['group'], ln['model'])][v]) for ln in lines for k, v in key.items() if k in ln)
check('categorical: the code prints every model in every group', sorted((ln['group'], ln['model']) for ln in lines), sorted(rep))
check.near('categorical: ... with the report\'s measures', d, 0, 1e-12)

# ---- ROC, lift and gains: against sklearn's roc_curve and by hand ------------------------------------------
def subset(want, got, tol=1e-12):
    i = 0
    for w_ in want:
        while i < len(got) and not (abs(got[i][0] - w_[0]) <= tol and abs(got[i][1] - w_[1]) <= tol):
            i += 1
        if i == len(got):
            return False
        i += 1
    return True


ok_roc, ok_lift = True, True
for key_, lab in (('a', 'Logistic'), ('b', 'Forest'), ('Model Average', 'Model Average')):
    for c in r['roc'][key_]:
        mk = vtxt == c['set']
        j = r['levels'].index(c['level'])
        s = P[lab][mk] if j == 1 else 1 - P[lab][mk]
        fpr, tpr, _ = skm.roc_curve(Y[mk] == j, s, sample_weight=freq[mk], drop_intermediate=False)
        ok_roc &= subset(list(zip(c['fpr'], c['tpr'])), list(zip(fpr, tpr))) and abs(c['auc'] - skm.roc_auc_score(Y[mk] == j, s, sample_weight=freq[mk])) < 1e-12
    for c in r['lift'][key_]:
        mk = vtxt == c['set']
        j = r['levels'].index(c['level'])
        s = P[lab][mk] if j == 1 else 1 - P[lab][mk]
        o = np.argsort(-s, kind='mergesort')
        cw = np.cumsum(freq[mk][o])
        hits = np.cumsum(np.where(Y[mk][o] == j, freq[mk][o], 0.0))
        base = hits[-1] / cw[-1]
        pts = list(zip(cw / cw[-1], hits / cw / base))
        ok_lift &= subset(list(zip(c['portion'], c['lift'])), pts) and abs(c['lift'][-1] - 1) < 1e-12 and abs(c['gains'][-1] - 1) < 1e-12 and subset(list(zip(c['portion'], c['gains'])), list(zip(cw / cw[-1], hits / hits[-1])))
check('ROC curves: every model\'s, each group and level, on sklearn\'s roc_curve (weights = Freq), its AUC sklearn\'s', ok_roc, True)
ok_pr = True
for key_, lab in (('a', 'Logistic'), ('b', 'Forest'), ('Model Average', 'Model Average')):
    for c in r['pr'][key_]:
        mk = vtxt == c['set']
        j = r['levels'].index(c['level'])
        s_ = P[lab][mk] if j == 1 else 1 - P[lab][mk]
        prec, rec, _ = skm.precision_recall_curve(Y[mk] == j, s_, sample_weight=freq[mk])
        ok_pr &= subset(list(zip(c['recall'], c['precision'])), list(zip(rec[::-1], prec[::-1]))) and abs(c['ap'] - skm.average_precision_score(Y[mk] == j, s_, sample_weight=freq[mk])) < 1e-12
        ok_pr &= abs(c['base'] - freq[mk][Y[mk] == j].sum() / freq[mk].sum()) < 1e-12
check('precision-recall curves: on sklearn\'s precision_recall_curve (weights = Freq), the average precision sklearn\'s, the level\'s rate', ok_pr, True)
check('lift and gains: the rows by probability, by hand; both end at 1', ok_lift, True)
for gi, gname in enumerate(r['groups']):
    for kind in ('roc', 'lift', 'gains', 'pr'):
        F, err = graph(r, kind, str(gi), tid, 'cat')
        lab = f'categorical: {kind} {gname}'
        check(f'{lab}: the code runs, one figure', (err, F is not None), (None, True))
        if not F:
            continue
        ax = F['axes'][0]
        names = ['Logistic', 'Forest', 'Tree', 'Model Average']
        keys = ['a', 'b', 'c', 'Model Average']
        src = r['roc'] if kind == 'roc' else r['pr'] if kind == 'pr' else r['lift']
        ok = True
        for k_, nm in zip(keys, names):
            c = next(c for c in src[k_] if c['set'] == gname and c['level'] == 'yes')
            leg = f'{nm} ({c["auc"]:.3f})' if kind == 'roc' else f'{nm} (AP {c["ap"]:.3f})' if kind == 'pr' else nm
            ln = next((q for q in ax['lines'] if q['label'] == leg), None)
            xs, ys = (c['fpr'], c['tpr']) if kind == 'roc' else (c['recall'], c['precision']) if kind == 'pr' else (c['portion'], c['lift'] if kind == 'lift' else c['gains'])
            ok &= ln is not None and subset(list(zip(xs, ys)), list(zip(ln['x'], ln['y'])), 1e-9)
        check(f'{lab}: every model\'s curve holds the page\'s points, the legend has the AUCs', (ok, len(F['legend'])), (True, 4))
        check(f'{lab}: the title, the size', (ax['title'], F['size']), (f'{"ROC" if kind == "roc" else "Lift" if kind == "lift" else "Precision Recall" if kind == "pr" else "Cum Gains"} {gname} yes', [4.8, 3.3]))
        if kind == 'pr':
            base = next(c for c in r['pr']['a'] if c['set'] == gname and c['level'] == 'yes')['base']
            check(f'{lab}: the dotted line at the level\'s rate', any(q['ls'] == ':' and abs(q['y'][0] - base) < 1e-12 and q['y'][0] == q['y'][1] for q in ax['lines']), True)

# ---- AUC Comparison: DeLong et al. from the pairs of rows -------------------------------------------------
def delong_pairs(scores, pos):
    """DeLong, DeLong and Clarke-Pearson (1988), written from the paper: psi of every (positive, negative) pair."""
    X = [s[pos] for s in scores]
    Yn = [s[~pos] for s in scores]
    m, k = pos.sum(), (~pos).sum()
    theta, V10, V01 = [], [], []
    for xr, yr in zip(X, Yn):
        psi = (xr[:, None] > yr[None, :]) + 0.5 * (xr[:, None] == yr[None, :])
        theta.append(psi.mean())
        V10.append(psi.mean(axis=1))
        V01.append(psi.mean(axis=0))
    S10, S01 = np.cov(np.array(V10)), np.cov(np.array(V01))
    return np.array(theta), S10 / m + S01 / k


worst_t = worst_s = worst_p = worst_o = 0.0
for a_ in r['auc']:
    mk = vtxt == a_['group']
    rep_ = np.repeat(np.arange(n)[mk], freq[mk].astype(int))   # every row as many times as its frequency
    pos = Y[rep_] == 1
    th, S = delong_pairs([pa[rep_], pb[rep_], pc[rep_], ((pa + pb + pc) / 3)[rep_]], pos)
    res_ = a_['levels'][1]
    worst_t = max(worst_t, max(abs(e['auc'] - t_) for e, t_ in zip(res_['each'], th)))
    worst_s = max(worst_s, max(abs(e['se'] - math.sqrt(S[i, i])) for i, e in enumerate(res_['each'])))
    k = 0
    for i in range(4):
        for j in range(i + 1, 4):
            pr_ = res_['pairs'][k]
            k += 1
            z = (th[i] - th[j]) / math.sqrt(S[i, i] + S[j, j] - 2 * S[i, j])
            worst_p = max(worst_p, abs(pr_['chisq'] - z * z) / (z * z))
    C = np.array([[1, -1, 0, 0], [1, 0, -1, 0], [1, 0, 0, -1]], dtype=float)   # each against the first: another set of contrasts
    c = C @ th
    chi = float(c @ np.linalg.solve(C @ S @ C.T, c))
    worst_o = max(worst_o, abs(res_['overall']['chisq'] - chi) / chi)
    check(f'AUC Comparison {a_["group"]}: 3 degrees of freedom for 4 AUCs', res_['overall']['df'], 3)
check.near('AUC Comparison: each AUC = the pairs\' mean of psi (the rows repeated by Freq)', worst_t, 0, 1e-12)
check.near('... each standard error = DeLong\'s from the pairs', worst_s, 0, 1e-12)
check.near('... each pair\'s chi-square = z² of the difference', worst_p, 0, 1e-9)
check.near('... the test that all are equal = the chi-square of other contrasts (each against the first)', worst_o, 0, 1e-9)
e0 = r['auc'][1]['levels'][1]['each'][0]
check.near('... the interval is AUC ± z·SE at the report\'s α', e0['upper'] - e0['auc'], 1.959963984540054 * e0['se'], 1e-12)
check.near('... the other level\'s AUC is the same (the curves mirror)', r['auc'][1]['levels'][0]['each'][0]['auc'], e0['auc'], 1e-12)
lines = run_code(r['auc_code']['1'], tid, 'cat')
each = {(ln['group'], ln['model']): ln for ln in lines if 'model' in ln}
d = max(abs(each[(a_['group'], e['model'])][k] - e[v]) for a_ in r['auc'] for e in a_['levels'][1]['each'] for k, v in (('AUC', 'auc'), ('Std Error', 'se'), ('Lower', 'lower')))
check.near('AUC Comparison: its code (the pairs of rows, another algorithm) gives the report\'s', d, 0, 1e-10)
tests = [ln for ln in lines if ln.get('test')]
check.near('... and the same overall tests', max(abs(t_['ChiSquare'] - a_['levels'][1]['overall']['chisq']) / a_['levels'][1]['overall']['chisq'] for t_, a_ in zip(tests, r['auc'])), 0, 1e-8)

# ---- the Decision Threshold's data: the groups as the validation sets ----------------------------------------
from smui import predictive as pv   # noqa: E402
if hasattr(pv, 'threshold'):
    rt_ = call('compare.fit', table=tid, y='cls', models=[PA, PB, PL], group='V', freq='f', threshold=True, table_name='cat')
    D = rt_['threshold']
    check('Decision Threshold: the sets are the groups, every model with probabilities', (D['sets'], [m_['label'] for m_ in D['models']]), (['Training', 'Validation', 'Test'], ['Logistic', 'Forest']))
    idx = np.asarray(D['points']['rows'])
    ok = D['points']['set'] == vnum[idx].astype(int).tolist() and D['points']['actual'] == Y[idx].tolist() and np.allclose(D['points']['w'], freq[idx])
    for mm, p1 in (('Logistic', pa), ('Forest', pb)):
        ent = next(m_ for m_ in D['models'] if m_['label'] == mm)
        ok &= np.allclose(ent['p'], p1[idx], rtol=0, atol=1e-15) and 'p0' not in ent   # the first level's is 1 minus the second's
    check('... every row: its set, level, frequency and each model\'s probability of yes', bool(ok), True)
    ent = D['models'][0]
    for s_ in (0, 1, 2):
        mk = np.asarray(D['points']['set']) == s_
        pp, yy, ww = np.asarray(ent['p'])[mk], np.asarray(D['points']['actual'])[mk], np.asarray(D['points']['w'])[mk]
        got = pv.counts_at(pv.cut_table(pp, yy == 1, ww), 0.5)
        want = [ww[(pp >= 0.5) & (yy == 1)].sum(), ww[(pp >= 0.5) & (yy == 0)].sum(), ww[(pp < 0.5) & (yy == 1)].sum(), ww[(pp < 0.5) & (yy == 0)].sum()]
        ok &= np.allclose(got, want, atol=1e-9)
    check('... the counts at a cut of 0.5 from them, by hand (rows by Freq)', bool(ok), True)
    ns = {}
    frame(tid).to_csv(os.path.join(tmp, 'cat.csv'), index=False)
    here = os.getcwd()
    os.chdir(tmp)
    try:
        exec(D['plots']['head_code'] + '\n' + D['plots']['select'], ns)
    finally:
        os.chdir(here)
    idx = np.asarray(D['points']['rows'])
    check('... its code\'s head makes y, sets, w and fitted[model] of the report\'s rows',
          (list(ns['d'].index) == idx.tolist(), ns['y'].tolist() == D['points']['actual'], ns['sets'].tolist() == D['points']['set'],
           np.allclose(ns['w'], freq[idx]), np.allclose(ns['fitted']['Forest'][:, 1], np.asarray(D['models'][1]['p']))), (True, True, True, True, True))
    check('... the code names each model\'s probabilities', [m_.get('code') for m_ in D['models']], [['fitted["Logistic"]'], ['fitted["Forest"]']])
    rn = call('compare.fit', table=tid, y='cls', models=[PA], group='Vn', threshold=True, table_name='cat')
    check('... a numeric validation column (0, 1, 2) is its sets too', rn['threshold']['sets'], ['Training', 'Validation', 'Test'])
    rn = call('compare.fit', table=tid, y='cls', models=[PA], threshold=True, table_name='cat')
    check('... no Group: every row one set, with a note', (rn['threshold']['sets'], 'every row is in one set' in rn.get('threshold_note', '')), (['Training'], True))
    tid3 = table({**cols, 'g': list(rng.choice(['north', 'south'], n))}, types={'Vn': 'nominal'}, tid='cat3')
    rn = call('compare.fit', table=tid3, y='cls', models=[PA], group='g', threshold=True, table_name='cat3')
    check('... another Group: no Decision Threshold, and why', (rn.get('threshold'), 'validation column' in rn.get('threshold_note', '')), (None, True))
else:
    check('predictive.threshold is there (WP3)', False, True)

# ---- value labels name the groups; three levels ----------------------------------------------------------------
meta = data.TABLES[tid]['meta']['Vn']
meta['valueLabels'] = [[0.0, 'Training'], [1.0, 'Validation'], [2.0, 'Test']]
rl = call('compare.fit', table=tid, y='cls', models=[PA, PB], group='Vn', freq='f', table_name='cat')
check('the Group column\'s value labels name the groups (data.level_label)', rl['groups'], ['Training', 'Validation', 'Test'] if hasattr(data, 'level_label') else ['0', '1', '2'])
text_ = {(x_['group'], x_['model']): x_ for x_ in r['measures']}
check.near('... the same measures as the text column\'s groups', max(abs(x_['entropy_rsquare'] - text_[(x_['group'], x_['model'])]['entropy_rsquare']) for x_ in rl['measures']), 0, 1e-12)
lines = run_code(rl['code'], tid, 'cat')
check('... and the code prints the labels as the groups', sorted({ln['group'] for ln in lines}), sorted(rl['groups']))
meta.pop('valueLabels')

rng = np.random.default_rng(3)
n3 = 700
z = rng.normal(size=(n3, 2))
lp = np.column_stack([np.zeros(n3), 1.2 * z[:, 0], -0.8 * z[:, 0] + z[:, 1]])
pr3 = np.exp(lp) / np.exp(lp).sum(1, keepdims=True)
u = rng.random(n3)
grade = np.array(['lo', 'mid', 'hi'])[(u[:, None] > np.cumsum(pr3, 1)).sum(1)]
noisy = np.exp(lp * 0.7) / np.exp(lp * 0.7).sum(1, keepdims=True)
tid = table({'grade': list(grade), 'Prob[lo]': pr3[:, 0], 'Prob[mid]': pr3[:, 1], 'Prob[hi]': pr3[:, 2], 'N[lo]': noisy[:, 0], 'N[hi]': noisy[:, 2]},
            types={'grade': 'ordinal'}, levels={'grade': ['lo', 'mid', 'hi']}, tid='three')
r3 = call('compare.fit', table=tid, y='grade', table_name='three', models=[
    M('t', 'True', 'prob', [{'name': 'Prob[lo]', 'level': 0}, {'name': 'Prob[mid]', 'level': 1}, {'name': 'Prob[hi]', 'level': 2}]),
    M('n', 'Noisy', 'prob', [{'name': 'N[lo]', 'level': 0}, {'name': 'N[hi]', 'level': 2}])])
Yg = np.array([{'lo': 0, 'mid': 1, 'hi': 2}[v] for v in grade])
check('three levels: no AUC column', ([c['key'] for c in r3['measure_columns']].count('auc'), r3['levels']), (0, ['lo', 'mid', 'hi']))
check.near('three levels: Mean -Log p = sklearn log_loss', r3['measures'][0]['mean_neg_log_p'], skm.log_loss(Yg, pr3, labels=[0, 1, 2]), 1e-12)
check.near('... the middle level left out is 1 minus the others', r3['measures'][1]['mean_neg_log_p'], skm.log_loss(Yg, np.column_stack([noisy[:, 0], 1 - noisy[:, 0] - noisy[:, 2], noisy[:, 2]]), labels=[0, 1, 2]), 1e-12)
check.near('... the misclassification rate', r3['measures'][0]['misclassification'], 1 - skm.accuracy_score(Yg, pr3.argmax(1)), 1e-12)
check('... ROC and lift curves of every level, AUC Comparison of every level', (len(r3['roc']['t']), len(r3['lift']['t']), len(r3['auc'][0]['levels'])), (3, 3, 3))
lines = run_code(r3['code'], tid, 'three')
check.near('... its code', max(abs(ln['Mean -Log p'] - x_['mean_neg_log_p']) for ln, x_ in zip(lines, r3['measures'])), 0, 1e-12)

# ---- a numeric 0/1 response, its levels named by value labels -------------------------------------------------------
rng = np.random.default_rng(71)
n4 = 500
z4 = rng.normal(size=n4)
y01 = (z4 + rng.normal(size=n4) > 0).astype(float)
q = 1 / (1 + np.exp(-1.5 * z4))
tid01 = table({'buy': y01, 'Prob[0]': 1 - q, 'Prob[1]': q, 'Most Likely buy': (q >= 0.5).astype(float)}, types={'buy': 'nominal', 'Most Likely buy': 'nominal'}, tid='num01')
data.TABLES[tid01]['meta']['buy']['valueLabels'] = [[0.0, 'no'], [1.0, 'yes']]
r7 = call('compare.fit', table=tid01, y='buy', table_name='num01', models=[M('p', 'Logistic', 'prob', [{'name': 'Prob[0]', 'level': 0}, {'name': 'Prob[1]', 'level': 1}]),
                                                                          M('l', 'Most Likely buy', 'level', [{'name': 'Most Likely buy'}])])
check('a numeric 0/1 response: its levels by their value labels', r7['levels'], ['no', 'yes'] if hasattr(data, 'level_label') else ['0', '1'])
check.near('... AUC = sklearn\'s', r7['measures'][0]['auc'], skm.roc_auc_score(y01, q), 1e-12)
check.near('... a numeric column of predicted levels', r7['measures'][1]['misclassification'], float(np.mean((q >= 0.5) != (y01 == 1))), 1e-12)
lines = run_code(r7['code'], tid01, 'num01')
check.near('... its code reads the numbers from the CSV', max(abs(ln['Misclassification Rate'] - x_['misclassification']) for ln, x_ in zip(lines, r7['measures'])), 0, 1e-12)
data.TABLES[tid01]['meta']['buy'].pop('valueLabels')

# ---- errors and what is left out ----------------------------------------------------------------------------------
def error(**kw):
    try:
        call('compare.fit', **kw)
        return None
    except Exception as e:
        return str(e)


tid = 'three'
check('errors: Group is the response', 'both a role column' in (error(table=tid, y='grade', group='grade', models=[M('t', 'T', 'prob', [{'name': 'Prob[lo]', 'level': 0}, {'name': 'Prob[mid]', 'level': 1}])]) or ''), True)
check('errors: a continuous response takes predicted values', 'continuous response takes' in (error(table='cont', y='y', models=[M('t', 'T', 'prob', [{'name': 'Lin', 'level': 0}])]) or ''), True)
r4 = call('compare.fit', table=tid, y='grade', models=[M('t', 'True', 'prob', [{'name': 'Prob[lo]', 'level': 0}, {'name': 'Prob[mid]', 'level': 1}, {'name': 'Prob[hi]', 'level': 2}]),
                                                        M('o', 'One', 'prob', [{'name': 'N[lo]', 'level': 0}])], table_name='three')
check('a model with two levels\' columns missing is left out, with a note', ([m_['label'] for m_ in r4['models']], any('One (no probability column for mid, hi' in s for s in r4['notes'])), (['True'], True))
check('... and alone it is an error', 'no model is left' in (error(table=tid, y='grade', models=[M('o', 'One', 'prob', [{'name': 'N[lo]', 'level': 0}])]) or ''), True)
check('errors: a column of predicted levels that are not levels of Y', 'not levels of grade' in (error(table=tid, y='grade', models=[M('l', 'L', 'level', [{'name': 'Prob[lo]'}])]) or ''), True)
r5 = call('compare.fit', table=tid, y='grade', models=[M('t', 'True', 'prob', [{'name': 'Prob[lo]', 'level': 0}, {'name': 'Prob[mid]', 'level': 1}, {'name': 'Prob[hi]', 'level': 2}])], average=True, table_name='three')
check('Model Averaging with one model: a note, no average', ([m_['label'] for m_ in r5['models']], any('needs two models' in s for s in r5['notes'])), (['True'], True))
r6 = call('compare.fit', table=tid, y='grade', table_name='three', models=[M('t', 'Model Average', 'prob', [{'name': 'Prob[lo]', 'level': 0}, {'name': 'Prob[mid]', 'level': 1}, {'name': 'Prob[hi]', 'level': 2}]),
                                                                        M('n', 'Noisy', 'prob', [{'name': 'N[lo]', 'level': 0}, {'name': 'N[hi]', 'level': 2}])], average=True)
check('a saved Model Average among the models: the new one is named apart', [m_['label'] for m_ in r6['models']], ['Model Average', 'Noisy', 'Model Average (2)'])
lines = run_code(r6['code'], tid, 'three')
check('... and its code keeps both', sorted({ln['model'] for ln in lines}), ['Model Average', 'Model Average (2)', 'Noisy'])

raise SystemExit(check.done())
