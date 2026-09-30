"""Analyze > Consumer Research > Uplift: JMP Pro's uplift tree.

An uplift model finds the rows a treatment helps most: a decision tree grown
as JMP's Partition grows it (partition.py's Tree: Split, Prune, Go, the
splits of one node, the LogWorth adjustment for the cuts a column offers),
each split the column and cut whose split x treatment interaction is the
most significant. JMP documents the test: for a continuous response the F
Ratio of the interaction in the linear model of the response on the split,
the treatment and their interaction; for a categorical one the ChiSquare of
the interaction in the logistic model of the same terms (here its
likelihood-ratio chi-square), the response of interest the response's first
level. The treatment is the Treatment column's first level, the control its
other levels. A node shows each group's mean (or rate) and count, the
treatment's mean less the control's (Trt Diff, the uplift) and its t ratio.

JMP adjusts the p-values by a Monte Carlo calibration it has not published;
the adjustment here is Partition's bound (ordered cuts: the expected
upcrossings of Lausen, Sauerbrei and Schumacher 1994; a nominal X:
Bonferroni over the groupings of its levels, every grouping tried up to 12
levels, else the levels ordered by their uplift and cut between
neighbours).

The summary is that of the regression model the tree is: a mean for each
leaf and group. Go splits until its validation RSquare has not improved for
10 splits and keeps the best tree, as Partition's Go. Beyond JMP: the Qini
curve of each set (Radcliffe's), the rows taken in the order of their
predicted uplift.

The engine (between the ENGINE markers) subclasses partition's Tree and
Node; the code the report shows is partition's engine and this one.
"""
import math

import numpy as np
from scipy import special

from .partition import BINS, Node, Tree, chi2_logsf, f_logsf, num_text

# ==== ENGINE: the uplift tree, Partition's with the split x treatment interaction (numpy and scipy only) ====
MIN_SIZE = 25   # JMP's Minimum Size Split: 25, or the rows over 2000 when that is more


def interaction_f(AL, AR, n):
    """The F ratio of the split x treatment interaction, for each candidate split: in the linear model of the
    response on the split, the treatment and their interaction (weighted least squares), the interaction's
    mean square over the error mean square. AL, AR: each candidate's two sides, columns [W0, W1, S0, S1, Q0,
    Q1]: the weight, the weighted sum and the weighted sum of squares of the response in the control (0) and
    the treatment (1) group; n: the rows (the error degrees of freedom are n - 4). The model with the
    interaction gives each of the four cells its own mean, so the interaction's sum of squares is
    (d_L - d_R)^2 / (1/W0_L + 1/W1_L + 1/W0_R + 1/W1_R), d the treatment's mean less the control's on a side."""
    with np.errstate(divide='ignore', invalid='ignore'):
        dL = AL[:, 3] / AL[:, 1] - AL[:, 2] / AL[:, 0]
        dR = AR[:, 3] / AR[:, 1] - AR[:, 2] / AR[:, 0]
        ss = (dL - dR) ** 2 / (1 / AL[:, 0] + 1 / AL[:, 1] + 1 / AR[:, 0] + 1 / AR[:, 1])
        sse = sum(A[:, 4 + g] - A[:, 2 + g] ** 2 / A[:, g] for A in (AL, AR) for g in (0, 1))
        sse = np.maximum(sse, 0.0)
        tot = ss + sse
        F = np.where(sse > 1e-13 * tot, ss / (sse / (n - 4)), np.where(ss > 1e-13 * tot, np.inf, 0.0))
    return F if n > 4 else np.zeros(len(F))


# the sign of each cell of a 2 x 2 x 2 table [side, treatment, response] in the one direction that keeps
# every two-way margin: moving the table along it changes only the three-way interaction
_SIGN = np.array([(-1.0) ** (s + g + z) for s in (0, 1) for g in (0, 1) for z in (0, 1)])


def interaction_g2(n, iters=80):
    """The likelihood-ratio chi-square of the split x treatment interaction in the logistic model of a binary
    response on the split, the treatment and their interaction, for each candidate split. n: K x 8 weighted
    counts, [side, treatment, response] in the order 000, 001, 010, 011, 100, ... The model with the
    interaction fits every cell (the observed counts); the model without it keeps the three two-way margins
    of the table, which leaves it one free parameter, delta, along the signs +- of the cells: the fit is the
    delta at which the two sides' odds ratios of the treatment are equal (the log of their ratio rises with
    delta, so bisection finds it). The chi-square is 2 sum n log(n / m), m the fit."""
    n = np.asarray(n, dtype=float)
    plus, minus = _SIGN > 0, _SIGN < 0
    lo = -np.min(n[:, plus], axis=1)
    hi = np.min(n[:, minus], axis=1)
    a, b = lo.copy(), hi.copy()
    move = hi > lo
    with np.errstate(divide='ignore', invalid='ignore'):
        for _ in range(iters):
            mid = (a + b) / 2
            f = np.sum(_SIGN * np.log(n + _SIGN * mid[:, None]), axis=1)
            below = f < 0
            a = np.where(move & below, mid, a)
            b = np.where(move & ~below, mid, b)
        delta = np.where(move, (a + b) / 2, 0.0)
        m = n + _SIGN * delta[:, None]
        g2 = 2 * np.sum(special.xlogy(n, n) - special.xlogy(n, np.where(n > 0, m, 1.0)), axis=1)
    return np.maximum(np.where(np.isfinite(g2), g2, 0.0), 0.0)


def group_means(A, binary):
    """Each group's mean (a binary response: its rate of the level of interest) from a node's or a side's
    aggregates (a vector, or rows of them): [control, treatment]."""
    A = np.asarray(A, dtype=float)
    with np.errstate(divide='ignore', invalid='ignore'):
        if binary:
            return A[..., 1] / (A[..., 0] + A[..., 1]), A[..., 3] / (A[..., 2] + A[..., 3])
        return A[..., 2] / A[..., 0], A[..., 3] / A[..., 1]


def uplift_of(A, binary):
    """The treatment's mean (or rate) less the control's, from aggregates (group_means)."""
    m0, m1 = group_means(A, binary)
    return m1 - m0


class UpliftNode(Node):
    """A node of the uplift tree: every row that reaches it (rows), its training rows (tr), their count and
    mean, and for each group, 0 the control and 1 the treatment, its weight (Wg), count (Ng), mean (mg: the
    rate of the level of interest for a categorical response) and sum of squares; diff, the uplift (the
    treatment's mean less the control's), and t, its t ratio (the pooled two-sample t)."""

    def __init__(self, tree, rows, path='', parent=None, label='All Rows'):
        t = tree
        self.tree, self.rows, self.path, self.parent, self.label = t, rows, path, parent, label
        self.tr = rows[t.train[rows]]
        w, c, g, y = t.w[self.tr], t.cnt[self.tr], t.trt[self.tr], t.y[self.tr]
        self.W, self.count = float(w.sum()), float(c.sum())
        self.mean = float(np.sum(w * y) / self.W) if self.W > 0 else math.nan
        self.ss = float(np.sum(w * (y - self.mean) ** 2)) if self.W > 0 else 0.0
        self.Wg, self.Ng, self.mg, self.ssg = [], [], [], []
        for k in (0, 1):
            m = g == k
            Wk = float(w[m].sum())
            mk = float(np.sum(w[m] * y[m]) / Wk) if Wk > 0 else math.nan
            self.Wg.append(Wk)
            self.Ng.append(float(c[m].sum()))
            self.mg.append(mk)
            self.ssg.append(float(np.sum(w[m] * (y[m] - mk) ** 2)) if Wk > 0 else 0.0)
        self.diff = self.mg[1] - self.mg[0]
        df = self.count - 2
        se = math.sqrt((self.ssg[0] + self.ssg[1]) / df * (1 / self.Wg[0] + 1 / self.Wg[1])) if df > 0 and min(self.Wg) > 0 else math.nan
        self.t = self.diff / se if se > 0 else math.nan
        self.value = self.diff
        self.children = None
        self.cand = None      # the split made here
        self.order = None     # when it was made
        self._cands = None
        self.T = None         # the sums of the rows' aggregates (set by the search)


class UpliftTree(Tree):
    """JMP's uplift tree. It grows, prunes and goes as Partition's Tree does; a split is the column and cut
    whose split x treatment interaction has the largest LogWorth: the F test of the interaction in the linear
    model of the response on the split, the treatment and the interaction (a continuous response), or its
    likelihood-ratio chi-square in the logistic model (binary: a categorical response, y 1 for the level of
    interest and 0 for the others). Each side of a split has Minimum Size Split rows and rows of both groups.

    cols, X, w, cnt, sets, informative: as Tree's; y: the response; trt: 1 for a row of the treatment, 0 for
    the control. A leaf predicts each group its mean (its rate); its uplift is the treatment's less the
    control's."""

    node_class = UpliftNode

    def __init__(self, cols, X, y, trt, binary=False, w=None, cnt=None, sets=None, minsize=MIN_SIZE, informative=True):
        self.trt = np.asarray(trt, dtype=int)
        self.binary = bool(binary)
        super().__init__(cols, X, y, 0, w, cnt, sets, minsize, informative)

    def fold_tree(self, sets):
        """An uplift tree of the same rows with a fold's sets (Go by the folds of a K-fold Validation column)."""
        return UpliftTree(self.cols, self.X, self.y, self.trt, self.binary, self.w, self.cnt, sets, self.minsize, self.informative)

    # ---- the split statistic ------------------------------------------------------
    def _splittable(self, node):
        return node.count >= 2 * self.minsize and min(node.Wg) > 0 and node.ss > 0

    def _aggregates(self, node):
        """A row's weight in its group and response cell: control no, yes, treatment no, yes (binary); or its
        weight, weighted deviation from the node's mean and its square in its group, [W0, W1, S0, S1, Q0, Q1]."""
        w, g, y = self.w[node.tr], self.trt[node.tr], self.y[node.tr]
        c, t = w * (1 - g), w * g
        if self.binary:
            A = np.column_stack([c * (1 - y), c * y, t * (1 - y), t * y])
        else:
            yc = y - node.mean
            A = np.column_stack([c, t, c * yc, t * yc, c * yc * yc, t * yc * yc])
        node.T = A.sum(axis=0)
        return A

    def _groups(self, A):
        """The control's and the treatment's weight in aggregates A."""
        return (A[:, 0] + A[:, 1], A[:, 2] + A[:, 3]) if self.binary else (A[:, 0], A[:, 1])

    def _crit(self, node, AL, cL):
        AR, cR = node.T - AL, node.count - cL
        ms = self.minsize - 1e-9
        good = (cL >= ms) & (cR >= ms)
        for v in self._groups(AL) + self._groups(AR):
            good &= v > 1e-12
        if self.binary:
            s = interaction_g2(np.maximum(np.concatenate([AL, AR], axis=1), 0.0))
        else:
            s = interaction_f(AL, AR, node.count)
        s = np.where(np.isnan(s), 0.0, s)
        return np.where(good, np.maximum(s, 0.0), -np.inf), good

    def _logp(self, node, stat):
        """ln p of the interaction's test: chi-square on 1 degree of freedom, or F on 1 and n - 4."""
        if self.binary:
            return chi2_logsf(stat, 1)
        df2 = node.count - 4
        return f_logsf(stat, 1, df2) if df2 > 0 else 0.0

    def _tiny(self, node):
        return 1e-12

    def _dof(self, node):
        return 1

    def _weight_of(self, AL):
        return sum(self._groups(AL))

    def _side_values(self, node, AL):
        """The uplift of each side: the side with the larger one is the first child."""
        return float(uplift_of(AL, self.binary)), float(uplift_of(node.T - AL, self.binary))

    def _extra(self, node, AL):
        """Gamma, the interaction's coefficient in the model the split is tested with, the first side's less
        the other's: of the uplifts (a continuous response), or of the log odds ratios of the treatment (a
        categorical one)."""
        AR = node.T - AL
        a, b = (AL, AR) if uplift_of(AL, self.binary) >= uplift_of(AR, self.binary) else (AR, AL)
        with np.errstate(divide='ignore', invalid='ignore'):
            if self.binary:
                g = math.log(a[3] * a[0] / (a[2] * a[1])) - math.log(b[3] * b[0] / (b[2] * b[1])) if min(a.min(), b.min()) > 0 else math.nan
            else:
                g = float(uplift_of(a, False) - uplift_of(b, False))
        return {'gamma': g if math.isfinite(g) else None}

    def _nominal_keys(self, node, B, u, Lp):
        """Every grouping of up to 12 levels; more levels in the order of their uplift, cut between neighbours
        (a level without one of the groups last)."""
        return None if u <= BINS else [uplift_of(B, self.binary)]

    def _nominal_bound(self, node, B, cb, stat, u, Lp):
        return math.nan     # Scheffe's bound does not hold for an interaction: Bonferroni over the groupings

    # ---- predictions -------------------------------------------------------------------
    def _fill(self, pred, nd):
        """Each row of node nd predicted its group's mean (or rate)."""
        pred[nd.rows] = np.where(self.trt[nd.rows] == 1, nd.mg[1], nd.mg[0])

    def n_params(self, leaves):
        """The regression model the tree is: a mean for each leaf and group, and the error variance."""
        return 2 * leaves + 1

    def difference(self, X):
        """The uplift of each row of X (a predictor matrix like the tree's): its leaf's."""
        return np.array([nd.diff for nd in self.leaves()])[self.leaf_index(X)]

    def predict_groups(self, X):
        """Each row's prediction as a control row and as a treatment row: two columns."""
        return np.array([nd.mg for nd in self.leaves()])[self.leaf_index(X)]

    def uplift_rows(self):
        """The uplift of every row the tree was fitted on: its leaf's."""
        out = np.zeros(len(self.y))
        for nd in self.leaves():
            out[nd.rows] = nd.diff
        return out

    def leaf_rates(self, m):
        """Each leaf's groups' means of the rows m (validation rows, say), and its uplift of them (nan where a
        group has none): [(control mean, treatment mean, uplift, control weight, treatment weight)]."""
        out = []
        for nd in self.leaves():
            r = nd.rows[m[nd.rows]]
            w, g, y = self.w[r], self.trt[r], self.y[r]
            ms, ws = [], []
            for k in (0, 1):
                wk = float(w[g == k].sum())
                ms.append(float(np.sum(w[g == k] * y[g == k]) / wk) if wk > 0 else math.nan)
                ws.append(wk)
            out.append((ms[0], ms[1], ms[1] - ms[0], ws[0], ws[1]))
        return out

    def boxes(self):
        """Every node as the report's tree draws it, parents before children and left before right: its path,
        condition (label), count, each group's mean (or rate), count and weight, the uplift and its t ratio;
        lo and hi, the first and last leaf under it; and the split made there: the column, its LogWorth, its
        statistic (F Ratio or ChiSquare) and Gamma."""
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
            d = {'path': nd.path, 'label': nd.label, 'count': nd.count, 'leaf': nd.children is None, 'lo': span[id(nd)][0], 'hi': span[id(nd)][1],
                 'means': list(nd.mg), 'counts': list(nd.Ng), 'weights': list(nd.Wg), 'diff': nd.diff, 't': nd.t, 'split': None}
            if nd.children:
                c = nd.cand
                d['split'] = {'column': self.cols[c['j']].name, 'logworth': c['logworth'], 'stat': c['stat'], 'gamma': c.get('gamma')}
            out.append(d)
        return out

    def text(self):
        """The tree as lines: each node's condition, each group's count and mean (the control first), the uplift,
        and its split's LogWorth."""
        lines = []
        for nd in self.nodes():
            what = (f'Count {num_text(nd.count)}  control {num_text(nd.Ng[0])} rows, mean {nd.mg[0]:.6g}  treatment {num_text(nd.Ng[1])} rows, '
                    f'mean {nd.mg[1]:.6g}  Trt Diff {nd.diff:.6g}')
            split = f'  | split by {self.cols[nd.cand["j"]].name}, LogWorth {nd.cand["logworth"]:.4f}' if nd.children else ''
            lines.append(f'{"  " * len(nd.path)}{nd.label}  {what}{split}')
        return '\n'.join(lines)


def qini(uplift, y, trt, w=None, m=None):
    """The Qini curve of the rows m (all when None): the rows taken in the order of their predicted uplift,
    highest first, those of one uplift (a leaf) together. After each group, x is the share of the rows' weight
    taken and q the Qini value, (Rt - Rc Nt / Nc) / N: the treatment rows' response (the count of the level of
    interest, or the sum of a continuous response) less the control rows' scaled to the treatment rows' weight
    (0 while no control row is taken), per unit of the rows' weight N (Radcliffe's Qini). Both start at 0.
    Returns x, q and the Qini coefficient: the area between the curve and the straight line to its end (the
    rows taken at random)."""
    uplift, y, trt = (np.asarray(v, dtype=float) for v in (uplift, y, trt))
    w = np.ones(len(y)) if w is None else np.asarray(w, dtype=float)
    m = np.ones(len(y), dtype=bool) if m is None else np.asarray(m, dtype=bool)
    u, yy, g, ww = uplift[m], y[m], trt[m], w[m]
    N = float(ww.sum())
    if not N > 0:
        return [0.0], [0.0], None
    x, q = [0.0], [0.0]
    Rt = Rc = Nt = Nc = taken = 0.0
    for v in sorted(set(u.tolist()), reverse=True):
        k = u == v
        Rt += float(np.sum((ww * yy * g)[k]))
        Rc += float(np.sum((ww * yy * (1 - g))[k]))
        Nt += float(np.sum((ww * g)[k]))
        Nc += float(np.sum((ww * (1 - g))[k]))
        taken += float(ww[k].sum())
        x.append(taken / N)
        q.append((Rt - Rc * Nt / Nc) / N if Nc > 0 else 0.0)
    area = float(np.sum(np.diff(x) * (np.array(q[1:]) + np.array(q[:-1])) / 2))
    return x, q, area - q[-1] / 2
# ==== END OF ENGINE ====

import inspect  # noqa: E402
import json  # noqa: E402

from . import data, partition, predictive  # noqa: E402
from .registry import api  # noqa: E402
from .util import formula_num, formula_ref, one_line  # noqa: E402

SEP = partition.SEP
_ENGINE = None


def engine_source():
    """This engine's code (it follows partition's), as the report shows it."""
    global _ENGINE
    if _ENGINE is None:
        with open(__file__, encoding='utf-8') as fh:
            text = fh.read()
        a, b = text.index('# ==== ENGINE'), text.index('# ==== END OF ENGINE')
        _ENGINE = text[a:b].rstrip() + '\n'
    return _ENGINE


# ---------------------------------------------------------------------------
# the report's tree
# ---------------------------------------------------------------------------

def _spec(y=None, treatment=None, x=(), weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
          minsize=None, ordinal_order=True, steps=None, treat_level=None, response_level=None, **_ignored):
    """Everything that decides the tree (the key of the model cache)."""
    return {'y': y, 'treatment': treatment, 'x': list(x or []), 'weight': weight, 'freq': freq, 'validation': validation,
            'portion': float(portion or 0), 'seed': predictive.seed_of(seed), 'missing': 'drop' if missing in (False, 'drop') else 'informative',
            'minsize': None if minsize in (None, '') else float(minsize), 'ordinal_order': bool(ordinal_order),
            'steps': [dict(s) for s in (steps or [])], 'treat_level': None if treat_level in (None, '') else str(treat_level),
            'response_level': None if response_level in (None, '') else str(response_level)}


def _value(v):
    return v.item() if hasattr(v, 'item') else v


def _prepared(table, rows, sp):
    """The prepared data (ordinal coding, Partition's) of the rows with a treatment, and U: the groups (trt 1 for
    the treatment, 0 for the control), the Treatment's levels, the response (a number; a categorical one as 1 for
    its level of interest, 0 for the others)."""
    y, tcol, x = sp['y'], sp['treatment'], list(sp['x'])
    if not tcol:
        raise ValueError('choose a Treatment column')
    if tcol == y or tcol in x or tcol in (sp['weight'], sp['freq'], sp['validation']):
        raise ValueError(f'{tcol} is the Treatment: it cannot be the response, a factor or a Weight, Freq or Validation column too')
    if not data.is_categorical(table, tcol):
        raise ValueError(f'{tcol}: the Treatment is a nominal or ordinal column (its first level is the treatment)')
    tf = data.frame(table, [tcol], rows, dropna=False)
    ok = tf[tcol].notna().to_numpy()
    use = None if (rows is None and ok.all()) else [int(r) for r in np.asarray(tf.index)[ok]]
    if use is not None and not use:
        raise ValueError(f'no rows with a value of {tcol}')
    P = predictive.prepare(table, y, x, rows=use, weight=sp['weight'], freq=sp['freq'], validation=sp['validation'],
                           portion=sp['portion'], seed=sp['seed'], missing=sp['missing'], coding='ordinal')
    if (~ok).sum():
        P.notes.insert(0, f'{int((~ok).sum())} rows with no {tcol} are left out.')
    tv = data.frame(table, [tcol], P.index.tolist(), dropna=False)[tcol]
    cats = list(tv.cat.categories)
    codes = tv.cat.codes.to_numpy()
    present = [j for j in range(len(cats)) if np.any(codes == j)]
    keys = [predictive.level_label(_value(cats[j])) for j in present]           # a level as the options name it
    names = [partition._shown_level(table, tcol, _value(cats[j])) for j in present]   # ... as the page shows it
    if len(present) < 2:
        raise ValueError(f'{tcol} has one level in these rows: an uplift needs a treatment and a control')
    k = keys.index(sp['treat_level']) if sp['treat_level'] in keys else 0
    trt = (codes == present[k]).astype(int)
    U = {'treatment': tcol, 'keys': keys, 'levels': names, 'treat_key': keys[k], 'treat': names[k], 'treat_value': _value(cats[present[k]]),
         'control': [lab for i, lab in enumerate(names) if i != k], 'trt': trt, 'binary': P.kind == 'categorical',
         'numeric_levels': all(isinstance(_value(cats[j]), (int, float)) for j in present)}
    if P.kind == 'categorical':
        rkeys = [predictive.level_label(v) for v in P.levels]
        want = sp['response_level']
        r = rkeys.index(want) if want in rkeys else P.labels.index(want) if want in P.labels else 0
        U.update(interest=partition._shown_level(table, y, P.levels[r]), interest_key=rkeys[r], response_keys=rkeys,
                 response_names=[partition._shown_level(table, y, v) for v in P.levels], interest_index=r, y=(P.target == r).astype(float))
    else:
        U.update(interest=None, interest_key=None, response_keys=[], response_names=[], interest_index=None, y=np.asarray(P.target, dtype=float))
    tr = P.train()
    for g, name in ((1, f'the treatment ({U["treat"]})'), (0, 'the control')):
        if not np.any(trt[tr] == g):
            raise ValueError(f'the training rows have no row of {name}: an uplift needs both groups')
    return P, U


def min_count(minsize, P):
    """Minimum Size Split as a count: JMP's default is 25, or the training rows over 2000 when that is more; a
    value below 1 is a share of the training rows."""
    if minsize is None:
        return float(max(MIN_SIZE, math.floor(P.counts(P.train()).sum() / 2000)))
    return partition.min_count(minsize, P)


def _grown(table, rows, sp):
    """The prepared data, the groups and the tree with the report's steps, remembered."""
    def build():
        P, U = _prepared(table, rows, sp)
        ms = min_count(sp['minsize'], P)
        t = UpliftTree(partition.columns_of(P, sp['ordinal_order']), P.X, U['y'], U['trt'], U['binary'], P.w, P.freq, P.sets, ms, P.missing == 'informative')
        t.folds = partition.fold_index(P)
        t.run(sp['steps'])
        return P, U, t, ms
    return predictive.cached('uplift', table, rows, sp, build)


def _node_json(t, nd, box):
    """A node of the report: what the tree draws of it (UpliftTree.boxes), its parent, leaf number and weight,
    the split's order and children, and every column's best split there."""
    d = dict(box, parent=nd.parent.path if nd.parent is not None else None, w=nd.W, number=box['lo'] + 1 if box['leaf'] else None)
    if nd.children:
        d['split'] = dict(box['split'], order=nd.order, children=[ch.path for ch in nd.children])
    best = nd.best()
    cands = []
    for j, c in enumerate(nd.candidates()):
        name = t.cols[j].name
        if c is None:
            cands.append({'column': name, 'stat': None, 'logworth': None, 'gamma': None, 'split': '', 'other': '', 'best': False})
        else:
            cands.append({'column': name, 'stat': c['stat'], 'logworth': c['logworth'], 'gamma': c.get('gamma'), 'split': c['labels'][c['first']],
                          'other': c['labels'][1 - c['first']], 'best': c is best})
    d['cands'] = cands
    return d


def _set_stats(P, t, pred, k, leaves):
    """The summary of set k: RSquare, RMSE (the training rows: of the regression model the tree is, over its
    error degrees of freedom; the others: the root mean squared error of the prediction) and N."""
    m = P.sets == k
    w = t.w[m]
    y = t.y[m]
    N = float(w.sum())
    sse = float(np.sum(w * (y - pred[m]) ** 2))
    sst = float(np.sum(w * (y - np.sum(w * y) / N) ** 2)) if N > 0 else 0.0
    n = float(t.cnt[m].sum())
    dfe = n - t.n_params(leaves) + 1
    rmse = math.sqrt(sse / dfe) if k == 0 and dfe > 0 else math.sqrt(sse / N) if k != 0 and N > 0 else None
    return {'set': predictive.SETS[k], 'rsquare': 1 - sse / sst if sst > 0 else None, 'rmse': rmse, 'n': n}


def _summary(P, t, pred):
    nl = len(t.leaves())
    rows = [_set_stats(P, t, pred, k, nl) for k in range(3) if P.has(k)]
    rows[0].update(splits=t.splits(), aicc=t.aicc(pred, nl))
    return rows


def _group_label(U):
    """The control group's name: its level, or its levels joined."""
    return U['control'][0] if len(U['control']) == 1 else ', '.join(U['control'])


def _head_lines(P, U, table_name, rows, freq, graph=False):
    """The lines that read the table and build d, X, y, w, sets, trt and cnt as the report does."""
    L = P.code(table_name, rows, extra_imports=[predictive.PLT] if graph else [])
    tq = json.dumps(U['treatment'])
    for i, line in enumerate(L):
        if line.startswith('d = df['):
            sp = P.spec
            cols = list(dict.fromkeys([P.y] + list(P.x) + [U['treatment']] + [c for c in (sp.get('weight'), sp.get('freq'), sp.get('validation')) if c]))
            L[i:i + 1] = [f'd = df[{json.dumps(cols)}]', f'd = d[d[{tq}].notna()]   # rows with a treatment']
            break
    if U['numeric_levels']:
        src = f'pd.to_numeric(d[{tq}], errors="coerce") == {formula_num(U["treat_value"])}'
    else:
        src = f'd[{tq}].astype(str) == {json.dumps(str(U["treat_value"]))}'
    L.append(f'trt = ({src}).to_numpy(int)   # 1: the treatment ({one_line(U["treat"])}, {"the first level" if U["treat_key"] == U["keys"][0] else "a level"} of {U["treatment"]}), 0: the control ({one_line(_group_label(U))})')
    if U['binary']:
        L.append(f'y = (y == {U["interest_index"]}).astype(float)   # 1: {one_line(U["interest"])}, the level of interest; 0: the other levels')
    L.append(f'cnt = d[{json.dumps(freq)}].to_numpy(float)   # the frequencies: the minimum size and the degrees of freedom count them'
             if freq else 'cnt = None   # every row counts once')
    return L


def _fit_lines(P, U, t, sp, ms, group):
    L = [f'# Uplift for {P.y}{f" ({one_line(group)})" if group else ""}: the report\'s steps replayed from the root', 'columns = [']
    L += [f'    {c!r},' for c in t.cols]
    L.append(']')
    if sp['minsize'] is None:
        L.append(f'# Minimum Size Split: JMP\'s default, 25 or the training rows over 2000: {num_text(ms)} rows')
    elif float(sp['minsize']) < 1:
        L.append(f'# Minimum Size Split {sp["minsize"]!r}: that share of the training rows, {num_text(ms)} rows')
    L.append(f'tree = UpliftTree(columns, X, y, trt, binary={U["binary"]}, w=w, cnt=cnt, sets=sets, minsize={num_text(ms)}, informative={P.missing == "informative"})')
    if P.folds is not None:
        L.append(f'tree.folds = folds   # the {P.k} folds of {sp["validation"]}: Go crossvalidates by them')
    L.append(f'tree.run({partition._py(sp["steps"])})')
    return L


def _script(P, U, t, sp, ms, group, table_name, rows):
    tail = _fit_lines(P, U, t, sp, ms, group) + [
        'print(tree.text())',
        'for k, r2 in tree.rsquares(tree.fitted()).items():',
        "    print(['Training', 'Validation', 'Test'][k], 'RSquare', round(r2, 6))"]
    return SEP.join(['\n'.join(_head_lines(P, U, table_name, rows, sp['freq'])), partition.engine_source(), engine_source(), '\n'.join(tail)])


def _graph_head(P, U, t, sp, ms, group, table_name, rows):
    """The head of every graph's code: the table and the tree the engine grows, then fitted (each row's group's
    mean in its leaf), uplift (each row's leaf's), leaf (each row's leaf, from the left from 0) and nodes."""
    tail = _fit_lines(P, U, t, sp, ms, group) + [
        'fitted = tree.fitted()   # each row\'s prediction: its group\'s mean (or rate) in its leaf',
        'uplift = tree.uplift_rows()   # each row\'s uplift: its leaf\'s Trt Diff',
        'leaf = np.zeros(len(y), dtype=int)   # each row\'s leaf, numbered from the left from 0',
        'for i, nd in enumerate(tree.leaves()):',
        '    leaf[nd.rows] = i',
        'nodes = tree.boxes()   # every node as the tree draws it']
    return SEP.join(['\n'.join(_head_lines(P, U, table_name, rows, sp['freq'], graph=True)), partition.engine_source(), engine_source(), '\n'.join(tail)])


# ---------------------------------------------------------------------------
# the graphs as matplotlib code: the head grows the tree; each tail draws one
# graph from it (the page's display choices come in plot)
# ---------------------------------------------------------------------------
TREAT, CONTROL = '#c0392b', predictive.BASE           # JMP's red and blue lines: the treatment, the control (light theme)
SET_COLORS = {0: predictive.BASE, 1: '#b8641d', 2: '#3a7d44'}


def _model_tail(P, U, plot):
    """The uplift model's graph: each leaf's training rows, the treatment's and then the control's, each part as
    wide as its rows, with the group's mean (or rate) across it."""
    J = json.dumps
    points = plot.get('points', True) is not False
    n = int(P.train().sum())
    L = ['leaves = [nd for nd in nodes if nd["leaf"]]   # left to right',
         'parts = [(l, g, np.flatnonzero((leaf == l) & train & (trt == g))) for l in range(len(leaves)) for g in (1, 0)]   # each leaf\'s treatment rows, then its control rows',
         'edges = np.r_[0, np.cumsum([len(r) for _, _, r in parts])] / sum(len(r) for _, _, r in parts)   # each part as wide as its rows',
         f'colors = {{1: "{TREAT}", 0: "{CONTROL}"}}   # the treatment, the control',
         f'names = {{1: {J(U["treat"])}, 0: {J(_group_label(U))}}}',
         predictive.figure(560, 300)]
    if not U['binary']:
        size = 3.5 if n > 1500 else 5
        if points:
            L += ['for i, (l, g, r) in enumerate(parts):',
                  '    lo, hi = edges[i], edges[i + 1]',
                  f'    ax.scatter(lo + (np.arange(len(r)) + 0.5) / max(len(r), 1) * (hi - lo), y[r], s={size * size * 0.55:g}, color=colors[g], label=names[g] if i < 2 else None)   # the rows evenly across the part']
        L += ['for i, (l, g, r) in enumerate(parts):',
              '    m = leaves[l]["means"][g]   # the group\'s mean in the leaf',
              '    ax.plot([edges[i], edges[i + 1]], [m, m], color=colors[g], linewidth=2.2' + (')' if points else ', label=names[g] if i < 2 else None)'),
              f'ax.set_ylabel({J(P.y)})']
    else:
        size = 3 if n > 1500 else 4.5
        L += ['for i, (l, g, r) in enumerate(parts):',
              '    rate = leaves[l]["means"][g]   # the group\'s rate of the level of interest in the leaf',
              f'    ax.bar((edges[i] + edges[i + 1]) / 2, rate, width=max(edges[i + 1] - edges[i], 1e-6), color=colors[g], alpha={0.28 if points else 0.8}, linewidth=0, label=names[g] if i < 2 else None)',
              '    ax.plot([edges[i], edges[i + 1]], [rate, rate], color=colors[g], linewidth=2.2)']
        if points:
            L += ['rng = np.random.default_rng(1)   # each row at random in its part: the level of interest under the rate, the others above it (the page\'s own random numbers differ)',
                  'for i, (l, g, r) in enumerate(parts):',
                  '    lo, hi, rate = edges[i], edges[i + 1], leaves[l]["means"][g]',
                  '    yes = y[r] == 1',
                  '    yy = np.where(yes, (0.1 + 0.8 * rng.uniform(size=len(r))) * rate, rate + (0.1 + 0.8 * rng.uniform(size=len(r))) * (1 - rate))',
                  f'    ax.scatter(lo + (0.08 + 0.84 * rng.uniform(size=len(r))) * (hi - lo), yy, s={size * size * 0.55:g}, color=colors[g])']
        L += ['ax.set_ylim(0, 1)', f'ax.set_ylabel({J(P.y + ": rate of " + str(U["interest"]))})']
    L += ['leaf_edges = [edges[2 * l] for l in range(1, len(leaves))]',
          'for e in leaf_edges:',
          f'    ax.axvline(e, color="{predictive.MUTED}", linewidth=1, linestyle=":")   # the leaves\' edges',
          'centers = [(edges[2 * l] + edges[2 * l + 2]) / 2 for l in range(len(leaves))]',
          'ax.set_xlim(0, 1)',
          'if len(leaves) <= 40:',
          '    ax.set_xticks(centers, [str(l + 1) for l in range(len(leaves))])   # the Leaf Report\'s numbers',
          'else:',
          '    ax.set_xticks([])',
          'ax.set_xlabel("Leaves: the treatment, then the control")',
          f'ax.set_title({J("Uplift model of " + P.y)}, wrap=True)',
          'fig.legend(loc="outside upper left", ncols=2, frameon=False, fontsize=8)',
          'plt.show()']
    return '\n'.join(L)


def draw_uplift_tree(nodes, groups, binary=False, stats=True, count=True, title='Uplift tree'):
    """The uplift tree as the report draws it (smui-p-uplift.js), with matplotlib: a box per node, the parents
    above their children and the leaves side by side from the left, joined by elbow lines. A box shows the
    node's condition, a line per group (the treatment's first): its mean (or rate) and count; and the t Ratio,
    the Trt Diff (the uplift) and the split's LogWorth. groups: the treatment's and the control's names. The
    sizes are the page's, in pixels at 100 an inch; stats and count are its Show Split Stats and Show Split
    Count."""
    import math
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle
    ink, second, muted, border, surface, band = '#352921', '#6b5d4f', '#786b5d', '#e0d7ce', '#fcf7f2', '#f6efe8'
    colors = ['#c0392b', '#2f6690']   # the treatment, the control
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

    def val(v):
        """A mean, a rate or an uplift as the box writes it: 4 decimals for a rate, else 6 digits."""
        if v is None or v != v:
            return '.'
        return (f'{v:.4f}'.replace('-', '−') if binary else fmt(v, 6))

    def clip(s, px, cw=6.4):
        n = max(3, int(px // cw))
        s = str(s)
        return s[:n - 1] + '…' if len(s) > n else s

    def at(v):
        return math.floor(v + 0.5)   # a pixel, rounded as the page rounds
    TITLE, ROW, GAP, VGAP, PAD = 20, 14, 14, 28, 6
    level_w = max(60, min(110, at(6.3 * max([9] + [len(str(g)) for g in groups])) + 8))
    num_w, cnt_w = 58, (46 if count else 0)
    BW = max(184, 10 + level_w + num_w + cnt_w)

    def height(nd):
        return TITLE + PAD + ROW * 3 + ROW * ((3 if nd['split'] else 2) if stats else 1) + 6

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
    top = 30 if title else 0
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
        ax.add_patch(Rectangle((x + 0.5, y0 + 0.5), BW - 1, TITLE - 0.5, facecolor=band, edgecolor='none'))   # the heading
        ax.text(x + 18, y0 + TITLE - 6, clip(nd['label'], BW - 24, 7.1), fontsize=11 * pt, fontweight='bold', color=ink)
        yy = y0 + TITLE + PAD + ROW - 3
        x_num = x + 7 + level_w + num_w - 4
        x_cnt = x + 7 + level_w + num_w + cnt_w - 4
        ax.text(x + 7, yy, 'Treatment', fontsize=9.5 * pt, color=muted)
        ax.text(x_num, yy, 'Rate' if binary else 'Mean', fontsize=9.5 * pt, color=muted, ha='right')
        if count:
            ax.text(x_cnt, yy, 'Count', fontsize=9.5 * pt, color=muted, ha='right')
        yy += ROW
        for g, name in ((1, groups[0]), (0, groups[1])):   # the treatment first
            ax.add_patch(Rectangle((x + 7, yy - 8), 3, 8, facecolor=colors[1 - g], edgecolor='none'))
            ax.text(x + 13, yy, clip(name, level_w - 8), fontsize=10.5 * pt, color=second)
            ax.text(x_num, yy, val(nd['means'][g]), fontsize=10.5 * pt, color=ink, ha='right')
            if count:
                ax.text(x_cnt, yy, fmt(nd['counts'][g]), fontsize=10.5 * pt, color=ink, ha='right')
            yy += ROW
        rows = ([('t Ratio', fmt(nd['t'], 4))] if stats else []) + [('Trt Diff', val(nd['diff']))]
        if stats and nd['split']:
            rows.append(('LogWorth', fmt(nd['split']['logworth'], 6)))
        for k, v in rows:
            ax.text(x + 7, yy, k, fontsize=10.5 * pt, color=second)
            ax.text(x + BW - 7, yy, v, fontsize=10.5 * pt, color=ink, ha='right')
            yy += ROW
    return fig, ax


def _tree_tail(U, plot):
    src = inspect.getsource(draw_uplift_tree).rstrip()
    call = (f'draw_uplift_tree(nodes, {json.dumps([U["treat"], _group_label(U)])}, binary={U["binary"]}, stats={plot.get("stats", True) is not False}, '
            f'count={plot.get("count", True) is not False})   # the page\'s Show Split options')
    return '\n'.join([src, '', '', call, 'plt.show()'])


def _uplift_graph_tail(P, U):
    """The Uplift Graph: each leaf's uplift as a bar as wide as its share of the training rows, the largest uplift
    first; with validation rows, the leaf's uplift on them as a black line across its bar."""
    L = ['leaves = [nd for nd in nodes if nd["leaf"]]',
         'order = sorted(range(len(leaves)), key=lambda l: -leaves[l]["diff"])   # the largest uplift first',
         'share = np.array([leaves[l]["count"] for l in order]) / sum(nd["count"] for nd in leaves)   # each leaf\'s share of the training rows',
         'left = np.r_[0, np.cumsum(share)[:-1]]',
         predictive.figure(460, 300),
         f'ax.bar(left + share / 2, [leaves[l]["diff"] for l in order], width=share, color="{predictive.BAR}", edgecolor="#fcf7f2", linewidth=1)']
    if P.has(1):
        L += ['wt = np.ones(len(y)) if w is None else w',
              'for i, l in enumerate(order):   # the leaf\'s uplift on its validation rows',
              '    r = (leaf == l) & (sets == 1)',
              '    t1, t0 = r & (trt == 1), r & (trt == 0)',
              '    if wt[t1].sum() > 0 and wt[t0].sum() > 0:',
              '        v = np.sum(wt[t1] * y[t1]) / wt[t1].sum() - np.sum(wt[t0] * y[t0]) / wt[t0].sum()',
              '        ax.plot([left[i], left[i] + share[i]], [v, v], color="#1c1c1c", linewidth=2)']
    L += [f'ax.axhline(0, color="{predictive.MUTED}", linewidth=1)',
          'ax.set_xlim(0, 1)',
          'ax.set_xticks([left[i] + share[i] / 2 for i in range(len(order))], [str(l + 1) for l in order])   # the leaves\' numbers',
          'ax.set_xlabel("Leaves by uplift (width: the share of the rows)")',
          'ax.set_ylabel("Uplift (Trt Diff)")',
          'ax.set_title("Uplift graph")',
          'plt.show()']
    return '\n'.join(L)


def _qini_tail(P):
    sets = [k for k in range(3) if P.has(k)]
    return '\n'.join([
        'def num(v, sig=4):',
        '    """A number as the report writes it: sig significant digits (an exponent below 1e-4), a true minus sign."""',
        '    if v != 0 and (abs(v) >= 1e9 or abs(v) < 1e-4):',
        '        m, e = f"{v:.{sig - 1}e}".split("e")',
        '        s = f"{m}e{int(e)}"',
        '    else:',
        '        s = f"{v:.{sig}g}"',
        '        if "e" in s:',
        '            s = repr(float(s))',
        '        if "." in s:',
        '            s = s.rstrip("0").rstrip(".")',
        '    return "−" + s[1:] if s.startswith("-") else s',
        '',
        '',
        f'sets_shown = {json.dumps([[k, predictive.SETS[k]] for k in sets])}',
        f'colors = {json.dumps({str(k): SET_COLORS[k] for k in sets})}',
        predictive.figure(420, 320),
        'for k, name in sets_shown:',
        '    qx, qy, coef = qini(uplift, y, trt, w, sets == k)   # the rows by their leaf\'s uplift, highest first',
        '    ax.plot(qx, qy, color=colors[str(k)], linewidth=1.8, marker="o", markersize=3, label=f"{name} (Qini {num(coef)})")',
        '    ax.plot([0, 1], [0, qy[-1]], color=colors[str(k)], linewidth=1, linestyle=":")   # the rows taken at random',
        'ax.set_xlim(0, 1)',
        'ax.set_xlabel("Portion of the rows (the highest predicted uplift first)")',
        'ax.set_ylabel("Qini: incremental response per row")',
        'ax.set_title("Qini curve")',
        'ax.legend(frameon=False, fontsize=8)',
        'plt.show()'])


def _plots(P, U, plot, go):
    return {'graph': _model_tail(P, U, plot), 'tree': _tree_tail(U, plot), 'upliftgraph': _uplift_graph_tail(P, U),
            'history': partition._history_tail(P, go, ylabel='RSquare'), 'aicc': partition._aicc_tail(), 'qini': _qini_tail(P),
            'contrib': '\n'.join(partition._contrib_lines(P) + predictive.contribution_lines(len(P.x), 'Column Uplift Contributions'))}


# ---------------------------------------------------------------------------
# the report
# ---------------------------------------------------------------------------

@api('uplift.fit')
def fit(table, y, treatment, x, rows=None, weight=None, freq=None, validation=None, portion=0.0, seed=None, missing='informative',
        minsize=None, ordinal_order=True, steps=None, treat_level=None, response_level=None, group=None, plot=None, table_name='data'):
    """The uplift tree of the report's steps: its nodes (each group's mean and count, the uplift and its t ratio,
    every column's best split), the summary, the leaves (their rules, and each group's mean on the validation
    and test rows), the split history, the Uplift Graph, the Qini curves, the column contributions, each row's
    leaf and group, the code, and the graphs' code. plot: the page's display choices (points, stats, count)."""
    sp = _spec(y, treatment, x, weight, freq, validation, portion, seed, missing, minsize, ordinal_order, steps, treat_level, response_level)
    P, U, t, ms = _grown(table, rows, sp)
    fitted = t.fitted()
    leaves = t.leaves()
    labels, rules = partition._leaf_labels(t), partition.leaf_rules(t)
    leaf_of = np.zeros(len(P.index), dtype=int)
    for i, nd in enumerate(leaves):
        leaf_of[nd.rows] = i
    other = {k: t.leaf_rates(P.sets == k) for k in (1, 2) if P.has(k)}
    leaf_json = []
    for i, nd in enumerate(leaves):
        e = {'number': i + 1, 'path': nd.path, 'label': labels[i], 'rule': rules[i], 'count': nd.count, 'w': nd.W,
             'means': list(nd.mg), 'counts': list(nd.Ng), 'diff': nd.diff, 't': nd.t}
        for k, rates in other.items():
            e[predictive.SETS[k].lower()] = {'means': list(rates[i][:2]), 'diff': rates[i][2], 'weights': list(rates[i][3:])}
        leaf_json.append(e)
    uplift = t.uplift_rows()
    qini_out = []
    for k in range(3):
        if P.has(k):
            qx, qy, coef = qini(uplift, t.y, t.trt, P.w, P.sets == k)
            qini_out.append({'set': predictive.SETS[k], 'x': qx, 'q': qy, 'coef': coef})
    hist = partition._history_rows(t.history())
    last = sp['steps'][-1].get('op') if sp['steps'] else None
    go = None
    if last == 'go' and t.go_trace:
        g = t.go_trace
        go = {'start': g['start'], 'best': g['best'], 'folds': g.get('folds'),
              'trace': [{'splits': e['splits'], **{predictive.SETS[k]: e[k] for k in (0, 1, 2) if k in e}, **({'Crossvalidation': e['cv']} if 'cv' in e else {})} for e in g['trace']]}
    vals = np.zeros(len(P.features))
    nsplit = {c: 0 for c in P.x}
    for nd in t.nodes():
        if nd.children:
            name = t.cols[nd.cand['j']].name
            vals[P.groups[name][0]] += nd.cand['stat']
            nsplit[name] += 1
    contrib = predictive.contributions(P, vals, 'ChiSquare' if U['binary'] else 'F Ratio')
    for r in contrib['rows']:
        r['splits'] = nsplit[r['column']]
    head = _graph_head(P, U, t, sp, ms, group, table_name, rows)
    plots = dict(_plots(P, U, plot or {}, go is not None), head_code=head)
    contrib['plot_code'] = plots.pop('contrib')
    notes = list(P.notes) + list(t.notes)
    threshold = None
    if U['binary'] and len(P.labels) == 2 and hasattr(predictive, 'threshold'):
        # the Decision Threshold of the probabilities: each row's group's rate of the level of interest in its leaf
        r = U['interest_index']
        prob = np.column_stack([fitted, 1 - fitted] if r == 0 else [1 - fitted, fitted])
        select = [f'y = {"(1 - y)" if r == 0 else "y"}.astype(int)   # each row\'s level: 0 {P.labels[0]}, 1 {P.labels[1]}',
                  f'fitted = np.column_stack({"[fitted, 1 - fitted]" if r == 0 else "[1 - fitted, fitted]"})   # each row\'s probability of each level']
        threshold = predictive.threshold(P.target, prob, list(P.labels), P.sets, P.w, P.index, head=head, select=select, values=P.levels)
        threshold['target'] = r   # the level of interest is the target at first
    return {'kind': P.kind, 'y': P.y, 'binary': U['binary'], 'interest': U['interest'], 'levels': list(P.labels),
            'treatment': U['treatment'], 'treat': U['treat'], 'control': U['control'], 'control_label': _group_label(U), 'treatment_levels': U['levels'],
            'treat_key': U['treat_key'], 'treatment_keys': U['keys'], 'interest_key': U['interest_key'], 'response_keys': U['response_keys'],
            'response_names': U['response_names'],
            'nodes': [_node_json(t, nd, box) for nd, box in zip(t.nodes(), t.boxes())], 'leaves': leaf_json,
            'assign': {'rows': P.index.tolist(), 'leaf': leaf_of.tolist(), 'set': P.sets.tolist(), 'y': t.y.tolist(), 'trt': t.trt.tolist()},
            'summary': _summary(P, t, fitted), 'history': hist, 'go': go, 'qini': qini_out, 'contributions': contrib,
            'splits': t.splits(), 'minsize': ms, 'minsize_default': sp['minsize'] is None, 'notes': notes, 'has_validation': bool(P.has(1)), 'folds': partition._folds_json(P),
            'sets': [predictive.SETS[k] for k in range(3) if P.has(k)],
            'columns': [{'name': c.name, 'kind': c.kind} for c in t.cols], 'plots': plots, 'threshold': threshold,
            'script': _script(P, U, t, sp, ms, group, table_name, rows)}


def _scored(table, rows, kw):
    """The tree, and every row of the table whose factors it can take: X, the row numbers, and each one's group
    (1 the treatment, 0 the control, -1 no treatment)."""
    sp = _spec(**kw)
    P, U, t, ms = _grown(table, rows, sp)
    X, rws = P.all_rows()
    tv = data.frame(table, [U['treatment']], rws.tolist(), dropna=False)[U['treatment']].astype(object)
    g = np.array([-1 if (v is None or (isinstance(v, float) and math.isnan(v))) else int(predictive.level_label(_value(v)) == U['treat_key']) for v in tv], dtype=int)
    return P, U, t, X, rws, g


@api('uplift.save')
def save(table, rows=None, what='difference', **kw):
    """Save Difference (every row whose factors the tree can take: its leaf's uplift), or Save Predicteds (a row
    with a treatment: its group's mean, or rate, in its leaf)."""
    P, U, t, X, rws, g = _scored(table, rows, kw)
    if what == 'difference':
        return {'rows': rws.tolist(), 'values': t.difference(X).tolist(), 'name': f'Difference {P.y}'}
    m = g >= 0
    pg = t.predict_groups(X[m])
    pred = np.where(g[m] == 1, pg[:, 1], pg[:, 0])
    if not U['binary']:
        return {'rows': rws[m].tolist(), 'values': pred.tolist(), 'name': f'Predicted {P.y}'}
    r = U['interest_index']
    if len(P.labels) == 2:   # both levels' probabilities and the most likely level, as the predictive platforms save them
        prob = np.column_stack([pred, 1 - pred] if r == 0 else [1 - pred, pred])
        return {'rows': rws[m].tolist(), 'prob': prob.tolist(), 'levels': list(P.labels), 'names': [f'Prob[{lab}]' for lab in P.labels],
                'most_likely': [P.labels[int(j)] for j in np.argmax(prob, axis=1)], 'most_name': f'Most Likely {P.y}',
                'ordinal': data.meta(P.table, P.y).get('modelingType') == 'ordinal'}
    return {'rows': rws[m].tolist(), 'prob': pred[:, None].tolist(), 'levels': list(P.labels), 'names': [f'Prob[{P.labels[r]}]']}


@api('uplift.formula')
def formula(table, rows=None, **kw):
    """Save Difference Formula (the uplift of each row's leaf) and Save Prediction Formula (a row's group's mean,
    or rate of the level of interest, in its leaf), as nested If in the page's formula language."""
    sp = _spec(**kw)
    P, U, t, ms = _grown(table, rows, sp)
    inf = P.missing == 'informative'
    diff = partition.tree_formula(t, P, lambda nd: formula_num(nd.diff), inf)
    tref = formula_ref(U['treatment'])
    is_treat = f'{tref} == {partition._level_lit(U["treat_value"])}'
    pred = partition.tree_formula(t, P, lambda nd: f'If({is_treat}, {formula_num(nd.mg[1])}, {formula_num(nd.mg[0])})', inf, guard=[U['treatment']])
    out = {'difference': {'name': f'Difference {P.y}', 'expr': diff}, 'binary': U['binary']}
    if U['binary']:
        out['prediction'] = {'name': f'Prob[{P.labels[U["interest_index"]]}]', 'expr': pred}
    else:
        out['prediction'] = {'name': f'Predicted {P.y}', 'expr': pred}
    return out


@api('uplift.leaves')
def leaves(table, rows=None, **kw):
    """Save Leaf Numbers and Save Leaf Labels, for every row the tree can take."""
    P, U, t, X, rws, g = _scored(table, rows, kw)
    idx = t.leaf_index(X)
    labels = partition._leaf_labels(t)
    return {'rows': rws.tolist(), 'numbers': (idx + 1).tolist(), 'labels': [labels[i] for i in idx]}
