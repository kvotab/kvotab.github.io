"""Analyze > Multivariate Methods > Partial Least Squares.

JMP's Partial Least Squares platform on scikit-learn's PLSRegression, which
is NIPALS: PLS2 with the X scores deflating both X and Y, as JMP's NIPALS
does (JMP's other method, SIMPLS, is not in scikit-learn). Y's and X's are
continuous; Centering and Scaling (both on by default) take the training
rows' means and standard deviations. scikit-learn always centres: with
Centering off it is given the rows and their mirror image (-x, -y), whose
means are 0, so its weights, loadings and scores are the uncentred data's.

Validation chooses the number of factors from 0 to the Initial Number of
Factors: KFold (scikit-learn's KFold, shuffled with the report's seed),
Leave-One-Out, Holdback (a share of the rows drawn from the seed, as the
predictive platforms draw a validation portion), a Validation column
(predictive.prepare's rules: 0 Training, 1 Validation, 2 Test), or None
(the Initial Number of Factors). Root Mean PRESS is the root mean squared
predicted residual of the validation rows over the responses, on the
centred and scaled Y; van der Voet's T^2 compares each number of factors
with the minimum, as SAS PROC PLS computes it (a randomization test of the
squared predicted residuals). The fit takes the number of factors with the
smallest Root Mean PRESS (at least 1), refitted on every training row.
"""
import inspect
import json

import numpy as np

from . import data, predictive, profile
from .registry import api

METHODS = {'kfold': 'KFold', 'holdback': 'Holdback', 'loo': 'Leave-One-Out', 'column': 'Validation Column', 'none': 'None'}
N_SIM = 1000             # van der Voet's randomizations (SAS's NSAMP default)
PROGRESS = True


# ---------------------------------------------------------------------------
# the helpers the shown code carries
# ---------------------------------------------------------------------------

def pls_fit(X, Y, A, center=True, scale=True):
    """NIPALS partial least squares with A factors: scikit-learn's
    PLSRegression on the rows (X, Y). Returns its weights W, Y weights C,
    loadings P, Y loadings Q, the rows' X and Y scores T and U, and the
    centring and scaling (the columns' means and standard deviations, or 0
    and 1). scikit-learn always centres; without Centering the rows and
    their mirror image (-x, -y) are fitted, whose means are 0. With more
    than one Y the NIPALS iteration runs until the squared change of the
    weights is below 1e-12 (scikit-learn's default, 1e-6, leaves them
    good to about 1e-3)."""
    import numpy as np
    from sklearn.cross_decomposition import PLSRegression
    n = len(X)
    xm = X.mean(axis=0) if center else np.zeros(X.shape[1])
    ym = Y.mean(axis=0) if center else np.zeros(Y.shape[1])
    xs = X.std(axis=0, ddof=1) if scale else np.ones(X.shape[1])
    ys = Y.std(axis=0, ddof=1) if scale else np.ones(Y.shape[1])
    xs[xs == 0] = 1.0
    ys[ys == 0] = 1.0
    if center:
        m = PLSRegression(n_components=A, scale=scale, tol=1e-12, max_iter=2000).fit(X, Y)
        T, U = m.x_scores_, m.y_scores_
    else:
        Xs, Ys = X / xs, Y / ys
        m = PLSRegression(n_components=A, scale=False, tol=1e-12, max_iter=2000).fit(np.vstack([Xs, -Xs]), np.vstack([Ys, -Ys]))
        T, U = m.x_scores_[:n], m.y_scores_[:n]
    return {'W': m.x_weights_, 'C': m.y_weights_, 'P': m.x_loadings_, 'Q': m.y_loadings_, 'T': T, 'U': U,
            'xm': xm, 'xs': xs, 'ym': ym, 'ys': ys, 'Xc': (X - xm) / xs, 'Yc': (Y - ym) / ys}


def pls_coef(fit, a):
    """The model with the first a factors: its coefficients B on the centred
    and scaled data (R Q', R = W (P'W)^-1), on the original data, and the
    intercepts."""
    import numpy as np
    W, P, Q = fit['W'][:, :a], fit['P'][:, :a], fit['Q'][:, :a]
    B = W @ np.linalg.pinv(P.T @ W) @ Q.T if a else np.zeros((W.shape[0], Q.shape[0]))
    Bo = B * fit['ys'][None, :] / fit['xs'][:, None]
    return B, Bo, fit['ym'] - fit['xm'] @ Bo


def pls_scores(fit, a, X, Y=None):
    """X scores of rows (X on the original scale) for the first a factors,
    T = X R with X centred and scaled, and with Y their Y scores, the NIPALS
    u = Y_b c_b / c_b'c_b with Y_b deflated by the earlier factors t q'."""
    import numpy as np
    W, P = fit['W'][:, :a], fit['P'][:, :a]
    T = ((X - fit['xm']) / fit['xs']) @ (W @ np.linalg.pinv(P.T @ W))
    if Y is None:
        return T, None
    Yd = (Y - fit['ym']) / fit['ys']
    U = np.zeros((len(Y), a))
    for b in range(a):
        c = fit['C'][:, b]
        U[:, b] = Yd @ c / (c @ c)
        Yd = Yd - np.outer(T[:, b], fit['Q'][:, b])
    return T, U


def cv_residuals(X, Y, sets, method, folds, A, center, scale, seed, ysd, tick=None):
    """Predicted residuals of the validation rows for 0 to A factors, each
    response divided by ysd (the training rows' standard deviations with
    Scaling, else 1). KFold (shuffled with the seed) and Leave-One-Out
    predict each training row from a model without it; Holdback and a
    Validation column predict the rows with sets == 1 from those with
    sets == 0. Returns the positions of the rows and the A + 1 arrays of
    residuals (rows x responses). tick(done, total), if given, after each
    fit."""
    import numpy as np
    from sklearn.model_selection import KFold, LeaveOneOut
    tr = np.flatnonzero(sets == 0)
    if method in ('kfold', 'loo'):
        split = KFold(n_splits=folds, shuffle=True, random_state=seed) if method == 'kfold' else LeaveOneOut()
        parts = [(tr[a], tr[b]) for a, b in split.split(tr)]
        at = tr
    else:
        at = np.flatnonzero(sets == 1)
        parts = [(tr, at)]
    where = np.empty(len(X), dtype=int)
    where[at] = np.arange(len(at))          # the residuals in the rows' order
    E = [np.zeros((len(at), Y.shape[1])) for _ in range(A + 1)]
    done = 0
    for fit_rows, held in parts:
        f = pls_fit(X[fit_rows], Y[fit_rows], A, center, scale)
        for a in range(A + 1):
            B, Bo, b0 = pls_coef(f, a)
            E[a][where[held]] = (Y[held] - (b0 + X[held] @ Bo)) / ysd
        done += len(held)
        if tick:
            tick(done, len(at))
    return at, E


def van_der_voet(E, best, seed, n_sim=1000):
    """van der Voet's (1994) test of each number of factors against the one
    with the smallest PRESS, as SAS PROC PLS computes it: D = R_a^2 - R_best^2
    for each row and response, C = d' S^-1 d with d the sums of D's columns
    and S = D'D; the p-value is the share of n_sim random swaps of the two
    models' squared residuals (the sign of each row of D) whose C exceeds
    it. Returns [(C, p)] for 0, 1, ... factors."""
    import numpy as np
    signs = np.random.default_rng(seed).choice([-1.0, 1.0], size=(n_sim, E[0].shape[0]))
    out = []
    for a in range(len(E)):
        D = E[a] ** 2 - E[best] ** 2
        if a == best or not np.any(D):
            out.append((0.0, 1.0))
            continue
        d = D.sum(axis=0)
        Si = np.linalg.pinv(D.T @ D)
        sim = signs @ D
        out.append((float(d @ Si @ d), float(np.mean(np.einsum('ij,jk,ik->i', sim, Si, sim) > d @ Si @ d))))
    return out


def pls_summary(fit, a):
    """Percent Variation Explained by each factor in the X's and the Y's (of
    the centred and scaled training data's sums of squares), and each X's
    variable importance VIP = sqrt(p sum_a SSY_a w_ja^2 / sum_a SSY_a), SSY_a
    the Y sum of squares factor a explains."""
    import numpy as np
    T, P, Q, W = fit['T'][:, :a], fit['P'][:, :a], fit['Q'][:, :a], fit['W'][:, :a]
    tt = (T ** 2).sum(axis=0)
    ssy = tt * (Q ** 2).sum(axis=0)
    xe = 100 * tt * (P ** 2).sum(axis=0) / (fit['Xc'] ** 2).sum()
    ye = 100 * ssy / (fit['Yc'] ** 2).sum()
    vip = np.sqrt(W.shape[0] * ((W ** 2 / (W ** 2).sum(axis=0)) @ ssy) / ssy.sum())
    return xe, ye, vip


def pls_distances(fit, a, X, Y, training):
    """DModX and DModY of rows, the distances to the X and Y models: the
    root mean square of the centred and scaled residuals after a factors
    (over p - a X degrees of freedom, and the q Y's), times
    sqrt(n / (n - a - 1)) for the n training rows; and Hotelling's T^2 of
    the rows' scores, each over the training variance of its factor."""
    import numpy as np
    n = len(fit['T'])
    T, _ = pls_scores(fit, a, X)
    E = (X - fit['xm']) / fit['xs'] - T @ fit['P'][:, :a].T
    F = (Y - fit['ym']) / fit['ys'] - T @ fit['Q'][:, :a].T
    corr = np.where(training, np.sqrt(n / (n - a - 1)), 1.0)
    p = X.shape[1]
    dmodx = np.sqrt((E ** 2).sum(axis=1) / (p - a)) * corr if p > a else np.full(len(X), np.nan)
    dmody = np.sqrt((F ** 2).sum(axis=1) / Y.shape[1]) * corr
    s2 = (fit['T'][:, :a] ** 2).sum(axis=0) / (n - 1)
    return dmodx, dmody, (T ** 2 / s2).sum(axis=1)


_HELPERS = (pls_fit, pls_coef, pls_scores, cv_residuals, van_der_voet, pls_summary, pls_distances)


def _source(fn):
    try:
        return inspect.getsource(fn).rstrip()
    except (OSError, TypeError):
        return f'# {fn.__name__}: see resources/py/smui/pls.py'


# ---------------------------------------------------------------------------
# the model
# ---------------------------------------------------------------------------

def _prepare(table, y, x, rows, validation, method, holdback, seed):
    ys, xs = list(dict.fromkeys(y or [])), list(dict.fromkeys(x or []))
    if not ys:
        raise ValueError('choose at least one Y, Response')
    if not xs:
        raise ValueError('choose at least one X, Factor')
    both = [c for c in ys if c in xs]
    if both:
        raise ValueError(f'{both[0]} cannot be both a Y and an X')
    portion = float(holdback) if method == 'holdback' and not validation else 0.0
    P = predictive.prepare(table, ys[0], xs + ys[1:], rows, validation=validation or None, portion=portion, seed=seed,
                           missing='drop', categorical_y=False)
    p = len(xs)
    X, Y = P.X[:, :p], np.column_stack([P.target, P.X[:, p:]])
    frame = data.frame(table, ys + xs, rows, dropna=False)
    notes = []
    miss = int((~frame.notna().all(axis=1)).sum())
    if miss:
        notes.append(f'{miss} rows missing a Y or an X are left out.')
    notes += [t for t in P.notes if validation and f'no {validation} value' in t]
    return P, ys, xs, X, Y, notes


def _methods(validation, method):
    return 'column' if validation else (method if method in METHODS and method != 'column' else 'kfold')


class _Model:
    pass


def _build(table, rows, y, x, validation=None, method='kfold', folds=7, holdback=0.2, factors=15, center=True, scale=True, seed=0):
    method = _methods(validation, method)
    P, ys, xs, X, Y, notes = _prepare(table, y, x, rows, validation, method, holdback, seed)
    sets = P.sets
    tr = sets == 0
    ntr = int(tr.sum())
    if method in ('holdback', 'column') and not np.any(sets == 1):
        raise ValueError('no validation rows: the Validation column has no 1 (Validation) rows' if method == 'column' else 'the Holdback Portion leaves no validation rows')
    folds = int(folds)
    if method == 'kfold':
        if folds < 2:
            raise ValueError('KFold needs at least 2 folds')
        if folds > ntr:
            raise ValueError(f'{folds} folds need at least {folds} rows; there are {ntr}')
    # the most factors every fit can take: the X's, and the rows less 2
    smallest = ntr - int(np.ceil(ntr / folds)) if method == 'kfold' else (ntr - 1 if method == 'loo' else ntr)
    A = int(min(int(factors), len(xs), smallest - 2, ntr - 2))
    if A < 1:
        raise ValueError(f'too few rows ({ntr} training rows) for a factor')
    M = _Model()
    M.P, M.ys, M.xs, M.X, M.Y, M.sets, M.notes = P, ys, xs, X, Y, sets, notes
    M.method, M.folds, M.holdback, M.center, M.scale, M.seed, M.factors_asked = method, folds, float(holdback), bool(center), bool(scale), int(seed), int(factors)
    M.A_max = A
    ysd = Y[tr].std(axis=0, ddof=1) if scale else np.ones(Y.shape[1])
    ysd[ysd == 0] = 1.0
    if method == 'none':
        M.cv = None
        M.a = A
    else:
        step = max(1, ntr // 20)

        def progress(done, total):
            if done % step == 0 or done == total:
                print(f'smui:progress pls {done} {total}', flush=True)
        at, E = cv_residuals(X, Y, sets, method, folds, A, center, scale, int(seed), ysd, progress if PROGRESS and method == 'loo' and ntr > 200 else None)
        rmp = np.array([np.sqrt(np.mean(e ** 2)) for e in E])
        best = int(np.argmin(rmp))
        vdv = van_der_voet(E, best, int(seed), N_SIM)
        fewest = next((a for a in range(1, A + 1) if vdv[a][1] > 0.10), None)
        M.cv = {'rmpress': rmp, 'best': best, 'vdv': vdv, 'fewest': fewest, 'n_rows': int(len(at)), 'rows': at}
        M.a = max(1, best)
    M.fit = pls_fit(X[tr], Y[tr], M.a, center, scale)
    return M


def _model(table, rows, y, x, validation=None, method='kfold', folds=7, holdback=0.2, factors=15, center=True, scale=True, seed=None):
    seed = predictive.seed_of(seed)
    seed = 0 if seed is None else seed
    spec = {'y': list(y or []), 'x': list(x or []), 'validation': validation or None, 'method': method, 'folds': int(folds), 'holdback': float(holdback),
            'factors': int(factors), 'center': bool(center), 'scale': bool(scale), 'seed': seed}
    return predictive.cached('pls', table, rows, spec, lambda: _build(table, rows, **spec))


def cv_title(M):
    if M.method == 'kfold':
        return f'KFold Cross Validation with K={M.folds} and Method=NIPALS'
    if M.method == 'loo':
        return 'Leave-One-Out Cross Validation with Method=NIPALS'
    if M.method == 'holdback':
        return f'Holdback Validation with Holdback={M.holdback:g} and Method=NIPALS'
    if M.method == 'column':
        return 'Validation Column Cross Validation with Method=NIPALS'
    return None


# ---------------------------------------------------------------------------
# the code under the report
# ---------------------------------------------------------------------------

def _rows_code(table, rows):
    n_all = data.TABLES[table]['n'] if table in data.TABLES else None
    if rows is None:
        return []
    keep = [int(r) for r in rows]
    if len(set(keep)) != len(keep):
        return [f'df = df.iloc[{keep}].reset_index(drop=True)   # the rows of the report (resampled)']
    if n_all is not None and len(keep) > n_all / 2:
        drop = sorted(set(range(n_all)) - set(keep))
        return [f'df = df.drop(index={drop})   # the rows the report leaves out'] if drop else []
    return [f'df = df.loc[{keep}]   # the rows of the report']


def _code(M, table, table_name, rows, alpha, graph=False):
    """The code under the report; graph: the head of its graphs (matplotlib imported, the numbers
    exactly as exported, no printing, and every row's table row number)."""
    ys, xs, v = M.ys, M.xs, M.P.spec.get('validation')
    L = ['import numpy as np', 'import pandas as pd', 'from scipy import stats',
         'from sklearn.cross_decomposition import PLSRegression', 'from sklearn.model_selection import KFold, LeaveOneOut']
    if graph:
        L += [predictive.PLT, '# the table, as File > Export CSV writes it (an empty field is missing)',
              f'df = pd.read_csv({json.dumps(table_name + ".csv")}, float_precision="round_trip", keep_default_na=False, na_values=[""])']
    else:
        L += ['# the table, as File > Export CSV writes it (an empty field is missing)',
              f'df = pd.read_csv({json.dumps(table_name + ".csv")}, float_precision="round_trip", keep_default_na=False, na_values=[""])']
    L += _rows_code(table, rows)
    cols = list(dict.fromkeys(ys + xs + ([v] if v else [])))
    L.append(f'd = df[{json.dumps(cols)}].dropna()   # rows with every Y and X' + (' and a validation value' if v else ''))
    L.append(f'X = d[{json.dumps(xs)}].to_numpy(float)')
    L.append(f'Y = d[{json.dumps(ys)}].to_numpy(float)')
    if v:
        if data.meta(table, v).get('dataType') == 'numeric':
            L.append(f'sets = d[{json.dumps(v)}].to_numpy(int)   # 0 training, 1 validation, 2 test')
        else:
            L.append(f'names = {json.dumps(predictive._SET_NAMES)}')
            L.append(f'sets = d[{json.dumps(v)}].str.strip().str.lower().map(names).to_numpy(int)   # 0 training, 1 validation, 2 test')
    elif M.method == 'holdback':
        k = int(round(M.holdback * len(M.P.index)))
        L.append(f'sets = np.zeros(len(d), dtype=int); sets[np.random.default_rng({M.seed}).permutation(len(d))[:{k}]] = 1   # Holdback {M.holdback:g}')
    else:
        L.append('sets = np.zeros(len(d), dtype=int)   # every row is a training row')
    L.append('train = sets == 0')
    L.append(f'center, scale = {M.center}, {M.scale}   # Centering, Scaling')
    L.append('')
    for h in _HELPERS:
        if graph and h is van_der_voet:   # no graph shows the test
            continue
        L.append(_source(h))
        L.append('')
    if M.cv is not None:
        L.append('ysd = Y[train].std(axis=0, ddof=1) if scale else np.ones(Y.shape[1])')
        L.append('ysd[ysd == 0] = 1.0')
        L.append(f'at, E = cv_residuals(X, Y, sets, {json.dumps(M.method)}, {M.folds}, {M.A_max}, center, scale, {M.seed}, ysd)')
        L.append('rmpress = [np.sqrt(np.mean(e ** 2)) for e in E]   # Root Mean PRESS for 0, 1, ... factors')
        L.append('best = int(np.argmin(rmpress))')
        if not graph:
            L.append(f'vdv = van_der_voet(E, best, {M.seed}, {N_SIM})   # van der Voet T² and Prob > T²')
            L.append('print("Root Mean PRESS", rmpress)')
            L.append('print("van der Voet", vdv)')
        L.append('a = max(1, best)   # the number of factors fitted')
    else:
        L.append(f'a = {M.a}   # the Initial Number of Factors (as many as the rows and X\'s allow)')
    L.append('fit = pls_fit(X[train], Y[train], a, center, scale)')
    L.append('B, Bo, b0 = pls_coef(fit, a)')
    if not graph:
        L.append('print("Model Coefficients for Centered and Scaled Data", B)')
        L.append('print("Model Coefficients for Original Data: Intercept", b0, "and", Bo)')
    L.append('xe, ye, vip = pls_summary(fit, a)')
    if not graph:
        L.append('print("Percent Variation Explained: X", xe, "Y", ye, "cumulative", np.cumsum(xe), np.cumsum(ye))')
        L.append('print("VIP", vip)')
    L.append('dmodx, dmody, t2 = pls_distances(fit, a, X, Y, train)')
    L.append(f'n = int(train.sum()); ucl = (n - 1) ** 2 / n * stats.beta.ppf({1 - alpha!r}, a / 2, (n - a - 1) / 2)   # T² limit, training rows')
    L.append('T, U = pls_scores(fit, a, X, Y)   # the X and Y scores of every row')
    if graph:
        L.append('rownum = d.index.to_numpy() + 1   # each row\'s number in the table')
    return '\n'.join(L)


# ---------------------------------------------------------------------------
# the graphs' code (smui-p-pls.js puts each under its graph): a tail each, after the head (_code, graph)
# ---------------------------------------------------------------------------

SET_COLORS = [predictive.BASE, '#3a7d44', '#6c5b7b']   # smui-p-pls.js setColors(), light theme
GRID = '#e0d7ce'                                        # the zero lines (the theme's grid colour)


def _width(w):
    """The page's width of a graph asked w pixels wide (W in smui-p-pls.js at a desktop width: 260 at least)."""
    return max(260, w)


def _by_set_lines(present, xv, yv, size):
    """Points of rows by set (training circles, validation diamonds, test squares), as bySet draws them."""
    L = [f'colors, markers = {json.dumps(SET_COLORS)}, ["o", "D", "s"]']
    for k in present:
        L += [f'm = sets == {k}   # the {predictive.SETS[k].lower()} rows',
              f'ax.scatter({xv}[m], {yv}[m], s={size}, color=colors[{k}], marker=markers[{k}], label="{predictive.SETS[k]}")']
    return L


def _ticks_line(n):
    rot = 'rotation=45, ha="right"' if n > 8 else 'rotation=0'
    return f'ax.set_xticks(range(len(names)), names, {rot})'


def _plots(M, n_rows, present, thr):
    """The tails of every graph of a fit (thr: the page's VIP threshold)."""
    J = json.dumps
    a, xs, ys = M.a, M.xs, M.ys
    size = 14 if n_rows <= 600 else 8 if n_rows <= 2000 else 5   # the page's marker size by the number of rows
    several = len(present) > 1
    legend = ['fig.legend(loc="outside upper left", ncols=3, frameon=False, fontsize=8)'] if several else []
    B, MUT, RED, BAR, TXT = predictive.BASE, predictive.MUTED, predictive.FIT, predictive.BAR, predictive.TEXT
    out = {}
    if M.cv is not None:
        ticks = 'k_[::2]' if M.A_max + 1 > 12 else 'k_'
        out['cv'] = '\n'.join([
            'k_ = np.arange(len(rmpress))   # 0, 1, ... factors',
            predictive.figure(_width(360), 260),
            f'ax.plot(k_, rmpress, color="{B}", linewidth=1.6, marker="o", markersize=4.5)',
            f'ax.plot([best], [rmpress[best]], linestyle="none", marker="o", markersize=8.3, markerfacecolor="none", markeredgecolor="{RED}", markeredgewidth=2)   # the minimum',
            f'ax.set_xticks({ticks})',
            'ax.set_xlabel("Number of Factors")', 'ax.set_ylabel("Root Mean PRESS")', 'ax.set_title("Root Mean PRESS by number of factors", wrap=True)', 'plt.show()'])
    out['xy'] = []
    for k in range(a):
        out['xy'].append('\n'.join([
            predictive.figure(_width(250 if a > 2 else 300), 240),
            *_by_set_lines(present, f'T[:, {k}]', f'U[:, {k}]', size),
            f'tt, tu = T[train, {k}] @ T[train, {k}], T[train, {k}] @ U[train, {k}]',
            'b = tu / tt if tt > 0 else 0.0   # the inner relation u = b t, fitted to the training rows',
            f't_ = T[:, {k}][np.isfinite(T[:, {k}])]',
            f'ax.plot([t_.min(), t_.max()], [b * t_.min(), b * t_.max()], color="{MUT}", linewidth=1, linestyle=":")',
            f'ax.set_xlabel("X Score {k + 1}")', f'ax.set_ylabel("Y Score {k + 1}")', f'ax.set_title("X-Y scores of factor {k + 1}")', 'plt.show()']))
    out['percent'] = {}
    for key, var, title in (('x', 'xe', 'X Effect'), ('y', 'ye', 'Y Effect')):
        out['percent'][key] = '\n'.join([
            'f_ = np.arange(1, a + 1)',
            predictive.figure(_width(300), 230),
            f'ax.bar(f_, {var}, color="{BAR}")   # each factor\'s percent',
            f'ax.plot(f_, np.cumsum({var}), color="{RED}", linewidth=1.6, marker="o", markersize=3.75)   # the cumulative percent',
            'ax.set_xticks(f_)', 'ax.set_ylim(0, 102)',
            'ax.set_xlabel("Number of Factors")', f'ax.set_ylabel("{title} (%)")', f'ax.set_title("{title}")', 'plt.show()'])
    p = len(xs)
    out['vip'] = '\n'.join([
        f'thr = {float(thr)!r}   # the VIP threshold (Set VIP Threshold)',
        f'names = {J(xs)}',
        predictive.figure(_width(max(320, min(760, 70 + 34 * p))), 270),
        f'ax.plot(range(len(names)), vip, color="{B}", linewidth=1.4)',
        f'ax.scatter(range(len(names)), vip, s=28, color=["{B}" if v > thr else "{MUT}" for v in vip], zorder=3)   # below the threshold: grey',
        f'ax.axhline(thr, color="{RED}", linewidth=1.3, linestyle="--")',
        _ticks_line(p),
        'ax.set_ylim(bottom=0)', 'ax.set_ylabel("VIP")', 'ax.set_title("Variable importance")', 'plt.show()'])
    out['vipcoef'] = []
    for k, ynm in enumerate(ys):
        out['vipcoef'].append('\n'.join([
            f'thr = {float(thr)!r}   # the VIP threshold (Set VIP Threshold)',
            f'names = {J(xs)}',
            f'c_ = B[:, {k}]   # the centred and scaled coefficients for {ynm}',
            'm_ = 1.15 * np.abs(c_).max() or 1.0',
            predictive.figure(_width(360), 300),
            f'ax.axvline(0, color="{GRID}", linewidth=1, zorder=0)',
            f'ax.scatter(c_, vip, s=28, color="{B}")',
            'for x_, v_, nm in zip(c_, vip, names):',
            f'    ax.annotate(nm, (x_, v_), xytext=(0, 5), textcoords="offset points", ha="center", va="bottom", fontsize=7.1, color="{TXT}")',
            f'ax.axhline(thr, color="{RED}", linewidth=1.2, linestyle="--")',
            'ax.set_xlim(-m_, m_)', 'ax.set_ylim(bottom=0)',
            f'ax.set_xlabel({J("Coefficient for " + ynm + " (centred and scaled)")})', 'ax.set_ylabel("VIP")',
            f'ax.set_title({J("VIP vs coefficients for " + ynm)}, wrap=True)', 'plt.show()']))
    out['loadings'] = {}
    for key, names, mat, title in (('x', xs, 'P', 'X Loadings'), ('y', ys, 'Q', 'Y Loadings')):
        out['loadings'][key] = '\n'.join([
            f'names = {J(names)}',
            f'L_ = fit["{mat}"][:, :a]   # the {title[0]} loadings, a column per factor',
            f'colors = {J(predictive.PALETTE)}',
            predictive.figure(_width(max(320, min(760, 80 + 34 * len(names)))), 290),
            f'ax.axhline(0, color="{GRID}", linewidth=1, zorder=0)',
            'for j in range(a):',
            '    ax.plot(range(len(names)), L_[:, j], color=colors[j % len(colors)], linewidth=1.4, marker="o", markersize=3.75, label=f"Factor {j + 1}")',
            _ticks_line(len(names)),
            f'ax.set_ylabel("{title}")', f'ax.set_title("{title}")',
            'fig.legend(loc="outside upper left", ncols=min(a, 6), frameon=False, fontsize=8)', 'plt.show()'])
    out['distance'] = {}
    for key, xv, yv, xt, yt, title in (('dmodx', 'rownum', 'dmodx', 'Row', 'DModX', 'Distance to the X model by row'),
                                       ('dmody', 'rownum', 'dmody', 'Row', 'DModY', 'Distance to the Y model by row'),
                                       ('both', 'dmodx', 'dmody', 'DModX', 'DModY', 'Distance to the Y model by distance to the X model')):
        if key != 'dmody' and not len(xs) > a:
            continue
        out['distance'][key] = '\n'.join([
            predictive.figure(_width(320), 250),
            *_by_set_lines(present, xv, yv, size),
            'ax.set_ylim(bottom=0)',
            f'ax.set_xlabel("{xt}")', f'ax.set_ylabel("{yt}")', f'ax.set_title("{title}", wrap=True)', *legend, 'plt.show()'])
    out['t2'] = '\n'.join([
        predictive.figure(_width(560), 270),
        *_by_set_lines(present, 'rownum', 't2', size),
        f'ax.axhline(ucl, color="{RED}", linewidth=1.3, linestyle="--")',
        f'ax.text(1, ucl, f"UCL {{ucl:.4g}}", transform=ax.get_yaxis_transform(), ha="right", va="bottom", fontsize=7.5, color="{RED}")',
        'ax.set_ylim(bottom=0)',
        'ax.set_xlabel("Row")', 'ax.set_ylabel("T²")', 'ax.set_title("T² by row")', *legend, 'plt.show()'])
    return out


# ---------------------------------------------------------------------------
# the page's calls
# ---------------------------------------------------------------------------

@api('pls.fit', packages=predictive.SK)
def fit(table, y, x, rows=None, validation=None, method='kfold', folds=7, holdback=0.2, factors=15, center=True, scale=True, seed=None, alpha=0.05, plot=None,
        table_name='data'):
    """One NIPALS fit: the cross validation, the percent variation
    explained, the coefficients, VIP, scores, loadings, distances and T^2."""
    from scipy import stats
    try:
        M = _model(table, rows, y, x, validation, method, folds, holdback, factors, center, scale, seed)
    except ValueError as e:
        return {'error': str(e)}
    a, f = M.a, M.fit
    X, Y, sets, idx = M.X, M.Y, M.sets, M.P.index
    tr = sets == 0
    B, Bo, b0 = pls_coef(f, a)
    xe, ye, vip = pls_summary(f, a)
    dmodx, dmody, t2 = pls_distances(f, a, X, Y, tr)
    n = int(tr.sum())
    ucl = float((n - 1) ** 2 / n * stats.beta.ppf(1 - float(alpha), a / 2, (n - a - 1) / 2))
    Tall, Uall = pls_scores(f, a, X, Y)
    cv = None
    if M.cv is not None:
        c = M.cv
        cv = {'title': cv_title(M), 'rows': [{'factors': k, 'rmpress': float(c['rmpress'][k]), 't2': c['vdv'][k][0], 'p': c['vdv'][k][1]} for k in range(M.A_max + 1)],
              'best': c['best'], 'fewest': c['fewest'], 'n_rows': c['n_rows'], 'n_sim': N_SIM}
    counts = {predictive.SETS[k]: int(np.sum(sets == k)) for k in range(3)}
    return {
        'y': M.ys, 'x': M.xs, 'method': M.method, 'method_label': METHODS[M.method], 'folds': M.folds, 'holdback': M.holdback,
        'center': M.center, 'scale': M.scale, 'seed': M.seed, 'factors_asked': M.factors_asked, 'factors_max': M.A_max, 'factors': a,
        'n': int(len(idx)), 'n_train': n, 'sets': counts, 'notes': M.notes, 'cv': cv,
        'percent': [{'factor': k + 1, 'x': float(xe[k]), 'cumx': float(np.sum(xe[:k + 1])), 'y': float(ye[k]), 'cumy': float(np.sum(ye[:k + 1]))} for k in range(a)],
        'coef': B.tolist(), 'coef_orig': Bo.tolist(), 'intercept': b0.tolist(), 'vip': vip.tolist(),
        'x_loadings': f['P'][:, :a].tolist(), 'y_loadings': f['Q'][:, :a].tolist(), 'x_weights': f['W'][:, :a].tolist(),
        'scores': {'rows': idx.tolist(), 'set': sets.tolist(), 't': Tall.tolist(), 'u': Uall.tolist()},
        'dist': {'rows': idx.tolist(), 'set': sets.tolist(), 'dmodx': dmodx.tolist(), 'dmody': dmody.tolist(), 't2': t2.tolist()},
        'dmodx_ok': bool(len(M.xs) > a), 'ucl': ucl,
        'code': _code(M, table, table_name, rows, float(alpha)),
        'plots': {'head_code': _code(M, table, table_name, rows, float(alpha), graph=True),
                  **_plots(M, len(idx), sorted({int(v) for v in sets}), float((plot or {}).get('vip', 0.8)))},
    }


@api('pls.save', packages=predictive.SK)
def save(table, y, x, what='pred', rows=None, validation=None, method='kfold', folds=7, holdback=0.2, factors=15, center=True, scale=True, seed=None):
    """Save Columns: the predicted Y's and the X scores for every row of
    the table with every X (as a formula column), the Y scores for every
    row with every Y and X."""
    M = _model(table, rows, y, x, validation, method, folds, holdback, factors, center, scale, seed)
    a, f = M.a, M.fit
    frame = data.frame(table, M.xs + M.ys, None, dropna=False)
    Xa = frame[M.xs].to_numpy(float)
    okx = np.isfinite(Xa).all(axis=1)
    rx = np.asarray(frame.index, dtype=int)[okx]
    if what == 'pred':
        B, Bo, b0 = pls_coef(f, a)
        pred = b0 + Xa[okx] @ Bo
        return {'rows': rx.tolist(), 'names': [f'Predicted {c}' for c in M.ys], 'values': pred.T.tolist()}
    if what == 'xscores':
        T, _ = pls_scores(f, a, Xa[okx])
        return {'rows': rx.tolist(), 'names': [f'X Score {k + 1}' for k in range(a)], 'values': T.T.tolist()}
    if what == 'yscores':
        Ya = frame[M.ys].to_numpy(float)
        ok = okx & np.isfinite(Ya).all(axis=1)
        _, U = pls_scores(f, a, Xa[ok], Ya[ok])
        return {'rows': np.asarray(frame.index, dtype=int)[ok].tolist(), 'names': [f'Y Score {k + 1}' for k in range(a)], 'values': U.T.tolist()}
    raise ValueError(f'unknown column to save: {what!r}')


def _predictor(table, rows=None, y=(), x=(), validation=None, method='kfold', folds=7, holdback=0.2, factors=15, center=True, scale=True, seed=None):
    """The Prediction Profiler's view of the fit: every Y over the X's
    ranges in the training rows."""
    M = _model(table, rows, y, x, validation, method, folds, holdback, factors, center, scale, seed)
    tr = M.sets == 0
    Xt = M.X[tr]
    B, Bo, b0 = pls_coef(M.fit, M.a)
    factors_ = [{'name': nm, 'type': 'continuous', 'min': float(Xt[:, k].min()), 'max': float(Xt[:, k].max()), 'mean': float(Xt[:, k].mean())} for k, nm in enumerate(M.xs)]

    def run(settings):
        Xs = np.array([[float(s[nm]) for nm in M.xs] for s in settings], dtype=float)
        pred = b0 + Xs @ Bo
        return [{'name': nm, 'pred': pred[:, k], 'lower': None, 'upper': None, 'bounded': False} for k, nm in enumerate(M.ys)]
    return profile.Predictor(factors_, run, data={nm: Xt[:, k].tolist() for k, nm in enumerate(M.xs)})


profile.expose('pls', _predictor, packages=predictive.SK)
