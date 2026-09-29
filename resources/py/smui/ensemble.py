"""Analyze > Predictive Modeling > Bootstrap Forest and Boosted Tree.

JMP Pro's two tree ensembles, fitted by scikit-learn:

  Bootstrap Forest   RandomForestRegressor / RandomForestClassifier: each
                     tree on a bootstrap sample of the training rows, a
                     random set of the X columns tried at each split. Each
                     tree is then cut back as JMP's documentation says its
                     trees stop: past Minimum Splits per Tree a split stays
                     only while it lowers the tree's out-of-bag loss, and
                     the first that does not is taken back. A categorical
                     response's probabilities are JMP's: a node's counts
                     plus a prior worth one row, never 0. The forest
                     averages its trees.
  Boosted Tree       GradientBoostingRegressor / GradientBoostingClassifier:
                     small trees (layers), each fitted to the residuals of
                     the layers before it and scaled by the learning rate.

With validation rows, Early Stopping grows the trees or layers one at a
time and keeps the number with the best validation statistic (RSquare, or
Entropy RSquare for a categorical response). Multiple Fits fits several
forests (over the number of terms) or boosted trees (over the splits and
the learning rate) and reports the best by the same statistic.

The data, sets and measures are predictive.py's. The fitted models are
cached (predictive.cached) for the profiler, Save Columns, the tree views
and the permutation importance. Everything random takes the report's seed.
The helper functions near the top are written out into the Python code
under the report as they are here, so that the code gives the same trees.
"""
import copy
import inspect
import json
import math

import numpy as np

from . import predictive, profile
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


HELPERS = (parents, jmp_probs, oob_losses, kept_splits, stands_for)


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
        self.model = None
        self.grown = 0
        self.kept = 0
        self.stopped = False
        self.curves = {}            # set -> stat -> [value after 1, 2, ... trees or layers]
        self.trees = []             # the forest's trees (cut back), each a dict
        self.fitted = None          # the prediction of every row of P
        self.oob = None             # the forest's out-of-bag prediction of the training rows
        self.oob_rows = None
        self.selection = None       # the statistics Model Validation-Set Summaries shows
        self.notes = []

    # ---- predictions of new rows
    def predict(self, X):
        if self.kind == 'forest':
            s = None
            for T in self.trees[:self.kept]:
                v = T['est'][T['rep'][T['tree'].apply(X)]]
                s = v if s is None else s + v
            return s / self.kept
        return self.model.predict(X)

    def proba(self, X, P=None):
        if self.kind == 'forest':
            s = None
            for T in self.trees[:self.kept]:
                v = T['est'][T['rep'][T['tree'].apply(X)]]
                s = v if s is None else s + v
            out = np.zeros((X.shape[0], self.n_levels))
            out[:, self.classes] = s / self.kept
            return out
        p = np.asarray(self.model.predict_proba(X), dtype=float)
        out = np.zeros((p.shape[0], self.n_levels))
        out[:, self.classes] = p
        return out


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


def grow_forest(P, st, terms, seed, prog):
    """A Bootstrap Forest: scikit-learn's forest grown ten trees at a time
    (warm_start: the trees do not depend on how many are grown), each tree
    cut back by JMP's rule, and with validation rows and Early Stopping on,
    stopped when the last tenth of the trees asked for (at least 5) has not
    improved the validation statistic; the best number is kept."""
    from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
    cat = P.kind == 'categorical'
    tr = P.train()
    tr_idx = np.flatnonzero(tr)
    Xt, yt = P.X[tr], P.target[tr]
    wt = None if P.w is None else P.w[tr]
    w1 = np.ones(len(yt)) if wt is None else wt
    if cat and len(np.unique(yt)) < 2:
        raise ValueError(f'{P.y} has one level in the training rows: nothing to classify')
    K = st['trees']
    nf = P.X.shape[1]
    kf = features_for(terms, len(P.x), nf)
    params = dict(criterion='entropy' if cat else 'squared_error', max_features=kf, max_leaf_nodes=st['maxSplits'] + 1,
                  min_samples_leaf=st['minSize'], bootstrap=True, max_samples=None if st['rate'] >= 1 else float(st['rate']),
                  random_state=int(seed), n_jobs=1)
    Cls = RandomForestClassifier if cat else RandomForestRegressor
    model = Cls(warm_start=True, n_estimators=1, **params)
    F = Fit()
    F.kind, F.params = 'forest', dict(params, n_features=kf, terms=terms)
    F.label = f'{terms} terms'
    early = st['early'] and P.has(1)
    patience = max(5, int(math.ceil(K / 10)))
    n = len(P.index)
    masks = _masks(P)
    share = _shares(P) if cat else None
    L = len(P.levels) if cat else 0
    S = np.zeros((n, L)) if cat else np.zeros(n)
    oob_sum = np.zeros((len(yt), L)) if cat else np.zeros(len(yt))
    oob_cnt = np.zeros(len(yt))
    oob_curve = {}
    best_k, best_v, best_S, best_oob = 0, -math.inf, None, None
    grown = 0
    vmask = P.mask(1)
    classes = None
    while grown < K and not F.stopped:
        target = min(K, grown + 10)
        model.set_params(n_estimators=target)
        model.fit(Xt, yt, sample_weight=wt)
        if cat and classes is None:
            classes = np.asarray(model.classes_, dtype=int)
            ycol = np.searchsorted(classes, yt)             # the row's level among the tree's columns
        view = copy.copy(model)
        view.estimators_ = model.estimators_[grown:target]
        for tree, drawn in zip(view.estimators_, view.estimators_samples_):
            T = _forest_tree(tree, np.bincount(drawn, minlength=len(yt)), P, Xt, yt if not cat else ycol, w1, cat, st, classes, L)
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
    F.model, F.grown, F.kept = model, grown, best_k
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


def _forest_tree(tree, inbag, P, Xt, yt, w1, cat, st, classes, L):
    """One tree of the forest: cut back (JMP's rule, unless the Tree Size
    setting says grow to the maximum), its estimate at every node, its
    prediction of every row, and its Per-Tree Summaries line."""
    t = tree.tree_
    parent = parents(tree)
    est = jmp_probs(tree, LAMBDA) if cat else t.value[:, 0, 0].copy()
    oob = inbag == 0
    loss = oob_losses(tree, Xt[oob], yt[oob], w1[oob], est, cat)
    total = len(loss) - 1
    kept = kept_splits(loss, st['minSplits']) if st['stop'] == 'oob' else total
    before = loss[kept + 1] if kept < total else loss[kept]
    rep = stands_for(parent, kept)
    node_all = rep[tree.apply(P.X)]
    if cat:
        full = np.zeros((t.node_count, L))
        full[:, classes] = est
        pred = full[node_all]
    else:
        pred = est[node_all]
    T = {'tree': tree, 'rep': rep, 'est': est, 'kept': kept, 'total': total, 'all': pred, 'oob': oob, 'parent': parent}
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
    """A Boosted Tree: scikit-learn's gradient boosting, its trees of
    Splits per Tree splits grown best first; with validation rows and
    Early Stopping on, the fit stops at the first layer that does not
    improve the validation statistic (JMP: 'until fitting an additional
    layer no longer improves the validation statistic') and keeps the
    layers before it."""
    from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
    cat = P.kind == 'categorical'
    tr = P.train()
    Xt, yt = P.X[tr], P.target[tr]
    wt = None if P.w is None else P.w[tr]
    if cat and len(np.unique(yt)) < 2:
        raise ValueError(f'{P.y} has one level in the training rows: nothing to classify')
    nf = P.X.shape[1]
    cols = None if st['colRate'] >= 1 else int(max(1, min(nf, round(st['colRate'] * nf))))
    params = dict(loss='log_loss' if cat else 'squared_error', learning_rate=float(learn), n_estimators=st['layers'],
                  subsample=float(st['rowRate']), criterion='squared_error', min_samples_leaf=st['minSize'], max_depth=None,
                  max_leaf_nodes=int(splits) + 1, max_features=cols, random_state=int(seed))
    Cls = GradientBoostingClassifier if cat else GradientBoostingRegressor
    model = Cls(**params)
    F = Fit()
    F.kind, F.params = 'boosted', dict(params, splits=int(splits))
    F.label = f'{splits} splits, learning rate {learn:g}'
    early = st['early'] and P.has(1)
    vmask = P.mask(1)
    Xv = P.X[vmask]
    share = _shares(P) if cat else None
    L = len(P.levels) if cat else 0
    state = {'gen': None, 'best': 0, 'best_v': -math.inf}
    classes = None

    def full_of(p):
        if not cat:
            return p
        out = np.zeros((p.shape[0], L))
        out[:, classes] = p
        return out

    def monitor(i, est, _locals):
        nonlocal classes
        prog.add(1)
        if not early:
            return False
        if state['gen'] is None:
            classes = np.asarray(est.classes_, dtype=int) if cat else None
            state['gen'] = est.staged_predict_proba(Xv) if cat else est.staged_predict(Xv)
        pv = next(state['gen'])
        sub = _Sub(P, vmask)
        v = stats_of(sub, full_of(pv), np.ones(int(vmask.sum()), dtype=bool), share)[_main_stat(P)]
        v = -math.inf if v is None else v
        if v > state['best_v']:
            state['best_v'], state['best'] = v, i + 1
            return False
        return True
    model.fit(Xt, yt, sample_weight=wt, monitor=monitor)
    if cat:
        classes = np.asarray(model.classes_, dtype=int)
    grown = int(model.estimators_.shape[0])
    F.grown = grown
    F.stopped = early and grown < st['layers']
    F.kept = state['best'] if early else grown
    if F.kept < 1:
        F.kept = 1
    # Cumulative Validation: every set after each layer
    masks = _masks(P)
    staged = model.staged_predict_proba(P.X) if cat else model.staged_predict(P.X)
    for k, pk in enumerate(staged, start=1):
        cur = full_of(np.asarray(pk, dtype=float))
        _record(F.curves, P, cur, share, masks)
        if k == F.kept:
            F.fitted = cur.copy()
    prog.finish(st['layers'], grown)
    # keep the layers chosen (a fit with that many layers is the same)
    if F.kept < grown:
        model.estimators_ = model.estimators_[:F.kept]
        model.train_score_ = model.train_score_[:F.kept]
        if hasattr(model, 'oob_improvement_'):
            model.oob_improvement_ = model.oob_improvement_[:F.kept]
        if hasattr(model, 'oob_scores_'):
            model.oob_scores_ = model.oob_scores_[:F.kept]
            model.oob_score_ = model.oob_scores_[-1]
        model.n_estimators_ = F.kept
    F.model = model
    F.classes, F.n_levels = classes, L
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


def _prepared(table, rows, y, x, weight, freq, validation, portion, seed, missing):
    return predictive.prepare(table, y, list(x or []), rows=rows, weight=weight, freq=freq, validation=validation,
                              portion=portion, seed=seed, missing=missing, coding='onehot')


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
        missing='informative', settings=None, shown=None, plot=None, table_name='data'):
    """Everything the Bootstrap Forest or Boosted Tree report shows. plot:
    the page's choices for the graphs' code ({'stat': the statistic
    Cumulative Validation shows})."""
    M = _model_args(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings)
    P, st = M.P, M.st
    i = _shown(M, shown)
    F = M.fits[i]
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
        notes.append(f'The {len(P.x)} X columns are {P.X.shape[1]} columns for scikit-learn (a 0/1 column per level of a categorical one{", and a Missing column where values are missing" if any(e.get("indicator") for e in P.enc) else ""}).')
    out['notes'] += notes
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
        for tree in F.model.estimators_.ravel():
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
    cls = ('RandomForestClassifier' if cat else 'RandomForestRegressor') if forest else ('GradientBoostingClassifier' if cat else 'GradientBoostingRegressor')
    L = P.code(table_name, rows, extra_imports=([predictive.PLT] if graph else []) + [f'from sklearn.ensemble import {cls}'])
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
    fit_w = 'sample_weight=None if w is None else w[train]'
    if forest:
        L += _source(HELPERS)
        L.append('')
        L.append(f'# the forest: {F.grown} trees grown, the first {F.kept} kept' + (f' (early stopping: {F.grown - F.kept} more trees did not improve the validation statistic)' if F.stopped else ''))
        L.append(f'rf = {cls}(n_estimators={F.grown}, criterion={p["criterion"]!r}, max_features={p["max_features"]}, '
                 f'max_leaf_nodes={p["max_leaf_nodes"]}, min_samples_leaf={p["min_samples_leaf"]}, bootstrap=True, '
                 f'max_samples={p["max_samples"]!r}, random_state={p["random_state"]}, n_jobs=1)')
        L.append(f'rf.fit(X[train], y[train], {fit_w})')
        if cat:
            L.append("ycol = np.searchsorted(rf.classes_, y[train])   # each training row's level among the forest's columns")
        L.append('forest = []   # each tree cut back: the tree, its estimate at every node, the node each node falls in')
        if graph:
            L.append('oobs, kept_of = [], []   # each tree\'s out-of-bag rows (of the training rows) and the splits it keeps')
        L.append('for tree, drawn in zip(rf.estimators_, rf.estimators_samples_):')
        L.append('    oob = np.bincount(drawn, minlength=int(train.sum())) == 0   # the training rows the tree did not see')
        if cat:
            L.append(f'    est = jmp_probs(tree, {LAMBDA})')
            L.append('    loss = oob_losses(tree, X[train][oob], ycol[oob], ww[train][oob], est, True)')
            L.append("    full = np.zeros((tree.tree_.node_count, len(levels))); full[:, rf.classes_] = est   # a column for every level")
        else:
            L.append('    full = tree.tree_.value[:, 0, 0]')
            L.append('    loss = oob_losses(tree, X[train][oob], y[train][oob], ww[train][oob], full, False)')
        if st['stop'] == 'oob':
            L.append(f"    kept = kept_splits(loss, {st['minSplits']})   # JMP's rule, Minimum Splits per Tree {st['minSplits']}")
        else:
            L.append('    kept = len(loss) - 1   # every split: the tree as scikit-learn grew it')
        L.append('    forest.append((tree, full, stands_for(parents(tree), kept)))')
        if graph:
            L.append('    oobs.append(oob)')
            L.append('    kept_of.append(kept)')
        L.append("each = [est[rep[tree.apply(X)]] for tree, est, rep in forest]   # every tree's prediction of every row")
        L.append('cum = np.cumsum(each, axis=0) / np.arange(1, len(each) + 1).reshape((-1,) + (1,) * each[0].ndim)   # the forest of the first k trees')
        L.append(f'KEPT = {F.kept}')
        L.append('')
        L.append('def predict(Xnew):')
        L.append('    """The forest of the trees kept: the mean of their predictions."""')
        L.append('    return np.mean([est[rep[tree.apply(Xnew)]] for tree, est, rep in forest[:KEPT]], axis=0)')
    else:
        args = (f'loss={p["loss"]!r}, learning_rate={p["learning_rate"]!r}, max_leaf_nodes={p["max_leaf_nodes"]}, max_depth=None, '
                f'min_samples_leaf={p["min_samples_leaf"]}, subsample={p["subsample"]!r}, max_features={p["max_features"]!r}, '
                f'criterion="squared_error", random_state={p["random_state"]}')
        L.append(f'# the boosted tree: {F.grown} layers fitted, the first {F.kept} kept' + (' (early stopping: the next layer did not improve the validation statistic)' if F.stopped else ''))
        L.append(f'gb = {cls}(n_estimators={F.grown}, {args})')
        L.append(f'gb.fit(X[train], y[train], {fit_w})')
        if cat:
            L.append('')
            L.append('def full(p):')
            L.append('    """The probabilities in a column for every level."""')
            L.append('    out = np.zeros((len(p), len(levels))); out[:, gb.classes_] = p')
            L.append('    return out')
            L.append('cum = [full(q) for q in gb.staged_predict_proba(X)]   # after 1, 2, ... layers')
        else:
            L.append('cum = list(gb.staged_predict(X))   # after 1, 2, ... layers')
        L.append(f'KEPT = {F.kept}')
        if F.kept < F.grown:
            L.append(f'kept = {cls}(n_estimators=KEPT, {args})   # the same model as the first {F.kept} layers of gb')
            L.append(f'kept.fit(X[train], y[train], {fit_w})')
        else:
            L.append('kept = gb')
        L.append('')
        L.append('def predict(Xnew):')
        L.append('    """The boosted tree of the layers kept."""')
        L.append('    return full(kept.predict_proba(Xnew))' if cat else '    return kept.predict(Xnew)')
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
    return '\n'.join(L)


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
          f'ax.set_title({json.dumps("Cumulative Validation of " + ("Bootstrap Forest" if forest else "Boosted Tree"))})',
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
        L += ['for (tree, est, rep), k in zip(forest[:KEPT], kept_of[:KEPT]):   # the kept trees, each with the splits it keeps',
              '    t, parent = tree.tree_, parents(tree)',
              f'    loss = node_loss(t, {cat})',
              '    for s in range(1, k + 1):   # the s-th split made nodes 2s - 1 and 2s',
              '        node = parent[2 * s - 1]',
              '        contrib[column_of[int(t.feature[node])]] += float(loss[node] - loss[2 * s - 1] - loss[2 * s])']
    else:
        L += ['for tree in kept.estimators_.ravel():   # every layer\'s trees (a tree per level of a categorical response)',
              '    t = tree.tree_',
              '    loss = node_loss(t, False)   # the SS of the residuals the tree fits',
              '    for node in np.flatnonzero(t.children_left >= 0):',
              '        contrib[column_of[int(t.feature[node])]] += float(loss[node] - loss[t.children_left[node]] - loss[t.children_right[node]])']
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


def _build(table, rows=None, y=None, x=(), kind='forest', weight=None, freq=None, validation=None, portion=0.0, seed=None,
           missing='informative', settings=None, shown=None, **_):
    M, F = _fit_of(table, rows, y, x, kind, weight, freq, validation, portion, seed, missing, settings, shown)
    return predictive.predictor(M.P, None, predict=F.predict, proba=F.proba)


profile.expose('ensemble', _build, packages=SK)


def _condition(P, j, left, threshold):
    """A split in words: X's column j at or below the threshold (left) or above."""
    name = P.features[j]
    col = None
    for c in P.x:
        if j in P.groups[c]:
            col = c
            break
    e = next(e for e in P.enc if e['name'] == col)
    if e['type'] == 'continuous' and name == col:
        return f'{col} {"<=" if left else ">"} {threshold:.6g}'
    if name.endswith(' Missing') or name == f'{col}[Missing]':
        return f'{col} {"not missing" if left else "missing"}'
    lv = name[len(col) + 1:-1]
    return f'{col} {"≠" if left else "="} {lv}'


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
        tree, limit, est = T['tree'], 2 * T['kept'], T['est']
        cls = F.classes
    else:
        trees = F.model.estimators_[i - 1]
        tree, limit, est, cls = trees[0], None, None, None
    t = tree.tree_
    lr = F.params.get('learning_rate', 1.0)

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
        walk(t.children_left[node], depth + 1, split or _condition(P, f, True, thr))
        walk(t.children_right[node], depth + 1, split or _condition(P, f, False, thr))
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
