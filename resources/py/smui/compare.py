"""Analyze > Predictive Modeling > Model Comparison.

JMP Pro's Model Comparison: the predictions that models have saved to the
table are compared on the same rows. For a continuous response a model is
a column of predicted values; for a categorical one, its probability
columns (Prob[level], one per level; the one level without a column is 1
minus the others) or a column of the levels it predicts. The page groups
the columns into models (by their names and the report their notes name)
and sends them here as

    models = [{'key', 'label', 'creator', 'kind': 'pred' | 'prob' | 'level',
               'columns': [{'name', 'level'}]}]   level: the index into the
                                                  response's levels (prob)

Every model is measured on the rows that have the response, the group,
the frequency and every model's prediction, in each group of the Group
column (usually the validation column: Training, Validation, Test) on its
own, as JMP evaluates each group separately: RSquare about the group's own
mean, and Entropy RSquare against the group's own shares of the levels.
The measures, ROC and lift curves and confusion matrices are
predictive.py's (measures, roc, lift, confusion), those every predictive
platform here reports; each group is a set of its own there. Beyond JMP's
measures a continuous response gets MSE, MAPE and the correlation of the
actual and predicted values (Klimberg ch. 14, Shmueli et al. ch. 5).

AUC Comparison is DeLong, DeLong and Clarke-Pearson's (1988) nonparametric
covariance of correlated AUCs, a row counted by its frequency. Model
Averaging (JMP's) is one more model: the mean of the models' predictions,
or of their probabilities of each level.
"""
import json
import math

import numpy as np
import pandas as pd
from scipy import stats

from . import data
from . import predictive as pv
from .registry import api
from .util import code_head

AVERAGE = 'Model Average'
HIGHER = {'rsquare', 'corr', 'entropy_rsquare', 'generalized_rsquare', 'auc'}
UNRANKED = {'n', 'neg_loglik', 'sse', 'me', 'mpe'}
# each model's colour in the graphs' code, in the models' order (smui-p-compare.js LIGHT)
COLORS = ['#2f6690', '#c46a12', '#3a7d44', '#b0413e', '#6c5b7b', '#1a8a78', '#8f7600', '#8c564b', '#b8428f', '#666666', '#107f8f', '#7b5bb5']
AVG_COLOR = '#352921'


def measure_columns(kind, two_levels):
    """The Measures of Fit table's measure columns, as JMP names them (and the extra ones)."""
    d4 = {'fmt': 'num', 'digits': 4}
    if kind == 'continuous':
        return [{'key': 'rsquare', 'label': 'RSquare', **d4}, {'key': 'rase', 'label': 'RASE', **d4}, {'key': 'mad', 'label': 'AAE', **d4},
                {'key': 'mse', 'label': 'MSE', **d4}, {'key': 'mape', 'label': 'MAPE', **d4}, {'key': 'corr', 'label': 'Correlation', **d4},
                {'key': 'n', 'label': 'Freq', 'fmt': 'num'},
                {'key': 'me', 'label': 'Mean Error', **d4, 'hidden': True}, {'key': 'mpe', 'label': 'MPE', **d4, 'hidden': True},
                {'key': 'medae', 'label': 'Median Abs Error', **d4, 'hidden': True},
                {'key': 'neg_loglik', 'label': '-LogLikelihood', **d4, 'hidden': True}, {'key': 'sse', 'label': 'SSE', **d4, 'hidden': True}]
    cols = [{'key': 'entropy_rsquare', 'label': 'Entropy RSquare', **d4}, {'key': 'generalized_rsquare', 'label': 'Generalized RSquare', **d4},
            {'key': 'mean_neg_log_p', 'label': 'Mean -Log p', **d4}, {'key': 'rase', 'label': 'RASE', **d4}, {'key': 'mad', 'label': 'Mean Abs Dev', **d4},
            {'key': 'misclassification', 'label': 'Misclassification Rate', **d4}]
    if two_levels:
        cols.append({'key': 'auc', 'label': 'AUC', **d4})
    cols += [{'key': 'n', 'label': 'N', 'fmt': 'num'}, {'key': 'neg_loglik', 'label': '-LogLikelihood', **d4, 'hidden': True}]
    return cols


def _prepared(kind, target, levels, labels, w, index):
    """One group as predictive.py's Prepared: every row in the one set it measures (Training there)."""
    P = pv.Prepared()
    P.kind = kind
    P.target = target
    P.levels, P.labels = list(levels), list(labels)
    P.sets = np.zeros(len(target), dtype=int)
    P.w = w
    P.freq = w
    P.index = np.asarray(index, dtype=int)
    return P


def _wcorr(a, b, w):
    """The correlation of a and b, each row counted w times."""
    ma, mb = np.sum(w * a) / np.sum(w), np.sum(w * b) / np.sum(w)
    sab, saa, sbb = np.sum(w * (a - ma) * (b - mb)), np.sum(w * (a - ma) ** 2), np.sum(w * (b - mb) ** 2)
    return float(sab / math.sqrt(saa * sbb)) if saa > 0 and sbb > 0 else None


def _extra(y, f, w, m):
    """MSE and the correlation of actual and predicted added to m (predictive.measures' row); MAPE too, over the rows
    whose response is not 0, when measures() has not given it."""
    n = float(np.sum(w))
    e = y - f
    m['mse'] = float(np.sum(w * e * e) / n)
    if 'mape' not in m:
        nz = y != 0
        m['mape'] = float(100 * np.sum(w[nz] * np.abs(e[nz] / y[nz])) / np.sum(w[nz])) if nz.any() else None
    m['corr'] = _wcorr(y, f, w)
    return m


def _thin(n, most):
    if n <= most:
        return np.arange(n)
    return np.unique(np.round(np.linspace(0, n - 1, most)).astype(int))


def precision_recall(P, fitted, most=200):
    """Per level: the precision-recall curve of the level against the others by its probability (JMP's Precision
    Recall Curve): at each cut, highest first (tied values together), the recall (the share of the level's rows
    called it) and the precision (the share of the rows called it that are), from recall 0 at precision 1, as
    scikit-learn's precision_recall_curve ends it; and the average precision, the sum of each step in recall
    times the precision there (scikit-learn's average_precision_score). Rows count by their Weight x Freq."""
    out = []
    fitted = np.asarray(fitted, dtype=float)
    y, w = P.target, P.weights()
    for j, lab in enumerate(P.labels):
        pos = y == j
        Pw = float(w[pos].sum())
        if Pw <= 0 or not (~pos).any():
            continue
        o = np.argsort(-fitted[:, j], kind='mergesort')
        s = fitted[o, j]
        tp = np.cumsum(np.where(pos[o], w[o], 0.0))
        fp = np.cumsum(np.where(pos[o], 0.0, w[o]))
        last = np.r_[s[1:] != s[:-1], True]   # the end of each run of equal values
        tp, fp = tp[last], fp[last]
        rec, prec = tp / Pw, tp / (tp + fp)
        ap = float(np.sum(np.diff(np.r_[0.0, rec]) * prec))
        xs, ys = np.r_[0.0, rec], np.r_[1.0, prec]
        keep = _thin(len(xs), most)
        out.append({'set': SETS0, 'level': lab, 'recall': xs[keep].tolist(), 'precision': ys[keep].tolist(), 'ap': ap, 'base': Pw / float(w.sum())})
    return out


SETS0 = pv.SETS[0]


def _best(values, key):
    """The models with the best value of a measure (ties within rounding)."""
    ok = [(k, v) for k, v in values if v is not None and np.isfinite(v)]
    if not ok:
        return []
    b = max(v for _, v in ok) if key in HIGHER else min(v for _, v in ok)
    return [k for k, v in ok if abs(v - b) <= 1e-12 * max(1.0, abs(b))]


# ---------------------------------------------------------------------------
# DeLong, DeLong and Clarke-Pearson (1988)
# ---------------------------------------------------------------------------

def delong(scores, pos, w=None):
    """The AUCs of several scores of the same rows (each row's score of the
    positive class; pos marks the positive rows) and their covariance
    matrix by DeLong et al.'s structural components: V10 of a positive row
    is the share of the negative rows it outscores (a tie counts half),
    V01 of a negative row the share of positive rows that outscore it, and
    S = S10/m + S01/n with S10, S01 their covariance matrices. w: each row's
    frequency (a row counts as that many rows)."""
    pos = np.asarray(pos, dtype=bool)
    w = np.ones(len(pos)) if w is None else np.asarray(w, dtype=float)
    wp, wn = w[pos], w[~pos]
    m, n = float(wp.sum()), float(wn.sum())
    if m <= 0 or n <= 0:
        return None, None
    k = len(scores)
    V10 = np.zeros((k, int(pos.sum())))
    V01 = np.zeros((k, int((~pos).sum())))
    theta = np.zeros(k)
    for r, s in enumerate(scores):
        s = np.asarray(s, dtype=float)
        x, yneg = s[pos], s[~pos]
        o = np.argsort(yneg, kind='mergesort')
        ys, cw = yneg[o], np.r_[0.0, np.cumsum(wn[o])]
        below = cw[np.searchsorted(ys, x, side='left')]
        upto = cw[np.searchsorted(ys, x, side='right')]
        V10[r] = (below + 0.5 * (upto - below)) / n
        o = np.argsort(x, kind='mergesort')
        xs, cp = x[o], np.r_[0.0, np.cumsum(wp[o])]
        tot = cp[-1]
        above = tot - cp[np.searchsorted(xs, yneg, side='right')]
        atleast = tot - cp[np.searchsorted(xs, yneg, side='left')]
        V01[r] = (above + 0.5 * (atleast - above)) / m
        theta[r] = float(np.sum(wp * V10[r]) / m)
    D10 = V10 - theta[:, None]
    D01 = V01 - theta[:, None]
    S10 = (D10 * wp) @ D10.T / (m - 1) if m > 1 else np.full((k, k), np.nan)
    S01 = (D01 * wn) @ D01.T / (n - 1) if n > 1 else np.full((k, k), np.nan)
    return theta, S10 / m + S01 / n


def auc_comparison(labels, scores, pos, w, alpha):
    """AUC Comparison: each AUC with its standard error and interval, every
    pair's difference with its standard error, interval and chi-square
    test, and the test that all the AUCs are equal (the contrasts of each
    AUC with the next, its chi-square on their rank)."""
    theta, S = delong(scores, pos, w)
    if theta is None:
        return None
    z = float(stats.norm.ppf(1 - alpha / 2))
    se = np.sqrt(np.clip(np.diag(S), 0, None))
    each = [{'model': labels[i], 'auc': float(theta[i]), 'se': float(se[i]), 'lower': float(theta[i] - z * se[i]), 'upper': float(theta[i] + z * se[i])}
            for i in range(len(labels))]
    pairs = []
    for i in range(len(labels)):
        for j in range(i + 1, len(labels)):
            dv = float(S[i, i] + S[j, j] - 2 * S[i, j])
            diff = float(theta[i] - theta[j])
            sd = math.sqrt(dv) if dv > 0 else 0.0
            chi = diff * diff / dv if dv > 1e-300 else None
            pairs.append({'model1': labels[i], 'model2': labels[j], 'diff': diff, 'se': sd, 'lower': diff - z * sd, 'upper': diff + z * sd,
                          'chisq': chi, 'p': float(stats.chi2.sf(chi, 1)) if chi is not None else None})
    overall = None
    if len(labels) > 1:
        L = np.zeros((len(labels) - 1, len(labels)))
        for i in range(len(labels) - 1):
            L[i, i], L[i, i + 1] = 1.0, -1.0
        C = L @ S @ L.T
        dof = int(np.linalg.matrix_rank(C, tol=1e-12 * max(1.0, float(np.max(np.abs(C))))))
        if dof > 0:
            c = L @ theta
            chi = float(c @ np.linalg.pinv(C, rcond=1e-10) @ c)
            overall = {'chisq': chi, 'df': dof, 'p': float(stats.chi2.sf(chi, dof))}
    return {'each': each, 'pairs': pairs, 'overall': overall}


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------

def _num(s):
    return pd.to_numeric(s, errors='coerce').to_numpy(float)


def _shown(table, name, v):
    """A level as the page shows it: its value label (data.level_label), or the value as text."""
    f = getattr(data, 'level_label', None)
    if f is not None:
        try:
            return str(f(table, name, v))
        except (KeyError, TypeError, ValueError):
            pass
    return pv.level_label(v)


def _check_models(models, cat_y):
    out = []
    for i, m in enumerate(models or []):
        kind = m.get('kind')
        cols = [c for c in (m.get('columns') or []) if c and c.get('name')]
        if kind not in ('pred', 'prob', 'level') or not cols:
            raise ValueError(f'model {i + 1}: no columns')
        if not cat_y and kind != 'pred':
            raise ValueError(f'{m.get("label")}: a continuous response takes columns of predicted values')
        if cat_y and kind == 'pred':
            raise ValueError(f'{m.get("label")}: a categorical response takes probability columns (Prob[level]) or a column of predicted levels')
        if kind in ('pred', 'level') and len(cols) != 1:
            raise ValueError(f'{m.get("label")}: one column of predictions')
        out.append({'key': str(m.get('key') or f'm{i}'), 'label': str(m.get('label') or cols[0]['name']), 'creator': m.get('creator') or '',
                    'kind': kind, 'columns': cols})
    if not out:
        raise ValueError('choose the models\' prediction columns (Y, Predictors)')
    seen = set()
    for m in out:   # every model its own name (the code keys its dict by them)
        base, k = m['label'], 2
        while m['label'] in seen:
            m['label'] = f'{base} ({k})'
            k += 1
        seen.add(m['label'])
    keys = [m['key'] for m in out]
    if len(set(keys)) != len(keys):
        raise ValueError('two models have the same key')
    return out


@api('compare.fit')
def fit(table, y, models, rows=None, group=None, freq=None, average=False, alpha=0.05, plot=None, threshold=False, table_name='data'):
    """Model Comparison of the models' saved predictions of y (see the
    module's docstring): the Measures of Fit of every model in every group,
    the best of each measure, ROC, lift and gains curves, confusion
    matrices and the AUC Comparison (categorical y), actual by predicted
    and residual by row (continuous y), and the Python that computes the
    same from a CSV export. average: Model Averaging, the mean of the
    models as one more model. plot: the page's choices for the graphs'
    code ({'level': the level of the curves}). threshold: the Decision
    Threshold's data (predictive.threshold, every model with
    probabilities), for a response with two levels. A level or a group is
    named by its value label (Column Info) when it has one."""
    if not y:
        raise ValueError('choose the response, Y')
    cat_y = data.is_categorical(table, y)
    M = _check_models(models, cat_y)
    for c in (group, freq):
        if c and (c == y or any(c == col['name'] for m in M for col in m['columns'])):
            raise ValueError(f'{c} is both a role column and the response or a prediction')
    names = list(dict.fromkeys([y] + [col['name'] for m in M for col in m['columns']] + [c for c in (group, freq) if c]))
    df = data.frame(table, names, rows, dropna=False)
    n0 = len(df)
    notes = []
    keep = np.array(df[y].notna(), dtype=bool)
    if not cat_y:
        keep &= np.isfinite(_num(df[y]))
    if (~keep).sum():
        notes.append(f'{int((~keep).sum())} rows with no {y} are left out.')
    fr = None
    if freq:
        fv = _num(df[freq])
        ok = np.isfinite(fv) & (fv > 0)
        if (keep & ~ok).sum():
            notes.append(f'{int((keep & ~ok).sum())} rows with a missing or non-positive {freq} are left out.')
        keep &= ok
    if group:
        ok = np.array(df[group].notna(), dtype=bool)
        if (keep & ~ok).sum():
            notes.append(f'{int((keep & ~ok).sum())} rows with no {group} are left out.')
        keep &= ok
    miss = np.zeros(n0, dtype=bool)
    for m in M:
        for col in m['columns']:
            s = df[col['name']]
            if m['kind'] == 'level':
                miss |= ~np.array(s.notna(), dtype=bool)
            else:
                if data.meta(table, col['name']).get('dataType') != 'numeric':
                    raise ValueError(f'{col["name"]} is not numeric: {"a probability" if m["kind"] == "prob" else "a prediction"} is a number')
                miss |= ~np.isfinite(_num(s))
    if (keep & miss).sum():
        notes.append(f'{int((keep & miss).sum())} rows missing a model\'s prediction are left out: every model is measured on the same rows.')
    keep &= ~miss
    d = df[keep]
    if len(d) == 0:
        raise ValueError('no rows have the response, the group and every model\'s prediction')
    index = np.asarray(d.index, dtype=int)
    w = _num(d[freq]) if freq else None
    wt = np.ones(len(d)) if w is None else w
    # the response
    if cat_y:
        s = d[y]
        cats = list(s.cat.categories)
        codes = s.cat.codes.to_numpy()
        used = set(int(c) for c in np.unique(codes))
        for m in M:
            if m['kind'] == 'prob':
                for col in m['columns']:
                    j = col.get('level')
                    if not (isinstance(j, int) and 0 <= j < len(cats)):
                        raise ValueError(f'{col["name"]}: not the probability of a level of {y}')
                    used.add(j)
            else:
                v = d[m['columns'][0]['name']].astype(object).tolist()
                lab = {pv.level_label(c): i for i, c in enumerate(cats)}
                bad = sorted({pv.level_label(x) for x in v if pv.level_label(x) not in lab})
                if bad:
                    raise ValueError(f'{m["columns"][0]["name"]} holds values that are not levels of {y}: {", ".join(bad[:5])}')
                used.update(lab[pv.level_label(x)] for x in v)
        lv_idx = sorted(used)
        remap = {j: i for i, j in enumerate(lv_idx)}
        levels = [cats[j].item() if hasattr(cats[j], 'item') else cats[j] for j in lv_idx]
        labels = [_shown(table, y, v) for v in levels]
        target = np.array([remap[int(c)] for c in codes], dtype=int)
        kind = 'categorical'
    else:
        target = _num(d[y])
        levels, labels, lv_idx, remap = [], [], [], {}
        kind = 'continuous'
    L = len(levels)
    if kind == 'continuous' and np.any(target == 0):
        notes.append(f'MAPE leaves out the {int(np.sum(target == 0))} rows whose {y} is 0 (their percentage error has no value).')
    for m in M:
        for col in m['columns']:
            if m['kind'] == 'prob':
                col['pos'] = remap[col['level']]
    # every model's prediction of every row
    fitted, clipped, dropped = {}, [], []
    for m in list(M):
        if m['kind'] == 'pred':
            fitted[m['key']] = _num(d[m['columns'][0]['name']])
        elif m['kind'] == 'prob':
            Pm = np.zeros((len(d), L))
            have = set()
            for col in m['columns']:
                j = remap[col['level']]
                if j in have:
                    raise ValueError(f'{m["label"]}: two columns for the level {labels[j]}')
                have.add(j)
                v = _num(d[col['name']])
                if np.any((v < 0) | (v > 1)):
                    clipped.append(col['name'])
                Pm[:, j] = v
            rest = [j for j in range(L) if j not in have]
            if len(rest) > 1:   # the model cannot be completed: left out, with a note
                dropped.append(f'{m["label"]} (no probability column for {", ".join(labels[j] for j in rest)}: every level of {y} but one needs its column)')
                M.remove(m)
                continue
            if rest:
                Pm[:, rest[0]] = np.clip(1 - Pm.sum(axis=1), 0, 1)
                m['complement'] = labels[rest[0]]
            fitted[m['key']] = Pm
        else:
            lab = {pv.level_label(lv): i for i, lv in enumerate(levels)}
            fitted[m['key']] = np.array([lab[pv.level_label(x)] for x in d[m['columns'][0]['name']].astype(object)], dtype=int)
    if clipped:
        notes.append(f'Probabilities outside 0 to 1 in {", ".join(clipped)}: the measures take them as they are.')
    if dropped:
        notes.append(f'Left out: {"; ".join(dropped)}.')
    if not M:
        raise ValueError('no model is left to compare')
    # Model Averaging
    avg_of = [m['key'] for m in M if m['kind'] in ('pred', 'prob')]
    if average:
        if len(avg_of) < 2:
            notes.append('Model Averaging needs two models with predictions or probabilities.')
        else:
            fitted[AVERAGE] = np.mean([fitted[k] for k in avg_of], axis=0)
            taken = {m['label'] for m in M}
            label, k = AVERAGE, 2
            while label in taken:
                label = f'{AVERAGE} ({k})'
                k += 1
            M.append({'key': AVERAGE, 'label': label, 'creator': 'Model Averaging', 'kind': 'pred' if kind == 'continuous' else 'prob',
                      'columns': [], 'of': avg_of})
            if any(m['kind'] == 'level' for m in M):
                notes.append('Model Averaging leaves out the models that give only a predicted level.')
    # the groups
    if group:
        gs = d[group]
        if isinstance(gs.dtype, pd.CategoricalDtype):
            gcats = [c for c in gs.cat.categories if (gs == c).any()]
        else:
            vals = gs.to_numpy()
            gcats = sorted({v for v in vals}, key=lambda v: (isinstance(v, str), v))
        gcats = [c.item() if hasattr(c, 'item') else c for c in gcats]
        gid = np.full(len(d), -1, dtype=int)
        for i, c in enumerate(gcats):
            gid[np.array(gs == c, dtype=bool)] = i
        glabels = [_shown(table, group, c) for c in gcats]
    else:
        gcats, glabels, gid = [None], [None], np.zeros(len(d), dtype=int)
    rows_out, roc, lift, conf, aucs, prc = [], {}, {}, {}, [], {}
    two = kind == 'categorical' and L == 2
    for gi, g in enumerate(glabels):
        mk = gid == gi
        P = _prepared(kind, target[mk], levels, labels, None if w is None else w[mk], index[mk])
        for m in M:
            f = fitted[m['key']][mk]
            if m['kind'] == 'level':
                ww = wt[mk]
                row = {'misclassification': float(np.sum(ww * (f != P.target)) / np.sum(ww)), 'n': float(np.sum(ww))}
                mat = np.zeros((L, L))
                np.add.at(mat, (P.target, f), P.counts())
                conf.setdefault(m['key'], []).append({'set': g, 'levels': list(labels), 'matrix': mat.tolist()})
            else:
                row = pv.measures(P, f)[0]
                row.pop('set', None)
                if kind == 'continuous':
                    _extra(P.target, f, wt[mk], row)
                else:
                    conf.setdefault(m['key'], []).extend({**c, 'set': g} for c in pv.confusion(P, f))
                    roc.setdefault(m['key'], []).extend({**c, 'set': g} for c in pv.roc(P, f, most=200))
                    lift.setdefault(m['key'], []).extend({**c, 'set': g} for c in pv.lift(P, f, most=160))
                    prc.setdefault(m['key'], []).extend({**c, 'set': g} for c in precision_recall(P, f))
            rows_out.append({'group': g, 'model': m['key'], 'label': m['label'], 'creator': m['creator'], **row})
        if kind == 'categorical':
            probs = [m for m in M if m['kind'] == 'prob']
            if probs:
                per = []
                for j in range(L):
                    pos = P.target == j
                    r = auc_comparison([m['label'] for m in probs], [fitted[m['key']][mk][:, j] for m in probs], pos, P.counts(), alpha)
                    per.append({'level': labels[j], **r} if r else None)
                aucs.append({'group': g, 'levels': per})
    mcols = measure_columns(kind, two)
    best = {}
    for gi, g in enumerate(glabels):
        best[str(gi)] = {c['key']: _best([(r['model'], r.get(c['key'])) for r in rows_out if r['group'] == g], c['key'])
                         for c in mcols if c['key'] not in UNRANKED}
    out = {'kind': kind, 'levels': labels, 'groups': glabels, 'group': group, 'n': {str(i): int(np.sum(gid == i)) for i in range(len(glabels))},
           'n_rows': len(d), 'models': [{k: v for k, v in m.items() if k in ('key', 'label', 'creator', 'kind', 'columns', 'complement', 'of')} for m in M],
           'measures': rows_out, 'measure_columns': mcols, 'best': best, 'notes': notes, 'alpha': alpha}
    if kind == 'categorical':
        out.update({'roc': roc, 'lift': lift, 'pr': prc, 'confusion': conf, 'auc': aucs})
    else:
        out['residuals'] = {'rows': index.tolist(), 'actual': target.tolist(), 'group': gid.tolist(),
                            'predicted': {m['key']: fitted[m['key']].tolist() for m in M}}
    S = _Spec(table, y, M, group, freq, gcats, glabels, levels, labels, lv_idx, rows, table_name, kind)
    out['code'] = S.measures_code()
    lv = (plot or {}).get('level')
    lv = lv if isinstance(lv, int) and not isinstance(lv, bool) and 0 <= lv < L else (1 if L == 2 else 0)
    out['plots'] = S.plot_codes(lv, gains=kind == 'categorical' and any('gains' in c for cs in lift.values() for c in cs))
    if kind == 'categorical' and any(m['kind'] == 'prob' for m in M):
        out['auc_code'] = {str(j): S.auc_code(j, alpha) for j in range(L)}
    if threshold and kind == 'categorical' and L == 2 and hasattr(pv, 'threshold'):
        out['threshold'], note = _threshold(S, M, fitted, target, labels, levels, w, index, gcats, glabels, gid)
        if note:
            out['threshold_note'] = note
    return out


SET_NAMES = {'training': 0, 'train': 0, 'validation': 1, 'valid': 1, 'test': 2}


def _sets_of(gcats, glabels, gid):
    """The groups as the validation sets (0 Training, 1 Validation, 2 Test), when they are those: each group's
    label or value names one set, or is 0, 1 or 2. None with no Group (every row one set, Training); raises when the
    groups are something else."""
    if gcats == [None]:
        return None, np.zeros(len(gid), dtype=int)
    k = []
    for c, lab in zip(gcats, glabels):
        j = SET_NAMES.get(str(lab).strip().lower(), SET_NAMES.get(str(c).strip().lower()))
        if j is None and isinstance(c, (int, float)) and float(c) in (0.0, 1.0, 2.0):
            j = int(c)
        if j is None or j in k:
            raise ValueError('the Decision Threshold takes the groups of a validation column (Training, Validation, Test; or 0, 1, 2) as its sets')
        k.append(j)
    return k, np.array(k, dtype=int)[gid]


def _threshold(S, M, fitted, target, labels, levels, w, index, gcats, glabels, gid):
    """predictive.threshold of every model with probabilities, the groups as its sets."""
    probs = [m for m in M if m['kind'] == 'prob']
    if not probs:
        return None, 'the Decision Threshold needs a model with probabilities'
    try:
        k, sets = _sets_of(gcats, glabels, gid)
    except ValueError as e:
        return None, str(e)
    J = json.dumps
    if k is None:
        select = ['y = yv   # each row\'s level, as its index', 'sets = np.zeros(len(d), dtype=int)   # every row in one set']
    else:
        select = ['y = yv   # each row\'s level, as its index', f'sets = np.array({J(k)})[gid]   # the groups as the sets: 0 Training, 1 Validation, 2 Test']
    head = '\n'.join(S._head())
    D = pv.threshold(target, {m['key']: (m['label'], fitted[m['key']]) for m in probs}, labels, sets, w, index, head=head, select=select,
                     code={m['key']: f'fitted[{J(m["label"])}]' for m in probs}, values=levels)
    return D, None if k is not None else 'No Group: every row is in one set, which the Decision Threshold calls Training.'


# ---------------------------------------------------------------------------
# the Python under the report
# ---------------------------------------------------------------------------

def _lit(v):
    """A value as a Python literal: a number as a float, anything else as text."""
    if isinstance(v, (bool, np.bool_)):
        return json.dumps(str(v))
    if isinstance(v, (int, float, np.integer, np.floating)):
        return json.dumps(float(v))
    return json.dumps(str(v))


class _Spec:
    """What the code needs to rebuild the report's rows, groups and models from a CSV export."""

    def __init__(self, table, y, M, group, freq, gcats, glabels, levels, labels, lv_idx, rows, table_name, kind):
        self.table, self.y, self.M, self.group, self.freq = table, y, M, group, freq
        self.gcats, self.glabels, self.levels, self.labels, self.kind = gcats, glabels, levels, labels, kind
        self.rows, self.table_name = rows, table_name

    def _head(self, extra=()):
        """The lines that read the table and make d (the rows every model is measured on), w (their frequencies),
        groups, group_names and gid (each row's group), yv (the response: a number, or the level's index) and
        fitted (each model's prediction, or its probability of every level, of every row)."""
        L = [code_head(self.table_name, list(extra))]
        n_all = data.TABLES[self.table]['n'] if self.table in data.TABLES else None
        if self.rows is not None:
            keep = [int(r) for r in self.rows]
            if n_all is not None and len(keep) > n_all / 2:
                drop = sorted(set(range(n_all)) - set(keep))
                if drop:
                    L.append(f'df = df.drop(index={drop})   # the rows the report leaves out')
            else:
                L.append(f'df = df.loc[{keep}]   # the rows of the report')
        J = json.dumps
        y = self.y
        L.append(f'y = {J(y)}   # the response')
        real = [m for m in self.M if m['key'] != AVERAGE]
        if self.kind == 'continuous':
            L.append('models = {   # each model: its column of predicted values')
            for m in real:
                L.append(f'    {J(m["label"])}: {J(m["columns"][0]["name"])},')
            L.append('}')
        else:
            L.append('models = {   # each model: its column of each level\'s probability, or its column of predicted levels')
            for m in real:
                if m['kind'] == 'level':
                    L.append(f'    {J(m["label"])}: {J(m["columns"][0]["name"])},')
                else:
                    lab = {int(col['pos']): col['name'] for col in m['columns']}
                    L.append(f'    {J(m["label"])}: {{{", ".join(f"{J(self.labels[j])}: {J(nm)}" for j, nm in sorted(lab.items()))}}},')
            L.append('}')
        cols = [y] + [c['name'] for m in real for c in m['columns']] + [c for c in (self.group, self.freq) if c]
        what = ', '.join(x for x in ('the response', 'a group' if self.group else '', 'a frequency' if self.freq else '') if x)
        L.append(f'd = df[{J(list(dict.fromkeys(cols)))}].dropna()   # the rows with {what} and every model\'s prediction: every model is measured on them')
        if self.freq:
            L.append(f'd = d[d[{J(self.freq)}] > 0]   # a non-positive frequency leaves the row out')
            L.append(f'w = d[{J(self.freq)}].to_numpy(float)   # each row counts as its frequency')
        else:
            L.append('w = np.ones(len(d))   # every row counts once')
        if self.group:
            numeric = data.meta(self.table, self.group).get('dataType') == 'numeric'
            src = f'pd.to_numeric(d[{J(self.group)}], errors="coerce")' if numeric else f'd[{J(self.group)}].astype(str)'
            L.append(f'groups = [{", ".join(_lit(c) for c in self.gcats)}]   # the groups of {self.group}, each measured on its own')
            L.append(f'group_names = {J(self.glabels)}   # ... as the report names them')
            L.append(f'gid = pd.Categorical({src}, categories=groups).codes   # each row\'s group')
        else:
            L.append('group_names = [None]   # no Group column: every row in one group')
            L.append('gid = np.zeros(len(d), dtype=int)')
        if self.kind == 'continuous':
            L.append('yv = d[y].to_numpy(float)')
            L.append('fitted = {name: d[col].to_numpy(float) for name, col in models.items()}   # each model\'s prediction of every row')
        else:
            numeric = all(isinstance(v, (int, float, np.integer, np.floating)) for v in self.levels)
            conv = 'pd.to_numeric({0}, errors="coerce")' if numeric else '{0}.astype(str)'
            L.append(f'levels = [{", ".join(_lit(v) for v in self.levels)}]   # the levels of {y} the report uses, in its order')
            L.append(f'names = {J(self.labels)}   # ... as the report names them')
            L.append(f'yv = pd.Categorical({conv.format("d[y]")}, categories=levels).codes   # each row\'s level, as its index')
            L += ['', '',
                  'def proba(cols):',
                  '    """A model\'s probability of each level: its columns; the one level it has no column for is 1 minus the others."""',
                  '    p = np.zeros((len(d), len(levels)))',
                  '    for j, name in enumerate(names):',
                  '        if name in cols:',
                  '            p[:, j] = d[cols[name]].to_numpy(float)',
                  '    rest = [j for j, name in enumerate(names) if name not in cols]',
                  '    if rest:',
                  '        p[:, rest[0]] = np.clip(1 - p.sum(axis=1), 0, 1)',
                  '    return p',
                  '', '',
                  'def predicted(col):',
                  '    """A column of predicted levels: each row\'s level, as its index."""',
                  f'    return pd.Categorical({conv.format("d[col]")}, categories=levels).codes',
                  '', '',
                  'fitted = {name: proba(cols) if isinstance(cols, dict) else predicted(cols) for name, cols in models.items()}   # each model\'s probabilities (or predicted level) of every row']
        avg = next((m for m in self.M if m['key'] == AVERAGE), None)
        if avg:
            names = [next(m['label'] for m in self.M if m['key'] == k) for k in avg['of']]
            L.append(f'fitted[{J(avg["label"])}] = np.mean([fitted[k] for k in {J(names)}], axis=0)   # Model Averaging: the mean of the models\' {"predictions" if self.kind == "continuous" else "probabilities"}')
        return L

    def measures_code(self):
        """The Measures of Fit of every model in every group, printed a line (JSON) each."""
        L = self._head(['import json'])
        if self.kind == 'continuous':
            L += ['', '',
                  'def wcorr(a, b, w):',
                  '    """The correlation of a and b, each row counted w times."""',
                  '    ma, mb = np.sum(w * a) / np.sum(w), np.sum(w * b) / np.sum(w)',
                  '    return np.sum(w * (a - ma) * (b - mb)) / np.sqrt(np.sum(w * (a - ma) ** 2) * np.sum(w * (b - mb) ** 2))',
                  '', '',
                  'for g, group_name in enumerate(group_names):',
                  '    m = gid == g',
                  '    yy, ww = yv[m], w[m]',
                  '    n = ww.sum()',
                  '    sst = np.sum(ww * (yy - np.sum(ww * yy) / n) ** 2)   # about the group\'s own mean',
                  '    nz = yy != 0   # MAPE leaves out the rows with a zero response',
                  '    for name, f in fitted.items():',
                  '        e = yy - f[m]',
                  '        sse = np.sum(ww * e ** 2)',
                  '        out = {"RSquare": 1 - sse / sst, "RASE": np.sqrt(sse / n), "AAE": np.sum(ww * np.abs(e)) / n, "MSE": sse / n,',
                  '               "MAPE": 100 * np.sum(ww[nz] * np.abs(e[nz] / yy[nz])) / ww[nz].sum(), "Correlation": wcorr(yy, f[m], ww), "Freq": n}',
                  '        print(json.dumps({"group": group_name, "model": name, **{k: float(v) for k, v in out.items()}}))']
        else:
            two = len(self.levels) == 2
            L += ['', '']
            if two:
                L += ['def auc(score, pos, w):',
                      '    """The area under the ROC curve: the share of (positive, negative) pairs whose positive row scores higher, a tie counting half."""',
                      '    u, inv = np.unique(score, return_inverse=True)',
                      '    pw = np.bincount(inv, weights=np.where(pos, w, 0.0), minlength=len(u))',
                      '    nw = np.bincount(inv, weights=np.where(pos, 0.0, w), minlength=len(u))',
                      '    return np.sum(pw * (np.cumsum(nw) - nw + 0.5 * nw)) / (pw.sum() * nw.sum())',
                      '', '']
            L += ['for g, group_name in enumerate(group_names):',
                  '    m = gid == g',
                  '    yy, ww = yv[m], w[m]',
                  '    n = ww.sum()',
                  '    share = np.array([ww[yy == j].sum() for j in range(len(levels))]) / n   # the constant model: the group\'s own shares of the levels',
                  '    ll0 = np.sum(ww * np.log(np.clip(share[yy], 1e-15, 1)))',
                  '    for name, f in fitted.items():',
                  '        if f.ndim == 1:   # predicted levels: the misclassification rate only',
                  '            print(json.dumps({"group": group_name, "model": name, "Misclassification Rate": float(np.sum(ww * (f[m] != yy)) / n), "N": float(n)}))',
                  '            continue',
                  '        p = f[m]',
                  '        pt = np.clip(p[np.arange(len(yy)), yy], 1e-15, 1)   # the probability of the level that occurred',
                  '        ll = np.sum(ww * np.log(pt))',
                  '        out = {"Entropy RSquare": 1 - ll / ll0, "Generalized RSquare": (1 - np.exp(2 * (ll0 - ll) / n)) / (1 - np.exp(2 * ll0 / n)),',
                  '               "Mean -Log p": -ll / n, "RASE": np.sqrt(np.sum(ww * (1 - pt) ** 2) / n), "Mean Abs Dev": np.sum(ww * (1 - pt)) / n,',
                  '               "Misclassification Rate": np.sum(ww * (p.argmax(axis=1) != yy)) / n, "N": n}']
            if two:
                L.append('        out["AUC"] = auc(p[:, 1], yy == 1, ww)   # of the second level')
            L.append('        print(json.dumps({"group": group_name, "model": name, **{k: float(v) for k, v in out.items()}}))')
        return '\n'.join(L)

    def auc_code(self, lv, alpha):
        """The AUC Comparison of one level (DeLong et al. 1988), printed a line (JSON) per group."""
        J = json.dumps
        probs = [m['label'] for m in self.M if m['kind'] == 'prob']
        L = self._head(['import json', 'from scipy import stats'])
        L += ['', '',
              'def delong(scores, pos, w):',
              '    """The AUCs of several scores of the same rows and their covariance (DeLong, DeLong and Clarke-Pearson 1988):',
              '    V10, each positive row\'s share of the negative rows it outscores (a tie half), V01, each negative row\'s share',
              '    of the positive rows that outscore it; S = cov(V10)/m + cov(V01)/n, a row counting as its frequency w."""',
              '    wp, wn = w[pos], w[~pos]',
              '    m, n = wp.sum(), wn.sum()',
              '    V10 = np.array([[np.sum(wn * ((x > s[~pos]) + 0.5 * (x == s[~pos]))) / n for x in s[pos]] for s in scores])',
              '    V01 = np.array([[np.sum(wp * ((s[pos] > v) + 0.5 * (s[pos] == v))) / m for v in s[~pos]] for s in scores])',
              '    theta = V10 @ wp / m',
              '    D10, D01 = V10 - theta[:, None], V01 - theta[:, None]',
              '    return theta, (D10 * wp) @ D10.T / (m - 1) / m + (D01 * wn) @ D01.T / (n - 1) / n',
              '', '',
              f'lv = {lv}   # the level {self.labels[lv]}',
              f'order = {J(probs)}   # the models with probabilities',
              f'z = stats.norm.ppf(1 - {alpha!r} / 2)',
              'for g, group_name in enumerate(group_names):',
              '    mk = gid == g',
              '    pos = yv[mk] == lv',
              '    if not (w[mk][pos].sum() > 0 and w[mk][~pos].sum() > 0):',
              '        continue   # the group lacks the level, or the others',
              '    theta, S = delong([fitted[name][mk][:, lv] for name in order], pos, w[mk])',
              '    se = np.sqrt(np.diag(S))',
              '    for i, name in enumerate(order):',
              '        print(json.dumps({"group": group_name, "model": name, "AUC": theta[i], "Std Error": se[i], "Lower": theta[i] - z * se[i], "Upper": theta[i] + z * se[i]}))',
              '    for i in range(len(order)):',
              '        for j in range(i + 1, len(order)):',
              '            diff, sd = theta[i] - theta[j], np.sqrt(S[i, i] + S[j, j] - 2 * S[i, j])',
              '            chisq = (diff / sd) ** 2 if sd > 0 else float("nan")',
              '            print(json.dumps({"group": group_name, "pair": [order[i], order[j]], "AUC Difference": diff, "Std Error": sd, "Lower": diff - z * sd, "Upper": diff + z * sd,',
              '                              "ChiSquare": chisq, "Prob>ChiSq": stats.chi2.sf(chisq, 1)}))',
              '    if len(order) > 1:',
              '        C = np.eye(len(order))[:-1] - np.eye(len(order), k=1)[:-1]   # each AUC less the next',
              '        c, V = C @ theta, C @ S @ C.T',
              '        chisq, df_ = c @ np.linalg.pinv(V, rcond=1e-10) @ c, np.linalg.matrix_rank(V, tol=1e-12 * max(1.0, np.abs(V).max()))',
              '        print(json.dumps({"group": group_name, "test": "all AUCs equal", "ChiSquare": chisq, "DF": int(df_), "Prob>ChiSq": stats.chi2.sf(chisq, df_)}))']
        return '\n'.join(L)

    # ---- the graphs' code (smui-p-compare.js puts each under its graph)
    def _colors(self):
        cm, i = {}, 0
        for m in self.M:
            if m['key'] == AVERAGE:
                cm[m['label']] = AVG_COLOR
            else:
                cm[m['label']] = COLORS[i % len(COLORS)]
                i += 1
        return cm

    def plot_codes(self, lv, gains=False):
        head = self._head([pv.PLT])
        colors = self._colors()
        J = json.dumps
        out = {'head_code': '\n'.join(head)}
        G = list(enumerate(self.glabels))
        beside = 'fig.legend(loc="outside right upper", frameon=False, fontsize=7.5)   # every model, beside the graph'

        def rows_line(g, gl):
            return f'm = gid == {g}   # the rows of {gl}' if gl is not None else 'm = gid == 0   # every row'

        if self.kind == 'categorical':
            probs = [m['label'] for m in self.M if m['kind'] == 'prob']
            level = self.labels[lv]
            pre = [f'lv = {lv}   # the level {level} (Level in the red triangle)', f'order = {J(probs)}   # the models with probabilities, in the report\'s order',
                   f'colors = {J({k: colors[k] for k in probs})}   # each model\'s colour, the same in every graph',
                   f'widths = {J({k: (2.2 if colors[k] == AVG_COLOR else 1.6) for k in probs})}   # the Model Average wider, and dashed',
                   self._freq_line()]
            dash = f'"--" if colors[name] == "{AVG_COLOR}" else "-"'
            roc, lift, gain, pr = {}, {}, {}, {}
            for g, gl in G:
                sp = f'{gl} ' if gl is not None else ''
                pr[str(g)] = '\n'.join(pre + [rows_line(g, gl), '', '',
                                              'def precision_recall(p, pos, f):',
                                              '    """Recall and precision at each cut on p, highest first; tied values move together; from recall 0 at precision 1."""',
                                              '    o = np.argsort(-p, kind="mergesort")',
                                              '    s, tp, fp = p[o], np.cumsum(np.where(pos[o], f[o], 0.0)), np.cumsum(np.where(pos[o], 0.0, f[o]))',
                                              '    last = np.r_[s[1:] != s[:-1], True]   # the end of each run of equal values',
                                              '    tp, fp = tp[last], fp[last]',
                                              '    return np.r_[0.0, tp / tp[-1]], np.r_[1.0, tp / (tp + fp)]', '', '',
                                              pv.figure(480, 330), 'pos = yv[m] == lv',
                                              'if f[m][pos].sum() > 0 and (~pos).any():   # the group has the level\'s rows and others',
                                              '    for name in order:',
                                              '        rec, prec = precision_recall(fitted[name][m][:, lv], pos, f[m])',
                                              '        ap = np.sum(np.diff(rec) * prec[1:])   # the average precision',
                                              f'        ax.plot(rec, prec, color=colors[name], linewidth=widths[name], linestyle={dash}, label=f"{{name}} (AP {{ap:.3f}})")',
                                              f'    ax.axhline(f[m][pos].sum() / f[m].sum(), color="{pv.MUTED}", linewidth=1, linestyle=":")   # the level\'s rate: a model that knows nothing',
                                              'ax.set_xlim(0, 1)', 'ax.set_ylim(0, 1.01)', 'ax.set_xlabel("Recall")', 'ax.set_ylabel("Precision")',
                                              f'ax.set_title({J(f"Precision Recall {sp}{level}")})', beside, 'plt.show()'])
                roc[str(g)] = '\n'.join(pre + [rows_line(g, gl), '', '',
                                               'def roc(p, pos, f):',
                                               '    """1 - specificity and sensitivity at each cut on p, highest first; tied values move together; f counts the rows."""',
                                               '    o = np.argsort(-p, kind="mergesort")',
                                               '    s, tp, fp = p[o], np.cumsum(np.where(pos[o], f[o], 0.0)), np.cumsum(np.where(pos[o], 0.0, f[o]))',
                                               '    last = np.r_[s[1:] != s[:-1], True]   # the end of each run of equal values',
                                               '    return np.r_[0.0, fp[last] / fp[-1]], np.r_[0.0, tp[last] / tp[-1]]', '', '',
                                               pv.figure(480, 330), 'pos = yv[m] == lv',
                                               'if f[m][pos].sum() > 0 and f[m][~pos].sum() > 0:   # the group has the level\'s rows and the others\'',
                                               '    for name in order:',
                                               '        fpr, tpr = roc(fitted[name][m][:, lv], pos, f[m])',
                                               '        auc = np.sum(np.diff(fpr) * (tpr[1:] + tpr[:-1]) / 2)   # the area under the curve',
                                               f'        ax.plot(fpr, tpr, color=colors[name], linewidth=widths[name], linestyle={dash}, label=f"{{name}} ({{auc:.3f}})")',
                                               f'ax.plot([0, 1], [0, 1], color="{pv.MUTED}", linewidth=1, linestyle=":")',
                                               'ax.set_xlim(0, 1)', 'ax.set_ylim(0, 1.01)', 'ax.set_xlabel("1 - Specificity")', 'ax.set_ylabel("Sensitivity")',
                                               f'ax.set_title({J(f"ROC {sp}{level}")})', beside, 'plt.show()'])
                for kind, store in (('lift', lift), ('gains', gain)):
                    if kind == 'gains' and not gains:
                        continue
                    ys = 'hits / cw / base' if kind == 'lift' else 'hits / hits[-1]'
                    what = 'the level\'s rate among the rows taken over its rate in the group' if kind == 'lift' else 'the share of the level\'s rows among those taken'
                    ref = f'ax.plot([0, 1], [1, 1], color="{pv.MUTED}", linewidth=1, linestyle=":")' if kind == 'lift' else f'ax.plot([0, 1], [0, 1], color="{pv.MUTED}", linewidth=1, linestyle=":")   # rows taken at random'
                    store[str(g)] = '\n'.join(pre + [rows_line(g, gl), pv.figure(480, 330), 'pos = yv[m] == lv', 'tot = f[m].sum()',
                                                     'base = f[m][pos].sum() / tot   # the level\'s rate in the group',
                                                     'if base > 0:',
                                                     '    for name in order:',
                                                     '        o = np.argsort(-fitted[name][m][:, lv], kind="mergesort")   # the rows, highest probability first',
                                                     '        cw, hits = np.cumsum(f[m][o]), np.cumsum(np.where(pos[o], f[m][o], 0.0))',
                                                     f'        ax.plot(cw / tot, {ys}, color=colors[name], linewidth=widths[name], linestyle={dash}, label=name)   # {what}',
                                                     ref, 'ax.set_xlim(0, 1)', *(['ax.set_ylim(0, 1.01)'] if kind == 'gains' else []),
                                                     'ax.set_xlabel("Portion")', f'ax.set_ylabel({J("Lift" if kind == "lift" else "Gains")})',
                                                     f'ax.set_title({J(("Lift " if kind == "lift" else "Cum Gains ") + sp + level)})', beside, 'plt.show()'])
            out['roc'], out['lift'] = roc, lift
            out['pr'] = pr
            if gains:
                out['gains'] = gain
        else:
            order = [m['label'] for m in self.M]
            pre = [f'order = {J(order)}   # the models, in the report\'s order', f'colors = {J(colors)}   # each model\'s colour, the same in every graph']
            abp, res = {}, {}
            for g, gl in G:
                sp = f' {gl}' if gl is not None else ''
                abp[str(g)] = '\n'.join(pre + [rows_line(g, gl), pv.figure(480, 330),
                                               'for name in order:',
                                               '    ax.scatter(fitted[name][m], yv[m], s=14, color=colors[name], alpha=0.8, label=name)',
                                               'v = np.concatenate([yv[m]] + [fitted[name][m] for name in order])',
                                               'v = v[np.isfinite(v)]',
                                               f'ax.plot([v.min(), v.max()], [v.min(), v.max()], color="{pv.MUTED}", linewidth=1, linestyle=":")   # actual = predicted',
                                               'ax.set_xlabel("Predicted")', f'ax.set_ylabel({J(self.y)})', f'ax.set_title({J("Actual by predicted" + sp)})', beside, 'plt.show()'])
                res[str(g)] = '\n'.join(pre + [rows_line(g, gl), pv.figure(480, 330),
                                               'row = d.index.to_numpy() + 1   # the row numbers, as the table shows them',
                                               'for name in order:',
                                               '    ax.scatter(row[m], yv[m] - fitted[name][m], s=14, color=colors[name], alpha=0.8, label=name)   # the actual value less the prediction',
                                               f'ax.plot([0, 1], [0, 0], color="{pv.MUTED}", linewidth=1, linestyle=":", transform=ax.get_yaxis_transform())   # zero, across the graph',
                                               'ax.set_xlabel("Row")', 'ax.set_ylabel("Residual")', f'ax.set_title({J("Residual by row" + sp)})', beside, 'plt.show()'])
            out['abp'], out['resid'] = abp, res
        return out

    def _freq_line(self):
        c = self.freq
        return (f'f = d[{json.dumps(c)}].to_numpy(float)   # each row\'s frequency: the curves count the rows by it' if c
                else 'f = np.ones(len(d))   # every row counts once')
