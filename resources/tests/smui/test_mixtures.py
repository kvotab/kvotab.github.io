#!/usr/bin/env python3
"""Analyze > Clustering > Normal Mixtures' backend
(resources/py/smui/mixtures.py), checked against scikit-learn's
GaussianMixture called directly with the same settings (every covariance
structure, scaled and unscaled columns, a range of clusters), against
closed forms (one cluster: the normal log likelihood at the sample mean and
the covariance with the n divisor; the log likelihood of the reported
proportions, means and covariances computed here with scipy; the parameter
counts; AICc and BIC), against the EM's fixed point (each proportion the
mean probability of its cluster, each mean the probability-weighted mean
of the rows), against its own EM with the uniform cluster switched off
(which must be GaussianMixture's EM), on simulated data with planted
outliers (the outlier cluster finds them, BIC picks the true number of
clusters), Freq against repeated rows, and by running the Python shown
under each result on a CSV export of the table.

    python3 resources/tests/smui/test_mixtures.py
"""
import contextlib
import io
import json
import os
import subprocess
import sys
import tempfile
import warnings

import numpy as np
import pandas as pd
from scipy import stats
from scipy.special import logsumexp
import sklearn
from sklearn.mixture import GaussianMixture

from backend import FAILED, PY, Checks, table
from backend import call as _call


def call(fn, **kw):
    """backend.call without the progress lines a range of fits prints."""
    with contextlib.redirect_stdout(io.StringIO()):
        return _call(fn, **kw)


check = Checks()
check('mixtures.py imports', 'mixtures' in FAILED, False)
from smui import mixtures as MX  # noqa: E402
from smui import registry  # noqa: E402

COVS = ('full', 'diag', 'tied', 'spherical')
rng = np.random.default_rng(20260927)


def mx(a, b):
    return float(np.max(np.abs(np.asarray(a, float) - np.asarray(b, float))))


def blobs(sizes, means, sds, seed):
    r = np.random.default_rng(seed)
    parts = [r.normal(m, s, (n, len(m))) for n, m, s in zip(sizes, means, sds)]
    lab = np.concatenate([np.full(n, j) for j, n in enumerate(sizes)])
    return np.vstack(parts), lab


def sk_fit(Z, k, cov, tours, seed, max_iter=500, tol=1e-6):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        return GaussianMixture(n_components=k, covariance_type=cov, n_init=tours, max_iter=max_iter, tol=tol, reg_covar=1e-6, random_state=seed).fit(Z)


def ll_here(X, f):
    """The log likelihood of the reported parameters, in the columns' units."""
    parts = [np.log(w) + stats.multivariate_normal(mean=mu, cov=np.array(C)).logpdf(X).reshape(len(X))
             for w, mu, C in zip(f['weights'], f['means'], f['covs'])]
    if f['outlier_weight'] is not None:
        parts.append(np.full(len(X), np.log(f['outlier_weight'] * f['outlier_density'])))
    return float(logsumexp(np.column_stack(parts), axis=1).sum())


# ---- the package: loaded on first use, never at the start ------------------------------------------------
check('mixtures.fit needs scikit-learn', json.loads(registry.packages_for('mixtures.fit')), ['scikit-learn'])
check('... and so do Save and the profiler', [json.loads(registry.packages_for(n)) for n in ('mixtures.save', 'mixtures.profile', 'mixtures.maximize', 'mixtures.importance')], [['scikit-learn']] * 4)
probe = subprocess.run([sys.executable, '-c', f'import sys; sys.path.insert(0, {PY!r}); import smui.mixtures, smui.embedding; print("sklearn" in sys.modules)'], capture_output=True, text=True)
check('importing the modules does not import scikit-learn', probe.stdout.strip(), 'False')
from sklearn.utils import parallel as sk_parallel  # noqa: E402
check('scikit-learn 1.8 keeps its thread-pool controller in utils.parallel (quiet_threadpoolctl relies on it)', hasattr(sk_parallel, '_get_threadpool_controller'), True)
MX.quiet_threadpoolctl()
check('... and quiet_threadpoolctl() leaves it made', sk_parallel._threadpool_controller is not None, True)

# ---- three clusters in three columns -------------------------------------------------------------------------
TRUE_MEANS = [[10, 50, 3], [15, 80, 4.5], [7, 70, 2]]
XA, labA = blobs([300, 200, 100], TRUE_MEANS, [[1, 5, 0.3], [1.5, 6, 0.4], [0.8, 4, 0.3]], 1)
XA[:, 1] += 0.8 * (XA[:, 0] - 10)          # a correlation within the clusters
cols = ['length', 'weight', 'girth']
tA = table({c: XA[:, j] for j, c in enumerate(cols)})
N, p = XA.shape
m, s = XA.mean(axis=0), XA.std(axis=0, ddof=1)
ZA = (XA - m) / s

for cov in COVS:
    r = call('mixtures.fit', table=tA, columns=cols, k_min=1, k_max=4, covariance=cov, tours=3, seed=11)
    check(f'{cov}: four fits, no error', (r.get('error'), [f['k'] for f in r['fits']], [('error' in f) for f in r['fits']]), (None, [1, 2, 3, 4], [False] * 4))
    worst = {'m2ll': 0, 'bic': 0, 'aic': 0, 'w': 0, 'mu': 0, 'cov': 0, 'lab': 0}
    counts_ok = conv_ok = q_ok = True
    for f in r['fits']:
        gm = sk_fit(ZA, f['k'], cov, 3, 11)
        ll = gm.score(ZA) * N - N * np.log(s).sum()
        worst['m2ll'] = max(worst['m2ll'], abs(f['m2ll'] + 2 * ll) / abs(ll))
        adj = 2 * N * np.log(s).sum()
        worst['bic'] = max(worst['bic'], abs(f['bic'] - (gm.bic(ZA) + adj)) / abs(f['bic']))
        worst['aic'] = max(worst['aic'], abs(f['aic'] - (gm.aic(ZA) + adj)) / abs(f['aic']))
        q_ok &= f['n_params'] == gm._n_parameters()
        o = np.argsort(-gm.weights_, kind='stable')
        worst['w'] = max(worst['w'], mx(f['weights'], gm.weights_[o]))
        worst['mu'] = max(worst['mu'], mx(f['means'], m + s * gm.means_[o]))
        worst['cov'] = max(worst['cov'], mx(f['covs'], MX._full_covs(gm)[o] * np.outer(s, s)[None]))
        worst['lab'] = max(worst['lab'], int(np.sum(np.array(f['labels']) != np.argmax(gm.predict_proba(ZA)[:, o], axis=1))))
        counts_ok &= f['counts'] == np.bincount(f['labels'], minlength=f['k']).astype(float).tolist()
        conv_ok &= (f['converged'], f['n_iter']) == (bool(gm.converged_), int(gm.n_iter_))
        aicc = f['aic'] + 2 * f['n_params'] * (f['n_params'] + 1) / (N - f['n_params'] - 1)
        check.near(f'{cov} k = {f["k"]}: AICc = AIC + 2q(q + 1)/(N − q − 1)', f['aicc'], aicc, rel=1e-12)
    check.near(f'{cov}: −2LogLikelihood = −2 GaussianMixture.score × N, moved to the columns\' units (worst, relative)', float(worst['m2ll']), 0.0, abs_=1e-12)
    check.near(f'{cov}: BIC = GaussianMixture.bic + 2N Σ log s (worst, relative)', float(worst['bic']), 0.0, abs_=1e-12)
    check.near(f'{cov}: AIC = GaussianMixture.aic + 2N Σ log s (worst, relative)', float(worst['aic']), 0.0, abs_=1e-12)
    check(f'{cov}: the number of parameters is GaussianMixture._n_parameters()', q_ok, True)
    check.near(f'{cov}: the proportions are GaussianMixture\'s, largest first', worst['w'], 0.0, abs_=1e-12)
    check.near(f'{cov}: the means are GaussianMixture\'s, in the columns\' units', worst['mu'], 0.0, abs_=1e-9)
    check.near(f'{cov}: the covariances are GaussianMixture\'s, in the columns\' units', worst['cov'], 0.0, abs_=1e-8)
    check(f'{cov}: every row\'s most likely cluster is GaussianMixture\'s', worst['lab'], 0)
    check(f'{cov}: the counts are the rows most likely in each cluster; iterations and convergence are GaussianMixture\'s', (counts_ok, conv_ok), (True, True))
    best = min(r['fits'], key=lambda f: f['bic'])['k']
    check(f'{cov}: the best is the smallest BIC', r['best'], best)
    if cov == 'full':
        check('full: BIC picks the true three clusters', r['best'], 3)
        f3 = next(f for f in r['fits'] if f['k'] == 3)
        agree = max(np.mean(np.array(f3['labels']) == perm) for perm in
                    [np.array(q)[labA] for q in ([0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0])])
        check(f'full, three clusters: the rows\' clusters are the simulated groups ({agree:.3f})', agree > 0.98, True)
        check('full: numbered by proportion, largest first', f3['weights'] == sorted(f3['weights'], reverse=True), True)
    ll_worst = max(abs(f['m2ll'] + 2 * ll_here(XA, f)) / f['m2ll'] for f in r['fits'])
    check.near(f'{cov}: −2LogLikelihood is that of the reported proportions, means and covariances (scipy, the columns\' units)', ll_worst, 0.0, abs_=1e-9)
    check(f'{cov}: the biplot\'s components (p > 2): two per cluster mean', [len(f['pc_means'][0]) for f in r['fits']], [2] * 4)

# unscaled: GaussianMixture on the columns themselves
r = call('mixtures.fit', table=tA, columns=cols, k_min=2, k_max=3, standardize=False, tours=2, seed=4)
for f in r['fits']:
    gm = sk_fit(XA, f['k'], 'full', 2, 4)
    o = np.argsort(-gm.weights_, kind='stable')
    check.near(f'unscaled, k = {f["k"]}: −2LogLikelihood = −2 GaussianMixture.score × N', f['m2ll'], -2 * gm.score(XA) * N, rel=1e-12)
    check.near(f'unscaled, k = {f["k"]}: BIC = GaussianMixture.bic', f['bic'], gm.bic(XA), rel=1e-12)
    check.near(f'unscaled, k = {f["k"]}: the means are GaussianMixture\'s', mx(f['means'], gm.means_[o]), 0.0, abs_=1e-10)
check('unscaled: scale 1, centre 0', (r['scale'], r['center']), ([1.0] * 3, [0.0] * 3))

# ---- closed forms: one cluster -------------------------------------------------------------------------------------
mean1 = XA.mean(axis=0)
cov_ml = np.cov(XA, rowvar=False, ddof=0)
closed = {'full': cov_ml, 'tied': cov_ml, 'diag': np.diag(np.diag(cov_ml)), 'spherical': np.eye(p) * np.diag(cov_ml).mean()}
for cov in COVS:
    r1 = call('mixtures.fit', table=tA, columns=cols, k_min=1, covariance=cov, standardize=False, seed=1)
    f = r1['fits'][0]
    C = closed[cov] + 1e-6 * np.eye(p)
    ll = stats.multivariate_normal(mean=mean1, cov=C).logpdf(XA).sum()
    check.near(f'one cluster, {cov}: −2LogLikelihood = the normal likelihood at the sample mean and the n-divisor covariance', f['m2ll'], -2 * ll, rel=1e-10)
    check.near(f'one cluster, {cov}: the mean is the sample mean', mx(f['means'][0], mean1), 0.0, abs_=1e-9)
    q = {'full': p + p * (p + 1) // 2, 'tied': p + p * (p + 1) // 2, 'diag': 2 * p, 'spherical': p + 1}[cov]
    check(f'one cluster, {cov}: {q} parameters', f['n_params'], q)
    check.near(f'one cluster, {cov}: BIC = −2 log L + q ln N', f['bic'], -2 * ll + q * np.log(N), rel=1e-10)
check.near('one full cluster fitted on the scaled columns: the same likelihood (the fit is equivariant; reg_covar aside)',
           call('mixtures.fit', table=tA, columns=cols, k_min=1)['fits'][0]['m2ll'], call('mixtures.fit', table=tA, columns=cols, k_min=1, standardize=False)['fits'][0]['m2ll'], rel=1e-6)
for cov, k, want in (('full', 3, 3 * 6 + 9 + 2), ('diag', 3, 9 + 9 + 2), ('tied', 3, 6 + 9 + 2), ('spherical', 3, 3 + 9 + 2)):
    check(f'n_parameters({k} clusters, 3 columns, {cov}) = {want}; one more with the outlier cluster', (MX.n_parameters(k, 3, cov), MX.n_parameters(k, 3, cov, True)), (want, want + 1))

# ---- the EM without the uniform cluster is GaussianMixture's --------------------------------------------------------
for cov in COVS:
    for iters, tol in ((5, 0.0), (40, 0.0), (500, 1e-6)):
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            gm = GaussianMixture(3, covariance_type=cov, n_init=4, max_iter=iters, tol=tol, reg_covar=1e-6, random_state=7).fit(ZA)
            em = MX.outlier_em(ZA, 3, cov, 4, 7, iters, tol, uniform=False)
        o1, o2 = np.argsort(-gm.weights_), np.argsort(-em['weights'])
        d = max(mx(em['weights'][o2], gm.weights_[o1]), mx(em['means'][o2], gm.means_[o1]), mx(em['covariances'][o2], MX._full_covs(gm)[o1]))
        check.near(f'outlier_em without the uniform cluster = GaussianMixture ({cov}, {iters} iterations{", tol 1e-6" if tol else ""}): the parameters', d, 0.0, abs_=1e-10)
        check(f'... the same iterations ({cov}, {iters})', em['n_iter'], int(gm.n_iter_))

# ---- the outlier cluster ------------------------------------------------------------------------------------------------
lo, hi = XA.min(axis=0) - 3 * XA.std(axis=0), XA.max(axis=0) + 3 * XA.std(axis=0)
OUT = np.random.default_rng(5).uniform(lo, hi, (30, 3))
XB = np.vstack([XA, OUT])
planted = np.r_[np.zeros(len(XA), bool), np.ones(30, bool)]
tB = table({c: XB[:, j] for j, c in enumerate(cols)})
rB = call('mixtures.fit', table=tB, columns=cols, k_min=1, k_max=5, outlier=True, seed=3, tours=5)
check('with the outlier cluster, BIC picks the true three clusters', rB['best'], 3)
fB = next(f for f in rB['fits'] if f['k'] == 3)
labB = np.array(fB['labels'])
recall = float(np.mean(labB[planted] == 3))
false_pos = float(np.mean(labB[~planted] == 3))
check(f'the outlier cluster (label 3) holds most planted outliers ({recall:.2f}) and few cluster rows ({false_pos:.3f})', (recall >= 0.8, false_pos <= 0.01), (True, True))
check.near(f'its proportion is near the planted share 30/630 ({fB["outlier_weight"]:.4f})', fB['outlier_weight'], 30 / 630, abs_=0.012)
vol = np.prod(XB.max(axis=0) - XB.min(axis=0))
check.near('the uniform density is 1 over the volume of the box that holds the rows', fB['outlier_density'], 1 / vol, rel=1e-10)
check('the counts: three clusters and the outlier cluster, adding to N', (len(fB['counts']), sum(fB['counts'])), (4, float(len(XB))))
check.near('with the outlier cluster: −2LogLikelihood is that of the reported parameters (scipy, with the uniform density)', fB['m2ll'], -2 * ll_here(XB, fB), rel=1e-10)
check('one parameter more than without', fB['n_params'], MX.n_parameters(3, 3, 'full') + 1)
rB0 = call('mixtures.fit', table=tB, columns=cols, k_min=3, seed=3, tours=5)
err_with = mx(np.sort(np.array(fB['means'])[:, 0]), np.sort(np.array(TRUE_MEANS)[:, 0]))
err_without = mx(np.sort(np.array(rB0['fits'][0]['means'])[:, 0]), np.sort(np.array(TRUE_MEANS)[:, 0]))
check(f'the clusters\' means are nearer the truth with the outlier cluster ({err_with:.3f}) than without ({err_without:.3f})', err_with < err_without, True)
rA_out = call('mixtures.fit', table=tA, columns=cols, k_min=3, outlier=True, seed=3, tours=5)
check(f'with no outliers the uniform cluster takes almost nothing ({rA_out["fits"][0]["outlier_weight"]:.4f})', rA_out['fits'][0]['outlier_weight'] < 0.01, True)
# the EM climbs: the log likelihood after 1, 2, ... iterations never falls
ZB = (XB - XB.mean(axis=0)) / XB.std(axis=0, ddof=1)
lbs = []
for it in range(1, 31):
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        lbs.append(MX.outlier_em(ZB, 3, 'full', 1, 9, it, 0.0)['lower_bound'])
check('the EM with the uniform cluster never lowers the likelihood (30 iterations)', bool(np.all(np.diff(lbs) >= -1e-12)), True)
for cov in COVS:
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        lb2 = [MX.outlier_em(ZB, 2, cov, 1, 2, it, 0.0)['lower_bound'] for it in range(1, 16)]
    check(f'... nor with {cov} covariances', bool(np.all(np.diff(lb2) >= -1e-12)), True)

# ---- the EM's fixed point, from the saved probabilities -------------------------------------------------------------
for label, tid, X_, kw in (('normal clusters', tA, XA, {}), ('with the outlier cluster', tB, XB, {'outlier': True})):
    rf = call('mixtures.fit', table=tid, columns=cols, k_min=3, tol=1e-11, max_iter=5000, seed=3, tours=2, **kw)
    sv = call('mixtures.save', table=tid, columns=cols, k=3, k_min=3, tol=1e-11, max_iter=5000, seed=3, tours=2, **kw)
    P = np.array(sv['prob'])
    f = rf['fits'][0]
    props = f['weights'] + ([f['outlier_weight']] if kw else [])
    check.near(f'{label}: each proportion is the mean probability of its cluster (the EM\'s fixed point)', mx(P.mean(axis=0), props), 0.0, abs_=1e-7)
    wm = (P[:, :3].T @ X_) / P[:, :3].sum(axis=0)[:, None]
    check.near(f'{label}: each mean is the probability-weighted mean of the rows', mx(wm, f['means']), 0.0, abs_=1e-5)
    check(f'{label}: the probabilities of a row add to 1, the saved cluster is the most likely', (bool(np.allclose(P.sum(axis=1), 1)), sv['cluster'] == (np.array(f['labels']) + 1).tolist()), (True, True))
check('the saved columns\' names', sv['names'], ['Prob[Cluster 1]', 'Prob[Cluster 2]', 'Prob[Cluster 3]', 'Prob[Outlier]'])

# ---- Freq: rows counted, as if repeated --------------------------------------------------------------------------------
fq = np.random.default_rng(8).integers(1, 4, len(XA)).astype(float)
tF = table({**{c: XA[:, j] for j, c in enumerate(cols)}, 'n': fq})
tR = table({c: np.repeat(XA[:, j], fq.astype(int)) for j, c in enumerate(cols)})
for kw in ({}, {'outlier': True}, {'covariance': 'diag'}):
    lab_ = 'Freq' + (f' ({", ".join(f"{k}={v}" for k, v in kw.items())})' if kw else '')
    a = call('mixtures.fit', table=tF, columns=cols, freq='n', k_min=2, k_max=3, seed=6, tours=2, **kw)
    b = call('mixtures.fit', table=tR, columns=cols, k_min=2, k_max=3, seed=6, tours=2, **kw)
    same = all(abs(x['m2ll'] - y['m2ll']) <= 1e-9 * abs(y['m2ll']) and mx(x['means'], y['means']) < 1e-9 and x['n_params'] == y['n_params'] for x, y in zip(a['fits'], b['fits']))
    check(f'{lab_}: the fits are those of the rows repeated', same, True)
    check(f'{lab_}: N is the sum of the frequencies, the rows are the table\'s', (a['n'], a['n_rows'], len(a['fits'][0]['labels'])), (int(fq.sum()), len(XA), len(XA)))
    check(f'{lab_}: the counts add to N', sum(a['fits'][0]['counts']), float(fq.sum()))
fq2 = fq.copy()
fq2[:3] = [0, np.nan, 2.5]
tF2 = table({**{c: XA[:, j] for j, c in enumerate(cols)}, 'n': fq2})
r2 = call('mixtures.fit', table=tF2, columns=cols, freq='n', k_min=2, seed=6)
check('Freq: a missing frequency or one below 1 leaves the row out; fractions are rounded down', (r2['n_rows'], r2['n'], any('below 1' in t for t in r2['notes']), any('rounded down' in t for t in r2['notes'])),
      (len(XA) - 2, int(np.floor(fq2[2:]).sum()), True, True))

# ---- rows, missing values, errors ---------------------------------------------------------------------------------
sub = list(range(0, 600, 2))
rs = call('mixtures.fit', table=tA, columns=cols, rows=sub, k_min=3, seed=2)
tS = table({c: XA[sub, j] for j, c in enumerate(cols)})
rs2 = call('mixtures.fit', table=tS, columns=cols, k_min=3, seed=2)
check('a row list (a By group, exclusions) limits the fit to those rows', (rs['n'], rs['rows'][:3], abs(rs['fits'][0]['m2ll'] - rs2['fits'][0]['m2ll']) < 1e-8), (300, [0, 2, 4], True))
XM = XA.copy()
XM[5, 1] = np.nan
tM = table({c: XM[:, j] for j, c in enumerate(cols)})
rm = call('mixtures.fit', table=tM, columns=cols, k_min=2, seed=2)
check('a row with a missing value is left out, and said so', (rm['n'], 5 in rm['rows'], rm['notes']), (599, False, ['1 row with a missing value left out.']))
check('no column: an error', call('mixtures.fit', table=tA, columns=[]).get('error'), 'choose one or more Y, Columns')
tC = table({'a': XA[:, 0], 'c': np.ones(len(XA))})
check('a column with one value: an error that names it', call('mixtures.fit', table=tC, columns=['a', 'c']).get('error', ''), 'c has a single value in these rows: nothing to cluster by')
tT = table({'a': [1.0, 2.0, 3.5, 4.0], 'b': [2.0, 1.0, 0.5, 3.0]})
rt_ = call('mixtures.fit', table=tT, columns=['a', 'b'], k_min=2, k_max=4, seed=1)
check('too few rows for a number of clusters: that fit has an error, the others are there', [('error' in f) for f in rt_['fits']], [False, False, True])
check('a range of more than 20 is cut to 20 fits', len(call('mixtures.fit', table=tA, columns=['length'], k_min=1, k_max=40, tours=1, seed=1)['fits']), 20)
check('Tours outside 1 to 100: an error', 'error' in call('mixtures.fit', table=tA, columns=cols, tours=0) and 'error' in call('mixtures.fit', table=tA, columns=cols, tours=101), True)
check('an unknown covariance structure: an error', 'error' in call('mixtures.fit', table=tA, columns=cols, covariance='banded'), True)
ra = call('mixtures.fit', table=tA, columns=cols, k_min=1, k_max=5, choose='aicc', seed=11, tours=3)
check('Best By AICc: the smallest AICc', (ra['choose'], ra['best']), ('aicc', min(ra['fits'], key=lambda f: f['aicc'])['k']))
r_again = call('mixtures.fit', table=table({c: XA[:, j] for j, c in enumerate(cols)}), columns=cols, k_min=3, seed=11, tours=3)
check('the same seed gives the same fit (a new table, so no cache)', abs(r_again['fits'][0]['m2ll'] - next(f for f in call('mixtures.fit', table=tA, columns=cols, k_min=1, k_max=4, covariance='full', tours=3, seed=11)['fits'] if f['k'] == 3)['m2ll']) < 1e-9, True)

# ---- one column --------------------------------------------------------------------------------------------------------
x1 = np.r_[np.random.default_rng(3).normal(0, 1, 300), np.random.default_rng(4).normal(6, 1.5, 200)]
t1 = table({'x': x1})
r1d = call('mixtures.fit', table=t1, columns=['x'], k_min=1, k_max=3, seed=5)
f2 = next(f for f in r1d['fits'] if f['k'] == 2)
check('one column: BIC picks two clusters', r1d['best'], 2)
check.near('one column: the means near 0 and 6', mx(sorted(m_[0] for m_ in f2['means']), [0, 6]), 0.0, abs_=0.25)
check('one column: no biplot, no principal components', ('pca' in r1d, 'pc_means' in f2), (False, False))
check.near('one column: −2LogLikelihood is that of the two normals (scipy)', f2['m2ll'], -2 * float(logsumexp(np.column_stack([np.log(w) + stats.norm(mu[0], sd[0]).logpdf(x1) for w, mu, sd in zip(f2['weights'], f2['means'], f2['sds'])]), axis=1).sum()), rel=1e-10)

# ---- the profiler of the cluster probabilities ---------------------------------------------------------------------------
spec = dict(columns=cols, k_min=1, k_max=4, covariance='full', tours=3, seed=11)
pr = call('mixtures.profile', table=tA, k=3, current={'length': 12.0}, **spec)
check('the profiler: the three columns as factors, with their ranges', [(f_['name'], round(f_['min'], 6), round(f_['max'], 6)) for f_ in pr['factors']], [(c, round(XA[:, j].min(), 6), round(XA[:, j].max(), 6)) for j, c in enumerate(cols)])
check('... a bounded response per cluster', [(q_['name'], q_['bounded']) for q_ in pr['responses']], [('Prob[Cluster 1]', True), ('Prob[Cluster 2]', True), ('Prob[Cluster 3]', True)])
check.near('... whose probabilities at the current setting add to 1', sum(q_['current']['pred'] for q_ in pr['responses']), 1.0, abs_=1e-12)
at = np.array([[12.0, XA[:, 1].mean(), XA[:, 2].mean()]])
gm3 = sk_fit(ZA, 3, 'full', 3, 11)
o3 = np.argsort(-gm3.weights_, kind='stable')
want = gm3.predict_proba((at - m) / s)[0, o3]
check.near('... and are GaussianMixture\'s predict_proba there', mx([q_['current']['pred'] for q_ in pr['responses']], want), 0.0, abs_=1e-12)
check('the profiler brings Maximize Desirability and Variable Importance with it', all(n in registry.names() for n in ('mixtures.profile', 'mixtures.maximize', 'mixtures.importance')), True)
imp = call('mixtures.importance', table=tA, k=3, imp_method='resampled', imp_n=64, **spec)
check('Variable Importance runs on the resampled columns (Sobol indices for every cluster)', len(imp.get('responses', imp.get('rows', []))) > 0 or bool(imp), True)
pro = call('mixtures.profile', table=tB, k=3, **{**spec, 'outlier': True, 'k_min': 1, 'k_max': 5, 'seed': 3, 'tours': 5})
check('with the outlier cluster the profiler has its probability too', [q_['name'] for q_ in pro['responses']][-1], 'Prob[Outlier]')

# ---- progress lines -------------------------------------------------------------------------------------------------------
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    _call('mixtures.fit', table=tA, columns=cols, k_min=2, k_max=5, seed=99)
lines = [ln for ln in buf.getvalue().splitlines() if ln.startswith('smui:progress')]
check('a range prints a progress line per fit', lines, [f'smui:progress mixtures {i} 4' for i in range(1, 5)])
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    _call('mixtures.fit', table=tA, columns=cols, k_min=4, seed=99)
check('one fit prints none', [ln for ln in buf.getvalue().splitlines() if ln.startswith('smui:progress')], [])

# ---- the Python shown runs on a CSV export and prints the report's numbers ---------------------------------------------------
work = tempfile.mkdtemp()


def run(code):
    with open(os.path.join(work, 'code.py'), 'w') as fh:
        fh.write(code)
    p_ = subprocess.run([sys.executable, 'code.py'], cwd=work, capture_output=True, text=True, timeout=900)
    if p_.returncode:
        print(p_.stderr[-3000:])
    return p_


def printed(out):
    got = {}
    for ln in out.splitlines():
        t = ln.split()
        if not t:
            continue
        if t[0] == 'fit':
            got[f'fit {int(t[1])}'] = [float(v) for v in t[2:]]
        elif t[0] in ('mean', 'sd'):
            got[f'{t[0]} {t[1]}'] = [float(v) for v in t[2:]]
        elif t[0] in ('proportion', 'count'):
            got[t[0]] = [float(v) for v in t[1:]]
    return got


def compare(res, label, rows_note=''):
    p_ = run(res['code'])
    if not check(f'the Cluster Comparison code runs ({label})', p_.returncode, 0):
        return
    got = printed(p_.stdout)
    worst = 0.0
    for f in res['fits']:
        g = got[f'fit {f["k"]}']
        want = [f['m2ll'], f['n_params'], f['aicc'], f['bic']]
        worst = max(worst, max(abs(a - b) / max(1.0, abs(b)) for a, b in zip(g, want)))
    check.near(f'... and prints the report\'s −2LogLikelihood, parameters, AICc and BIC ({label})', worst, 0.0, abs_=1e-10)
    f = next(f for f in res['fits'] if f['k'] == res['best'])
    p_ = run(f['code'])
    if not check(f'the code of the best fit runs ({label})', p_.returncode, 0):
        return
    got = printed(p_.stdout)
    props = f['weights'] + ([f['outlier_weight']] if f['outlier_weight'] is not None else [])
    d = max(mx(got['proportion'], props), mx(got['count'], f['counts']),
            max(mx(got[f'mean {j + 1}'], f['means'][j]) for j in range(f['k'])), max(mx(got[f'sd {j + 1}'], f['sds'][j]) for j in range(f['k'])))
    check.near(f'... and prints its proportions, counts, means and standard deviations ({label})', d, 0.0, abs_=1e-9)


pd.DataFrame({c: XB[:, j] for j, c in enumerate(cols)}).to_csv(os.path.join(work, 'data.csv'), index=False)
compare(call('mixtures.fit', table=tB, columns=cols, k_min=1, k_max=4, seed=3, tours=3, table_name='data'), 'normal clusters, scaled')
compare(call('mixtures.fit', table=tB, columns=cols, k_min=2, k_max=4, seed=3, tours=3, outlier=True, table_name='data'), 'the outlier cluster')
compare(call('mixtures.fit', table=tB, columns=cols, k_min=2, k_max=3, seed=8, tours=2, covariance='spherical', standardize=False, table_name='data'), 'spherical, unscaled')
compare(call('mixtures.fit', table=tB, columns=cols, k_min=2, k_max=3, seed=8, tours=2, covariance='tied', rows=list(range(0, 630, 3)), table_name='data'), 'tied, a row list')
compare(call('mixtures.fit', table=tB, columns=cols, k_min=2, k_max=3, seed=8, tours=2, covariance='diag', rows=list(range(40, 630)), outlier=True, table_name='data'), 'diagonal with the outlier cluster, rows dropped')
fq3 = np.random.default_rng(2).integers(1, 3, len(XB)).astype(float)
pd.DataFrame({**{c: XB[:, j] for j, c in enumerate(cols)}, 'count (n)': fq3}).to_csv(os.path.join(work, 'freq.csv'), index=False)
tF3 = table({**{c: XB[:, j] for j, c in enumerate(cols)}, 'count (n)': fq3})
compare(call('mixtures.fit', table=tF3, columns=cols, freq='count (n)', k_min=2, k_max=3, seed=5, tours=2, table_name='freq'), 'Freq')
compare(call('mixtures.fit', table=tF3, columns=cols, freq='count (n)', k_min=3, seed=5, tours=2, outlier=True, table_name='freq'), 'Freq with the outlier cluster')
code = call('mixtures.fit', table=tB, columns=cols, k_min=3, outlier=True, seed=3, table_name='data')['code']
check('the outlier cluster\'s code carries its EM (outlier_em and mixture_log_parts, from the module\'s own source)', ('def outlier_em(' in code and 'def mixture_log_parts(' in code and 'GaussianMixture(' not in code), (True))
code = call('mixtures.fit', table=tB, columns=cols, k_min=3, seed=3, table_name='data')['code']
check('the normal clusters\' code is GaussianMixture\'s', ('GaussianMixture(n_components=k' in code and 'outlier_em' not in code), True)

# ---- the graphs' code: the criteria graph whole, the lines the page's graphs start with -------------------------
# (the page adds the drawing: its choices; test-ui-mixtures.py runs those blocks in the page)
from test_charts import run_snippet  # noqa: E402


def frag_vars(code, csv_name, label):
    """A fragment run on the whole table's CSV: its variables."""
    ns, here = {}, os.getcwd()
    os.chdir(work)
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            exec(compile(code.replace('data.csv', csv_name), label, 'exec'), ns)
    except Exception as e:   # the check below reports it
        ns['__error__'] = f'{type(e).__name__}: {e}'
    finally:
        os.chdir(here)
    check(f'{label}: runs', ns.get('__error__'), None)
    return ns


def graph_checks(res, label, csv_name='data.csv', frame=None):
    ok = [f for f in res['fits'] if 'error' not in f]
    if len(ok) >= 3:
        figs, err = run_snippet(res['criteria_code'].replace('data.csv', csv_name), frame, csv_name[:-4], work)
        check(f'the Cluster Criteria graph\'s code runs ({label})', (err, len(figs or [])), (None, 1))
        if figs:
            ax = figs[0]['axes'][0]
            by = {ln['label']: ln for ln in ax['lines']}
            ks = [f['k'] for f in ok]
            check.near(f'... BIC and AICc of each number of clusters ({label})', max(mx(by['BIC']['y'], [f['bic'] for f in ok]), mx(by['AICc']['y'], [f['aicc'] for f in ok]), mx(by['BIC']['x'], ks)), 0.0, abs_=1e-8)
            check(f'... the titles and the size ({label})', (ax['xlabel'], ax['ylabel'], ax['title'], figs[0]['size'], [float(k) for k in ks] == ax['xticks'][:len(ks)] or ax['xticks'] == [float(k) for k in ks]),
                  ('NCluster', 'Criterion', 'Cluster criteria', [4.6, 2.5], True))
    else:
        check(f'fewer than three fits: no criteria graph ({label})', 'criteria_code' in res, False)
    f = next(f for f in ok if f['k'] == res['best'])
    ns = frag_vars(f['fit_head'] + ('\n' + res['pca_lines'] if res.get('pca_lines') else ''), csv_name, f'the lines under the graphs of {f["k"]} clusters ({label})')
    if 'cluster' not in ns:
        return
    check(f'... each row\'s cluster is the report\'s ({label})', ns['cluster'].tolist(), f['labels'])
    props = f['weights'] + ([f['outlier_weight']] if f['outlier_weight'] is not None else [])
    check.near(f'... and so are the proportions, means and covariances in the columns\' units ({label})',
               max(mx(ns['w'], props), mx(ns['means'][:f['k']], f['means']), mx(ns['covs'][:f['k']], f['covs'])), 0.0, abs_=1e-9)
    if f['outlier_weight'] is not None:
        check.near(f'... and the outlier cluster\'s density ({label})', float(ns['box_density']), f['outlier_density'], rel=1e-12)
    if res.get('pca_lines'):
        check.near(f'... the rows\' principal component scores and eigenvalues ({label})', max(mx(ns['scores'], res['pca']['scores']), mx(ns['evals'], res['pca']['eigenvalues'])), 0.0, abs_=1e-9)
        check.near(f'... each cluster carried onto the components ({label})', max(mx(ns['pc_means'], f['pc_means']), mx(ns['pc_covs'], f['pc_covs'])), 0.0, abs_=1e-9)


frameB = pd.DataFrame({c: XB[:, j] for j, c in enumerate(cols)})
graph_checks(call('mixtures.fit', table=tB, columns=cols, k_min=1, k_max=4, seed=3, tours=3, table_name='data'), 'normal clusters, a range', frame=frameB)
graph_checks(call('mixtures.fit', table=tB, columns=cols, k_min=2, k_max=4, seed=3, tours=3, outlier=True, table_name='data'), 'the outlier cluster', frame=frameB)
graph_checks(call('mixtures.fit', table=tB, columns=cols, k_min=2, k_max=3, seed=8, tours=2, covariance='spherical', standardize=False, table_name='data'), 'spherical, unscaled', frame=frameB)
graph_checks(call('mixtures.fit', table=tF3, columns=cols, freq='count (n)', k_min=2, k_max=4, seed=5, tours=2, table_name='freq'), 'Freq', 'freq.csv',
             pd.DataFrame({**{c: XB[:, j] for j, c in enumerate(cols)}, 'count (n)': fq3}))
# a By group (its where line) with rows left out; one column (the density's lines)
grpB = ['u' if i % 3 else 'v' for i in range(len(XB))]
tG = table({**{c: XB[:, j] for j, c in enumerate(cols)}, 'grp': grpB})
frameG = pd.DataFrame({**{c: XB[:, j] for j, c in enumerate(cols)}, 'grp': grpB})
frameG.to_csv(os.path.join(work, 'bygroup.csv'), index=False)
rows_u = [i for i in range(len(XB)) if grpB[i] == 'u' and i not in (1, 2, 4)]
rg = call('mixtures.fit', table=tG, columns=cols, rows=rows_u, where=[{'column': 'grp', 'value': 'u'}], k_min=2, k_max=4, seed=4, tours=2, table_name='bygroup')
check('a By group: the code keeps its rows, drops the ones left out', all('df = df[df["grp"] == "u"]' in c and 'df = df.drop(index=[1, 2, 4])' in c for c in [rg['code'], rg['criteria_code'], rg['fits'][0]['fit_head'], rg['fits'][0]['code']]), True)
graph_checks(rg, 'a By group, rows left out', 'bygroup.csv', frameG)
r1 = call('mixtures.fit', table=tB, columns=[cols[0]], k_min=2, seed=3, tours=2, outlier=True, table_name='data')
graph_checks(r1, 'one column with the outlier cluster', frame=frameB)

# ---- Save Clusters and Save Mixture Probabilities for every row; Save Mixture Formulas ---------------------------------
# Every row of the By group whose columns are present gets its cluster and probabilities from the report's fit: the
# rows the fit leaves out (excluded) too, scored by scikit-learn's GaussianMixture fitted here to the report's rows.
# The formulas (JMP's Dist Formula <k>, Dist Total, Prob Formula <k>, and the Cluster Formula) are computed by the
# page's formula language (smui-formula.js in node) on the whole table and checked against those probabilities and
# against scipy's normal densities of the reported means and covariances.
import shutil  # noqa: E402

NODE = shutil.which('node')
FORMULA_JS = r"""
const fs = require('fs'), path = require('path'), vm = require('vm');
const spec = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const sb = { console }; sb.self = sb; vm.createContext(sb);
for (const f of ['smui-util.js', 'smui-table.js', 'smui-formula.js']) vm.runInContext(fs.readFileSync(path.join(spec.js, f), 'utf8'), sb, { filename: f });
const SM = sb.SM;
const t = new SM.Table({ name: 't', columns: spec.columns.map((c) => ({ name: c.name, dataType: c.char ? 'character' : 'numeric', values: c.values.map((v) => (v == null ? (c.char ? null : NaN) : v)) })) });
const ref = (name) => `:"${String(name).replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
const out = [], made = [];
for (const s of spec.saved) {
  const c = t.addColumn({ name: s.name, dataType: 'numeric', values: [] });
  made.push(c);
  try { SM.formula.apply(t, c, s.formula.replace(/\{\{col:(\d+)\}\}/g, (_, j) => ref(made[+j].name))); } catch (e) { out.push({ name: c.name, error: e.message }); continue; }
  out.push({ name: c.name, values: Array.from(c.values, (v) => (typeof v === 'number' && !Number.isFinite(v) ? null : v)) });
}
process.stdout.write(JSON.stringify(out));
"""


def formula_values(columns, saved):
    """The saved formulas computed by the page's formula language on a table of these columns ({name: values});
    None without node."""
    if not NODE:
        return None
    d = tempfile.mkdtemp(prefix='smui-mix-formula-')
    with open(os.path.join(d, 'f.js'), 'w') as fh:
        fh.write(FORMULA_JS)
    cols_ = [{'name': k, 'char': any(isinstance(x, str) for x in v), 'values': [None if x is None or (not isinstance(x, str) and not np.isfinite(x)) else (x if isinstance(x, str) else float(x)) for x in v]} for k, v in columns.items()]
    with open(os.path.join(d, 's.json'), 'w') as fh:
        json.dump({'js': os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'js')), 'columns': cols_,
                   'saved': [{'name': c['name'], 'formula': c['formula']} for c in saved]}, fh)
    r = subprocess.run([NODE, os.path.join(d, 'f.js'), os.path.join(d, 's.json')], capture_output=True, text=True, timeout=300)
    if r.returncode:
        raise RuntimeError(r.stderr)
    return json.loads(r.stdout)


def col_of(res, name):
    c = next(x for x in res if x['name'] == name)
    if 'error' in c:
        raise RuntimeError(f'{name}: {c["error"]}')
    return np.array([np.nan if v is None else v for v in c['values']], dtype=float)


if not NODE:
    print('note: node is not installed; the formula checks are skipped')
XS = XA[:240].copy()
XS[9, 2] = np.nan                         # a row with a missing value: no cluster, no probability
XS[30] = [40.0, 300.0, 30.0]              # a row far from every cluster: its densities underflow
grpS = np.where(np.arange(240) % 3 == 0, 'g1', 'g2')
colsS = {**{c: XS[:, j] for j, c in enumerate(cols)}, 'g': grpS.tolist()}
tS2 = table(colsS)
fitted = [i for i in range(240) if i not in (1, 2, 3, 30) and np.isfinite(XS[i]).all()]   # rows 1-3 excluded, the far row too
for cov in COVS:
    for kw in ({}, {'outlier': True}):
        tag = f'saved columns ({cov}{", outlier cluster" if kw else ""})'
        base = dict(table=tS2, columns=cols, rows=fitted, k_min=3, covariance=cov, seed=5, tours=2, **kw)
        rf = call('mixtures.fit', **base)
        f = rf['fits'][0]
        sv = call('mixtures.save', k=3, **base)
        rows_ = sv['rows']
        want_rows = [i for i in range(240) if np.isfinite(XS[i]).all()]
        check(f'{tag}: every row whose columns are present, excluded ones too', rows_, want_rows)
        P = np.array(sv['prob'])
        at = {r: i for i, r in enumerate(rows_)}
        check(f'{tag}: the report\'s own rows keep their clusters', [sv['cluster'][at[r]] for r in rf['rows']], [c + 1 for c in f['labels']])
        if not kw:
            # scikit-learn fitted here to the report's rows (scaled as the report scales them) scores the others
            Xf = XS[fitted]
            m_, s_ = Xf.mean(0), Xf.std(0, ddof=1)
            gm = sk_fit((Xf - m_) / s_, 3, cov, 2, 5)
            o_ = np.argsort(-gm.weights_, kind='stable')
            Psk = gm.predict_proba((XS[want_rows] - m_) / s_)[:, o_]
            check.near(f'{tag}: the probabilities of every row = scikit-learn\'s predict_proba of the same fit', mx(P, Psk), 0.0, abs_=1e-9)
        fm = call('mixtures.formulas', k=3, **base)
        m = 3 + (1 if kw else 0)
        names = [c['name'] for c in fm['columns']]
        want_names = [f'Dist Formula {j + 1}' for j in range(3)] + (['Dist Formula Outlier'] if kw else []) + ['Dist Total'] + [f'Prob Formula {j + 1}' for j in range(3)] + (['Prob Formula Outlier'] if kw else []) + ['Cluster Formula']
        check(f'{tag}: JMP\'s Dist Formula, Dist Total and Prob Formula columns, and the Cluster Formula', names, want_names)
        fr = formula_values(colsS, fm['columns'])
        if fr is None:
            continue
        Pf = np.column_stack([col_of(fr, n_) for n_ in names[m + 1:2 * m + 1]])
        Df = np.column_stack([col_of(fr, n_) for n_ in names[:m]])
        tot = col_of(fr, 'Dist Total')
        near_rows = [r for r in want_rows if r != 30]
        check.near(f'{tag}: the Prob formulas = the saved probabilities (every row but the far one)', mx(Pf[near_rows], P[[at[r] for r in near_rows]]), 0.0, abs_=1e-12)
        dens = np.column_stack([w_ * stats.multivariate_normal(mean=mu_, cov=np.array(C_)).pdf(XS[near_rows]) for w_, mu_, C_ in zip(f['weights'], f['means'], f['covs'])])
        if kw:
            dens = np.column_stack([dens, np.full(len(near_rows), f['outlier_weight'] * f['outlier_density'])])
        check.near(f'{tag}: each Dist formula = the share times the normal density of the reported mean and covariance (scipy)', float(np.max(np.abs(Df[near_rows] - dens) / np.maximum(dens, 1e-300))), 0.0, abs_=1e-9)
        check.near(f'{tag}: Dist Total = their sum, the mixture\'s density', float(np.max(np.abs(tot[near_rows] - dens.sum(1)) / dens.sum(1))), 0.0, abs_=1e-9)
        cf = col_of(fr, 'Cluster Formula')
        check(f'{tag}: the Cluster Formula = Save Clusters on every row', [cf[r] for r in want_rows], [float(c) for c in sv['cluster']])
        check(f'{tag}: a row with a missing value: nothing', (bool(np.isnan(cf[9])), bool(np.isnan(Pf[9]).all())), (True, True))
        if not kw:
            check(f'{tag}: the far row: its densities underflow, so the Prob formulas are missing, as JMP\'s (Save Mixture Probabilities has them)', (bool(np.isnan(Pf[30]).all()), bool(np.isfinite(P[at[30]]).all())), (True, True))
        check(f'{tag}: ... but it has a Cluster Formula, from the log densities', cf[30], float(sv['cluster'][at[30]]))
# a By group: the other group's rows get nothing
g1 = [i for i in range(240) if grpS[i] == 'g1' and np.isfinite(XS[i]).all() and i != 30]
fmg = call('mixtures.formulas', table=tS2, columns=cols, rows=g1, k=2, k_min=2, seed=5, tours=2, where=[{'column': 'g', 'value': 'g1'}])
svg = call('mixtures.save', table=tS2, columns=cols, rows=g1, k=2, k_min=2, seed=5, tours=2, where=[{'column': 'g', 'value': 'g1'}])
check('a By group: Save Mixture Probabilities gives the group\'s rows only', svg['rows'], [i for i in range(240) if grpS[i] == 'g1' and np.isfinite(XS[i]).all()])
fr = formula_values(colsS, fmg['columns'])
if fr is not None:
    cf = col_of(fr, 'Cluster Formula')
    check('a By group: the formulas are missing outside the group', bool(np.isnan(cf[grpS == 'g2']).all()), True)
    check('... and give the group\'s rows their saved clusters', [cf[r] for r in svg['rows']], [float(c) for c in svg['cluster']])

sys.exit(check.done())
