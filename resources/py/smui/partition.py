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
    informative: Informative Missing; levels: the response's level names."""

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
        self.root = Node(self, np.arange(n))

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
        if node.count < 2 * self.minsize or len(node.tr) < 2:
            return None
        if (self.L and node.g2 <= 0) or (not self.L and node.ss <= 0):
            return None
        col, v = self.cols[j], self.vals[j][node.tr]
        w, c = self.w[node.tr], self.cnt[node.tr]
        if self.L:
            A = np.zeros((len(v), self.L))
            A[np.arange(len(v)), self.y[node.tr]] = w
        else:
            A = np.column_stack([w, w * (self.y[node.tr] - node.mean)])   # centred at the node's mean
        miss = np.isnan(v) if col.kind == 'continuous' else v < 0
        if col.kind == 'nominal':
            return self._nominal(node, j, col, v, A, c)
        return self._ordered(node, j, col, v, A, c, miss, cut)

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

    def _finish(self, node, j, rule, stat, lp, lnM, labels, v0, v1, cL, cR):
        lw = max(0.0, -(lp + lnM) / LN10) if math.isfinite(lp) else math.inf
        rule.big = 0 if cL >= cR else 1
        return {'j': j, 'stat': float(stat), 'lp': float(lp), 'lnM': float(lnM), 'logworth': float(lw), 'rule': rule,
                'labels': labels, 'first': 0 if v0 >= v1 else 1, 'counts': (float(cL), float(cR))}

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
                    best = (float(s[i]), f, i, AL[good, :].sum(axis=1) if self.L else AL[good, 0])
        tiny = 1e-10 * (node.g2 if self.L else node.ss)
        if best is None or best[0] <= tiny:
            return None
        stat, f, i, mw = best
        AL, cL, ms = fams[f]
        k = int(ks[i])
        lp = self._logp(node, stat)
        d = max(1, int(np.sum(node.n > 0)) - 1) if self.L else 1
        lnM = 0.0 if cut is not None else ordered_mult(lp, mw, node.W, d)
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
        return self._finish(node, j, rule, stat, lp, lnM, labels, v0, v1, cL[i], node.count - cL[i])

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
        if self.L and Lp >= 3 and u <= BINS:
            # every grouping, the first level on side 0: 2^(u-1) - 1 of them
            g = np.arange(1, 2 ** (u - 1))
            high = (g[:, None] >> np.arange(u - 1)[None, :]) & 1
            memb = np.column_stack([np.ones(len(g)), 1 - high])
        else:
            if not self.L:
                keys = [node.mean + B[:, 1] / B[:, 0]]
            elif Lp <= 2:
                j0 = int(np.flatnonzero(node.n > 0)[0])
                keys = [B[:, j0] / B.sum(axis=1)]
            else:   # many levels: the levels in the order of each response level's rate
                keys = [B[:, q] / B.sum(axis=1) for q in np.flatnonzero(node.n > 0)]
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
        tiny = 1e-10 * (node.g2 if self.L else node.ss)
        if not good.any() or s.max() <= tiny:
            return None
        i = int(np.argmax(s))
        stat = float(s[i])
        lp = self._logp(node, stat)
        # the multiplicity: Bonferroni over the groupings, or Scheffe's bound
        # (the best grouping is no better than the test of all u levels)
        lnG = (u - 1) * math.log(2) + math.log1p(-2.0 ** -(u - 1))
        if self.L:
            lpS = chi2_logsf(stat, (u - 1) * max(1, Lp - 1))
        else:
            ssb = float(np.sum(B[:, 1] ** 2 / B[:, 0]))
            dfw = node.count - u
            mse = (node.ss - ssb) / dfw if dfw > 0 else 0.0
            lpS = f_logsf(stat / ((u - 1) * mse), u - 1, dfw) if mse > node.ss * 1e-12 else math.nan
        lnM = lnG if not (math.isfinite(lpS) and math.isfinite(lp)) else max(0.0, min(lnG, lpS - lp))
        low, high = codes[memb[i] == 1], codes[memb[i] == 0]
        labels = [f'{col.name}({", ".join(col.level(x) for x in sorted(side, key=lambda q: (q < 0, q)))})' for side in (low, high)]
        rule = Rule('set', low=low, high=high)
        v0, v1 = self._side_values(node, AL[i])
        return self._finish(node, j, rule, stat, lp, lnM, labels, v0, v1, cL[i], node.count - cL[i])

    # ---- growing and pruning -------------------------------------------------------
    def split(self, node, cand):
        """Split node by a candidate: its children, the side with the larger
        mean (or rate of the first level) first."""
        s = cand['rule'].side(self.vals[cand['j']][node.rows])
        first = cand['first']
        node.children = [Node(self, node.rows[s == side], node.path + 'LR'[pos], node, cand['labels'][side])
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
        splits, then keep the tree with the best validation RSquare."""
        valid = self.sets == 1
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
                pred[ch.rows] = ch.value
            made.append(nd)
            r = self.rsquare(pred, valid)
            trace.append(dict(self.rsquares(pred), splits=start + len(made)))
            if r > best + 1e-12:
                best, k_best = r, len(made)
        for nd in reversed(made[k_best:]):
            self.prune_below(nd)
        self.go_trace = {'start': start, 'best': start + k_best, 'trace': trace}

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
            out[leaf.rows] = leaf.value
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

    def history(self):
        """RSquare of each set after each split, in the order they were made."""
        made = sorted((nd for nd in self.nodes() if nd.children), key=lambda nd: nd.order)
        pred = np.zeros((len(self.y), self.L)) if self.L else np.zeros(len(self.y))
        pred[:] = self.root.value
        out = [self.rsquares(pred)]
        for nd in made:
            for ch in nd.children:
                pred[ch.rows] = ch.value
            out.append(self.rsquares(pred))
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


def kfold(cols, X, y, L, w, cnt, sets, k=5, seed=0, splits=0, minsize=5, informative=True):
    """K-fold crossvalidation of a tree of `splits` best splits: the training
    rows in k folds drawn from the seed, each fold predicted by the tree
    grown on the others. Returns the out-of-fold predictions, the folds and
    each fold's RSquare."""
    sets = np.asarray(sets, dtype=int)
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

import json  # noqa: E402

from . import data, predictive, profile  # noqa: E402
from .registry import api  # noqa: E402

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
    """The engine's X columns from the prepared data (ordinal coding)."""
    cols = []
    for e in P.enc:
        idx = P.groups[e['name']]
        if e['type'] == 'continuous':
            cols.append(Col(e['name'], 'continuous', idx[0], idx[1] if len(idx) > 1 else None))
        else:
            ordinal = ordinal_order and data.meta(P.table, e['name']).get('modelingType') == 'ordinal'
            cols.append(Col(e['name'], 'ordinal' if ordinal else 'nominal', idx[0], None, [predictive.level_label(v) for v in e['levels']]))
    return cols


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


def _node_json(P, t, nd, lo, hi, number):
    d = {'path': nd.path, 'parent': nd.parent.path if nd.parent is not None else None, 'label': nd.label, 'count': nd.count,
         'w': nd.W, 'leaf': nd.children is None, 'lo': lo, 'hi': hi, 'number': number, 'split': None}
    if t.L:
        d.update(rates=nd.rate.tolist(), probs=nd.prob.tolist(), counts=nd.n.tolist(), g2=nd.g2)
    else:
        d.update(mean=nd.mean, sd=nd.sd, ss=nd.ss)
    if nd.children:
        c = nd.cand
        d['split'] = {'column': t.cols[c['j']].name, 'logworth': c['logworth'], 'stat': c['stat'], 'order': nd.order,
                      'children': [ch.path for ch in nd.children],
                      'difference': None if t.L else nd.children[0].mean - nd.children[1].mean}
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
    leaves = t.leaves()
    at = {id(nd): i for i, nd in enumerate(leaves)}
    span = {}

    def walk(nd):
        if nd.children is None:
            span[id(nd)] = (at[id(nd)], at[id(nd)])
        else:
            a = walk(nd.children[0])
            b = walk(nd.children[1])
            span[id(nd)] = (a[0], b[1])
        return span[id(nd)]
    walk(t.root)
    return [_node_json(P, t, nd, *span[id(nd)], at[id(nd)] + 1 if nd.children is None else None) for nd in t.nodes()]


def _summary(P, splits, fit):
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
    return rows


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
    lines = [f'# Partition for {P.y}{f" ({group})" if group else ""}: the report\'s steps replayed from the root',
             'columns = [']
    lines += [f'    {c!r},' for c in t.cols]
    lines.append(']')
    if float(sp['minsize']) < 1:
        lines.append(f'# Minimum Size Split {sp["minsize"]!r}: that share of the training rows, {num_text(ms)} rows')
    lines.append(f'tree = Tree(columns, X, y, {L}, w, cnt, sets, minsize={num_text(ms)}, informative={P.missing == "informative"}'
                 + (f', levels={json.dumps(list(P.labels))})' if L else ')'))
    lines.append(f'tree.run({_py(sp["steps"])})')
    lines.append('print(tree.text())')
    lines.append('for k, r2 in tree.rsquares(tree.fitted()).items():')
    lines.append("    print(['Training', 'Validation', 'Test'][k], 'RSquare', round(r2, 6))")
    return '\n'.join(lines)


SEP = '\n\n# ----\n'


@api('partition.fit')
def fit(table, y, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
        minsize=5, ordinal_order=True, steps=None, group=None, table_name='data'):
    """The tree of the report's steps: its nodes (with every column's best
    split), the Measures of Fit, the summary line, the split history, the
    leaves, the column contributions, and each row's leaf."""
    sp = _spec(y, x, weight, freq, validation, portion, seed, missing, minsize, ordinal_order, steps)
    P, t, ms = _grown(table, rows, sp)
    fitted = t.fitted()
    rep = predictive.report(P, fitted)
    leaves = t.leaves()
    labels = _leaf_labels(t)
    leaf_of = np.zeros(len(P.index), dtype=int)
    for i, nd in enumerate(leaves):
        leaf_of[nd.rows] = i
    leaf_json = []
    for i, nd in enumerate(leaves):
        e = {'number': i + 1, 'path': nd.path, 'label': labels[i], 'count': nd.count, 'w': nd.W}
        if t.L:
            e.update(probs=nd.prob.tolist(), rates=nd.rate.tolist(), counts=nd.n.tolist())
        else:
            e.update(mean=nd.mean, sd=nd.sd)
        leaf_json.append(e)
    hist = [{'splits': i, **{predictive.SETS[k]: v for k, v in h.items()}} for i, h in enumerate(t.history())]
    last = (sp['steps'][-1].get('op') if sp['steps'] else None)
    go = None
    if last == 'go' and t.go_trace:
        g = t.go_trace
        go = {'start': g['start'], 'best': g['best'], 'trace': [{'splits': e['splits'], **{predictive.SETS[k]: e[k] for k in (0, 1, 2) if k in e}} for e in g['trace']]}
    script = SEP.join([_head_code(P, sp, table_name, rows), engine_source(), _fit_code(P, t, sp, ms, group)])
    return {'kind': P.kind, 'y': P.y, 'levels': list(P.labels), 'nodes': _tree_json(P, t), 'leaves': leaf_json,
            'assign': {'rows': P.index.tolist(), 'leaf': leaf_of.tolist(), 'set': P.sets.tolist(), 'y': P.target.tolist()},
            'fit': rep, 'summary': _summary(P, t.splits(), rep), 'history': hist, 'go': go, 'contributions': _contributions(P, t),
            'splits': t.splits(), 'minsize': ms, 'notes': list(t.notes), 'has_validation': bool(P.has(1)),
            'columns': [{'name': c.name, 'kind': c.kind} for c in t.cols], 'method': 'jmp', 'script': script}


@api('partition.save')
def save(table, y, x, rows=None, **kw):
    """Save Predicteds and Save Residuals: every row of the table whose factors the tree can take."""
    P, t, _ = _grown(table, rows, _spec(y, x, **kw))
    return predictive.saved(P, t.predict, t.predict_proba)


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
    k = int(k)
    ntr = int(P.train().sum())
    if not 2 <= k <= ntr:
        raise ValueError(f'the number of folds is from 2 to the number of training rows ({ntr})')
    seed = sp['seed'] if sp['seed'] is not None else 0
    L = len(P.levels) if P.kind == 'categorical' else 0
    pred, fold, per = kfold(t.cols, P.X, P.target, L, P.w, P.freq, P.sets, k, seed, t.splits(), ms, P.missing == 'informative')
    folded, overall = _kfold_measures(P, pred, t)
    lines = [f'# K Fold Crossvalidation{f" ({group})" if group else ""}: {k} folds of the training rows, each tree with the best {t.splits()} splits',
             'columns = [', *[f'    {c!r},' for c in t.cols], ']',
             f'pred, fold, per = kfold(columns, X, y, {L}, w, cnt, sets, k={k}, seed={seed}, splits={t.splits()}, minsize={num_text(ms)}, informative={P.missing == "informative"})',
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
    return {'k': k, 'folds': per, 'folded': folded, 'overall': overall, 'kind': P.kind, 'splits': t.splits(), 'fold': fold.tolist(), 'script': script}


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


def _cart_r2(P, fitted, k):
    m = next((x for x in predictive.measures(P, fitted) if x['set'] == predictive.SETS[k]), None)
    if m is None:
        return math.nan
    v = m['entropy_rsquare'] if P.kind == 'categorical' else m['rsquare']
    return math.nan if v is None else v


def _cart_go(P, n0, n_max, ms, seed, root):
    """Go for CART: a leaf added at a time until the validation RSquare has
    not improved for 10 leaves; the number of leaves with the best."""
    trace, best, k_best = [], None, n0
    k = n0
    while k - k_best <= AHEAD and k <= n_max:
        f = _cart_fitted(P, _cart_model(P, k, ms, seed), root)
        r = _cart_r2(P, f, 1)
        trace.append({'splits': k - 1, **{predictive.SETS[q]: _cart_r2(P, f, q) for q in (0, 1, 2) if P.has(q)}})
        if best is None or r > best + 1e-12:
            best, k_best = r, k
        k += 1
    return k_best, {'start': n0 - 1, 'best': k_best - 1, 'trace': trace}


def _cart_grown(table, rows, sp):
    def build():
        P = _prepared(table, rows, sp, 'onehot')
        ms = min_count(sp['minsize'], P)
        root = _cart_root(P)
        full = _cart_model(P, 2 ** 20, ms, sp['seed'])
        n_max = 1 if full is None else int(full.get_n_leaves())
        n, notes, go = 1, [], None
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
                if not P.has(1):
                    notes.append(f'Step {i + 1} (go) was not done: Go needs validation rows (a Validation column or a validation portion).')
                    continue
                n, go = _cart_go(P, n, n_max, ms, sp['seed'], root)
            else:
                notes.append(f'Step {i + 1} ({op}) was not done: CART grows the whole tree best first, so it splits and prunes the tree, not one node.')
        if sp['steps'] and sp['steps'][-1].get('op') != 'go':
            go = None
        c = Cart(P, _cart_model(P, n, ms, sp['seed']), ms)
        c._root_value, c.notes, c.go = root, notes, go
        return P, c
    return predictive.cached('partition.cart', table, rows, sp, build)


def _cart_nodes(P, c):
    """The fitted tree as the engine's nodes: rows, conditions, statistics."""
    tr_mask = P.train()
    w, cnt = P.weights(), P.counts()
    L = c.L
    model = c.model

    def stats_of(r):
        t = r[tr_mask[r]]
        d = {'count': float(cnt[t].sum()), 'w': float(w[t].sum())}
        if L:
            nvec = np.bincount(P.target[t], weights=w[t], minlength=L)
            rate = nvec / nvec.sum() if nvec.sum() > 0 else np.full(L, 1.0 / L)
            d.update(counts=nvec.tolist(), rates=rate.tolist(), probs=rate.tolist(), g2=float(-2 * _H(nvec, nvec.sum())))
        else:
            yv = P.target[t]
            mean = float(np.sum(w[t] * yv) / w[t].sum())
            ss = float(np.sum(w[t] * (yv - mean) ** 2))
            d.update(mean=mean, ss=ss, sd=math.sqrt(ss / (d['count'] - 1)) if d['count'] > 1 else None)
        return d
    if model is None:
        d = {'path': '', 'parent': None, 'label': 'All Rows', 'leaf': True, 'lo': 0, 'hi': 0, 'number': 1, 'cands': [], 'split': None, **stats_of(np.arange(len(P.index)))}
        return [d], [np.arange(len(P.index))], ['All Rows']
    tr = model.tree_
    path = model.decision_path(P.X).tocsc()
    rows_of = [path[:, i].nonzero()[0] for i in range(tr.node_count)]
    feats = P.features

    def present_levels(name, r):
        """The levels of a nominal X among the training rows r (for the conditions)."""
        idx = P.groups[name]
        t = r[tr_mask[r]]
        return [feats[q][len(name) + 1:-1] for q in idx if P.X[t, q].sum() > 0]

    def labels(i):
        f, thr = int(tr.feature[i]), float(tr.threshold[i])
        name = feats[f]
        col = next(cn for cn in P.x if f in P.groups[cn])
        e = next(e for e in P.enc if e['name'] == col)
        if e['type'] == 'continuous':
            if name.endswith(' Missing') and f != P.groups[col][0]:
                return [f'{col} not Missing', f'{col} Missing']
            return [f'{col}<={thr:.6g}', f'{col}>{thr:.6g}']   # scikit-learn's cut, halfway between two values (shown to 6 digits)
        lev = name[len(col) + 1:-1]
        rest = [x for x in present_levels(col, rows_of[i]) if x != lev]
        return [f'{col}({", ".join(rest)})', f'{col}({lev})']
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

    def rng(i):
        if tr.children_left[i] == -1:
            span[i] = (lat[i], lat[i])
        else:
            a, b = rng(int(tr.children_left[i])), rng(int(tr.children_right[i]))
            span[i] = (a[0], b[1])
        return span[i]
    rng(0)
    by = {}
    for i, p, parent, label in nodes:
        d = {'path': p, 'parent': parent, 'label': label, 'leaf': bool(tr.children_left[i] == -1), 'lo': span[i][0], 'hi': span[i][1],
             'number': lat[i] + 1 if i in lat else None, 'cands': [], 'split': None, **stats_of(rows_of[i])}
        by[p] = d
        out.append(d)
    k = 0
    # the splits' statistics and the order scikit-learn made them in (largest impurity decrease first, as best-first growth does)
    for d in out:
        if not d['leaf']:
            a, b = by[d['path'] + 'L'], by[d['path'] + 'R']
            stat = d['g2'] - a['g2'] - b['g2'] if L else d['ss'] - a['ss'] - b['ss']
            i = next(q for q, p, _, _ in nodes if p == d['path'])
            f = int(tr.feature[i])
            col = next(cn for cn in P.x if f in P.groups[cn])
            d['split'] = {'column': col, 'logworth': None, 'stat': stat, 'order': None, 'children': [a['path'], b['path']],
                          'difference': None if L else a['mean'] - b['mean']}
    inner = sorted((d for d in out if not d['leaf']), key=lambda d: (-d['split']['stat'], len(d['path'])))
    # best first: a node is split only after its parent
    done = {''}
    pending = list(inner)
    while pending:
        nxt = next(d for d in pending if (d['parent'] in done or d['parent'] is None))
        pending.remove(nxt)
        done.add(nxt['path'])
        nxt['split']['order'] = k
        k += 1
    leaf_labels = []
    for i in leaves:
        p = next(pp for q, pp, _, _ in nodes if q == i)
        parts, cur = [], by[p]
        while cur['parent'] is not None:
            parts.append(cur['label'])
            cur = by[cur['parent']]
        leaf_labels.append('&'.join(reversed(parts)) or 'All Rows')
    return out, [rows_of[i] for i in leaves], leaf_labels


def _cart_history(P, c, nodes, leaf_rows):
    """RSquare per set after each split, in best-first order."""
    root = c._root_value
    L = c.L
    by = {d['path']: d for d in nodes}
    tr_rows = {}
    path = c.model.decision_path(P.X).tocsc() if c.model is not None else None
    if c.model is not None:
        walk = []

        def collect(i, p):
            walk.append((i, p))
            if c.model.tree_.children_left[i] != -1:
                collect(int(c.model.tree_.children_left[i]), p + 'L')
                collect(int(c.model.tree_.children_right[i]), p + 'R')
        collect(0, '')
        for i, p in walk:
            tr_rows[p] = path[:, i].nonzero()[0]
    pred = np.tile(root, (len(P.index), 1)) if L else np.full(len(P.index), root)
    out = [{'splits': 0, **{predictive.SETS[q]: _cart_r2(P, pred, q) for q in (0, 1, 2) if P.has(q)}}]
    inner = sorted((d for d in nodes if not d['leaf']), key=lambda d: d['split']['order'])
    for s, d in enumerate(inner, 1):
        for ch in d['split']['children']:
            e = by[ch]
            pred[tr_rows[ch]] = np.array(e['probs']) if L else e['mean']
        out.append({'splits': s, **{predictive.SETS[q]: _cart_r2(P, pred, q) for q in (0, 1, 2) if P.has(q)}})
    return out


def _cart_code(P, c, sp, table_name, rows, group):
    n = 1 if c.model is None else int(c.model.get_n_leaves())
    head = '\n'.join(P.code(table_name, rows, extra_imports=('from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor, export_text',)))
    kind = 'DecisionTreeClassifier(criterion="log_loss", ' if P.kind == 'categorical' else 'DecisionTreeRegressor('
    lines = [f'# Partition for {P.y}{f" ({group})" if group else ""} by CART: {n} leaves, grown best first']
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
def cart_fit(table, y, x, rows=None, group=None, table_name='data', **kw):
    """The report of a CART tree (scikit-learn) with as many leaves as the steps ask for."""
    sp, P, c = _cart_payload(table, y, x, rows, kw)
    nodes, leaf_rows, labels = _cart_nodes(P, c)
    fitted = _cart_fitted(P, c.model, c._root_value)
    rep = predictive.report(P, fitted)
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
    return {'kind': P.kind, 'y': P.y, 'levels': list(P.labels), 'nodes': nodes, 'leaves': leaf_json,
            'assign': {'rows': P.index.tolist(), 'leaf': leaf_of.tolist(), 'set': P.sets.tolist(), 'y': P.target.tolist()},
            'fit': rep, 'summary': _summary(P, splits, rep), 'history': _cart_history(P, c, nodes, leaf_rows), 'go': c.go,
            'contributions': contrib, 'splits': splits, 'minsize': c.ms, 'notes': list(c.notes), 'has_validation': bool(P.has(1)),
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
    k = int(k)
    tr = np.flatnonzero(P.train())
    if not 2 <= k <= len(tr):
        raise ValueError(f'the number of folds is from 2 to the number of training rows ({len(tr)})')
    seed = sp['seed'] if sp['seed'] is not None else 0
    n = 1 if c.model is None else int(c.model.get_n_leaves())
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
    lines = [f'# K Fold Crossvalidation{f" ({group})" if group else ""}: {k} folds of the training rows, each a CART tree of {n} leaves',
             'tr = np.flatnonzero(train)', 'fold = np.full(len(y), -1)',
             f'fold[tr] = np.random.default_rng([{int(seed)}, 2]).permutation(np.arange(len(tr)) % {k})',
             'pred = np.zeros(' + (f'(len(y), {L}))' if L else 'len(y))')]
    kind = 'DecisionTreeClassifier(criterion="log_loss", ' if L else 'DecisionTreeRegressor('
    lines += [f'for f in range({k}):', '    fit_rows = (fold >= 0) & (fold != f)',
              f'    model = {kind}max_leaf_nodes={max(2, n)}, min_samples_leaf={max(1, int(math.ceil(c.ms)))}, random_state={int(seed)})',
              '    model.fit(X[fit_rows], y[fit_rows], sample_weight=None if w is None else w[fit_rows])',
              '    pred[fold == f] = ' + ('model.predict_proba(X[fold == f])   # (every level is in every fold here)' if L else 'model.predict(X[fold == f])'),
              'wt = (np.ones(len(y)) if w is None else w)[train]']
    if not L:
        lines.append("print('Folded RSquare', 1 - np.sum(wt * (y[train] - pred[train]) ** 2) / np.sum(wt * (y[train] - np.average(y[train], weights=wt)) ** 2))")
    head = '\n'.join(P.code(table_name, rows, extra_imports=('from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor',)))
    return {'k': k, 'folds': per, 'folded': folded, 'overall': overall, 'kind': P.kind, 'splits': n - 1, 'fold': fold.tolist(), 'script': SEP.join([head, '\n'.join(lines)])}


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
