"""Analyze > Predictive Modeling: K Nearest Neighbors, Naive Bayes and
Support Vector Machines, as JMP Pro lays them out, on scikit-learn.

  knn.fit, knn.save, knn.neighbors   the misclassification rate or RASE of
                   every K from 1 to K on each set, the best K, and the fit
                   of the chosen one (KNeighborsClassifier / Regressor on the
                   standardized factors; a training row is not its own
                   neighbour)
  naivebayes.fit, naivebayes.save   the class shares times a normal density
                   for each continuous factor and smoothed level shares for
                   each categorical one: the model of scikit-learn's
                   GaussianNB and CategoricalNB, with the class shares
                   counted once and a missing value left out of its row
  svm.fit, svm.boundary, svm.save   SVC (probabilities by Platt scaling) or
                   SVR on the standardized factors, and a tuning design of
                   Cost and Gamma kept by validation on request
  knn.profile, naivebayes.profile, svm.profile   the Prediction Profiler

Every function is registered with packages=SK: the worker loads
scikit-learn before the first call. sklearn is imported inside the
functions, never at the top (the page loads this module at the start).
The data, the sets and the Measures of Fit are predictive.py's; the fitted
models are kept with predictive.cached(), so the Save commands and the
profiler reuse them.
"""
import json
import math

import numpy as np
import pandas as pd

from . import data, predictive as pv, profile
from .registry import api
from .util import col, formula_num, formula_ref, formula_str

SK = pv.SK
EPS_P = 1e-15          # probabilities are kept inside [EPS_P, 1 - EPS_P]


def _prepare(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
             missing='informative', categorical_y=None):
    return pv.prepare(table, y, list(x or []), rows=rows, weight=weight, freq=freq, validation=validation,
                      portion=float(portion or 0), seed=pv.seed_of(seed), missing=missing or 'informative',
                      categorical_y=categorical_y)


def _roles(y, x, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative'):
    return {'y': y, 'x': list(x or []), 'weight': weight, 'freq': freq, 'validation': validation,
            'portion': float(portion or 0), 'seed': pv.seed_of(seed), 'missing': missing or 'informative'}


def _cont_columns(P):
    """The columns of P.X that hold a continuous factor's values."""
    return [P.groups[e['name']][0] for e in P.enc if e['type'] == 'continuous']


def _scaling(P):
    """The centre and scale of every column of P.X: a continuous factor's
    column by the training rows' mean and standard deviation (n - 1); the 0/1
    columns of levels and Missing stay as they are. Written as the code
    under the report writes it, so that both give the same digits."""
    X = P.X
    cont = _cont_columns(P)
    center, scale = np.zeros(X.shape[1]), np.ones(X.shape[1])
    if cont:
        Xt = X[P.train()][:, cont]
        center[cont] = Xt.mean(0)
        with np.errstate(invalid='ignore', divide='ignore'):
            sd = Xt.std(0, ddof=1) if len(Xt) > 1 else np.zeros(len(cont))
        scale[cont] = np.where(sd > 0, sd, 1.0)
    return center, scale


def _scale_code(P):
    return [f'cont = {_cont_columns(P)}   # the columns of X that hold continuous factors, standardized by the training rows\' mean and SD; 0/1 columns stay as they are',
            'center, scale = np.zeros(X.shape[1]), np.ones(X.shape[1])',
            'center[cont] = X[train][:, cont].mean(0)',
            'sd = X[train][:, cont].std(0, ddof=1)',
            'scale[cont] = np.where(sd > 0, sd, 1.0)',
            'Z = (X - center) / scale']


def _ok_rows(P):
    """Rows of the table the model can take (Save): every row, or with
    Informative Missing off the rows with every factor."""
    frame = data.frame(P.table, P.x, None, dropna=False)
    if P.missing == 'informative':
        return frame
    ok = np.array(frame.notna().all(axis=1), dtype=bool)
    for c in P.x:
        if not data.is_categorical(P.table, c):
            ok &= np.isfinite(pd.to_numeric(frame[c], errors='coerce').to_numpy(float))
    return frame[ok]


def _saved_categorical(P, rows, prob):
    """What Save Predicteds puts in the table for a categorical response
    (as predictive.saved)."""
    prob = np.asarray(prob, dtype=float)
    return {'rows': [int(r) for r in rows], 'prob': prob.tolist(), 'levels': list(P.labels),
            'most_likely': [P.labels[int(j)] for j in np.argmax(prob, axis=1)],
            'names': [f'Prob[{lab}]' for lab in P.labels], 'most_name': f'Most Likely {P.y}',
            'ordinal': data.meta(P.table, P.y).get('modelingType') == 'ordinal'}


def _saved_continuous(P, rows, pred):
    pred = np.asarray(pred, dtype=float)
    yv = pd.to_numeric(pd.Series(data.raw(P.table, P.y, np.asarray(rows, dtype=int))), errors='coerce').to_numpy(float)
    return {'rows': [int(r) for r in rows], 'values': pred.tolist(), 'residuals': (yv - pred).tolist(), 'name': f'Predicted {P.y}'}


def _observed(P):
    """The training rows' values of each factor (a profiler's resampled
    inputs), as predictive.predictor gives them."""
    frame = data.frame(P.table, P.x, P.index[P.train()], dropna=False)
    return {c: [None if (isinstance(v, float) and math.isnan(v)) else (v.item() if hasattr(v, 'item') else v) for v in frame[c].astype(object)] for c in P.x}


def _set_names(P):
    return [(k, pv.SETS[k]) for k in range(3) if P.has(k)]


def _print_sets_code(P, what):
    """Lines that print a quantity of each set, as the tests read them."""
    return [f'for s, name in {json.dumps([list(t) for t in _set_names(P)])}:',
            '    m = sets == s',
            f'    print(name, {what})']


# ===========================================================================
# K NEAREST NEIGHBORS
# ===========================================================================
# A row is predicted from its K nearest training rows (a training row not
# from itself): every K from 1 up to K is fitted, and the best kept by the
# validation rows, the folds of a K-fold Validation column, or the training
# rows. Options: Standardize (the continuous factors by the training rows'
# mean and SD, on at first), Distance Weights (1/distance, off at first).
# A tied vote goes to one of the tied levels at random, from the report's
# seed, as JMP breaks ties (a uniform number per table row and level: the
# largest among the tied levels wins).

KNN_WEIGHTS = ('uniform', 'distance')


def knn_weights(dist, k, weights='uniform'):
    """The weights of each row's first k neighbours: 1 each, or with distance weights 1/distance, and when one of
    them is at distance 0, 1 for those at 0 and 0 for the others (as scikit-learn's weights='distance')."""
    d = np.asarray(dist, dtype=float)[:, :k]
    if weights != 'distance':
        return np.ones_like(d)
    zero = d == 0
    with np.errstate(divide='ignore'):
        inv = 1.0 / d
    return np.where(zero.any(axis=1, keepdims=True), zero.astype(float), inv)


def knn_votes(ytr, near, dist, k, n_levels, weights='uniform'):
    """Each level's votes among each row's first k neighbours: their count, or with distance weights k times the
    level's share of the weights (so that equal weights give the counts)."""
    n = len(near)
    at = np.arange(n)
    if weights != 'distance':
        counts = np.zeros((n, n_levels))
        for j in range(k):
            counts[at, ytr[near[:, j]]] += 1
        return counts
    w = knn_weights(dist, k, weights)
    v = np.zeros((n, n_levels))
    for j in range(k):
        v[at, ytr[near[:, j]]] += w[:, j]
    return k * v / w.sum(axis=1, keepdims=True)


def knn_mean(ytr, near, dist, k, weights='uniform'):
    """The (weighted) mean response of each row's first k neighbours."""
    if weights != 'distance':
        total = np.zeros(len(near))
        for j in range(k):
            total += ytr[near[:, j]]
        return total / k
    w = knn_weights(dist, k, weights)
    return np.sum(w * ytr[near[:, :k]], axis=1) / w.sum(axis=1)


def knn_decide(votes, tie):
    """The level most neighbours have; a tie broken at random: of the tied levels the one with the largest tie."""
    top = votes == votes.max(axis=1, keepdims=True)
    return np.argmax(np.where(top, tie, -1.0), axis=1)


def _knn_ties(P, rows, n_levels):
    """The seeded uniform numbers that break tied votes, by the table's row number (the same for a row whatever
    else the table holds: the stream's first rows)."""
    rows = np.asarray(rows, dtype=int)
    n = int(max(data.TABLES[P.table]['n'], (rows.max() + 1) if len(rows) else 0))
    return np.random.default_rng([int(P.spec.get('seed') or 0), 7]).random((n, n_levels))[rows]


def _knn_setup(table, rows, y, x, k=10, validation=None, portion=0.0, seed=None, missing='informative', standardize=True, weights='uniform', **_):
    P = _prepare(table, y, x, rows, validation=validation, portion=portion, seed=seed, missing=missing)
    ntr = int(P.train().sum())
    if ntr < 2:
        raise ValueError('K Nearest Neighbors needs at least two training rows')
    try:
        kk = int(round(float(k)))
    except (TypeError, ValueError):
        raise ValueError(f'the Number of Neighbors, K, is a whole number, not {k!r}')
    if kk < 1:
        raise ValueError('the Number of Neighbors, K, is at least 1')
    if weights not in KNN_WEIGHTS:
        raise ValueError(f'the weights are uniform or distance, not {weights!r}')
    kmax = min(kk, ntr - 1)
    if P.k:        # each fold predicted from the other folds: K at most the rows outside the largest fold
        kmax = min(kmax, int(min(np.sum(P.folds != j) for j in range(P.k))))
    spec = {**_roles(y, x, validation=validation, portion=portion, seed=seed, missing=missing), 'k': kmax, 'standardize': bool(standardize), 'weights': weights}
    M = pv.cached('knn', table, rows, spec, lambda: _knn_model(P, kmax, bool(standardize), weights))
    return P, M, kk


def _knn_model(P, kmax, standardize=True, weights='uniform'):
    from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor, NearestNeighbors
    if standardize:
        center, scale = _scaling(P)
    else:
        center, scale = np.zeros(P.X.shape[1]), np.ones(P.X.shape[1])
    Z = (P.X - center) / scale
    tr = P.train()
    Model = KNeighborsClassifier if P.kind == 'categorical' else KNeighborsRegressor
    m = Model(n_neighbors=kmax).fit(Z[tr], P.target[tr])
    near = np.empty((len(Z), kmax), dtype=int)
    dist = np.empty((len(Z), kmax))
    dist[tr], near[tr] = m.kneighbors()             # a training row is not its own neighbour
    if (~tr).any():
        dist[~tr], near[~tr] = m.kneighbors(Z[~tr])
    out = {'model': m, 'center': center, 'scale': scale, 'near': near, 'dist': dist, 'kmax': kmax, 'ytr': P.target[tr],
           'train_rows': P.index[tr], 'standardize': standardize, 'weights': weights}
    if P.k:        # the folds of the Validation column: each fold's rows from their neighbours in the other folds
        near_cv, dist_cv = np.empty((len(Z), kmax), dtype=int), np.empty((len(Z), kmax))
        for j in range(P.k):
            held = P.folds == j
            others = np.flatnonzero(~held)
            dd, ii = NearestNeighbors().fit(Z[others]).kneighbors(Z[held], n_neighbors=kmax)
            near_cv[held], dist_cv[held] = others[ii], dd     # every row trains, so a row's place among the training rows is its own
        out['near_cv'], out['dist_cv'] = near_cv, dist_cv
    return out


def _knn_predict(P, M, near, dist, k, tie=None):
    """The prediction of k neighbours: each level's votes as a share with a prior of one vote spread over the levels,
    (votes + 1/L)/(k + 1), so that no probability is 0 or 1 and the largest is the level most neighbours have; and
    each row's called level (a tie broken by tie, at random); or the (weighted) mean of the k responses."""
    ytr = M['ytr']
    if P.kind == 'categorical':
        L = len(P.levels)
        v = knn_votes(ytr, near, dist, k, L, M['weights'])
        prob = (v + 1 / L) / (k + 1)
        return prob, (knn_decide(v, tie) if tie is not None else prob.argmax(1))
    return knn_mean(ytr, near, dist, k, M['weights']), None


def _knn_path(P, M):
    """The criterion of every k on each set (and the folds', with a K-fold Validation column), as the loop of the
    code computes it; a tied vote broken at random from the seed."""
    K = M['kmax']
    sets = _set_names(P)
    out = []
    cat = P.kind == 'categorical'
    tie = _knn_ties(P, P.index, len(P.levels)) if cat else None
    for k in range(1, K + 1):
        row = {'k': k}
        parts = [(s, P.sets == s, M['near'], M['dist']) for s, _nm in sets]
        if P.k:
            parts.append(('cv', np.ones(len(P.index), dtype=bool), M['near_cv'], M['dist_cv']))
        for s, m, near, dist in parts:
            f, dec = _knn_predict(P, M, near, dist, k, tie)
            row[f'n{s}'] = int(m.sum())
            if cat:
                wrong = dec[m] != P.target[m]
                row[f'rate{s}'] = float(np.mean(wrong))
                row[f'miss{s}'] = int(wrong.sum())
            else:
                r = P.target[m] - f[m]
                row[f'rase{s}'] = float(np.sqrt(np.mean(r ** 2)))
                row[f'sse{s}'] = float(np.sum(r ** 2))
        out.append(row)
    return out


def _knn_best(P, path):
    """The best K: the smallest misclassification rate (or RASE) on the validation rows when there are some, else
    of the folds of a K-fold Validation column, else on the training rows; of equal values the smallest K."""
    by = 1 if P.has(1) else ('cv' if P.k else 0)
    key = f'rate{by}' if P.kind == 'categorical' else f'rase{by}'
    crit = np.array([r[key] for r in path])
    return int(np.argmin(crit)) + 1, by


def _knn_chosen(P, M, chosen):
    if chosen in (None, ''):
        return _knn_best(P, _knn_path(P, M))[0]
    return max(1, min(M['kmax'], int(round(float(chosen)))))


def _knn_columns(P):
    cols = [col('k', 'K', 'int')]
    for s, nm in _set_names(P) + ([('cv', 'Crossvalidation')] if P.k else []):
        cols.append(col(f'n{s}', f'{nm} Count', 'int', hidden=True))
        if P.kind == 'categorical':
            cols += [col(f'rate{s}', f'{nm} Misclassification Rate'), col(f'miss{s}', f'{nm} Misclassifications', 'int', hidden=True)]
        else:
            cols += [col(f'rase{s}', f'{nm} RASE'), col(f'sse{s}', f'{nm} SSE', hidden=True)]
    return cols


@api('knn.fit', packages=SK)
def knn_fit(table, y, x, rows=None, k=10, chosen=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
            missing='informative', standardize=True, weights='uniform', keep=None, table_name='data'):
    """K Nearest Neighbors: every K from 1 to k. chosen: the K whose fit is shown (None: the best, by the
    validation rows when there are some, else by the folds of a K-fold Validation column, else by the training
    rows, each training row predicted from the others). keep: the page's key to keep the fitted model under (Score
    Rows)."""
    try:
        P, M, asked = _knn_setup(table, rows, y, x, k=k, validation=validation, portion=portion, seed=seed, missing=missing,
                                 standardize=standardize, weights=weights)
    except ValueError as e:
        return {'error': str(e)}
    K = M['kmax']
    path = _knn_path(P, M)
    best, by = _knn_best(P, path)
    ck = best if chosen in (None, '') else max(1, min(K, int(round(float(chosen)))))
    cat = P.kind == 'categorical'
    tie = _knn_ties(P, P.index, len(P.levels)) if cat else None
    fitted, decided = _knn_predict(P, M, M['near'], M['dist'], ck, tie)
    notes = []
    if asked > K:
        notes.append(f'K is {K}, the most the training rows allow (a training row is not its own neighbour{"; a fold is predicted from the others" if P.k else ""}); {asked} was asked for.')
    head = '\n'.join(_knn_head(P, M, K, None if chosen in (None, '') else ck, table_name, rows))
    rep = pv.report(P, fitted, head=head, decided=decided)
    rep['plots']['selection'] = _knn_selection_tail(P, K)
    out = {'kind': P.kind, 'k': K, 'best': best, 'chosen': ck, 'by': 'Crossvalidation' if by == 'cv' else pv.SETS[by],
           'path': {'columns': _knn_columns(P), 'rows': path}, 'fit': rep, 'n_train': int(P.train().sum()), 'notes': notes,
           'features': list(P.features), 'scaled': [P.features[j] for j in _cont_columns(P)] if M['standardize'] else [],
           'standardize': M['standardize'], 'weights': M['weights'], 'folds': P.k, 'code': '\n'.join(_knn_code(P, M, K, table_name, rows))}
    if cat:
        out['decided'] = {'rows': P.index.tolist(), 'set': P.sets.tolist(), 'actual': P.target.tolist(), 'pred': decided.tolist()}
        rep['plots']['mosaic'] = {s: _knn_mosaic_tail(P, k_) for k_, s in _set_names(P)}
        if P.k:
            fcv, dcv = _knn_predict(P, M, M['near_cv'], M['dist_cv'], ck, tie)
            out['cv'] = {'measures': next((q for q in pv.measures(P, fcv, dcv) if q['set'] == 'Training'), None)}
    elif P.k:
        fcv, _ = _knn_predict(P, M, M['near_cv'], M['dist_cv'], ck)
        out['cv'] = {'measures': next((q for q in pv.measures(P, fcv) if q['set'] == 'Training'), None)}
    if out.get('cv') and out['cv']['measures']:
        out['cv']['measures'] = {**out['cv']['measures'], 'set': 'Crossvalidation'}
    pv.keep(keep, {'kind': 'knn', 'P': P, 'M': M, 'chosen': ck, 'table_name': table_name})
    return out


# the levels' colours and markers of the learners' graphs (smui-p-learners.js, light theme)
HUES = ['#2a78d6', '#1baf7a', '#e34948', '#4a3aa7', '#b07c00', '#d55181', '#3d8b1f']
MARKERS = ['o', 's', 'D', '^', 'v', '*', 'h', 'p']


def _knn_neighbor_lines(P, M, K):
    """The lines that find the neighbours as the report finds them: near and dist (and near_cv, dist_cv of a K-fold
    Validation column), the training rows' responses, the tie-breakers."""
    cat = P.kind == 'categorical'
    cls = 'KNeighborsClassifier' if cat else 'KNeighborsRegressor'
    L = ([''] + _scale_code(P) + ['']) if M['standardize'] else ['', 'Z = X.copy()   # the columns as they are (Standardize is off)', '']
    L += [f'from sklearn.neighbors import {cls}' + (', NearestNeighbors' if P.k else ''),
          f'K = {K}',
          f'knn = {cls}(n_neighbors=K).fit(Z[train], y[train])',
          'near, dist = np.empty((len(Z), K), dtype=int), np.empty((len(Z), K))   # each row\'s K nearest training rows (their places in Z[train]), nearest first',
          'dist[train], near[train] = knn.kneighbors()   # a training row is not its own neighbour']
    if (~P.train()).any():
        L.append('dist[~train], near[~train] = knn.kneighbors(Z[~train])')
    if P.k:
        L += ['near_cv, dist_cv = np.empty((len(Z), K), dtype=int), np.empty((len(Z), K))   # each fold\'s rows from their neighbours in the other folds',
              f'for j in range({P.k}):',
              '    held = folds == j',
              '    others = np.flatnonzero(~held)',
              '    dd, ii = NearestNeighbors().fit(Z[others]).kneighbors(Z[held], n_neighbors=K)',
              '    near_cv[held], dist_cv[held] = others[ii], dd   # every row trains: its place among the training rows is its own']
    L.append('ytr = y[train]')
    L.append(f'weights = {json.dumps(M["weights"])}   # uniform, or distance (Distance Weights in the red triangle)')
    L += ['', '', _src_of(knn_weights, knn_votes if cat else knn_mean) + ('\n\n\n' + _src_of(knn_decide) if cat else ''), '', '']
    if cat:
        L += ['L = len(levels)',
              f'seed = {int(P.spec.get("seed") or 0)}   # the report\'s seed',
              'tie = np.random.default_rng([seed, 7]).random((d.index.max() + 1, L))[d.index.to_numpy()]   # by the row\'s number: a tied vote goes to the tied level with the largest of these (at random, as JMP)']
    return L


def _src_of(*fns):
    import inspect
    return '\n\n\n'.join(inspect.getsource(f).rstrip() for f in fns)


def _knn_head(P, M, K, picked, table_name, rows):
    """The head of K Nearest Neighbors' graphs: the neighbours found as the report finds them, each set's
    criterion for every K (crit), the best K, and fitted, the chosen K's prediction (picked: the K picked
    in Model Selection, or None for the best)."""
    cat = P.kind == 'categorical'
    cls = 'KNeighborsClassifier' if cat else 'KNeighborsRegressor'
    L = P.code(table_name, rows=rows, extra_imports=[pv.PLT, f'from sklearn.neighbors import {cls}'])
    L += _knn_neighbor_lines(P, M, K)
    parts = '[(s, sets == s, near, dist) for s in (0, 1, 2) if (sets == s).any()]' + (' + [("cv", np.ones(len(y), dtype=bool), near_cv, dist_cv)]' if P.k else '')
    L.append(f'crit = {{s: [] for s, *_ in {parts}}}   # each set\'s ' + ('misclassification rate' if cat else 'RASE') + ' for K = 1, 2, ...' + (' (cv: the folds\')' if P.k else ''))
    L += ['for k in range(1, K + 1):',
          f'    for s, m, nb, ds in {parts}:']
    if cat:
        L += ['        called = knn_decide(knn_votes(ytr, nb, ds, k, L, weights), tie)',
              '        crit[s].append(np.mean(called[m] != y[m]))']
    else:
        L += ['        pred = knn_mean(ytr, nb, ds, k, weights)',
              '        crit[s].append(np.sqrt(np.mean((y[m] - pred[m]) ** 2)))']
    by = '1' if P.has(1) else ('"cv"' if P.k else '0')
    L += [f'best = int(np.argmin(crit[{by}])) + 1   # the smallest on the {"validation rows" if P.has(1) else ("folds" if P.k else "training rows")}; of equal ones the smallest K',
          f'chosen = {picked}   # the K picked in Model Selection' if picked is not None else 'chosen = best']
    if cat:
        L += ['votes = knn_votes(ytr, near, dist, chosen, L, weights)',
              'fitted = (votes + 1 / L) / (chosen + 1)   # the chosen K\'s probabilities: the votes with a prior of one vote spread over the levels',
              'called = knn_decide(votes, tie)   # each row\'s level, a tie broken at random']
    else:
        L.append('fitted = knn_mean(ytr, near, dist, chosen, weights)   # the chosen K\'s prediction of every row')
    return L


def _knn_selection_tail(P, K):
    """Model Selection's plot: each set's criterion by K, the best K dotted (and a K picked, solid)."""
    what = 'Misclassification Rate' if P.kind == 'categorical' else 'RASE'
    return '\n'.join([
        f'colors, markers, styles = {json.dumps(HUES)}, {json.dumps(MARKERS)}, ["-", "--", ":", "-."]',
        'names = {0: "Training", 1: "Validation", 2: "Test", "cv": "Crossvalidation"}',
        pv.figure(430, 300),
        'for i, (s, v) in enumerate(crit.items()):',
        '    ax.plot(range(1, K + 1), v, color=colors[i], linewidth=2, linestyle=styles[i], marker=markers[i], markersize=5.6, label=names[s])',
        f'ax.axvline(best, color="{pv.MUTED}", linewidth=1.2, linestyle=":")',
        f'ax.text(best, 1, f" best K = {{best}}", transform=ax.get_xaxis_transform(), ha="left", va="top", fontsize=7.5, color="{pv.MUTED}")',
        'if chosen != best:',
        f'    ax.axvline(chosen, color="{pv.TEXT}", linewidth=1.2)   # the K shown',
        'ax.set_xlim(0.5, K + 0.5)',
        *(['ax.set_xticks(range(1, K + 1))'] if K <= 20 else []),
        'ax.set_ylim(bottom=0)',
        'ax.set_xlabel("K")', f'ax.set_ylabel("{what}")', f'ax.set_title("{what} by K")',
        'fig.legend(loc="outside upper left", ncols=4, frameon=False, fontsize=8)',
        'plt.show()'])


def _knn_mosaic_tail(P, k):
    """The mosaic of a set: a bar per actual level as wide as its share of the set's rows, cut by the shares of the
    levels the rows are called."""
    s = pv.SETS[k]
    return '\n'.join([
        f'm = sets == {k}   # the {s.lower()} rows',
        f'colors = {json.dumps(HUES)}',
        'L = len(levels)',
        'cm = np.zeros((L, L))',
        'np.add.at(cm, (y[m], called[m]), 1)   # actual by called, a row each',
        'width = cm.sum(1) / cm.sum()   # each actual level\'s share of the rows',
        'left = np.r_[0, np.cumsum(width)[:-1]]',
        'share = cm / np.where(cm.sum(1, keepdims=True) > 0, cm.sum(1, keepdims=True), 1)   # the shares of the levels called, within each actual level',
        pv.figure(360, 300),
        'bottom = np.zeros(L)',
        'for j in range(L):',
        '    ax.bar(left + width / 2, share[:, j], width=width * 0.98, bottom=bottom, color=colors[j % len(colors)], label=str(levels[j]))',
        '    bottom = bottom + share[:, j]',
        'ax.set_xlim(0, 1)', 'ax.set_ylim(0, 1)',
        'ax.set_xticks(left + width / 2, [str(v) for v in levels])',
        f'ax.set_xlabel("Actual")', 'ax.set_ylabel("Called")', f'ax.set_title({json.dumps(f"Mosaic {s}")})',
        'fig.legend(loc="outside right upper", frameon=False, fontsize=8)',
        'plt.show()'])


def _knn_code(P, M, K, table_name, rows):
    cat = P.kind == 'categorical'
    L = P.code(table_name, rows=rows)
    L += _knn_neighbor_lines(P, M, K)
    parts = '[(s, sets == s, near, dist) for s in (0, 1, 2) if (sets == s).any()]' + (' + [("cv", np.ones(len(y), dtype=bool), near_cv, dist_cv)]' if P.k else '')
    L += ['for k in range(1, K + 1):', f'    out = []', f'    for s, m, nb, ds in {parts}:']
    if cat:
        L += ['        called = knn_decide(knn_votes(ytr, nb, ds, k, L, weights), tie)   # each row\'s level, a tied vote broken at random',
              '        out.append(np.mean(called[m] != y[m]))',
              '    print("k", k, *out)   # the misclassification rate of each set' + (' and of the folds' if P.k else '')]
    else:
        L += ['        pred = knn_mean(ytr, nb, ds, k, weights)   # the mean response of the k nearest',
              '        out.append(np.sqrt(np.mean((y[m] - pred[m]) ** 2)))',
              '    print("k", k, *out)   # the RASE of each set' + (' and of the folds' if P.k else '')]
    return L


def _knn_rows(P, M, frame_rows, X):
    """The neighbour lists (first kmax) and distances of rows of the table: a row of the report keeps its own (a
    training row without itself), any other row gets its nearest training rows."""
    pos = {int(r): i for i, r in enumerate(P.index)}
    near = np.empty((len(frame_rows), M['kmax']), dtype=int)
    dist = np.empty((len(frame_rows), M['kmax']))
    inside = np.array([int(r) in pos for r in frame_rows], dtype=bool)
    if inside.any():
        at = [pos[int(r)] for r in np.asarray(frame_rows)[inside]]
        near[inside], dist[inside] = M['near'][at], M['dist'][at]
    if (~inside).any():
        Z = (X[~inside] - M['center']) / M['scale']
        dist[~inside], near[~inside] = M['model'].kneighbors(Z)
    return near, dist


def _knn_saved(P, M, rws, X, ck, fresh=False):
    """Save Predicteds' columns for rows of a table (fresh: every row from the training rows, none of them in the
    report, as for another table)."""
    if fresh:
        Z = (X - M['center']) / M['scale']
        dist, near = M['model'].kneighbors(Z) if len(Z) else (np.zeros((0, M['kmax'])), np.zeros((0, M['kmax']), dtype=int))
    else:
        near, dist = _knn_rows(P, M, rws, X)
    cat = P.kind == 'categorical'
    tie = _knn_ties(P, rws, len(P.levels)) if cat and len(rws) else None
    fitted, decided = _knn_predict(P, M, near, dist, ck, tie) if len(rws) else (np.zeros((0, len(P.levels))) if cat else np.zeros(0), np.zeros(0, dtype=int))
    if cat:
        out = _saved_categorical(P, rws, fitted)
        out['most_likely'] = [P.labels[int(j)] for j in decided]
    else:
        out = _saved_continuous(P, rws, fitted)
    return out


@api('knn.save', packages=SK)
def knn_save(table, y, x, rows=None, k=10, chosen=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
             missing='informative', standardize=True, weights='uniform'):
    """Save Predicteds of the chosen K for every row the model can take (a tied vote broken at random, as in the
    report)."""
    P, M, _ = _knn_setup(table, rows, y, x, k=k, validation=validation, portion=portion, seed=seed, missing=missing, standardize=standardize, weights=weights)
    ck = _knn_chosen(P, M, chosen)
    X, rws = P.all_rows()
    out = _knn_saved(P, M, rws, X, ck)
    out['k'] = ck
    return out


@api('knn.score', packages=SK)
def knn_score(table, keep=None, source=None, target_rows=None, y=None, x=None, rows=None, k=10, chosen=None, validation=None, portion=0.0,
              seed=None, missing='informative', standardize=True, weights='uniform'):
    """Score Rows: the report's model (kept under keep when it fitted) on rows of a table (table: the one to score,
    another open table or the report's own with rows added since; target_rows: those rows, None for all). Without
    the kept model (the engine started again) it is fitted again from the source table as it is now."""
    K_ = pv.kept(keep)
    note = None
    if K_ is None or K_.get('kind') != 'knn':
        P, M, _ = _knn_setup(source or table, rows, y, x, k=k, validation=validation, portion=portion, seed=seed, missing=missing, standardize=standardize, weights=weights)
        ck = _knn_chosen(P, M, chosen)
        note = 'The model was fitted again (the engine had not kept it): on the report\'s table as it is now.'
    else:
        P, M, ck = K_['P'], K_['M'], K_['chosen']
    X, rws = pv.score_frame(P, table, target_rows)
    same = table == P.table
    out = _knn_saved(P, M, rws, X, ck, fresh=not same)
    out.update({'k': ck, 'note': note})
    return out


@api('knn.neighbors', packages=SK)
def knn_neighbors(table, y, x, rows=None, k=10, chosen=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
                  missing='informative', standardize=True, weights='uniform'):
    """Save Near Neighbor Rows: for every row the model can take, the row
    numbers (from 1, as the table shows them) of its K nearest training rows."""
    P, M, _ = _knn_setup(table, rows, y, x, k=k, validation=validation, portion=portion, seed=seed, missing=missing, standardize=standardize, weights=weights)
    X, rws = P.all_rows()
    near, _ = _knn_rows(P, M, rws, X)
    rownum = M['train_rows'][near] + 1
    return {'rows': [int(r) for r in rws], 'near': rownum.T.tolist(), 'names': [f'RowNear {j + 1}' for j in range(M['kmax'])]}


def _knn_build(table, rows=None, y=None, x=(), k=10, chosen=None, validation=None, portion=0.0, seed=None, missing='informative',
               standardize=True, weights='uniform', **_):
    P, M, _ = _knn_setup(table, rows, y, x, k=k, validation=validation, portion=portion, seed=seed, missing=missing, standardize=standardize, weights=weights)
    ck = _knn_chosen(P, M, chosen)

    def run(settings):
        X = P.encode_settings(settings)
        dist, near = M['model'].kneighbors((X - M['center']) / M['scale'])
        f, _ = _knn_predict(P, M, near, dist, ck)
        if P.kind == 'continuous':
            return [{'name': P.y, 'pred': f, 'lower': None, 'upper': None, 'bounded': False}]
        return [{'name': f'Prob[{lab}]', 'pred': f[:, j], 'lower': None, 'upper': None, 'bounded': True} for j, lab in enumerate(P.labels)]
    return profile.Predictor(P.factors(), run, _observed(P))


profile.expose('knn', _knn_build, packages=SK)


# ===========================================================================
# NAIVE BAYES
# ===========================================================================

def _nb_features(P, frame):
    """The factors of some rows (a DataFrame with the x columns) as the model
    reads them: a continuous factor's values (NaN missing) and, with
    Informative Missing, a 0/1 Missing factor; a categorical factor's level
    number (a missing value is a level of its own with Informative Missing,
    else -1: left out; a level the rows lack is -1 too)."""
    out = []
    informative = P.missing == 'informative'
    for e in P.enc:
        s = frame[e['name']]
        if e['type'] == 'continuous':
            v = pd.to_numeric(s, errors='coerce').to_numpy(float)
            out.append({'kind': 'normal', 'name': e['name'], 'v': v})
            if informative and e['indicator']:
                out.append({'kind': 'levels', 'name': f'{e["name"]} Missing', 'code': (~np.isfinite(v)).astype(int), 'ncat': 2,
                            'labels': ['present', 'missing'], 'of': e['name']})
        else:
            nl = len(e['levels'])
            idx = np.array([pv._level_at(e['levels'], v) for v in s.astype(object)], dtype=int)
            code = np.where(idx >= 0, idx, -1)
            ncat = nl
            if informative and e['indicator']:
                code = np.where(idx == -1, nl, code)
                ncat = nl + 1
            out.append({'kind': 'levels', 'name': e['name'], 'code': code, 'ncat': ncat,
                        'labels': [pv.level_label(v) for v in e['levels']] + (['Missing'] if ncat > nl else []), 'of': e['name']})
    return out


def _nb_model(P, alpha, var_smoothing, fit_rows=None):
    """The class shares, and per factor and level the normal density's mean
    and variance or the smoothed level shares, from the training rows that
    have the factor (weighted by Weight x Freq): GaussianNB's weighted mean
    and variance plus var_smoothing times the largest variance of a factor,
    and CategoricalNB's (count + alpha) / (total + alpha x levels).
    fit_rows: the rows to fit (a fold's others), the training rows by default."""
    frame = data.frame(P.table, P.x, P.index, dropna=False)
    feats = _nb_features(P, frame)
    tr = P.train() if fit_rows is None else np.asarray(fit_rows, dtype=bool)
    wt = P.weights()
    y = P.target
    L = len(P.levels)
    cls = [tr & (y == c) for c in range(L)]
    count = np.array([wt[m].sum() for m in cls])
    share = count / wt[tr].sum()
    normals = [f for f in feats if f['kind'] == 'normal']
    spread = [float(np.var(f['v'][tr & np.isfinite(f['v'])])) for f in normals if (tr & np.isfinite(f['v'])).any()]
    eps = var_smoothing * max(spread) if spread else 0.0
    parts = []
    for f in feats:
        if f['kind'] == 'normal':
            v = f['v']
            ok = np.isfinite(v)
            if not (tr & ok).any():
                parts.append({**f, 'skip': True})
                continue
            mu, var, n = np.zeros(L), np.zeros(L), np.zeros(L)
            for c in range(L):
                m = cls[c] & ok
                n[c] = wt[m].sum()
                if not n[c] > 0:
                    m = tr & ok          # a level with no values of this factor: its overall distribution
                mu[c] = np.average(v[m], weights=wt[m])
                var[c] = np.average((v[m] - mu[c]) ** 2, weights=wt[m]) + eps
            parts.append({**f, 'mean': mu, 'var': var, 'n': n, 'skip': False})
        else:
            code, k = f['code'], f['ncat']
            ok = code >= 0
            counts = np.zeros((L, k))
            logp = np.zeros((L, k))
            for c in range(L):
                m = cls[c] & ok
                counts[c] = np.bincount(code[m], weights=wt[m], minlength=k)
                nn = counts[c] + alpha
                logp[c] = np.log(nn / nn.sum())
            parts.append({**f, 'count': counts, 'logp': logp, 'skip': False})
    with np.errstate(divide='ignore'):
        log_prior = np.log(share)
    return {'log_prior': log_prior, 'share': share, 'count': count, 'parts': parts, 'eps': eps, 'alpha': alpha, 'var_smoothing': var_smoothing}


def _nb_proba(P, M, feats, n):
    """The level probabilities of n rows whose factors feats holds
    (_nb_features): the normal densities first, then the level shares, in the
    order the code under the report adds them."""
    L = len(P.levels)
    logp = np.tile(M['log_prior'], (n, 1))
    pairs = list(zip(feats, M['parts']))
    for f, part in [q for q in pairs if q[0]['kind'] == 'normal'] + [q for q in pairs if q[0]['kind'] != 'normal']:
        if part['skip']:
            continue
        if f['kind'] == 'normal':
            v = f['v']
            ok = np.isfinite(v)
            for c in range(L):
                mu, var = part['mean'][c], part['var'][c]
                logp[ok, c] += -0.5 * np.log(2 * np.pi * var) - (v[ok] - mu) ** 2 / (2 * var)
        else:
            code = f['code']
            ok = (code >= 0) & (code < part['ncat'])
            for c in range(L):
                logp[ok, c] += part['logp'][c][code[ok]]
    with np.errstate(invalid='ignore'):
        prob = np.exp(logp - logp.max(1, keepdims=True))
    prob = prob / prob.sum(1, keepdims=True)
    return np.clip(prob, EPS_P, 1 - EPS_P)


def _nb_setup(table, rows, y, x, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
              alpha=1.0, var_smoothing=1e-9, **_):
    if y and not data.is_categorical(table, y):
        raise ValueError(f'Naive Bayes classifies: {y} is continuous; make it nominal or ordinal (right click it in the Columns panel)')
    P = _prepare(table, y, x, rows, weight=weight, freq=freq, validation=validation, portion=portion, seed=seed, missing=missing)
    a = float(alpha if alpha is not None else 1.0)
    vs = float(var_smoothing if var_smoothing is not None else 1e-9)
    if not a > 0:
        raise ValueError('the smoothing alpha is positive')
    if not vs >= 0:
        raise ValueError('the variance smoothing is zero or more')
    spec = {**_roles(y, x, weight, freq, validation, portion, seed, missing), 'alpha': a, 'var_smoothing': vs}
    M = pv.cached('naivebayes', table, rows, spec, lambda: _nb_model(P, a, vs))
    return P, M


def _nb_parameters(P, M):
    """The model's numbers per factor, for the Class Parameters outline."""
    out = []
    for part in M['parts']:
        if part['skip']:
            out.append({'factor': part['name'], 'kind': part['kind'], 'rows': [], 'note': 'no training row has a value'})
            continue
        if part['kind'] == 'normal':
            rows = [{'level': lab, 'n': float(part['n'][c]), 'mean': float(part['mean'][c]), 'sd': float(math.sqrt(part['var'][c]))}
                    for c, lab in enumerate(P.labels)]
            out.append({'factor': part['name'], 'kind': 'normal', 'rows': rows})
        else:
            rows = []
            for c, lab in enumerate(P.labels):
                r = {'level': lab, 'n': float(part['count'][c].sum())}
                for j in range(part['ncat']):
                    r[f'p{j}'] = float(math.exp(part['logp'][c][j]))
                rows.append(r)
            out.append({'factor': part['name'], 'kind': 'levels', 'labels': part['labels'], 'rows': rows})
    return out


@api('naivebayes.fit', packages=SK)
def nb_fit(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
           alpha=1.0, var_smoothing=1e-9, table_name='data'):
    """Naive Bayes: Fit Details, confusion matrices, ROC and lift curves."""
    try:
        P, M = _nb_setup(table, rows, y, x, weight, freq, validation, portion, seed, missing, alpha, var_smoothing)
    except ValueError as e:
        return {'error': str(e)}
    frame = data.frame(P.table, P.x, P.index, dropna=False)
    prob = _nb_proba(P, M, _nb_features(P, frame), len(frame))
    rep = pv.report(P, prob, head='\n'.join(_nb_code(P, M, table_name, rows, graph=True)))
    notes = []
    absent = [lab for lab, c in zip(P.labels, M['count']) if not c > 0]
    if absent:
        notes.append(f'No training row has the level{"s" if len(absent) > 1 else ""} {", ".join(absent)}: {"their" if len(absent) > 1 else "its"} class share is 0, and so is {"their" if len(absent) > 1 else "its"} probability (at the smallest value kept, 1e-15).')
    out = {'kind': 'categorical', 'fit': rep, 'parameters': _nb_parameters(P, M), 'priors': [{'level': lab, 'n': float(c), 'share': float(s)} for lab, c, s in zip(P.labels, M['count'], M['share'])],
           'eps': M['eps'], 'alpha': M['alpha'], 'var_smoothing': M['var_smoothing'], 'notes': notes,
           'code': '\n'.join(_nb_code(P, M, table_name, rows))}
    if P.k:        # a K-fold Validation column: each fold predicted by the model fitted to the others
        feats = _nb_features(P, frame)
        cv = pv.crossvalidate(P, lambda fit_rows: _nb_proba(P, _nb_model(P, M['alpha'], M['var_smoothing'], fit_rows), feats, len(frame)))
        out['cv'] = {'measures': cv['measures'], 'folds': cv['folds'], 'k': P.k}
    return out


@api('naivebayes.formula', packages=SK)
def nb_formula(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
               alpha=1.0, var_smoothing=1e-9):
    """Save Prediction Formula: the model in the page's formula language, as live columns: a Log Score[level] per
    level (the log of the class share plus each factor's log density or log share, a factor a row lacks left out),
    Prob[level] = 1 / (the sum over the levels of Exp(Log Score[other] - Log Score[level])), kept between 1e-15
    and 1 - 1e-15 as the report keeps them, and the Most Likely level (of equal ones the first). With Informative
    Missing off, a row missing a factor gets no prediction, as Save Predicteds gives it none."""
    P, M = _nb_setup(table, rows, y, x, weight, freq, validation, portion, seed, missing, alpha, var_smoothing)
    L = len(P.levels)
    informative = P.missing == 'informative'
    enc = {e['name']: e for e in P.enc}
    terms = [[] for _ in range(L)]
    normals = [pt for pt in M['parts'] if pt['kind'] == 'normal']
    others = [pt for pt in M['parts'] if pt['kind'] != 'normal']
    for part in normals + others:          # the order _nb_proba adds them in
        if part['skip']:
            continue
        ref = formula_ref(part['of'] if part['kind'] != 'normal' else part['name'])
        for c in range(L):
            if part['kind'] == 'normal':
                mu, var = float(part['mean'][c]), float(part['var'][c])
                terms[c].append(f'If(Is Missing({ref}), 0, {formula_num(-0.5 * math.log(2 * math.pi * var))} - ({ref} - {formula_num(mu)}) ^ 2 / {formula_num(2 * var)})')
            elif part['name'] != part['of']:           # a continuous factor's Missing factor (present, missing)
                terms[c].append(f'If(Is Missing({ref}), {formula_num(part["logp"][c][1])}, {formula_num(part["logp"][c][0])})')
            else:
                e = enc[part['of']]
                numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in e['levels'])
                arms = ', '.join(f'{formula_num(v) if numeric else formula_str(v)}, {formula_num(part["logp"][c][j])}' for j, v in enumerate(e['levels']))
                miss = formula_num(part['logp'][c][len(e['levels'])]) if part['ncat'] > len(e['levels']) else '0'
                terms[c].append(f'If(Is Missing({ref}), {miss}, Match({ref}, {arms}, 0))')
    scores = []
    for c, lab in enumerate(P.labels):
        lp = M['log_prior'][c]
        head = formula_num(lp) if np.isfinite(lp) else '-1e300'
        expr = ' + '.join([head] + terms[c])
        if not informative:
            need = ' | '.join(f'Is Missing({formula_ref(nm)})' for nm in P.x)
            expr = f'If({need}, ., {expr})'
        scores.append({'name': f'Log Score[{lab}]', 'expr': expr})
    probs = []
    for c, lab in enumerate(P.labels):
        sc = formula_ref(scores[c]['name'])
        den = ' + '.join(f'Exp({formula_ref(scores[j]["name"])} - {sc})' for j in range(L))
        probs.append({'name': f'Prob[{lab}]', 'expr': f'Max({formula_num(EPS_P)}, Min({formula_num(1 - EPS_P)}, 1 / ({den})))'})
    vals = [v.item() if hasattr(v, 'item') else v for v in P.levels]
    lit = [formula_num(v) if isinstance(v, (float, int)) and not isinstance(v, bool) else formula_str(v) for v in vals]
    arms = []
    for c in range(L - 1):
        cond = ' & '.join(f'{formula_ref(probs[c]["name"])} >= {formula_ref(probs[j]["name"])}' for j in range(c + 1, L))
        arms.append(f'{cond}, {lit[c]}')
    most = {'name': f'Most Likely {P.y}', 'expr': f'If({", ".join(arms)}, {lit[L - 1]})', 'levels': vals,
            'ordinal': data.meta(P.table, P.y).get('modelingType') == 'ordinal'}
    return {'scores': scores, 'probs': probs, 'most': most, 'levels': list(P.labels)}


def _nb_code(P, M, table_name, rows, graph=False):
    """The code under the report; graph: the head of its graphs (matplotlib imported, no printing, fitted)."""
    L = P.code(table_name, rows=rows, extra_imports=[pv.PLT] if graph else [])
    L += ['',
          '# Naive Bayes: log P(level) plus, for every factor, log P(factor | level); a factor a row lacks is left out',
          'L = len(levels)',
          'wt = np.ones(len(d)) if w is None else w',
          'cls = [train & (y == c) for c in range(L)]',
          'share = np.array([wt[m].sum() for m in cls]) / wt[train].sum()   # the class shares, counted once',
          'with np.errstate(divide="ignore"):',
          '    logp = np.tile(np.log(share), (len(d), 1))']
    normals = [e for e in P.enc if e['type'] == 'continuous']
    if normals:
        L.append('normal = {   # the continuous factors: a normal density per level')
        for e in normals:
            nm = json.dumps(e['name'])
            L.append(f'    {nm}: pd.to_numeric(d[{nm}], errors="coerce").to_numpy(float),')
        L += ['}',
              'eps = ' + repr(float(M['var_smoothing'])) + ' * max((np.var(v[train & np.isfinite(v)]) for v in normal.values() if (train & np.isfinite(v)).any()), default=0.0)   # GaussianNB\'s var_smoothing',
              'for v in normal.values():',
              '    ok = np.isfinite(v)',
              '    if not (train & ok).any():',
              '        continue',
              '    for c in range(L):',
              '        m = cls[c] & ok',
              '        if not wt[m].sum() > 0:',
              '            m = train & ok   # a level with no values of this factor: its overall distribution',
              '        mu = np.average(v[m], weights=wt[m])',
              '        var = np.average((v[m] - mu) ** 2, weights=wt[m]) + eps',
              '        logp[ok, c] += -0.5 * np.log(2 * np.pi * var) - (v[ok] - mu) ** 2 / (2 * var)']
    cats = []
    informative = P.missing == 'informative'
    for e in P.enc:
        nm = json.dumps(e['name'])
        if e['type'] == 'continuous':
            if informative and e['indicator']:
                cats.append((f'{e["name"]} Missing', f'normal[{nm}]', None, 2))
        else:
            lv = '[' + ', '.join(pv._pylit(v) for v in e['levels']) + ']'
            numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in e['levels'])
            src = f'pd.to_numeric(d[{nm}], errors="coerce")' if numeric else f'd[{nm}].astype(object)'
            k = len(e['levels']) + (1 if informative and e['indicator'] else 0)
            cats.append((e['name'], src, lv, k))
    if cats:
        L.append(f'alpha = {float(M["alpha"])!r}   # the smoothing of the level shares (CategoricalNB\'s alpha)')
        L.append('levels_of = {   # the categorical factors: the level number (-1: left out) and the number of levels')
        for name, src, lv, k in cats:
            if lv is None:
                L.append(f'    {json.dumps(name)}: (np.isnan({src}).astype(int), 2),   # 1: missing')
            else:
                expr = f'pd.Categorical({src}, categories={lv}).codes.astype(int)'
                L.append(f'    {json.dumps(name)}: ({expr}, {k}),')
        L.append('}')
        for e in P.enc:
            if e['type'] != 'continuous' and informative and e['indicator']:
                nm = json.dumps(e['name'])
                L.append(f'levels_of[{nm}][0][d[{nm}].isna().to_numpy()] = {len(e["levels"])}   # a missing value is a level of its own (Informative Missing)')
        L += ['for code, k in levels_of.values():',
              '    ok = code >= 0',
              '    for c in range(L):',
              '        m = cls[c] & ok',
              '        n = np.bincount(code[m], weights=wt[m], minlength=k) + alpha',
              '        logp[ok, c] += np.log(n / n.sum())[code[ok]]']
    L += ['prob = np.exp(logp - logp.max(1, keepdims=True))',
          f'prob = np.clip(prob / prob.sum(1, keepdims=True), {EPS_P!r}, 1 - {EPS_P!r})',
          'most = prob.argmax(1)   # the most likely level']
    if graph:
        return L + ['fitted = prob   # each row\'s probability of every level']
    L += _print_sets_code(P, '"misclassification", np.average(most[m] != y[m], weights=wt[m]), "mean -log p", np.average(-np.log(prob[m, y[m]]), weights=wt[m])')
    return L


@api('naivebayes.save', packages=SK)
def nb_save(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
            alpha=1.0, var_smoothing=1e-9):
    """Save Predicteds: the level probabilities and the most likely level of
    every row the model can take (every row with Informative Missing)."""
    P, M = _nb_setup(table, rows, y, x, weight, freq, validation, portion, seed, missing, alpha, var_smoothing)
    frame = _ok_rows(P)
    prob = _nb_proba(P, M, _nb_features(P, frame), len(frame)) if len(frame) else np.zeros((0, len(P.levels)))
    return _saved_categorical(P, np.asarray(frame.index, dtype=int), prob)


def _nb_build(table, rows=None, y=None, x=(), weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
              alpha=1.0, var_smoothing=1e-9, **_):
    P, M = _nb_setup(table, rows, y, x, weight, freq, validation, portion, seed, missing, alpha, var_smoothing)

    def run(settings):
        prob = _nb_proba(P, M, _nb_features(P, P.frame_of(settings)), len(settings))
        return [{'name': f'Prob[{lab}]', 'pred': prob[:, j], 'lower': None, 'upper': None, 'bounded': True} for j, lab in enumerate(P.labels)]
    return profile.Predictor(P.factors(), run, _observed(P))


profile.expose('naivebayes', _nb_build, packages=SK)


# ===========================================================================
# SUPPORT VECTOR MACHINES
# ===========================================================================

KERNELS = {'rbf': 'Radial Basis Function', 'linear': 'Linear'}


def _svm_args(kernel, cost, gamma, points):
    kernel = kernel or 'rbf'
    if kernel not in KERNELS:
        raise ValueError(f'the kernel is rbf or linear, not {kernel!r}')
    try:
        c = float(cost if cost not in (None, '') else 1.0)
    except (TypeError, ValueError):
        raise ValueError(f'Cost is a positive number, not {cost!r}')
    if not c > 0 or not math.isfinite(c):
        raise ValueError('Cost is a positive number')
    g = None
    if gamma not in (None, ''):
        try:
            g = float(gamma)
        except (TypeError, ValueError):
            raise ValueError(f'Gamma is a positive number, not {gamma!r}')
        if not g > 0 or not math.isfinite(g):
            raise ValueError('Gamma is a positive number')
    pts = int(points or 20)
    if not 2 <= pts <= 200:
        raise ValueError('the tuning design has 2 to 200 points')
    return kernel, c, g, pts


def design_points(kernel, points, gamma0):
    """The tuning design: Cost from 0.1 to 1000 and Gamma from 1/100 to 10
    times its default, evenly on the log scale, crossed (about `points`
    pairs); the linear kernel has Cost alone, from 0.01 to 100."""
    if kernel == 'linear':
        return [(float(c), None) for c in np.logspace(-2, 2, points)]
    nc = max(2, int(round(math.sqrt(points * 5 / 4))))
    ng = max(2, int(round(points / nc)))
    return [(float(c), float(gamma0 * g)) for c in np.logspace(-1, 3, nc) for g in np.logspace(-2, 1, ng)]


def _svm_estimator(P, kernel, C, gamma, seed, probability):
    from sklearn.svm import SVC, SVR
    g = gamma if gamma is not None else 'scale'
    if P.kind == 'categorical':
        return SVC(kernel=kernel, C=C, gamma=g, probability=probability, random_state=seed)
    return SVR(kernel=kernel, C=C, gamma=g, epsilon=0.1)


def _svm_folds(P, seed):
    """Where the tuning design is judged: the validation rows, or with none
    5-fold cross-validation of the training rows (stratified by level for a
    categorical response when every level has 5 rows), from the seed."""
    tr = np.flatnonzero(P.train())
    if P.has(1):
        return [(tr, np.flatnonzero(P.mask(1)))], 'validation'
    if P.k:        # the folds of a K-fold Validation column
        return [(np.flatnonzero(f), np.flatnonzero(h)) for f, h in pv.fold_masks(P)], f'the {P.k} folds of the Validation column'
    from sklearn.model_selection import KFold, StratifiedKFold
    if len(tr) < 10:
        raise ValueError('the tuning design needs validation rows, or at least 10 training rows for 5-fold cross-validation')
    yt = P.target[tr]
    if P.kind == 'categorical' and np.unique(yt, return_counts=True)[1].min() >= 5:
        sp = StratifiedKFold(n_splits=5, shuffle=True, random_state=seed).split(tr, yt)
        how = 'stratified 5-fold cross-validation'
    else:
        sp = KFold(n_splits=5, shuffle=True, random_state=seed).split(tr)
        how = '5-fold cross-validation'
    return [(tr[a], tr[b]) for a, b in sp], how


def _svm_setup(table, rows, y, x, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
               kernel='rbf', cost=1.0, gamma=None, tune=False, points=20, **_):
    P = _prepare(table, y, x, rows, weight=weight, freq=freq, validation=validation, portion=portion, seed=seed, missing=missing)
    kernel, C, G, pts = _svm_args(kernel, cost, gamma, points)
    tr = P.train()
    if P.kind == 'categorical' and len(np.unique(P.target[tr])) < 2:
        raise ValueError(f'the training rows have one level of {y}: nothing to separate')
    spec = {**_roles(y, x, weight, freq, validation, portion, seed, missing), 'kernel': kernel, 'cost': C, 'gamma': G,
            'tune': bool(tune), 'points': pts}
    M = pv.cached('svm', table, rows, spec, lambda: _svm_model(P, kernel, C, G, bool(tune), pts, pv.seed_of(seed)))
    return P, M


def _svm_model(P, kernel, C, G, tune, pts, seed):
    center, scale = _scaling(P)
    Z = (P.X - center) / scale
    tr = P.train()
    gamma0 = 1.0 / Z.shape[1]
    gamma = G if G is not None else gamma0
    wt = P.weights()
    sw = None if P.w is None else P.w[tr]
    ym, ys = 0.0, 1.0
    if P.kind == 'continuous':
        ym = float(np.mean(P.target[tr]))
        ys = float(np.std(P.target[tr], ddof=1)) if tr.sum() > 1 else 0.0
        ys = ys if ys > 0 else 1.0
    tuning = None
    if tune:
        design = design_points(kernel, pts, gamma0)
        folds, how = _svm_folds(P, seed)
        results = []
        for i, (c, g) in enumerate(design):
            wrong, sq, tot = 0.0, 0.0, 0.0
            failed = None
            for a, b in folds:
                est = _svm_estimator(P, kernel, c, g if g is not None else gamma0, seed, False)
                try:
                    if P.kind == 'categorical':
                        est.fit(Z[a], P.target[a], sample_weight=None if P.w is None else P.w[a])
                        pred = est.predict(Z[b])
                        wrong += float(np.sum(wt[b] * (pred != P.target[b])))
                    else:
                        est.fit(Z[a], (P.target[a] - ym) / ys, sample_weight=None if P.w is None else P.w[a])
                        pred = ym + ys * est.predict(Z[b])
                        sq += float(np.sum(wt[b] * (P.target[b] - pred) ** 2))
                except ValueError as e:        # a fold with one level
                    failed = str(e)
                    break
                tot += float(np.sum(wt[b]))
            crit = None if failed else (wrong / tot if P.kind == 'categorical' else math.sqrt(sq / tot))
            results.append({'cost': c, 'gamma': g, 'crit': crit})
            if len(design) > 1:
                print(f'smui:progress svm {i + 1} {len(design)}', flush=True)
        ok = [r for r in results if r['crit'] is not None]
        if not ok:
            raise ValueError('no point of the tuning design could be fitted')
        # the smallest criterion; of equal ones the smaller Cost, then the smaller Gamma
        best = min(ok, key=lambda r: (r['crit'], r['cost'], r['gamma'] or 0.0))
        C, gamma = best['cost'], (best['gamma'] if best['gamma'] is not None else gamma0)
        tuning = {'design': results, 'how': how, 'best': results.index(best), 'gamma0': gamma0}
    model = _svm_estimator(P, kernel, C, gamma, seed, True)
    if P.kind == 'categorical':
        model.fit(Z[tr], P.target[tr], sample_weight=sw)
    else:
        model.fit(Z[tr], (P.target[tr] - ym) / ys, sample_weight=sw)
    return {'model': model, 'center': center, 'scale': scale, 'kernel': kernel, 'C': C, 'gamma': gamma, 'gamma0': gamma0,
            'ym': ym, 'ys': ys, 'tuning': tuning, 'seed': seed}


def _svm_z(M, X):
    return (X - M['center']) / M['scale']


def _svm_fitted(P, M, X):
    """Probabilities (categorical) or predictions (continuous) for rows X."""
    Z = _svm_z(M, X)
    if P.kind == 'categorical':
        return P.proba(M['model'], Z)
    return M['ym'] + M['ys'] * M['model'].predict(Z)


@api('svm.fit', packages=SK)
def svm_fit(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
            kernel='rbf', cost=1.0, gamma=None, tune=False, points=20, keep=None, table_name='data'):
    """Support Vector Machines: Model Summary, Fit Details and the rest; the
    tuning design when asked. keep: the page's key to keep the fitted model
    under (Score Rows)."""
    try:
        P, M = _svm_setup(table, rows, y, x, weight, freq, validation, portion, seed, missing, kernel, cost, gamma, tune, points)
    except ValueError as e:
        return {'error': str(e)}
    m = M['model']
    fitted = _svm_fitted(P, M, P.X)
    rep = pv.report(P, fitted, head='\n'.join(_svm_code(P, M, table_name, rows, graph=True)))
    if M['tuning']:
        rep['plots']['tuning'] = _svm_tuning_tail(P, M)
    tr = P.train()
    summary = {'kernel': M['kernel'], 'kernel_label': KERNELS[M['kernel']], 'cost': M['C'], 'gamma': M['gamma'] if M['kernel'] == 'rbf' else None,
               'gamma0': M['gamma0'], 'n_sv': int(len(m.support_)), 'n_train': int(tr.sum()), 'n_columns': int(P.X.shape[1]), 'seed': M['seed']}
    if P.kind == 'categorical':
        summary['sv_per_level'] = [{'level': P.labels[int(c)], 'n': int(k)} for c, k in zip(m.classes_, m.n_support_)]
        dec = m.predict(_svm_z(M, P.X))
        summary['differs'] = int(np.sum(dec != np.argmax(fitted, axis=1)))
    else:
        summary['epsilon'] = float(m.epsilon)
        summary['ym'], summary['ys'] = M['ym'], M['ys']
    out = {'kind': P.kind, 'fit': rep, 'summary': summary, 'features': list(P.features),
           'continuous': [e['name'] for e in P.enc if e['type'] == 'continuous'],
           'code': '\n'.join(_svm_code(P, M, table_name, rows))}
    if M['tuning']:
        t = M['tuning']
        out['tuning'] = {'rows': t['design'], 'how': t['how'], 'best': t['best'], 'gamma0': t['gamma0'],
                         'label': ('Misclassification Rate' if P.kind == 'categorical' else 'RASE')}
    pv.keep(keep, {'kind': 'svm', 'P': P, 'M': M})
    return out


@api('svm.score', packages=SK)
def svm_score(table, keep=None, source=None, target_rows=None, y=None, x=None, rows=None, weight=None, freq=None, validation=None, portion=0.0,
              seed=None, missing='informative', kernel='rbf', cost=1.0, gamma=None, tune=False, points=20):
    """Score Rows: the report's model (kept under keep) on rows of a table (another open table, or the report's own
    with rows added since; target_rows: those rows, None for all). Without the kept model it is fitted again from
    the source table as it is now."""
    K_ = pv.kept(keep)
    note = None
    if K_ is None or K_.get('kind') != 'svm':
        P, M = _svm_setup(source or table, rows, y, x, weight, freq, validation, portion, seed, missing, kernel, cost, gamma, tune, points)
        note = 'The model was fitted again (the engine had not kept it): on the report\'s table as it is now.'
    else:
        P, M = K_['P'], K_['M']
    X, rws = pv.score_frame(P, table, target_rows)
    f = _svm_fitted(P, M, X) if len(rws) else (np.zeros((0, len(P.levels))) if P.kind == 'categorical' else np.zeros(0))
    if P.kind == 'categorical':
        out = _saved_categorical(P, rws, f)
    else:
        out = {'rows': [int(r) for r in rws], 'values': np.asarray(f, dtype=float).tolist(), 'name': f'Predicted {P.y}'}
    out['note'] = note
    return out


def _svm_code(P, M, table_name, rows, graph=False):
    """The code under the report; graph: the head of its graphs (matplotlib imported, no printing, fitted)."""
    cat = P.kind == 'categorical'
    kernel = M['kernel']
    L = P.code(table_name, rows=rows, extra_imports=[pv.PLT] if graph else [])
    L += [''] + _scale_code(P) + ['']
    cls = 'SVC' if cat else 'SVR'
    wtr = 'None if w is None else w[train]'
    seed = M['seed']
    L.append(f'from sklearn.svm import {cls}')
    if not cat:
        L += ['ym, ys = y[train].mean(), y[train].std(ddof=1)   # the response standardized too (epsilon 0.1 is on that scale)',
              'ys = ys if ys > 0 else 1.0']
    if M['tuning']:
        t = M['tuning']
        folds_how = t['how']
        L += ['', f'# the tuning design: each Cost{" and Gamma" if kernel == "rbf" else ""} judged by {folds_how}',
              'wt = np.ones(len(d)) if w is None else w',
              f'gamma0 = 1 / Z.shape[1]']
        if kernel == 'rbf':
            nc = len({r['cost'] for r in t['design']})
            ng = len({r['gamma'] for r in t['design']})
            L.append(f'design = [(c, gamma0 * g) for c in np.logspace(-1, 3, {nc}) for g in np.logspace(-2, 1, {ng})]')
        else:
            L.append(f'design = [(c, None) for c in np.logspace(-2, 2, {len(t["design"])})]')
        if P.has(1):
            L.append('splits = [(np.flatnonzero(train), np.flatnonzero(sets == 1))]   # the validation rows')
        elif P.k:
            L.append(f'splits = [(np.flatnonzero(folds != j), np.flatnonzero(folds == j)) for j in range({P.k})]   # the folds of the Validation column')
        else:
            tr_idx = 'np.flatnonzero(train)'
            if folds_how.startswith('stratified'):
                L += ['from sklearn.model_selection import StratifiedKFold',
                      f'tr = {tr_idx}',
                      f'splits = [(tr[a], tr[b]) for a, b in StratifiedKFold(n_splits=5, shuffle=True, random_state={seed}).split(tr, y[tr])]']
            else:
                L += ['from sklearn.model_selection import KFold',
                      f'tr = {tr_idx}',
                      f'splits = [(tr[a], tr[b]) for a, b in KFold(n_splits=5, shuffle=True, random_state={seed}).split(tr)]']
        L += ['results = []',
              'for c, g in design:',
              '    err, tot = 0.0, 0.0',
              '    for a, b in splits:',
              f'        est = {cls}(kernel="{kernel}", C=c, gamma=gamma0 if g is None else g{", probability=False, random_state=" + str(seed) if cat else ", epsilon=0.1"})']
        if cat:
            L += ['        pred = est.fit(Z[a], y[a], sample_weight=None if w is None else w[a]).predict(Z[b])',
                  '        err += np.sum(wt[b] * (pred != y[b]))']
        else:
            L += ['        pred = ym + ys * est.fit(Z[a], (y[a] - ym) / ys, sample_weight=None if w is None else w[a]).predict(Z[b])',
                  '        err += np.sum(wt[b] * (y[b] - pred) ** 2)']
        L += ['        tot += np.sum(wt[b])',
              f'    results.append(({"err / tot" if cat else "np.sqrt(err / tot)"}, c, 0.0 if g is None else g))',
              *([] if graph else ['    print("design", c, g, results[-1][0])']),
              'crit, C, gamma = min(results)   # the smallest; of equal ones the smaller Cost, then Gamma',
              'gamma = gamma if gamma > 0 else gamma0',
              '']
        cg = 'C=C, gamma=gamma'
    else:
        cg = f'C={M["C"]!r}, gamma={M["gamma"]!r}'
    if cat:
        L += [f'svm = SVC(kernel="{kernel}", {cg}, probability=True, random_state={seed})   # probability: Platt scaling fitted by 5-fold cross-validation inside libsvm, from the seed',
              f'svm.fit(Z[train], y[train], sample_weight={wtr})',
              'prob = np.zeros((len(d), len(levels)))',
              'prob[:, svm.classes_] = svm.predict_proba(Z)',
              'most = prob.argmax(1)   # the most likely level: the largest probability (svm.predict, from the decision function, can differ near the boundary)',
              'wt = np.ones(len(d)) if w is None else w']
        if graph:
            return L + ['fitted = prob   # each row\'s probability of every level']
        L += _print_sets_code(P, '"misclassification", np.average(most[m] != y[m], weights=wt[m]), "mean -log p", np.average(-np.log(np.clip(prob[m, y[m]], 1e-15, 1)), weights=wt[m])')
    else:
        L += [f'svm = SVR(kernel="{kernel}", {cg}, epsilon=0.1).fit(Z[train], (y[train] - ym) / ys, sample_weight={wtr})',
              'pred = ym + ys * svm.predict(Z)',
              'wt = np.ones(len(d)) if w is None else w']
        if graph:
            return L + ['fitted = pred   # each row\'s prediction']
        L += _print_sets_code(P, '"RASE", np.sqrt(np.average((y[m] - pred[m]) ** 2, weights=wt[m]))')
    return L


RAMP = ['#cde2fb', '#9ec5f4', '#6da7ec', '#3987e5', '#256abf', '#184f95', '#0d366b']   # smui-p-learners.js ramp(), light theme


def _svm_tuning_tail(P, M):
    """The tuning design's plot: each Cost and Gamma coloured by its criterion (the radial basis function)
    or the criterion by Cost (linear), the best marked; the design as the head ran it (results)."""
    t = M['tuning']
    what = 'Misclassification Rate' if P.kind == 'categorical' else 'RASE'
    judged = 'Validation' if t['how'] == 'validation' else 'Cross-Validated'
    L = ['crit_, cost_, gamma_ = (np.array(v, dtype=float) for v in zip(*results))   # each design point\'s criterion, Cost and Gamma']
    if M['kernel'] == 'rbf':
        L += ['from matplotlib.colors import LinearSegmentedColormap',
              f'ramp = LinearSegmentedColormap.from_list("ramp", {json.dumps(RAMP)})',
              pv.figure(400, 320),
              'sc = ax.scatter(cost_, gamma_, c=crit_, cmap=ramp, marker="s", s=75, edgecolors="#fcf7f2", linewidths=0.7)',
              f'ax.scatter([C], [gamma], marker="s", s=150, facecolors="none", edgecolors="{pv.TEXT}", linewidths=1.5)   # the best, fitted again',
              f'fig.colorbar(sc, ax=ax, label="{what}")',
              'ax.set_xscale("log")', 'ax.set_yscale("log")', 'ax.set_xlabel("Cost")', 'ax.set_ylabel("Gamma")']
    else:
        L += [pv.figure(400, 300),
              f'ax.plot(cost_, crit_, color="{HUES[0]}", linewidth=2, marker="o", markersize=5.6)',
              f'ax.plot([C], [crit], linestyle="none", marker="o", markersize=11, markerfacecolor="none", markeredgecolor="{pv.TEXT}", markeredgewidth=1.5)   # the best, fitted again',
              'ax.set_xscale("log")', 'ax.set_ylim(bottom=0)', 'ax.set_xlabel("Cost")', f'ax.set_ylabel("{judged} {what}")']
    L += ['ax.set_title("Tuning design")', 'plt.show()']
    return '\n'.join(L)


@api('svm.boundary', packages=SK)
def svm_boundary(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
                 kernel='rbf', cost=1.0, gamma=None, tune=False, points=20, pair=None, current=None, m=61, plot=None, table_name='data'):
    """The decision function (two levels), the most likely level (more) or
    the prediction (a continuous response) over a grid of two continuous
    factors, the other factors at their current values (as the profiler
    holds them: the mean, the first level), and the rows on it."""
    P, M = _svm_setup(table, rows, y, x, weight, freq, validation, portion, seed, missing, kernel, cost, gamma, tune, points)
    conts = [e for e in P.enc if e['type'] == 'continuous']
    if len(conts) < 2:
        raise ValueError('the decision boundary needs two continuous factors')
    names = [e['name'] for e in conts]
    pr = [c for c in (pair or []) if c in names][:2]
    if len(pr) < 2 or pr[0] == pr[1]:
        pr = names[:2]
    a, b = pr
    fac = P.factors()
    cur = profile.setting(fac, current)
    frame = data.frame(P.table, [a, b], P.index, dropna=False)
    va = pd.to_numeric(frame[a], errors='coerce').to_numpy(float)
    vb = pd.to_numeric(frame[b], errors='coerce').to_numpy(float)
    m = int(max(11, min(151, m or 61)))

    def span(v):
        v = v[np.isfinite(v)]
        lo, hi = float(np.min(v)), float(np.max(v))
        pad = 0.04 * (hi - lo) if hi > lo else 0.5
        return np.linspace(lo - pad, hi + pad, m)
    gx, gy = span(va), span(vb)
    XX, YY = np.meshgrid(gx, gy)
    settings = []
    for u, v in zip(XX.ravel(), YY.ravel()):
        s = dict(cur)
        s[a], s[b] = float(u), float(v)
        settings.append(s)
    Xg = P.encode_settings(settings)
    Zg = _svm_z(M, Xg)
    model = M['model']
    held = [{'name': f['name'], 'value': cur[f['name']] if f['type'] == 'continuous' else pv.level_label(cur[f['name']])}
            for f in fac if f['name'] not in (a, b)]
    out = {'pair': [a, b], 'x': gx.tolist(), 'y': gy.tolist(), 'kind': P.kind, 'levels': list(P.labels), 'held': held}
    if P.kind == 'categorical':
        prob = P.proba(model, Zg)
        out['most'] = np.argmax(prob, axis=1).reshape(m, m).tolist()
        out['pmax'] = np.max(prob, axis=1).reshape(m, m).tolist()
        if len(model.classes_) == 2:
            out['decision'] = model.decision_function(Zg).reshape(m, m).tolist()
            out['positive'] = P.labels[int(model.classes_[1])]
            out['negative'] = P.labels[int(model.classes_[0])]
    else:
        out['pred'] = (M['ym'] + M['ys'] * model.predict(Zg)).reshape(m, m).tolist()
    sv = np.zeros(len(P.index), dtype=bool)
    sv[np.flatnonzero(P.train())[model.support_]] = True
    ok = np.isfinite(va) & np.isfinite(vb)
    out['points'] = {'rows': P.index[ok].tolist(), 'x': va[ok].tolist(), 'y': vb[ok].tolist(), 'set': P.sets[ok].tolist(),
                     'value': P.target[ok].tolist(), 'sv': sv[ok].tolist()}
    out['n_missing'] = int((~ok).sum())
    held_py = ', '.join(f'{json.dumps(k)}: {pv._pylit(v)}' for k, v in cur.items() if k not in (a, b))
    lines = ['# the decision boundary: run the Support Vector Machines code first (it makes encode, svm, center, scale)',
             f'gx = np.linspace({float(gx[0])!r}, {float(gx[-1])!r}, {m})',
             f'gy = np.linspace({float(gy[0])!r}, {float(gy[-1])!r}, {m})',
             'XX, YY = np.meshgrid(gx, gy)',
             f'held = {{{held_py}}}   # the other factors, at their current values' if held_py else 'held = {}',
             f'grid = pd.DataFrame({{**{{k: [v] * XX.size for k, v in held.items()}}, {json.dumps(a)}: XX.ravel(), {json.dumps(b)}: YY.ravel()}})',
             'Zg = (encode(grid) - center) / scale']
    if P.kind == 'categorical':
        lines += ['pg = np.zeros((len(grid), len(levels)))', 'pg[:, svm.classes_] = svm.predict_proba(Zg)',
                  'most_grid = pg.argmax(1).reshape(XX.shape)   # the most likely level at each point']
        if len(model.classes_) == 2:
            lines.append('dec = svm.decision_function(Zg).reshape(XX.shape)   # 0 on the boundary, -1 and 1 on the margins')
    else:
        lines.append('pred_grid = (ym + ys * svm.predict(Zg)).reshape(XX.shape)')
    out['code'] = '\n'.join(lines)
    out['plot_code'] = _boundary_tail(P, M, a, b, m, cur, held_py, len(model.classes_) == 2 if P.kind == 'categorical' else False,
                                      plot or {})
    return out


def _boundary_tail(P, M, a, b, m, cur, held_py, two, plot):
    """The decision boundary (or the prediction surface) over two continuous factors, after the head: the
    grid over the rows' ranges, the model on it with the other factors held, the rows on it (filled:
    training, open: the others), the support vectors ringed (Support Vectors in the red triangle)."""
    J = json.dumps
    cat = P.kind == 'categorical'
    rings = plot.get('sv', cat) is not False
    L = [f'# the {"decision boundary" if cat else "prediction surface"} over {a} and {b}, the other factors held',
         f'va, vb = pd.to_numeric(d[{J(a)}], errors="coerce").to_numpy(float), pd.to_numeric(d[{J(b)}], errors="coerce").to_numpy(float)', '', '',
         'def span(v):',
         '    """The grid over the rows\' range, with 4% more at each end."""',
         '    v = v[np.isfinite(v)]',
         '    pad = 0.04 * (v.max() - v.min()) if v.max() > v.min() else 0.5',
         f'    return np.linspace(v.min() - pad, v.max() + pad, {m})', '', '',
         'gx, gy = span(va), span(vb)',
         'XX, YY = np.meshgrid(gx, gy)',
         f'held = {{{held_py}}}   # the other factors, at the Prediction Profiler\'s current values (the means and the first levels until moved)' if held_py else 'held = {}',
         f'grid = pd.DataFrame({{**{{k: [v] * XX.size for k, v in held.items()}}, {J(a)}: XX.ravel(), {J(b)}: YY.ravel()}})',
         'Zg = (encode(grid) - center) / scale',
         f'colors, markers = {J(HUES)}, {J(MARKERS)}',
         'ok = np.isfinite(va) & np.isfinite(vb)   # the rows with both',
         'sv = np.zeros(len(d), dtype=bool)',
         'sv[np.flatnonzero(train)[svm.support_]] = True   # the training rows that are support vectors',
         'from matplotlib.colors import LinearSegmentedColormap, ListedColormap',
         'from matplotlib.lines import Line2D',
         pv.figure(500, 440),
         'extent = (gx[0], gx[-1], gy[0], gy[-1])',
         'handles = []']
    if cat and two:
        L += ['pg = np.zeros((len(grid), len(levels)))', 'pg[:, svm.classes_] = svm.predict_proba(Zg)',
              'dec = svm.decision_function(Zg).reshape(XX.shape)   # 0 on the boundary, -1 and 1 on the margins',
              'neg, pos = colors[int(svm.classes_[0])], colors[int(svm.classes_[1])]   # toward the second level where positive',
              'ax.imshow(np.clip(dec, -2.5, 2.5), extent=extent, origin="lower", aspect="auto", cmap=LinearSegmentedColormap.from_list("dec", [neg, "#fcf7f2", pos]), vmin=-2.5, vmax=2.5, alpha=0.24, interpolation="bilinear")',
              f'ax.contour(gx, gy, dec, levels=[0], colors="{pv.TEXT}", linewidths=1.44)',
              f'ax.contour(gx, gy, dec, levels=[-1, 1], colors="{pv.MUTED}", linewidths=0.86, linestyles="--")',
              f'handles += [Line2D([], [], color="{pv.TEXT}", linewidth=1.44, label="Boundary"), Line2D([], [], color="{pv.MUTED}", linewidth=0.86, linestyle="--", label="Margins (±1)")]']
    elif cat:
        L += ['pg = np.zeros((len(grid), len(levels)))', 'pg[:, svm.classes_] = svm.predict_proba(Zg)',
              'most_grid = pg.argmax(1).reshape(XX.shape)   # the most likely level at each point',
              'ax.imshow(most_grid, extent=extent, origin="lower", aspect="auto", cmap=ListedColormap(colors[:len(levels)]), vmin=-0.5, vmax=len(levels) - 0.5, alpha=0.24, interpolation="nearest")']
    else:
        L += ['pred_grid = (ym + ys * svm.predict(Zg)).reshape(XX.shape)',
              f'ramp = LinearSegmentedColormap.from_list("ramp", {J(RAMP)})',
              'im = ax.imshow(pred_grid, extent=extent, origin="lower", aspect="auto", cmap=ramp, alpha=0.45, interpolation="bilinear")',
              'cs = ax.contour(gx, gy, pred_grid, colors="#fcf7f2", linewidths=0.43)',
              f'ax.clabel(cs, fontsize=6.8, colors="{pv.TEXT}")',
              f'fig.colorbar(im, ax=ax, label={J(P.y)})']
    if cat:
        L += ['for j, name in enumerate(levels):',
              '    for train_rows, face in ((True, True), (False, False)):',
              '        r = ok & (y == j) & (train == train_rows)',
              '        if r.any():',
              '            ax.scatter(va[r], vb[r], s=34, marker=markers[j % len(markers)], facecolors=colors[j % len(colors)] if face else "none", edgecolors=colors[j % len(colors)] if not face else "#fcf7f2", linewidths=0.8)',
              '    if (ok & (y == j)).any():',
              '        handles.append(Line2D([], [], linestyle="none", marker=markers[j % len(markers)], color=colors[j % len(colors)], label=str(name)))']
    else:
        L += ['for train_rows, face in ((True, True), (False, False)):',
              '    r = ok & (train == train_rows)',
              '    if r.any():',
              f'        ax.scatter(va[r], vb[r], s=26, marker="o", facecolors="{pv.TEXT}" if face else "none", edgecolors="{pv.TEXT}" if not face else "#fcf7f2", linewidths=0.6)',
              f'handles.append(Line2D([], [], linestyle="none", marker="o", color="{pv.TEXT}", label="Rows"))']
    if rings:
        L += ['if (sv & ok).any():',
              f'    ax.scatter(va[sv & ok], vb[sv & ok], s=100, facecolors="none", edgecolors="{pv.MUTED}", linewidths=0.72)   # Support Vectors',
              f'    handles.append(Line2D([], [], linestyle="none", marker="o", markersize=8, markerfacecolor="none", color="{pv.MUTED}", label="Support vectors"))']
    L += ['ax.set_xlim(gx[0], gx[-1])', 'ax.set_ylim(gy[0], gy[-1])',
          f'ax.set_xlabel({J(a)})', f'ax.set_ylabel({J(b)})',
          f'ax.set_title({J(("Decision boundary" if cat else "Prediction surface") + " over " + a + " and " + b)}, wrap=True)',
          'fig.legend(handles=handles, loc="outside upper left", ncols=4, frameon=False, fontsize=8)',
          'plt.show()']
    return '\n'.join(L)


@api('svm.save', packages=SK)
def svm_save(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
             kernel='rbf', cost=1.0, gamma=None, tune=False, points=20):
    """Save Predicteds (continuous) or the probabilities and the most likely
    level (categorical), for every row the model can take."""
    P, M = _svm_setup(table, rows, y, x, weight, freq, validation, portion, seed, missing, kernel, cost, gamma, tune, points)
    return pv.saved(P, lambda X: _svm_fitted(P, M, X), lambda X: _svm_fitted(P, M, X))


def _svm_build(table, rows=None, y=None, x=(), weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
               kernel='rbf', cost=1.0, gamma=None, tune=False, points=20, **_):
    P, M = _svm_setup(table, rows, y, x, weight, freq, validation, portion, seed, missing, kernel, cost, gamma, tune, points)
    return pv.predictor(P, M['model'], predict=lambda X: _svm_fitted(P, M, X), proba=lambda X: _svm_fitted(P, M, X))


profile.expose('svm', _svm_build, packages=SK)
