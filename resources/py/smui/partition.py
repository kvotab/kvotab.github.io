"""Analyze > Predictive Modeling > Partition: JMP's decision tree.

A tree grown one split at a time, as JMP's Partition platform grows it. A
split is the column and cut with the largest LogWorth, -log10 of the
split's p-value adjusted for the number of ways the column can be cut: the
two-group F test for a continuous response, the likelihood-ratio
chi-square G² for a categorical one. A continuous or ordinal X is cut at a
value; a nominal X splits its levels into two groups (ordered by the
response mean or rate; every grouping for a response of three or more
levels). With Informative Missing a missing value of a continuous X goes
to the side that fits best and a missing level is a level of its own. A
leaf's probabilities are smoothed toward its parent's by JMP's rule, so
they are never 0.

JMP's adjustment of the p-value comes from a Monte Carlo calibration that
JMP has not published. Here the adjustment is a bound: for ordered cuts
the expected number of upcrossings between neighbouring cuts (Lausen,
Sauerbrei and Schumacher 1994; Rice's formula for a chi process), for a
nominal X the smaller of Bonferroni over the groupings and Scheffé's bound
(the best grouping is no better than the test of all its levels), never
more than Bonferroni over the candidates.

The splits the user makes are a list of steps the report keeps (Split,
Prune, Go, the split of one node), replayed from the root every time, so
Redo, By groups and projects give the same tree.

The engine (between the ENGINE markers) uses numpy and scipy only; the
report shows it as the code of the tree. CART, scikit-learn's
DecisionTreeRegressor and DecisionTreeClassifier grown best first, is the
second method (the cart_* functions, which load scikit-learn).
"""
# ==== ENGINE: JMP's Partition, one split at a time (numpy and scipy only) ====
import math

import numpy as np
from scipy import special, stats

LAMBDA = 0.9    # JMP: the weight of the parent's prior in a node's prior (categorical response)
AHEAD = 10      # Go: the splits looked at past the best validation RSquare
BINS = 12       # a nominal X of up to this many levels tries every grouping (response of 3+ levels)
LN10 = math.log(10)


def num_text(v):
    """A cut value as the conditions show it: 12 for 12.0, else the shortest exact form."""
    v = float(v)
    return str(int(v)) if v.is_integer() and abs(v) < 1e15 else repr(v)


def between(lo, hi):
    """The shortest decimal c with lo < c <= hi: a cut between two neighbouring values."""
    if not lo < hi:
        return float(hi)
    for d in range(-15, 18):
        q = 10.0 ** -d
        c = math.floor(lo / q + 1) * q
        if d > 0:
            c = float(f'{c:.{d}f}')
        if lo < c <= hi:
            return float(c)
    return float(hi)


def f_logsf(F, d1, d2):
    """ln P(F(d1, d2) > F); the incomplete beta's leading term where scipy underflows."""
    if not F > 0:
        return 0.0
    if math.isinf(F):
        return -math.inf
    lp = float(stats.f.logsf(F, d1, d2))
    if not math.isfinite(lp):
        x, a, b = d2 / (d2 + d1 * F), d2 / 2, d1 / 2
        lp = a * math.log(x) + b * math.log1p(-x) - math.log(a) - special.betaln(a, b)
    return lp


def chi2_logsf(x, d):
    """ln P(chi2(d) > x); the incomplete gamma's leading term where scipy underflows."""
    if not x > 0:
        return 0.0
    if math.isinf(x):
        return -math.inf
    lp = float(stats.chi2.logsf(x, d))
    if not math.isfinite(lp):
        lp = (d / 2 - 1) * math.log(x / 2) - x / 2 - special.gammaln(d / 2)
    return lp


def chi_of(lp, d):
    """The chi value r with P(chi2(d) > r^2) = exp(lp) (for d = 1 the normal deviate)."""
    if lp > -700:
        return math.sqrt(float(stats.chi2.isf(math.exp(lp), d)))
    x = -2 * lp
    for _ in range(40):
        x = max(1e-12, 2 * ((d / 2 - 1) * math.log(x / 2) - special.gammaln(d / 2) - lp))
    return math.sqrt(x)


def ordered_mult(lp, m, total, d):
    """ln of how much likelier the best of ordered cut points is than one of
    them: 1 plus, for each pair of neighbouring cuts, the expected number of
    upcrossings of the statistic between them relative to its p-value, each
    at most 1. That is the leading term of Lausen, Sauerbrei and
    Schumacher's improved Bonferroni bound (1994) for a one-degree-of-freedom
    statistic, and of Rice's formula for a chi process of d degrees of
    freedom. m: the left weights at the cuts allowed, in order; total: the
    node's weight; lp: ln of the best cut's p-value."""
    m = np.asarray(m, dtype=float)
    k = len(m)
    if k < 2:
        return 0.0
    if not math.isfinite(lp):
        return math.log(k)
    t = np.sqrt(np.clip(1 - m[:-1] * (total - m[1:]) / (m[1:] * (total - m[:-1])), 0.0, 1.0))
    r = chi_of(lp, d)
    up = t * math.exp(float(stats.chi.logpdf(r, d)) - 0.5 * math.log(2 * math.pi) - lp)
    return math.log1p(float(np.sum(np.minimum(up, 1.0))))


def _H(A, W):
    """sum n ln n - W ln W over each row of level weights A (W: its sums)."""
    return np.sum(special.xlogy(A, A), axis=-1) - special.xlogy(W, W)


class Col:
    """An X column read from the predictor matrix X: 'continuous' (X[:, j],
    missing where X[:, miss] is 1), or 'ordinal' / 'nominal' (the level
    number in X[:, j], -1 when missing; levels: their names)."""

    def __init__(self, name, kind, j, miss=None, levels=None):
        self.name, self.kind, self.j, self.miss, self.levels = name, kind, j, miss, list(levels or [])

    def __repr__(self):
        import json
        extra = '' if self.kind == 'continuous' and self.miss is None else f', {self.miss!r}' if self.kind == 'continuous' else f', None, {json.dumps(self.levels)}'
        return f'Col({json.dumps(self.name)}, {self.kind!r}, {self.j}{extra})'

    def values(self, X):
        v = np.asarray(X[:, self.j], dtype=float)
        if self.kind == 'continuous':
            return np.where(X[:, self.miss] == 1, np.nan, v) if self.miss is not None else v
        return np.where(np.isfinite(v), v, -1).astype(int)

    def level(self, code):
        code = int(code)
        return 'Missing' if code < 0 else self.levels[code] if code < len(self.levels) else f'level {code}'


class Rule:
    """Where a split sends a row, side 0 or 1. 'cut': x < cut to side 0 (x a
    value, or an ordinal level number); 'set': the levels in `low` to side
    0, those in `high` to 1. `miss` is the side of a missing value; None when
    no training row at the node was missing, and then the larger side
    (`big`) takes it, as it takes a level the node never saw."""

    def __init__(self, kind, cut=None, low=(), high=(), miss=None, big=0):
        self.kind, self.cut, self.miss, self.big = kind, cut, miss, big
        self.low, self.high = sorted(int(v) for v in low), sorted(int(v) for v in high)

    def side(self, v):
        if self.kind == 'cut':
            missing = np.isnan(v) if v.dtype.kind == 'f' else v < 0
            s = np.where(v < self.cut, 0, 1)
        else:
            missing = (v < 0) & (-1 not in self.low) & (-1 not in self.high)
            s = np.where(np.isin(v, self.low), 0, np.where(np.isin(v, self.high), 1, self.big))
        return np.where(missing, self.big if self.miss is None else self.miss, s).astype(int)


class Node:
    """A node: every row that reaches it (rows), its training rows (tr), and
    their count, mean and SS (continuous) or level weights, rates and
    smoothed probabilities (categorical)."""

    def __init__(self, tree, rows, path='', parent=None, label='All Rows'):
        t = tree
        self.tree, self.rows, self.path, self.parent, self.label = t, rows, path, parent, label
        self.tr = rows[t.train[rows]]
        w = t.w[self.tr]
        self.W, self.count = float(w.sum()), float(t.cnt[self.tr].sum())
        if t.L:
            self.n = np.bincount(t.y[self.tr], weights=w, minlength=t.L).astype(float)
            self.rate = self.n / self.W if self.W > 0 else np.full(t.L, 1.0 / t.L)
            # JMP: Prob = (n + prior)/(N + 1); the root's prior is its rates, a
            # child's 0.9 of its parent's prior and 0.1 of its parent's Prob
            self.prior = self.rate.copy() if parent is None else LAMBDA * parent.prior + (1 - LAMBDA) * parent.prob
            self.prob = (self.n + self.prior) / (self.W + 1)
            self.H = float(_H(self.n, self.W))
            self.g2 = -2 * self.H
            self.value = self.prob
        else:
            yv = t.y[self.tr]
            self.mean = float(np.sum(w * yv) / self.W) if self.W > 0 else math.nan
            self.ss = float(np.sum(w * (yv - self.mean) ** 2)) if self.W > 0 else 0.0
            self.sd = math.sqrt(self.ss / (self.count - 1)) if self.count > 1 else math.nan
            self.value = self.mean
        self.children = None
        self.cand = None      # the split made here
        self.order = None     # when it was made
        self._cands = None

    def candidates(self):
        """The best split of every X column here (None where there is none)."""
        if self._cands is None:
            self._cands = [self.tree.search(self, j) for j in range(len(self.tree.cols))]
        return self._cands

    def best(self):
        c = [x for x in self.candidates() if x is not None]
        return max(c, key=lambda x: (x['logworth'], x['stat'])) if c else None


class Tree:
    """A decision tree grown as JMP's Partition grows it.

    cols: the X columns (Col) of the predictor matrix X; y: the response
    (numbers, or level numbers 0..L-1 of L levels); w: case weights; cnt:
    row counts (Freq: the minimum size and the degrees of freedom count
    them); sets: 0 training, 1 validation, 2 test (only training rows choose
    the splits); minsize: the least count on each side of a split;
    informative: Informative Missing; levels: the response's level names.

    The split statistic lives in a few methods (_splittable, _aggregates,
    _crit, _logp and those after them), so that another tree can grow the
    same way with another statistic (the Uplift platform's UpliftTree)."""

    node_class = Node

    def __init__(self, cols, X, y, L, w=None, cnt=None, sets=None, minsize=5, informative=True, levels=None):
        self.cols, self.L = list(cols), int(L)
        self.X = np.asarray(X, dtype=float)
        self.vals = [c.values(self.X) for c in self.cols]
        self.y = np.asarray(y, dtype=int if self.L else float)
        n = len(self.y)
        self.w = np.ones(n) if w is None else np.asarray(w, dtype=float)
        self.cnt = np.ones(n) if cnt is None else np.asarray(cnt, dtype=float)
        self.sets = np.zeros(n, dtype=int) if sets is None else np.asarray(sets, dtype=int)
        self.train = self.sets == 0
        self.minsize = max(1.0, float(minsize))
        self.informative = bool(informative)
        self.levels = list(levels) if levels is not None else [str(j) for j in range(self.L)]
        if self.L:
            wt = self.w[self.train]
            self.share = np.bincount(self.y[self.train], weights=wt, minlength=self.L) / wt.sum()
        self.made = 0
        self.notes = []
        self.go_trace = None
        self.folds = None           # a K-fold Validation column: each row's fold (-1 none); Go then crossvalidates
        self.root = self.node_class(self, np.arange(n))

    # ---- the tree -----------------------------------------------------------
    def nodes(self, top=None):
        """Every node, parents before children, left before right."""
        out, stack = [], [top or self.root]
        while stack:
            nd = stack.pop()
            out.append(nd)
            if nd.children:
                stack.extend(reversed(nd.children))
        return out

    def leaves(self, top=None):
        return [nd for nd in self.nodes(top) if nd.children is None]

    def find(self, path):
        nd = self.root
        for ch in path or '':
            if not nd.children or ch not in 'LR':
                raise ValueError(f'the tree has no node {path}')
            nd = nd.children[0 if ch == 'L' else 1]
        return nd

    def splits(self):
        return sum(1 for nd in self.nodes() if nd.children)

    # ---- the best split of one column at one node ------------------------------
    def search(self, node, j, cut=None):
        """The best split of column j at node (cut: split a continuous column
        there instead), or None when no split leaves minsize rows on each side."""
        if not self._splittable(node):
            return None
        col, v = self.cols[j], self.vals[j][node.tr]
        A, c = self._aggregates(node), self.cnt[node.tr]
        miss = np.isnan(v) if col.kind == 'continuous' else v < 0
        if col.kind == 'nominal':
            return self._nominal(node, j, col, v, A, c)
        return self._ordered(node, j, col, v, A, c, miss, cut)

    # ---- the split statistic: what another tree changes ---------------------------
    def _splittable(self, node):
        """Whether a node can be split at all: rows enough for two sides, and a response that varies."""
        if node.count < 2 * self.minsize or len(node.tr) < 2:
            return False
        return node.g2 > 0 if self.L else node.ss > 0

    def _aggregates(self, node):
        """What each training row of the node adds to a side's statistic: its weight in its level's column
        (categorical), or its weight and weighted deviation from the node's mean (continuous)."""
        w = self.w[node.tr]
        if self.L:
            A = np.zeros((len(w), self.L))
            A[np.arange(len(w)), self.y[node.tr]] = w
            return A
        return np.column_stack([w, w * (self.y[node.tr] - node.mean)])   # centred at the node's mean

    def _tiny(self, node):
        """A split statistic at or below this is no split."""
        return 1e-10 * (node.g2 if self.L else node.ss)

    def _dof(self, node):
        """The degrees of freedom of the split's chi process (the ordered cuts' multiplicity)."""
        return max(1, int(np.sum(node.n > 0)) - 1) if self.L else 1

    def _weight_of(self, AL):
        """The weight of each candidate left side."""
        return AL.sum(axis=1) if self.L else AL[:, 0]

    def _extra(self, node, AL):
        """More about the split chosen, for the report (the uplift tree's Gamma)."""
        return {}

    def _nominal_keys(self, node, B, u, Lp):
        """The orders of a nominal X's levels to cut between neighbours, or None to try every grouping."""
        if self.L and Lp >= 3 and u <= BINS:
            return None
        if not self.L:
            return [node.mean + B[:, 1] / B[:, 0]]
        if Lp <= 2:
            j0 = int(np.flatnonzero(node.n > 0)[0])
            return [B[:, j0] / B.sum(axis=1)]
        return [B[:, q] / B.sum(axis=1) for q in np.flatnonzero(node.n > 0)]   # many levels: in the order of each response level's rate

    def _nominal_bound(self, node, B, cb, stat, u, Lp):
        """ln p of the test of all u levels at once (Scheffe's bound on the best grouping), or nan."""
        if self.L:
            return chi2_logsf(stat, (u - 1) * max(1, Lp - 1))
        ssb = float(np.sum(B[:, 1] ** 2 / B[:, 0]))
        dfw = node.count - u
        mse = (node.ss - ssb) / dfw if dfw > 0 else 0.0
        return f_logsf(stat / ((u - 1) * mse), u - 1, dfw) if mse > node.ss * 1e-12 else math.nan

    def _fill(self, pred, nd):
        """The prediction of the rows of node nd, written into pred."""
        pred[nd.rows] = nd.value

    def _crit(self, node, AL, cL):
        """The split statistic of each candidate left side (aggregates AL,
        counts cL): SS (continuous) or G^2 (categorical); -inf where the
        split is not allowed."""
        T = node.n if self.L else np.array([node.W, 0.0])
        AR, cR = T - AL, node.count - cL
        if self.L:
            WL, WR = AL.sum(axis=1), AR.sum(axis=1)
        else:
            WL, WR = AL[:, 0], AR[:, 0]
        good = (cL >= self.minsize - 1e-9) & (cR >= self.minsize - 1e-9) & (WL > 1e-12) & (WR > 1e-12)
        with np.errstate(divide='ignore', invalid='ignore'):
            if self.L:
                s = 2 * (_H(AL, WL) + _H(np.maximum(AR, 0), WR) - node.H)
            else:
                s = AL[:, 1] ** 2 * node.W / (WL * WR)
        s = np.where(good, np.maximum(s, 0.0), -np.inf)
        return s, good

    def _logp(self, node, stat):
        """ln of the split's p-value: the two-group F test, or G^2 as a chi-square."""
        if self.L:
            return chi2_logsf(stat, max(1, int(np.sum(node.n > 0)) - 1))
        df2 = node.count - 2
        if df2 <= 0:
            return 0.0
        sse = node.ss - stat
        return -math.inf if sse <= node.ss * 1e-12 else f_logsf(stat / (sse / df2), 1, df2)

    def _finish(self, node, j, rule, stat, lp, lnM, labels, v0, v1, cL, cR, extra=None):
        lw = max(0.0, -(lp + lnM) / LN10) if math.isfinite(lp) else math.inf
        rule.big = 0 if cL >= cR else 1
        out = {'j': j, 'stat': float(stat), 'lp': float(lp), 'lnM': float(lnM), 'logworth': float(lw), 'rule': rule,
               'labels': labels, 'first': 0 if v0 >= v1 else 1, 'counts': (float(cL), float(cR))}
        out.update(extra or {})
        return out

    def _side_values(self, node, AL):
        """The mean (or the first level's rate) of each side, which orders the children."""
        T = node.n if self.L else np.array([node.W, 0.0])
        AR = T - AL
        if self.L:
            return AL[0] / AL.sum(), AR[0] / AR.sum()
        return node.mean + AL[1] / AL[0], node.mean + AR[1] / AR[0]

    def _ordered(self, node, j, col, v, A, c, miss, cut):
        ok = ~miss
        vals, inv = np.unique(v[ok], return_inverse=True)
        u = len(vals)
        K = A.shape[1]
        B = np.zeros((u, K))
        np.add.at(B, inv, A[ok])
        cb = np.bincount(inv, weights=c[ok], minlength=u)
        Am, cm = A[miss].sum(axis=0), float(c[miss].sum())
        has = bool(miss.any())
        CL = np.vstack([np.zeros(K), np.cumsum(B, axis=0)])     # left: the first k values, k = 0..u
        cl = np.r_[0.0, np.cumsum(cb)]
        ks = np.arange(u + 1)
        if cut is not None:
            ks = np.array([int(np.searchsorted(vals, float(cut), side='left'))])
        fams = [(CL[ks] + Am, cl[ks] + cm, 0), (CL[ks], cl[ks], 1)] if has else [(CL[ks], cl[ks], None)]
        best, allowed = None, 0
        for f, (AL, cL, ms) in enumerate(fams):
            s, good = self._crit(node, AL, cL)
            allowed += int(good.sum())
            if good.any():
                i = int(np.argmax(s))
                if best is None or s[i] > best[0]:
                    best = (float(s[i]), f, i, self._weight_of(AL[good, :]))
        if best is None or best[0] <= self._tiny(node):
            return None
        stat, f, i, mw = best
        AL, cL, ms = fams[f]
        k = int(ks[i])
        lp = self._logp(node, stat)
        lnM = 0.0 if cut is not None else ordered_mult(lp, mw, node.W, self._dof(node))
        if has:
            lnM = min(lnM + math.log(2), math.log(max(1, allowed)))
        if col.kind == 'continuous':
            # a cut between the neighbouring values (the smallest value when only missing rows are below it)
            cv = float(cut) if cut is not None else math.inf if k == u else float(vals[0]) if k == 0 else between(float(vals[k - 1]), float(vals[k]))
            if math.isinf(cv):
                labels = [f'{col.name} not Missing', f'{col.name} Missing']
            else:
                labels = [f'{col.name}<{num_text(cv)}', f'{col.name}>={num_text(cv)}']
                if ms is not None:
                    labels[ms] += ' or Missing'
        else:
            cv = int(vals[k]) if k < u else int(vals[-1]) + 1
            sides = [[col.level(q) for q in vals[:k]], [col.level(q) for q in vals[k:]]]
            if ms is not None:
                sides[ms].append('Missing')
            labels = [f'{col.name}({", ".join(s)})' for s in sides]
        rule = Rule('cut', cut=cv, miss=ms)
        v0, v1 = self._side_values(node, AL[i])
        return self._finish(node, j, rule, stat, lp, lnM, labels, v0, v1, cL[i], node.count - cL[i], self._extra(node, AL[i]))

    def _nominal(self, node, j, col, v, A, c):
        codes, inv = np.unique(v, return_inverse=True)
        u = len(codes)
        if u < 2:
            return None
        K = A.shape[1]
        B = np.zeros((u, K))
        np.add.at(B, inv, A)
        cb = np.bincount(inv, weights=c, minlength=u)
        Lp = int(np.sum(node.n > 0)) if self.L else 0
        keys = self._nominal_keys(node, B, u, Lp)
        if keys is None:
            # every grouping, the first level on side 0: 2^(u-1) - 1 of them
            g = np.arange(1, 2 ** (u - 1))
            high = (g[:, None] >> np.arange(u - 1)[None, :]) & 1
            memb = np.column_stack([np.ones(len(g)), 1 - high])
        else:
            rows = []
            for key in keys:
                order = np.argsort(key, kind='mergesort')
                for k in range(1, u):
                    m = np.zeros(u)
                    m[order[:k]] = 1
                    rows.append(m)
            memb = np.array(rows)
        AL, cL = memb @ B, memb @ cb
        s, good = self._crit(node, AL, cL)
        if not good.any() or s.max() <= self._tiny(node):
            return None
        i = int(np.argmax(s))
        stat = float(s[i])
        lp = self._logp(node, stat)
        # the multiplicity: Bonferroni over the groupings, or Scheffe's bound
        # (the best grouping is no better than the test of all u levels)
        lnG = (u - 1) * math.log(2) + math.log1p(-2.0 ** -(u - 1))
        lpS = self._nominal_bound(node, B, cb, stat, u, Lp)
        lnM = lnG if not (math.isfinite(lpS) and math.isfinite(lp)) else max(0.0, min(lnG, lpS - lp))
        low, high = codes[memb[i] == 1], codes[memb[i] == 0]
        labels = [f'{col.name}({", ".join(col.level(x) for x in sorted(side, key=lambda q: (q < 0, q)))})' for side in (low, high)]
        rule = Rule('set', low=low, high=high)
        v0, v1 = self._side_values(node, AL[i])
        return self._finish(node, j, rule, stat, lp, lnM, labels, v0, v1, cL[i], node.count - cL[i], self._extra(node, AL[i]))

    # ---- growing and pruning -------------------------------------------------------
    def split(self, node, cand):
        """Split node by a candidate: its children, the side with the larger
        mean (or rate of the first level) first."""
        s = cand['rule'].side(self.vals[cand['j']][node.rows])
        first = cand['first']
        node.children = [self.node_class(self, node.rows[s == side], node.path + 'LR'[pos], node, cand['labels'][side])
                         for pos, side in enumerate((first, 1 - first))]
        node.cand, node.order = cand, self.made
        self.made += 1
        return node

    def split_best(self, top=None):
        """Split the leaf (at or below top) whose best split has the largest LogWorth."""
        best = None
        for leaf in self.leaves(top):
            c = leaf.best()
            if c is not None and (best is None or (c['logworth'], c['stat']) > (best[1]['logworth'], best[1]['stat'])):
                best = (leaf, c)
        return None if best is None else self.split(*best)

    def prune_below(self, node):
        node.children, node.cand, node.order = None, None, None
        return node

    def prune_worst(self, top=None):
        """Take back the split (at or below top) with two leaves and the smallest LogWorth."""
        last = [nd for nd in self.nodes(top) if nd.children and all(ch.children is None for ch in nd.children)]
        if not last:
            return None
        return self.prune_below(min(last, key=lambda nd: (nd.cand['logworth'], nd.cand['stat'])))

    def go(self, ahead=AHEAD, most=400):
        """Split until the validation RSquare has not improved for `ahead`
        splits, then keep the tree with the best validation RSquare (with the
        folds of a K-fold Validation column, go_folds)."""
        valid = self.sets == 1
        if not valid.any() and self.folds is not None:
            return self.go_folds(ahead, most)
        if not valid.any():
            raise ValueError('Go needs validation rows: a Validation column or a validation portion')
        pred = self.fitted()
        start = self.splits()
        best = self.rsquare(pred, valid)
        trace = [dict(self.rsquares(pred), splits=start)]
        made, k_best = [], 0
        while len(made) - k_best < ahead and len(made) < most:
            nd = self.split_best()
            if nd is None:
                break
            for ch in nd.children:
                self._fill(pred, ch)
            made.append(nd)
            r = self.rsquare(pred, valid)
            trace.append(dict(self.rsquares(pred), splits=start + len(made)))
            if r > best + 1e-12:
                best, k_best = r, len(made)
        for nd in reversed(made[k_best:]):
            self.prune_below(nd)
        self.go_trace = {'start': start, 'best': start + k_best, 'trace': trace}

    def fold_tree(self, sets):
        """A tree of the same rows with other sets: a fold's, its rows held out."""
        return Tree(self.cols, self.X, self.y, self.L, self.w, self.cnt, sets, self.minsize, self.informative, self.levels)

    def go_folds(self, ahead=AHEAD, most=400):
        """Go by the folds of a K-fold Validation column (self.folds): beside
        this tree a tree per fold, grown on the other folds split for split
        (each its own best split, from the root to this tree's size); the
        crossvalidated RSquare of a size is that of every row predicted by the
        tree that did not see its fold. Splits until it has not improved for
        `ahead` splits, then keeps the size with the best."""
        fold = np.asarray(self.folds, dtype=int)
        k = int(fold.max()) + 1
        held = [fold == f for f in range(k)]
        rows = fold >= 0
        start = self.splits()
        trees = []
        for f in range(k):
            ft = self.fold_tree(np.where(held[f], 1, np.where(rows, 0, 2)))
            for _ in range(start):
                if ft.split_best() is None:
                    break
            trees.append(ft)

        def crossvalidated():
            out = np.zeros((len(self.y), self.L)) if self.L else np.zeros(len(self.y))
            for f, ft in enumerate(trees):
                out[held[f]] = ft.fitted()[held[f]]
            return self.rsquare(out, rows)
        pred = self.fitted()
        best = crossvalidated()
        trace = [dict(self.rsquares(pred), splits=start, cv=best)]
        made, k_best = [], 0
        while len(made) - k_best < ahead and len(made) < most:
            nd = self.split_best()
            if nd is None:
                break
            for ch in nd.children:
                self._fill(pred, ch)
            for ft in trees:
                ft.split_best()
            made.append(nd)
            r = crossvalidated()
            trace.append(dict(self.rsquares(pred), splits=start + len(made), cv=r))
            if r > best + 1e-12:
                best, k_best = r, len(made)
        for nd in reversed(made[k_best:]):
            self.prune_below(nd)
        self.go_trace = {'start': start, 'best': start + k_best, 'trace': trace, 'folds': k}

    def step(self, st):
        """One of the report's steps: split, here, specific, prune, below, go."""
        op = st.get('op')
        node = self.find(st.get('node')) if st.get('node') else self.root
        if op == 'split':
            done = 0
            for _ in range(max(1, int(st.get('n') or 1))):
                if self.split_best(node) is None:
                    break
                done += 1
            if not done:
                raise ValueError(f'no leaf can be split with at least {num_text(self.minsize)} rows on each side')
        elif op in ('here', 'specific'):
            if node.children:
                raise ValueError(f'{node.label} is split already')
            if op == 'here':
                c = node.best()
            else:
                names = [col.name for col in self.cols]
                if st.get('col') not in names:
                    raise ValueError(f'{st.get("col")} is not an X column of the tree')
                c = self.search(node, names.index(st['col']), cut=st.get('cut'))
            if c is None:
                raise ValueError(f'{node.label} has no split with at least {num_text(self.minsize)} rows on each side')
            self.split(node, c)
        elif op == 'prune':
            if self.prune_worst(node) is None:
                raise ValueError('there is no split to prune')
        elif op == 'below':
            if not node.children:
                raise ValueError(f'{node.label} has no split below it')
            self.prune_below(node)
        elif op == 'go':
            self.go()
        else:
            raise ValueError(f'unknown step {op!r}')

    def run(self, steps):
        for i, st in enumerate(steps or []):
            try:
                self.step(st)
            except ValueError as e:
                self.notes.append(f'Step {i + 1} ({st.get("op")}) was not done: {e}.')
        return self

    # ---- predictions and how good they are ---------------------------------------------
    def fitted(self):
        """The prediction of every row: its leaf's mean, or its leaf's Prob."""
        out = np.zeros((len(self.y), self.L)) if self.L else np.zeros(len(self.y))
        for leaf in self.leaves():
            self._fill(out, leaf)
        return out

    def rsquare(self, pred, m):
        """RSquare of the rows m: 1 - SSE/SST about their own mean, or the
        entropy RSquare 1 - LL/LL0, LL0 from the training shares of the levels."""
        if not m.any():
            return math.nan
        w = self.w[m]
        if self.L:
            y = self.y[m]
            ll = np.sum(w * np.log(np.clip(pred[m][np.arange(len(y)), y], 1e-15, 1)))
            ll0 = np.sum(w * np.log(np.clip(self.share[y], 1e-15, 1)))
            return float(1 - ll / ll0) if ll0 < 0 else math.nan
        y = self.y[m]
        sse = np.sum(w * (y - pred[m]) ** 2)
        sst = np.sum(w * (y - np.sum(w * y) / w.sum()) ** 2)
        return float(1 - sse / sst) if sst > 0 else math.nan

    def rsquares(self, pred):
        return {k: self.rsquare(pred, self.sets == k) for k in (0, 1, 2) if np.any(self.sets == k)}

    def n_params(self, leaves):
        """The parameters of the model a tree of this many leaves is: a mean per leaf and the error variance, or
        each leaf's probabilities of the levels (all but one)."""
        return leaves * (self.L - 1) if self.L else leaves + 1

    def aicc(self, pred, leaves):
        """AICc of the training rows: -2 log L + 2k + 2k(k + 1)/(N - k - 1), k = n_params(leaves), N their
        weight; L the normal likelihood with variance SSE/N (a continuous response, as the Measures of Fit's
        -LogLikelihood), or the product of each row's probability of its level (the tree's Prob)."""
        m = self.train
        w = self.w[m]
        N = float(w.sum())
        if self.L:
            y = self.y[m]
            m2ll = -2 * float(np.sum(w * np.log(np.clip(pred[m][np.arange(len(y)), y], 1e-15, 1))))
        else:
            sse = float(np.sum(w * (self.y[m] - pred[m]) ** 2))
            if not sse > 0:
                return math.nan
            m2ll = N * (math.log(2 * math.pi * sse / N) + 1)
        k = self.n_params(leaves)
        return m2ll + 2 * k + (2 * k * (k + 1) / (N - k - 1) if N - k - 1 > 0 else math.nan)

    def history(self):
        """RSquare of each set after each split, in the order they were made, and the training rows' AICc
        (under 'aicc')."""
        made = sorted((nd for nd in self.nodes() if nd.children), key=lambda nd: nd.order)
        pred = np.zeros((len(self.y), self.L)) if self.L else np.zeros(len(self.y))
        self._fill(pred, self.root)
        out = [dict(self.rsquares(pred), aicc=self.aicc(pred, 1))]
        for i, nd in enumerate(made):
            for ch in nd.children:
                self._fill(pred, ch)
            out.append(dict(self.rsquares(pred), aicc=self.aicc(pred, i + 2)))
        return out

    # ---- new rows --------------------------------------------------------------------------
    def leaf_index(self, X):
        """The leaf of each row of X (a predictor matrix like the tree's), by its place in leaves()."""
        X = np.asarray(X, dtype=float)
        vals = [c.values(X) for c in self.cols]
        at = {id(nd): i for i, nd in enumerate(self.leaves())}
        out = np.zeros(len(X), dtype=int)
        stack = [(self.root, np.arange(len(X)))]
        while stack:
            nd, r = stack.pop()
            if nd.children is None:
                out[r] = at[id(nd)]
                continue
            s = nd.cand['rule'].side(vals[nd.cand['j']][r])
            stack.append((nd.children[0], r[s == nd.cand['first']]))
            stack.append((nd.children[1], r[s != nd.cand['first']]))
        return out

    @property
    def classes_(self):
        return np.arange(self.L)

    def predict(self, X):
        return np.array([nd.value for nd in self.leaves()])[self.leaf_index(X)]

    def predict_proba(self, X):
        return np.array([nd.prob for nd in self.leaves()])[self.leaf_index(X)]

    def boxes(self):
        """Every node as the report's tree draws it, parents before children and left before right: its path
        ('' the root, then L and R down to it), its condition (label), count, and mean and std dev, or its
        level rates, probabilities (Prob) and weights (counts) and G^2; lo and hi, the first and last leaf
        under it (the leaves numbered left to right from 0); and the split made there: the column, its
        LogWorth and statistic (SS or G^2), and the left child's mean less the right child's."""
        at = {id(nd): i for i, nd in enumerate(self.leaves())}
        span = {}

        def walk(nd):
            if nd.children is None:
                span[id(nd)] = (at[id(nd)], at[id(nd)])
            else:
                span[id(nd)] = (walk(nd.children[0])[0], walk(nd.children[1])[1])
            return span[id(nd)]
        walk(self.root)
        out = []
        for nd in self.nodes():
            d = {'path': nd.path, 'label': nd.label, 'count': nd.count, 'leaf': nd.children is None,
                 'lo': span[id(nd)][0], 'hi': span[id(nd)][1], 'split': None}
            if self.L:
                d.update(rates=nd.rate.tolist(), probs=nd.prob.tolist(), counts=nd.n.tolist(), g2=nd.g2)
            else:
                d.update(mean=nd.mean, sd=nd.sd)
            if nd.children:
                c = nd.cand
                d['split'] = {'column': self.cols[c['j']].name, 'logworth': c['logworth'], 'stat': c['stat'],
                              'difference': None if self.L else nd.children[0].mean - nd.children[1].mean}
            out.append(d)
        return out

    def text(self):
        """The tree as lines: each node's condition, count and mean (or Prob), and its split's LogWorth."""
        lines = []
        for nd in self.nodes():
            if self.L:
                what = f'Count {num_text(nd.count)}  G^2 {nd.g2:.6g}  ' + '  '.join(f'Prob[{lv}] {p:.4f}' for lv, p in zip(self.levels, nd.prob))
            else:
                what = f'Count {num_text(nd.count)}  Mean {nd.mean:.6g}  Std Dev {nd.sd:.6g}'
            split = f'  | split by {self.cols[nd.cand["j"]].name}, LogWorth {nd.cand["logworth"]:.4f}' if nd.children else ''
            lines.append(f'{"  " * len(nd.path)}{nd.label}  {what}{split}')
        return '\n'.join(lines)


def kfold(cols, X, y, L, w, cnt, sets, k=5, seed=0, splits=0, minsize=5, informative=True, folds=None):
    """K-fold crossvalidation of a tree of `splits` best splits: the training
    rows in k folds drawn from the seed, each fold predicted by the tree
    grown on the others; folds: each row's fold from a K-fold Validation
    column (-1 none), used instead (k is then its number of folds). Returns
    the out-of-fold predictions, the folds and each fold's RSquare."""
    sets = np.asarray(sets, dtype=int)
    if folds is not None:
        fold = np.asarray(folds, dtype=int)
        k = int(fold.max()) + 1
    else:
        tr = np.flatnonzero(sets == 0)
        fold = np.full(len(sets), -1)
        fold[tr] = np.random.default_rng([int(seed), 2]).permutation(np.arange(len(tr)) % k)
    pred = np.zeros((len(sets), L)) if L else np.zeros(len(sets))
    out = []
    for f in range(k):
        s = np.where(fold == f, 1, np.where(fold >= 0, 0, 2))
        t = Tree(cols, X, y, L, w, cnt, s, minsize, informative)
        made = 0
        while made < splits and t.split_best() is not None:
            made += 1
        fit = t.fitted()
        held = fold == f
        pred[held] = fit[held]
        out.append({'fold': f + 1, 'n': float(t.cnt[held].sum()), 'splits': made, 'rsquare': t.rsquare(fit, held)})
    return pred, fold, out
# ==== END OF ENGINE ====

import inspect  # noqa: E402
import json  # noqa: E402

from . import data, predictive, profile  # noqa: E402
from .registry import api  # noqa: E402
from .util import one_line  # noqa: E402   (a By group's label from the table, kept on one line in the code's comments)

_ENGINE = None


def engine_source():
    """The engine's code, as the report shows it."""
    global _ENGINE
    if _ENGINE is None:
        with open(__file__, encoding='utf-8') as fh:
            text = fh.read()
        a, b = text.index('# ==== ENGINE'), text.index('# ==== END OF ENGINE')
        _ENGINE = text[a:b].rstrip() + '\n'
    return _ENGINE


def _py(v):
    """A Python literal of a step list (JSON's null is None)."""
    if v is None or isinstance(v, bool):
        return repr(v)
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v)
    if isinstance(v, dict):
        return '{' + ', '.join(f'{json.dumps(str(k))}: {_py(x)}' for k, x in v.items()) + '}'
    return '[' + ', '.join(_py(x) for x in v) + ']'


# ---------------------------------------------------------------------------
# the report's tree
# ---------------------------------------------------------------------------

def _spec(y=None, x=(), weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
          minsize=5, ordinal_order=True, steps=None, **_ignored):
    """Everything that decides the tree (the key of the model cache)."""
    return {'y': y, 'x': list(x or []), 'weight': weight, 'freq': freq, 'validation': validation, 'portion': float(portion or 0),
            'seed': predictive.seed_of(seed), 'missing': 'drop' if missing in (False, 'drop') else 'informative',
            'minsize': float(5 if minsize in (None, '') else minsize), 'ordinal_order': bool(ordinal_order),
            'steps': [dict(s) for s in (steps or [])]}


def _prepared(table, rows, sp, coding):
    return predictive.prepare(table, sp['y'], sp['x'], rows=rows, weight=sp['weight'], freq=sp['freq'], validation=sp['validation'],
                              portion=sp['portion'], seed=sp['seed'], missing=sp['missing'], coding=coding)


def columns_of(P, ordinal_order=True):
    """The engine's X columns from the prepared data (ordinal coding); a level's name is its value label when
    the column has one (the conditions show it)."""
    cols = []
    for e in P.enc:
        idx = P.groups[e['name']]
        if e['type'] == 'continuous':
            cols.append(Col(e['name'], 'continuous', idx[0], idx[1] if len(idx) > 1 else None))
        else:
            ordinal = ordinal_order and data.meta(P.table, e['name']).get('modelingType') == 'ordinal'
            names = [_shown_level(P.table, e['name'], v) for v in e['levels']]
            cols.append(Col(e['name'], 'ordinal' if ordinal else 'nominal', idx[0], None, names))
    return cols


def _shown_level(table, column, v):
    """A level as the page shows it: its value label, or the value (2.0 as 2)."""
    lab = getattr(data, 'level_label', None)
    return lab(table, column, v, predictive.level_label(v)) if lab else predictive.level_label(v)


def min_count(minsize, P):
    """Minimum Size Split as a count: a value below 1 is a share of the training rows."""
    v = float(minsize)
    if not v > 0:
        raise ValueError('the Minimum Size Split is a positive number')
    return float(max(1, math.ceil(v * P.counts(P.train()).sum()))) if v < 1 else v


def _grown(table, rows, sp):
    """The prepared data and the tree with the report's steps, remembered."""
    def build():
        P = _prepared(table, rows, sp, 'ordinal')
        L = len(P.levels) if P.kind == 'categorical' else 0
        ms = min_count(sp['minsize'], P)
        t = Tree(columns_of(P, sp['ordinal_order']), P.X, P.target, L, P.w, P.freq, P.sets, ms, P.missing == 'informative', P.labels)
        t.folds = fold_index(P)
        t.run(sp['steps'])
        return P, t, ms
    return predictive.cached('partition', table, rows, sp, build)


def _leaf_labels(t):
    """Each leaf's conditions from the root, joined by & (JMP's Leaf Label)."""
    out = []
    for nd in t.leaves():
        parts, p = [], nd
        while p.parent is not None:
            parts.append(p.label)
            p = p.parent
        out.append('&'.join(reversed(parts)) or 'All Rows')
    return out


def _side_of(par, ch):
    """The side (0 or 1) of par's split that its child ch is."""
    first = par.cand['first']
    return first if ch is par.children[0] else 1 - first


def leaf_rules(t):
    """Each leaf's rule: its Leaf Label with the conditions on one column merged, each column once, in the order
    it first comes on the path. A continuous column's cuts become one range (2<=x<5) and keep 'or Missing' when
    every condition on it has it; a categorical column's groups of levels become the levels they share. The rule
    says what the conditions say, nothing more: a condition without 'or Missing' leaves missing values out."""
    out = []
    for nd in t.leaves():
        path, p = [], nd
        while p.parent is not None:
            path.append((p.parent, p))
            p = p.parent
        merged, order = {}, []
        for par, ch in reversed(path):
            c = par.cand
            j, side, rule = c['j'], _side_of(par, ch), c['rule']
            col = t.cols[j]
            if j not in merged:
                order.append(j)
                merged[j] = {'lo': -math.inf, 'hi': math.inf, 'miss': True} if col.kind == 'continuous' else {'levels': None, 'miss': True}
            m = merged[j]
            if col.kind == 'continuous':
                cut = float(rule.cut)
                if math.isinf(cut):          # 'x not Missing' (side 0) against 'x Missing' (side 1)
                    lo, hi = (-math.inf, math.inf) if side == 0 else (math.inf, math.inf)
                else:
                    lo, hi = (-math.inf, cut) if side == 0 else (cut, math.inf)
                m['lo'], m['hi'] = max(m['lo'], lo), min(m['hi'], hi)
                m['miss'] = m['miss'] and rule.miss == side
            else:
                # the levels the label lists (the node's own), Missing as -1
                codes = np.unique(t.vals[j][par.tr])
                if rule.kind == 'cut':
                    listed = {int(q) for q in codes if q >= 0 and (q < rule.cut) == (side == 0)}
                    if rule.miss == side:
                        listed.add(-1)
                else:
                    listed = set(rule.low if side == 0 else rule.high)
                m['levels'] = listed if m['levels'] is None else (m['levels'] & listed)
        parts = []
        for j in order:
            col, m = t.cols[j], merged[j]
            if col.kind == 'continuous':
                lo, hi, miss = m['lo'], m['hi'], m['miss']
                if lo >= hi:
                    parts.append(f'{col.name} Missing')
                    continue
                if math.isinf(lo) and math.isinf(hi):
                    parts.append(f'{col.name} not Missing')
                    continue
                txt = (f'{num_text(lo)}<={col.name}<{num_text(hi)}' if math.isfinite(lo) and math.isfinite(hi)
                       else f'{col.name}>={num_text(lo)}' if math.isfinite(lo) else f'{col.name}<{num_text(hi)}')
                parts.append(txt + (' or Missing' if miss else ''))
            else:
                levels = sorted(m['levels'] or (), key=lambda q: (q < 0, q))
                parts.append(f'{col.name}({", ".join(col.level(q) for q in levels)})')
        out.append('&'.join(parts) or 'All Rows')
    return out


# ---------------------------------------------------------------------------
# Save Prediction Formula: the tree as nested If, in the page's formula language
# ---------------------------------------------------------------------------
# JMP writes the tree as nested conditional clauses. Each split here is one
# If: the condition of the side its missing (or unseen) values go to, that
# side, the other; a numeric level column's missing value makes a comparison
# missing, so there Is Missing comes first. Informative Missing off (rows
# missing a factor are left out, and Save Predicteds gives them nothing): a
# row missing any factor gets a missing prediction.

FORMULA_MAX, DEPTH_MAX = 50000, 150    # smui-formula.js reads formulas of up to 50000 characters and 160 levels


def _level_lit(v):
    """A level as a value in formula text: a number, or text in quotes."""
    from .util import formula_num, formula_str
    return formula_num(v) if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) else formula_str(v)


def _missing_side(rule):
    """The side a missing (or unknown) value of the split's column goes to."""
    if rule.kind == 'set':
        return 0 if -1 in rule.low else 1 if -1 in rule.high else rule.big
    return rule.miss if rule.miss is not None else rule.big


def tree_formula(t, P, leaf_value, informative=True, guard=()):
    """The tree t as nested If: leaf_value(leaf) is each leaf's value as formula text. P: the prepared data (the
    levels of each categorical factor, in the order the tree codes them). guard: more columns a row must have
    (the Uplift's treatment); with informative False every factor is one of them."""
    from .util import formula_num, formula_ref
    levels = {e['name']: list(e['levels']) for e in P.enc if e['type'] != 'continuous'}
    depth = [0]

    def walk(nd, d):
        depth[0] = max(depth[0], d)
        if nd.children is None:
            return leaf_value(nd)
        c = nd.cand
        col, rule = t.cols[c['j']], c['rule']
        ref = formula_ref(col.name)
        sub = {_side_of(nd, ch): walk(ch, d + 1) for ch in nd.children}
        m = _missing_side(rule)
        if col.kind == 'continuous':
            cut = float(rule.cut)
            if math.isinf(cut):
                return f'If(Is Missing({ref}), {sub[1]}, {sub[0]})'
            cond = f'{ref} < {formula_num(cut)}' if m == 0 else f'{ref} >= {formula_num(cut)}'
            if informative:
                cond = f'Is Missing({ref}) | {cond}'
            return f'If({cond}, {sub[m]}, {sub[1 - m]})'
        lv = levels[col.name]
        other = 1 - m
        if rule.kind == 'cut':
            codes = [q for q in range(len(lv)) if (q < rule.cut) == (other == 0)]
        else:
            seen = set(rule.low) | set(rule.high)
            codes = [q for q in range(len(lv)) if q in (rule.low if other == 0 else rule.high) or (q not in seen and rule.big == other)]
        cond = ' | '.join(f'{ref} == {_level_lit(lv[q])}' for q in codes)
        numeric = all(isinstance(v, (int, float, np.integer, np.floating)) for v in lv)
        if informative and numeric:
            cond = f'!Is Missing({ref}) & ({cond})' if len(codes) > 1 else f'!Is Missing({ref}) & {cond}'
        return f'If({cond}, {sub[other]}, {sub[m]})'
    body = walk(t.root, 1)
    need = list(dict.fromkeys(list(guard) + ([] if informative else list(P.x))))
    if need:
        body = f'If({" | ".join(f"Is Missing({formula_ref(c)})" for c in need)}, ., {body})'
    if len(body) > FORMULA_MAX:
        raise ValueError(f'the tree is too large for a formula: {len(body)} characters, at most {FORMULA_MAX}; save the predicted values instead')
    if depth[0] > DEPTH_MAX:
        raise ValueError(f'the tree is too deep for a formula: {depth[0]} levels, at most {DEPTH_MAX}; save the predicted values instead')
    return body


def _node_json(P, t, nd, box):
    """A node of the report: what the tree draws of it (Tree.boxes, which the code under the tree calls too),
    its parent, weight and leaf number, the split's order and children, and every column's best split there."""
    d = dict(box, parent=nd.parent.path if nd.parent is not None else None, w=nd.W, number=box['lo'] + 1 if box['leaf'] else None)
    if not t.L:
        d['ss'] = nd.ss
    if nd.children:
        d['split'] = dict(box['split'], order=nd.order, children=[ch.path for ch in nd.children])
    cands = []
    best = nd.best()
    for j, c in enumerate(nd.candidates()):
        col = t.cols[j]
        if c is None:
            cands.append({'column': col.name, 'stat': None, 'logworth': None, 'split': '', 'other': '', 'best': False})
        else:
            cands.append({'column': col.name, 'stat': c['stat'], 'logworth': c['logworth'], 'split': c['labels'][c['first']],
                          'other': c['labels'][1 - c['first']], 'best': c is best})
    d['cands'] = cands
    return d


def _tree_json(P, t):
    return [_node_json(P, t, nd, box) for nd, box in zip(t.nodes(), t.boxes())]


def _summary(P, splits, fit, aicc=None):
    """The summary line of each set, JMP's: RSquare, RASE (or Entropy RSquare and the Misclassification Rate),
    N, and on the training line the Number of Splits and the AICc."""
    rows = []
    for m in fit['measures']:
        k = predictive.SETS.index(m['set'])
        n = float(P.counts(P.mask(k)).sum())
        if P.kind == 'continuous':
            rows.append({'set': m['set'], 'rsquare': m['rsquare'], 'rase': m['rase'], 'n': n})
        else:
            rows.append({'set': m['set'], 'entropy_rsquare': m['entropy_rsquare'], 'misclassification': m['misclassification'], 'n': n})
    if rows:
        rows[0]['splits'] = splits
        rows[0]['aicc'] = aicc
    return rows


def _history_rows(hist):
    """Tree.history() (or cart_history) as the report's rows: the number of splits, each set's RSquare by name,
    and the AICc."""
    out = []
    for i, h in enumerate(hist):
        row = {'splits': i, **{predictive.SETS[k]: v for k, v in h.items() if isinstance(k, int)}}
        if 'aicc' in h:
            row['aicc'] = h['aicc']
        out.append(row)
    return out


def _contributions(P, t):
    vals = np.zeros(len(P.features))
    splits = {c: 0 for c in P.x}
    for nd in t.nodes():
        if nd.children:
            name = t.cols[nd.cand['j']].name
            vals[P.groups[name][0]] += nd.cand['stat']
            splits[name] += 1
    out = predictive.contributions(P, vals, 'SS' if P.kind == 'continuous' else 'G^2')
    for r in out['rows']:
        r['splits'] = splits[r['column']]
    return out


def _head_code(P, sp, table_name, rows):
    lines = P.code(table_name, rows)
    f = sp['freq']
    lines.append(f'cnt = d[{json.dumps(f)}].to_numpy(float)   # the frequencies: the minimum size and the degrees of freedom count them'
                 if f else 'cnt = None   # every row counts once')
    return '\n'.join(lines)


def _fit_code(P, t, sp, ms, group):
    L = len(P.levels) if P.kind == 'categorical' else 0
    lines = [f'# Partition for {P.y}{f" ({one_line(group)})" if group else ""}: the report\'s steps replayed from the root',
             'columns = [']
    lines += [f'    {c!r},' for c in t.cols]
    lines.append(']')
    if float(sp['minsize']) < 1:
        lines.append(f'# Minimum Size Split {sp["minsize"]!r}: that share of the training rows, {num_text(ms)} rows')
    lines.append(f'tree = Tree(columns, X, y, {L}, w, cnt, sets, minsize={num_text(ms)}, informative={P.missing == "informative"}'
                 + (f', levels={json.dumps(list(P.labels))})' if L else ')'))
    if P.folds is not None:
        lines.append(f'tree.folds = folds   # the {P.k} folds of {P.spec["validation"]}: Go crossvalidates by them')
    lines.append(f'tree.run({_py(sp["steps"])})')
    lines.append('print(tree.text())')
    lines.append('for k, r2 in tree.rsquares(tree.fitted()).items():')
    lines.append("    print(['Training', 'Validation', 'Test'][k], 'RSquare', round(r2, 6))")
    return '\n'.join(lines)


SEP = '\n\n# ----\n'


# ---------------------------------------------------------------------------
# the graphs as matplotlib code (predictive.graph_codes has the scheme)
# ---------------------------------------------------------------------------
# Every graph of the report is drawn from the tree the code grows: the head
# reads the table, replays the report's steps (the engine's, or CART's
# scikit-learn tree) and ends with fitted, leaf (each row's leaf, numbered
# left to right) and nodes (every node as the tree draws it: Tree.boxes, or
# cart_boxes). The tails draw the partition graph, the tree and the small
# tree (draw_tree), the split history, the leaf report and the column
# contributions; predictive.graph_codes the ROC, lift and actual by
# predicted. The page's display choices come in `plot` (Show Points, the
# Show Split options).

def draw_tree(nodes, levels=None, small=False, stats=True, bar=True, prob=True, count=True, cart=False, title='Decision tree'):
    """The tree as the report draws it (smui-p-partition.js), with matplotlib: a box per node, the parents
    above their children and the leaves side by side from the left, joined by elbow lines. A box shows the
    node's condition, count, mean and std dev, and the split's LogWorth (CART: its SS) and Difference; or
    its G^2 and a line per level: the rate as a bar, Rate, Prob and Count. small: the Small Tree View's
    boxes (the condition, the rows, the mean or the most likely level). The sizes are the page's, in pixels
    at 100 an inch; stats, bar, prob and count are its Show Split options."""
    import math
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    palette = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']
    ink, second, muted, border, surface, band = '#352921', '#6b5d4f', '#786b5d', '#e0d7ce', '#fcf7f2', '#f6efe8'
    pt = 0.72   # points per pixel, at 100 pixels an inch

    def fmt(v, sig=7):
        """A number as the report writes it: an integer as it is, else sig significant digits."""
        if v is None or v != v:
            return '.'
        if math.isinf(v):
            return '∞' if v > 0 else '−∞'
        if float(v).is_integer() and abs(v) < 1e15:
            s = str(int(v))
        elif abs(v) >= 1e9 or abs(v) < 1e-4:
            m, e = f'{v:.{min(sig, 5) - 1}e}'.split('e')
            s = f'{m}e{int(e)}'
        else:
            s = f'{v:.{sig}g}'
            if 'e' in s:
                s = repr(float(s))
            if '.' in s:
                s = s.rstrip('0').rstrip('.')
        return '−' + s[1:] if s.startswith('-') else s

    def clip(s, px, cw=6.4):
        n = max(3, int(px // cw))
        s = str(s)
        return s[:n - 1] + '…' if len(s) > n else s

    def at(v):
        return math.floor(v + 0.5)   # a pixel, rounded as the page rounds

    cat = levels is not None
    L = len(levels) if cat else 0
    TITLE, ROW, GAP, VGAP, PAD = (17, 12, 8, 18, 6) if small else (20, 14, 14, 28, 6)
    level_w = bar_w = num_w = cnt_w = 0
    if small:
        BW = 118
    elif cat:
        level_w = max(38, min(96, at(6.3 * max([5] + [len(str(v)) for v in levels]))))
        bar_w, num_w, cnt_w = (38 if bar else 0), 46, (42 if count else 0)
        BW = max(184, 10 + level_w + bar_w + num_w * (2 if prob else 1) + cnt_w)
    else:
        BW = 184

    def height(nd):
        if small:
            return TITLE + ROW + 5
        h = TITLE + PAD
        if cat:
            h += (ROW * (3 if nd['split'] else 2) if stats else 0) + ROW * (L + 1)
        else:
            h += ROW * ((3 + (2 if nd['split'] else 0)) if stats else 1)
        return h + 6

    def depth(nd):
        return len(nd['path'])
    D = max(depth(nd) for nd in nodes)
    row_h = [0] * (D + 1)
    for nd in nodes:
        row_h[depth(nd)] = max(row_h[depth(nd)], height(nd))
    ys, yy = [], PAD
    for d in range(D + 1):
        ys.append(yy)
        yy += row_h[d] + VGAP
    H = math.ceil(yy - VGAP + PAD)
    W = math.ceil(GAP + sum(1 for nd in nodes if nd['leaf']) * (BW + GAP))

    def cx(nd):
        return GAP + (nd['lo'] + nd['hi']) / 2 * (BW + GAP) + BW / 2
    top = 30 if title else 0   # room for the title
    fig = plt.figure(figsize=(W / 100, (H + top) / 100))
    ax = fig.add_axes([0, 0, 1, H / (H + top)])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)   # y down, as on the page
    ax.axis('off')
    if title:
        ax.set_title(title, fontsize=9)
    by = {nd['path']: nd for nd in nodes}
    for nd in nodes:   # the lines from each split node down to its two children
        if nd['split']:
            d = depth(nd)
            x0, y0, ym = cx(nd), ys[d] + height(nd), ys[d] + row_h[d] + VGAP / 2
            for side in 'LR':
                ch = by[nd['path'] + side]
                ax.plot([x0, x0, cx(ch), cx(ch)], [y0, ym, ym, ys[d + 1]], color=muted, linewidth=1.2 * pt)
    for nd in nodes:
        x, y0, h = at(cx(nd) - BW / 2), ys[depth(nd)], height(nd)
        ax.add_patch(Rectangle((x + 0.5, y0 + 0.5), BW - 1, h - 1, facecolor=surface, edgecolor=muted if nd['leaf'] else border, linewidth=pt))
        if small:
            ax.text(x + 5, y0 + TITLE - 5, clip(nd['label'], BW - 8, 6.2), fontsize=9.5 * pt, color=ink)
            if cat:
                j = nd['probs'].index(max(nd['probs']))   # the most likely level
                right = f'{clip(levels[j], 36, 5.6)} {nd["probs"][j]:.3f}'
            else:
                right = fmt(nd['mean'], 4)
            ax.text(x + 5, y0 + TITLE + ROW - 2, f'{fmt(nd["count"])} rows', fontsize=9 * pt, color=second)
            ax.text(x + BW - 5, y0 + TITLE + ROW - 2, right, fontsize=9 * pt, color=ink, ha='right')
            continue
        ax.add_patch(Rectangle((x + 0.5, y0 + 0.5), BW - 1, TITLE - 0.5, facecolor=band, edgecolor='none'))   # the heading
        ax.text(x + 18, y0 + TITLE - 6, clip(nd['label'], BW - 24, 7.1), fontsize=11 * pt, fontweight='bold', color=ink)
        rows = []   # (name, value) lines under the heading
        s = nd['split']
        if not cat:
            if stats:
                rows += [('Count', fmt(nd['count'])), ('Mean', fmt(nd['mean'], 6)), ('Std Dev', fmt(nd['sd'], 6))]
                if s:
                    rows += [('SS' if cart else 'LogWorth', fmt(s['stat'] if cart else s['logworth'], 6)), ('Difference', fmt(s['difference'], 6))]
            else:
                rows.append(('Mean', fmt(nd['mean'], 6)))
        elif stats:
            rows += [('Count', fmt(nd['count'])), ('G^2', fmt(nd['g2'], 6))]
            if s:
                rows.append(('Split G^2' if cart else 'LogWorth', fmt(s['stat'] if cart else s['logworth'], 6)))
        yy = y0 + TITLE + PAD + ROW - 3
        for k, v in rows:
            ax.text(x + 7, yy, k, fontsize=10.5 * pt, color=second)
            ax.text(x + BW - 7, yy, v, fontsize=10.5 * pt, color=ink, ha='right')
            yy += ROW
        if not cat:
            continue
        # the level table: Level, a bar, Rate, Prob, Count
        x_bar = x + 7 + level_w
        x_rate = x_bar + bar_w + num_w - 4
        x_prob = x_rate + num_w if prob else None
        x_cnt = x_bar + bar_w + num_w * (2 if prob else 1) + cnt_w - 4
        heads = [(x + 7, 'Level', 'left'), (x_rate, 'Rate', 'right')] + ([(x_prob, 'Prob', 'right')] if prob else []) + ([(x_cnt, 'Count', 'right')] if count else [])
        for hx, ht, ha in heads:
            ax.text(hx, yy, ht, fontsize=9.5 * pt, color=muted, ha=ha)
        yy += ROW
        for j, lv in enumerate(levels):
            ax.text(x + 7, yy, clip(lv, level_w - 4), fontsize=10.5 * pt, color=second)
            if bar:
                ax.add_patch(Rectangle((x_bar, yy - 8), bar_w - 6, 8, facecolor=border, edgecolor='none'))
                ax.add_patch(Rectangle((x_bar, yy - 8), max(0.0, (bar_w - 6) * nd['rates'][j]), 8, facecolor=palette[j % len(palette)], edgecolor='none'))
            ax.text(x_rate, yy, f'{nd["rates"][j]:.4f}', fontsize=10.5 * pt, color=ink, ha='right')
            if prob:
                ax.text(x_prob, yy, f'{nd["probs"][j]:.4f}', fontsize=10.5 * pt, color=ink, ha='right')
            if count:
                ax.text(x_cnt, yy, fmt(math.floor(nd['counts'][j] * 1000 + 0.5) / 1000), fontsize=10.5 * pt, color=ink, ha='right')
            yy += ROW
    return fig, ax


def _graph_head(P, t, sp, ms, group, table_name, rows):
    """The head of every graph's code: the table and the tree the engine grows (the report's steps), then
    fitted, leaf and nodes."""
    L = len(P.levels) if P.kind == 'categorical' else 0
    lines = P.code(table_name, rows, extra_imports=[predictive.PLT])
    f = sp['freq']
    lines.append(f'cnt = d[{json.dumps(f)}].to_numpy(float)   # the frequencies: the minimum size and the degrees of freedom count them'
                 if f else 'cnt = None   # every row counts once')
    fit = [f'# Partition for {P.y}{f" ({one_line(group)})" if group else ""}: the report\'s steps replayed from the root', 'columns = [']
    fit += [f'    {c!r},' for c in t.cols]
    fit.append(']')
    if float(sp['minsize']) < 1:
        fit.append(f'# Minimum Size Split {sp["minsize"]!r}: that share of the training rows, {num_text(ms)} rows')
    fit.append(f'tree = Tree(columns, X, y, {L}, w, cnt, sets, minsize={num_text(ms)}, informative={P.missing == "informative"}'
               + (f', levels={json.dumps(list(P.labels))})' if L else ')'))
    if P.folds is not None:
        fit.append(f'tree.folds = folds   # the {P.k} folds of {P.spec["validation"]}: Go crossvalidates by them')
    fit.append(f'tree.run({_py(sp["steps"])})')
    fit += ['fitted = tree.fitted()   # each row\'s prediction: its leaf\'s mean, or its leaf\'s probability of every level',
            'leaf = np.zeros(len(y), dtype=int)   # each row\'s leaf, numbered from the left from 0',
            'for i, nd in enumerate(tree.leaves()):',
            '    leaf[nd.rows] = i',
            'nodes = tree.boxes()   # every node as the tree draws it']
    return SEP.join(['\n'.join(lines), engine_source(), '\n'.join(fit)])


def _partition_tail(P, plot):
    """The partition graph: the training rows side by side in their leaves, each leaf as wide as its rows."""
    J = json.dumps
    points = plot.get('points', True) is not False
    n = int(P.train().sum())
    L = ['leaves = [nd for nd in nodes if nd["leaf"]]   # left to right',
         'idx = [np.flatnonzero((leaf == l) & train) for l in range(len(leaves))]   # each leaf\'s training rows, in the table\'s order',
         'edges = np.r_[0, np.cumsum([len(r) for r in idx])] / sum(len(r) for r in idx)   # each leaf\'s band: as wide as its rows',
         'centers = (edges[:-1] + edges[1:]) / 2']
    if P.kind == 'continuous':
        size = 3.5 if n > 1500 else 5
        L += [predictive.figure(560, 300)]
        if points:
            L += ['for l, r in enumerate(idx):',
                  '    lo, hi = edges[l], edges[l + 1]',
                  f'    ax.scatter(lo + (np.arange(len(r)) + 0.5) / len(r) * (hi - lo), y[r], s={size * size * 0.55:g}, color="{predictive.BASE}")   # the rows evenly across the band, in order']
        L += ['for l, nd in enumerate(leaves):',
              f'    ax.plot([edges[l], edges[l + 1]], [nd["mean"], nd["mean"]], color="{predictive.FIT}", linewidth=2)   # the leaf\'s mean',
              f'ax.set_ylabel({J(P.y)})']
    else:
        size = 3 if n > 1500 else 4.5
        L += [f'names = {J(list(P.labels))}   # the levels, as the report names them',
              f'colors = {J(predictive.PALETTE)}',
              'rates = np.array([nd["rates"] for nd in leaves])',
              'cum = np.c_[np.zeros(len(leaves)), np.cumsum(rates, axis=1)]   # the rates stacked in each band',
              predictive.figure(560, 300),
              'for j, name in enumerate(names):',
              f'    ax.bar(centers, rates[:, j], bottom=cum[:, j], width=np.maximum(np.diff(edges), 1e-6), color=colors[j % len(colors)], alpha={0.28 if points else 0.8}, linewidth=0, label=name)']
        if points:
            L += ['rng = np.random.default_rng(1)   # each row at random in its level\'s part of its band, as the page places it (with random numbers of its own)',
                  'for l, r in enumerate(idx):',
                  '    lo, hi, j = edges[l], edges[l + 1], y[r]',
                  f'    ax.scatter(lo + (0.08 + 0.84 * rng.uniform(size=len(r))) * (hi - lo), cum[l, j] + (0.1 + 0.8 * rng.uniform(size=len(r))) * rates[l, j], s={size * size * 0.55:g}, color="{predictive.BASE}")']
        L += ['ax.set_ylim(0, 1)', f'ax.set_ylabel({J(P.y + ": rate")})',
              'fig.legend(loc="outside upper left", ncols=min(len(names), 6), frameon=False, fontsize=8)']
    L += ['for e in edges[1:-1]:',
          f'    ax.axvline(e, color="{predictive.MUTED}", linewidth=1, linestyle=":")   # the leaves\' edges',
          'ax.set_xlim(0, 1)',
          'if len(leaves) <= 40:',
          '    ax.set_xticks(centers, [str(l + 1) for l in range(len(leaves))])   # the Leaf Report\'s numbers',
          'else:',
          '    ax.set_xticks([])',
          'ax.set_xlabel("Leaves (the Leaf Report\'s numbers)")',
          f'ax.set_title({J("Partition of " + P.y)}, wrap=True)',
          'plt.show()']
    return '\n'.join(L)


def _tree_tail(P, plot, small, cart):
    """The tree, or the Small Tree View: draw_tree on the nodes."""
    src = inspect.getsource(draw_tree).rstrip()
    lv = f'levels={json.dumps(list(P.labels))}' if P.kind == 'categorical' else 'levels=None'
    opts = '' if small else f', stats={plot.get("stats", True) is not False}, bar={plot.get("bar", True) is not False}, prob={plot.get("prob", True) is not False}, count={plot.get("count", True) is not False}'
    call = f'draw_tree(nodes, {lv}, small={small}{opts}, cart={cart}, title={json.dumps("Small tree view" if small else "Decision tree")})'
    return '\n'.join([src, '', '', call + ('' if small else '   # the page\'s Show Split options'), 'plt.show()'])


def _aicc_tail(cart=False):
    """The split history's AICc: the training rows' AICc after each split, in the order made, the smallest
    marked (Tree.history's 'aicc', or cart_history's)."""
    return '\n'.join(([inspect.getsource(cart_history).rstrip(), '', ''] if cart else []) + [
        ('hist = cart_history(model, X, y, w, sets, nodes, root, L)' if cart else 'hist = tree.history()') + '   # after 0, 1, ... splits: each set\'s RSquare, and the AICc',
        'aicc = [h["aicc"] for h in hist]',
        predictive.figure(460, 260),
        f'ax.plot(range(len(aicc)), aicc, color="{predictive.BASE}", linewidth=1.8, marker="o", markersize=3.6)',
        'best = int(np.nanargmin(aicc)) if np.isfinite(aicc).any() else None',
        'if best is not None:',
        f'    ax.plot([best], [aicc[best]], linestyle="none", marker="D", markersize=7, color="{predictive.FIT}")   # the smallest AICc',
        'ax.set_xlim(left=0)', 'ax.set_xlabel("Number of Splits")', 'ax.set_ylabel("AICc")',
        'ax.set_title("AICc by number of splits")',
        'plt.show()'])


def _history_tail(P, go, cart=False, ylabel=None):
    """The split history: each set's RSquare (or entropy RSquare) after each split, in the order made
    (the engine's Tree.history, or cart_history), and after Go the splits it looked at past the best."""
    sets = [k for k in range(3) if P.has(k)]
    colors = {0: predictive.BASE, 1: '#b8641d', 2: '#3a7d44'}
    L = [inspect.getsource(cart_history).rstrip(), '', '',
         'hist = cart_history(model, X, y, w, sets, nodes, root, L)   # each set\'s RSquare after 0, 1, ... splits, in the order best-first growth made them'] if cart else [
         'hist = tree.history()   # each set\'s RSquare after 0, 1, ... splits, in the order the splits were made']
    L += [
         f'colors = {json.dumps({str(k): colors[k] for k in sets})}',
         f'sets = {json.dumps([[k, predictive.SETS[k]] for k in sets])}',
         predictive.figure(460, 280),
         'for k, name in sets:',
         '    ax.plot(range(len(hist)), [h[k] for h in hist], color=colors[str(k)], linewidth=1.8, marker="o", markersize=3.6, label=name)']
    cvgo = bool(go) and P.folds is not None and not P.has(1)
    if cvgo:
        L += [('g = go' if cart else 'g = tree.go_trace') + '   # Go by the folds: the crossvalidated RSquare ("cv") of each size it looked at',
              'upto = [e for e in g["trace"] if e["splits"] <= g["best"]]',
              'past = [e for e in g["trace"] if e["splits"] >= g["best"]]',
              f'ax.plot([e["splits"] for e in upto], [e["cv"] for e in upto], color="{colors[1]}", linewidth=1.8, marker="o", markersize=3.6, label="Crossvalidation")',
              'if len(past) > 1:',
              f'    ax.plot([e["splits"] for e in past], [e["cv"] for e in past], color="{colors[1]}", linewidth=1.2, linestyle=":", marker="o", markersize=2.9, markerfacecolor="none")']
    if go:
        L += [('g = go' if cart else 'g = tree.go_trace') + '   # Go: the splits it looked at, and the number it kept',
              'after = [e for e in g["trace"] if e["splits"] > g["best"]]',
              'kept = next(e for e in g["trace"] if e["splits"] == g["best"])',
              'for k, name in sets:',
              '    ax.plot([g["best"]] + [e["splits"] for e in after], [kept[k]] + [e[k] for e in after], color=colors[str(k)], linewidth=1.2, linestyle=":",',
              '            marker="o", markersize=2.9, markerfacecolor="none")   # looked at past the best, then pruned',
              f'ax.axvline(g["best"], color="{predictive.MUTED}", linewidth=1, linestyle="--")']
    L += ['ax.set_xlim(left=0)', 'ax.set_xlabel("Number of Splits")',
          f'ax.set_ylabel("{ylabel or ("Entropy RSquare" if P.kind == "categorical" else "RSquare")}")',
          'ax.set_title("Split history")']
    if len(sets) > 1 or cvgo:
        L.append('fig.legend(loc="outside upper left", ncols=3, frameon=False, fontsize=8)')
    L.append('plt.show()')
    return '\n'.join(L)


def _leaves_tail(P, nl):
    """The Leaf Report's bars: each leaf's mean, or its probabilities stacked."""
    h = max(160, min(560, 48 + 22 * nl))
    L = ['leaves = [nd for nd in nodes if nd["leaf"]]   # left to right, numbered from 1',
         'numbers = [str(l + 1) for l in range(len(leaves))]']
    if P.kind == 'continuous':
        L += [predictive.figure(320, h),
              f'ax.barh(numbers, [nd["mean"] for nd in leaves], height=0.75, color="{predictive.BAR}")',
              'ax.invert_yaxis()   # leaf 1 at the top',
              f'ax.set_xlabel({json.dumps("Mean " + P.y)})', 'ax.set_ylabel("Leaf")', 'ax.set_title("Leaf means")']
    else:
        L += [f'names = {json.dumps(list(P.labels))}', f'colors = {json.dumps(predictive.PALETTE)}',
              'probs = np.array([nd["probs"] for nd in leaves])',
              predictive.figure(340, h + 20),
              'for j, name in enumerate(names):',
              '    ax.barh(numbers, probs[:, j], left=probs[:, :j].sum(axis=1), height=0.75, color=colors[j % len(colors)], label=name)',
              'ax.invert_yaxis()   # leaf 1 at the top', 'ax.set_xlim(0, 1)',
              'ax.set_xlabel("Prob")', 'ax.set_ylabel("Leaf")', 'ax.set_title("Leaf probabilities")',
              'fig.legend(loc="outside upper left", ncols=min(len(names), 4), frameon=False, fontsize=8)']
    L.append('plt.show()')
    return '\n'.join(L)


def _contrib_lines(P):
    """contrib: the SS (or G^2) of each column's splits, from the nodes."""
    return [f'contrib = {{c: 0.0 for c in {json.dumps(list(P.x))}}}   # the X columns',
            'for nd in nodes:',
            '    if nd["split"]:',
            '        contrib[nd["split"]["column"]] += nd["split"]["stat"]   # what the split explains (SS or G^2)']


def _plots(P, head, plot, nl, go, cart):
    """The graphs' code of a tree (every tail after head)."""
    return {'partition': _partition_tail(P, plot), 'tree': _tree_tail(P, plot, False, cart), 'small': _tree_tail(P, plot, True, cart),
            'history': _history_tail(P, go, cart), 'aicc': _aicc_tail(cart), 'leaves': _leaves_tail(P, nl)}


def _cart_head(P, c, sp, group, table_name, rows):
    """The head of a CART tree's graphs: the table, and the report's steps replayed on scikit-learn's tree
    grown best first (Go's loop too, as _cart_grown runs it), then fitted, leaf and nodes (cart_boxes)."""
    L = c.L
    cls = 'DecisionTreeClassifier' if L else 'DecisionTreeRegressor'
    lines = P.code(table_name, rows, extra_imports=[predictive.PLT, f'from sklearn.tree import {cls}'])
    f = sp['freq']
    lines.append(f'cnt = d[{json.dumps(f)}].to_numpy(float)   # the frequencies: a node\'s count counts them'
                 if f else 'cnt = None   # every row counts once')
    helpers = '\n\n\n'.join(inspect.getsource(fn).rstrip() for fn in (cart_r2, cart_boxes))
    crit = 'criterion="log_loss", ' if L else ''
    steps = sp['steps']
    F = [f'# Partition for {P.y}{f" ({one_line(group)})" if group else ""} by CART: scikit-learn\'s tree grown best first, the report\'s steps replayed',
         f'L = {L}   # the levels of the response (0: a continuous response)',
         'wt = np.ones(len(y)) if w is None else w', '', '',
         'def grow(k):',
         '    """The CART tree of k leaves, grown best first (None: one leaf, no split)."""',
         '    if k < 2:',
         '        return None',
         f'    return {cls}({crit}max_leaf_nodes=int(k), min_samples_leaf={max(1, int(math.ceil(c.ms)))}, random_state={int(sp["seed"] or 0)}).fit(X[train], y[train], sample_weight=wt[train])',
         '', '',
         'def predict(model):',
         '    """Every row\'s prediction: its leaf\'s rates (a column for every level) or its mean; with no split the root\'s."""',
         '    if model is None:',
         '        return np.tile(root, (len(y), 1)) if L else np.full(len(y), root)',
         '    if not L:',
         '        return model.predict(X)',
         '    out = np.zeros((len(X), L))',
         '    out[:, model.classes_.astype(int)] = model.predict_proba(X)',
         '    return out', '', '',
         'root = np.bincount(y[train], weights=wt[train], minlength=L) / wt[train].sum() if L else float(np.sum(wt[train] * y[train]) / wt[train].sum())   # with no split',
         'full = grow(2 ** 20)',
         'n_max = 1 if full is None else int(full.get_n_leaves())   # the leaves of the whole tree']
    if float(sp['minsize']) < 1:
        F.insert(1, f'# Minimum Size Split {sp["minsize"]!r}: that share of the training rows, {num_text(c.ms)} rows')
    if any(st.get('op') == 'go' for st in steps) and P.folds is not None and not P.has(1):
        F += ['', '',
              'def grow_on(k, rows):',
              '    """The CART tree of k leaves grown on the rows (None: one leaf, no split)."""',
              '    if k < 2:',
              '        return None',
              f'    return {cls}({crit}max_leaf_nodes=int(k), min_samples_leaf={max(1, int(math.ceil(c.ms)))}, random_state={int(sp["seed"] or 0)}).fit(X[rows], y[rows], sample_weight=wt[rows])',
              '', '',
              'def predict_on(model, rows):',
              '    """Every row\'s prediction by a tree grown on the rows (with no split, their mean or shares)."""',
              '    if model is None:',
              '        r0 = np.bincount(y[rows], weights=wt[rows], minlength=L) / wt[rows].sum() if L else float(np.sum(wt[rows] * y[rows]) / wt[rows].sum())',
              '        return np.tile(r0, (len(y), 1)) if L else np.full(len(y), r0)',
              '    if not L:',
              '        return model.predict(X)',
              '    out = np.zeros((len(X), L))',
              '    out[:, model.classes_.astype(int)] = model.predict_proba(X)',
              '    return out', '', '',
              'def go_from(n0):',
              f'    """Go by the {P.k} folds of the Validation column: a leaf more at a time until the crossvalidated RSquare (each fold',
              '    predicted by the tree of as many leaves grown on the other folds) has not improved for 10 leaves; the number of',
              '    leaves with the best, and what it looked at."""',
              '    trace, best, k_best, k = [], None, n0, n0',
              f'    while k - k_best <= {AHEAD} and k <= n_max:',
              '        f = predict(grow(k))',
              '        cvp = np.zeros_like(f)',
              f'        for q in range({P.k}):',
              '            fit_rows = (folds >= 0) & (folds != q)',
              '            cvp[folds == q] = predict_on(grow_on(k, fit_rows), fit_rows)[folds == q]',
              '        r = cart_r2(cvp, y, w, np.where(folds >= 0, 0, -1), 0, L)',
              '        trace.append({"splits": k - 1, 0: cart_r2(f, y, w, sets, 0, L), "cv": r})   # the training and the crossvalidated RSquare',
              '        if best is None or r > best + 1e-12:',
              '            best, k_best = r, k',
              '        k += 1',
              '    return k_best, {"start": n0 - 1, "best": k_best - 1, "trace": trace}', '', '']
    elif any(st.get('op') == 'go' for st in steps):
        F += ['', '',
              'def go_from(n0):',
              '    """Go: a leaf more at a time until the validation RSquare has not improved for 10 leaves; the number of',
              '    leaves with the best, and what it looked at."""',
              '    trace, best, k_best, k = [], None, n0, n0',
              f'    while k - k_best <= {AHEAD} and k <= n_max:',
              '        f = predict(grow(k))',
              '        r = cart_r2(f, y, w, sets, 1, L)',
              '        trace.append({"splits": k - 1, **{q: cart_r2(f, y, w, sets, q, L) for q in (0, 1, 2) if (sets == q).any()}})',
              '        if best is None or r > best + 1e-12:',
              '            best, k_best = r, k',
              '        k += 1',
              '    return k_best, {"start": n0 - 1, "best": k_best - 1, "trace": trace}', '', '']
    F += [f'steps = {_py(steps)}   # the report\'s steps: CART splits and prunes the whole tree, not one node',
          'n, go = 1, None',
          'for st in steps:',
          '    if st["op"] == "split" and not st.get("node"):',
          '        n = min(n_max, n + max(1, int(st.get("n") or 1)))',
          '    elif st["op"] == "prune" and not st.get("node"):',
          '        n = max(1, n - 1)']
    if any(st.get('op') == 'go' for st in steps):
        F += ['    elif st["op"] == "go"' + ('' if P.folds is not None and not P.has(1) else ' and (sets == 1).any()') + ':', '        n, go = go_from(n)']
    F += ['if not steps or steps[-1]["op"] != "go":',
          '    go = None   # the split history shows what Go looked at right after it',
          'model = grow(n)',
          'fitted = predict(model)   # each row\'s prediction: its leaf\'s mean, or its leaf\'s rates',
          f'features = {json.dumps(list(P.features))}   # the columns of X',
          'columns = [' + ', '.join(f'({json.dumps(n)}, {cont}, {cols})' for n, cont, cols in _cart_columns(P)) + ']   # each X column: continuous or not, its columns of X',
          'nodes, leaf_rows, _ = cart_boxes(model, X, y, w, cnt, train, L, features, columns, root)   # every node as the tree draws it',
          'leaf = np.zeros(len(y), dtype=int)   # each row\'s leaf, numbered from the left from 0',
          'for i, r in enumerate(leaf_rows):',
          '    leaf[r] = i']
    return SEP.join(['\n'.join(lines), helpers, '\n'.join(F)])


@api('partition.fit')
def fit(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
        minsize=5, ordinal_order=True, steps=None, group=None, plot=None, table_name='data'):
    """The tree of the report's steps: its nodes (with every column's best
    split), the Measures of Fit, the summary line, the split history, the
    leaves, the column contributions, and each row's leaf. plot: the page's
    display choices for the graphs' code (points, stats, bar, prob, count)."""
    sp = _spec(y, x, weight, freq, validation, portion, seed, missing, minsize, ordinal_order, steps)
    P, t, ms = _grown(table, rows, sp)
    fitted = t.fitted()
    head = _graph_head(P, t, sp, ms, group, table_name, rows)
    rep = predictive.report(P, fitted, head=head)
    leaves = t.leaves()
    labels, rules = _leaf_labels(t), leaf_rules(t)
    leaf_of = np.zeros(len(P.index), dtype=int)
    for i, nd in enumerate(leaves):
        leaf_of[nd.rows] = i
    leaf_json = []
    for i, nd in enumerate(leaves):
        e = {'number': i + 1, 'path': nd.path, 'label': labels[i], 'rule': rules[i], 'count': nd.count, 'w': nd.W}
        if t.L:
            e.update(probs=nd.prob.tolist(), rates=nd.rate.tolist(), counts=nd.n.tolist())
        else:
            e.update(mean=nd.mean, sd=nd.sd)
        leaf_json.append(e)
    hist = _history_rows(t.history())
    last = (sp['steps'][-1].get('op') if sp['steps'] else None)
    go = None
    if last == 'go' and t.go_trace:
        g = t.go_trace
        go = {'start': g['start'], 'best': g['best'], 'folds': g.get('folds'),
              'trace': [{'splits': e['splits'], **{predictive.SETS[k]: e[k] for k in (0, 1, 2) if k in e}, **({'Crossvalidation': e['cv']} if 'cv' in e else {})} for e in g['trace']]}
    script = SEP.join([_head_code(P, sp, table_name, rows), engine_source(), _fit_code(P, t, sp, ms, group)])
    rep['plots'].update(_plots(P, head, plot or {}, len(leaves), go is not None, False))
    contrib = _contributions(P, t)
    contrib['plot_code'] = '\n'.join(_contrib_lines(P) + predictive.contribution_lines(len(P.x)))
    return {'kind': P.kind, 'y': P.y, 'levels': list(P.labels), 'nodes': _tree_json(P, t), 'leaves': leaf_json,
            'assign': {'rows': P.index.tolist(), 'leaf': leaf_of.tolist(), 'set': P.sets.tolist(), 'y': P.target.tolist()},
            'fit': rep, 'summary': _summary(P, t.splits(), rep, t.aicc(fitted, len(leaves))), 'history': hist, 'go': go, 'contributions': contrib,
            'splits': t.splits(), 'minsize': ms, 'notes': list(t.notes), 'has_validation': bool(P.has(1)), 'folds': _folds_json(P),
            'columns': [{'name': c.name, 'kind': c.kind} for c in t.cols], 'method': 'jmp', 'script': script}


def fold_index(P):
    """Each row's fold (from 0; -1 none) of a K-fold Validation column, from predictive.fold_masks, or None
    without one (a Validation column of more than three values holds the folds; every row trains)."""
    masks = predictive.fold_masks(P)
    if not masks:
        return None
    fold = np.full(len(P.index), -1)
    for j, (_, held) in enumerate(masks):
        fold[held] = j
    return fold


def _folds_json(P):
    """A K-fold Validation column's folds, for the page: their number, the column and each fold's value."""
    if P.folds is None:
        return None
    return {'k': int(P.k), 'column': P.spec.get('validation'), 'values': [predictive.level_label(v) for v in P.fold_values]}


@api('partition.save')
def save(table, y, x, rows=None, **kw):
    """Save Predicteds and Save Residuals: every row of the table whose factors the tree can take."""
    P, t, _ = _grown(table, rows, _spec(y, x, **kw))
    return predictive.saved(P, t.predict, t.predict_proba)


@api('partition.formula')
def formula(table, y, x, rows=None, what='prediction', **kw):
    """Save Prediction Formula, as JMP writes it: the tree as nested If, of the leaf's mean (a continuous
    response) or of each level's probability (a column Prob[level] per level); the page adds the Most Likely
    column from the probabilities' columns. what 'leaf_number' or 'leaf_label': Save Leaf Number Formula and
    Save Leaf Label Formula, each leaf's number (from 1, left to right) or its label."""
    from .util import formula_num, formula_str
    P, t, _ = _grown(table, rows, _spec(y, x, **kw))
    inf = P.missing == 'informative'
    if what in ('leaf_number', 'leaf_label'):
        leaves = t.leaves()
        at = {id(nd): i for i, nd in enumerate(leaves)}
        labels = _leaf_labels(t)
        if what == 'leaf_number':
            return {'kind': what, 'columns': [{'name': 'Leaf Number', 'expr': tree_formula(t, P, lambda nd: str(at[id(nd)] + 1), inf)}]}
        return {'kind': what, 'columns': [{'name': 'Leaf Label', 'expr': tree_formula(t, P, lambda nd: formula_str(labels[at[id(nd)]]), inf)}]}
    if P.kind == 'continuous':
        return {'kind': 'continuous', 'columns': [{'name': f'Predicted {P.y}', 'expr': tree_formula(t, P, lambda nd: formula_num(nd.mean), inf)}]}
    cols = [{'name': f'Prob[{lab}]', 'level': lab, 'expr': tree_formula(t, P, lambda nd, j=j: formula_num(nd.prob[j]), inf)} for j, lab in enumerate(P.labels)]
    return {'kind': 'categorical', 'columns': cols, 'levels': list(P.labels), 'most_name': f'Most Likely {P.y}',
            'ordinal': data.meta(P.table, P.y).get('modelingType') == 'ordinal'}


@api('partition.leaves')
def leaves(table, y, x, rows=None, **kw):
    """Save Leaf Numbers and Save Leaf Labels, for every row the tree can take."""
    P, t, _ = _grown(table, rows, _spec(y, x, **kw))
    X, rws = P.all_rows()
    idx = t.leaf_index(X)
    labels = _leaf_labels(t)
    return {'rows': rws.tolist(), 'numbers': (idx + 1).tolist(), 'labels': [labels[i] for i in idx]}


def _kfold_measures(P, pred_oof, t):
    """The folded measures (out-of-fold predictions of the training rows) and the overall ones (the tree's own)."""
    folded = next(m for m in predictive.measures(P, pred_oof) if m['set'] == 'Training')
    overall = next(m for m in predictive.measures(P, t.fitted()) if m['set'] == 'Training')
    return folded, overall


@api('partition.kfold')
def kfold_api(table, y, x, rows=None, k=5, group=None, table_name='data', **kw):
    """K Fold Crossvalidation of a tree with as many splits as the report's."""
    sp = _spec(y, x, **kw)
    P, t, ms = _grown(table, rows, sp)
    by_column = P.folds is not None
    k = int(P.k) if by_column else int(k)
    ntr = int(P.train().sum())
    if not by_column and not 2 <= k <= ntr:
        raise ValueError(f'the number of folds is from 2 to the number of training rows ({ntr})')
    seed = sp['seed'] if sp['seed'] is not None else 0
    L = len(P.levels) if P.kind == 'categorical' else 0
    pred, fold, per = kfold(t.cols, P.X, P.target, L, P.w, P.freq, P.sets, k, seed, t.splits(), ms, P.missing == 'informative', fold_index(P))
    folded, overall = _kfold_measures(P, pred, t)
    what = f'the {k} folds of {sp["validation"]}' if by_column else f'{k} folds of the training rows'
    lines = [f'# K Fold Crossvalidation{f" ({one_line(group)})" if group else ""}: {what}, each tree with the best {t.splits()} splits',
             'columns = [', *[f'    {c!r},' for c in t.cols], ']',
             f'pred, fold, per = kfold(columns, X, y, {L}, w, cnt, sets, k={k}, seed={seed}, splits={t.splits()}, minsize={num_text(ms)}, informative={P.missing == "informative"}'
             + (', folds=folds)' if by_column else ')'),
             'for f in per:', '    print(f)']
    if L:
        lines += ['share = np.bincount(y[train], weights=(np.ones(len(y)) if w is None else w)[train], minlength=pred.shape[1]) / (np.ones(len(y)) if w is None else w)[train].sum()',
                  'wt = (np.ones(len(y)) if w is None else w)[train]',
                  'p = np.clip(pred[train][np.arange(train.sum()), y[train]], 1e-15, 1)',
                  "print('Folded Entropy RSquare', 1 - np.sum(wt * np.log(p)) / np.sum(wt * np.log(share[y[train]])))"]
    else:
        lines += ['wt = (np.ones(len(y)) if w is None else w)[train]', 'yt, pt = y[train], pred[train]',
                  "print('Folded RSquare', 1 - np.sum(wt * (yt - pt) ** 2) / np.sum(wt * (yt - np.average(yt, weights=wt)) ** 2))"]
    script = SEP.join([_head_code(P, sp, table_name, rows), engine_source(), '\n'.join(lines)])
    if by_column:
        for e, v in zip(per, P.fold_values):
            e['value'] = predictive.level_label(v)
    return {'k': k, 'folds': per, 'folded': folded, 'overall': overall, 'kind': P.kind, 'splits': t.splits(), 'fold': fold.tolist(), 'script': script,
            'by_column': sp['validation'] if by_column else None}


def _profile_build(table, rows=None, **spec):
    P, t, _ = _grown(table, rows, _spec(**spec))
    return predictive.predictor(P, t)


profile.expose('partition', _profile_build)


# ---------------------------------------------------------------------------
# CART: scikit-learn's trees, grown best first
# ---------------------------------------------------------------------------
#
# DecisionTreeRegressor (squared error) or DecisionTreeClassifier (log loss,
# the entropy) with max_leaf_nodes: scikit-learn then grows best first,
# each split the one with the largest decrease of the impurity, so Split
# adds a leaf and Prune takes one off. The splits are not adjusted for how
# many cuts a column has, a nominal X is its 0/1 level columns (a split is
# one level against the rest), and a cut is halfway between two values.

class Cart:
    """A fitted scikit-learn tree with the report's view of it: nodes with
    their rows, conditions and statistics like the engine's."""

    def __init__(self, P, model, ms):
        self.P, self.model, self.ms = P, model, ms
        self.L = len(P.levels) if P.kind == 'categorical' else 0

    @property
    def classes_(self):
        return np.arange(self.L)

    def predict(self, X):
        return self.model.predict(X) if self.model is not None else np.full(len(X), self._root_value)

    def predict_proba(self, X):
        if self.model is None:
            return np.tile(self._root_value, (len(X), 1))
        return self.P.proba(self.model, X)


def _cart_model(P, n_leaves, ms, seed):
    from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
    if n_leaves < 2:
        return None
    tr = P.train()
    kw = dict(max_leaf_nodes=int(n_leaves), min_samples_leaf=max(1, int(math.ceil(ms))), random_state=int(seed or 0))
    m = DecisionTreeClassifier(criterion='log_loss', **kw) if P.kind == 'categorical' else DecisionTreeRegressor(**kw)
    return m.fit(P.X[tr], P.target[tr], sample_weight=P.weights(tr))


def _cart_fitted(P, model, root):
    if model is None:
        return np.tile(root, (len(P.index), 1)) if P.kind == 'categorical' else np.full(len(P.index), root)
    return P.proba(model, P.X) if P.kind == 'categorical' else model.predict(P.X)


def _cart_root(P):
    tr = P.train()
    w = P.weights(tr)
    if P.kind == 'categorical':
        return np.bincount(P.target[tr], weights=w, minlength=len(P.levels)) / w.sum()
    return float(np.sum(w * P.target[tr]) / w.sum())


def cart_r2(fitted, y, w, sets, k, L):
    """The RSquare of the rows of set k (0 training, 1 validation, 2 test): 1 - SSE/SST about their own
    mean, or for a categorical response (L levels) the entropy RSquare 1 - LL/LL0, LL0 from the training
    rows' shares of the levels, as the Measures of Fit have them; nan for a set with no rows."""
    import math
    import numpy as np
    m = sets == k
    if not m.any():
        return math.nan
    wt = np.ones(len(y)) if w is None else w
    if L:
        tr = sets == 0
        share = np.array([wt[tr][y[tr] == j].sum() for j in range(L)]) / wt[tr].sum()
        ym, p, wm = y[m], fitted[m], wt[m]
        ll = float(np.sum(wm * np.log(np.clip(p[np.arange(len(ym)), ym], 1e-15, 1.0))))
        ll0 = float(np.sum(wm * np.log(np.clip(share[ym], 1e-15, 1.0))))
        return 1 - ll / ll0 if ll0 < 0 else math.nan
    ym, f, wm = y[m], fitted[m], wt[m]
    r = ym - f
    N = float(wm.sum())
    sse = float(np.sum(wm * r * r))
    sst = float(np.sum(wm * (ym - float(np.sum(wm * ym) / N)) ** 2))
    return 1 - sse / sst if sst > 0 else math.nan


def _cart_r2(P, fitted, k):
    return cart_r2(np.asarray(fitted, dtype=float), P.target, P.w, P.sets, k, len(P.levels) if P.kind == 'categorical' else 0)


def cart_cv_r2(P, n_leaves, ms, seed, fold):
    """The crossvalidated RSquare of CART trees of n_leaves leaves: each fold of a K-fold Validation column
    (fold: each row's fold, -1 none) predicted by the tree of as many leaves grown on the other folds."""
    L = len(P.levels) if P.kind == 'categorical' else 0
    pred = np.zeros((len(P.index), L)) if L else np.zeros(len(P.index))
    for f in range(int(fold.max()) + 1):
        held = fold == f
        Q = _SetsView(P, np.where(held, 1, np.where(fold >= 0, 0, 2)))
        pv = _cart_fitted(Q, _cart_model(Q, n_leaves, ms, seed), _cart_root(Q))
        pred[held] = pv[held]
    return cart_r2(pred, P.target, P.w, np.where(fold >= 0, 0, -1), 0, L)


def _cart_go(P, n0, n_max, ms, seed, root, fold=None):
    """Go for CART: a leaf added at a time until the validation RSquare (with a K-fold Validation column and no
    validation rows, the crossvalidated one: cart_cv_r2) has not improved for 10 leaves; the number of leaves
    with the best."""
    cv = fold is not None and not P.has(1)
    trace, best, k_best = [], None, n0
    k = n0
    while k - k_best <= AHEAD and k <= n_max:
        f = _cart_fitted(P, _cart_model(P, k, ms, seed), root)
        r = cart_cv_r2(P, k, ms, seed, fold) if cv else _cart_r2(P, f, 1)
        trace.append({'splits': k - 1, **{predictive.SETS[q]: _cart_r2(P, f, q) for q in (0, 1, 2) if P.has(q)}, **({'Crossvalidation': r} if cv else {})})
        if best is None or r > best + 1e-12:
            best, k_best = r, k
        k += 1
    return k_best, {'start': n0 - 1, 'best': k_best - 1, 'trace': trace, 'folds': int(fold.max()) + 1 if cv else None}


def _cart_grown(table, rows, sp):
    def build():
        P = _prepared(table, rows, sp, 'onehot')
        ms = min_count(sp['minsize'], P)
        root = _cart_root(P)
        full = _cart_model(P, 2 ** 20, ms, sp['seed'])
        n_max = 1 if full is None else int(full.get_n_leaves())
        n, notes, go = 1, [], None
        fold = fold_index(P)
        for i, st in enumerate(sp['steps']):
            op = st.get('op')
            if op == 'split' and not st.get('node'):
                if n >= n_max:
                    notes.append(f'Step {i + 1} (split) was not done: no leaf can be split with at least {num_text(ms)} rows on each side.')
                n = min(n_max, n + max(1, int(st.get('n') or 1)))
            elif op == 'prune' and not st.get('node'):
                if n <= 1:
                    notes.append(f'Step {i + 1} (prune) was not done: there is no split to prune.')
                n = max(1, n - 1)
            elif op == 'go':
                if not P.has(1) and fold is None:
                    notes.append(f'Step {i + 1} (go) was not done: Go needs validation rows (a Validation column or a validation portion).')
                    continue
                n, go = _cart_go(P, n, n_max, ms, sp['seed'], root, fold)
            else:
                notes.append(f'Step {i + 1} ({op}) was not done: CART grows the whole tree best first, so it splits and prunes the tree, not one node.')
        if sp['steps'] and sp['steps'][-1].get('op') != 'go':
            go = None
        c = Cart(P, _cart_model(P, n, ms, sp['seed']), ms)
        c._root_value, c.notes, c.go = root, notes, go
        return P, c
    return predictive.cached('partition.cart', table, rows, sp, build)


def cart_boxes(model, X, y, w, cnt, train, L, features, columns, root=None):
    """A fitted scikit-learn tree as the report's tree draws it (the engine's is Tree.boxes): every node,
    parents before children and left before right, with its path ('' the root, then L and R), its
    condition (scikit-learn's cut, halfway between two values, shown to 6 digits; for a categorical X
    the level against the others its training rows have), its training rows' count, weight, and mean
    and std dev, or level weights, rates and G^2 (CART does not smooth its rates: Prob is the rate), the
    first and last leaf under it, and the split made there: its column, its SS or G^2 (the node's less
    its children's), the order best-first growth made it in, and the left child's mean less the right's.
    y: numbers, or level numbers 0..L-1 (L 0 for a continuous response); w: the weights, cnt the
    counts (Freq), each None for ones; features: the names of X's columns; columns: [(x column, whether
    it is continuous, its columns of X)]; root: the prediction with no split. Returns the nodes, each
    leaf's rows (every row, not only training ones) and each leaf's label."""
    import math
    import numpy as np
    from scipy.special import xlogy
    w = np.ones(len(y)) if w is None else w
    cnt = np.ones(len(y)) if cnt is None else cnt

    def stats_of(r):
        t = r[train[r]]
        d = {'count': float(cnt[t].sum()), 'w': float(w[t].sum())}
        if L:
            n = np.bincount(y[t], weights=w[t], minlength=L)
            rate = n / n.sum() if n.sum() > 0 else np.full(L, 1.0 / L)
            d.update(counts=n.tolist(), rates=rate.tolist(), probs=rate.tolist(), g2=float(-2 * (np.sum(xlogy(n, n)) - xlogy(n.sum(), n.sum()))))
        else:
            mean = float(np.sum(w[t] * y[t]) / w[t].sum())
            ss = float(np.sum(w[t] * (y[t] - mean) ** 2))
            d.update(mean=mean, ss=ss, sd=math.sqrt(ss / (d['count'] - 1)) if d['count'] > 1 else None)
        return d
    if model is None:
        d = {'path': '', 'parent': None, 'label': 'All Rows', 'leaf': True, 'lo': 0, 'hi': 0, 'number': 1, 'cands': [], 'split': None, **stats_of(np.arange(len(y)))}
        return [d], [np.arange(len(y))], ['All Rows']
    tr = model.tree_
    path = model.decision_path(X).tocsc()
    rows_of = [path[:, i].nonzero()[0] for i in range(tr.node_count)]
    column_of = {j: (name, cont, cols) for name, cont, cols in columns for j in cols}

    def labels(i):
        f, thr = int(tr.feature[i]), float(tr.threshold[i])
        col, cont, cols = column_of[f]
        name = features[f]
        if cont:
            if name.endswith(' Missing') and f != cols[0]:
                return [f'{col} not Missing', f'{col} Missing']
            return [f'{col}<={thr:.6g}', f'{col}>{thr:.6g}']   # scikit-learn's cut, halfway between two values
        t = rows_of[i][train[rows_of[i]]]
        present = [features[q][len(col) + 1:-1] for q in cols if X[t, q].sum() > 0]   # the levels its training rows have
        lev = name[len(col) + 1:-1]
        return [f'{col}({", ".join(x for x in present if x != lev)})', f'{col}({lev})']
    out, nodes, leaves = [], [], []

    def walk(i, p, parent, label):
        nodes.append((i, p, parent, label))
        if tr.children_left[i] == -1:
            leaves.append(i)
            return
        lab = labels(i)
        walk(int(tr.children_left[i]), p + 'L', p, lab[0])
        walk(int(tr.children_right[i]), p + 'R', p, lab[1])
    walk(0, '', None, 'All Rows')
    lat = {i: k for k, i in enumerate(leaves)}
    span = {}

    def reach(i):
        if tr.children_left[i] == -1:
            span[i] = (lat[i], lat[i])
        else:
            span[i] = (reach(int(tr.children_left[i]))[0], reach(int(tr.children_right[i]))[1])
        return span[i]
    reach(0)
    by = {}
    for i, p, parent, label in nodes:
        d = {'path': p, 'parent': parent, 'label': label, 'leaf': bool(tr.children_left[i] == -1), 'lo': span[i][0], 'hi': span[i][1],
             'number': lat[i] + 1 if i in lat else None, 'cands': [], 'split': None, **stats_of(rows_of[i])}
        by[p] = d
        out.append(d)
    node_at = {p: i for i, p, _, _ in nodes}
    for d in out:   # the splits' statistics
        if not d['leaf']:
            a, b = by[d['path'] + 'L'], by[d['path'] + 'R']
            stat = d['g2'] - a['g2'] - b['g2'] if L else d['ss'] - a['ss'] - b['ss']
            d['split'] = {'column': column_of[int(tr.feature[node_at[d['path']]])][0], 'logworth': None, 'stat': stat, 'order': None,
                          'children': [a['path'], b['path']], 'difference': None if L else a['mean'] - b['mean']}
    # the order best-first growth made the splits in: the largest decrease first, a node only after its parent
    pending = sorted((d for d in out if not d['leaf']), key=lambda d: (-d['split']['stat'], len(d['path'])))
    done, k = {''}, 0
    while pending:
        nxt = next(d for d in pending if d['parent'] in done or d['parent'] is None)
        pending.remove(nxt)
        done.add(nxt['path'])
        nxt['split']['order'] = k
        k += 1
    leaf_labels = []
    for i in leaves:
        parts, cur = [], by[next(pp for q, pp, _, _ in nodes if q == i)]
        while cur['parent'] is not None:
            parts.append(cur['label'])
            cur = by[cur['parent']]
        leaf_labels.append('&'.join(reversed(parts)) or 'All Rows')
    return out, [rows_of[i] for i in leaves], leaf_labels


def cart_history(model, X, y, w, sets, nodes, root, L):
    """Each set's RSquare (cart_r2) after 0, 1, ... splits of a CART tree, in the order best-first growth
    made them: the rows that reach a new pair of children take the children's rates (or means). And the
    training rows' AICc (under 'aicc'): -2 log L + 2k + 2k(k + 1)/(N - k - 1), L normal with variance SSE/N
    and k the leaves' means and the variance, or L the product of each row's rate of its level and k the
    leaves' rates (all but one level's); N the rows' weight."""
    import math
    import numpy as np
    wt = np.ones(len(y)) if w is None else w
    tr = sets == 0

    def aicc(pred, leaves):
        N = float(wt[tr].sum())
        if L:
            m2ll = -2 * float(np.sum(wt[tr] * np.log(np.clip(pred[tr][np.arange(int(tr.sum())), y[tr]], 1e-15, 1))))
            k = leaves * (L - 1)
        else:
            sse = float(np.sum(wt[tr] * (y[tr] - pred[tr]) ** 2))
            if not sse > 0:
                return math.nan
            m2ll, k = N * (math.log(2 * math.pi * sse / N) + 1), leaves + 1
        return m2ll + 2 * k + (2 * k * (k + 1) / (N - k - 1) if N - k - 1 > 0 else math.nan)
    pred = np.tile(root, (len(y), 1)) if L else np.full(len(y), float(root))
    present = [k for k in (0, 1, 2) if np.any(sets == k)]
    out = [{**{k: cart_r2(pred, y, w, sets, k, L) for k in present}, 'aicc': aicc(pred, 1)}]
    if model is None:
        return out
    t = model.tree_
    path = model.decision_path(X).tocsc()
    number = {}

    def walk(i, p):
        number[p] = i
        if t.children_left[i] != -1:
            walk(int(t.children_left[i]), p + 'L')
            walk(int(t.children_right[i]), p + 'R')
    walk(0, '')
    by = {d['path']: d for d in nodes}
    for d in sorted((d for d in nodes if d['split']), key=lambda d: d['split']['order']):
        for ch in (d['path'] + 'L', d['path'] + 'R'):
            pred[path[:, number[ch]].nonzero()[0]] = np.array(by[ch]['probs']) if L else by[ch]['mean']
        out.append({**{k: cart_r2(pred, y, w, sets, k, L) for k in present}, 'aicc': aicc(pred, len(out) + 1)})
    return out


def _cart_columns(P):
    """cart_boxes' columns: each x column, whether it is continuous, its columns of X."""
    return [(e['name'], e['type'] == 'continuous', list(P.groups[e['name']])) for e in P.enc]


def _cart_nodes(P, c):
    """The fitted tree as the engine's nodes: rows, conditions, statistics (cart_boxes)."""
    return cart_boxes(c.model, P.X, P.target, P.w, P.freq, P.train(), c.L, list(P.features), _cart_columns(P), c._root_value)


def _cart_history(P, c, nodes, leaf_rows):
    """RSquare per set after each split, in best-first order (cart_history)."""
    return _history_rows(cart_history(c.model, P.X, P.target, P.w, P.sets, nodes, c._root_value, c.L))


def _cart_code(P, c, sp, table_name, rows, group):
    n = 1 if c.model is None else int(c.model.get_n_leaves())
    head = '\n'.join(P.code(table_name, rows, extra_imports=('from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor, export_text',)))
    kind = 'DecisionTreeClassifier(criterion="log_loss", ' if P.kind == 'categorical' else 'DecisionTreeRegressor('
    lines = [f'# Partition for {P.y}{f" ({one_line(group)})" if group else ""} by CART: {n} leaves, grown best first']
    if n < 2:
        lines.append('print("no split: every row in one leaf")')
    else:
        lines += [f'model = {kind}max_leaf_nodes={n}, min_samples_leaf={max(1, int(math.ceil(c.ms)))}, random_state={int(sp["seed"] or 0)})',
                  'model.fit(X[train], y[train], sample_weight=None if w is None else w[train])',
                  f'print(export_text(model, feature_names={json.dumps(list(P.features))}))',
                  'print("Training RSquare" if model.__class__.__name__.endswith("Regressor") else "Training mean accuracy", model.score(X[train], y[train], sample_weight=None if w is None else w[train]))']
    return SEP.join([head, '\n'.join(lines)])


def _cart_payload(table, y, x, rows, kw):
    sp = _spec(y, x, **kw)
    P, c = _cart_grown(table, rows, sp)
    return sp, P, c


@api('partition.cart_fit', packages=predictive.SK)
def cart_fit(table, y, x, rows=None, group=None, plot=None, table_name='data', **kw):
    """The report of a CART tree (scikit-learn) with as many leaves as the steps ask for. plot: the
    page's display choices for the graphs' code, as partition.fit takes them."""
    sp, P, c = _cart_payload(table, y, x, rows, kw)
    nodes, leaf_rows, labels = _cart_nodes(P, c)
    fitted = _cart_fitted(P, c.model, c._root_value)
    head = _cart_head(P, c, sp, group, table_name, rows)
    rep = predictive.report(P, fitted, head=head)
    leaf_of = np.zeros(len(P.index), dtype=int)
    for i, r in enumerate(leaf_rows):
        leaf_of[r] = i
    leaf_json = []
    for i, d in enumerate([d for d in nodes if d['leaf']]):
        e = {'number': i + 1, 'path': d['path'], 'label': labels[i], 'count': d['count'], 'w': d['w']}
        e.update({k: d[k] for k in (('probs', 'rates', 'counts') if c.L else ('mean', 'sd'))})
        leaf_json.append(e)
    splits = sum(1 for d in nodes if not d['leaf'])
    contrib_vals = np.zeros(len(P.features))
    count = {cn: 0 for cn in P.x}
    for d in nodes:
        if not d['leaf']:
            contrib_vals[P.groups[d['split']['column']][0]] += d['split']['stat']
            count[d['split']['column']] += 1
    contrib = predictive.contributions(P, contrib_vals, 'SS' if P.kind == 'continuous' else 'G^2')
    for r in contrib['rows']:
        r['splits'] = count[r['column']]
    contrib['plot_code'] = '\n'.join(_contrib_lines(P) + predictive.contribution_lines(len(P.x)))
    rep['plots'].update(_plots(P, head, plot or {}, len(leaf_json), c.go is not None, True))
    hist = _cart_history(P, c, nodes, leaf_rows)
    return {'kind': P.kind, 'y': P.y, 'levels': list(P.labels), 'nodes': nodes, 'leaves': leaf_json,
            'assign': {'rows': P.index.tolist(), 'leaf': leaf_of.tolist(), 'set': P.sets.tolist(), 'y': P.target.tolist()},
            'fit': rep, 'summary': _summary(P, splits, rep, hist[-1].get('aicc')), 'history': hist, 'go': c.go,
            'contributions': contrib, 'splits': splits, 'minsize': c.ms, 'notes': list(c.notes), 'has_validation': bool(P.has(1)), 'folds': _folds_json(P),
            'columns': [{'name': e['name'], 'kind': e['type']} for e in P.enc], 'method': 'cart',
            'script': _cart_code(P, c, sp, table_name, rows, group)}


@api('partition.cart_save', packages=predictive.SK)
def cart_save(table, y, x, rows=None, **kw):
    _, P, c = _cart_payload(table, y, x, rows, kw)
    return predictive.saved(P, c.predict, c.predict_proba)


@api('partition.cart_leaves', packages=predictive.SK)
def cart_leaves(table, y, x, rows=None, **kw):
    _, P, c = _cart_payload(table, y, x, rows, kw)
    X, rws = P.all_rows()
    if c.model is None:
        return {'rows': rws.tolist(), 'numbers': [1] * len(rws), 'labels': ['All Rows'] * len(rws)}
    nodes, _, labels = _cart_nodes(P, c)
    leaf_ids = c.model.apply(X)
    order = []

    def collect(i):
        if c.model.tree_.children_left[i] == -1:
            order.append(i)
        else:
            collect(int(c.model.tree_.children_left[i]))
            collect(int(c.model.tree_.children_right[i]))
    collect(0)
    at = {i: k for k, i in enumerate(order)}
    idx = np.array([at[int(i)] for i in leaf_ids], dtype=int)
    return {'rows': rws.tolist(), 'numbers': (idx + 1).tolist(), 'labels': [labels[i] for i in idx]}


@api('partition.cart_kfold', packages=predictive.SK)
def cart_kfold(table, y, x, rows=None, k=5, group=None, table_name='data', **kw):
    """K Fold Crossvalidation of a CART tree with as many leaves as the report's."""
    sp, P, c = _cart_payload(table, y, x, rows, kw)
    by_column = P.folds is not None
    k = int(P.k) if by_column else int(k)
    tr = np.flatnonzero(P.train())
    if not by_column and not 2 <= k <= len(tr):
        raise ValueError(f'the number of folds is from 2 to the number of training rows ({len(tr)})')
    seed = sp['seed'] if sp['seed'] is not None else 0
    n = 1 if c.model is None else int(c.model.get_n_leaves())
    if by_column:
        fold = fold_index(P)
    else:
        fold = np.full(len(P.index), -1)
        fold[tr] = np.random.default_rng([int(seed), 2]).permutation(np.arange(len(tr)) % k)
    L = c.L
    pred = np.zeros((len(P.index), L)) if L else np.zeros(len(P.index))
    per = []
    for f in range(k):
        keep = (fold >= 0) & (fold != f)
        held = fold == f
        sets = np.where(keep, 0, np.where(held, 1, 2))
        Q = _SetsView(P, sets)
        m = _cart_model(Q, n, c.ms, seed)
        pv = _cart_fitted(Q, m, _cart_root(Q))
        pred[held] = pv[held]
        per.append({'fold': f + 1, 'n': float(P.counts(held).sum()), 'splits': (1 if m is None else int(m.get_n_leaves())) - 1, 'rsquare': _cart_r2(Q, pv, 1)})
    folded, overall = next(m for m in predictive.measures(P, pred) if m['set'] == 'Training'), next(m for m in predictive.measures(P, _cart_fitted(P, c.model, c._root_value)) if m['set'] == 'Training')
    what = f'the {k} folds of {sp["validation"]}' if by_column else f'{k} folds of the training rows'
    lines = [f'# K Fold Crossvalidation{f" ({one_line(group)})" if group else ""}: {what}, each a CART tree of {n} leaves']
    if by_column:
        lines.append('fold = folds   # the folds of the Validation column')
    else:
        lines += ['tr = np.flatnonzero(train)', 'fold = np.full(len(y), -1)',
                  f'fold[tr] = np.random.default_rng([{int(seed)}, 2]).permutation(np.arange(len(tr)) % {k})']
    lines.append('pred = np.zeros(' + (f'(len(y), {L}))' if L else 'len(y))'))
    kind = 'DecisionTreeClassifier(criterion="log_loss", ' if L else 'DecisionTreeRegressor('
    lines += [f'for f in range({k}):', '    fit_rows = (fold >= 0) & (fold != f)',
              f'    model = {kind}max_leaf_nodes={max(2, n)}, min_samples_leaf={max(1, int(math.ceil(c.ms)))}, random_state={int(seed)})',
              '    model.fit(X[fit_rows], y[fit_rows], sample_weight=None if w is None else w[fit_rows])',
              '    pred[fold == f] = ' + ('model.predict_proba(X[fold == f])   # (every level is in every fold here)' if L else 'model.predict(X[fold == f])'),
              'wt = (np.ones(len(y)) if w is None else w)[train]']
    if not L:
        lines.append("print('Folded RSquare', 1 - np.sum(wt * (y[train] - pred[train]) ** 2) / np.sum(wt * (y[train] - np.average(y[train], weights=wt)) ** 2))")
    head = '\n'.join(P.code(table_name, rows, extra_imports=('from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor',)))
    if by_column:
        for e, v in zip(per, P.fold_values):
            e['value'] = predictive.level_label(v)
    return {'k': k, 'folds': per, 'folded': folded, 'overall': overall, 'kind': P.kind, 'splits': n - 1, 'fold': fold.tolist(), 'script': SEP.join([head, '\n'.join(lines)]),
            'by_column': sp['validation'] if by_column else None}


class _SetsView:
    """The prepared data with other sets (a fold's), for the CART helpers."""

    def __init__(self, P, sets):
        self._P, self.sets = P, sets

    def __getattr__(self, k):
        return getattr(self._P, k)

    def mask(self, k):
        return self.sets == k

    def has(self, k):
        return bool(np.any(self.sets == k))

    def train(self):
        return self.sets == 0

    def weights(self, m=None):
        w = np.ones(len(self._P.index)) if self._P.w is None else self._P.w
        return w if m is None else w[m]

    def counts(self, m=None):
        f = np.ones(len(self._P.index)) if self._P.freq is None else self._P.freq
        return f if m is None else f[m]

    def proba(self, model, X):
        return predictive.Prepared.proba(self, model, X)


def _cart_profile_build(table, rows=None, **spec):
    sp = _spec(**spec)
    P, c = _cart_grown(table, rows, sp)
    return predictive.predictor(P, c, predict=c.predict, proba=c.predict_proba)


profile.expose('partition.cart', _cart_profile_build, packages=predictive.SK)
