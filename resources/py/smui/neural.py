"""Analyze > Predictive Modeling > Neural (resources/js/smui-p-neural.js).

JMP's Neural platform on scikit-learn's multilayer perceptrons:
MLPRegressor for continuous responses, MLPClassifier for a categorical
one, fitted by L-BFGS (a quasi-Newton method, as JMP's BFGS is). Each Go
in the report's Model Launch adds a model, fitted here from its settings:

  the design       JMP centres and scales every column of the design row
                   behind the scenes; here a StandardScaler in a Pipeline,
                   fitted on the training rows, does it, and the Estimates
                   are turned back to the columns' own scale. A categorical
                   factor is a 0/1 column per level (predictive.prepare;
                   JMP uses effect coding).
  the responses    JMP fits every response in one network, summing their
                   log-likelihoods. MLPRegressor fits several continuous
                   responses in one network: they are fitted together, each
                   standardized by its training mean and standard deviation.
                   MLPClassifier takes one categorical response: each gets a
                   network of its own, with the same structure and sets.
  the penalty      JMP starts with no penalty and then searches its size
                   by the validation likelihood, each fit starting from the
                   one before. Here scikit-learn's alpha (its penalty is
                   JMP's Squared one) runs up GRID from almost none, each
                   fit warm-started from the last, until two steps in a row
                   do not improve the validation likelihood; the best model
                   is kept. JMP also stops each BFGS run when the validation
                   likelihood no longer improves; scikit-learn's L-BFGS runs
                   to its tolerance or max_iter.
  tours            restarts from new random weights; the best validation
                   likelihood is kept.
  KFold            as JMP does it: for each alpha the K fold models, the
                   alpha with the best validation likelihood summed over the
                   folds, then the fold whose model fits every row best.
  boosting         as JMP describes it: base models fitted in turn to what
                   the learning-rate-scaled sum of the ones before leaves,
                   while the validation likelihood improves; the last is not
                   scaled. A categorical response is boosted on the log-odds
                   scale: each base model is fitted to the gradient of the
                   log-likelihood, with a line search.
  transform        Transform Covariates: scikit-learn's PowerTransformer
                   (Yeo-Johnson, standardized) on the continuous factors
                   (JMP fits a Johnson Su or Sb distribution to each).

Everything random comes from the report's seed: the holdback, the folds
and every random_state (from the seed, the tour and the base model).
"""
import copy
import json
import math
import sys
import warnings

import numpy as np
import pandas as pd

from . import data, predictive, profile
from .predictive import SK
from .registry import api

# scikit-learn's alpha, from almost no penalty to a strong one: the penalty
# path (up, as JMP searches: from a network fitted without a penalty; down
# from a strong penalty a two-layer network stays at the zero saddle)
GRID = (0.001, 0.01, 0.03, 0.1, 0.3, 1.0, 3.0, 10.0, 30.0)
NO_VALIDATION_ALPHA = 1e-4          # scikit-learn's default, when no rows validate
ACT = {'tanh': 'TanH', 'logistic': 'Logistic', 'relu': 'ReLU', 'identity': 'Linear'}
METHOD_LABEL = {'holdback': 'Random Holdback', 'kfold': 'KFold', 'excluded': 'Excluded Rows Holdback', 'column': 'Validation Column'}
EPS = 1e-15


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
    """The Model Launch settings, checked, with JMP's defaults."""
    m = dict(model or {})
    act = m.get('activation') or 'tanh'
    if act not in ACT:
        raise ValueError(f'unknown activation {act!r}: scikit-learn has tanh, logistic, relu and identity')
    method = m.get('method') or 'holdback'
    if method not in METHOD_LABEL:
        raise ValueError(f'unknown validation method {method!r}')
    penalty = m.get('penalty') or 'squared'
    if penalty in ('absolute', 'weight_decay'):
        raise ValueError('scikit-learn\'s MLP has only the Squared penalty (alpha): Absolute and Weight Decay are not in it')
    if penalty not in ('squared', 'none'):
        raise ValueError(f'unknown penalty method {penalty!r}')
    if m.get('robust'):
        raise ValueError('Robust Fit (least absolute deviations) is not in scikit-learn\'s MLP, whose loss is squared error')
    s = {
        'method': method,
        'portion': _num(m, 'portion', 0.3333, 0.0, 1.0, 'The Holdback Proportion', open_lo=True) if method == 'holdback' else None,
        'folds': _num(m, 'folds', 5, 2, 50, 'The Number of Folds', integer=True) if method == 'kfold' else None,
        'activation': act,
        'n1': _num(m, 'n1', 3, 1, 500, 'The first layer\'s nodes', integer=True),
        'n2': _num(m, 'n2', 0, 0, 500, 'The second layer\'s nodes', integer=True),
        'boost': _num(m, 'boost', 0, 0, 1000, 'The Number of Models', integer=True),
        'rate': _num(m, 'rate', 0.1, 0.0, 1.0, 'The Learning Rate', open_lo=True),
        'transform': bool(m.get('transform')),
        'penalty': penalty,
        'tours': _num(m, 'tours', 1, 1, 100, 'The Number of Tours', integer=True),
        'max_iter': _num(m, 'max_iter', 200, 1, 100000, 'The Maximum Iterations', integer=True),
    }
    if s['portion'] is not None and s['portion'] >= 1:
        raise ValueError('The Holdback Proportion is below 1')
    if s['boost']:
        s['n2'] = 0     # JMP: boosting takes one layer; a second is ignored
    else:
        s['rate'] = None
    return s


def name_of(s):
    """JMP's name of the model: NTanH(3), NTanH(3)NTanH2(2), NTanH(2)NBoost(10)."""
    a = ACT[s['activation']]
    out = f'N{a}({s["n1"]})'
    if s['n2']:
        out += f'N{a}2({s["n2"]})'
    if s['boost']:
        out += f'NBoost({s["boost"]})'
    return out


def _layers(s):
    """scikit-learn's hidden_layer_sizes, inputs first. JMP's second layer is
    the one next to the X's, so it comes first here."""
    return (s['n2'], s['n1']) if s['n2'] else (s['n1'],)


def _rs(seed, *k):
    """The random_state of one fit, from the report's seed and the tour (and
    the base model of a boosted network)."""
    ss = np.random.SeedSequence([int(seed) % (2 ** 32)] + [int(v) for v in k])
    return int(ss.generate_state(1)[0] % (2 ** 31 - 1))


# ---------------------------------------------------------------------------
# the design of every split of the rows
# ---------------------------------------------------------------------------

def _x_with_fills(P, sets):
    """X with Informative Missing's fills taken from the training rows of
    these sets; returns (X, the encoding)."""
    tr = np.asarray(sets) == 0
    frame = data.frame(P.table, P.x, P.index.tolist(), dropna=False)
    enc = copy.deepcopy(P.enc)
    for e in enc:
        if e['type'] == 'continuous':
            v = pd.to_numeric(frame[e['name']], errors='coerce').to_numpy(float)
            fin = np.isfinite(v)
            trv = v[tr & fin]
            e['fill'] = float(np.mean(trv)) if len(trv) else float(np.mean(v[fin]))
    keep = P.enc
    P.enc = enc
    try:
        X, _ = P.encode(frame)
    finally:
        P.enc = keep
    return X, enc


def _apply_sets(P, sets):
    """Give P these sets, with the fills of their training rows."""
    if P.missing == 'informative':
        P.X, P.enc = _x_with_fills(P, sets)
    P.sets = np.asarray(sets, dtype=int)


def _cont_columns(P):
    """The columns of X that hold a continuous factor's values (not its
    Missing column): the ones Transform Covariates transforms."""
    return [P.groups[e['name']][0] for e in P.enc if e['type'] == 'continuous']


class _Transform:
    """Transform Covariates: a PowerTransformer on the continuous columns,
    fitted on the training rows. Columns constant there are left alone."""

    def __init__(self, cols, X, tr):
        from sklearn.preprocessing import PowerTransformer
        Xt = X[tr]
        self.cols = [j for j in cols if len(Xt) and np.ptp(Xt[:, j]) > 0]
        self.pt = PowerTransformer().fit(Xt[:, self.cols]) if self.cols else None

    def __call__(self, X):
        if not self.cols:
            return X
        X = np.array(X, dtype=float, copy=True)
        X[:, self.cols] = self.pt.transform(X[:, self.cols])
        return X


class _Design:
    """One split of the rows into training and validation: X with the
    split's fills, the transform fitted on its training rows, the weights."""

    def __init__(self, P, sets, spec, cont):
        self.sets = np.asarray(sets, dtype=int)
        self.tr = self.sets == 0
        self.va = self.sets == 1
        self.X = _x_with_fills(P, self.sets)[0] if P.missing == 'informative' else P.X
        self.transform = _Transform(cont, self.X, self.tr) if spec['transform'] else None
        self.Xt = self.transform(self.X) if self.transform else self.X
        self.w = P.w
        self.wt = np.ones(len(P.index)) if P.w is None else P.w
        self.fw = {} if P.w is None else {'scale__sample_weight': P.w[self.tr], 'mlp__sample_weight': P.w[self.tr]}


class _Split:
    """A design and one network's target on it."""

    def __init__(self, d, kind, Ys, L=None):
        self.__dict__.update(d.__dict__)
        self.kind = kind
        if kind == 'continuous':
            Y = np.column_stack(Ys)
            self.Y = Y
            mu = np.average(Y[self.tr], axis=0, weights=self.wt[self.tr])
            sd = np.sqrt(np.average((Y[self.tr] - mu) ** 2, axis=0, weights=self.wt[self.tr]))
            self.mu, self.sd = mu, np.where(sd > 0, sd, 1.0)
            Z = (Y - self.mu) / self.sd
            self.Z = Z[:, 0] if Z.shape[1] == 1 else Z
        else:
            self.y = np.asarray(Ys[0], dtype=int)
            self.L = int(L)
            self.Yh = np.eye(self.L)[self.y]

    def nll(self, fitted, m):
        """-log likelihood of rows m: fitted is the prediction on the
        responses' scale (n x c), or the level probabilities (n x L); a
        normal likelihood with variance SSE/N for each continuous response."""
        if not m.any():
            return None
        w = self.wt[m]
        N = float(w.sum())
        if self.kind == 'continuous':
            r = self.Y[m] - fitted[m]
            sse = np.sum(w[:, None] * r * r, axis=0)
            return float(np.sum(0.5 * N * (np.log(2 * np.pi * np.maximum(sse, 1e-300) / N) + 1)))
        p = fitted[m][np.arange(int(m.sum())), self.y[m]]
        return float(-np.sum(w * np.log(np.clip(p, EPS, 1.0))))

    def scores(self, fitted):
        return self.nll(fitted, self.tr), self.nll(fitted, self.va)

    def g0(self):
        """The log odds a boosted network starts from: the training shares."""
        wt = self.wt[self.tr]
        share = np.array([wt[self.y[self.tr] == j].sum() for j in range(self.L)]) / wt.sum()
        return np.log(np.clip(share, 1e-15, None))


# ---------------------------------------------------------------------------
# networks
# ---------------------------------------------------------------------------

def _clip(p):
    """Probabilities never exactly 0 or 1 (the model never gives them)."""
    p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
    return p / p.sum(axis=1, keepdims=True)


def _softmax(G):
    E = np.exp(G - G.max(axis=1, keepdims=True))
    return E / E.sum(axis=1, keepdims=True)


def _pipeline(s, rs, classifier):
    from sklearn.neural_network import MLPClassifier, MLPRegressor
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import StandardScaler
    cls = MLPClassifier if classifier else MLPRegressor
    mlp = cls(hidden_layer_sizes=_layers(s), activation=s['activation'], solver='lbfgs', max_iter=s['max_iter'], random_state=rs, warm_start=True)
    return Pipeline([('scale', StandardScaler()), ('mlp', mlp)])


def _fit(est, X, y, fw):
    """est.fit, with its warnings kept aside: only the chosen fits' reach
    the report."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter('always')
        est.fit(X, y, **fw)
    return [(w.category, str(w.message)) for w in caught]


def _out(est, X, shape=None):
    """A regressor's output as an n x c array (or the shape given)."""
    f = np.asarray(est.predict(X), dtype=float)
    return f.reshape(len(X), -1) if shape is None else f.reshape(shape)


def _proba_of(est, X, L):
    p = np.zeros((len(X), L))
    p[:, est.classes_] = est.predict_proba(X)
    return _clip(p)


class _Net:
    """A fitted network: its responses and what predicts them. parts are
    [(pipeline, weight)]: one for a plain network, the base models of a
    boosted one (their weighted sum, on the standardized scale or on the
    log-odds scale)."""

    def __init__(self, kind, resp):
        self.kind = kind
        self.resp = resp            # indices of the model's responses
        self.parts = []
        self.transform = None
        self.mu = self.sd = None
        self.g0 = None
        self.L = None
        self.boosted = False
        self.info = {}

    def xt(self, X):
        return self.transform(X) if self.transform else X

    def raw(self, Xt):
        """The sum of the parts on transformed rows: the standardized
        predictions, or the log odds of a boosted categorical network."""
        F = None if self.g0 is None else np.tile(self.g0, (len(Xt), 1))
        for est, s in self.parts:
            f = s * _out(est, Xt)
            F = f if F is None else F + f
        return F

    def fitted_t(self, Xt):
        if self.kind == 'continuous':
            return self.mu + self.sd * self.raw(Xt)
        if not self.boosted:
            return _proba_of(self.parts[0][0], Xt, self.L)
        return _clip(_softmax(self.raw(Xt)))

    def fitted(self, X):
        """Continuous: n x c predictions; categorical: n x L probabilities in
        the table's level order."""
        return self.fitted_t(self.xt(X))

    def predict(self, X):
        return self.fitted(X)

    def proba(self, X):
        return self.fitted(X)

    def classes(self):
        """The levels (indices) the output layer has."""
        if self.boosted:
            return list(range(self.L))
        return [int(c) for c in self.parts[0][0].classes_]


class _Ticker:
    """'smui:progress neural <done> <total>' lines for the page (only in
    Pyodide), about ten per model."""

    def __init__(self, total):
        self.total = max(1, int(total))
        self.done = 0
        self.next = 0.1
        self.on = sys.platform == 'emscripten' and self.total >= 12

    def __call__(self):
        self.done += 1
        if self.on and self.done >= self.next * self.total:
            print(f'smui:progress neural {min(self.done, self.total)} {self.total}', flush=True)
            while self.next * self.total <= self.done:
                self.next += 0.1


def _alphas(s, splits):
    if s['penalty'] == 'none':
        return (0.0,)
    if not any(sp.va.any() for sp in splits):
        return (NO_VALIDATION_ALPHA,)
    return GRID


def _plain_model(sp, est):
    """A plain network's prediction on its split's rows."""
    if sp.kind == 'continuous':
        return sp.mu + sp.sd * _out(est, sp.Xt)
    return _proba_of(est, sp.Xt, sp.L)


def _joint_path(splits, s, rs, tick, classifier, target, model):
    """Each split's network up the penalty path, warm-started; the alpha
    whose models have the best validation likelihood summed over the splits
    (the training likelihood when no rows validate). target(split) is what
    the networks fit, model(split, est) the prediction scored. Returns the
    best alpha's networks (copies) and the path."""
    alphas = _alphas(s, splits)
    validate = any(sp.va.any() for sp in splits)
    chains = [_pipeline(s, rs, classifier) for _ in splits]
    best, path, worse = None, [], 0
    for a in alphas:
        caught, tr_s, va_s, iters = [], 0.0, 0.0, []
        for sp, est in zip(splits, chains):
            est.set_params(mlp__alpha=a)
            caught.append(_fit(est, sp.Xt[sp.tr], target(sp)[sp.tr], sp.fw))
            t, v = sp.scores(model(sp, est))
            tr_s += t
            va_s += v or 0.0
            iters.append(int(est[-1].n_iter_))
            tick()
        crit = va_s if validate else tr_s
        path.append({'alpha': a, 'iterations': iters[0] if len(iters) == 1 else float(np.mean(iters)), 'train': tr_s, 'valid': va_s if validate else None})
        if best is None or crit < best['crit']:
            best = {'alpha': a, 'crit': crit, 'est': [copy.deepcopy(e) for e in chains], 'caught': caught, 'index': len(path) - 1}
            worse = 0
        else:
            worse += 1
            if worse >= 2:
                break
    for i, r in enumerate(path):
        r['chosen'] = i == best['index']
    best['alphas'] = [r['alpha'] for r in path[:best['index'] + 1]]
    return best, path


def _line_search(sp, G, f):
    """The step on the log-odds scale that most improves the training
    likelihood (a categorical response's boosting)."""
    from scipy.optimize import minimize_scalar
    rows = np.flatnonzero(sp.tr)
    wt, yy = sp.wt[rows], sp.y[rows]
    Gt, ft = G[rows], f[rows]

    def nll(r):
        return -np.sum(wt * np.log(np.clip(_softmax(Gt + r * ft)[np.arange(len(rows)), yy], 1e-15, None)))
    return float(minimize_scalar(nll, bounds=(0.0, 100.0), method='bounded').x)


def _boost(sp, s, rs_list, tick, first, alpha):
    """Boost one split, JMP's way: base models fitted in turn to what the
    ones before leave, each scaled by the learning rate, while the
    validation likelihood improves (the training one without validation
    rows), up to the Number of Models; the last kept is not scaled.
    first: the first base model (already up the penalty path)."""
    nu = s['rate']
    cont = sp.kind == 'continuous'
    n = len(sp.sets)
    if cont:
        F = np.zeros(sp.Z.shape)
        fitted = lambda F_: sp.mu + sp.sd * F_.reshape(n, -1)
        g0 = None
    else:
        g0 = sp.g0()
        F = np.tile(g0, (n, 1))
        fitted = lambda G_: _clip(_softmax(G_))
    prev = sp.scores(fitted(F))
    validate = bool(sp.va.any())
    parts, rows = [], []
    for k in range(s['boost']):
        if k == 0:
            est, caught = first
        else:
            est = _pipeline(s, rs_list[k], False)
            est.set_params(mlp__alpha=alpha)
            target = (sp.Z - F) if cont else (sp.Yh - _softmax(F))
            caught = _fit(est, sp.Xt[sp.tr], target[sp.tr], sp.fw)
            tick()
        f = _out(est, sp.Xt, F.shape)
        rho = 1.0 if cont else _line_search(sp, F, f)
        Fk = F + nu * rho * f
        sc = sp.scores(fitted(Fk))
        better = (sc[1] < prev[1]) if validate else (sc[0] < prev[0])
        rows.append({'model': k + 1, 'step': rho, 'train': sc[0], 'valid': sc[1], 'kept': bool(better)})
        if not better and parts:
            break
        parts.append({'est': est, 'rho': rho, 'caught': caught})
        F, prev = Fk, sc
        if not better:          # not even the first improved: it stays, alone
            rows[-1]['kept'] = True
            break
    for i, p in enumerate(parts):
        # the last base model is not scaled by the learning rate
        p['w'] = (nu * p['rho']) if i < len(parts) - 1 else (1.0 * p['rho'])
    return {'parts': parts, 'rows': rows, 'g0': g0}


def _fit_network(kind, resp, splits, s, rs, seed, t, tick):
    """One network on every split, for one tour. Returns the network of each
    split, the chosen alpha and its path, and the criteria that choose the
    tour (the validation likelihood summed over the splits) and the fold
    (the likelihood of every row)."""
    out = {'nets': [], 'iterations': [], 'boost_rows': [], 'caught': [], 'random_states': [rs]}
    classifier = kind == 'categorical' and not s['boost']
    if not s['boost']:
        target = (lambda sp: sp.Z) if kind == 'continuous' else (lambda sp: sp.y)
        best, path = _joint_path(splits, s, rs, tick, classifier, target, _plain_model)
        for sp, est, caught in zip(splits, best['est'], best['caught']):
            net = _Net(kind, resp)
            net.parts = [(est, 1.0)]
            net.transform = sp.transform
            if kind == 'continuous':
                net.mu, net.sd = sp.mu, sp.sd
            else:
                net.L = sp.L
            out['nets'].append(net)
            out['iterations'].append(int(est[-1].n_iter_))
            out['caught'].append(caught)
    else:
        # the first base model up the penalty path, scored as a model of
        # its own target (the standardized responses, or the first gradient)
        rs_list = [rs] + [_rs(seed, t, k) for k in range(1, s['boost'])]
        out['random_states'] = rs_list
        if kind == 'continuous':
            target = lambda sp: sp.Z
            model = _plain_model
        else:
            target = lambda sp: sp.Yh - _softmax(np.tile(sp.g0(), (len(sp.sets), 1)))

            def model(sp, est):
                G = np.tile(sp.g0(), (len(sp.sets), 1))
                f = _out(est, sp.Xt, G.shape)
                return _clip(_softmax(G + _line_search(sp, G, f) * f))
        best, path = _joint_path(splits, s, rs, tick, False, target, model)
        for sp, est, caught in zip(splits, best['est'], best['caught']):
            b = _boost(sp, s, rs_list, tick, (est, caught), best['alpha'])
            net = _Net(kind, resp)
            net.boosted = True
            net.parts = [(p['est'], float(p['w'])) for p in b['parts']]
            net.transform = sp.transform
            if kind == 'continuous':
                net.mu, net.sd = sp.mu, sp.sd
            else:
                net.L, net.g0 = sp.L, b['g0']
            net.info['steps'] = [float(p['rho']) for p in b['parts']]
            out['nets'].append(net)
            out['iterations'].append([int(p['est'][-1].n_iter_) for p in b['parts']])
            out['boost_rows'].append(b['rows'])
            out['caught'].append([c for p in b['parts'] for c in p['caught']])
    out['alpha'], out['path'], out['alphas'] = best['alpha'], path, best['alphas']
    validate = any(sp.va.any() for sp in splits)
    crit, fold_valid, full = 0.0, [], []
    for sp, net in zip(splits, out['nets']):
        fitted = net.fitted_t(sp.Xt)
        tr_s, va_s = sp.scores(fitted)
        fold_valid.append(va_s)
        full.append(sp.nll(fitted, np.ones(len(sp.sets), dtype=bool)))
        crit += va_s if validate else tr_s
    out['crit'], out['fold_valid'], out['full'] = crit, fold_valid, full
    return out


# ---------------------------------------------------------------------------
# a model: every network, fitted on the report's rows
# ---------------------------------------------------------------------------

class _Model:
    """A fitted model: ys, x, Ps (one Prepared per response, with the final
    sets), nets, the validation method and what chose the fit."""


def _responses(y):
    ys = y if isinstance(y, (list, tuple)) else [y]
    ys = [c for c in dict.fromkeys(ys) if c]
    if not ys:
        raise ValueError('choose a Y, Response')
    return ys


def _build(table, rows, ys, x, freq, validation, seed, missing, s, holdback):
    """Fit the model: what the report, the profiler and Save use."""
    M = _Model()
    M.ys, M.spec, M.seed = ys, s, int(seed)
    x = [c for c in dict.fromkeys(x or []) if c and c not in ys]
    if not x:
        raise ValueError('choose at least one X, Factor (other than the responses)')
    M.x = x
    M.notes = []
    # the rows with every response (scikit-learn takes no missing response)
    df = data.frame(table, ys, rows, dropna=False)
    ok = np.ones(len(df), dtype=bool)
    for c in ys:
        if data.is_categorical(table, c):
            ok &= df[c].notna().to_numpy()
        else:
            ok &= np.isfinite(pd.to_numeric(df[c], errors='coerce').to_numpy(float))
    if (~ok).sum():
        M.notes.append(f'{int((~ok).sum())} rows with no {ys[0]} are left out.' if len(ys) == 1 else
                       f'{int((~ok).sum())} rows missing one of the responses are left out: the networks take only rows with every response.')
    use = None if (rows is None and ok.all()) else [int(r) for r in np.asarray(df.index)[ok]]
    if use is not None and not use:
        raise ValueError('no rows with every response')
    M.rows = use
    method = 'column' if validation else s['method']
    if method == 'column' and not validation:
        raise ValueError('Validation Column: cast a column into the Validation role')
    M.method = method
    portion = s['portion'] if method == 'holdback' else 0.0
    M.Ps = [predictive.prepare(table, c, x, rows=use, freq=freq, validation=validation, portion=portion, seed=seed, missing=missing) for c in ys]
    P0 = M.Ps[0]
    n = len(P0.index)
    M.notes += [t for t in P0.notes if t not in M.notes]
    # the splits: one, or one per fold
    folds = None
    if method == 'excluded':
        hb = {int(r) for r in (holdback or [])}
        base = np.array([1 if int(r) in hb else 0 for r in P0.index], dtype=int)
        if base.all():
            raise ValueError('Excluded Rows Holdback: every row is excluded, so none trains the model')
        split_sets = [base]
    elif method == 'kfold':
        K = s['folds']
        if K > n:
            raise ValueError(f'KFold: {K} folds need at least {K} rows; there are {n}')
        folds = np.empty(n, dtype=int)
        folds[np.random.default_rng(int(seed)).permutation(n)] = np.arange(n) % K
        split_sets = [(folds == k).astype(int) for k in range(K)]
    else:
        split_sets = [P0.sets.copy()]
    M.folds = folds
    # the networks: the continuous responses together, each categorical one alone
    cont = [j for j, P in enumerate(M.Ps) if P.kind == 'continuous']
    groups = ([('continuous', cont)] if cont else []) + [('categorical', [j]) for j, P in enumerate(M.Ps) if P.kind == 'categorical']
    cols = _cont_columns(P0) if s['transform'] else []
    designs = [_Design(P0, ss, s, cols) for ss in split_sets]
    splits = [[_Split(d, kind, [M.Ps[j].target for j in resp], len(M.Ps[resp[0]].levels) if kind == 'categorical' else None) for d in designs] for kind, resp in groups]
    K = len(split_sets)
    per_fit = (len(GRID) if s['penalty'] == 'squared' else 1) + max(0, s['boost'] - 1)
    tick = _Ticker(s['tours'] * K * per_fit * len(groups))
    # every network is fitted on the same splits; the tour and, for KFold,
    # the fold are chosen by the likelihood of every network together
    results, tour_rows = [], []
    for t in range(s['tours']):
        rs = _rs(seed, t)
        per_net = [_fit_network(kind, resp, sps, s, rs, seed, t, tick) for (kind, resp), sps in zip(groups, splits)]
        results.append(per_net)
        tour_rows.append({'tour': t + 1, 'random_state': rs, 'criterion': sum(r['crit'] for r in per_net)})
    best_t = int(np.argmin([r['criterion'] for r in tour_rows]))
    for i, r in enumerate(tour_rows):
        r['chosen'] = i == best_t
    M.tours, M.tour = tour_rows, best_t
    chosen = results[best_t]
    k_best = 0
    M.fold_rows = []
    if method == 'kfold':
        full = np.sum([r['full'] for r in chosen], axis=0)
        valid = np.sum([r['fold_valid'] for r in chosen], axis=0)
        k_best = int(np.argmin(full))
        M.fold_rows = [{'fold': k + 1, 'rows': int((folds == k).sum()), 'valid': float(valid[k]), 'all': float(full[k]), 'chosen': k == k_best} for k in range(K)]
    M.fold = k_best
    for P in M.Ps:
        _apply_sets(P, split_sets[k_best])
    M.nets = []
    for (kind, resp), r in zip(groups, chosen):
        net = r['nets'][k_best]
        net.info.update({'alpha': r['alpha'], 'path': r['path'], 'alphas': r['alphas'], 'iterations': r['iterations'][k_best],
                         'boost': r['boost_rows'][k_best] if r['boost_rows'] else None,
                         'random_states': r['random_states'], 'caught': r['caught'][k_best]})
        M.nets.append(net)
    M.X = M.Ps[0].X
    return M


def _model(table, rows, y, x, freq, validation, seed, missing, model, holdback):
    ys = _responses(y)
    s = spec_of(model)
    seed = predictive.seed_of(seed)
    if seed is None:
        raise ValueError('the model needs a random seed')
    key = {'y': ys, 'x': list(x or []), 'freq': freq, 'validation': validation, 'seed': seed, 'missing': missing, 'spec': s,
           'holdback': predictive.rows_sig(holdback) if s['method'] == 'excluded' and not validation else None}
    return predictive.cached('neural', table, rows, key, lambda: _build(table, rows, ys, x, freq, validation, seed, missing, s, holdback))


# ---------------------------------------------------------------------------
# what the report shows
# ---------------------------------------------------------------------------

def _act(name, a):
    if name == 'tanh':
        return np.tanh(a)
    if name == 'logistic':
        return 1.0 / (1.0 + np.exp(-a))
    if name == 'relu':
        return np.maximum(a, 0.0)
    return a


def _layer_params(est):
    """A pipeline's weights, the first layer on the scale of its input
    columns (the StandardScaler undone): [(W, b)] from inputs to output."""
    sc, mlp = est[0], est[-1]
    W0, b0 = mlp.coefs_[0], mlp.intercepts_[0]
    W0o = W0 / sc.scale_[:, None]
    b0o = b0 - (sc.mean_ / sc.scale_) @ W0
    return [(W0o, b0o)] + [(mlp.coefs_[i], mlp.intercepts_[i]) for i in range(1, len(mlp.coefs_))]


def _combined(net):
    """The network as one list of layers on the reported scale, [(W, b)]
    from the inputs [through H2] through H1 to the outputs: a boosted
    network's base models side by side in H1; the outputs on the responses'
    scale, or as the log odds of each level against the last (a binary
    response: one output, the first level's)."""
    layers_all = [_layer_params(est) for est, _ in net.parts]
    if not net.boosted:
        L = layers_all[0]
        W, b = L[-1]
        if net.kind == 'continuous':
            W, b = W * net.sd, net.mu + net.sd * b
        elif W.shape[1] == 1:       # scikit-learn's logit of the second level
            W, b = -W, -b
        else:
            W, b = W[:, :-1] - W[:, -1:], b[:-1] - b[-1]
        return L[:-1] + [(W, b)]
    Wh = np.concatenate([L[0][0] for L in layers_all], axis=1)
    bh = np.concatenate([L[0][1] for L in layers_all])
    Wo = np.concatenate([w * L[1][0] for L, (_, w) in zip(layers_all, net.parts)], axis=0)
    bo = sum(w * L[1][1] for L, (_, w) in zip(layers_all, net.parts))
    if net.kind == 'continuous':
        Wo, bo = Wo * net.sd, net.mu + net.sd * bo
    else:
        bo = net.g0 + bo
        Wo, bo = Wo[:, :-1] - Wo[:, -1:], bo[:-1] - bo[-1]
    return [(Wh, bh), (Wo, bo)]


def _out_names(M, net):
    """The output nodes' names: each response, or response[level] for every
    level but the last that the network has (JMP's parameterization)."""
    if net.kind == 'continuous':
        return [M.ys[j] for j in net.resp]
    P = M.Ps[net.resp[0]]
    return [f'{P.y}[{P.labels[c]}]' for c in net.classes()[:-1]]


def _feature_names(M, net):
    P = M.Ps[net.resp[0]]
    feats = list(P.features)
    if net.transform is not None:
        for j in net.transform.cols:
            feats[j] = f'T({feats[j]})'
    return feats


def _estimates(M, net):
    """The Estimates: every weight and bias with JMP's names (H1_1:x1,
    H1_1:Intercept; H2_ for the layer next to the X's; y:H1_1)."""
    layers = _combined(net)
    nh = len(layers) - 1
    hname = ['H2', 'H1'] if nh == 2 else ['H1']
    rows = []
    ins = _feature_names(M, net)
    for li, (W, b) in enumerate(layers):
        outs = [f'{hname[li]}_{i + 1}' for i in range(W.shape[1])] if li < nh else _out_names(M, net)
        for i, o in enumerate(outs):
            for j, a in enumerate(ins):
                rows.append({'parameter': f'{o}:{a}', 'estimate': float(W[j, i])})
            rows.append({'parameter': f'{o}:Intercept', 'estimate': float(b[i])})
        ins = outs
    return rows


def _diagram(M, net):
    """The network for the Diagram: the X columns, the hidden layers (the one
    next to the X's first) and the responses, with every weight."""
    P = M.Ps[net.resp[0]]
    layers = _combined(net)
    nh = len(layers) - 1
    hname = ['H2', 'H1'] if nh == 2 else ['H1']
    feats = _feature_names(M, net)
    inputs = [{'name': c, 'features': [feats[j] for j in P.groups[c]], 'columns': P.groups[c],
               'type': 'categorical' if data.is_categorical(P.table, c) else 'continuous'} for c in P.x]
    hidden = [{'name': hname[i], 'n': int(layers[i][0].shape[1])} for i in range(nh)]
    outputs = [{'name': M.ys[j], 'kind': M.Ps[j].kind} for j in net.resp]
    return {'inputs': inputs, 'hidden': hidden, 'outputs': outputs, 'activation': M.spec['activation'],
            'weights': [W.tolist() for W, _ in layers], 'biases': [b.tolist() for _, b in layers], 'out_names': _out_names(M, net)}


def _hidden_values(net, X, s):
    """The hidden nodes' values on rows X: JMP's H1 (next to the output) and
    H2 (next to the X's), each n x nodes."""
    Xt = net.xt(X)
    h1, h2 = [], []
    for est, _ in net.parts:
        mlp = est[-1]
        a = est[0].transform(Xt)
        acts = []
        for i in range(len(mlp.coefs_) - 1):
            a = _act(s['activation'], a @ mlp.coefs_[i] + mlp.intercepts_[i])
            acts.append(a)
        h1.append(acts[-1])
        if len(acts) == 2:
            h2.append(acts[0])
    out = {'H1': np.concatenate(h1, axis=1)}
    if h2:
        out['H2'] = np.concatenate(h2, axis=1)
    return out


def _warn_chosen(M, name):
    """The chosen fits' warnings (L-BFGS that stopped at max_iter), under
    the report, with the model's name."""
    seen = set()
    for net in M.nets:
        for cat, msg in net.info.get('caught') or []:
            if issubclass(cat, (DeprecationWarning, PendingDeprecationWarning, FutureWarning)):
                continue
            text = f'Model {name}: {msg}'
            if text not in seen:
                seen.add(text)
                warnings.warn(text, cat)


def _validation_info(M, validation):
    s = M.spec
    info = {'method': M.method, 'label': METHOD_LABEL[M.method]}
    if M.method == 'holdback':
        info['portion'] = s['portion']
    if M.method == 'kfold':
        info.update({'folds': s['folds'], 'fold': M.fold + 1})
    if M.method == 'column':
        info['column'] = validation
    return info


def _by_response(M):
    """(net, its column of the response) for every response, in order."""
    out = [None] * len(M.ys)
    for net in M.nets:
        for jj, j in enumerate(net.resp):
            out[j] = (net, jj)
    return out


@api('neural.fit', packages=SK)
def fit(table, y, x, rows=None, freq=None, validation=None, seed=None, missing='informative', model=None, holdback=None, table_name='data'):
    """One model of the report: its measures per set and response, its
    Estimates and Diagram, how it was fitted, and the code."""
    try:
        M = _model(table, rows, y, x, freq, validation, seed, missing, model, holdback)
    except ValueError as e:
        return {'error': str(e)}
    s = M.spec
    name = name_of(s)
    _warn_chosen(M, name)
    fitted = [net.fitted(M.X) for net in M.nets]
    resp_out = []
    for j, (net, jj) in enumerate(_by_response(M)):
        P = M.Ps[j]
        f = fitted[M.nets.index(net)]
        rep = predictive.report(P, f[:, jj] if net.kind == 'continuous' else f)
        rep['notes'] = []
        resp_out.append({'y': P.y, 'kind': P.kind, 'net': M.nets.index(net), 'fit': rep})
    nets_out = []
    for net in M.nets:
        info = net.info
        nets_out.append({
            'responses': [M.ys[j] for j in net.resp], 'kind': net.kind, 'alpha': info['alpha'], 'penalty': s['penalty'],
            'iterations': info['iterations'], 'max_iter': s['max_iter'], 'path': info['path'],
            'boosted': net.boosted, 'boost': info['boost'], 'components': len(net.parts), 'steps': info.get('steps'),
            'random_states': info['random_states'][:len(net.parts)] if net.boosted else info['random_states'],
            'estimates': _estimates(M, net), 'diagram': _diagram(M, net),
            'transformed': [M.Ps[0].features[j] for j in net.transform.cols] if net.transform else [],
        })
    P0 = M.Ps[0]
    notes = list(M.notes)
    if s['penalty'] == 'squared' and not P0.has(1):
        notes.append(f'No rows validate the model, so the penalty cannot be chosen: alpha is {NO_VALIDATION_ALPHA:g}, scikit-learn\'s default.')
    return {
        'name': name, 'spec': s, 'responses': resp_out, 'nets': nets_out,
        'validation': _validation_info(M, validation), 'seed': M.seed,
        'tours': M.tours, 'tour': M.tour + 1, 'folds': M.fold_rows,
        'sets': [predictive.SETS[k] for k in range(3) if P0.has(k)], 'n': {predictive.SETS[k]: int(P0.mask(k).sum()) for k in range(3)},
        'notes': notes, 'features': list(P0.features), 'x': list(M.x),
        'code': _code(M, table_name),
    }


@api('neural.save', packages=SK)
def save(table, y, x, rows=None, freq=None, validation=None, seed=None, missing='informative', model=None, holdback=None, what='predicteds'):
    """What Save Columns puts in the table: every response's predictions
    (on every row whose factors the model can take), the hidden nodes'
    values, the sets, or the transformed covariates."""
    try:
        M = _model(table, rows, y, x, freq, validation, seed, missing, model, holdback)
    except ValueError as e:
        return {'error': str(e)}
    s = M.spec
    P0 = M.Ps[0]
    if what == 'validation':
        return {'rows': P0.index.tolist(), 'values': P0.sets.tolist(), 'name': 'Validation'}
    Xa, rows_a = P0.all_rows()
    if what == 'hidden':
        cols = []
        several = len(M.nets) > 1
        for net in M.nets:
            hv = _hidden_values(net, Xa, s)
            tag = f' {", ".join(M.ys[j] for j in net.resp)}' if several else ''
            for layer in ('H1', 'H2'):
                if layer in hv:
                    for i in range(hv[layer].shape[1]):
                        cols.append({'name': f'{layer}_{i + 1}{tag}', 'values': hv[layer][:, i].tolist()})
        return {'rows': rows_a.tolist(), 'columns': cols}
    if what == 'transformed':
        cols = []
        net = M.nets[0]
        if net.transform and net.transform.cols:
            Xt = net.transform(Xa)
            for j in net.transform.cols:
                cols.append({'name': f'T({P0.features[j]})', 'values': Xt[:, j].tolist()})
        return {'rows': rows_a.tolist(), 'columns': cols}
    out = []
    for j, (net, jj) in enumerate(_by_response(M)):
        P = M.Ps[j]
        if net.kind == 'continuous':
            r = predictive.saved(P, lambda X, net=net, jj=jj: net.predict(X)[:, jj])
        else:
            r = predictive.saved(P, None, net.proba)
        r['y'] = P.y
        out.append(r)
    return {'responses': out}


def _predictor(table, rows=None, y=None, x=None, freq=None, validation=None, seed=None, missing='informative', model=None, holdback=None, **_):
    """The Prediction Profiler's view of a model: every response."""
    M = _model(table, rows, y, x, freq, validation, seed, missing, model, holdback)
    P0 = M.Ps[0]
    where = _by_response(M)

    def run(settings):
        X = P0.encode_settings(settings)
        fitted = {id(net): net.fitted(X) for net in M.nets}
        out = []
        for j, (net, jj) in enumerate(where):
            P = M.Ps[j]
            f = fitted[id(net)]
            if net.kind == 'continuous':
                out.append({'name': P.y, 'pred': f[:, jj], 'lower': None, 'upper': None, 'bounded': False})
            else:
                for k, lab in enumerate(P.labels):
                    out.append({'name': f'Prob[{lab}]' if len(M.ys) == 1 else f'{P.y} Prob[{lab}]', 'pred': f[:, k], 'lower': None, 'upper': None, 'bounded': True})
        return out
    # the training rows' factor values, for the profiler's resampled inputs
    frame = data.frame(P0.table, P0.x, P0.index[P0.train()], dropna=False)
    observed = {c: [None if (isinstance(v, float) and math.isnan(v)) else (v.item() if hasattr(v, 'item') else v) for v in frame[c].astype(object)] for c in P0.x}
    return profile.Predictor(P0.factors(), run, observed)


profile.expose('neural', _predictor, packages=SK)


# ---------------------------------------------------------------------------
# the code under a model: the same fits, from a CSV export of the table
# ---------------------------------------------------------------------------

def _levels_code(P, var):
    """The lines that make a categorical response's level index, as P.code does."""
    lv = '[' + ', '.join(predictive._pylit(v) for v in P.levels) + ']'
    numeric = all(isinstance(v, (float, int, np.floating, np.integer)) for v in P.levels)
    src = f'pd.to_numeric(d[{json.dumps(P.y)}], errors="coerce")' if numeric else f'd[{json.dumps(P.y)}].astype(object)'
    return [f'levels = {lv}', f'{var} = pd.Categorical({src}, categories=levels).codes   # the index of the level']


def _mlp_code(s, cls, rs):
    return (f'Pipeline([("scale", StandardScaler()), ("mlp", {cls}(hidden_layer_sizes={_layers(s)!r}, activation={json.dumps(s["activation"])}, '
            f'solver="lbfgs", max_iter={s["max_iter"]}, random_state={rs}, warm_start=True))])')


def _alpha_list(a):
    return '[' + ', '.join(repr(float(v)) for v in a) + ']'


def _code(M, table_name):
    s = M.spec
    P0 = M.Ps[0]
    kinds = {net.kind for net in M.nets}
    mlps = []
    if 'continuous' in kinds or s['boost']:
        mlps.append('MLPRegressor')
    if 'categorical' in kinds and not s['boost']:
        mlps.append('MLPClassifier')
    imports = [f'from sklearn.neural_network import {", ".join(mlps)}', 'from sklearn.pipeline import Pipeline', 'from sklearn.preprocessing import StandardScaler']
    if s['transform']:
        imports[-1] = 'from sklearn.preprocessing import PowerTransformer, StandardScaler'
    if s['boost'] and 'categorical' in kinds:
        imports.append('from scipy.optimize import minimize_scalar')
    L = P0.code(table_name, M.rows, extra_imports=imports)
    # every digit of the table read back: a network's fit carries a last-digit
    # difference far (pandas' default parser is off by one in the last digit)
    csv = f'pd.read_csv({json.dumps(table_name + ".csv")})'
    L[0] = L[0].replace(f'df = {csv}   # the table, as File > Export CSV writes it',
                        f'df = {csv[:-1]}, float_precision="round_trip")   # the table, as File > Export CSV writes it, every digit read back')
    # every response in d (P.code knows the first)
    if len(M.ys) > 1:
        sp = P0.spec
        cols = list(dict.fromkeys(list(M.ys) + list(P0.x) + [c for c in (sp.get('weight'), sp.get('freq'), sp.get('validation')) if c]))
        for i, line in enumerate(L):
            if line.startswith('d = df['):
                L[i] = f'd = df[{json.dumps(cols)}]'
                break
    # the sets that P.code cannot know: KFold's, and the excluded rows'
    zero = 'sets = np.zeros(len(d), dtype=int)   # every row trains the model'
    if M.method in ('kfold', 'excluded') and zero in L:
        i = L.index(zero)
        if M.method == 'kfold':
            new = [f'fold = np.empty(len(d), dtype=int); fold[np.random.default_rng({M.seed}).permutation(len(d))] = np.arange(len(d)) % {s["folds"]}   # KFold: the folds',
                   f'sets = (fold == {M.fold}).astype(int)   # the fold whose model fits every row best validates it']
        else:
            held = [int(r) for r, k in zip(P0.index, P0.sets) if k == 1]
            new = [f'sets = d.index.isin({held}).astype(int)   # Excluded Rows Holdback: the excluded rows validate']
        L[i:i + 1] = new
    L.append('wt = np.ones(len(d)) if w is None else w')
    L.append('fit_w = {} if w is None else {"scale__sample_weight": w[train], "mlp__sample_weight": w[train]}')
    net0 = M.nets[0]
    if net0.transform is not None and net0.transform.cols:
        L.append(f'cont = {net0.transform.cols}   # the continuous factors\' columns: Transform Covariates makes them near normal')
        L.append('pt = PowerTransformer().fit(X[train][:, cont])   # Yeo-Johnson, standardized')
        L.append('X = X.copy(); X[:, cont] = pt.transform(X[:, cont])')
    for net in M.nets:
        L.append('')
        L += _net_code(M, net)
    return '\n'.join(L)


def _net_code(M, net):
    s = M.spec
    info = net.info
    names = [M.ys[j] for j in net.resp]
    L = [f'# ---- Model {name_of(s)}: the network of {", ".join(names)}']
    path = _alpha_list(info['alphas'])
    if s['penalty'] == 'none':
        why = 'No Penalty'
    elif M.Ps[0].has(1):
        why = 'up the penalty path to the alpha the validation rows chose, each fit starting where the last ended'
    else:
        why = 'no rows validate: scikit-learn\'s default alpha'
    K = len(net.parts)
    rss = info['random_states'][:K]
    if net.kind == 'continuous':
        L.append(f'Y = d[{json.dumps(names)}].to_numpy(float)   # the continuous responses, fitted together')
        L.append('mu = np.average(Y[train], axis=0, weights=wt[train])')
        L.append('sd = np.sqrt(np.average((Y[train] - mu) ** 2, axis=0, weights=wt[train]))')
        L.append('sd = np.where(sd > 0, sd, 1.0)')
        L.append('Z = (Y - mu) / sd   # standardized by the training rows')
        if len(names) == 1:
            L.append('Z = Z[:, 0]')
        if not net.boosted:
            L.append(f'net = {_mlp_code(s, "MLPRegressor", rss[0])}')
            L.append(f'for alpha in {path}:   # {why}')
            L.append('    net.set_params(mlp__alpha=alpha).fit(X[train], Z[train], **fit_w)')
            L.append('pred = mu + sd * net.predict(X).reshape(len(X), -1)   # a column per response')
        else:
            L.append('F = np.zeros(Z.shape)   # the boosted sum, on the standardized scale')
            L.append(f'for k, rs in enumerate({rss}):   # the base models kept')
            L.append(f'    net = {_mlp_code(s, "MLPRegressor", "rs")}')
            L.append(f'    for alpha in ({path} if k == 0 else [{float(info["alpha"])!r}]):   # the first up the penalty path, the rest at its alpha')
            L.append('        net.set_params(mlp__alpha=alpha).fit(X[train], (Z - F)[train], **fit_w)   # what the models before leave')
            L.append(f'    F = F + ({float(s["rate"])!r} if k < {K - 1} else 1.0) * net.predict(X).reshape(F.shape)   # scaled by the learning rate, but the last')
            L.append('pred = mu + sd * F.reshape(len(X), -1)')
        L.append('for k, name in enumerate(["Training", "Validation", "Test"]):')
        L.append('    m = sets == k')
        L.append('    if m.any():')
        L.append('        sse = np.sum(wt[m][:, None] * (Y[m] - pred[m]) ** 2, axis=0)')
        L.append('        sst = np.sum(wt[m][:, None] * (Y[m] - np.average(Y[m], axis=0, weights=wt[m])) ** 2, axis=0)')
        L.append('        print(name, "RSquare", 1 - sse / sst, "RASE", np.sqrt(sse / wt[m].sum()))')
        return L
    P = M.Ps[net.resp[0]]
    L += _levels_code(P, 'yc')
    if not net.boosted:
        L.append(f'net = {_mlp_code(s, "MLPClassifier", rss[0])}')
        L.append(f'for alpha in {path}:   # {why}')
        L.append('    net.set_params(mlp__alpha=alpha).fit(X[train], yc[train], **fit_w)')
        L.append('proba = np.zeros((len(X), len(levels)))')
        L.append('proba[:, net.classes_] = net.predict_proba(X)')
    else:
        L.append('Yh = np.eye(len(levels))[yc]   # a 0/1 column per level')
        L.append('share = np.array([wt[train][yc[train] == j].sum() for j in range(len(levels))]) / wt[train].sum()')
        L.append('G = np.tile(np.log(np.clip(share, 1e-15, None)), (len(X), 1))   # the log odds, from the training shares')
        L.append('')
        L.append('')
        L.append('def softmax(G):')
        L.append('    E = np.exp(G - G.max(axis=1, keepdims=True))')
        L.append('    return E / E.sum(axis=1, keepdims=True)')
        L.append('')
        L.append('')
        L.append('rows_t = np.flatnonzero(train)')
        L.append(f'for k, rs in enumerate({rss}):   # the base models kept')
        L.append(f'    net = {_mlp_code(s, "MLPRegressor", "rs")}')
        L.append(f'    for alpha in ({path} if k == 0 else [{float(info["alpha"])!r}]):   # the first up the penalty path, the rest at its alpha')
        L.append('        net.set_params(mlp__alpha=alpha).fit(X[train], (Yh - softmax(G))[train], **fit_w)   # the gradient of the log likelihood')
        L.append('    f = net.predict(X).reshape(G.shape)')
        L.append('    nll = lambda r: -np.sum(wt[rows_t] * np.log(np.clip(softmax(G[rows_t] + r * f[rows_t])[np.arange(len(rows_t)), yc[rows_t]], 1e-15, None)))')
        L.append('    rho = minimize_scalar(nll, bounds=(0.0, 100.0), method="bounded").x   # a line search on the training likelihood')
        L.append(f'    G = G + ({float(s["rate"])!r} * rho if k < {K - 1} else rho) * f   # scaled by the learning rate, but the last')
        L.append('proba = softmax(G)')
    L.append('proba = np.clip(proba, 1e-15, 1 - 1e-15); proba /= proba.sum(axis=1, keepdims=True)   # never exactly 0 or 1')
    L.append('for k, name in enumerate(["Training", "Validation", "Test"]):')
    L.append('    m = sets == k')
    L.append('    if m.any():')
    L.append('        p = proba[m][np.arange(m.sum()), yc[m]]')
    L.append('        print(name, "-LogLikelihood", -np.sum(wt[m] * np.log(p)), "Misclassification Rate", np.sum(wt[m] * (proba[m].argmax(axis=1) != yc[m])) / wt[m].sum())')
    return L
