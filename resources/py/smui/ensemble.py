"""Analyze > Predictive Modeling > Decision Forest and Boosted Tree.

JMP Pro's two tree ensembles, their trees scikit-learn's decision trees:

  Decision Forest   each tree a DecisionTreeRegressor / Classifier on a
                     bootstrap sample of the training rows, a random set of
                     the X columns tried at each split, the samples and
                     seeds drawn as scikit-learn's RandomForestRegressor
                     draws them (without a nominal X the forest is that
                     forest). Each tree is then cut back as JMP's
                     documentation says its trees stop: past Minimum Splits
                     per Tree a split stays only while it lowers the tree's
                     out-of-bag loss, and the first that does not is taken
                     back. A categorical response's probabilities are JMP's:
                     a node's counts plus a prior worth one row, never 0.
                     The forest averages its trees.
  Boosted Tree       small trees (layers), each fitted to the residuals of
                     the layers before it and scaled by the learning rate:
                     scikit-learn's gradient boosting written out layer by
                     layer (boost_layer; without a nominal X it is
                     GradientBoostingRegressor / Classifier, the same draws).

A categorical X is one column of level numbers. A split on a nominal X
takes two groups of its levels, as JMP's do: each tree (each layer's tree)
orders the levels by the mean response of its rows (the mean residual, for
a layer), and a cut in that order is a grouping, the best one at the tree's
root for a continuous or two-level response (Fisher's result); a response
of three or more levels orders them by the first principal component of
the levels' shares. An ordinal X keeps its order. A missing level, and a
level a tree's rows lack, is NaN, which scikit-learn's trees send to the
better side of each split.

With validation rows, Early Stopping grows the trees or layers one at a
time and keeps the number with the best validation statistic (RSquare, or
Entropy RSquare for a categorical response). Multiple Fits fits several
forests (over the number of terms) or boosted trees (over the splits and
the learning rate) and reports the best by the same statistic.

The data, sets and measures are predictive.py's. The fitted models are
cached (predictive.cached) for the profiler, Save Columns, the tree views
and the permutation importance, and kept under the report's key
(predictive.keep) for Score Rows. Everything random takes the report's
seed. The helper functions near the top are written out into the Python
code under the report as they are here, so that the code gives the same
trees.
"""
import copy
import inspect
import json
import math

import numpy as np

from . import data, predictive, profile
from .registry import api

SK = predictive.SK
LAMBDA = 0.9            # JMP's weight of a node's prior on its parent's prior
SET_NAMES = predictive.SETS


# ---------------------------------------------------------------------------
# the trees: helpers the shown code carries as they are
# ---------------------------------------------------------------------------

def parents(tree):
    """The parent of each node of a fitted scikit-learn tree (-1 at the root)."""
    t = tree.tree_
    parent = np.full(t.node_count, -1)
    inner = np.flatnonzero(t.children_left >= 0)
    parent[t.children_left[inner]] = inner
    parent[t.children_right[inner]] = inner
    return parent


def jmp_probs(tree, lam=0.9):
    """JMP's probabilities at every node of a classification tree:
    Prob = (n + prior) / (N + 1), n the node's (weighted) counts of the
    levels and N their sum; a node's prior is lam times its parent's prior
    plus 1 - lam times its parent's Prob, the root's prior its own shares.
    No probability is 0 unless the level is missing from the tree's rows."""
    t = tree.tree_
    N = t.weighted_n_node_samples
    n = t.value[:, 0, :] * N[:, None]           # scikit-learn keeps the shares
    parent = parents(tree)
    depth = t.compute_node_depths() - 1
    prior = np.zeros_like(n)
    prob = np.zeros_like(n)
    prior[0] = n[0] / N[0]
    prob[0] = (n[0] + prior[0]) / (N[0] + 1)
    for d in range(1, int(depth.max()) + 1):
        at = np.flatnonzero(depth == d)
        up = parent[at]
        prior[at] = lam * prior[up] + (1 - lam) * prob[up]
        prob[at] = (n[at] + prior[at]) / (N[at] + 1)[:, None]
    return prob


def oob_losses(tree, X, y, w, est, categorical):
    """The out-of-bag loss of the tree cut back to its first k splits, for
    k = 0, 1, ..., in the order scikit-learn made them (best first: the
    k-th split made nodes 2k - 1 and 2k). X, y, w: the out-of-bag rows;
    est: each node's estimate (a mean, or JMP's probabilities, y then the
    column of the row's level). The loss is the squared error, or -log p."""
    t = tree.tree_
    path = tree.decision_path(X)
    row = np.repeat(np.arange(X.shape[0]), np.diff(path.indptr))
    node = path.indices
    if categorical:
        err = -w[row] * np.log(np.clip(est[node, y[row]], 1e-15, 1.0))
    else:
        err = w[row] * (y[row] - est[node]) ** 2
    f = np.bincount(node, weights=err, minlength=t.node_count)   # each node's loss, were it a leaf
    k = np.arange(1, int((t.children_left >= 0).sum()) + 1)
    split = parents(tree)[2 * k - 1]                                  # the node split at step k
    return f[0] + np.r_[0.0, np.cumsum(f[2 * k - 1] + f[2 * k] - f[split])]


def kept_splits(loss, min_splits):
    """JMP's rule for a forest's tree: at least min_splits splits; after
    that a split stays while it lowers the out-of-bag loss, and the first
    one that does not is taken back."""
    last = len(loss) - 1
    k = min(min_splits, last)
    while k < last and loss[k + 1] < loss[k]:
        k += 1
    return k


def stands_for(parent, kept):
    """The node of the tree cut back to `kept` splits that each node falls
    in: itself when its id is at most 2 * kept, else its nearest such
    ancestor."""
    rep = np.arange(len(parent))
    out = rep > 2 * kept
    while out.any():
        rep[out] = parent[rep[out]]
        out = rep > 2 * kept
    return rep


def level_ranks(codes, target, w, u):
    """The order in which a tree splits a nominal X's u levels into two
    groups, as JMP groups levels: each level by the weighted mean of target
    over the rows (codes: the rows' level numbers 0 .. u - 1, -1 missing;
    w: their weights, 0 for a row the tree does not use). A cut anywhere in
    this order is a grouping of the levels, and the best cut is the best of
    all groupings for a continuous or two-level target (Fisher 1958). A
    target of several columns (the 0/1 columns of a response of three or
    more levels) orders the levels by the first principal component of
    their shares. Returns each level's rank, NaN for a level the rows lack
    (a tree sends it where missing values go)."""
    ok = (codes >= 0) & (w > 0)
    c = codes[ok].astype(int)
    wk = w[ok]
    t = target[ok]
    W = np.bincount(c, weights=wk, minlength=u)
    present = W > 0
    score = np.zeros(u)
    if t.ndim == 1:
        score[present] = np.bincount(c, weights=wk * t, minlength=u)[present] / W[present]
    else:
        share = np.column_stack([np.bincount(c, weights=wk * t[:, k], minlength=u) for k in range(t.shape[1])])[present] / W[present, None]
        dev = share - W[present] @ share / W[present].sum()
        v = np.linalg.eigh((dev * W[present, None]).T @ dev)[1][:, -1]     # the first principal component
        v = -v if v[np.argmax(np.abs(v))] < 0 else v                       # its sign fixed, so the order is too
        score[present] = share @ v
    order = np.argsort(np.where(present, score, np.inf), kind='mergesort')[:int(present.sum())]
    rank = np.full(u, np.nan)
    rank[order] = np.arange(len(order), dtype=float)
    return rank


def recode(X, maps):
    """X with each categorical column as a tree reads it (maps: [(column,
    ranks)] from maps_for): a nominal column's level numbers become their
    ranks, an ordinal one's (ranks None) stay as they are, and a missing
    value (-1), or a level without a rank, becomes NaN, which the tree sends
    to the better side of each split."""
    if not maps:
        return X
    out = X.copy()
    for j, rank in maps:
        code = X[:, j]
        ok = code >= 0
        col = np.full(len(code), np.nan)
        col[ok] = code[ok] if rank is None else np.asarray(rank, dtype=float)[code[ok].astype(int)]
        out[:, j] = col
    return out


def maps_for(X, target, w, nominal, ordinal):
    """How one tree reads the categorical columns of X: each nominal column
    (nominal: [(column, number of levels)]) by the ranks of its levels in
    the tree's rows (level_ranks: target and w are the rows' target and
    weights), each ordinal one (ordinal: [column]) in its level order."""
    return [(j, level_ranks(X[:, j], target, w, u)) for j, u in nominal] + [(j, None) for j in ordinal]


def sample_mask(n, n_in, rs):
    """The rows of one boosting layer: n_in of the n training rows drawn
    without replacement from the RandomState rs, as scikit-learn's gradient
    boosting draws them (selection sampling)."""
    rand = rs.uniform(size=n)
    mask = np.zeros(n, dtype=bool)
    taken = 0
    for i in range(n):
        if rand[i] * (n - i) < n_in - taken:
            mask[i] = True
            taken += 1
    return mask


def boost_start(yt, wt, kind, n):
    """The raw prediction before the first layer, as scikit-learn's gradient
    boosting starts: the weighted mean (kind 'squared', a continuous
    response), the log odds of the second level ('binomial'), or each
    level's log share less their mean ('multinomial', n levels); a share is
    kept within machine epsilon of 0 and 1."""
    if kind == 'squared':
        return np.array([np.average(yt, weights=wt)])
    from scipy.special import logit
    eps = np.finfo(np.float64).eps
    counts = np.bincount(yt, weights=wt, minlength=n)
    share = np.clip(counts / counts.sum(), eps, 1 - eps)
    if kind == 'binomial':
        return np.array([logit(share[1])])
    return np.log(share / np.exp(np.mean(np.log(share))))


def boost_layer(Xt, yt, wt, raw, kind, lr, rs, row_rate, tree_args, nominal, ordinal):
    """One layer of the boosted tree, as scikit-learn's gradient boosting
    fits a stage: the rows drawn (row_rate below 1), then a regression tree
    on the negative gradient (the residuals; for three or more levels a tree
    per level), its leaves given a Newton step for a categorical response,
    and lr times its prediction added to raw, the training rows' raw
    predictions (updated in place). Each tree reads the nominal columns in
    the order of their levels' mean residual (maps_for), so that a split
    takes two groups of levels. rs: the one RandomState of the whole fit.
    Returns the layer's trees, [(tree, maps)]."""
    from sklearn.tree import DecisionTreeRegressor
    n = len(yt)
    if row_rate < 1:
        mask = sample_mask(n, max(1, int(row_rate * n)), rs)
        w = wt * mask
    else:
        mask, w = np.ones(n, dtype=bool), wt
    if kind == 'squared':
        neg = (yt - raw[:, 0])[:, None]
    elif kind == 'binomial':
        e = np.exp(-raw[:, 0])
        neg = -np.where(raw[:, 0] > -37, ((1 - yt) - yt * e) / (1 + e), np.exp(raw[:, 0]) - yt)[:, None]
    else:
        e = np.exp(raw - raw.max(axis=1, keepdims=True))
        neg = (yt[:, None] == np.arange(raw.shape[1])).astype(float) - e / e.sum(axis=1, keepdims=True)
    layer = []
    for k in range(neg.shape[1]):
        maps = maps_for(Xt, neg[:, k], w, nominal, ordinal)
        Xk = recode(Xt, maps)
        tree = DecisionTreeRegressor(random_state=rs, **tree_args).fit(Xk, neg[:, k], sample_weight=w)
        leaf = tree.apply(Xk)
        t = tree.tree_
        if kind != 'squared':
            yk = (yt == (1 if kind == 'binomial' else k)).astype(float)
            factor = 1.0 if kind == 'binomial' else (raw.shape[1] - 1) / raw.shape[1]
            for node in np.flatnonzero(t.children_left == -1):
                i = np.flatnonzero(mask & (leaf == node))
                g = neg[i, k]
                p = yk[i] - g
                num = np.average(g, weights=w[i]) * factor
                den = np.average(p * (1 - p), weights=w[i])
                t.value[node, 0, 0] = 0.0 if abs(den) < 1e-150 else float(num) / float(den)
        raw[:, k] += lr * t.value[:, 0, 0].take(leaf, axis=0)
        layer.append((tree, maps))
    return layer


def boost_value(raw, kind, classes, n_levels):
    """The boosted tree's prediction from its raw predictions: the value (a
    continuous response), or the probability of every one of n_levels
    levels, the logistic of the log odds (two levels) or the softmax of the
    level scores (more); classes: the levels the training rows have."""
    if kind == 'squared':
        return raw[:, 0].copy()
    from scipy.special import expit
    out = np.zeros((len(raw), n_levels))
    if kind == 'binomial':
        p = expit(raw[:, 0])
        out[:, classes[1]] = p
        out[:, classes[0]] = 1 - p
    else:
        e = np.exp(raw - raw.max(axis=1, keepdims=True))
        out[:, classes] = e / e.sum(axis=1, keepdims=True)
    return out


HELPERS = (parents, jmp_probs, oob_losses, kept_splits, stands_for, level_ranks, recode, maps_for)
BOOST_HELPERS = (level_ranks, recode, maps_for, sample_mask, boost_start, boost_layer, boost_value)


def _source(fns):
    out = []
    for fn in fns:
        try:
            out.append(inspect.getsource(fn).rstrip())
        except (OSError, TypeError):
            out.append(f'# (the source of {fn.__name__} could not be read here)')
    return out


# ---------------------------------------------------------------------------
# settings: JMP's names and defaults
# ---------------------------------------------------------------------------

def default_terms(p):
    """JMP's default Number of Terms Sampled per Split for p X columns:
    p - floor(p/4), about three quarters (JMP's own example: 13 terms, 10
    sampled; before JMP 16 it was floor(p/4))."""
    return max(1, p - p // 4)


def _num(v, d, lo=None, hi=None, integer=False, what=''):
    if v is None or v == '':
        return d
    try:
        x = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{what}: {v!r} is not a number')
    if not math.isfinite(x):
        raise ValueError(f'{what}: {v!r} is not a number')
    if integer:
        if abs(x - round(x)) > 1e-9:
            raise ValueError(f'{what} is a whole number, not {v}')
        x = int(round(x))
    if lo is not None and x < lo:
        raise ValueError(f'{what} is at least {lo}')
    if hi is not None and x > hi:
        raise ValueError(f'{what} is at most {hi}')
    return x


def settings_of(kind, s, p):
    """The platform's settings with JMP's defaults filled in and checked."""
    s = dict(s or {})
    if kind == 'forest':
        terms = _num(s.get('terms'), default_terms(p), 1, None, True, 'Number of Terms Sampled per Split')
        terms = min(terms, p)
        out = {
            'trees': _num(s.get('trees'), 100, 1, 5000, True, 'Number of Trees in the Forest'),
            'terms': terms,
            'rate': _num(s.get('rate'), 1.0, 1e-9, 1.0, False, 'Bootstrap Sample Rate'),
            'minSplits': _num(s.get('minSplits'), 10, 0, None, True, 'Minimum Splits per Tree'),
            'maxSplits': _num(s.get('maxSplits'), 2000, 1, 100000, True, 'Maximum Splits per Tree'),
            'minSize': _num(s.get('minSize'), 5, 1, None, True, 'Minimum Size Split'),
            'early': bool(s.get('early', True)),
            'multi': bool(s.get('multi', False)),
            'stop': s.get('stop', 'oob') if s.get('stop', 'oob') in ('oob', 'none') else 'oob',
        }
        out['maxTerms'] = min(p, max(terms, _num(s.get('maxTerms'), p, 1, None, True, 'Max Number of Terms')))
        if out['minSplits'] > out['maxSplits']:
            raise ValueError('Minimum Splits per Tree is more than Maximum Splits per Tree')
        return out
    out = {
        'layers': _num(s.get('layers'), 50, 1, 20000, True, 'Number of Layers'),
        'splits': _num(s.get('splits'), 3, 1, 1000, True, 'Splits per Tree'),
        'learn': _num(s.get('learn'), 0.1, 1e-9, 1.0, False, 'Learning Rate'),
        'minSize': _num(s.get('minSize'), 5, 1, None, True, 'Minimum Size Split'),
        'rowRate': _num(s.get('rowRate'), 1.0, 1e-9, 1.0, False, 'Row Sampling Rate'),
        'colRate': _num(s.get('colRate'), 1.0, 1e-9, 1.0, False, 'Column Sampling Rate'),
        'early': bool(s.get('early', True)),
        'multi': bool(s.get('multi', False)),
    }
    out['maxSplits'] = max(out['splits'], _num(s.get('maxSplits'), out['splits'], 1, 1000, True, 'Max Splits per Tree'))
    out['maxLearn'] = max(out['learn'], _num(s.get('maxLearn'), out['learn'], 1e-9, 1.0, False, 'Max Learning Rate'))
    return out


def terms_sequence(lo, hi):
    """The numbers of terms Multiple Fits tries: from lo, each about 1.25
    times the one before (at least one more), up to hi (JMP's example goes
    4, 5, 6, 8, 10)."""
    out = [lo]
    while out[-1] < hi:
        out.append(min(hi, max(out[-1] + 1, int(math.floor(1.25 * out[-1] + 0.5)))))
    return out


def grid_of(st):
    """The boosted trees Multiple Fits tries: every Splits per Tree from
    the lower to the upper bound, and learning rates in steps of 0.1."""
    splits = list(range(st['splits'], st['maxSplits'] + 1))
    rates = []
    r = st['learn']
    while r <= st['maxLearn'] + 1e-9 and len(rates) < 11:
        rates.append(round(r, 10))
        r += 0.1
    return [(s, r) for s in splits for r in rates]


def features_for(terms, p, n_features):
    """X columns tried at each split: the terms' share of the columns of X
    (a categorical term is a 0/1 column per level)."""
    if n_features == p:
        return int(terms)
    return int(max(1, min(n_features, round(terms * n_features / p))))


# ---------------------------------------------------------------------------
# measures of a set of rows (as predictive.measures computes them)
# ---------------------------------------------------------------------------

STAT_KEYS = {'continuous': ('rsquare', 'rase', 'mad'),
             'categorical': ('entropy_rsquare', 'mean_neg_log_p', 'rase', 'mad', 'misclassification')}
STAT_LABELS = {'rsquare': 'RSquare', 'rase': 'RASE', 'mad': 'Mean Abs Dev', 'entropy_rsquare': 'Entropy RSquare',
               'mean_neg_log_p': 'Mean -Log p', 'misclassification': 'Misclassification Rate'}


def _shares(P):
    tr = P.train()
    wt = P.weights(tr)
    return np.array([wt[P.target[tr] == j].sum() for j in range(len(P.levels))]) / wt.sum()


def stats_of(P, fitted, m, share=None, full=False):
    """The measures of the rows m: RSquare, RASE and Mean Abs Dev of a
    continuous response; Entropy RSquare, Mean -Log p, RASE, Mean Abs Dev
    and the Misclassification Rate of a categorical one (full: all of
    predictive.measures' columns)."""
    w = P.weights()[m]
    N = float(w.sum())
    if N <= 0:
        return None
    out = {'n': N}
    if P.kind == 'continuous':
        y, f = P.target[m], np.asarray(fitted, dtype=float)[m]
        r = y - f
        sse = float(np.sum(w * r * r))
        yb = float(np.sum(w * y) / N)
        sst = float(np.sum(w * (y - yb) ** 2))
        out.update({'rsquare': 1 - sse / sst if sst > 0 else None, 'rase': math.sqrt(sse / N), 'mad': float(np.sum(w * np.abs(r)) / N)})
        if full:
            out.update({'neg_loglik': 0.5 * N * (math.log(2 * math.pi * sse / N) + 1) if sse > 0 else None, 'sse': sse})
        return out
    share = _shares(P) if share is None else share
    y = P.target[m]
    p = np.asarray(fitted, dtype=float)[m]
    pt = np.clip(p[np.arange(len(y)), y], 1e-15, 1.0)
    ll = float(np.sum(w * np.log(pt)))
    ll0 = float(np.sum(w * np.log(np.clip(share[y], 1e-15, 1.0))))
    out.update({'entropy_rsquare': 1 - ll / ll0 if ll0 < 0 else None, 'mean_neg_log_p': -ll / N,
                'rase': math.sqrt(float(np.sum(w * (1 - pt) ** 2)) / N), 'mad': float(np.sum(w * (1 - pt)) / N),
                'misclassification': float(np.sum(w * (np.argmax(p, axis=1) != y)) / N)})
    if full:
        den = 1 - math.exp(2 * ll0 / N)
        out['generalized_rsquare'] = (1 - math.exp(2 * (ll0 - ll) / N)) / den if den > 0 else None
        out['neg_loglik'] = -ll
        if len(P.levels) == 2:
            out['auc'] = predictive._auc(p[:, 1], y == 1, w)
    return out


def _main_stat(P):
    return 'rsquare' if P.kind == 'continuous' else 'entropy_rsquare'


# ---------------------------------------------------------------------------
# a fitted forest or boosted tree
# ---------------------------------------------------------------------------

class Fit:
    """One forest or boosted tree: the model, how many trees or layers it
    keeps, the curves of Cumulative Validation, and its predictions."""

    def __init__(self):
        self.kind = None
        self.label = ''
        self.params = {}
        self.grown = 0
        self.kept = 0
        self.stopped = False
        self.curves = {}            # set -> stat -> [value after 1, 2, ... trees or layers]
        self.trees = []             # the forest's trees (cut back), each a dict
        self.layers = []            # the boosted tree's layers kept, each [(tree, maps)]: a tree per level for 3+ levels
        self.init = None            # ... the raw prediction before the first layer
        self.loss = None            # ... 'squared', 'binomial' or 'multinomial'
        self.fitted = None          # the prediction of every row of P
        self.oob = None             # the forest's out-of-bag prediction of the training rows
        self.oob_rows = None
        self.selection = None       # the statistics Model Validation-Set Summaries shows
        self.classes = None         # the levels the training rows have (a categorical response)
        self.n_levels = 0
        self.notes = []

    # ---- predictions of new rows (X coded as P.X is)
    def _forest_sum(self, X):
        s = None
        for T in self.trees[:self.kept]:
            v = T['est'][T['rep'][T['tree'].apply(recode(X, T['maps']))]]
            s = v if s is None else s + v
        return s / self.kept

    def raw(self, X):
        """The boosted tree's raw predictions of the rows X: the start plus each kept layer."""
        raw = np.tile(self.init, (X.shape[0], 1))
        lr = self.params['learning_rate']
        for layer in self.layers[:self.kept]:
            for k, (tree, maps) in enumerate(layer):
                raw[:, k] += lr * tree.tree_.value[:, 0, 0].take(tree.apply(recode(X, maps)), axis=0)
        return raw

    def predict(self, X):
        if self.kind == 'forest':
            return self._forest_sum(X)
        return boost_value(self.raw(X), self.loss, self.classes, self.n_levels)

    def proba(self, X, P=None):
        if self.kind == 'forest':
            out = np.zeros((X.shape[0], self.n_levels))
            out[:, self.classes] = self._forest_sum(X)
            return out
        return boost_value(self.raw(X), self.loss, self.classes, self.n_levels)


def _progress(what, done, total):
    print(f'smui:progress {what} {int(done)} {int(total)}', flush=True)


class _Progress:
    """'smui:progress' lines about every tenth of the work."""

    def __init__(self, what, total):
        self.what, self.total, self.done, self.next = what, max(1, int(total)), 0, 0

    def add(self, k=1):
        if k <= 0:
            return
        self.done = min(self.total, self.done + k)
        if self.done >= self.next or self.done == self.total:
            _progress(self.what, self.done, self.total)
            self.next = self.done + max(1, self.total // 10)

    def finish(self, part_total, part_done):
        """A fit that stopped early: its remaining share counts as done."""
        self.add(part_total - part_done)


def _record(curves, P, fitted, share, masks):
    for name, m in masks.items():
        s = stats_of(P, fitted, m, share)
        c = curves.setdefault(name, {})
        for key in STAT_KEYS[P.kind]:
            c.setdefault(key, []).append(None if s is None else s.get(key))


def _masks(P):
    return {SET_NAMES[k]: P.mask(k) for k in range(3) if P.has(k)}


def categorical_columns(P):
    """The columns of X (level numbers: P is coded 'ordinal') that hold a
    categorical X: the nominal ones, [(column, number of levels)], whose
    levels a split takes in two groups, and the ordinal ones, [column],
    which keep their level order."""
    nominal, ordinal = [], []
    for e in P.enc:
        if e['type'] == 'continuous':
            continue
        j = P.groups[e['name']][0]
        if data.meta(P.table, e['name']).get('modelingType') == 'ordinal':
            ordinal.append(int(j))
        else:
            nominal.append((int(j), len(e['levels'])))
    return nominal, ordinal


def forest_target(yt, ycol, classes):
    """What a forest's tree orders a nominal X's levels by: the response
    (continuous), the second level's 0/1 column (two levels), or every
    level's (three or more: level_ranks takes their first principal
    component)."""
    if classes is None:
        return yt
    if len(classes) == 2:
        return (ycol == 1).astype(float)
    return np.eye(len(classes))[ycol]


def grow_forest(P, st, terms, seed, prog):
    """A Decision Forest: its trees grown one at a time, each on a
    bootstrap sample drawn as scikit-learn's RandomForestRegressor draws it
    (a seed per tree from the report's seed: the first k trees do not
    depend on how many are grown), its nominal columns read in the order of
    the sample's level means (maps_for), cut back by JMP's rule; with
    validation rows and Early Stopping on, growth stops when the last tenth
    of the trees asked for (at least 5) has not improved the validation
    statistic, and the best number is kept."""
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
    cat = P.kind == 'categorical'
    tr = P.train()
    tr_idx = np.flatnonzero(tr)
    Xt, yt = P.X[tr], P.target[tr]
    w1 = np.ones(len(yt)) if P.w is None else np.asarray(P.w[tr], dtype=float)
    if cat and len(np.unique(yt)) < 2:
        raise ValueError(f'{P.y} has one level in the training rows: nothing to classify')
    K = st['trees']
    nf = P.X.shape[1]
    kf = features_for(terms, len(P.x), nf)
    n_tr = len(yt)
    n_boot = n_tr if st['rate'] >= 1 else max(round(n_tr * float(st['rate'])), 1)
    params = dict(criterion='entropy' if cat else 'squared_error', max_features=kf, max_leaf_nodes=st['maxSplits'] + 1, min_samples_leaf=st['minSize'])
    Cls = DecisionTreeClassifier if cat else DecisionTreeRegressor
    nominal, ordinal = categorical_columns(P)
    classes = np.unique(yt).astype(int) if cat else None
    ycol = np.searchsorted(classes, yt) if cat else None     # the row's level among the tree's columns
    target = forest_target(yt, ycol, classes)
    seeds = np.random.RandomState(int(seed)).randint(np.iinfo(np.int32).max, size=K)
    F = Fit()
    F.kind, F.params = 'forest', dict(params, n_boot=int(n_boot), random_state=int(seed), n_features=kf, terms=terms)
    F.label = f'{terms} terms'
    early = st['early'] and P.has(1)
    patience = max(5, int(math.ceil(K / 10)))
    n = len(P.index)
    masks = _masks(P)
    share = _shares(P) if cat else None
    L = len(P.levels) if cat else 0
    S = np.zeros((n, L)) if cat else np.zeros(n)
    oob_sum = np.zeros((n_tr, L)) if cat else np.zeros(n_tr)
    oob_cnt = np.zeros(n_tr)
    oob_curve = {}
    best_k, best_v, best_S, best_oob = 0, -math.inf, None, None
    grown = 0
    vmask = P.mask(1)
    for b in range(K):
        s_b = int(seeds[b])
        inbag = np.bincount(np.random.RandomState(s_b).randint(0, n_tr, n_boot, dtype=np.int32), minlength=n_tr)
        sw = w1 * inbag
        maps = maps_for(Xt, target, sw, nominal, ordinal)
        tree = Cls(random_state=s_b, **params).fit(recode(Xt, maps), yt, sample_weight=sw)
        T = _forest_tree(tree, maps, inbag, P, Xt, ycol if cat else yt, w1, cat, st, classes, L)
        F.trees.append(T)
        grown += 1
        S += T['all']
        ob = T.pop('oob')
        oob_sum[ob] += T['all'][tr_idx][ob]
        oob_cnt[ob] += 1
        T.pop('all')             # not kept: the forest's sums have it
        cur = S / grown
        _record(F.curves, P, cur, share, masks)
        _oob_record(oob_curve, P, tr_idx, oob_sum, oob_cnt, share)
        prog.add(1)
        if early:
            v = stats_of(P, cur, vmask, share)[_main_stat(P)]
            v = -math.inf if v is None else v
            if v > best_v:
                best_v, best_k, best_S, best_oob = v, grown, cur.copy(), (oob_sum.copy(), oob_cnt.copy())
            elif grown - best_k >= patience:
                F.stopped = True
                break
    prog.finish(K, grown)
    if not early:
        best_k, best_S, best_oob = grown, S / grown, (oob_sum, oob_cnt)
    F.grown, F.kept = grown, best_k
    F.fitted = best_S
    F.curves['Out of Bag'] = oob_curve
    s, c = best_oob
    F.oob_rows = c > 0
    F.oob = np.where(c[:, None] > 0, s / np.maximum(c, 1)[:, None], 0.0) if cat else np.where(c > 0, s / np.maximum(c, 1), np.nan)
    F.classes, F.n_levels = classes, L
    F.patience = patience
    return F


def _oob_record(curve, P, tr_idx, oob_sum, oob_cnt, share):
    ok = oob_cnt > 0
    m = np.zeros(len(P.index), dtype=bool)
    m[tr_idx[ok]] = True
    fitted = np.zeros((len(P.index), oob_sum.shape[1])) if oob_sum.ndim == 2 else np.zeros(len(P.index))
    fitted[tr_idx[ok]] = oob_sum[ok] / (oob_cnt[ok][:, None] if oob_sum.ndim == 2 else oob_cnt[ok])
    s = stats_of(P, fitted, m, share) if ok.any() else None
    for key in STAT_KEYS[P.kind]:
        curve.setdefault(key, []).append(None if s is None else s.get(key))


def _forest_tree(tree, maps, inbag, P, Xt, yt, w1, cat, st, classes, L):
    """One tree of the forest (maps: how it reads the categorical columns):
    cut back (JMP's rule, unless the Tree Size setting says grow to the
    maximum), its estimate at every node, its prediction of every row, and
    its Per-Tree Summaries line."""
    t = tree.tree_
    parent = parents(tree)
    est = jmp_probs(tree, LAMBDA) if cat else t.value[:, 0, 0].copy()
    oob = inbag == 0
    loss = oob_losses(tree, recode(Xt[oob], maps), yt[oob], w1[oob], est, cat)
    total = len(loss) - 1
    kept = kept_splits(loss, st['minSplits']) if st['stop'] == 'oob' else total
    before = loss[kept + 1] if kept < total else loss[kept]
    rep = stands_for(parent, kept)
    node_all = rep[tree.apply(recode(P.X, maps))]
    if cat:
        full = np.zeros((t.node_count, L))
        full[:, classes] = est
        pred = full[node_all]
    else:
        pred = est[node_all]
    T = {'tree': tree, 'maps': maps, 'rep': rep, 'est': est, 'kept': kept, 'total': total, 'all': pred, 'oob': oob, 'parent': parent}
    # the summaries: in bag (each row as often as it was drawn) and out of bag
    trp = pred[P.train()]
    cw = inbag * w1
    oob_n = float(w1[oob].sum())
    row = {'splits': kept, 'oob_loss': float(before), 'oob_n': oob_n, 'oob_loss_n': float(before) / oob_n if oob_n > 0 else None}
    if not cat:
        y = P.target[P.train()]
        ib_n = float(cw.sum())
        ib_sse = float(np.sum(cw * (y - trp) ** 2))
        yb = float(np.sum(cw * y) / ib_n)
        ib_sst = float(np.sum(cw * (y - yb) ** 2))
        oob_sse = float(np.sum(w1[oob] * (y[oob] - trp[oob]) ** 2))
        row.update({'rsquare': 1 - ib_sse / ib_sst if ib_sst > 0 else None, 'ib_sse': ib_sse, 'ib_n': ib_n, 'ib_sse_n': ib_sse / ib_n,
                    'oob_sse': oob_sse, 'oob_sse_n': oob_sse / oob_n if oob_n > 0 else None})
    T['row'] = row
    # the splits kept, for Column Contributions
    k = np.arange(1, kept + 1)
    split = parent[2 * k - 1] if kept else np.zeros(0, dtype=int)
    T['split_features'] = t.feature[split]
    T['split_gain'] = _gains(t, split, 2 * k - 1, 2 * k, cat)
    return T


def _node_loss(t, cat):
    """Each node's SS (continuous) or G² (categorical) of its training rows."""
    N = t.weighted_n_node_samples
    if not cat:
        return t.impurity * N
    n = t.value[:, 0, :] * N[:, None]
    with np.errstate(divide='ignore', invalid='ignore'):
        g = np.where(n > 0, n * np.log(n / N[:, None]), 0.0)
    return -2.0 * g.sum(axis=1)


def _gains(t, split, left, right, cat):
    f = _node_loss(t, cat)
    return f[split] - f[left] - f[right]


def grow_boosted(P, st, splits, learn, seed, prog):
    """A Boosted Tree: layer after layer (boost_layer), scikit-learn's
    gradient boosting with its trees of Splits per Tree splits grown best
    first, from one RandomState of the report's seed; with validation rows
    and Early Stopping on, the fit stops at the first layer that does not
    improve the validation statistic (JMP: 'until fitting an additional
    layer no longer improves the validation statistic') and keeps the
    layers before it."""
    cat = P.kind == 'categorical'
    tr = P.train()
    Xt = P.X[tr]
    wt = np.ones(int(tr.sum())) if P.w is None else np.asarray(P.w[tr], dtype=float)
    if cat:
        classes = np.unique(P.target[tr]).astype(int)
        if len(classes) < 2:
            raise ValueError(f'{P.y} has one level in the training rows: nothing to classify')
        yt = np.searchsorted(classes, P.target[tr])
        loss = 'binomial' if len(classes) == 2 else 'multinomial'
    else:
        classes, yt, loss = None, np.asarray(P.target[tr], dtype=float), 'squared'
    nf = P.X.shape[1]
    cols = None if st['colRate'] >= 1 else int(max(1, min(nf, round(st['colRate'] * nf))))
    tree_args = dict(criterion='squared_error', max_leaf_nodes=int(splits) + 1, min_samples_leaf=st['minSize'], max_features=cols)
    nominal, ordinal = categorical_columns(P)
    lr = float(learn)
    F = Fit()
    F.kind = 'boosted'
    F.params = dict(tree_args, loss=loss, learning_rate=lr, splits=int(splits), subsample=float(st['rowRate']), random_state=int(seed))
    F.label = f'{splits} splits, learning rate {learn:g}'
    F.loss, F.classes, F.n_levels = loss, classes, (len(P.levels) if cat else 0)
    F.init = boost_start(yt, wt, loss, len(classes) if cat else 1)
    early = st['early'] and P.has(1)
    vmask = P.mask(1)
    share = _shares(P) if cat else None
    masks = _masks(P)
    rs = np.random.RandomState(int(seed))
    raw = np.tile(F.init, (len(yt), 1))              # the training rows' raw predictions
    raw_all = np.tile(F.init, (len(P.index), 1))     # every row's
    best, best_v = 0, -math.inf
    for i in range(st['layers']):
        layer = boost_layer(Xt, yt, wt, raw, loss, lr, rs, float(st['rowRate']), tree_args, nominal, ordinal)
        for k, (tree, maps) in enumerate(layer):
            raw_all[:, k] += lr * tree.tree_.value[:, 0, 0].take(tree.apply(recode(P.X, maps)), axis=0)
        F.layers.append(layer)
        cur = boost_value(raw_all, loss, classes, F.n_levels)
        _record(F.curves, P, cur, share, masks)       # Cumulative Validation: every set after each layer
        prog.add(1)
        if early:
            v = stats_of(P, cur, vmask, share)[_main_stat(P)]
            v = -math.inf if v is None else v
            if v > best_v:
                best_v, best = v, i + 1
            else:
                break
    grown = len(F.layers)
    prog.finish(st['layers'], grown)
    F.grown = grown
    F.stopped = early and grown < st['layers']
    F.kept = max(1, best if early else grown)
    F.layers = F.layers[:F.kept]                      # the layers kept (a fit of that many layers is the same)
    F.fitted = F.predict(P.X)
    return F


class _Sub:
    """The validation rows of P as a P of their own, for stats_of."""

    def __init__(self, P, m):
        self.kind, self.levels = P.kind, P.levels
        self.target = P.target[m]
        self.w = None if P.w is None else P.w[m]

    def weights(self, m=None):
        w = np.ones(len(self.target)) if self.w is None else self.w
        return w if m is None else w[m]


# ---------------------------------------------------------------------------
# the model of a report (cached)
# ---------------------------------------------------------------------------

class Model:
    def __init__(self):
        self.P = None
        self.kind = None
        self.st = None
        self.fits = []
        self.best = 0
        self.by = 'validation'     # how the best of several fits was chosen
        self.seed = None
        self.notes = []
        self.cv = {}               # a K-fold Validation column: each fit's crossvalidation (crossvalidated)


def crossvalidated(M, i):
    """With a K-fold Validation column (every row trains): fit i crossvalidated by its folds, the forest or
    boosted tree of the same settings grown on the other folds predicting each fold (predictive.crossvalidate,
    by predictive.fold_masks); None without folds. Kept with the model."""
    P = M.P
    if P.folds is None:
        return None
    if i not in M.cv:
        F, st = M.fits[i], M.st
        prog = _Progress(M.kind, (st['trees'] if M.kind == 'forest' else st['layers']) * P.k)

        def fit_predict(fit_rows):
            Q = copy.copy(P)
            Q.sets = np.where(fit_rows, 0, 2)        # the held fold's rows: predicted, never fitted
            if M.kind == 'forest':
                return grow_forest(Q, st, F.params['terms'], M.seed, prog).fitted
            return grow_boosted(Q, st, F.params['splits'], F.params['learning_rate'], M.seed, prog).fitted
        M.cv[i] = predictive.crossvalidate(P, fit_predict)
    return M.cv[i]


def _prepared(table, rows, y, x, weight, freq, validation, portion, seed, missing):
    return predictive.prepare(table, y, list(x or []), rows=rows, weight=weight, freq=freq, validation=validation,
                              portion=portion, seed=seed, missing=missing, coding='ordinal')


def model_of(table, rows, y, x, kind, weight=None, freq=None, validation=None, portion=0.0, seed=None,
             missing='informative', settings=None):
    """The fitted forest or boosted tree of a report, built once."""
    if kind not in ('forest', 'boosted'):
        raise ValueError(f'no ensemble {kind!r}')
    seed = predictive.seed_of(seed)
    if seed is None:
        seed = 1
    x = list(x or [])
    st = settings_of(kind, settings, len(x))
    spec = {'y': y, 'x': x, 'kind': kind, 'weight': weight, 'freq': freq, 'validation': validation,
            'portion': float(portion or 0), 'seed': seed, 'missing': missing, 'settings': st}

    def build():
        P = _prepared(table, rows, y, x, weight, freq, validation, portion, seed, missing)
        M = Model()
        M.P, M.kind, M.st, M.seed = P, kind, st, seed
        has_valid = P.has(1)
        if kind == 'forest':
            seq = terms_sequence(st['terms'], st['maxTerms']) if st['multi'] else [st['terms']]
            prog = _Progress('forest', st['trees'] * len(seq))
            M.fits = [grow_forest(P, st, m, seed, prog) for m in seq]
            M.by = 'validation' if has_valid else 'oob'
        else:
            grid = grid_of(st) if st['multi'] else [(st['splits'], st['learn'])]
            if st['multi'] and not has_valid:
                M.notes.append('Multiple Fits chooses by the validation rows, and there are none: one boosted tree is fitted.')
                grid = [(st['splits'], st['learn'])]
            if len(grid) > 60:
                raise ValueError(f'Multiple Fits: {len(grid)} boosted trees is too many (at most 60); narrow the splits or the learning rates')
            prog = _Progress('boosted', st['layers'] * len(grid))
            M.fits = [grow_boosted(P, st, s, r, seed, prog) for s, r in grid]
            M.by = 'validation'
        for F in M.fits:
            F.selection = _selection(P, F, M.by)
        key = _main_stat(P)
        vals = [(-math.inf if F.selection.get(key) is None else F.selection[key]) for F in M.fits]
        M.best = int(np.argmax(vals)) if len(M.fits) > 1 else 0
        return M
    return predictive.cached('ensemble', table, rows, spec, build)


def _selection(P, F, by):
    """The statistics of a fit that choose among several: the validation
    set's, or (a forest without validation rows) the out-of-bag ones."""
    if P.has(1):
        return stats_of(P, F.fitted, P.mask(1)) or {}
    if F.kind == 'forest':
        m = np.zeros(len(P.index), dtype=bool)
        m[np.flatnonzero(P.train())[F.oob_rows]] = True
        full = np.zeros_like(F.fitted)
        full[np.flatnonzero(P.train())[F.oob_rows]] = F.oob[F.oob_rows]
        return (stats_of(P, full, m) or {}) if m.any() else {}
    return stats_of(P, F.fitted, P.train()) or {}


def _shown(M, shown):
    if shown is None or shown == '':
        return M.best
    try:
        i = int(shown)
    except (TypeError, ValueError):
        return M.best
    return i if 0 <= i < len(M.fits) else M.best


def _model_args(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings):
    return model_of(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings)


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------

@api('ensemble.fit', packages=SK)
def fit(table, y, x, kind='forest', rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
        missing='informative', settings=None, shown=None, plot=None, table_name='data', keep=None):
    """Everything the Decision Forest or Boosted Tree report shows. plot:
    the page's choices for the graphs' code ({'stat': the statistic
    Cumulative Validation shows}); keep: the page's key for the report (its
    id and By group), under which the fit shown is kept for Score Rows."""
    M = _model_args(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings)
    P, st = M.P, M.st
    i = _shown(M, shown)
    F = M.fits[i]
    predictive.keep(keep, {'kind': 'ensemble', 'ensemble': kind, 'M': M, 'F': F})
    cat = P.kind == 'categorical'
    head = _code(P, M, F, table_name, rows, graph=True)
    rep = predictive.report(P, F.fitted, head=head)
    rep['plots']['cumulative'] = _cumulative_tail(P, F, (plot or {}).get('stat'))
    out = {'kind': kind, 'response': P.kind, 'fit': rep, 'shown': i, 'best': M.best, 'multi': len(M.fits) > 1, 'by': M.by,
           'notes': list(M.notes), 'seed': M.seed, 'terms': len(P.x), 'n_features': int(P.X.shape[1])}
    out['spec'] = _spec_rows(P, M, F, table, validation)
    out['summaries'] = _summaries(M) if len(M.fits) > 1 else None
    out['cumulative'] = _cumulative(P, F)
    if kind == 'forest':
        out['trees'] = _per_tree(P, F)
        oob = _oob_measures(P, F)
        if oob:
            rep['measures'].append(oob)
        if not cat:
            rows_ = [T['row'] for T in F.trees[:F.kept]]
            ib = [math.sqrt(r['ib_sse_n']) for r in rows_]
            oo = [math.sqrt(r['oob_sse_n']) for r in rows_ if r['oob_sse_n'] is not None]
            out['individual'] = [{'what': 'In Bag', 'rase': float(np.mean(ib))}, {'what': 'Out of Bag', 'rase': float(np.mean(oo)) if oo else None}]
    out['contributions'] = _contributions(P, F)
    out['contributions']['plot_code'] = '\n'.join(_contrib_lines(P, F) + predictive.contribution_lines(len(P.x)))
    notes = []
    if kind == 'forest':
        short = sum(1 for T in F.trees[:F.kept] if T['total'] < st['minSplits'])
        if short:
            notes.append(f'{short} of the {F.kept} trees have fewer than {st["minSplits"]} splits (Minimum Splits per Tree): no split was left that keeps {st["minSize"]} rows on each side.')
    if P.X.shape[1] != len(P.x):
        notes.append(f'The {len(P.x)} X columns are {P.X.shape[1]} columns for the trees: a continuous column with missing values has a 0/1 Missing column beside it (its missing values are its training mean).')
    out['notes'] += notes
    cv = crossvalidated(M, i)
    if cv:
        rep['measures'].append(dict(cv['measures'], set='Crossvalidation'))
        what = 'forest' if kind == 'forest' else 'boosted tree'
        out['notes'].append(f'Crossvalidation: each row predicted by the {what} of these settings grown without its fold, the {P.k} folds of {validation} (every row trains the {what} above).')
        out['crossvalidation'] = {'folds': cv['folds'], 'k': int(P.k), 'column': validation}
    out['code'] = _code(P, M, F, table_name, rows)
    return out


def _spec_rows(P, M, F, table, validation):
    """The Specifications report: the settings used in the fit shown."""
    st = M.st
    n = {k: int(P.mask(k).sum()) for k in range(3)}
    left = [['Target Column', P.y, 'text']]
    if validation:
        left.append(['Validation Column', validation, 'text'])
    elif P.spec.get('portion'):
        left.append(['Validation Portion', P.spec['portion']])
    right = [['Training Rows', n[0], 'int'], ['Validation Rows', n[1], 'int'], ['Test Rows', n[2], 'int'], ['Number of Terms', len(P.x), 'int']]
    if M.kind == 'forest':
        left += [['Number of Trees in the Forest', st['trees'], 'int'], ['Number of Trees Kept', F.kept, 'int'],
                 ['Number of Terms Sampled per Split', F.params['terms'], 'int'], ['Bootstrap Sample Rate', st['rate']]]
        n_boot = n[0] if st['rate'] >= 1 else max(1, int(round(n[0] * st['rate'])))
        right += [['Bootstrap Samples', n_boot, 'int'], ['Minimum Splits per Tree', st['minSplits'], 'int'],
                  ['Maximum Splits per Tree', st['maxSplits'], 'int'], ['Minimum Size Split', st['minSize'], 'int']]
    else:
        left += [['Number of Layers', st['layers'], 'int'], ['Number of Layers Kept', F.kept, 'int'],
                 ['Splits per Tree', F.params['splits'], 'int'], ['Learning Rate', F.params['learning_rate']]]
        right += [['Minimum Size Split', st['minSize'], 'int'], ['Row Sampling Rate', st['rowRate']], ['Column Sampling Rate', st['colRate']]]
    early = st['early'] and P.has(1)
    left.append(['Early Stopping', 'On' if early else ('Off' if P.has(1) else 'Off (no validation rows)'), 'text'])
    left.append(['Random Seed', M.seed, 'int'])
    return {'left': left, 'right': right}


def _summaries(M):
    """Model Validation-Set Summaries: every fit, best marked."""
    P = M.P
    keys = STAT_KEYS[P.kind]
    rows = []
    for j, F in enumerate(M.fits):
        r = {'index': j, 'best': j == M.best}
        if F.kind == 'forest':
            r.update({'n_terms': F.params['terms'], 'n_trees': F.kept})
        else:
            r.update({'splits': F.params['splits'], 'learn': F.params['learning_rate'], 'n_layers': F.kept})
        for k in keys:
            r[k] = F.selection.get(k)
        rows.append(r)
    return {'rows': rows, 'keys': list(keys), 'by': M.by}


def _cumulative(P, F):
    """Cumulative Validation: each set's statistics after 1, 2, ... trees
    or layers, and the number kept."""
    series = []
    for name in (list(SET_NAMES) + (['Out of Bag'] if F.kind == 'forest' else [])):
        if name in F.curves and F.curves[name]:
            series.append({'set': name, 'stats': F.curves[name]})
    return {'x': list(range(1, F.grown + 1)), 'series': series, 'kept': F.kept, 'grown': F.grown, 'stopped': F.stopped,
            'keys': list(STAT_KEYS[P.kind]), 'patience': getattr(F, 'patience', 1)}


def _per_tree(P, F):
    rows = [dict(T['row'], tree=j + 1) for j, T in enumerate(F.trees[:F.kept])]
    order = sorted(range(len(rows)), key=lambda j: (math.inf if rows[j]['oob_loss_n'] is None else rows[j]['oob_loss_n'], j))
    for rank, j in enumerate(order, start=1):
        rows[j]['rank'] = rank
    return rows


def _oob_measures(P, F):
    """The forest's out-of-bag prediction of the training rows (each by the
    trees that did not see it), as a line of Overall Statistics."""
    tr_idx = np.flatnonzero(P.train())
    ok = F.oob_rows
    if not ok.any():
        return None
    m = np.zeros(len(P.index), dtype=bool)
    m[tr_idx[ok]] = True
    full = np.zeros_like(F.fitted)
    full[tr_idx[ok]] = F.oob[ok]
    s = stats_of(P, full, m, full=True)
    s['set'] = 'Out of Bag'
    return s


def _contributions(P, F):
    """Column Contributions: per X column, the number of splits on it over
    every tree or layer and the SS or G² they take away."""
    feat_col = {}
    for c in P.x:
        for j in P.groups[c]:
            feat_col[j] = c
    count = {c: 0 for c in P.x}
    value = {c: 0.0 for c in P.x}
    if F.kind == 'forest':
        for T in F.trees[:F.kept]:
            for f, g in zip(T['split_features'], T['split_gain']):
                c = feat_col[int(f)]
                count[c] += 1
                value[c] += float(g)
        label = 'G²' if P.kind == 'categorical' else 'SS'
    else:
        for layer in F.layers:
            for tree, _maps in layer:
                t = tree.tree_
                inner = np.flatnonzero(t.children_left >= 0)
                g = _gains(t, inner, t.children_left[inner], t.children_right[inner], False)
                for f, v in zip(t.feature[inner], g):
                    c = feat_col[int(f)]
                    count[c] += 1
                    value[c] += float(v)
        label = 'SS'
    tot = sum(max(v, 0.0) for v in value.values())
    rows = [{'column': c, 'splits': count[c], 'value': value[c], 'portion': value[c] / tot if tot > 0 else None} for c in P.x]
    rows.sort(key=lambda r: -r['value'])
    return {'rows': rows, 'label': label}


# ---------------------------------------------------------------------------
# the code under the report
# ---------------------------------------------------------------------------

def _code(P, M, F, table_name, rows, graph=False):
    """Python that builds the same model from a CSV export of the table and
    prints the Cumulative Validation curves and the Overall Statistics.
    graph: the head of the graphs' code instead (predictive.graph_codes):
    matplotlib imported, each tree's out-of-bag rows and kept splits kept
    (oobs, kept_of), no printing, and fitted, every row's prediction."""
    cat = P.kind == 'categorical'
    st = M.st
    p = F.params
    forest = F.kind == 'forest'
    cls = 'DecisionTreeClassifier' if forest and cat else 'DecisionTreeRegressor'
    L = P.code(table_name, rows, extra_imports=([predictive.PLT] if graph else []) + [f'from sklearn.tree import {cls}'])
    L += ['', 'SETS = ["Training", "Validation", "Test"]', "ww = np.ones(len(y)) if w is None else w   # each row's weight"]
    if cat:
        L.append('share = np.array([ww[train][y[train] == j].sum() for j in range(len(levels))]) / ww[train].sum()   # the training shares of the levels')
    L += ['', 'def stats(fitted, m):']
    if cat:
        L += ['    """Entropy RSquare, Mean -Log p, RASE, Mean Abs Dev and Misclassification Rate of the rows m."""',
              '    ym, p, wm = y[m], fitted[m], ww[m]',
              '    pt = np.clip(p[np.arange(len(ym)), ym], 1e-15, 1)',
              '    ll, ll0, N = np.sum(wm * np.log(pt)), np.sum(wm * np.log(np.clip(share[ym], 1e-15, 1))), wm.sum()',
              '    return [1 - ll / ll0, -ll / N, np.sqrt(np.sum(wm * (1 - pt) ** 2) / N), np.sum(wm * (1 - pt)) / N, np.sum(wm * (p.argmax(1) != ym)) / N]']
    else:
        L += ['    """RSquare, RASE and Mean Abs Dev of the rows m."""',
              '    ym, f, wm = y[m], fitted[m], ww[m]',
              '    N = wm.sum(); sse = np.sum(wm * (ym - f) ** 2)',
              '    return [1 - sse / np.sum(wm * (ym - np.sum(wm * ym) / N) ** 2), np.sqrt(sse / N), np.sum(wm * np.abs(ym - f)) / N]']
    L.append('')
    L += _source(HELPERS if forest else BOOST_HELPERS)
    L.append('')
    nominal, ordinal = categorical_columns(P)
    L.append(f'NOMINAL = {json.dumps([[j, u] for j, u in nominal])}   # the nominal X columns: their column of X and number of levels (a split takes two groups of levels)')
    L.append(f'ORDINAL = {json.dumps(ordinal)}   # the ordinal ones: a split keeps their level order')
    if forest:
        L.append(f'# the forest: {F.grown} trees grown, the first {F.kept} kept' + (f' (early stopping: {F.grown - F.kept} more trees did not improve the validation statistic)' if F.stopped else ''))
        L.append('Xt, yt, wt = X[train], y[train], ww[train]')
        if cat:
            L.append('ycol = np.searchsorted(np.unique(yt), yt)   # each training row\'s level among the levels the training rows have')
            if len(F.classes) == 2:
                L.append('target = (ycol == 1).astype(float)   # a tree orders a nominal X\'s levels by their share of the second level')
            else:
                L.append(f'target = np.eye({len(F.classes)})[ycol]   # a tree orders a nominal X\'s levels by the first principal component of their shares')
        else:
            L.append('target = yt   # a tree orders a nominal X\'s levels by their mean response')
        L.append(f'seeds = np.random.RandomState({p["random_state"]}).randint(np.iinfo(np.int32).max, size={F.grown})   # a seed per tree, drawn as scikit-learn\'s forests draw them')
        L.append('forest = []   # each tree cut back: the tree, how it reads the categorical columns, its estimate at every node, the node each node falls in')
        if graph:
            L.append('oobs, kept_of = [], []   # each tree\'s out-of-bag rows (of the training rows) and the splits it keeps')
        L.append('for s in seeds:')
        L.append(f'    inbag = np.bincount(np.random.RandomState(s).randint(0, len(yt), {p["n_boot"]}, dtype=np.int32), minlength=len(yt))   # the bootstrap sample: how often each training row was drawn')
        L.append('    maps = maps_for(Xt, target, wt * inbag, NOMINAL, ORDINAL)   # the order of each nominal column\'s levels in the sample')
        L.append(f'    tree = {cls}(criterion={p["criterion"]!r}, max_features={p["max_features"]}, max_leaf_nodes={p["max_leaf_nodes"]}, '
                 f'min_samples_leaf={p["min_samples_leaf"]}, random_state=int(s))')
        L.append('    tree.fit(recode(Xt, maps), yt, sample_weight=wt * inbag)')
        L.append('    oob = inbag == 0   # the training rows the tree did not see')
        if cat:
            L.append(f'    est = jmp_probs(tree, {LAMBDA})')
            L.append('    loss = oob_losses(tree, recode(Xt[oob], maps), ycol[oob], wt[oob], est, True)')
            L.append("    full = np.zeros((tree.tree_.node_count, len(levels))); full[:, tree.classes_] = est   # a column for every level")
        else:
            L.append('    full = tree.tree_.value[:, 0, 0]')
            L.append('    loss = oob_losses(tree, recode(Xt[oob], maps), yt[oob], wt[oob], full, False)')
        if st['stop'] == 'oob':
            L.append(f"    kept = kept_splits(loss, {st['minSplits']})   # JMP's rule, Minimum Splits per Tree {st['minSplits']}")
        else:
            L.append('    kept = len(loss) - 1   # every split: the tree as scikit-learn grew it')
        L.append('    forest.append((tree, maps, full, stands_for(parents(tree), kept)))')
        if graph:
            L.append('    oobs.append(oob)')
            L.append('    kept_of.append(kept)')
        L.append("each = [est[rep[tree.apply(recode(X, maps))]] for tree, maps, est, rep in forest]   # every tree's prediction of every row")
        L.append('cum = np.cumsum(each, axis=0) / np.arange(1, len(each) + 1).reshape((-1,) + (1,) * each[0].ndim)   # the forest of the first k trees')
        L.append(f'KEPT = {F.kept}')
        L.append('')
        L.append('def predict(Xnew):')
        L.append('    """The forest of the trees kept: the mean of their predictions."""')
        L.append('    return np.mean([est[rep[tree.apply(recode(Xnew, maps))]] for tree, maps, est, rep in forest[:KEPT]], axis=0)')
    else:
        lr = p['learning_rate']
        L.append('Xt, wt = X[train], ww[train]')
        if cat:
            L.append('classes = np.unique(y[train])   # the levels the training rows have')
            L.append('yt = np.searchsorted(classes, y[train])   # ... numbered from 0')
        else:
            L.append('yt, classes = y[train], None')
        words = {'squared': 'squared error: each layer fits the residuals', 'binomial': 'the log likelihood of two levels: each layer adds to the log odds',
                 'multinomial': 'the log likelihood of several levels: each layer has a tree per level'}[F.loss]
        L.append(f'KIND = {F.loss!r}   # {words}')
        L.append(f'init = boost_start(yt, wt, KIND, {len(F.classes) if cat else 1})   # the start, before the first layer')
        L.append(f'tree_args = dict(criterion="squared_error", max_leaf_nodes={p["max_leaf_nodes"]}, min_samples_leaf={p["min_samples_leaf"]}, max_features={p["max_features"]!r})')
        L.append(f'rs = np.random.RandomState({p["random_state"]})   # one RandomState for the row samples and the trees, drawn in scikit-learn\'s order')
        L.append('raw = np.tile(init, (len(yt), 1))   # the training rows\' raw predictions, which each layer adds to')
        L.append(f'layers = [boost_layer(Xt, yt, wt, raw, KIND, {lr!r}, rs, {p["subsample"]!r}, tree_args, NOMINAL, ORDINAL) for _ in range({F.grown})]'
                 + f'   # {F.grown} layers fitted' + (' (early stopping: the last did not improve the validation statistic)' if F.stopped else ''))
        L.append(f'KEPT = {F.kept}   # the layers kept')
        L.append('')
        L.append('def staged(Xnew):')
        L.append('    """The raw predictions of the rows Xnew after each layer."""')
        L.append('    raw = np.tile(init, (len(Xnew), 1))')
        L.append('    for layer in layers:')
        L.append('        for k, (tree, maps) in enumerate(layer):')
        L.append(f'            raw[:, k] += {lr!r} * tree.tree_.value[:, 0, 0].take(tree.apply(recode(Xnew, maps)), axis=0)')
        L.append('        yield raw.copy()')
        L.append('')
        L.append(f'cum = [boost_value(r, KIND, classes, {len(P.levels) if cat else 0}) for r in staged(X)]   # the model after 1, 2, ... layers')
        L.append('')
        L.append('def predict(Xnew):')
        L.append('    """The boosted tree of the layers kept."""')
        L.append('    for k, r in enumerate(staged(Xnew), start=1):')
        L.append('        if k == KEPT:')
        L.append(f'            return boost_value(r, KIND, classes, {len(P.levels) if cat else 0})')
    what = 'trees' if forest else 'layers'
    if graph:
        L.append('fitted = predict(X)   # each row\'s prediction, or its probability of every level')
        return '\n'.join(L)
    L.append('')
    L.append(f'# Cumulative Validation: {STAT_LABELS[_main_stat(P)]} of each set against the number of {what}')
    L.append('for k, name in enumerate(SETS):')
    L.append('    if (sets == k).any():')
    L.append('        print("curve", name, *[float(stats(c, sets == k)[0]) for c in cum])')
    L.append('')
    L.append('# Overall Statistics')
    L.append('fitted = predict(X)')
    L.append('for k, name in enumerate(SETS):')
    L.append('    if (sets == k).any():')
    L.append('        print("measures", name, *[float(v) for v in stats(fitted, sets == k)])')
    if P.folds is not None:
        L += _cv_lines(P, M, F)
    return '\n'.join(L)


def _cv_lines(P, M, F):
    """The code of the Crossvalidation line: the model of the same settings grown on the other folds of the
    K-fold Validation column predicting each fold (after the report's code, which has the helpers)."""
    cat = P.kind == 'categorical'
    p, st = F.params, M.st
    L = ['', f'# Crossvalidation by the {P.k} folds of {P.spec["validation"]}: each fold predicted by the model of these settings grown on the other folds', '']
    if F.kind == 'forest':
        cls = 'DecisionTreeClassifier' if cat else 'DecisionTreeRegressor'
        rate = st['rate']
        L += ['def model_on(rows):',
              f'    """The forest of {F.grown} trees grown on the rows (as above, no early stopping without validation rows): its prediction of every row."""',
              '    Xt, yt, wt = X[rows], y[rows], ww[rows]']
        if cat:
            L += ['    ycol = np.searchsorted(np.unique(yt), yt)',
                  '    target = (ycol == 1).astype(float) if len(np.unique(yt)) == 2 else np.eye(len(np.unique(yt)))[ycol]']
        else:
            L.append('    target = yt')
        L += [f'    n_boot = len(yt) if {rate!r} >= 1 else max(round(len(yt) * {rate!r}), 1)',
              f'    each = []',
              f'    for s in np.random.RandomState({p["random_state"]}).randint(np.iinfo(np.int32).max, size={F.grown}):',
              '        inbag = np.bincount(np.random.RandomState(s).randint(0, len(yt), n_boot, dtype=np.int32), minlength=len(yt))',
              '        maps = maps_for(Xt, target, wt * inbag, NOMINAL, ORDINAL)',
              f'        tree = {cls}(criterion={p["criterion"]!r}, max_features={p["max_features"]}, max_leaf_nodes={p["max_leaf_nodes"]}, min_samples_leaf={p["min_samples_leaf"]}, random_state=int(s))',
              '        tree.fit(recode(Xt, maps), yt, sample_weight=wt * inbag)',
              '        oob = inbag == 0']
        if cat:
            L += [f'        est = jmp_probs(tree, {LAMBDA})',
                  '        loss = oob_losses(tree, recode(Xt[oob], maps), ycol[oob], wt[oob], est, True)',
                  '        full = np.zeros((tree.tree_.node_count, len(levels))); full[:, tree.classes_] = est']
        else:
            L += ['        full = tree.tree_.value[:, 0, 0]',
                  '        loss = oob_losses(tree, recode(Xt[oob], maps), yt[oob], wt[oob], full, False)']
        L += [f"        kept = kept_splits(loss, {st['minSplits']})" if st['stop'] == 'oob' else '        kept = len(loss) - 1',
              '        each.append(full[stands_for(parents(tree), kept)[tree.apply(recode(X, maps))]])',
              '    return np.mean(each, axis=0)']
    else:
        L += ['def model_on(rows):',
              f'    """The boosted tree of {F.grown} layers grown on the rows (as above, no early stopping without validation rows): its prediction of every row."""',
              '    Xt, wt = X[rows], ww[rows]']
        if cat:
            L += ['    cl = np.unique(y[rows])', '    yt = np.searchsorted(cl, y[rows])',
                  "    kind = 'binomial' if len(cl) == 2 else 'multinomial'"]
        else:
            L += ['    yt, cl, kind = y[rows], None, "squared"']
        L += ['    init = boost_start(yt, wt, kind, len(cl) if cl is not None else 1)',
              f'    rs = np.random.RandomState({p["random_state"]})',
              '    raw = np.tile(init, (len(yt), 1))',
              '    out = np.tile(init, (len(y), 1))',
              f'    for _ in range({F.grown}):',
              f'        for k, (tree, maps) in enumerate(boost_layer(Xt, yt, wt, raw, kind, {p["learning_rate"]!r}, rs, {p["subsample"]!r}, tree_args, NOMINAL, ORDINAL)):',
              f'            out[:, k] += {p["learning_rate"]!r} * tree.tree_.value[:, 0, 0].take(tree.apply(recode(X, maps)), axis=0)',
              f'    return boost_value(out, kind, cl, {len(P.levels) if cat else 0})']
    L += ['', '',
          'cvp = np.zeros_like(fitted)',
          f'for q in range({P.k}):',
          '    cvp[folds == q] = model_on(folds != q)[folds == q]',
          'print("measures", "Crossvalidation", *[float(v) for v in stats(cvp, folds >= 0)])']
    return L


# ---------------------------------------------------------------------------
# the graphs as matplotlib code (predictive.graph_codes has the scheme): the
# head is the model's code (_code with graph=True), the tails Cumulative
# Validation and the column contributions; predictive's the ROC and lift
# curves and actual by predicted
# ---------------------------------------------------------------------------

SET_COLORS = {'Training': predictive.BASE, 'Validation': '#c0620f', 'Test': '#2e7d3a', 'Out of Bag': '#6c5b7b'}   # smui-p-ensemble.js, light theme


def _cumulative_tail(P, F, stat):
    """Cumulative Validation: the statistic shown of each set after 1, 2, ... trees or layers (the model
    of the first k), and for a forest of the training rows out of bag; the number kept marked."""
    keys = list(STAT_KEYS[P.kind])
    stat = stat if stat in keys else keys[0]
    forest = F.kind == 'forest'
    what = 'Trees' if forest else 'Layers'
    L = [f'stat = {keys.index(stat)}   # the statistic shown (Statistic in the red triangle): {STAT_LABELS[stat]}, of what stats() gives',
         'curves = {name: [stats(c, sets == k)[stat] for c in cum] for k, name in enumerate(SETS) if (sets == k).any()}   # the model of the first k, for each k']
    if forest:
        L += ['# out of bag: each training row predicted by those of the first k trees that did not see it',
              'tr_idx = np.flatnonzero(train)',
              'oob_sum, oob_cnt = np.zeros((len(tr_idx),) + each[0].shape[1:]), np.zeros(len(tr_idx))',
              'curves["Out of Bag"] = []',
              'for j in range(len(forest)):',
              '    oob_sum[oobs[j]] += each[j][tr_idx][oobs[j]]',
              '    oob_cnt[oobs[j]] += 1',
              '    ok = oob_cnt > 0',
              '    m = np.zeros(len(y), dtype=bool)',
              '    m[tr_idx[ok]] = True',
              '    f = np.zeros_like(each[0])',
              '    f[tr_idx[ok]] = oob_sum[ok] / (oob_cnt[ok][:, None] if f.ndim == 2 else oob_cnt[ok])',
              '    curves["Out of Bag"].append(stats(f, m)[stat])']
    L += [f'colors = {json.dumps({k: v for k, v in SET_COLORS.items() if forest or k != "Out of Bag"})}',
          'x = np.arange(1, len(cum) + 1)',
          predictive.figure(540, 310),
          'for name, v in curves.items():',
          '    ax.plot(x, v, color=colors[name], linewidth=2.2 if name == "Validation" else 1.5, linestyle=":" if name == "Out of Bag" else "-",',
          '            marker="o" if len(x) == 1 else "None", label=name)',
          'on = "Validation" if "Validation" in curves else "Out of Bag" if "Out of Bag" in curves else next(iter(curves))',
          f'ax.plot([KEPT], [curves[on][KEPT - 1]], linestyle="none", marker="D", markersize=7, color=colors[on], markeredgecolor="#fcf7f2")   # the number kept',
          f'ax.axvline(KEPT, color="{predictive.MUTED}", linewidth=1.2, linestyle="--")',
          'ax.set_xlim(0.5, len(cum) + 0.5)',
          f'ax.set_xlabel("Number of {what}")', f'ax.set_ylabel("{STAT_LABELS[stat]}")',
          f'ax.set_title({json.dumps("Cumulative Validation of " + ("Decision Forest" if forest else "Boosted Tree"))})',
          'fig.legend(loc="outside upper left", ncols=4, frameon=False, fontsize=8)',
          'plt.show()']
    return '\n'.join(L)


def _contrib_lines(P, F):
    """contrib: the SS or G^2 of the splits on each X column, over the kept trees (as cut back) or every
    layer's trees, from the model the head fits (_contributions)."""
    cat = P.kind == 'categorical'
    L = [f'groups = {json.dumps({c: [int(j) for j in P.groups[c]] for c in P.x})}   # the columns of X of each X column',
         'column_of = {j: c for c, js in groups.items() for j in js}',
         'contrib = {c: 0.0 for c in groups}',
         '',
         '',
         'def node_loss(t, cat):',
         '    """Each node\'s SS (a continuous response) or G^2 (a categorical one: -2 n log(n / N) of its level counts)."""',
         '    N = t.weighted_n_node_samples',
         '    if not cat:',
         '        return t.impurity * N',
         '    n = t.value[:, 0, :] * N[:, None]',
         '    with np.errstate(divide="ignore", invalid="ignore"):',
         '        g = np.where(n > 0, n * np.log(n / N[:, None]), 0.0)',
         '    return -2.0 * g.sum(axis=1)',
         '', '']
    if F.kind == 'forest':
        L += ['for (tree, maps, est, rep), k in zip(forest[:KEPT], kept_of[:KEPT]):   # the kept trees, each with the splits it keeps',
              '    t, parent = tree.tree_, parents(tree)',
              f'    loss = node_loss(t, {cat})',
              '    for s in range(1, k + 1):   # the s-th split made nodes 2s - 1 and 2s',
              '        node = parent[2 * s - 1]',
              '        contrib[column_of[int(t.feature[node])]] += float(loss[node] - loss[2 * s - 1] - loss[2 * s])']
    else:
        L += ['for layer in layers[:KEPT]:   # every kept layer\'s trees (a tree per level of a response of three or more levels)',
              '    for tree, maps in layer:',
              '        t = tree.tree_',
              '        loss = node_loss(t, False)   # the SS of the residuals the tree fits',
              '        for node in np.flatnonzero(t.children_left >= 0):',
              '            contrib[column_of[int(t.feature[node])]] += float(loss[node] - loss[t.children_left[node]] - loss[t.children_right[node]])']
    return L


# ---------------------------------------------------------------------------
# the rest of the report: Save Columns, the profiler, the trees, the
# permutation importance
# ---------------------------------------------------------------------------

def _fit_of(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings, shown):
    M = _model_args(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings)
    return M, M.fits[_shown(M, shown)]


@api('ensemble.save', packages=SK)
def save(table, y, x, kind='forest', rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
         missing='informative', settings=None, shown=None):
    """Save Predicteds (and Residuals): every row whose factors the model can take."""
    M, F = _fit_of(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings, shown)
    return predictive.saved(M.P, F.predict, F.proba)


@api('ensemble.score', packages=SK)
def score(table, keep=None, source=None, target_rows=None, y=None, x=None, kind='forest', rows=None, weight=None, freq=None,
          validation=None, portion=0.0, seed=None, missing='informative', settings=None, shown=None):
    """Score Rows: the report's forest or boosted tree (kept under keep when it fitted) on rows of a table (table: the
    one to score, another open table or the report's own with rows added since; target_rows: those rows, None for
    all), found by the names of the X columns. Its formula would run to thousands of nested conditions, so the model
    scores the rows itself. Without the kept model (the engine started again) it is fitted again from the source
    table as it is now, and the note says so."""
    K_ = predictive.kept(keep)
    note = None
    if K_ is None or K_.get('kind') != 'ensemble' or K_.get('ensemble') != kind:
        M, F = _fit_of(source or table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings, shown)
        note = 'The model was fitted again (the engine had not kept it): on the report\'s table as it is now.'
    else:
        M, F = K_['M'], K_['F']
    P = M.P
    X, rws = predictive.score_frame(P, table, target_rows)
    if P.kind == 'categorical':
        pr = F.proba(X) if len(rws) else np.zeros((0, len(P.levels)))
        out = {'rows': [int(r) for r in rws], 'prob': pr.tolist(), 'levels': list(P.labels),
               'most_likely': [P.labels[int(j)] for j in np.argmax(pr, axis=1)], 'names': [f'Prob[{lab}]' for lab in P.labels],
               'most_name': f'Most Likely {P.y}', 'ordinal': data.meta(P.table, P.y).get('modelingType') == 'ordinal'}
    else:
        out = {'rows': [int(r) for r in rws], 'values': (F.predict(X) if len(rws) else np.zeros(0)).tolist(), 'name': f'Predicted {P.y}'}
    out['note'] = note
    return out


def _build(table, rows=None, y=None, x=(), kind='forest', weight=None, freq=None, validation=None, portion=0.0, seed=None,
           missing='informative', settings=None, shown=None, **_):
    M, F = _fit_of(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings, shown)
    return predictive.predictor(M.P, None, predict=F.predict, proba=F.proba)


profile.expose('ensemble', _build, packages=SK)


def _condition(P, j, left, threshold, ranks=None, missing_left=None):
    """A split in words, as JMP words them: X's column j at or below the
    threshold (left) or above it; a categorical column's levels on that
    side, in their order, as g(a, c) (ranks: a nominal column's ranks in the
    tree, None for an ordinal one), with Missing where the tree sends
    missing values when the column has them (and a level the tree's rows
    lacked, which goes there too); a Missing column's 0 or 1."""
    col = next(c for c in P.x if j in P.groups[c])
    e = next(e for e in P.enc if e['name'] == col)
    if e['type'] == 'continuous':
        if P.features[j] == col:
            return f'{col} {"<=" if left else ">"} {threshold:.6g}'
        return f'{col} {"not missing" if left else "missing"}'
    u = len(e['levels'])
    pos = np.arange(u, dtype=float) if ranks is None else np.asarray(ranks, dtype=float)
    side = [predictive.level_label(e['levels'][i]) for i in range(u) if np.isfinite(pos[i]) and (pos[i] <= threshold) == left]
    if missing_left is not None and bool(missing_left) == left:
        side += [predictive.level_label(e['levels'][i]) for i in range(u) if not np.isfinite(pos[i])]
        if e.get('indicator'):
            side.append('Missing')
    return f'{col}({", ".join(side)})'


@api('ensemble.tree', packages=SK)
def tree_view(table, y, x, kind='forest', rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
              missing='informative', settings=None, shown=None, index=1, detail='estimates', most=400):
    """Show Trees: one tree of the forest (as it was cut back) or one layer
    of the boosted tree, as nested lines."""
    M, F = _fit_of(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings, shown)
    P = M.P
    count = F.kept
    i = int(max(1, min(count, int(index or 1))))
    lines = []
    if F.kind == 'forest':
        T = F.trees[i - 1]
        tree, maps, limit, est = T['tree'], T['maps'], 2 * T['kept'], T['est']
        cls = F.classes
    else:
        tree, maps = F.layers[i - 1][0]
        limit, est, cls = None, None, None
    t = tree.tree_
    lr = F.params.get('learning_rate', 1.0)
    ranks = dict(maps)
    go_left = t.missing_go_to_left

    def info(node):
        n = float(t.weighted_n_node_samples[node])
        if detail != 'estimates':
            return {}
        if F.kind == 'forest' and P.kind == 'categorical':
            return {'count': n, 'probs': [[P.labels[int(c)], float(est[node, k])] for k, c in enumerate(cls)]}
        if F.kind == 'forest':
            return {'count': n, 'estimate': float(est[node])}
        return {'count': n, 'estimate': float(lr * t.value[node, 0, 0])}

    def walk(node, depth, text):
        if len(lines) >= most:
            return
        leaf = t.children_left[node] < 0 or (limit is not None and t.children_left[node] > limit)
        lines.append({'depth': depth, 'text': text, 'leaf': bool(leaf), **info(node)})
        if leaf:
            return
        f, thr = int(t.feature[node]), float(t.threshold[node])
        split = P.features[f] if detail == 'names' else None
        rk, ml = ranks.get(f), bool(go_left[node])
        walk(t.children_left[node], depth + 1, split or _condition(P, f, True, thr, rk, ml))
        walk(t.children_right[node], depth + 1, split or _condition(P, f, False, thr, rk, ml))
    walk(0, 0, 'All Rows')
    out = {'index': i, 'count': count, 'what': 'Tree' if F.kind == 'forest' else 'Layer', 'lines': lines, 'truncated': len(lines) >= most,
           'nodes': int(t.node_count), 'response': P.kind}
    if F.kind == 'boosted' and P.kind == 'categorical' and len(F.classes) > 2:
        out['note'] = f'Layer {i} has a tree for each level; this is the one for {P.labels[int(F.classes[0])]}.'
    elif F.kind == 'boosted' and P.kind == 'categorical':
        out['note'] = f'Estimates are offsets of the log odds of {P.labels[int(F.classes[1])]} (the learning rate times the leaf value).'
    elif F.kind == 'boosted':
        out['note'] = 'Estimates are what the layer adds to the prediction (the learning rate times the leaf mean of the residuals).'
    return out


@api('ensemble.permutation', packages=SK)
def permutation(table, y, x, kind='forest', rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None,
                missing='informative', settings=None, shown=None, repeats=5, table_name='data'):
    """Permutation importance: how much the validation (or training)
    statistic falls when one X column's values are shuffled over the rows,
    the model left as it is; the mean over the repeats."""
    M, F = _fit_of(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings, shown)
    P = M.P
    repeats = int(max(1, min(50, int(repeats or 5))))
    on = 1 if P.has(1) else 0
    m = P.mask(on)
    Xe = P.X[m]
    sub = _Sub(P, m)
    allm = np.ones(int(m.sum()), dtype=bool)
    share = _shares(P) if P.kind == 'categorical' else None
    key = _main_stat(P)
    pred = (lambda X: F.proba(X)) if P.kind == 'categorical' else F.predict
    base = stats_of(sub, pred(Xe), allm, share)[key]
    rng = np.random.default_rng(int(M.seed))
    rows_ = []
    prog = _Progress('permutation', len(P.x) * repeats)
    for c in P.x:
        idx = P.groups[c]
        drops = []
        for _ in range(repeats):
            Xp = Xe.copy()
            Xp[:, idx] = Xe[rng.permutation(len(Xe))][:, idx]
            drops.append(base - stats_of(sub, pred(Xp), allm, share)[key])
            prog.add(1)
        rows_.append({'column': c, 'value': float(np.mean(drops)), 'sd': float(np.std(drops, ddof=1)) if repeats > 1 else None})
    tot = sum(max(r['value'], 0.0) for r in rows_)
    for r in rows_:
        r['portion'] = r['value'] / tot if tot > 0 else None
    rows_.sort(key=lambda r: -r['value'])
    label = f'Decrease in {STAT_LABELS[key]}'
    code = '\n'.join([
        f'# Permutation importance on the {SET_NAMES[on].lower()} rows: the fall in {STAT_LABELS[key]} when one column is shuffled',
        '# (run after the report\'s code above, which builds X, y, sets and the model; predict = the model\'s prediction of X)',
        f'rng = np.random.default_rng({int(M.seed)})',
        f'm = sets == {on}',
        f'groups = {json.dumps({c: [int(j) for j in P.groups[c]] for c in P.x})}   # the columns of X of each X column',
        'base = stats(fitted, m)[0]',
        'for c, idx in groups.items():',
        '    drops = []',
        f'    for _ in range({repeats}):',
        '        Xp = X[m].copy(); Xp[:, idx] = X[m][rng.permutation(int(m.sum()))][:, idx]',
        '        Xall = X.copy(); Xall[m] = Xp',
        '        drops.append(base - stats(predict(Xall), m)[0])',
        '    print("permutation", c, np.mean(drops))',
    ])
    # the bars' code, after the head of the model's graphs (ensemble.fit's plots.head_code)
    plot = [f'# Permutation Importance: the fall in {STAT_LABELS[key]} of the {SET_NAMES[on].lower()} rows when one X column\'s values are shuffled over them',
            f'groups = {json.dumps({c: [int(j) for j in P.groups[c]] for c in P.x})}   # the columns of X of each X column (a categorical one\'s move together)',
            f'rng = np.random.default_rng({int(M.seed)})   # the report\'s seed',
            f'm = sets == {on}',
            'base = stats(fitted, m)[0]',
            'contrib = {}',
            'for c, idx in groups.items():',
            '    drops = []',
            f'    for _ in range({repeats}):   # the shuffles',
            '        Xp = X[m].copy()',
            '        Xp[:, idx] = X[m][rng.permutation(int(m.sum()))][:, idx]',
            '        Xall = X.copy()',
            '        Xall[m] = Xp',
            '        drops.append(base - stats(predict(Xall), m)[0])',
            '    contrib[c] = float(np.mean(drops))']
    return {'contributions': {'rows': rows_, 'label': label, 'plot_code': '\n'.join(plot + predictive.contribution_lines(len(P.x), 'Permutation Importance'))},
            'set': SET_NAMES[on], 'repeats': repeats, 'base': base, 'code': code}
