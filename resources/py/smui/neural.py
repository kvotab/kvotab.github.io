"""Analyze > Predictive Modeling > Neural (resources/js/smui-p-neural.js).

JMP's Neural platform, fitted here as JMP documents its numerics (the JMP 9
Neural Platform Numerics white paper, and the Neural chapter of JMP's help):

  the design     a continuous factor enters as its value (its Johnson Su or
                 Sb transform to normality with Transform Covariates; with
                 Informative Missing the imputed mean and a 0/1 missing
                 column), a categorical one by effect coding (a column per
                 level but the last: 1 for the level, -1 for the last); a
                 missing level is the last level. Every design column is
                 centred and scaled behind the scenes by the training rows'
                 mean and standard deviation; the Estimates are on the
                 design's own scale.
  the network    one or two hidden layers, each with any number of TanH,
                 Linear and Gaussian (exp(-x^2)) nodes; every response in one
                 network: a continuous response one linear output, a
                 categorical one the log odds of each level against the last.
  the fit        the negative log likelihood of the training rows, summed
                 over the responses (Gaussian with the variance profiled out;
                 Laplacian, least absolute deviations, with Robust Fit;
                 multinomial), plus a penalty on the hidden layers' weights
                 (Squared, Absolute, Weight Decay or none; not the intercepts,
                 not the weights into the outputs), minimized by L-BFGS
                 (quasi-Newton, as JMP's BFGS). The iterate with the best
                 validation likelihood is kept (JMP's early stopping). The
                 penalty is searched from none upward, each fit starting
                 where the one before ended, by the validation likelihood.
  tours          restarts from new normal random starting values; the tour
                 with the best validation likelihood is kept.
  KFold          as JMP does it: for each penalty the model of every fold,
                 the penalty with the best validation likelihood summed over
                 the folds, then the fold whose model fits every row best. A
                 Validation column of more than three values gives the folds.
  boosting       base networks of one layer fitted in turn, each to the
                 likelihood with the sum of those before as an offset (on the
                 log-odds scale for a categorical response), scaled by the
                 learning rate, while the validation likelihood improves; the
                 last one kept is not scaled.

The engine (between the ENGINE markers) uses numpy and scipy only; the code
under a model is that engine and the same fit. Everything random comes from
the report's seed: the holdback, the folds, every tour's starting values.
"""
# ==== ENGINE: JMP's neural network, fitted by L-BFGS (numpy and scipy only) ====
import math

import numpy as np
from scipy import optimize, stats

ACTIVATIONS = ('tanh', 'linear', 'gauss')      # JMP's TanH, Linear and Gaussian nodes
SMOOTH = 1e-4        # |b| as sqrt(b^2 + SMOOTH^2) - SMOOTH: the Absolute penalty and Robust Fit, smooth for L-BFGS
LAMBDAS = (0.0, 1e-4, 3e-4, 1e-3, 3e-3, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0)   # the penalty path, from none upward
NO_VALIDATION_LAMBDA = 1e-4                     # the penalty when no rows validate it
PATIENCE = 10        # early stopping: L-BFGS iterations without a better validation likelihood before the fit stops


def activate(code, A):
    """Each node's value from its sum: TanH (code 0), Linear (1: the sum), Gaussian (2: exp(-a^2))."""
    H = A.copy()
    t, g = code == 0, code == 2
    H[:, t] = np.tanh(A[:, t])
    H[:, g] = np.exp(-A[:, g] ** 2)
    return H


def slope(code, A, H):
    """d value / d sum of each node."""
    D = np.ones_like(A)
    t, g = code == 0, code == 2
    D[:, t] = 1 - H[:, t] ** 2
    D[:, g] = -2 * A[:, g] * H[:, g]
    return D


class Net:
    """A network: p inputs, its hidden layers (each a list of its nodes' activations, the layer next to the X's
    first) and q outputs. Its parameters are one vector: each layer's weights (inputs x nodes, by rows) and
    intercepts in turn, the output layer's last. The penalized ones are the hidden layers' weights (JMP: not the
    intercepts, not the weights from the last hidden layer to the outputs)."""

    def __init__(self, p, layers, q):
        self.p, self.q = int(p), int(q)
        self.layers = [list(la) for la in layers]
        self.codes = [np.array([ACTIVATIONS.index(a) for a in la], dtype=int) for la in self.layers]
        sizes = [self.p] + [len(la) for la in self.layers] + [self.q]
        self.shapes = [(sizes[i], sizes[i + 1]) for i in range(len(sizes) - 1)]
        self.size = sum(a * b + b for a, b in self.shapes)
        mask = []
        for i, (a, b) in enumerate(self.shapes):
            mask += [i < len(self.shapes) - 1] * (a * b) + [False] * b
        self.penalized = np.array(mask, dtype=bool)

    def unpack(self, theta):
        """[(W, intercepts)] of every layer, the output layer last."""
        out, k = [], 0
        for a, b in self.shapes:
            out.append((theta[k:k + a * b].reshape(a, b), theta[k + a * b:k + a * b + b]))
            k += a * b + b
        return out

    def start(self, rng):
        """Normal random starting values (JMP's), each layer's weights of sd 1/sqrt(its inputs); intercepts 0."""
        parts = []
        for a, b in self.shapes:
            parts += [rng.normal(0.0, 1.0 / math.sqrt(max(a, 1)), a * b), np.zeros(b)]
        return np.concatenate(parts)

    def forward(self, theta, Z):
        """Each hidden layer's sums and values, and the outputs (n x q)."""
        P = self.unpack(theta)
        H, sums, vals = Z, [], []
        for (W, c), code in zip(P[:-1], self.codes):
            A = H @ W + c
            H = activate(code, A)
            sums.append(A)
            vals.append(H)
        W, c = P[-1]
        return sums, vals, H @ W + c

    def backward(self, theta, Z, sums, vals, dO):
        """The gradient of a loss whose derivative with respect to the outputs is dO."""
        P = self.unpack(theta)
        grads = [None] * len(P)
        grads[-1] = ((vals[-1] if vals else Z).T @ dO, dO.sum(axis=0))
        dH = dO @ P[-1][0].T
        for i in range(len(P) - 2, -1, -1):
            dA = dH * slope(self.codes[i], sums[i], vals[i])
            grads[i] = ((vals[i - 1] if i > 0 else Z).T @ dA, dA.sum(axis=0))
            if i > 0:
                dH = dA @ P[i][0].T
        return np.concatenate([np.concatenate([g[0].ravel(), g[1]]) for g in grads])


class Targets:
    """The responses, in the order of the network's outputs: a continuous one has one output, on the scale of
    (y - mean) / sd of its training rows; a categorical one of L levels L - 1, the log odds of each level against
    the last. ys: each response's values (numbers, or level codes 0 to L - 1); kinds: 0 for a continuous one, L
    for a categorical one; w: the rows' weights (Freq); train: the rows that set the scales; robust: a continuous
    response's likelihood is Laplacian (least absolute deviations), not Gaussian."""

    def __init__(self, ys, kinds, w, train, robust=False):
        self.w = np.asarray(w, dtype=float)
        self.robust = bool(robust)
        self.blocks, k = [], 0
        tr = np.asarray(train, dtype=bool)
        for y, L in zip(ys, kinds):
            if L:
                self.blocks.append({'kind': 'cat', 'a': k, 'b': k + L - 1, 'L': int(L), 'y': np.asarray(y, dtype=int)})
                k += L - 1
            else:
                y = np.asarray(y, dtype=float)
                wt = self.w[tr]
                mu = float(np.sum(wt * y[tr]) / wt.sum())
                sd = math.sqrt(float(np.sum(wt * (y[tr] - mu) ** 2) / wt.sum())) or 1.0
                self.blocks.append({'kind': 'cont', 'a': k, 'b': k + 1, 'mu': mu, 'sd': sd, 'y': y, 'z': (y - mu) / sd})
                k += 1
        self.q = k

    def start_offset(self, train):
        """The outputs of the model with no factor: 0 (a continuous response's training mean), or the log odds of
        a categorical response's training shares; boosting starts from it."""
        tr = np.asarray(train, dtype=bool)
        F = np.zeros(self.q)
        for b in self.blocks:
            if b['kind'] == 'cat':
                wt = self.w[tr]
                share = np.array([wt[b['y'][tr] == j].sum() for j in range(b['L'])]) / wt.sum()
                share = np.clip(share, 1e-12, None)
                F[b['a']:b['b']] = np.log(share[:-1] / share[-1])
        return F

    def loss(self, O, rows, grad=True):
        """The negative log likelihood of the rows (an index array; O their outputs), summed over the responses:
        Gaussian with the variance profiled out, (N/2)(log(SSE/N) + 1 + log 2 pi); with Robust Fit Laplacian,
        N (log(SAD/N) + 1 + log 2), |r| smoothed; multinomial, -sum w log p. N is the rows' weight. Returns it and
        its gradient with respect to O."""
        w = self.w[rows]
        N = float(w.sum())
        total, dO = 0.0, (np.zeros_like(O) if grad else None)
        for b in self.blocks:
            if b['kind'] == 'cont':
                r = b['z'][rows] - O[:, b['a']]
                if self.robust:
                    s = np.sqrt(r * r + SMOOTH * SMOOTH)
                    sad = float(np.sum(w * (s - SMOOTH)))
                    sad = max(sad, 1e-300)
                    total += N * (math.log(sad / N) + 1 + math.log(2))
                    if grad:
                        dO[:, b['a']] = -N / sad * w * r / s
                else:
                    sse = max(float(np.sum(w * r * r)), 1e-300)
                    total += 0.5 * N * (math.log(sse / N) + 1 + math.log(2 * math.pi))
                    if grad:
                        dO[:, b['a']] = -N / sse * w * r
            else:
                T = O[:, b['a']:b['b']]
                m = np.maximum(T.max(axis=1), 0.0)
                E = np.exp(T - m[:, None])
                den = np.exp(-m) + E.sum(axis=1)
                y = b['y'][rows]
                logp = np.where(y < b['L'] - 1, T[np.arange(len(y)), np.minimum(y, b['L'] - 2)] - m, -m) - np.log(den)
                total += -float(np.sum(w * np.clip(logp, math.log(1e-300), 0.0)))
                if grad:
                    Pm = E / den[:, None]
                    Y = np.zeros_like(Pm)
                    hit = y < b['L'] - 1
                    Y[np.flatnonzero(hit), y[hit]] = 1.0
                    dO[:, b['a']:b['b']] = w[:, None] * (Pm - Y)
        return total, dO

    def predict(self, O):
        """Each response's prediction from the outputs: a continuous one's value on its own scale, a categorical
        one's probabilities of its levels (n x L)."""
        out = []
        for b in self.blocks:
            if b['kind'] == 'cont':
                out.append(b['mu'] + b['sd'] * O[:, b['a']])
            else:
                T = np.column_stack([O[:, b['a']:b['b']], np.zeros(len(O))])
                T = T - T.max(axis=1, keepdims=True)
                E = np.exp(T)
                out.append(E / E.sum(axis=1, keepdims=True))
        return out


def penalty(kind, b):
    """JMP's penalty functions of the penalized weights b and their gradient: Squared b^2, Absolute |b| (smoothed),
    Weight Decay b^2 / (1 + b^2), or none."""
    if kind == 'squared':
        return float(np.sum(b * b)), 2 * b
    if kind == 'absolute':
        s = np.sqrt(b * b + SMOOTH * SMOOTH)
        return float(np.sum(s - SMOOTH)), b / s
    if kind == 'weight_decay':
        d = 1 + b * b
        return float(np.sum(b * b / d)), 2 * b / (d * d)
    return 0.0, np.zeros_like(b)


def objective(theta, net, T, Z, rows, lam, pen, offset=None):
    """What L-BFGS minimizes: the rows' negative log likelihood over their weight, plus lam times the penalty of
    the hidden layers' weights; and its gradient."""
    sums, vals, O = net.forward(theta, Z[rows])
    if offset is not None:
        O = O + offset[rows]
    nll, dO = T.loss(O, rows)
    N = float(T.w[rows].sum())
    g = net.backward(theta, Z[rows], sums, vals, dO / N)
    val = nll / N
    if lam > 0:
        pv, pg = penalty(pen, theta[net.penalized])
        val += lam * pv
        g[net.penalized] += lam * pg
    return val, g


def nll_of(theta, net, T, Z, rows, offset=None):
    """The negative log likelihood of the rows (None without rows)."""
    if not len(rows):
        return None
    O = net.forward(theta, Z[rows])[2]
    if offset is not None:
        O = O + offset[rows]
    return T.loss(O, rows, grad=False)[0]


def fit_once(net, T, Z, tr, va, lam, pen, theta0, max_iter, offset=None):
    """One L-BFGS fit of the training rows tr, from theta0. With validation rows va, the iterate with the best
    validation likelihood is kept and the fit stops once PATIENCE iterations have not bettered it (JMP's early
    stopping); the start is not one of them (a fit warm-started where another ended is a fit of its own), unless
    the fit makes no iteration. Returns the parameters, the iterations and the -log likelihood of the training and
    validation rows."""
    best = {'nll': math.inf, 'theta': np.array(theta0, dtype=float), 'it': 0}
    seen = [0]

    def watch(intermediate_result):
        seen[0] += 1
        if not len(va):
            return
        v = nll_of(intermediate_result.x, net, T, Z, va, offset)
        if v < best['nll'] - 1e-12 * max(1.0, abs(v)):
            best.update(nll=v, theta=intermediate_result.x.copy(), it=seen[0])
        elif seen[0] - best['it'] >= PATIENCE:
            raise StopIteration
    res = optimize.minimize(objective, np.array(theta0, dtype=float), args=(net, T, Z, tr, lam, pen, offset), jac=True,
                            method='L-BFGS-B', callback=watch, options={'maxiter': int(max_iter), 'ftol': 1e-13, 'gtol': 1e-9})
    theta = best['theta'] if len(va) else res.x
    return {'theta': theta, 'iterations': seen[0], 'kept': best['it'] if len(va) else seen[0],
            'train': nll_of(theta, net, T, Z, tr, offset), 'valid': nll_of(theta, net, T, Z, va, offset)}


def penalty_path(net, T, Z, splits, pen, starts, max_iter, offsets=None, lambdas=LAMBDAS):
    """JMP's search of the penalty over every split of the rows at once (one split, or K folds): the fits with no
    penalty from the starting values, then with larger ones, each fit starting where the one before ended, until
    two penalties in a row have not bettered the validation likelihood summed over the splits; the best is kept.
    Without validation rows the penalty is NO_VALIDATION_LAMBDA (or none with No Penalty). splits: [(training
    rows, validation rows)] as index arrays; starts: each split's starting values."""
    validate = any(len(va) for _, va in splits)
    lams = (0.0,) if pen == 'none' else lambdas if validate else (NO_VALIDATION_LAMBDA,)
    thetas = [np.array(s, dtype=float) for s in starts]
    path, best, worse = [], None, 0
    for lam in lams:
        fits = [fit_once(net, T, Z, tr, va, lam, pen, th, max_iter, None if offsets is None else offsets[i]) for i, ((tr, va), th) in enumerate(zip(splits, thetas))]
        thetas = [f['theta'] for f in fits]
        crit = sum(f['valid'] or 0.0 for f in fits) if validate else sum(f['train'] for f in fits)
        path.append({'lambda': lam, 'iterations': float(np.mean([f['iterations'] for f in fits])), 'train': sum(f['train'] for f in fits),
                     'valid': sum(f['valid'] or 0.0 for f in fits) if validate else None})
        if best is None or crit < best['crit']:
            best, worse = {'lambda': lam, 'crit': crit, 'fits': fits, 'index': len(path) - 1}, 0
        else:
            worse += 1
            if worse >= 2:
                break
    for i, r in enumerate(path):
        r['chosen'] = i == best['index']
    return best, path


class Model:
    """A fitted network as one: its layers [(W, intercepts)] on the design's centred and scaled columns, the
    hidden layers' activations, and the responses (Targets) its outputs predict; offset: the constant added to
    the outputs (a boosted network's start). A boosted network's base models sit side by side in its hidden
    layer, their outputs weighted by the learning rate (the last one kept by 1)."""

    def __init__(self, layers, codes, T, offset=None):
        self.layers, self.codes, self.T = layers, codes, T
        self.offset = np.zeros(T.q) if offset is None else np.asarray(offset, dtype=float)

    @classmethod
    def of(cls, net, theta, T, offset=None):
        return cls(net.unpack(np.asarray(theta, dtype=float)), list(net.codes), T, offset)

    @classmethod
    def boosted(cls, net, parts, T, offset):
        """The base models [(theta, weight)] of one hidden layer as one network."""
        Ls = [net.unpack(np.asarray(th, dtype=float)) for th, _ in parts]
        W1 = np.concatenate([L[0][0] for L in Ls], axis=1)
        b1 = np.concatenate([L[0][1] for L in Ls])
        Wo = np.concatenate([wt * L[1][0] for L, (_, wt) in zip(Ls, parts)], axis=0)
        bo = sum(wt * L[1][1] for L, (_, wt) in zip(Ls, parts))
        return cls([(W1, b1), (Wo, bo)], [np.concatenate([net.codes[0]] * len(parts))], T, offset)

    def hidden(self, Z):
        """Each hidden layer's values (the layer next to the X's first)."""
        H, out = Z, []
        for (W, c), code in zip(self.layers[:-1], self.codes):
            H = activate(code, H @ W + c)
            out.append(H)
        return out

    def outputs(self, Z):
        hs = self.hidden(Z)
        W, c = self.layers[-1]
        return (hs[-1] if hs else Z) @ W + c + self.offset

    def predict(self, Z):
        """Each response's prediction: its value, or its levels' probabilities."""
        return self.T.predict(self.outputs(Z))


def boost(net, T, Z, splits, pen, start, max_iter, K, rate, seeds):
    """JMP's boosting of one split (training rows, validation rows): base networks (net, one hidden layer) fitted
    in turn, each to the likelihood with the sum of those before as an offset, added scaled by the learning rate,
    while the validation likelihood improves (the training one without validation rows), up to K; the first base
    model runs up the penalty path, the rest are fitted at its penalty from new starting values (seeds); the last
    one kept enters unscaled. Returns the parts [(theta, weight)], the start, the rows of the report and the
    penalty chosen with its path."""
    (tr, va), = splits
    F0 = T.start_offset(np.isin(np.arange(len(Z)), tr))
    F = np.tile(F0, (len(Z), 1))
    validate = bool(len(va))
    prev = (T.loss(F[tr], tr, grad=False)[0], T.loss(F[va], va, grad=False)[0] if validate else None)
    parts, rows = [], []
    best, path = None, []
    for k in range(int(K)):
        if k == 0:
            best, path = penalty_path(net, T, Z, splits, pen, [start], max_iter, offsets=[F])
            fit = best['fits'][0]
        else:
            fit = fit_once(net, T, Z, tr, va, best['lambda'], pen, net.start(np.random.default_rng(seeds[k])), max_iter, F)
        g = net.forward(fit['theta'], Z)[2]
        Fk = F + rate * g
        sc = (T.loss(Fk[tr], tr, grad=False)[0], T.loss(Fk[va], va, grad=False)[0] if validate else None)
        better = sc[1] < prev[1] if validate else sc[0] < prev[0]
        rows.append({'model': k + 1, 'train': sc[0], 'valid': sc[1], 'kept': bool(better), 'iterations': fit['iterations']})
        if not better and parts:
            break
        parts.append((fit['theta'], rate))
        F, prev = Fk, sc
        if not better:        # not even the first improved: it stays, alone
            rows[-1]['kept'] = True
            break
    parts[-1] = (parts[-1][0], 1.0)         # the last base model kept is not scaled by the learning rate
    return {'parts': parts, 'offset': F0, 'rows': rows, 'best': best, 'path': path}


def fit_neural(Z, T, splits, layers, spec, seed):
    """The network of spec (layers: the hidden layers' activations, the one next to the X's first; penalty,
    tours, max_iter, boost, rate) on the splits of the rows [(training, validation)], as the report fits it: for
    each tour its own normal random starting values from the seed (every split starts from them), the penalty
    searched over the splits together (or each split's network boosted), the tour with the best validation
    likelihood summed over the splits kept, and with several splits (KFold) the split whose model fits every row
    best. Returns the Model and how it was chosen."""
    net = Net(Z.shape[1], layers, T.q)
    validate = any(len(va) for _, va in splits)
    everyone = np.arange(len(Z))
    tours = []
    for t in range(int(spec['tours'])):
        start = net.start(np.random.default_rng([int(seed) % (2 ** 32), 7, t]))
        if spec['boost']:
            per = [boost(net, T, Z, [sp], spec['penalty'], start, spec['max_iter'], spec['boost'], spec['rate'],
                         [[int(seed) % (2 ** 32), 7, t, k, i] for k in range(int(spec['boost']))]) for i, sp in enumerate(splits)]
            models = [Model.boosted(net, b['parts'], T, b['offset']) for b in per]
            last = [b['rows'][len(b['parts']) - 1] for b in per]
            crit = sum((r['valid'] if validate else r['train']) or 0.0 for r in last)
            tours.append({'tour': t + 1, 'criterion': crit, 'models': models, 'per': per, 'valid': [r['valid'] for r in last]})
        else:
            best, path = penalty_path(net, T, Z, splits, spec['penalty'], [start] * len(splits), spec['max_iter'])
            models = [Model.of(net, f['theta'], T) for f in best['fits']]
            tours.append({'tour': t + 1, 'criterion': best['crit'], 'models': models, 'best': best, 'path': path, 'valid': [f['valid'] for f in best['fits']]})
    k = int(np.argmin([r['criterion'] for r in tours]))
    chosen = tours[k]
    fold, fold_rows = 0, []
    if len(splits) > 1:
        full = [T.loss(m.outputs(Z), everyone, grad=False)[0] for m in chosen['models']]
        fold = int(np.argmin(full))
        fold_rows = [{'fold': j + 1, 'rows': int(len(va)), 'valid': chosen['valid'][j], 'all': full[j], 'chosen': j == fold} for j, (_, va) in enumerate(splits)]
    if spec['boost']:
        b = chosen['per'][fold]
        kept = len(b['parts'])
        how = {'lambda': b['best']['lambda'], 'path': b['path'], 'boost': b['rows'], 'components': kept, 'iterations': [r['iterations'] for r in b['rows'][:kept]]}
    else:
        how = {'lambda': chosen['best']['lambda'], 'path': chosen['path'], 'boost': None, 'components': 1, 'iterations': chosen['best']['fits'][fold]['iterations']}
    return {'model': chosen['models'][fold], 'net': net, 'tour': k, 'fold': fold, 'folds': fold_rows,
            'tours': [{'tour': r['tour'], 'criterion': r['criterion'], 'chosen': i == k} for i, r in enumerate(tours)], **how}


def johnson_fit(x):
    """The Johnson Su or Sb distribution fitted to the values x by maximum likelihood (scipy's), the one with the
    larger likelihood: (kind, a, b, loc, scale); z = a + b asinh((x - loc)/scale) (Su) or a + b log(u / (1 - u)),
    u = (x - loc)/scale (Sb), is then near normal."""
    x = np.asarray(x, dtype=float)
    best = None
    try:
        p = stats.johnsonsu.fit(x)
        ll = float(np.sum(stats.johnsonsu.logpdf(x, *p)))
        if math.isfinite(ll):
            best = (ll, ('su',) + tuple(float(v) for v in p))
    except Exception:
        pass
    lo, hi = float(np.min(x)), float(np.max(x))
    pad = 0.05 * (hi - lo if hi > lo else 1.0)
    try:
        p = stats.johnsonsb.fit(x, loc=lo - pad, scale=hi - lo + 2 * pad)
        ll = float(np.sum(stats.johnsonsb.logpdf(x, *p)))
        if math.isfinite(ll) and (best is None or ll > best[0]):
            best = (ll, ('sb',) + tuple(float(v) for v in p))
    except Exception:
        pass
    return best[1] if best else ('su', 0.0, 1.0, float(np.mean(x)), float(np.std(x)) or 1.0)


def johnson_z(par, x):
    """The Johnson transform of x (johnson_fit's parameters) to near normality."""
    kind, a, b, loc, scale = par
    u = (np.asarray(x, dtype=float) - loc) / scale
    if kind == 'su':
        return a + b * np.arcsinh(u)
    u = np.clip(u, 1e-12, 1 - 1e-12)
    return a + b * np.log(u / (1 - u))


class Design:
    """JMP's design row of the factors, from the predictor matrix X (a 0/1 column per level of a categorical
    factor, its last column its missing level when it has one; a continuous factor's value with its training
    mean in place of a missing one, and its 0/1 missing column). blocks: each factor, ('cont', column, missing
    column or None) or ('cat', its columns); transform: Transform Covariates. fit() takes the Johnson transforms
    of the continuous factors and the means and standard deviations of every design column from the training
    rows; apply() gives the design centred and scaled, as the network takes it."""

    def __init__(self, blocks, transform=False):
        self.blocks = [tuple(b) for b in blocks]
        self.transform = bool(transform)
        self.johnson, self.fill = {}, {}
        self.mean = self.sd = None

    def raw(self, X):
        """The design on its own scale: a continuous factor's value or transform (a missing one: the mean of the
        training rows' transforms) and its missing column; a categorical factor's effect coding, a column per
        level but the last (1 for the level, -1 for the last, 0 otherwise)."""
        X = np.asarray(X, dtype=float)
        cols = []
        for b in self.blocks:
            if b[0] == 'cont':
                j, jm = b[1], b[2]
                v = X[:, j]
                if j in self.johnson:
                    z = johnson_z(self.johnson[j], v)
                    if jm is not None:
                        z = np.where(X[:, jm] == 1, self.fill[j], z)
                    v = z
                cols.append(v)
                if jm is not None:
                    cols.append(X[:, jm])
            else:
                c = list(b[1])
                for q in c[:-1]:
                    cols.append(X[:, q] - X[:, c[-1]])
        return np.column_stack(cols) if cols else np.zeros((len(X), 0))

    def fit(self, X, w, rows):
        X = np.asarray(X, dtype=float)
        w = np.asarray(w, dtype=float)
        if self.transform:
            for b in self.blocks:
                if b[0] == 'cont':
                    j, jm = b[1], b[2]
                    ok = rows if jm is None else rows[X[rows, jm] == 0]
                    v = X[ok, j]
                    if len(np.unique(v)) > 2:
                        self.johnson[j] = johnson_fit(v)
                        self.fill[j] = float(np.average(johnson_z(self.johnson[j], v), weights=w[ok]))
        D = self.raw(X[rows])
        wt = w[rows]
        self.mean = np.average(D, axis=0, weights=wt) if D.shape[1] else np.zeros(0)
        sd = np.sqrt(np.average((D - self.mean) ** 2, axis=0, weights=wt)) if D.shape[1] else np.zeros(0)
        self.sd = np.where(sd > 1e-12, sd, 1.0)
        return self

    def apply(self, X):
        return (self.raw(X) - self.mean) / self.sd
# ==== END OF ENGINE ====

import copy  # noqa: E402
import inspect  # noqa: E402
import json  # noqa: E402

import pandas as pd  # noqa: E402

from . import data, predictive, profile  # noqa: E402
from .registry import api  # noqa: E402
from .util import formula_num, formula_ref, formula_str  # noqa: E402

SEP = predictive.SEP
ACT_LABEL = {'tanh': 'TanH', 'linear': 'Linear', 'gauss': 'Gaussian'}
METHOD_LABEL = {'holdback': 'Random Holdback', 'kfold': 'KFold', 'excluded': 'Excluded Rows Holdback', 'column': 'Validation Column', 'folds': 'KFold'}
PENALTIES = ('squared', 'absolute', 'weight_decay', 'none')
LAYER_KEYS = (('t1', 'l1', 'g1'), ('t2', 'l2', 'g2'))    # the nodes of each activation, first layer (next to the responses) and second
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


# ---------------------------------------------------------------------------
# the settings of one model (the Model Launch)
# ---------------------------------------------------------------------------

def _num(m, key, default, lo, hi, what, integer=False, open_lo=False):
    v = m.get(key, default)
    if v is None or v == '':
        v = default
    try:
        v = float(v)
    except (TypeError, ValueError):
        raise ValueError(f'{what}: a number, not {v!r}')
    if not math.isfinite(v) or v < lo or v > hi or (open_lo and v <= lo):
        raise ValueError(f'{what} is above {lo:g} and at most {hi:g}' if open_lo else f'{what} is from {lo:g} to {hi:g}')
    if integer:
        if v != int(v):
            raise ValueError(f'{what} is a whole number')
        v = int(v)
    return v


def spec_of(model):
    """The Model Launch settings, checked, with JMP's defaults (three TanH nodes in one layer, no boosting, the
    Squared penalty, one tour). A model saved before the layers had several activations (activation, n1, n2)
    reads as those nodes of its activation (Logistic and ReLU, scikit-learn's, as TanH)."""
    m = dict(model or {})
    notes = []
    if not any(k in m for k in ('t1', 'l1', 'g1', 't2', 'l2', 'g2')) and ('n1' in m or 'activation' in m):
        act = m.get('activation') or 'tanh'
        key = {'identity': 'l', 'linear': 'l', 'gauss': 'g'}.get(act, 't')
        if act in ('logistic', 'relu'):
            notes.append(f'The model was saved with {act} nodes, which JMP has not: they are TanH nodes now.')
        m[f'{key}1'] = m.get('n1', 3)
        m[f'{key}2'] = m.get('n2', 0)
    method = m.get('method') or 'holdback'
    if method not in METHOD_LABEL:
        raise ValueError(f'unknown validation method {method!r}')
    penalty = m.get('penalty') or 'squared'
    if penalty not in PENALTIES:
        raise ValueError(f'unknown penalty method {penalty!r}')
    s = {'method': method,
         'portion': _num(m, 'portion', 0.3333, 0.0, 1.0, 'The Holdback Proportion', open_lo=True) if method == 'holdback' else None,
         'folds': _num(m, 'folds', 5, 2, 50, 'The Number of Folds', integer=True) if method == 'kfold' else None,
         'boost': _num(m, 'boost', 0, 0, 1000, 'The Number of Models', integer=True),
         'rate': _num(m, 'rate', 0.1, 0.0, 1.0, 'The Learning Rate', open_lo=True),
         'transform': bool(m.get('transform')), 'robust': bool(m.get('robust')), 'penalty': penalty,
         'tours': _num(m, 'tours', 1, 1, 100, 'The Number of Tours', integer=True),
         'max_iter': _num(m, 'max_iter', 200, 1, 100000, 'The Maximum Iterations', integer=True)}
    default = {'t1': 3} if not any(m.get(k) not in (None, '') for k in LAYER_KEYS[0]) else {}   # JMP's three TanH nodes, when the first layer is not given
    for li, keys in enumerate(LAYER_KEYS):
        for key in keys:
            s[key] = _num(m, key, default.get(key, 0), 0, 500, f'The {"first" if li == 0 else "second"} layer\'s {ACT_LABEL[ACTIVATIONS["tlg".index(key[0])]]} nodes', integer=True)
    if s['t1'] + s['l1'] + s['g1'] < 1:
        raise ValueError('The first layer needs at least one node')
    if s['portion'] is not None and s['portion'] >= 1:
        raise ValueError('The Holdback Proportion is below 1')
    if s['boost']:
        for key in LAYER_KEYS[1]:
            s[key] = 0          # JMP: boosting takes one layer; a second is ignored
    else:
        s['rate'] = None
    s['notes'] = notes
    return s


def layers_of(s):
    """The hidden layers' activations, the one next to the X's first: JMP's second layer (when there is one),
    then its first."""
    def one(keys):
        return ['tanh'] * s[keys[0]] + ['linear'] * s[keys[1]] + ['gauss'] * s[keys[2]]
    second = one(LAYER_KEYS[1])
    return ([second] if second else []) + [one(LAYER_KEYS[0])]


def name_of(s):
    """JMP's name of the model: NTanH(3), NTanH(2)NLinear(1), NTanH(3)NTanH2(2), NGaussian(2)NBoost(10)."""
    out = ''
    for li, keys in enumerate(LAYER_KEYS):
        for key, act in zip(keys, ACTIVATIONS):
            if s[key]:
                out += f'N{ACT_LABEL[act]}{"2" if li else ""}({s[key]})'
    if s['boost']:
        out += f'NBoost({s["boost"]})'
    return out


# ---------------------------------------------------------------------------
# a model: every response in one network, fitted on the report's rows
# ---------------------------------------------------------------------------

class _Model:
    """A fitted model: ys, x, Ps (one Prepared per response, the same rows and sets), the design, the targets,
    the network (res: fit_neural's result), the validation method and the splits."""


def _responses(y):
    ys = y if isinstance(y, (list, tuple)) else [y]
    ys = [c for c in dict.fromkeys(ys) if c]
    if not ys:
        raise ValueError('choose a Y, Response')
    return ys


def _blocks(P):
    """The design's blocks from the prepared data (one-hot coding): each factor's columns of X."""
    out = []
    for e in P.enc:
        idx = list(P.groups[e['name']])
        if e['type'] == 'continuous':
            out.append(('cont', idx[0], idx[1] if len(idx) > 1 else None))
        else:
            out.append(('cat', idx))
    return out


def _design_names(P, design):
    """The names of the design's columns: x (T(x) transformed), x Missing, g[level] for each level but the last."""
    names = []
    for e, b in zip(P.enc, design.blocks):
        if b[0] == 'cont':
            names.append(f'T({e["name"]})' if b[1] in design.johnson else e['name'])
            if b[2] is not None:
                names.append(f'{e["name"]} Missing')
        else:
            names += [P.features[q] for q in b[1][:-1]]
    return names


def _build(table, rows, ys, x, freq, validation, seed, missing, s, holdback):
    """Fit the model: what the report, the profiler and Save use."""
    M = _Model()
    M.ys, M.spec, M.seed = ys, s, int(seed)
    x = [c for c in dict.fromkeys(x or []) if c and c not in ys]
    if not x:
        raise ValueError('choose at least one X, Factor (other than the responses)')
    M.x, M.notes = x, list(s.get('notes') or [])
    # the rows with every response (the likelihood of a row missing one would lack it)
    df = data.frame(table, ys, rows, dropna=False)
    ok = np.ones(len(df), dtype=bool)
    for c in ys:
        if data.is_categorical(table, c):
            ok &= df[c].notna().to_numpy()
        else:
            ok &= np.isfinite(pd.to_numeric(df[c], errors='coerce').to_numpy(float))
    if (~ok).sum():
        M.notes.append(f'{int((~ok).sum())} rows with no {ys[0]} are left out.' if len(ys) == 1 else
                       f'{int((~ok).sum())} rows missing one of the responses are left out: the network takes only rows with every response.')
    use = None if (rows is None and ok.all()) else [int(r) for r in np.asarray(df.index)[ok]]
    if use is not None and not use:
        raise ValueError('no rows with every response')
    M.rows = use
    method = 'column' if validation else s['method']
    portion = s['portion'] if method == 'holdback' else 0.0
    M.Ps = [predictive.prepare(table, c, x, rows=use, freq=freq, validation=validation, portion=portion, seed=seed, missing=missing) for c in ys]
    P0 = M.Ps[0]
    if method == 'column' and P0.folds is not None:
        method = 'folds'          # a Validation column of K folds: KFold by its folds
    M.method = method
    n = len(P0.index)
    M.notes += [t for t in P0.notes if t not in M.notes]
    # the splits of the rows: [(training, validation)], one or K
    everyone = np.arange(n)
    folds = None
    if method == 'excluded':
        hb = {int(r) for r in (holdback or [])}
        va = np.array([int(r) in hb for r in P0.index], dtype=bool)
        if va.all():
            raise ValueError('Excluded Rows Holdback: every row is excluded, so none trains the model')
        splits = [(everyone[~va], everyone[va])]
        sets = va.astype(int)
    elif method in ('kfold', 'folds'):
        if method == 'kfold':
            K = s['folds']
            if K > n:
                raise ValueError(f'KFold: {K} folds need at least {K} rows; there are {n}')
            folds = np.empty(n, dtype=int)
            folds[np.random.default_rng(int(seed)).permutation(n)] = np.arange(n) % K
        else:
            folds = np.full(n, -1)               # the folds of the Validation column (predictive.fold_masks)
            for j, (_, held) in enumerate(predictive.fold_masks(P0)):
                folds[held] = j
            K = P0.k
        splits = [(everyone[folds != k], everyone[folds == k]) for k in range(K)]
        sets = np.zeros(n, dtype=int)
    else:
        sets = P0.sets.copy()
        splits = [(everyone[sets == 0], everyone[sets == 1])]
    M.folds = folds
    w = np.ones(n) if P0.w is None else P0.w
    # the design, from the rows that train (with KFold every row: it takes the factors only, never a response)
    design_rows = everyone if folds is not None else splits[0][0]
    M.design = Design(_blocks(P0), s['transform']).fit(P0.X, w, design_rows)
    Z = M.design.apply(P0.X)
    kinds = [len(P.levels) if P.kind == 'categorical' else 0 for P in M.Ps]
    M.T = Targets([P.target for P in M.Ps], kinds, w, np.isin(everyone, design_rows), s['robust'] and any(k == 0 for k in kinds))
    if s['robust'] and all(kinds):
        M.notes.append('Robust Fit is for a continuous response: a categorical one\'s likelihood is multinomial either way.')
    M.res = fit_neural(Z, M.T, splits, layers_of(s), s, seed)
    M.splits = splits
    if folds is not None:
        k = M.res['fold']
        sets = np.where(folds == k, 1, 0)
    for P in M.Ps:
        P.sets = np.asarray(sets, dtype=int) if method != 'column' else P.sets
    M.Z = Z
    M.w = w
    return M


def _model(table, rows, y, x, freq, validation, seed, missing, model, holdback):
    ys = _responses(y)
    s = spec_of(model)
    seed = predictive.seed_of(seed)
    if seed is None:
        raise ValueError('the model needs a random seed')
    key = {'y': ys, 'x': list(x or []), 'freq': freq, 'validation': validation, 'seed': seed, 'missing': missing,
           'spec': {k: v for k, v in s.items() if k != 'notes'},
           'holdback': predictive.rows_sig(holdback) if s['method'] == 'excluded' and not validation else None}
    return predictive.cached('neural', table, rows, key, lambda: _build(table, rows, ys, x, freq, validation, seed, missing, s, holdback))


# ---------------------------------------------------------------------------
# what the report shows
# ---------------------------------------------------------------------------

def _reported_layers(M):
    """The network on the design's own scale (its centring and scaling folded into the first layer) and each
    continuous response's output on the response's scale: [(W, intercepts)] from the design to the outputs."""
    mod = M.res['model']
    layers = [(W.copy(), c.copy()) for W, c in mod.layers]
    d = M.design
    W0, c0 = layers[0]
    layers[0] = (W0 / d.sd[:, None], c0 - (d.mean / d.sd) @ W0)
    Wo, co = layers[-1]
    co = co + mod.offset
    Wo, co = Wo.copy(), co.copy()
    for b in M.T.blocks:
        if b['kind'] == 'cont':
            j = b['a']
            Wo[:, j] = Wo[:, j] * b['sd']
            co[j] = b['mu'] + b['sd'] * co[j]
    layers[-1] = (Wo, co)
    return layers


def _hnames(nh):
    return ['H2', 'H1'] if nh == 2 else ['H1']


def _node_acts(M):
    """Each hidden layer's nodes' activations, the layer next to the X's first."""
    return [[ACTIVATIONS[c] for c in code] for code in M.res['model'].codes]


def _out_names(M):
    """The output nodes' names: each continuous response, response[level] for every level but the last of a
    categorical one (the log odds of the level against the last, as JMP writes them)."""
    out = []
    for P, b in zip(M.Ps, M.T.blocks):
        out += [P.y] if b['kind'] == 'cont' else [f'{P.y}[{lab}]' for lab in P.labels[:-1]]
    return out


def _estimates(M):
    """The Estimates: every weight and intercept, with JMP's names (H1_1:x1, H1_1:Intercept; H2_ for the layer
    next to the X's; y:H1_1, y[level]:H1_1)."""
    layers = _reported_layers(M)
    nh = len(layers) - 1
    hn = _hnames(nh)
    rows = []
    ins = _design_names(M.Ps[0], M.design)
    for li, (W, c) in enumerate(layers):
        outs = [f'{hn[li]}_{i + 1}' for i in range(W.shape[1])] if li < nh else _out_names(M)
        for i, o in enumerate(outs):
            for j, a in enumerate(ins):
                rows.append({'parameter': f'{o}:{a}', 'estimate': float(W[j, i])})
            rows.append({'parameter': f'{o}:Intercept', 'estimate': float(c[i])})
        ins = outs
    return rows


def _diagram(M):
    """The network for the Diagram: the X columns, the hidden layers (the one next to the X's first, each node's
    activation), the responses, with every weight on the reported scale."""
    P = M.Ps[0]
    layers = _reported_layers(M)
    nh = len(layers) - 1
    names = _design_names(P, M.design)
    cols, k = {}, 0
    for e, b in zip(P.enc, M.design.blocks):
        n_ = (1 + (b[2] is not None)) if b[0] == 'cont' else len(b[1]) - 1
        cols[e['name']] = list(range(k, k + n_))
        k += n_
    inputs = [{'name': c, 'features': [names[j] for j in cols[c]], 'columns': cols[c], 'type': 'categorical' if data.is_categorical(P.table, c) else 'continuous'} for c in P.x]
    acts = _node_acts(M)
    hidden = [{'name': _hnames(nh)[i], 'n': int(layers[i][0].shape[1]), 'acts': acts[i]} for i in range(nh)]
    outputs = [{'name': M.ys[j], 'kind': M.Ps[j].kind} for j in range(len(M.ys))]
    return {'inputs': inputs, 'hidden': hidden, 'outputs': outputs, 'weights': [W.tolist() for W, _ in layers], 'biases': [c.tolist() for _, c in layers],
            'out_names': _out_names(M), 'blocks': [[b['a'], b['b']] for b in M.T.blocks]}


def _validation_info(M, validation):
    s = M.spec
    info = {'method': M.method, 'label': METHOD_LABEL[M.method]}
    if M.method == 'holdback':
        info['portion'] = s['portion']
    if M.method in ('kfold', 'folds'):
        info.update({'folds': len(M.splits), 'fold': M.res['fold'] + 1})
    if M.method in ('column', 'folds'):
        info['column'] = validation
    return info


def _fitted(M, Z=None):
    """Each response's prediction of every row of the model's data: its value, or its levels' probabilities."""
    return M.res['model'].predict(M.Z if Z is None else Z)


def _clip_probs(p):
    p = np.clip(np.asarray(p, dtype=float), 1e-15, 1 - 1e-15)
    return p / p.sum(axis=1, keepdims=True)


@api('neural.fit')
def fit(table, y, x, rows=None, freq=None, validation=None, seed=None, missing='informative', model=None, holdback=None, table_name='data'):
    """One model of the report: its measures per set and response, its Estimates and Diagram, how it was fitted,
    and the code."""
    try:
        M = _model(table, rows, y, x, freq, validation, seed, missing, model, holdback)
    except ValueError as e:
        return {'error': str(e)}
    s = M.spec
    name = name_of(s)
    preds = _fitted(M)
    head = _code(M, table_name, graph=True)
    resp_out = []
    for j, (P, b, f) in enumerate(zip(M.Ps, M.T.blocks, preds)):
        if b['kind'] == 'cont':
            select = [f'y, fitted = Y[:, {j}], pred[{j}]   # the response {P.y}: its values and the network\'s prediction']
            rep = predictive.report(P, f, head=head, select=select)
            rep['plots']['rbp'] = {predictive.SETS[q]: '\n'.join(select + predictive.abp_lines(q, residual=True)) for q in range(3) if P.has(q)}
        else:
            select = [f'y, fitted, levels = Y[:, {j}].astype(int), pred[{j}], levels_of[{j}]   # the response {P.y}: its levels and the network\'s probabilities']
            rep = predictive.report(P, _clip_probs(f), head=head, select=select)
        rep['notes'] = []
        resp_out.append({'y': P.y, 'kind': P.kind, 'net': 0, 'fit': rep})
    res = M.res
    net_out = {'responses': list(M.ys), 'kinds': [P.kind for P in M.Ps], 'lambda': res['lambda'], 'penalty': s['penalty'], 'robust': M.T.robust,
               'iterations': res['iterations'], 'max_iter': s['max_iter'], 'path': res['path'], 'boosted': bool(s['boost']), 'boost': res['boost'],
               'components': res['components'], 'estimates': _estimates(M), 'diagram': _diagram(M), 'diagram_code': _diagram_tail(M),
               'transformed': [n_ for n_ in _design_names(M.Ps[0], M.design) if n_.startswith('T(')]}
    P0 = M.Ps[0]
    notes = list(M.notes)
    if s['penalty'] != 'none' and not any(len(va) for _, va in M.splits):
        notes.append(f'No rows validate the model, so the penalty cannot be chosen: it is {NO_VALIDATION_LAMBDA:g}.')
    return {'name': name, 'spec': {k: v for k, v in s.items() if k != 'notes'}, 'responses': resp_out, 'nets': [net_out],
            'validation': _validation_info(M, validation), 'seed': M.seed, 'tours': res['tours'], 'tour': res['tour'] + 1, 'folds': res['folds'],
            'sets': [predictive.SETS[k] for k in range(3) if P0.has(k)], 'n': {predictive.SETS[k]: int(P0.mask(k).sum()) for k in range(3)},
            'notes': notes, 'features': _design_names(P0, M.design), 'x': list(M.x),
            'script': _code(M, table_name), 'plots': {'head_code': head}}   # 'script': the page shows it split in parts, the engine once


def _all_design(M):
    """The design of every row of the table whose factors the model can take, and the row numbers."""
    Xa, rws = M.Ps[0].all_rows()
    return M.design.apply(Xa), rws, Xa


@api('neural.save')
def save(table, y, x, rows=None, freq=None, validation=None, seed=None, missing='informative', model=None, holdback=None, what='predicteds', response=None):
    """What Save Columns puts in the table: every response's predictions (on every row whose factors the model can
    take), the hidden nodes' values, the sets, or the transformed covariates. response: one response's
    predictions alone, as the predictive platforms' Save Predicteds gives them (the Decision Threshold's save)."""
    try:
        M = _model(table, rows, y, x, freq, validation, seed, missing, model, holdback)
    except ValueError as e:
        return {'error': str(e)}
    P0 = M.Ps[0]
    if what == 'validation':
        return {'rows': P0.index.tolist(), 'values': P0.sets.tolist(), 'name': 'Validation'}
    Za, rws, Xa = _all_design(M)
    if what == 'hidden':
        hs = M.res['model'].hidden(Za)
        # on the design's own scale the same values: the hidden nodes do not depend on the scaling
        cols = []
        hn = _hnames(len(hs))
        for li in range(len(hs) - 1, -1, -1):
            for i in range(hs[li].shape[1]):
                cols.append({'name': f'{hn[li]}_{i + 1}', 'values': hs[li][:, i].tolist()})
        return {'rows': rws.tolist(), 'columns': cols}
    if what == 'transformed':
        D = M.design.raw(Xa)
        names = _design_names(P0, M.design)
        return {'rows': rws.tolist(), 'columns': [{'name': nm, 'values': D[:, j].tolist()} for j, nm in enumerate(names) if nm.startswith('T(')]}
    preds = M.res['model'].predict(Za)
    out = []
    for P, b, f in zip(M.Ps, M.T.blocks, preds):
        if b['kind'] == 'cont':
            yv = pd.to_numeric(pd.Series(data.raw(P.table, P.y, rws)), errors='coerce').to_numpy(float)
            r = {'rows': rws.tolist(), 'values': f.tolist(), 'residuals': (yv - f).tolist(), 'name': f'Predicted {P.y}'}
        else:
            pr = _clip_probs(f)
            r = {'rows': rws.tolist(), 'prob': pr.tolist(), 'levels': list(P.labels), 'most_likely': [P.labels[int(j)] for j in np.argmax(pr, axis=1)],
                 'names': [f'Prob[{lab}]' for lab in P.labels], 'most_name': f'Most Likely {P.y}',
                 'ordinal': data.meta(P.table, P.y).get('modelingType') == 'ordinal'}
        r['y'] = P.y
        out.append(r)
    if response is not None:
        one = next((r for r in out if r['y'] == response), None)
        if one is None:
            return {'error': f'{response} is not a response of the model'}
        if len(M.ys) > 1 and 'names' in one:
            one = dict(one, names=[f'{response} {nm}' for nm in one['names']])
        return one
    return {'responses': out}


def _predictor(table, rows=None, y=None, x=None, freq=None, validation=None, seed=None, missing='informative', model=None, holdback=None, **_):
    """The Prediction Profiler's view of a model: every response."""
    M = _model(table, rows, y, x, freq, validation, seed, missing, model, holdback)
    P0 = M.Ps[0]

    def run(settings):
        Z = M.design.apply(P0.encode_settings(settings))
        out = []
        for P, b, f in zip(M.Ps, M.T.blocks, M.res['model'].predict(Z)):
            if b['kind'] == 'cont':
                out.append({'name': P.y, 'pred': f, 'lower': None, 'upper': None, 'bounded': False})
            else:
                for k, lab in enumerate(P.labels):
                    out.append({'name': f'Prob[{lab}]' if len(M.ys) == 1 else f'{P.y} Prob[{lab}]', 'pred': f[:, k], 'lower': None, 'upper': None, 'bounded': True})
        return out
    frame = data.frame(P0.table, P0.x, P0.index[P0.train()], dropna=False)
    observed = {c: [None if (isinstance(v, float) and math.isnan(v)) else (v.item() if hasattr(v, 'item') else v) for v in frame[c].astype(object)] for c in P0.x}
    return profile.Predictor(P0.factors(), run, observed)


profile.expose('neural', _predictor)


# ---------------------------------------------------------------------------
# Save Formulas and Save Profile Formulas: the network in the page's formula language
# ---------------------------------------------------------------------------
FORMULA_MAX = 50000


def _level_lit(v):
    return formula_num(v) if isinstance(v, (int, float, np.integer, np.floating)) and not isinstance(v, bool) else formula_str(v)


def _design_texts(M):
    """Each design column as formula text, on its own scale: a continuous factor (its Johnson transform; a
    missing value: the training mean, or the mean of the transforms), its missing column, a categorical factor's
    effect coding (Match of the level: 1, the last level: -1, else 0; a missing level is the last one when the
    fit had it)."""
    P = M.Ps[0]
    out = []
    for e, b in zip(P.enc, M.design.blocks):
        ref = formula_ref(e['name'])
        if b[0] == 'cont':
            j = b[1]
            if j in M.design.johnson:
                kind, a, bb, loc, scale = M.design.johnson[j]
                u = f'(({ref} - {formula_num(loc)}) / {formula_num(scale)})'
                if kind == 'su':
                    z = f'({formula_num(a)} + {formula_num(bb)} * If({u} < 0, -1, 1) * Log(Abs({u}) + Sqrt({u} ^ 2 + 1)))'
                else:
                    uc = f'Min(Max({u}, 1e-12), {formula_num(1 - 1e-12)})'
                    z = f'({formula_num(a)} + {formula_num(bb)} * Log({uc} / (1 - {uc})))'
                fill = M.design.fill.get(j, 0.0)
                # a missing value: the mean of the training rows' transforms, or (a column with none missing in the
                # fit) the transform of the training mean, as the design reads the predictor matrix
                fill = M.design.fill[j] if b[2] is not None else float(johnson_z(M.design.johnson[j], e['fill']))
            else:
                z, fill = ref, e['fill']
            out.append(f'If(Is Missing({ref}), {formula_num(fill)}, {z})' if P.missing == 'informative' else z)
            if b[2] is not None:
                out.append(f'Is Missing({ref})')
        else:
            levels = list(e['levels'])
            last = '.' if e['indicator'] else _level_lit(levels[-1])
            for lv in (levels if e['indicator'] else levels[:-1]):
                mt = f'Match({ref}, {_level_lit(lv)}, 1, {last}, -1, 0)'
                # Informative Missing off: a row missing a factor has no prediction
                out.append(mt if P.missing == 'informative' else f'If(Is Missing({ref}), ., {mt})')
    return out


def _sum_text(W_col, c, ins):
    """c + sum w x as formula text (weights that are 0 left out)."""
    terms = [formula_num(c)] + [f'{formula_num(wv)} * {x}' for wv, x in zip(W_col, ins) if wv != 0]
    return ' + '.join(terms).replace('+ -', '- ')


def _node_text(act, s):
    return {'tanh': f'TanH({s})', 'linear': f'({s})', 'gauss': f'Exp(-(({s}) ^ 2))'}[act]


def network_formulas(M, hidden_refs=None):
    """The network's predictions as formula text: every response's prediction (a continuous one's value; a
    categorical one's Prob[] of each level). hidden_refs: the names of saved hidden-node columns to refer to
    (Save Formulas: {'H1_1': name, ...}); None writes the hidden nodes into each formula (Save Profile Formulas).
    Returns (hidden columns [(name, formula)], response formulas [(name, formula, info)])."""
    layers = _reported_layers(M)
    acts = _node_acts(M)
    nh = len(layers) - 1
    hn = _hnames(nh)
    ins = _design_texts(M)
    hidden_cols = []
    for li in range(nh):
        W, c = layers[li]
        texts = [_node_text(acts[li][i], _sum_text(W[:, i], c[i], ins)) for i in range(W.shape[1])]
        names = [f'{hn[li]}_{i + 1}' for i in range(W.shape[1])]
        hidden_cols += list(zip(names, texts))
        ins = [formula_ref(hidden_refs[nm]) for nm in names] if hidden_refs is not None else [f'({t})' for t in texts]
    Wo, co = layers[-1]
    outs = []
    for P, b in zip(M.Ps, M.T.blocks):
        if b['kind'] == 'cont':
            outs.append((f'Predicted {P.y}', _sum_text(Wo[:, b['a']], co[b['a']], ins), {'kind': 'continuous', 'y': P.y}))
        else:
            th = [f'Exp({_sum_text(Wo[:, j], co[j], ins)})' for j in range(b['a'], b['b'])]
            den = f'(1 + {" + ".join(th)})'
            pref = f'{P.y} ' if len(M.ys) > 1 else ''
            for k, lab in enumerate(P.labels):
                num = th[k] if k < len(th) else '1'
                outs.append((f'{pref}Prob[{lab}]', f'{num} / {den}', {'kind': 'categorical', 'y': P.y, 'level': lab}))
    return hidden_cols, outs


@api('neural.formula')
def formula(table, y, x, rows=None, freq=None, validation=None, seed=None, missing='informative', model=None, holdback=None, what='profile', names=None):
    """Save Profile Formulas (what 'profile': every response's prediction as one formula, the hidden nodes written
    into it), Save Formulas ('formulas': the hidden nodes as formula columns of their own, H1_1, ..., and the
    predictions from them) or Save Transformed Covariates as formulas ('transformed'). The page adds the Most
    Likely column of a categorical response from its Prob[] columns. names: the column each hidden node is saved
    as (Save Formulas; the page takes the names first), {'H1_1': 'H1_1 2', ...}."""
    try:
        M = _model(table, rows, y, x, freq, validation, seed, missing, model, holdback)
    except ValueError as e:
        return {'error': str(e)}
    P0 = M.Ps[0]
    if what == 'transformed':
        texts = _design_texts(M)
        names = _design_names(P0, M.design)
        return {'columns': [{'name': nm, 'expr': tx} for nm, tx in zip(names, texts) if nm.startswith('T(')]}
    if what == 'formulas':
        hidden, _ = network_formulas(M)
        refs = {nm: (names or {}).get(nm, nm) for nm, _ in hidden}
        hidden, outs = network_formulas(M, refs)
        cols = [{'name': nm, 'expr': tx, 'hidden': True} for nm, tx in hidden]
    else:
        _, outs = network_formulas(M)
        cols = []
    cols += [{'name': nm, 'expr': tx, **info} for nm, tx, info in outs]
    too = [c['name'] for c in cols if len(c['expr']) > FORMULA_MAX]
    if too:
        raise ValueError(f'the formula of {too[0]} is too long ({max(len(c["expr"]) for c in cols)} characters, at most {FORMULA_MAX}): Save Formulas writes the hidden nodes as columns of their own')
    most = []
    for P, b in zip(M.Ps, M.T.blocks):
        if b['kind'] == 'cat':
            pref = f'{P.y} ' if len(M.ys) > 1 else ''
            most.append({'names': [f'{pref}Prob[{lab}]' for lab in P.labels], 'levels': list(P.labels), 'most_name': f'Most Likely {P.y}',
                         'ordinal': data.meta(P.table, P.y).get('modelingType') == 'ordinal'})
    return {'columns': cols, 'most': most}


# ---------------------------------------------------------------------------
# the code under a model: the same fit, from a CSV export of the table
# ---------------------------------------------------------------------------

def draw_network(inputs, layers, outputs, title=None):
    """The network as the report's Diagram draws it (smui-p-neural.js), with matplotlib: the X columns as boxes on
    the left, the hidden nodes as circles with their activation's curve (the layer next to the X's first; layers:
    each layer's nodes' activations, 'tanh', 'linear' or 'gauss'), the responses as boxes on the right, and a
    line for every connection. The sizes are the page's, in pixels at 100 an inch."""
    import math
    import matplotlib.pyplot as plt
    from matplotlib.collections import LineCollection
    from matplotlib.patches import Circle, PathPatch, Rectangle
    from matplotlib.path import Path
    pt = 0.72   # points per pixel
    ink, muted = '#352921', '#786b5d'
    fills = {'in': ('#dce8f4', '#2f6690'), 'hid': ('#ddf0da', '#3a7d44'), 'out': ('#d4efeb', '#1b7a70')}
    M_, L_, C_ = Path.MOVETO, Path.LINETO, Path.CURVE4
    glyphs = {'tanh': ([(-6, 4), (-1.5, 4), (1.5, -4), (6, -4)], [M_, C_, C_, C_]),
              'linear': ([(-6, 5), (6, -5)], [M_, L_]),
              'gauss': ([(-6, 4), (-2.5, 4), (-1.5, -4.5), (0, -4.5), (1.5, -4.5), (2.5, 4), (6, 4)], [M_, C_, C_, C_, C_, C_, C_])}

    def short(v, n=22):
        v = str(v)
        return v[:n - 1] + '…' if len(v) > n else v
    sizes = [len(la) for la in layers]
    n_in, n_out, nh = len(inputs), len(outputs), len(layers)
    most = max([n_in, n_out] + sizes)
    sp = 34 if most <= 12 else 24 if most <= 30 else 16
    r = 11 if sp >= 30 else 9 if sp >= 24 else 6
    pad, top, gap = 16, 28, 120
    in_w = min(170, max(56, 7 * max(len(short(c)) for c in inputs) + 16))
    out_w = min(170, max(56, 7 * max(len(short(c)) for c in outputs) + 16))
    cols = [pad + in_w / 2] + [pad + in_w + gap * (i + 1) for i in range(nh)] + [pad + in_w + gap * (nh + 1) + out_w / 2]
    W, H = math.ceil(cols[-1] + out_w / 2 + pad), math.ceil(top + most * sp + pad)

    def y_of(i, n):
        return top + most * sp / 2 + (i - (n - 1) / 2) * sp
    fig = plt.figure(figsize=(W / 100, (H + 30) / 100))   # and a line for the title
    ax = fig.add_axes([0, 0, 1, H / (H + 30)])
    ax.set_xlim(0, W)
    ax.set_ylim(H, 0)   # y down, as on the page
    ax.axis('off')
    ax.set_title(title or f'Network diagram: {n_in} inputs, {" and ".join(str(n) for n in sizes)} hidden nodes, {n_out} output{"s" if n_out > 1 else ""}', fontsize=9)
    names = ['H2', 'H1'] if nh == 2 else ['H1']
    for i, c in enumerate(['Inputs'] + names[:nh] + ['Outputs']):
        ax.text(cols[i], 14, c, ha='center', fontsize=10.5 * pt, color=muted)
    segs = [[(cols[0] + in_w / 2, y_of(j, n_in)), (cols[1] - r, y_of(k, sizes[0]))] for j in range(n_in) for k in range(sizes[0])]
    for li in range(1, nh):
        segs += [[(cols[li] + r, y_of(a, sizes[li - 1])), (cols[li + 1] - r, y_of(b, sizes[li]))] for a in range(sizes[li - 1]) for b in range(sizes[li])]
    segs += [[(cols[nh] + r, y_of(a, sizes[-1])), (cols[nh + 1] - out_w / 2, y_of(i, n_out))] for a in range(sizes[-1]) for i in range(n_out)]
    ax.add_collection(LineCollection(segs, colors=muted, alpha=0.5, linewidths=pt, zorder=0.5))   # every weight
    for j, c in enumerate(inputs):
        y0 = y_of(j, n_in)
        ax.add_patch(Rectangle((cols[0] - in_w / 2, y0 - 10), in_w, 20, facecolor=fills['in'][0], edgecolor=fills['in'][1], linewidth=1.2 * pt))
        ax.text(cols[0], y0 + 4, short(c), ha='center', fontsize=11 * pt, color=ink)
    for li, la in enumerate(layers):
        for k, act in enumerate(la):
            x0, y0 = cols[li + 1], y_of(k, len(la))
            ax.add_patch(Circle((x0, y0), r, facecolor=fills['hid'][0], edgecolor=fills['hid'][1], linewidth=1.4 * pt))
            if r >= 9:   # the activation's curve, as the page draws it
                vs, codes = glyphs.get(act, glyphs['tanh'])
                ax.add_patch(PathPatch(Path([(x0 + u * r / 11, y0 + v * r / 11) for u, v in vs], codes), facecolor='none', edgecolor=ink, linewidth=1.5 * pt, capstyle='round'))
    for i, c in enumerate(outputs):
        y0 = y_of(i, n_out)
        ax.add_patch(Rectangle((cols[-1] - out_w / 2, y0 - 10), out_w, 20, facecolor=fills['out'][0], edgecolor=fills['out'][1], linewidth=1.2 * pt))
        ax.text(cols[-1], y0 + 4, short(c), ha='center', fontsize=11 * pt, color=ink)
    return fig, ax


def _diagram_tail(M):
    """The Diagram: draw_network on the X columns, the fitted network's hidden layers and the responses."""
    d = _diagram(M)
    ins, outs = [c['name'] for c in d['inputs']], [o['name'] for o in d['outputs']]
    return '\n'.join([inspect.getsource(draw_network).rstrip(), '', '',
                      'acts = [[ACTIVATIONS[c] for c in code] for code in fitted_model.codes]   # each hidden node\'s activation, the layer next to the X\'s first',
                      f'draw_network({json.dumps(ins)}, acts, {json.dumps(outs)})   # the X columns, the hidden layers fitted, the responses',
                      'plt.show()'])


def _levels_code(P, var):
    """The lines that make a categorical response's level index, as P.code does."""
    lv = '[' + ', '.join(predictive._pylit(v) for v in P.levels) + ']'
    numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in P.levels)
    src = f'pd.to_numeric(d[{json.dumps(P.y)}], errors="coerce")' if numeric else f'd[{json.dumps(P.y)}].astype(object)'
    return [f'{var} = pd.Categorical({src}, categories={lv}).codes   # the index of the level']


def _code(M, table_name, graph=False):
    """The code under a model: the network fitted as the report fits it, from a CSV export of the table, printing
    each set's measures. graph: the head of the graphs' code instead (predictive.graph_codes): matplotlib
    imported, no printing, and every response's values and predictions (Y, pred, levels_of) for the graphs."""
    s = M.spec
    P0 = M.Ps[0]
    L = P0.code(table_name, M.rows, extra_imports=[predictive.PLT] if graph else [])
    if len(M.ys) > 1:       # every response in d (P.code knows the first)
        sp = P0.spec
        cols = list(dict.fromkeys(list(M.ys) + list(P0.x) + [c for c in (sp.get('weight'), sp.get('freq'), sp.get('validation')) if c]))
        for i, line in enumerate(L):
            if line.startswith('d = df['):
                L[i] = f'd = df[{json.dumps(cols)}]'
                break
    # the splits that P.code cannot know: KFold's, and the excluded rows'
    zero = 'sets = np.zeros(len(d), dtype=int)   # every row trains the model'
    n = len(P0.index)
    if M.method == 'kfold' and zero in L:
        i = L.index(zero)
        L[i:i + 1] = [f'folds = np.empty(len(d), dtype=int); folds[np.random.default_rng({M.seed}).permutation(len(d))] = np.arange(len(d)) % {s["folds"]}   # KFold: the folds',
                      'sets = np.zeros(len(d), dtype=int)']
    elif M.method == 'excluded' and zero in L:
        held = [int(r) for r, (k) in zip(P0.index, P0.sets) if k == 1]
        L[L.index(zero)] = f'sets = d.index.isin({held}).astype(int)   # Excluded Rows Holdback: the excluded rows validate'
    head_end = len(L)   # the table's rows and the predictor matrix; the engine, then the fit
    L.append('wt = np.ones(len(d)) if w is None else w')
    L.append('everyone = np.arange(len(d))')
    if M.method in ('kfold', 'folds'):
        L.append(f'splits = [(everyone[folds != k], everyone[folds == k]) for k in range({len(M.splits)})]   # each fold validates the model of the others')
        L.append('design_rows = everyone   # KFold: the design from every row (it takes the factors only)')
    else:
        L.append('splits = [(everyone[sets == 0], everyone[sets == 1])]   # the training rows, the validation rows')
        L.append('design_rows = splits[0][0]')
    blocks = _blocks(P0)
    L.append(f'design = Design({blocks!r}, transform={s["transform"]}).fit(X, wt, design_rows)   # JMP\'s design: effect coding{", Johnson transforms" if s["transform"] else ""}, centred and scaled')
    L.append('Z = design.apply(X)')
    # the responses: the first is y (P.code); the others read here
    ys_lines, kinds = [], []
    for j, P in enumerate(M.Ps):
        var = f'y{j}'
        if j == 0:
            ys_lines.append(f'{var} = y')
        elif P.kind == 'categorical':
            ys_lines += _levels_code(P, var)
        else:
            ys_lines.append(f'{var} = d[{json.dumps(P.y)}].to_numpy(float)')
        kinds.append(len(P.levels) if P.kind == 'categorical' else 0)
    L += ys_lines
    L.append(f'T = Targets([{", ".join(f"y{j}" for j in range(len(M.Ps)))}], {kinds}, wt, np.isin(everyone, design_rows), robust={M.T.robust})   # every response in one network')
    spec = {k: s[k] for k in ('penalty', 'tours', 'max_iter', 'boost', 'rate')}
    L.append(f'res = fit_neural(Z, T, splits, {layers_of(s)!r}, {spec!r}, seed={M.seed})   # Model {name_of(s)}: tours, the penalty path{", boosting" if s["boost"] else ""}, early stopping')
    L.append('fitted_model = res["model"]')
    if M.method in ('kfold', 'folds'):
        L.append('sets = np.where(folds == res["fold"], 1, 0)   # the fold whose model fits every row best validates it')
    L.append('pred = fitted_model.predict(Z)   # each response\'s prediction: its value, or its levels\' probabilities')
    if graph:
        L.append(f'Y = np.column_stack([{", ".join(f"y{j}" for j in range(len(M.Ps)))}]).astype(float)   # the responses, for the graphs')
        L.append(f'levels_of = {[list(P.labels) if P.kind == "categorical" else None for P in M.Ps]!r}   # each categorical response\'s levels')
        L.append('pred = [p if p.ndim == 1 else np.clip(p, 1e-15, 1 - 1e-15) / np.clip(p, 1e-15, 1 - 1e-15).sum(axis=1, keepdims=True) for p in pred]')
        return SEP.join(['\n'.join(L[:head_end]), engine_source(), '\n'.join(L[head_end:])])
    for j, P in enumerate(M.Ps):
        L.append('')
        L.append(f'# the measures of {P.y}')
        L.append('for k, name in enumerate(["Training", "Validation", "Test"]):')
        L.append('    m = sets == k')
        L.append('    if m.any():')
        if P.kind == 'continuous':
            L.append(f'        r = y{j}[m] - pred[{j}][m]')
            L.append(f'        sse, sst = np.sum(wt[m] * r ** 2), np.sum(wt[m] * (y{j}[m] - np.average(y{j}[m], weights=wt[m])) ** 2)')
            L.append(f'        print({json.dumps(P.y)}, name, "RSquare", 1 - sse / sst, "RASE", np.sqrt(sse / wt[m].sum()))')
        else:
            L.append(f'        p = np.clip(pred[{j}][m], 1e-15, 1)[np.arange(m.sum()), y{j}[m]]')
            L.append(f'        print({json.dumps(P.y)}, name, "-LogLikelihood", -np.sum(wt[m] * np.log(p)), "Misclassification Rate", np.sum(wt[m] * (pred[{j}][m].argmax(axis=1) != y{j}[m])) / wt[m].sum())')
    return SEP.join(['\n'.join(L[:head_end]), engine_source(), '\n'.join(L[head_end:])])
