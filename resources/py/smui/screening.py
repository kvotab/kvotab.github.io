"""Analyze > Predictive Modeling > Model Screening, and Make Validation Column.

Model Screening fits many kinds of predictive model to one response, with
the same rows, the same holdback and the same seed, and puts their Measures
of Fit side by side, as JMP Pro's platform does:

  Decision Tree             best-first splits (DecisionTreeClassifier/Regressor)
  Bootstrap Forest          RandomForestClassifier/Regressor
  Boosted Tree              GradientBoostingClassifier/Regressor
  K Nearest Neighbors       NearestNeighbors on standardized columns
  Naive Bayes               GaussianNB with CategoricalNB (categorical Y)
  Neural                    MLPClassifier/Regressor, three tanh nodes
  Support Vector Machines   SVC (with Platt's sigmoid) or SVR, RBF kernel
  Discriminant              linear discriminant analysis (categorical Y)
  Fit Least Squares, or Nominal / Ordinal Logistic
  Generalized Regression    the lasso and elastic net paths
  Fit Stepwise              forward selection by BIC

Each fitter is a plain function of the predictor matrix that
predictive.prepare() makes (X, y, w and the sets); it returns a function of
new rows that gives the prediction, or the probability of every level, and a
line about what it chose. The same functions are the Python shown under the
report (inspect.getsource), so the code gives the report's numbers.

A method that tunes something (the tree's number of splits, K, the penalty,
the number of trees or layers) tunes it on the validation rows when there
are any. Without them it uses a rule of its own (crossvalidation within the
training rows, leave-one-out, a holdback, AICc or BIC), so that K-fold
crossvalidation of a whole method is honest: the held-out fold never tunes.

Make Validation Column gives every row of the table a set, training,
validation or test: at random, stratified, by groups, or by a time cutpoint,
in whole numbers of rows that match the proportions (see split_counts and
stratum_counts).
"""
import copy
import json
import math
import time
import warnings

import numpy as np

from . import data, predictive as pv
from .profile import expose
from .registry import api
from .util import code_head

SETS = pv.SETS
CV = 'Crossvalidation'

# key, label, and for categorical responses only
METHODS = [('tree', 'Decision Tree'), ('forest', 'Bootstrap Forest'), ('boosted', 'Boosted Tree'), ('knn', 'K Nearest Neighbors'),
           ('nb', 'Naive Bayes'), ('neural', 'Neural'), ('svm', 'Support Vector Machines'), ('lda', 'Discriminant'),
           ('linear', 'Fit Least Squares'), ('lasso', 'Generalized Regression Lasso'), ('enet', 'Generalized Regression Elastic Net'),
           ('stepwise', 'Fit Stepwise')]
LABEL = dict(METHODS)
CATEGORICAL_ONLY = {'nb', 'lda'}
DEFAULT = [k for k, _ in METHODS if k != 'stepwise']
USES = {'tree': 'sklearn.tree.DecisionTreeClassifier/Regressor', 'forest': 'sklearn.ensemble.RandomForestClassifier/Regressor',
        'boosted': 'sklearn.ensemble.GradientBoostingClassifier/Regressor', 'knn': 'sklearn.neighbors.NearestNeighbors',
        'nb': 'sklearn.naive_bayes.GaussianNB, CategoricalNB', 'neural': 'sklearn.neural_network.MLPClassifier/Regressor',
        'svm': 'sklearn.svm.SVC, SVR', 'lda': 'numpy, scipy.linalg.pinvh', 'linear': 'sklearn.linear_model.LinearRegression, LogisticRegression; scipy.optimize',
        'lasso': 'sklearn.linear_model.enet_path, LogisticRegression (saga)', 'enet': 'sklearn.linear_model.enet_path, LogisticRegression (saga)',
        'stepwise': 'numpy.linalg.lstsq, sklearn.linear_model.LogisticRegression'}
# the measures of the Summary Across the Models, and which way is better
SUMMARY = {'continuous': ['rsquare', 'rase'], 'categorical': ['entropy_rsquare', 'misclassification', 'auc']}
HIGHER = {'rsquare', 'entropy_rsquare', 'generalized_rsquare', 'auc'}
SPEC = ('y', 'x', 'weight', 'freq', 'validation', 'portion', 'seed', 'missing', 'kfold')


# ============================================================================
# the helpers every fitter uses (shown in the code under the report)
# ============================================================================

def weighted_scaler(A, w=None):
    """Each column's (weighted) mean and standard deviation; a constant column gets 1."""
    A = np.asarray(A, dtype=float)
    wt = np.ones(len(A)) if w is None else np.asarray(w, dtype=float)
    center = wt @ A / wt.sum()
    scale = np.sqrt(wt @ (A - center) ** 2 / wt.sum())
    scale[~(scale > 1e-12)] = 1.0
    return center, scale


def level_shares(y, w, n_levels):
    """The (weighted) share of each level of y."""
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    s = np.bincount(np.asarray(y, dtype=int), weights=wt, minlength=n_levels)[:n_levels]
    return s / s.sum()


def loss(y, f, w, n_levels):
    """What tuning makes small: the (weighted) sum of squared errors, or of -log p of the actual level."""
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    if not n_levels:
        return float(np.sum(wt * (y - f) ** 2))
    p = f[np.arange(len(y)), np.asarray(y, dtype=int)]
    return float(-np.sum(wt * np.log(np.clip(p, 1e-15, 1.0))))


def full_proba(p, classes, n_levels):
    """The probabilities of the levels a model saw, among all the levels (0 for a level with no training rows)."""
    out = np.zeros((len(p), n_levels))
    out[:, np.asarray(classes, dtype=int)] = p
    return out


def smooth_counts(counts, share):
    """Level rates with a prior of one row spread as the training shares: never exactly 0 or 1."""
    return (counts + share) / (counts.sum(axis=1, keepdims=True) + 1.0)


def linear_columns(factors):
    """The columns of X for the models with an intercept: each categorical factor's last level left out."""
    cols = []
    for f in factors:
        cols += f['cols'][:-1] if f['kind'] == 'categorical' else f['cols']
        if f['missing'] is not None:
            cols.append(f['missing'])
    return cols


def inner_folds(train, k, seed):
    """A fold number from 0 to k - 1 for each training row, from the seed (-1 for the other rows)."""
    idx = np.flatnonzero(train)
    fold = np.full(len(train), -1)
    fold[idx[np.random.default_rng(seed).permutation(len(idx))]] = np.arange(len(idx)) % k
    return fold


def tree_paths(model, Xq):
    """Each row's path through a fitted tree: its node numbers from the root, padded with a number above every node."""
    dp = model.decision_path(np.asarray(Xq, dtype=np.float32)).tocsr()
    n = dp.shape[0]
    lens = np.diff(dp.indptr)
    M = np.full((n, max(1, int(lens.max()) if n else 1)), model.tree_.node_count)
    M[np.repeat(np.arange(n), lens), np.arange(dp.indptr[-1]) - np.repeat(dp.indptr[:-1], lens)] = dp.indices
    return np.sort(M, axis=1)


def leaf_after(paths, s):
    """The leaf of each row after s best-first splits: sklearn numbers the nodes in the order its best-first
    splits make them, so the tree after s splits is nodes 0 to 2s, and a row's leaf is the deepest of those
    on its path."""
    k = (paths <= 2 * s).sum(axis=1) - 1
    return paths[np.arange(len(paths)), k]


def platt(F, positive, w=None):
    """Platt's sigmoid P = 1/(1 + exp(a F + b)) for decision values F, fitted as scikit-learn's
    CalibratedClassifierCV(method='sigmoid') does (the targets pulled in by the prior); returns (a, b)."""
    from scipy.optimize import minimize
    from scipy.special import expit
    F = np.asarray(F, dtype=float)
    positive = np.asarray(positive, dtype=bool)
    wt = np.ones(len(F)) if w is None else np.asarray(w, dtype=float)
    scale = float(np.max(np.abs(F))) if len(F) and np.max(np.abs(F)) >= 30 else 1.0
    Fs = F / scale
    n0, n1 = wt[~positive].sum(), wt[positive].sum()
    T = np.where(positive, (n1 + 1.0) / (n1 + 2.0), 1.0 / (n0 + 2.0))

    def loss_grad(ab):
        z = -(ab[0] * Fs + ab[1])
        g = wt * (expit(z) - T)
        return float(np.sum(wt * (np.logaddexp(0, z) - T * z))), np.array([-(g @ Fs), -g.sum()])
    res = minimize(loss_grad, np.array([0.0, math.log((n0 + 1.0) / (n1 + 1.0))]), method='L-BFGS-B', jac=True,
                   options={'gtol': 1e-6, 'ftol': 64 * np.finfo(float).eps})
    return res.x[0] / scale, res.x[1]


def logit_proba(Z, coef, intercept):
    """A fitted logistic model's probabilities: the sigmoid for two levels, the softmax for more."""
    s = Z @ np.asarray(coef).T + np.asarray(intercept)
    if s.shape[1] == 1:
        p1 = 1.0 / (1.0 + np.exp(-s[:, 0]))
        return np.column_stack([1 - p1, p1])
    s = s - s.max(axis=1, keepdims=True)
    e = np.exp(s)
    return e / e.sum(axis=1, keepdims=True)


def ordinal_logit(A, y, w, n_levels):
    """The cumulative logit (proportional odds) model P(Y <= j) = 1/(1 + exp(-(t_j - A b))), fitted by
    (weighted) maximum likelihood; returns a function of new rows giving every level's probability."""
    from scipy.optimize import minimize
    from scipy.special import expit
    A = np.asarray(A, dtype=float)
    y = np.asarray(y, dtype=int)
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    present = np.unique(y)
    K = len(present)
    code = np.searchsorted(present, y)
    center, scale = weighted_scaler(A, wt)
    Z = (A - center) / scale
    p, n = Z.shape[1], len(y)
    if K == 1:
        return lambda An: full_proba(np.ones((len(An), 1)), present, n_levels)
    cum = np.cumsum(np.bincount(code, weights=wt, minlength=K))[:-1] / wt.sum()
    t0 = np.log(cum / (1 - cum))
    x0 = np.concatenate([np.zeros(p), t0[:1], np.log(np.maximum(np.diff(t0), 1e-6))])
    rows = np.arange(n)

    def cuts(x):
        return np.cumsum(np.concatenate([x[p:p + 1], np.exp(x[p + 1:])]))

    def nll(x):
        beta, t = x[:p], cuts(x)
        F = np.column_stack([np.zeros(n), expit(t[None, :] - (Z @ beta)[:, None]), np.ones(n)])
        up, lo = F[rows, code + 1], F[rows, code]
        pr = np.maximum(up - lo, 1e-300)
        fu, fl = up * (1 - up), lo * (1 - lo)
        G = np.zeros((n, K + 1))
        G[rows, code + 1] -= wt * fu / pr
        G[rows, code] += wt * fl / pr
        gt = G[:, 1:K].sum(axis=0)
        gx = np.concatenate([Z.T @ (wt * (fu - fl) / pr), [gt.sum()], np.exp(x[p + 1:]) * np.cumsum(gt[::-1])[::-1][1:]])
        return float(-np.sum(wt * np.log(pr))), gx
    res = minimize(nll, x0, jac=True, method='L-BFGS-B', options={'maxiter': 2000, 'gtol': 1e-8})
    beta, t = res.x[:p], cuts(res.x)

    def prob(An):
        Zn = (np.asarray(An, dtype=float) - center) / scale
        F = np.column_stack([np.zeros(len(Zn)), expit(t[None, :] - (Zn @ beta)[:, None]), np.ones(len(Zn))])
        return full_proba(np.diff(F, axis=1), present, n_levels)
    return prob


def no_penalty_logistic():
    """scikit-learn's unpenalized logistic regression (C = inf), to the maximum likelihood (tol 1e-8: the default
    1e-4 stops about 1e-4 short of it in the probabilities)."""
    from sklearn.linear_model import LogisticRegression
    return LogisticRegression(C=np.inf, max_iter=1000, tol=1e-8)


def fit_quietly(model, *args, **kw):
    """model.fit(...), without the warning scikit-learn 1.8 gives for its own C=np.inf (no penalty)."""
    with warnings.catch_warnings():
        warnings.filterwarnings('ignore', message='Setting penalty=None will ignore the C and l1_ratio parameters')
        return model.fit(*args, **kw)


# ============================================================================
# the fitters: fit_x(X, y, w, train, tune, n_levels, factors, seed) ->
# (predict, info); predict(new X) is the prediction (continuous) or an
# n x levels matrix of probabilities; tune is the validation rows, or None
# ============================================================================

def fit_tree(X, y, w, train, tune, n_levels, factors, seed, max_leaves=64, min_leaf=5, folds=5):
    """Decision Tree (JMP's Partition): splits made best first, the leaf whose split most reduces the impurity
    (squared error, or entropy for a categorical Y) next, no leaf under min_leaf rows; as many splits as give the
    best validation measure, or with no validation rows the best 5-fold crossvalidation within the training rows.
    A leaf's rates carry a prior of one row, as JMP's do."""
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

    def grow(rows):
        if n_levels:
            m = DecisionTreeClassifier(criterion='entropy', max_leaf_nodes=max_leaves, min_samples_leaf=min_leaf, random_state=seed)
        else:
            m = DecisionTreeRegressor(max_leaf_nodes=max_leaves, min_samples_leaf=min_leaf, random_state=seed)
        m.fit(X[rows], y[rows], sample_weight=None if w is None else w[rows])
        t = m.tree_
        if not n_levels:
            return m, t.value[:, 0, 0]
        counts = np.zeros((t.node_count, n_levels))
        counts[:, m.classes_.astype(int)] = t.value[:, 0, :] * t.weighted_n_node_samples[:, None]
        return m, smooth_counts(counts, level_shares(y[rows], None if w is None else w[rows], n_levels))

    def curve(m, value, rows):
        paths = tree_paths(m, X[rows])
        return [loss(y[rows], value[leaf_after(paths, s)], None if w is None else w[rows], n_levels) for s in range((m.tree_.node_count - 1) // 2 + 1)]

    if tune is not None and tune.any():
        m, value = grow(train)
        best = int(np.argmin(curve(m, value, tune)))
        how = 'the validation rows'
    else:
        fold = inner_folds(train, folds, [seed, 1])
        total = np.zeros(max_leaves)
        for k in range(folds):
            if not np.any(fold == k):
                continue
            mk, vk = grow((fold >= 0) & (fold != k))
            c = curve(mk, vk, fold == k)
            total += np.array(c + [c[-1]] * (max_leaves - len(c)))
        m, value = grow(train)
        best = int(np.argmin(total[:(m.tree_.node_count - 1) // 2 + 1]))
        how = f'{folds}-fold crossvalidation within the training rows'

    def predict(Xn):
        return value[leaf_after(tree_paths(m, Xn), best)]
    return predict, {'text': f'{best} splits ({best + 1} leaves), chosen by {how}', 'splits': best}


def fit_forest(X, y, w, train, tune, n_levels, factors, seed, trees=100, min_leaf=5):
    """Bootstrap Forest: trees on bootstrap samples of the training rows, each split from a random subset of the
    columns (a third of them, or the square root of their number for a categorical Y), no leaf under min_leaf
    rows; the forest averages the trees (a leaf's rates carry a prior of one row). With validation rows, the
    number of trees (10, 20, ..., trees) with the best validation measure."""
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    p = X.shape[1]
    if n_levels:
        m = RandomForestClassifier(n_estimators=trees, criterion='entropy', max_features=max(1, int(round(math.sqrt(p)))), min_samples_leaf=min_leaf, random_state=seed, n_jobs=1)
    else:
        m = RandomForestRegressor(n_estimators=trees, max_features=max(1, int(round(p / 3))), min_samples_leaf=min_leaf, random_state=seed, n_jobs=1)
    m.fit(X[train], y[train], sample_weight=None if w is None else w[train])
    if n_levels:
        share = level_shares(y[train], None if w is None else w[train], n_levels)
        tables = []
        for t in m.estimators_:
            counts = np.zeros((t.tree_.node_count, n_levels))
            counts[:, m.classes_.astype(int)] = t.tree_.value[:, 0, :] * t.tree_.weighted_n_node_samples[:, None]
            tables.append(smooth_counts(counts, share))

    def each(Xn):
        Xf = np.asarray(Xn, dtype=np.float32)
        if n_levels:
            return np.array([tab[t.apply(Xf)] for t, tab in zip(m.estimators_, tables)])
        return np.array([t.predict(Xf) for t in m.estimators_])
    use, how = trees, 'every tree (no validation rows)'
    if tune is not None and tune.any():
        cum = np.cumsum(each(X[tune]), axis=0)
        sizes = list(range(10, trees + 1, 10))
        ls = [loss(y[tune], cum[k - 1] / k, None if w is None else w[tune], n_levels) for k in sizes]
        use, how = sizes[int(np.argmin(ls))], 'the validation rows'

    def predict(Xn):
        return each(Xn)[:use].mean(axis=0)
    return predict, {'text': f'{use} trees ({how}), {m.max_features} of {p} columns tried at each split', 'trees': use}


def fit_boosted(X, y, w, train, tune, n_levels, factors, seed, layers=50, splits=3, rate=0.1, min_leaf=5):
    """Boosted Tree: layers of small trees (splits splits each) fitted to what the layers before them leave, the
    learning rate shrinking each; no leaf under min_leaf rows. With validation rows, the number of layers with the
    best validation measure (early stopping)."""
    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
    kind = GradientBoostingClassifier if n_levels else GradientBoostingRegressor
    m = kind(n_estimators=layers, learning_rate=rate, max_leaf_nodes=splits + 1, max_depth=None, min_samples_leaf=min_leaf, random_state=seed)
    m.fit(X[train], y[train], sample_weight=None if w is None else w[train])
    use, how = layers, 'every layer (no validation rows)'
    if tune is not None and tune.any():
        staged = m.staged_predict_proba(X[tune]) if n_levels else m.staged_predict(X[tune])
        ls = [loss(y[tune], full_proba(f, m.classes_, n_levels) if n_levels else f, None if w is None else w[tune], n_levels) for f in staged]
        use, how = int(np.argmin(ls)) + 1, 'the validation rows'
        m.estimators_ = m.estimators_[:use]
        m.n_estimators_ = use

    def predict(Xn):
        Xn = np.asarray(Xn, dtype=float)
        return full_proba(m.predict_proba(Xn), m.classes_, n_levels) if n_levels else m.predict(Xn)
    return predict, {'text': f'{use} layers ({how}), {splits} splits per tree, learning rate {rate:g}', 'layers': use}


def fit_knn(X, y, w, train, tune, n_levels, factors, seed, k_max=10):
    """K Nearest Neighbors on the columns standardized by the training rows: the (weighted) mean of the K nearest
    training rows, or their level rates with a prior of one row. K from 1 to k_max with the smallest validation
    error (the misclassification rate for a categorical Y), or without validation rows the smallest leave-one-out
    error in the training rows."""
    from sklearn.neighbors import NearestNeighbors
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    center, scale = weighted_scaler(X[train], wt[train])
    idx = np.flatnonzero(train)
    K = max(1, min(k_max, len(idx) - 1))
    nn = NearestNeighbors().fit((X[idx] - center) / scale)
    yt, wtt = y[idx], wt[idx]
    share = level_shares(yt, wtt, n_levels) if n_levels else None

    def pred(nb, k):
        ww, yy = wtt[nb[:, :k]], yt[nb[:, :k]]
        if not n_levels:
            return np.sum(ww * yy, axis=1) / ww.sum(axis=1)
        return smooth_counts(np.stack([np.sum(ww * (yy == j), axis=1) for j in range(n_levels)], axis=1), share)
    if tune is not None and tune.any():
        rows = tune
        nb = nn.kneighbors((X[tune] - center) / scale, n_neighbors=K, return_distance=False)
        how = 'the validation rows'
    else:
        rows = train
        nb = nn.kneighbors((X[idx] - center) / scale, n_neighbors=K + 1, return_distance=False)
        own = nb == np.arange(len(idx))[:, None]
        nb = np.take_along_axis(nb, np.argsort(own, axis=1, kind='stable'), axis=1)[:, :K]
        how = 'leave-one-out in the training rows'
    errs = []
    for k in range(1, K + 1):
        f = pred(nb, k)
        e = (np.argmax(f, axis=1) != y[rows]) if n_levels else (y[rows] - f) ** 2
        errs.append(float(np.sum(wt[rows] * e)))
    best = int(np.argmin(errs)) + 1

    def predict(Xn):
        return pred(nn.kneighbors((np.asarray(Xn, dtype=float) - center) / scale, n_neighbors=best, return_distance=False), best)
    return predict, {'text': f'K = {best} ({how}), of 1 to {K}', 'k': best}


def fit_nb(X, y, w, train, tune, n_levels, factors, seed):
    """Naive Bayes: the factors independent within each level of Y; a continuous factor normal (its mean and
    variance in each level), a categorical one by its level shares with one row added to each (Laplace), a Missing
    column as a factor of two levels."""
    from sklearn.naive_bayes import CategoricalNB, GaussianNB
    cont = [f['cols'][0] for f in factors if f['kind'] == 'continuous']

    def codes(Xn):
        out, sizes = [], []
        for f in factors:
            if f['kind'] == 'categorical':
                cols = f['cols'] + ([f['missing']] if f['missing'] is not None else [])
                out.append(np.argmax(Xn[:, cols], axis=1))
                sizes.append(len(cols))
            elif f['missing'] is not None:
                out.append(Xn[:, f['missing']].astype(int))
                sizes.append(2)
        return (np.column_stack(out) if out else None), sizes
    ww = None if w is None else w[train]
    yt = np.asarray(y[train], dtype=int)
    gnb = GaussianNB().fit(X[train][:, cont], yt, sample_weight=ww) if cont else None
    C, sizes = codes(X)
    cnb = CategoricalNB(alpha=1.0, min_categories=sizes).fit(C[train], yt, sample_weight=ww) if C is not None else None
    classes = (gnb or cnb).classes_

    def predict(Xn):
        Xn = np.asarray(Xn, dtype=float)
        joint = np.zeros((len(Xn), len(classes)))
        if gnb is not None:
            joint += gnb.predict_joint_log_proba(Xn[:, cont])
        if cnb is not None:
            joint += cnb.predict_joint_log_proba(codes(Xn)[0])
        if gnb is not None and cnb is not None:
            joint -= np.log(gnb.class_prior_)           # the prior once, not twice
        joint -= joint.max(axis=1, keepdims=True)
        p = np.exp(joint)
        return full_proba(p / p.sum(axis=1, keepdims=True), classes, n_levels)
    return predict, {'text': f'{len(cont)} normal and {len(sizes)} categorical factors, priors the training shares'}


def fit_neural(X, y, w, train, tune, n_levels, factors, seed, nodes=3, penalties=(0.001, 0.01, 0.1), holdback=1 / 3):
    """Neural: one hidden layer of nodes tanh nodes on the standardized columns (and a standardized continuous Y),
    fitted by L-BFGS with a squared penalty on the weights; the penalty with the best validation measure, or with no
    validation rows the best on a holdback of a third of the training rows (then refitted on them all)."""
    from sklearn.neural_network import MLPClassifier, MLPRegressor
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    center, scale = weighted_scaler(X[train], wt[train])
    Z = (X - center) / scale
    if n_levels:
        target, ym, ys = y, 0.0, 1.0
    else:
        (ym,), (ys,) = weighted_scaler(y[train][:, None], wt[train])
        target = (y - ym) / ys

    def net(rows, a):
        kind = MLPClassifier if n_levels else MLPRegressor
        return kind(hidden_layer_sizes=(nodes,), activation='tanh', solver='lbfgs', alpha=a, max_iter=2000, random_state=seed).fit(
            Z[rows], target[rows], sample_weight=None if w is None else w[rows])

    def out(m, Zn):
        return full_proba(m.predict_proba(Zn), m.classes_, n_levels) if n_levels else ym + ys * m.predict(Zn)
    if tune is not None and tune.any():
        fit_rows, check, how = train, tune, 'the validation rows'
    else:
        idx = np.flatnonzero(train)
        check = np.zeros(len(y), dtype=bool)
        check[idx[np.random.default_rng([seed, 2]).permutation(len(idx))[:int(round(holdback * len(idx)))]]] = True
        fit_rows, how = train & ~check, 'a holdback of a third of the training rows'
    nets = [net(fit_rows, a) for a in penalties]
    b = int(np.argmin([loss(y[check], out(m, Z[check]), None if w is None else w[check], n_levels) for m in nets]))
    m = nets[b] if fit_rows is train else net(train, penalties[b])

    def predict(Xn):
        return out(m, (np.asarray(Xn, dtype=float) - center) / scale)
    return predict, {'text': f'{nodes} tanh nodes, penalty {penalties[b]:g} ({how})', 'penalty': penalties[b]}


def fit_svm(X, y, w, train, tune, n_levels, factors, seed, cost=1.0):
    """Support Vector Machines with a radial basis kernel on the standardized columns, cost 1 and gamma 1/(number
    of columns): SVR on a standardized Y (epsilon 0.1), or SVC with Platt's sigmoid on the training decision values
    for the probabilities (one per level, normalized)."""
    from sklearn.svm import SVC, SVR
    from scipy.special import expit
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    center, scale = weighted_scaler(X[train], wt[train])
    gamma = 1.0 / max(1, X.shape[1])
    ww = None if w is None else w[train]
    Zt = (X[train] - center) / scale
    if not n_levels:
        (ym,), (ys,) = weighted_scaler(y[train][:, None], wt[train])
        m = SVR(kernel='rbf', C=cost, gamma=gamma, epsilon=0.1).fit(Zt, (y[train] - ym) / ys, sample_weight=ww)

        def predict(Xn):
            return ym + ys * m.predict((np.asarray(Xn, dtype=float) - center) / scale)
        return predict, {'text': f'RBF kernel, cost {cost:g}, gamma {gamma:.4g}, {len(m.support_)} support vectors'}
    m = SVC(kernel='rbf', C=cost, gamma=gamma, decision_function_shape='ovr').fit(Zt, y[train], sample_weight=ww)
    classes = m.classes_
    F = m.decision_function(Zt)
    cal = [platt(F, y[train] == classes[1], ww)] if len(classes) == 2 else [platt(F[:, j], y[train] == c, ww) for j, c in enumerate(classes)]

    def predict(Xn):
        F = m.decision_function((np.asarray(Xn, dtype=float) - center) / scale)
        if len(classes) == 2:
            p1 = expit(-(cal[0][0] * F + cal[0][1]))
            p = np.column_stack([1 - p1, p1])
        else:
            p = np.column_stack([expit(-(a * F[:, j] + b)) for j, (a, b) in enumerate(cal)])
            p /= p.sum(axis=1, keepdims=True)
        return full_proba(p, classes, n_levels)
    return predict, {'text': f'RBF kernel, cost {cost:g}, gamma {gamma:.4g}, {len(m.support_)} support vectors, Platt probabilities'}


def fit_lda(X, y, w, train, tune, n_levels, factors, seed):
    """Discriminant (linear): normal factors with one covariance matrix for every level, pooled within the levels
    with n - (number of levels) degrees of freedom; priors the training shares."""
    from scipy.linalg import pinvh
    cols = linear_columns(factors)
    A = np.asarray(X, dtype=float)[:, cols]
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    At, yt, wtt = A[train], np.asarray(y[train], dtype=int), wt[train]
    classes = np.unique(yt)
    means = np.array([np.average(At[yt == c], axis=0, weights=wtt[yt == c]) for c in classes])
    prior = np.array([wtt[yt == c].sum() for c in classes]) / wtt.sum()
    R = At - means[np.searchsorted(classes, yt)]
    Si = pinvh((R * wtt[:, None]).T @ R / max(wtt.sum() - len(classes), 1e-12))

    def predict(Xn):
        An = np.asarray(Xn, dtype=float)[:, cols]
        d = np.stack([np.log(prior[k]) - 0.5 * np.einsum('ij,jk,ik->i', An - means[k], Si, An - means[k]) for k in range(len(classes))], axis=1)
        d -= d.max(axis=1, keepdims=True)
        p = np.exp(d)
        return full_proba(p / p.sum(axis=1, keepdims=True), classes, n_levels)
    return predict, {'text': f'linear, {len(cols)} columns, priors the training shares'}


def fit_linear(X, y, w, train, tune, n_levels, factors, seed, ordinal=False):
    """Fit Least Squares (the main effects, by weighted least squares), or for a categorical Y Nominal Logistic
    (multinomial, by maximum likelihood) or Ordinal Logistic (cumulative logit)."""
    cols = linear_columns(factors)
    A = np.asarray(X, dtype=float)[:, cols]
    ww = None if w is None else w[train]
    if not n_levels:
        from sklearn.linear_model import LinearRegression
        m = LinearRegression().fit(A[train], y[train], sample_weight=ww)
        return (lambda Xn: m.predict(np.asarray(Xn, dtype=float)[:, cols])), {'text': f'the main effects, {len(cols)} terms and an intercept'}
    if ordinal:
        prob = ordinal_logit(A[train], y[train], ww, n_levels)
        return (lambda Xn: prob(np.asarray(Xn, dtype=float)[:, cols])), {'text': f'cumulative logit, {len(cols)} terms'}
    center, scale = weighted_scaler(A[train], ww)
    m = fit_quietly(no_penalty_logistic(), (A[train] - center) / scale, y[train], sample_weight=ww)
    return (lambda Xn: full_proba(m.predict_proba((np.asarray(Xn, dtype=float)[:, cols] - center) / scale), m.classes_, n_levels)), {'text': f'multinomial logit, {len(cols)} terms'}


def fit_genreg(X, y, w, train, tune, n_levels, factors, seed, l1_ratio=1.0, n_lambda=100):
    """Generalized Regression: the lasso (l1_ratio 1) or elastic net penalty path on the centred and scaled
    main effects; the penalty with the best validation measure, or with no validation rows the smallest AICc. A
    normal response by coordinate descent (enet_path), a categorical one by logistic regression (saga, 30 penalties
    from the one that zeroes every coefficient)."""
    cols = linear_columns(factors)
    A = np.asarray(X, dtype=float)[:, cols]
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    center, scale = weighted_scaler(A[train], wt[train])
    Z = (A - center) / scale
    N = wt[train].sum()
    has_tune = tune is not None and tune.any()

    def aicc(m2ll, k):
        return m2ll + 2 * k + (2 * k * (k + 1) / (N - k - 1) if N - k - 1 > 0 else np.inf)
    if not n_levels:
        from sklearn.linear_model import enet_path
        sw = wt[train] / wt[train].mean()
        ym = float(np.average(y[train], weights=sw))
        r = np.sqrt(sw)
        lambdas, coefs, _ = enet_path(Z[train] * r[:, None], (y[train] - ym) * r, l1_ratio=l1_ratio, n_alphas=n_lambda, eps=1e-3, tol=1e-8, max_iter=10000)
        fits = ym + Z @ coefs
        if has_tune:
            crit = [loss(y[tune], fits[tune, j], None if w is None else w[tune], 0) for j in range(len(lambdas))]
        else:
            sse = wt[train] @ (y[train][:, None] - fits[train]) ** 2
            crit = [aicc(N * (math.log(2 * math.pi * s / N) + 1) if s > 0 else -np.inf, int(np.count_nonzero(coefs[:, j])) + 2) for j, s in enumerate(sse)]
        j = int(np.argmin(crit))
        b = coefs[:, j]

        def predict(Xn):
            return ym + ((np.asarray(Xn, dtype=float)[:, cols] - center) / scale) @ b
        lam = lambdas[j]
    else:
        from sklearn.linear_model import LogisticRegression
        from sklearn.svm import l1_min_c
        yt = np.asarray(y[train], dtype=int)
        Cs = l1_min_c(Z[train], yt, loss='log') / max(l1_ratio, 1e-3) * np.logspace(0, 4, 30)
        m = LogisticRegression(solver='saga', l1_ratio=l1_ratio, C=Cs[0], max_iter=1000, tol=1e-4, warm_start=True, random_state=seed)
        path = []
        for C in Cs:
            m.set_params(C=C).fit(Z[train], yt, sample_weight=None if w is None else w[train])
            path.append((m.coef_.copy(), m.intercept_.copy()))
        classes = m.classes_
        probs = [full_proba(logit_proba(Z, c, i), classes, n_levels) for c, i in path]
        if has_tune:
            crit = [loss(y[tune], p[tune], None if w is None else w[tune], n_levels) for p in probs]
        else:
            crit = [aicc(2 * loss(y[train], p[train], None if w is None else w[train], n_levels), int(np.count_nonzero(c)) + len(classes) - 1) for p, (c, _) in zip(probs, path)]
        j = int(np.argmin(crit))
        b, b0 = path[j]

        def predict(Xn):
            return full_proba(logit_proba((np.asarray(Xn, dtype=float)[:, cols] - center) / scale, b, b0), classes, n_levels)
        lam = 1 / Cs[j]
    kind = 'lasso' if l1_ratio == 1 else f'elastic net (alpha {l1_ratio:g})'
    return predict, {'text': f'{kind}, {int(np.count_nonzero(b))} of {b.size} estimates nonzero, penalty {lam:.4g} ({"the validation rows" if has_tune else "AICc"})'}


def fit_stepwise(X, y, w, train, tune, n_levels, factors, seed, ordinal=False):
    """Fit Stepwise: forward selection of the factors (a categorical factor's columns enter together), each step
    adding the one that most improves the training fit; the step with the smallest BIC, or with validation rows the
    best validation measure. Least squares, or nominal or ordinal logistic regression."""
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    groups = [g for g in ([c for c in ((f['cols'][:-1] if f['kind'] == 'categorical' else f['cols']) + ([f['missing']] if f['missing'] is not None else []))] for f in factors)]
    names = [f['name'] for f in factors]
    N = wt[train].sum()
    ww = None if w is None else w[train]

    def model(cols):
        A = np.asarray(X, dtype=float)[:, cols]
        if not n_levels:
            D = np.column_stack([np.ones(int(train.sum())), A[train]])
            r = np.sqrt(wt[train])
            beta = np.linalg.lstsq(D * r[:, None], y[train] * r, rcond=None)[0]
            f = (lambda Xn: beta[0] + np.asarray(Xn, dtype=float)[:, cols] @ beta[1:])
            sse = float(wt[train] @ (y[train] - f(X[train])) ** 2)
            return f, N * (math.log(2 * math.pi * sse / N) + 1) if sse > 0 else -np.inf, len(cols) + 2
        yt = np.asarray(y[train], dtype=int)
        K = len(np.unique(yt))
        if not cols:
            share = level_shares(yt, ww, n_levels)
            f = (lambda Xn: np.tile(share, (len(Xn), 1)))
            k = K - 1
        elif ordinal:
            prob = ordinal_logit(A[train], yt, ww, n_levels)
            f = (lambda Xn: prob(np.asarray(Xn, dtype=float)[:, cols]))
            k = len(cols) + K - 1
        else:
            center, scale = weighted_scaler(A[train], ww)
            m = fit_quietly(no_penalty_logistic(), (A[train] - center) / scale, yt, sample_weight=ww)
            f = (lambda Xn: full_proba(m.predict_proba((np.asarray(Xn, dtype=float)[:, cols] - center) / scale), m.classes_, n_levels))
            k = (K - 1) * (len(cols) + 1)
        return f, 2 * loss(y[train], f(X[train]), ww, n_levels), k
    chosen, left = [], [i for i, g in enumerate(groups) if g]
    steps = [([],) + model([])]
    while left:
        best = None
        for g in left:
            cand = model(sum((groups[i] for i in chosen + [g]), []))
            if best is None or cand[1] < best[1][1]:
                best = (g, cand)
        chosen.append(best[0])
        left.remove(best[0])
        steps.append((list(chosen),) + best[1])
    if tune is not None and tune.any():
        crit = [loss(y[tune], s[1](X[tune]), None if w is None else w[tune], n_levels) for s in steps]
        how = 'the best validation measure'
    else:
        crit = [s[2] + s[3] * math.log(N) for s in steps]
        how = 'the smallest BIC'
    j = int(np.argmin(crit))
    kept = [names[i] for i in steps[j][0]]
    return steps[j][1], {'text': f'{len(kept)} of {len(left) + len(chosen)} factors ({how}): {", ".join(kept) if kept else "none"}'}


FITTERS = {'tree': fit_tree, 'forest': fit_forest, 'boosted': fit_boosted, 'knn': fit_knn, 'nb': fit_nb, 'neural': fit_neural, 'svm': fit_svm,
           'lda': fit_lda, 'linear': fit_linear, 'lasso': fit_genreg, 'enet': fit_genreg, 'stepwise': fit_stepwise}
EXTRA = {'enet': {'l1_ratio': 0.9}}
# the helpers each fitter's shown code needs, beyond the common ones
COMMON = [weighted_scaler, level_shares, loss, full_proba]
NEEDS = {'tree': [smooth_counts, inner_folds, tree_paths, leaf_after], 'forest': [smooth_counts], 'boosted': [], 'knn': [smooth_counts], 'nb': [],
         'neural': [], 'svm': [platt], 'lda': [linear_columns], 'linear': [linear_columns, ordinal_logit, no_penalty_logistic, fit_quietly],
         'lasso': [linear_columns, logit_proba], 'enet': [linear_columns, logit_proba],
         'stepwise': [level_shares, ordinal_logit, no_penalty_logistic, fit_quietly]}


def crossvalidation(train, k, repeats, seed):
    """K-fold crossvalidation of the training rows, repeated: (repeat, fold, rows fitted, rows held out); each
    repeat a new random split into k folds of nearly equal size, from the seed."""
    idx = np.flatnonzero(train)
    rng = np.random.default_rng(seed)
    out = []
    for r in range(repeats):
        fold = np.full(len(train), -1)
        fold[idx[rng.permutation(len(idx))]] = np.arange(len(idx)) % k
        for j in range(k):
            out.append((r, j, (fold >= 0) & (fold != j), fold == j))
    return out


def auc(score, pos, w):
    """The area under the ROC curve, ties counted half, weighted."""
    score, pos, w = np.asarray(score, dtype=float), np.asarray(pos, dtype=bool), np.asarray(w, dtype=float)
    P_, N_ = w[pos].sum(), w[~pos].sum()
    if P_ <= 0 or N_ <= 0:
        return None
    u, inv = np.unique(score, return_inverse=True)
    pw = np.bincount(inv, weights=np.where(pos, w, 0.0), minlength=len(u))
    nw = np.bincount(inv, weights=np.where(pos, 0.0, w), minlength=len(u))
    return float(np.sum(pw * (np.cumsum(nw) - nw + 0.5 * nw)) / (P_ * N_))


def measures(y, f, w, sets, n_levels):
    """The Measures of Fit of each set (0 Training, 1 Validation, 2 Test) as the report computes them."""
    wt = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    f = np.asarray(f, dtype=float)
    out = {}
    if n_levels:
        tr = sets == 0
        share = np.bincount(np.asarray(y[tr], dtype=int), weights=wt[tr], minlength=n_levels)[:n_levels] / wt[tr].sum()
    for k, name in enumerate(('Training', 'Validation', 'Test')):
        m = sets == k
        if not m.any():
            continue
        ww, N = wt[m], float(wt[m].sum())
        if not n_levels:
            r = y[m] - f[m]
            sse = float(np.sum(ww * r * r))
            sst = float(np.sum(ww * (y[m] - np.sum(ww * y[m]) / N) ** 2))
            out[name] = {'rsquare': 1 - sse / sst if sst > 0 else None, 'rase': math.sqrt(sse / N), 'mad': float(np.sum(ww * np.abs(r)) / N),
                         'neg_loglik': 0.5 * N * (math.log(2 * math.pi * sse / N) + 1) if sse > 0 else None, 'sse': sse, 'n': N}
            continue
        yy, p = np.asarray(y[m], dtype=int), f[m]
        pt = np.clip(p[np.arange(len(yy)), yy], 1e-15, 1.0)
        ll = float(np.sum(ww * np.log(pt)))
        ll0 = float(np.sum(ww * np.log(np.clip(share[yy], 1e-15, 1.0))))
        den = 1 - math.exp(2 * ll0 / N)
        row = {'entropy_rsquare': 1 - ll / ll0 if ll0 < 0 else None, 'generalized_rsquare': (1 - math.exp(2 * (ll0 - ll) / N)) / den if den > 0 else None,
               'mean_neg_log_p': -ll / N, 'rase': math.sqrt(float(np.sum(ww * (1 - pt) ** 2)) / N), 'mad': float(np.sum(ww * (1 - pt)) / N),
               'misclassification': float(np.sum(ww * (np.argmax(p, axis=1) != yy)) / N), 'neg_loglik': -ll, 'n': N}
        if n_levels == 2:
            row['auc'] = auc(p[:, 1], yy == 1, ww)
        out[name] = row
    return out


# ============================================================================
# the platform
# ============================================================================

def _spec(kw):
    s = {k: kw.get(k) for k in SPEC}
    s['x'] = list(s['x'] or [])
    s['portion'] = float(s['portion'] or 0)
    s['kfold'] = int(s['kfold'] or 0)
    seed = pv.seed_of(s['seed'])
    s['seed'] = 1 if seed is None else seed
    s['missing'] = s['missing'] or 'informative'
    return s


def _kfold(s):
    """The number of folds in use: none with a Validation column (its sets win)."""
    return s['kfold'] if s['kfold'] >= 2 and not s['validation'] else 0


def _P(table, rows, s):
    def build():
        portion = 0.0 if _kfold(s) else s['portion']
        return pv.prepare(table, s['y'], s['x'], rows, s['weight'], s['freq'], s['validation'], portion, s['seed'], s['missing'])
    return pv.cached('screening-data', table, rows, s, build, keep=64)


def factors_of(P):
    """The factors as the fitters take them: each x column's columns of X, and its Missing column."""
    out = []
    for e in P.enc:
        idx = list(P.groups[e['name']])
        miss = idx.pop() if e['indicator'] else None
        out.append({'name': e['name'], 'kind': 'continuous' if e['type'] == 'continuous' else 'categorical', 'cols': idx, 'missing': miss})
    return out


def _ordinal(P):
    return P.kind == 'categorical' and data.meta(P.table, P.y).get('modelingType') == 'ordinal'


def label_of(key, P):
    if key == 'linear' and P.kind == 'categorical':
        return 'Ordinal Logistic' if _ordinal(P) else 'Nominal Logistic'
    return LABEL[key]


def _call_fitter(key, P, train, tune, seed):
    kw = dict(EXTRA.get(key, {}))
    if key in ('linear', 'stepwise') and _ordinal(P):
        kw['ordinal'] = True
    n_levels = len(P.levels) if P.kind == 'categorical' else 0
    return FITTERS[key](P.X, P.target, P.w, train, tune, n_levels, factors_of(P), seed, **kw)


def _caught(fn, *args):
    """fn(*args) and the warnings it gave, (category, first line)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        out = fn(*args)
    seen = []
    for w in caught:
        m = (w.category, str(w.message).strip().splitlines()[0].rstrip(':') if str(w.message).strip() else '')
        if m not in seen:
            seen.append(m)
    return out, seen


def _warn(label, caught):
    """The warnings of a method's fit again, with its name (the report lists them under the report)."""
    for cat, text in caught:
        warnings.warn(text if issubclass(cat, (DeprecationWarning, PendingDeprecationWarning, FutureWarning)) else f'{label}: {text}', cat)


def _model(table, rows, s, key):
    """The method fitted to the training rows (tuned on the validation rows), remembered."""
    P = _P(table, rows, s)

    def build():
        t0 = time.perf_counter()
        tune = P.mask(1) if P.has(1) else None
        (predict, info), caught = _caught(_call_fitter, key, P, P.train(), tune, s['seed'])
        return {'predict': predict, 'info': info, 'seconds': time.perf_counter() - t0, 'warnings': caught}
    return pv.cached('screening-model', table, rows, {**s, 'method': key}, build, keep=64)


def _crossvalidated(table, rows, s, key, repeats):
    """K-fold crossvalidation of one method: the held-out measures of every fold, and each row's out-of-fold
    prediction from the first repeat."""
    P = _P(table, rows, s)
    k = _kfold(s)

    def build():
        folds = []
        oof = None
        caught = []
        for r, j, fit_rows, held in crossvalidation(P.train(), k, repeats, s['seed']):
            (predict, info), c = _caught(_call_fitter, key, P, fit_rows, None, s['seed'])
            caught += [x for x in c if x not in caught]
            f = predict(P.X)
            Q = copy.copy(P)
            Q.sets = np.where(held, 1, np.where(fit_rows, 0, -1))
            m = {x['set']: x for x in pv.measures(Q, f)}
            folds.append({'repeat': r, 'fold': j, 'training': m.get('Training'), 'held': m.get('Validation'), 'info': info['text']})
            if r == 0:
                if oof is None:
                    oof = np.zeros_like(f)
                oof[held] = f[held]
            _tick()
        return {'folds': folds, 'oof': oof, 'warnings': caught}
    return pv.cached('screening-cv', table, rows, {**s, 'method': key, 'repeats': repeats}, build, keep=64)


_PROGRESS = {'done': 0, 'total': 0}


def _tick():
    _PROGRESS['done'] += 1
    print(f'smui:progress screening {_PROGRESS["done"]} {_PROGRESS["total"]}', flush=True)


def _methods(methods, P):
    keys = [k for k, _ in METHODS if k in (methods if methods is not None else DEFAULT)]
    return [k for k in keys if P.kind == 'categorical' or k not in CATEGORICAL_ONLY]


def _mean_sd(rows, keys):
    mean, sd = {}, {}
    for k in keys:
        v = [r[k] for r in rows if r and r.get(k) is not None]
        mean[k] = float(np.mean(v)) if v else None
        sd[k] = float(np.std(v, ddof=1)) if len(v) > 1 else None
    return mean, sd


def _best(values, key):
    """The methods with the best value of a measure."""
    ok = [(m, v) for m, v in values if v is not None and np.isfinite(v)]
    if not ok:
        return []
    b = max(v for _, v in ok) if key in HIGHER else min(v for _, v in ok)
    return [m for m, v in ok if abs(v - b) <= 1e-12 * max(1.0, abs(b))]


def dominant(rows, keys):
    """The methods no other method matches or beats on every measure while beating on one (Pareto)."""
    def better(a, b, k):
        return a > b if k in HIGHER else a < b
    ok = [(m, v) for m, v in rows if all(v.get(k) is not None for k in keys)]
    out = []
    for m, v in ok:
        beaten = any(all(not better(v[k], u[k], k) for k in keys) and any(better(u[k], v[k], k) for k in keys) for n, u in ok if n != m)
        if not beaten:
            out.append(m)
    return out


@api('screening.fit', packages=pv.SK)
def fit(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
        methods=None, kfold=0, repeats=1, table_name='data'):
    """Every chosen method on the same rows and sets: the Measures of Fit per method and set, the crossvalidated
    measures (K-fold), the best and the dominant methods, and the curves and predictions the comparisons draw."""
    s = _spec(locals())
    P = _P(table, rows, s)
    keys = _methods(methods, P)
    if not keys:
        raise ValueError('choose at least one method that fits this response')
    K = _kfold(s)
    repeats = max(1, int(repeats or 1)) if K else 1
    n_levels = len(P.levels) if P.kind == 'categorical' else 0
    _PROGRESS.update(done=0, total=len(keys) * (1 + K * repeats))
    notes = list(P.notes)
    if s['kfold'] >= 2 and s['validation']:
        notes.append(f'K-fold crossvalidation is not used: the Validation column {s["validation"]} gives the sets.')
    elif K and s['portion']:
        notes.append('The Validation Portion is not used with K-fold crossvalidation.')
    out = {'kind': P.kind, 'levels': list(P.labels), 'sets': [SETS[k] for k in range(3) if P.has(k)], 'n': {SETS[k]: int(P.mask(k).sum()) for k in range(3)},
           'seed': s['seed'], 'kfold': K, 'repeats': repeats, 'features': list(P.features), 'measure_columns': pv.measure_columns(P.kind)}
    res = []
    fitted = {}
    for key in keys:
        r = {'key': key, 'label': label_of(key, P), 'uses': USES[key]}
        try:
            M = _model(table, rows, s, key)
            _warn(r['label'], M['warnings'])
            f = np.asarray(M['predict'](P.X), dtype=float)
            fitted[key] = f
            r.update({'measures': {m['set']: m for m in pv.measures(P, f)}, 'info': M['info']['text'], 'seconds': M['seconds']})
        except Exception as e:  # a method that cannot fit these data: say so, keep the others
            r['error'] = f'{type(e).__name__}: {e}'
        _tick()
        res.append(r)
    mk = [c['key'] for c in pv.measure_columns(P.kind) if c['key'] != 'set']
    if K:
        for r in res:
            if 'error' in r:
                _PROGRESS['done'] += K * repeats
                continue
            try:
                cv = _crossvalidated(table, rows, s, r['key'], repeats)
                _warn(f'{r["label"]} (crossvalidation)', cv['warnings'])
            except Exception as e:
                r['cv_error'] = f'{type(e).__name__}: {e}'
                continue
            mean, sd = _mean_sd([f['held'] for f in cv['folds']], mk)
            tmean, _ = _mean_sd([f['training'] for f in cv['folds']], mk)
            r['measures'][CV] = {**mean, 'n': mean.get('n')}
            r['cv'] = {'sd': sd, 'training': tmean, 'folds': [{'repeat': f['repeat'], 'fold': f['fold'], **(f['held'] or {})} for f in cv['folds']]}
            fitted[(r['key'], CV)] = cv['oof']
    ok = [r for r in res if 'measures' in r]
    compare = 'Validation' if P.has(1) else (CV if K else 'Training')
    summary = [k for k in SUMMARY[P.kind] if k != 'auc' or n_levels == 2]
    shown_sets = out['sets'] + ([CV] if K else [])
    out['best'] = {st: {k: _best([(r['key'], r['measures'].get(st, {}).get(k)) for r in ok], k) for k in mk} for st in shown_sets}
    out['dominant'] = dominant([(r['key'], r['measures'].get(compare, {})) for r in ok], summary)
    first = summary[0]
    ranked = sorted(ok, key=lambda r: -(r['measures'].get(compare, {}).get(first) if r['measures'].get(compare, {}).get(first) is not None else -np.inf))
    out['order'] = [r['key'] for r in ranked] + [r['key'] for r in res if 'measures' not in r]
    out.update({'methods': res, 'compare': compare, 'summary': summary, 'notes': notes, 'shown_sets': shown_sets})
    # what the comparisons draw
    if P.kind == 'categorical':
        out['roc'], out['lift'] = {}, {}
        for r in ok:
            f = fitted[r['key']]
            out['roc'][r['key']] = pv.roc(P, f, most=160)
            out['lift'][r['key']] = pv.lift(P, f, most=120)
            if (r['key'], CV) in fitted:
                Q = copy.copy(P)
                Q.sets = np.ones(len(P.index), dtype=int)
                g = fitted[(r['key'], CV)]
                out['roc'][r['key']] += [{**c, 'set': CV} for c in pv.roc(Q, g, most=160)]
                out['lift'][r['key']] += [{**c, 'set': CV} for c in pv.lift(Q, g, most=120)]
    else:
        out['residuals'] = {'rows': P.index.tolist(), 'actual': P.target.tolist(), 'set': P.sets.tolist(),
                            'predicted': {r['key']: fitted[r['key']].tolist() for r in ok},
                            'oof': {r['key']: fitted[(r['key'], CV)].tolist() for r in ok if (r['key'], CV) in fitted}}
    out['code'] = _code(P, table_name, rows, [r['key'] for r in ok], s, K, repeats)
    return out


# ---- the Python under the report ------------------------------------------------------------------

def _src(fns):
    import inspect
    seen, out = set(), []
    for f in fns:
        if f.__name__ not in seen:
            seen.add(f.__name__)
            out.append(inspect.getsource(f).rstrip())
    return '\n\n\n'.join(out)


def _exact_csv(head, table_name):
    """read_csv with the round-trip float parser: pandas' default parser is off by one unit in the last place in
    about one value in five, and forests, support vectors and neural networks can turn on such a difference."""
    call = f'pd.read_csv({json.dumps(table_name + ".csv")})'
    return head.replace(call, call[:-1] + ', float_precision="round_trip")')


def _code(P, table_name, rows, keys, s, K, repeats):
    n_levels = len(P.levels) if P.kind == 'categorical' else 0
    L = P.code(table_name, rows, extra_imports=['import json', 'import math', 'import warnings'])
    L[0] = _exact_csv(L[0], table_name)
    L += ['valid = sets == 1',
          'tune = valid if valid.any() else None   # the rows that tune a method: the validation rows, or none',
          f'n_levels = {n_levels}   # the levels of the response (0: a continuous response)',
          f'factors = {factors_of(P)!r}   # each factor\'s columns of X',
          f'seed = {int(s["seed"])}', '', '']
    fns = list(COMMON)
    for k in keys:
        fns += NEEDS[k]
    fns += [FITTERS[k] for k in keys] + [auc, measures] + ([crossvalidation] if K else [])
    L.append(_src(fns))
    L += ['', '', 'methods = {']
    for k in keys:
        kw = dict(EXTRA.get(k, {}))
        if k in ('linear', 'stepwise') and _ordinal(P):
            kw['ordinal'] = True
        args = ''.join(f', {a}={v!r}' for a, v in kw.items())
        L.append(f'    {json.dumps(label_of(k, P))}: lambda *a: {FITTERS[k].__name__}(*a{args}),')
    L += ['}', 'for name, fit in methods.items():',
          '    predict, info = fit(X, y, w, train, tune, n_levels, factors, seed)',
          '    for set_name, m in measures(y, predict(X), w, sets, n_levels).items():',
          "        print(json.dumps({'method': name, 'set': set_name, **m}))"]
    if K:
        L += ['', f'# {K}-fold crossvalidation{f", repeated {repeats} times" if repeats > 1 else ""}: each fold held out once, the method fitted to the others (and tuned without them)',
              'for name, fit in methods.items():',
              f'    for r, j, fit_rows, held in crossvalidation(train, {K}, {repeats}, seed):',
              '        predict, info = fit(X, y, w, fit_rows, None, n_levels, factors, seed)',
              '        m = measures(y, predict(X), w, np.where(held, 1, np.where(fit_rows, 0, -1)), n_levels)["Validation"]',
              "        print(json.dumps({'method': name, 'repeat': r, 'fold': j, **m}))"]
    return '\n'.join(L)


# ---- the profiler, Save Columns, Decision Threshold ------------------------------------------------

def _profile_build(table, rows=None, method=None, **kw):
    s = _spec(kw)
    P = _P(table, rows, s)
    if method not in FITTERS:
        raise ValueError(f'no method {method!r}')
    fn = _model(table, rows, s, method)['predict']
    return pv.predictor(P, None, predict=fn, proba=fn)


expose('screening', _profile_build, packages=pv.SK)


@api('screening.save', packages=pv.SK)
def save(table, method, rows=None, **kw):
    """Save Columns of one method: the prediction (and residual), or every level's probability and the most likely
    level, for every row of the table whose factors the model can take."""
    s = _spec(kw)
    P = _P(table, rows, s)
    fn = _model(table, rows, s, method)['predict']
    out = pv.saved(P, fn, fn)
    lab = label_of(method, P)
    if P.kind == 'continuous':
        out['name'] = f'Predicted {P.y} {lab}'
    else:
        out['names'] = [f'Prob[{v}] {lab}' for v in P.labels]
        out['most_name'] = f'Most Likely {P.y} {lab}'
    return out


def _confusion_at(target, p1, f, cut):
    """Counts at a cut on the probability of the target level: (true positive, false positive, false negative,
    true negative), each row counted by its frequency."""
    pred = p1 >= cut
    return (float(np.sum(f[pred & target])), float(np.sum(f[pred & ~target])), float(np.sum(f[~pred & target])), float(np.sum(f[~pred & ~target])))


def _rates(tp, fp, fn, tn):
    pos, neg, n = tp + fn, fp + tn, tp + fp + fn + tn
    prec = tp / (tp + fp) if tp + fp > 0 else None
    sens = tp / pos if pos > 0 else None
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'sensitivity': sens, 'specificity': tn / neg if neg > 0 else None, 'precision': prec,
            'misclassification': (fp + fn) / n if n > 0 else None, 'f1': 2 * prec * sens / (prec + sens) if prec and sens else None}


@api('screening.threshold', packages=pv.SK)
def threshold(table, rows=None, methods=None, cut=0.5, level=1, repeats=1, table_name='data', **kw):
    """Decision Threshold for a response with two levels: each method's confusion counts and rates at a cut on the
    probability of one level, per set, and the misclassification rate of every cut from 0 to 1."""
    s = _spec(kw)
    P = _P(table, rows, s)
    if P.kind != 'categorical' or len(P.levels) != 2:
        raise ValueError('Decision Threshold is for a response with two levels')
    level = int(level)
    if level not in (0, 1):
        raise ValueError('the target level is the first or the second')
    cut = float(cut)
    K = _kfold(s)
    grid = np.round(np.linspace(0, 1, 101), 2)
    out = {'level': P.labels[level], 'cut': cut, 'methods': [], 'grid': grid.tolist()}
    for key in _methods(methods, P):
        r = {'key': key, 'label': label_of(key, P), 'sets': {}, 'curves': {}}
        try:
            f = np.asarray(_model(table, rows, s, key)['predict'](P.X), dtype=float)
        except Exception as e:
            r['error'] = f'{type(e).__name__}: {e}'
            out['methods'].append(r)
            continue
        parts = [(SETS[k], P.mask(k), f) for k in range(3) if P.has(k)]
        if K:
            parts.append((CV, np.ones(len(P.index), dtype=bool), _crossvalidated(table, rows, s, key, max(1, int(repeats or 1)))['oof']))
        for name, m, g in parts:
            target, p1, fr = P.target[m] == level, g[m][:, level], P.counts(m)
            r['sets'][name] = _rates(*_confusion_at(target, p1, fr, cut))
            r['curves'][name] = [(lambda c: (c[1] + c[2]) / max(fr.sum(), 1e-300))(_confusion_at(target, p1, fr, t)) for t in grid]
        out['methods'].append(r)
    return out


# ============================================================================
# Make Validation Column
# ============================================================================

def split_counts(n, props):
    """Whole numbers of rows for the sets that add up to n: the floor of n times each proportion, and the rows
    left over to the sets with the largest remainders (a tie to the earlier set)."""
    raw = np.round(n * np.asarray(props, dtype=float) / np.sum(props), 9)
    k = np.floor(raw).astype(int)
    for j in sorted(range(len(raw)), key=lambda j: (-(raw[j] - k[j]), j))[:n - int(k.sum())]:
        k[j] += 1
    return k


def stratum_counts(sizes, props):
    """The rows of each set in each stratum: each stratum's share of every set rounded down or up, so that every
    stratum's rows are placed and the set totals are the unstratified split_counts (controlled rounding: the
    largest remainders first, then augmenting paths for what they could not place)."""
    sizes = np.asarray(sizes, dtype=int)
    E = np.round(sizes[:, None] * (np.asarray(props, dtype=float) / np.sum(props))[None, :], 9)
    F = np.floor(E).astype(int)
    frac = E - F
    need_row = sizes - F.sum(axis=1)
    need_col = split_counts(int(sizes.sum()), props) - F.sum(axis=0)
    up = np.zeros_like(F)
    J, S = F.shape
    for _, j, k in sorted((-frac[j, k], j, k) for j in range(J) for k in range(S) if frac[j, k] > 0):
        if need_row[j] > 0 and need_col[k] > 0:
            up[j, k], need_row[j], need_col[k] = 1, need_row[j] - 1, need_col[k] - 1
    while need_row.any():
        j0 = int(np.flatnonzero(need_row > 0)[0])
        # a path stratum -> set (a cell that can go up) -> stratum (a cell that is up, which gives it back) -> ...
        prev, frontier, seen_j, end = {('j', j0): None}, [j0], {j0}, None
        while frontier and end is None:
            nxt = []
            for j in frontier:
                for k in range(S):
                    if frac[j, k] > 0 and not up[j, k] and ('k', k) not in prev:
                        prev[('k', k)] = ('j', j)
                        if need_col[k] > 0:
                            end = k
                            break
                        for j2 in range(J):
                            if up[j2, k] and j2 not in seen_j:
                                seen_j.add(j2)
                                prev[('j', j2)] = ('k', k)
                                nxt.append(j2)
                if end is not None:
                    break
            frontier = nxt
        if end is None:
            raise ValueError('the strata cannot be rounded to these proportions')
        node = ('k', end)
        while prev[node] is not None:
            a = prev[node]
            if node[0] == 'k':
                up[a[1], node[1]] = 1
            else:
                up[node[1], a[1]] = 0
            node = a
        need_row[j0] -= 1
        need_col[end] -= 1
    return F + up


def make_sets(n, props, seed, strata=None, groups=None, time=None):
    """Training (0), validation (1) and test (2) for n rows, in the proportions props:
    random     split_counts rows of each set, the rows in random order;
    strata     (a code per row) the same within each stratum, the strata in the order they first appear, and the
               totals still split_counts (stratum_counts);
    groups     (a code per row) every row of a group in one set: the groups in random order, each to the set its
               middle row falls in by the cumulative split_counts;
    time       (a number per row) no randomness: the distinct times in order, each to the set its middle row falls
               in, so that the earliest rows train; a row with no time gets no set (-1)."""
    rng = np.random.default_rng(seed)
    props = np.asarray(props, dtype=float)
    sets = np.full(n, -1)

    def by_blocks(blocks):
        m = sum(len(b) for b in blocks)
        c = np.cumsum(split_counts(m, props))
        at = 0
        for b in blocks:
            mid = at + len(b) / 2
            sets[b] = 0 if mid < c[0] else (1 if mid < c[1] else 2)
            at += len(b)
    if time is not None:
        t = np.asarray(time, dtype=float)
        ok = np.flatnonzero(np.isfinite(t))
        u, inv = np.unique(t[ok], return_inverse=True)
        by_blocks([ok[inv == j] for j in range(len(u))])
    elif groups is not None:
        g = np.asarray(groups)
        blocks = [np.flatnonzero(g == v) for v in range(int(g.max()) + 1)]
        by_blocks([blocks[i] for i in rng.permutation(len(blocks))])
    elif strata is not None:
        st = np.asarray(strata)
        members = [np.flatnonzero(st == v) for v in range(int(st.max()) + 1)]
        counts = stratum_counts([len(m) for m in members], props)
        for m, c in zip(members, counts):
            order = m[rng.permutation(len(m))]
            sets[order[:c[0]]] = 0
            sets[order[c[0]:c[0] + c[1]]] = 1
            sets[order[c[0] + c[1]:]] = 2
    else:
        c = split_counts(n, props)
        order = rng.permutation(n)
        sets[order[:c[0]]] = 0
        sets[order[c[0]:c[0] + c[1]]] = 1
        sets[order[c[0] + c[1]:]] = 2
    return sets


def _codes(table, names):
    """A code per row for the combinations of values of some columns, in the order they first appear (a missing
    value is a value of its own)."""
    n = data.TABLES[table]['n']
    cols = [data.raw(table, c) for c in names]

    def txt(v):
        if v is None or (isinstance(v, float) and math.isnan(v)):
            return ''
        return repr(v)
    seen, codes = {}, np.empty(n, dtype=int)
    for i in range(n):
        k = tuple(txt(c[i]) for c in cols)
        codes[i] = seen.setdefault(k, len(seen))
    return codes


@api('screening.validation_column')
def validation_column(table, training=0.6, validation=0.2, test=0.2, strata=None, groups=None, time=None, seed=None, values='text',
                      name='Validation', table_name='data'):
    """Make Validation Column: every row of the table gets a set (see make_sets)."""
    props = [float(v or 0) for v in (training, validation, test)]
    if any(v < 0 or not math.isfinite(v) for v in props) or props[0] <= 0:
        raise ValueError('the proportions are 0 or more, and the training share is above 0')
    strata, groups = [c for c in (strata or []) if c], [c for c in (groups or []) if c]
    if sum(bool(v) for v in (strata, groups, time)) > 1:
        raise ValueError('choose one kind: stratification columns, grouping columns or a cutpoint column')
    seed = pv.seed_of(seed)
    if seed is None:
        seed = int(np.random.default_rng().integers(1, 2 ** 31 - 1))
    n = data.TABLES[table]['n']
    if time:
        if data.meta(table, time).get('dataType') != 'numeric':
            raise ValueError(f'the cutpoint column {time} is not numeric')
        sets = make_sets(n, props, seed, time=np.asarray(data.raw(table, time), dtype=float))
        method = f'cutpoint by {time}'
    elif groups:
        sets = make_sets(n, props, seed, groups=_codes(table, groups))
        method = f'grouped by {", ".join(groups)}'
    elif strata:
        sets = make_sets(n, props, seed, strata=_codes(table, strata))
        method = f'stratified by {", ".join(strata)}'
    else:
        sets = make_sets(n, props, seed)
        method = 'random'
    counts = [int(np.sum(sets == k)) for k in range(3)]
    tot = sum(props)
    words = ['Training', 'Validation', 'Test']
    vals = [None if k < 0 else (words[k] if values == 'text' else int(k)) for k in sets.tolist()]
    note = (f'Make Validation Column: {method}, proportions {", ".join(f"{p / tot:.4g}" for p in props)} (training, validation, test), '
            f'seed {seed}: {counts[0]} training, {counts[1]} validation, {counts[2]} test rows'
            + (f', {n - sum(counts)} with no {time} and no set' if n - sum(counts) else '') + '.')
    return {'values': vals, 'counts': counts, 'seed': seed, 'method': method, 'notes': note,
            'code': _validation_code(table_name, props, seed, strata, groups, time, values, name)}


def _validation_code(table_name, props, seed, strata, groups, time, values, name):
    L = [code_head(table_name), '']
    L.append(_src([split_counts, stratum_counts, make_sets]))
    L.append('')
    L.append('')
    keys = strata or groups
    if keys:
        L.append(f'keys = df[{json.dumps(keys)}].astype(str).agg("\\x1f".join, axis=1)   # the combinations of values, missing ones included')
        L.append('codes = pd.factorize(keys, sort=False)[0]   # in the order they first appear')
    arg = ', strata=codes' if strata else (', groups=codes' if groups else (f', time=pd.to_numeric(df[{json.dumps(time)}], errors="coerce").to_numpy(float)' if time else ''))
    L.append(f'sets = make_sets(len(df), {[round(p, 12) for p in props]!r}, {int(seed)}{arg})')
    if values == 'text':
        L.append(f'df[{json.dumps(name)}] = pd.Series(np.array(["Training", "Validation", "Test", None], dtype=object)[sets])   # -1: no set')
    else:
        L.append(f'df[{json.dumps(name)}] = pd.Series(sets, dtype=float).where(sets >= 0)   # 0 training, 1 validation, 2 test')
    L.append(f'print(df[{json.dumps(name)}].value_counts(dropna=False))')
    return '\n'.join(L)
