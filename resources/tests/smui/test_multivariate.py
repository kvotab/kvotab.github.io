#!/usr/bin/env python3
"""Analyze > Multivariate Methods, Clustering and Screening: the backend
(resources/py/smui/multivariate.py), checked against statsmodels and scipy
called directly, against brute-force computations of the definitions JMP
documents, and against published values (the cubic clustering criterion of
the Fisher iris example in the SAS PROC CLUSTER and FASTCLUS documentation;
the distance correlation of a bivariate normal, Székely, Rizzo and Bakirov
2007, Theorem 7). The data are simulated here from fixed seeds.

    python3 resources/tests/smui/test_multivariate.py
"""
import itertools
import math
import sys

import numpy as np
import pandas as pd
import statsmodels.api as sm
from scipy import stats
from scipy.cluster.hierarchy import fcluster
from scipy.cluster.vq import kmeans2

from backend import Checks, call, table
from smui import multivariate as mv

check = Checks()
rng = np.random.default_rng(20260926)

# ---- a table with correlated columns, one missing value and a weight ----------
n = 150
z = rng.normal(size=(n, 2))
X = np.column_stack([z[:, 0] + 0.3 * rng.normal(size=n), z[:, 0] + 0.5 * rng.normal(size=n),
                     z[:, 1] + 0.4 * rng.normal(size=n), z[:, 1] - 0.3 * z[:, 0] + 0.6 * rng.normal(size=n),
                     0.5 * z[:, 0] + 0.5 * z[:, 1] + 0.7 * rng.normal(size=n), rng.normal(size=n)])
cols = ['a', 'b', 'c', 'd', 'e', 'f']
Xm = X.copy()
Xm[7, 1] = np.nan
wt = rng.integers(1, 4, n).astype(float)
grp = np.where(z[:, 0] > 0.4, 'hi', np.where(z[:, 1] > 0, 'mid', 'lo'))
tid = table({**{c: Xm[:, j] for j, c in enumerate(cols)}, 'w': wt, 'g': grp.tolist()})
ok = np.isfinite(Xm).all(1)
Xc = Xm[ok]
nc = len(Xc)

# ---- Multivariate: correlations ---------------------------------------------------------
r = call('multivariate.fit', table=tid, columns=cols)
R = np.corrcoef(Xc, rowvar=False)
check('row-wise uses the complete rows', (r['n'], r['n_missing_rows']), (float(nc), 1))
check.near('correlation a,b', r['corr'][0][1], R[0, 1])
check.near('correlation e,f', r['corr'][4][5], R[4, 5])
pr = stats.pearsonr(Xc[:, 0], Xc[:, 3])
check.near('p-value of a correlation (scipy pearsonr)', r['p'][0][3], float(pr.pvalue))
ci = pr.confidence_interval(0.95)
check.near('Fisher z lower limit (scipy)', r['lower'][0][3], float(ci.low))
check.near('Fisher z upper limit (scipy)', r['upper'][0][3], float(ci.high))
check.near('covariance (numpy, n-1)', r['cov'][1][2], float(np.cov(Xc, rowvar=False)[1, 2]))
# inverse correlations: the diagonal is 1/(1 - R2) of each column on the others
ols = sm.OLS(Xc[:, 2], sm.add_constant(np.delete(Xc, 2, axis=1))).fit()
check.near('inverse correlation diagonal = VIF (statsmodels OLS)', r['inv'][2][2], 1 / (1 - ols.rsquared))
# partial correlation: the correlation of the residuals given the others
others = sm.add_constant(np.delete(Xc, [0, 1], axis=1))
ra = sm.OLS(Xc[:, 0], others).fit().resid
rb = sm.OLS(Xc[:, 1], others).fit().resid
rab = float(np.corrcoef(ra, rb)[0, 1])
check.near('partial correlation = correlation of OLS residuals', r['partial'][0][1], rab)
t = rab * math.sqrt((nc - 6) / (1 - rab * rab))
check.near('partial correlation p-value (t, n - p df)', r['partial_p'][0][1], float(2 * stats.t.sf(abs(t), nc - 6)))
# pairwise: each pair on its own complete rows (pandas' corr is pairwise)
rp = call('multivariate.fit', table=tid, columns=cols, method='pairwise')
dfm = pd.DataFrame(Xm, columns=cols)
check.near('pairwise correlation a,b (pandas)', rp['corr'][0][1], float(dfm.corr().loc['a', 'b']))
check('pairwise counts', (rp['count'][0][1], rp['count'][0][2]), (float(n - 1), float(n)))
pc = [x for x in r['pairs'] if x['var'] == 'c' and x['by'] == 'a'][0]
check.near('Pairwise Correlations: r', pc['r'], float(dfm[['a', 'c']].corr().iloc[0, 1]))
check('Pairwise Correlations: count', pc['count'], float(n))
check.near('Pairwise Correlations: p (scipy)', pc['p'], float(stats.pearsonr(Xm[:, 0], Xm[:, 2]).pvalue))
# simple statistics
u = {s['column']: s for s in r['uni']}
check.near('univariate mean of b (its own rows)', u['b']['mean'], float(np.nanmean(Xm[:, 1])))
check.near('univariate std dev of b', u['b']['sd'], float(np.nanstd(Xm[:, 1], ddof=1)))
mm = {s['column']: s for s in r['multi']}
check.near('multivariate mean of a (complete rows)', mm['a']['mean'], float(Xc[:, 0].mean()))
# weights: statsmodels DescrStatsW
from statsmodels.stats.weightstats import DescrStatsW  # noqa: E402
rw = call('multivariate.fit', table=tid, columns=cols, freq='w')
d = DescrStatsW(Xc, weights=wt[ok], ddof=1)
check.near('weighted correlation (DescrStatsW)', rw['corr'][0][4], float(d.corrcoef[0, 4]))
check.near('weighted covariance (DescrStatsW)', rw['cov'][0][4], float(d.cov[0, 4]))
check('freq counts as observations', rw['n'], float(wt[ok].sum()))
check('code shown', 'corr()' in r['code'], True)

# ---- Multivariate: nonparametric -------------------------------------------------------------
sp = call('multivariate.nonparametric', table=tid, columns=cols, measure='spearman')
x0 = sp['pairs'][0]
okp = np.isfinite(Xm[:, 0]) & np.isfinite(Xm[:, 1])
ref = stats.spearmanr(Xm[okp, 0], Xm[okp, 1])
check.near("Spearman's rho (scipy)", x0['value'], float(ref.statistic))
check.near("Spearman's p (scipy)", x0['p'], float(ref.pvalue))
kd = call('multivariate.nonparametric', table=tid, columns=cols, measure='kendall')
ref = stats.kendalltau(Xm[okp, 0], Xm[okp, 1], variant='b', method='asymptotic')
check.near("Kendall's tau-b (scipy)", kd['pairs'][0]['value'], float(ref.statistic))
check.near("Kendall's p (scipy, asymptotic)", kd['pairs'][0]['p'], float(ref.pvalue))
# Hoeffding's D: 1 for a perfectly monotone relation, invariant to monotone
# transformations, unbiased (mean zero) under independence
xx = rng.normal(size=40)
check.near("Hoeffding's D is 1 for y = exp(x)", mv.hoeffding_d(xx, np.exp(xx))[0], 1.0, rel=1e-12)
yy = xx + rng.normal(size=40)
check.near("Hoeffding's D uses only ranks", mv.hoeffding_d(xx, yy)[0], mv.hoeffding_d(np.exp(xx), yy ** 3)[0], rel=1e-12)
sims = np.array([mv.hoeffding_d(rng.normal(size=12), rng.normal(size=12))[0] for _ in range(3000)])
check("Hoeffding's D is unbiased under independence (mean within 4 SE of 0)", abs(sims.mean()) < 4 * sims.std() / math.sqrt(len(sims)), True)
# ties: brute-force bivariate ranks
xt = np.array([1, 2, 2, 3, 4, 4, 5, 6, 6, 7], float)
yt = np.array([2, 1, 3, 3, 5, 4, 4, 6, 7, 7], float)
Qb = np.array([1 + sum((1.0 if xt[j] < xt[i] else 0.5 if xt[j] == xt[i] else 0) * (1.0 if yt[j] < yt[i] else 0.5 if yt[j] == yt[i] else 0) for j in range(10) if j != i) for i in range(10)])
Rr, Ss = stats.rankdata(xt), stats.rankdata(yt)
D1, D2, D3 = np.sum((Qb - 1) * (Qb - 2)), np.sum((Rr - 1) * (Rr - 2) * (Ss - 1) * (Ss - 2)), np.sum((Rr - 2) * (Ss - 2) * (Qb - 1))
Dref = 30 * ((8 * 7) * D1 + D2 - 2 * 8 * D3) / (10 * 9 * 8 * 7 * 6)
check.near("Hoeffding's D with ties (brute-force Q, JMP's formula)", mv.hoeffding_d(xt, yt)[0], Dref, rel=1e-12)
# the Blum-Kiefer-Rosenblatt tail against a simulation of sum chi2/(2 j^2 k^2)
jj = np.arange(1, 121)
lam = (1 / (2 * np.outer(jj * jj, jj * jj))).ravel()
rest = math.pi ** 4 / 72 - lam.sum()
Tsim = np.concatenate([(rng.standard_normal((2000, lam.size)) ** 2) @ lam for _ in range(40)]) + rest
for xq in (1.0, 2.0, 3.0):
    check.near(f'BKR P(T > {xq}) (Imhof) against 80000 simulations', mv.bkr_sf(xq), float(np.mean(Tsim > xq)), abs_=0.006)
hd = call('multivariate.nonparametric', table=tid, columns=['a', 'b'], measure='hoeffding')
check('Hoeffding p is a probability', 0 <= hd['pairs'][0]['p'] <= 1, True)

# ---- Multivariate: distance correlation (statsmodels dist_dependence_measures) ---------------------
from statsmodels.stats.dist_dependence_measures import distance_covariance_test, distance_statistics  # noqa: E402
dc = call('multivariate.distance', table=tid, columns=['a', 'b', 'c'])
pab = [x for x in dc['pairs'] if (x['by'], x['var']) == ('a', 'b')][0]
okab = np.isfinite(Xm[:, 0]) & np.isfinite(Xm[:, 1])
st_ab = distance_statistics(Xm[okab, 0], Xm[okab, 1])
check('distance: each pair on its own complete rows', pab['count'], int(okab.sum()))
check.near('dCor = statsmodels distance_statistics', pab['dcor'], float(st_ab.distance_correlation))
check.near('dCov = distance_statistics', pab['dcov'], float(st_ab.distance_covariance))
check.near('n·dCov² = its test statistic', pab['stat'], float(st_ab.test_statistic))
# by the definition: the mean product of the doubly centred distance matrices
xa_, xb_ = Xm[okab, 0], Xm[okab, 1]
A_ = np.abs(xa_[:, None] - xa_[None, :])
B_ = np.abs(xb_[:, None] - xb_[None, :])
A_ = A_ - A_.mean(0) - A_.mean(1)[:, None] + A_.mean()
B_ = B_ - B_.mean(0) - B_.mean(1)[:, None] + B_.mean()
dcov2 = (A_ * B_).mean()
check.near('dCov² = mean(A·B) of the doubly centred distances (by hand)', pab['dcov'] ** 2, float(dcov2))
check.near('dCor = dCov/√(dVar·dVar) (by hand)', pab['dcor'], float(math.sqrt(dcov2 / math.sqrt((A_ * A_).mean() * (B_ * B_).mean()))))
check('the matrix is symmetric with 1 on the diagonal', (dc['matrix'][0][1] == dc['matrix'][1][0], dc['matrix'][2][2]), (True, 1.0))
check.near('the matrix holds the pair\'s dCor', dc['matrix'][0][1], pab['dcor'])
check.near('the correlation beside it (numpy)', pab['r'], float(np.corrcoef(xa_, xb_)[0, 1]))
import warnings  # noqa: E402
np.random.seed(20260926)
with warnings.catch_warnings():
    warnings.simplefilter('ignore')   # statsmodels says it falls back to the asymptotic p-value; the report shows that
    ref_t = distance_covariance_test(xa_, xb_)
check('n ≤ 500: the permutation test (statsmodels\' rule)', pab['method'].startswith(('permutation', 'asymptotic: no permutation')), True)
check.near('the p-value = distance_covariance_test with the fixed seed', pab['p'], float(ref_t[1]))
pac = [x for x in dc['pairs'] if (x['by'], x['var']) == ('a', 'c')][0]
np.random.seed(20260926)
ref_ac = distance_covariance_test(Xm[:, 0], Xm[:, 2])
check.near('a weaker pair: the permutation p-value', pac['p'], float(ref_ac[1]))
check('its method and number of permutations (B = 200 + 5000/n)', (pac['method'], pac['B']), (f'permutation (B = {int(200 + 5000 / n)})', int(200 + 5000 / n)))
check.near('the same p-value on a second run (seeded)', call('multivariate.distance', table=tid, columns=['a', 'c'])['pairs'][0]['p'], pac['p'])
np.random.seed(5)
call('multivariate.distance', table=tid, columns=['a', 'c'])
after_ = np.random.rand()
np.random.seed(5)
check('the permutations leave numpy\'s global random state as it was', after_, np.random.rand())
dca = call('multivariate.distance', table=tid, columns=['a', 'c'], method='asym')
check.near('Asymptotic Test Only: 2(1 − Φ(√(n·dCov²/S)))', dca['pairs'][0]['p'], float(distance_covariance_test(Xm[:, 0], Xm[:, 2], method='asym')[1]))
check('its method', dca['pairs'][0]['method'], 'asymptotic')
# y = 2x + 1: dCor is 1; it uses only distances, so a shift and a scale do not change it
tl_ = table({'x': Xm[:, 4], 'y': 2 * Xm[:, 4] + 1, 'z': -3 * Xm[:, 5] + 10, 'w': Xm[:, 5]})
dl_ = call('multivariate.distance', table=tl_, columns=['x', 'y', 'z', 'w'])
check.near('a straight line: dCor 1', [x for x in dl_['pairs'] if (x['by'], x['var']) == ('x', 'y')][0]['dcor'], 1.0, rel=1e-12)
check.near('dCor(-3w + 10, w) = 1 too', [x for x in dl_['pairs'] if (x['by'], x['var']) == ('z', 'w')][0]['dcor'], 1.0, rel=1e-12)
pfall = [x for x in dl_['pairs'] if (x['by'], x['var']) == ('x', 'y')][0]
check('no permutation reaches a perfect line: statsmodels\' asymptotic p, said so', (pfall['method'].startswith('asymptotic: no permutation'), 'HypothesisTestWarning' in ' '.join(dl_.get('warnings', []))), (True, True))
# the population value for a bivariate normal (Székely, Rizzo and Bakirov 2007, Theorem 7)
rho_ = 0.6
pop = math.sqrt((rho_ * math.asin(rho_) + math.sqrt(1 - rho_ ** 2) - rho_ * math.asin(rho_ / 2) - math.sqrt(4 - rho_ ** 2) + 1) / (1 + math.pi / 3 - math.sqrt(3)))
dns = []
for s_ in range(20):   # the mean of 20 samples of 1000: its standard error is about 0.005
    zz = np.random.default_rng(100 + s_).multivariate_normal([0, 0], [[1, rho_], [rho_, 1]], size=1000)
    dn_ = call('multivariate.distance', table=table({'u': zz[:, 0], 'v': zz[:, 1]}), columns=['u', 'v'])
    dns.append(dn_['pairs'][0]['dcor'])
check.near(f'bivariate normal, ρ 0.6: the mean dCor of 20 samples is the population {pop:.4f}', float(np.mean(dns)), pop, abs_=0.02)
check('more than 500 rows: the asymptotic test', dn_['pairs'][0]['method'], 'asymptotic')
# Freq: the same as repeating the rows
tf_ = table({'a': Xm[:20, 0], 'c': Xm[:20, 2], 'k': [2.0, 1.0] * 10})
df_ = call('multivariate.distance', table=tf_, columns=['a', 'c'], freq='k')
rep_ = np.repeat(np.arange(20), [2, 1] * 10)
check.near('Freq: dCor of the repeated rows', df_['pairs'][0]['dcor'], float(distance_statistics(Xm[rep_, 0], Xm[rep_, 2]).distance_correlation))
check('Freq must be whole numbers', 'error' in call('multivariate.distance', table=table({'a': [1.0, 2, 3, 4], 'c': [2.0, 1, 4, 3], 'k': [1.5, 1, 1, 1]}), columns=['a', 'c'], freq='k'), True)
# more rows than the distance matrices take: a seeded subsample, said so
big = np.random.default_rng(13).normal(size=(2300, 2))
dbig = call('multivariate.distance', table=table({'p': big[:, 0], 'q': big[:, 0] ** 2 + big[:, 1]}), columns=['p', 'q'])
keep_ = np.sort(np.random.default_rng(20260926).choice(2300, 2000, replace=False))
check('2300 rows: 2000 used, a note', (dbig['pairs'][0]['count'], dbig['pairs'][0]['used'], any('subsample' in t for t in dbig['notes'])), (2300, 2000, True))
check.near('the subsample\'s dCor', dbig['pairs'][0]['dcor'], float(distance_statistics(big[keep_, 0], big[keep_, 0] ** 2 + big[keep_, 1]).distance_correlation))
wide = np.random.default_rng(14).normal(size=(500, 5))
dw = call('multivariate.distance', table=table({f'w{j}': wide[:, j] for j in range(5)}), columns=[f'w{j}' for j in range(5)])
check('ten pairs of 500 rows: too many permutations here, the asymptotic tests, said so', (all(x['method'] == 'asymptotic' for x in dw['pairs']), any('too long' in t for t in dw['notes'])), (True, True))
check('a constant column has no distance correlation', call('multivariate.distance', table=table({'a': [1.0, 2, 3, 4, 5], 'c': [2.0] * 5}), columns=['a', 'c'])['pairs'][0]['dcor'], None)
# the example in the (i) topic: y = x² on 41 points from −1 to 1, and a circle of 40 points
xq_ = np.linspace(-1, 1, 41)
th_ = np.linspace(0, 2 * np.pi, 40, endpoint=False)
dq = call('multivariate.distance', table=table({'x': xq_, 'y': xq_ ** 2}), columns=['x', 'y'])['pairs'][0]
dcirc = call('multivariate.distance', table=table({'x': np.cos(th_), 'y': np.sin(th_)}), columns=['x', 'y'])['pairs'][0]
import os  # noqa: E402
with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'js', 'smui-p-multivariate.js')) as fjs:
    js_src = fjs.read()
topic_parab = f'correlation 0, Spearman ρ {abs(stats.spearmanr(xq_, xq_ ** 2).statistic):.2f}, dCor {dq["dcor"]:.2f}, p {dq["p"]:.2f} (permutations)'
topic_circ = f'correlation 0, Spearman ρ {abs(stats.spearmanr(np.cos(th_), np.sin(th_)).statistic):.2f}, dCor {dcirc["dcor"]:.2f}, p {dcirc["p"]:.2f}'
check('the (i) topic\'s parabola is computed so', topic_parab in js_src, True)
check('the (i) topic\'s circle is computed so', topic_circ in js_src, True)
check('the parabola: correlation 0, dCor about 0.49', (abs(dq['r']) < 1e-12, round(dq['dcor'], 2)), (True, 0.49))

# ---- Multivariate: outlier distances and item reliability -----------------------------------------
o = call('multivariate.outliers', table=tid, columns=cols)
S = np.cov(Xc, rowvar=False)
e = Xc - Xc.mean(0)
M2 = np.einsum('ij,jk,ik->i', e, np.linalg.inv(S), e)
check.near('Mahalanobis distance', o['mahal'][5], float(math.sqrt(M2[5])))
check.near('T² is the squared Mahalanobis distance', o['t2'][5], float(M2[5]))
i = 11
Xo = np.delete(Xc, i, axis=0)
eo = Xc[i] - Xo.mean(0)
Jb = float(math.sqrt(eo @ np.linalg.inv(np.cov(Xo, rowvar=False)) @ eo))
check.near('jackknife distance = distance to the other rows (brute force)', o['jack'][i], Jb)
check('distances carry the page row numbers', o['rows'][:9], [0, 1, 2, 3, 4, 5, 6, 8, 9])
p6 = 6
check.near('T² UCL (Mason and Young)', o['ucl_t2'], (nc - 1) ** 2 / nc * float(stats.beta.ppf(0.95, p6 / 2, (nc - p6 - 1) / 2)))
rel = call('multivariate.reliability', table=tid, columns=['a', 'b', 'e'])
S3 = np.cov(Xc[:, [0, 1, 4]], rowvar=False)
k3 = 3
check.near("Cronbach's alpha = k/(k-1)(1 - sum var / var of the sum)", rel['alpha'], k3 / (k3 - 1) * (1 - np.trace(S3) / S3.sum()))
R3 = np.corrcoef(Xc[:, [0, 1, 4]], rowvar=False)
rbar = (R3.sum() - 3) / 6
check.near("standardized alpha = k r/(1 + (k-1) r)", rel['std_alpha'], 3 * rbar / (1 + 2 * rbar))
S2 = np.cov(Xc[:, [1, 4]], rowvar=False)
check.near('alpha with a left out', rel['items'][0]['alpha'], 2 * (1 - np.trace(S2) / S2.sum()))

# ---- Principal Components ------------------------------------------------------------------------------
from statsmodels.multivariate.pca import PCA  # noqa: E402
pc = call('pca.fit', table=tid, columns=cols)
ev = np.sort(np.linalg.eigvalsh(R))[::-1]
check.near('eigenvalues of the correlation matrix (numpy)', pc['eigenvalues'][0], float(ev[0]))
check.near('eigenvalues sum to p', sum(pc['eigenvalues']), 6.0)
smp = PCA(Xc, standardize=True, normalize=False)
check.near('eigenvalues = statsmodels PCA eigenvals / n', pc['eigenvalues'][2], float(np.asarray(smp.eigenvals)[2] / nc))
sc = np.array(pc['scores'])
check.near('score variance = eigenvalue', float(np.var(sc[:, 0], ddof=1)), pc['eigenvalues'][0], rel=1e-9)
load = np.array(pc['loadings'])
check.near('loading = correlation of variable and component', load[3, 1], float(np.corrcoef(Xc[:, 3], sc[:, 1])[0, 1]), rel=1e-9)
V = np.array(pc['eigenvectors'])
check.near('eigenvectors have norm one', float(np.linalg.norm(V[:, 2])), 1.0)
Z = (Xc - Xc.mean(0)) / Xc.std(0, ddof=1)
check.near('scores are the standardized rows times the eigenvectors', sc[4, 2], float(Z[4] @ V[:, 2]))
b0 = pc['bartlett'][0]
lam6 = np.array(pc['eigenvalues'])
check.near("Bartlett's test of equal eigenvalues (Jackson 2003)", b0['chi2'], (nc - 1) * (6 * math.log(lam6.mean()) - np.log(lam6).sum()))
check("its degrees of freedom", [x['df'] for x in pc['bartlett']], [20.0, 14.0, 9.0, 5.0, 2.0, None])
pcv = call('pca.fit', table=tid, columns=cols, on='covariances')
check.near('on covariances: eigenvalues of the covariance matrix', pcv['eigenvalues'][0], float(np.sort(np.linalg.eigvalsh(S))[::-1][0]))
lv = np.array(pcv['loadings'])
check.near('on covariances: loading = correlation of variable and component', lv[2, 0], float(np.corrcoef(Xc[:, 2], np.array(pcv['scores'])[:, 0])[0, 1]), rel=1e-9)
pcu = call('pca.fit', table=tid, columns=cols, on='unscaled')
check.near("unscaled: eigenvalues of X'X / n", pcu['eigenvalues'][0], float(np.sort(np.linalg.eigvalsh(Xc.T @ Xc / nc))[::-1][0]))
# a known 2 x 2 correlation matrix: eigenvalues 1 + r and 1 - r
t2 = table({'u': [1.0, 2.0, 3.0, 4.0, 5.0], 'v': [2.0, 1.0, 4.0, 3.0, 5.0]})
p2 = call('pca.fit', table=t2, columns=['u', 'v'])
check.near('2 x 2: eigenvalues 1 + r, 1 - r (r = 0.8)', p2['eigenvalues'][0], 1.8)
# frequencies are replicated rows
pf = call('pca.fit', table=tid, columns=cols, freq='w')
Xe = np.repeat(Xc, wt[ok].astype(int), axis=0)
check.near('Freq = replicated rows', pf['eigenvalues'][1], float(np.sort(np.linalg.eigvalsh(np.corrcoef(Xe, rowvar=False)))[::-1][1]))
# rotation: varimax without Kaiser normalization is statsmodels' own
from statsmodels.multivariate.factor_rotation import rotate_factors  # noqa: E402
prv = call('pca.fit', table=tid, columns=cols, rotation='varimax', n_rotate=2, kaiser=False)
Lref, _ = rotate_factors(load[:, :2], 'varimax')
Lgot = np.array(prv['rotation']['loadings'])
check('varimax (no normalization) = statsmodels rotate_factors, up to order and sign',
      np.allclose(np.sort(np.abs(Lgot).ravel()), np.sort(np.abs(Lref).ravel()), atol=1e-6), True)
check.near('an orthogonal rotation keeps the communalities', float((Lgot ** 2).sum()), float((load[:, :2] ** 2).sum()))

# ---- Factor Analysis --------------------------------------------------------------------------------------
from statsmodels.multivariate.factor import Factor  # noqa: E402
fa = call('factor.fit', table=tid, columns=cols, n_factors=2, method='ml', rotation='none')
ref = Factor(Xc, n_factor=2, method='ml').fit()
A = np.array(fa['unrotated'])
check('ML loadings = statsmodels Factor (up to sign)', np.allclose(np.abs(A), np.abs(ref.loadings_no_rot), atol=1e-5), True)
check.near('ML uniquenesses = statsmodels', fa['uniqueness'][0], float(ref.uniqueness[0]), rel=1e-5)
check('default number of factors: eigenvalues >= 1', fa['n_default'], int(np.sum(ev >= 1)))
Sig = A @ A.T + np.diag(fa['uniqueness'])
Fml = math.log(np.linalg.det(Sig)) - math.log(np.linalg.det(R)) + np.trace(R @ np.linalg.inv(Sig)) - 6
check.near('ML test of 2 factors: Bartlett-corrected chi-square', fa['ml_test']['chi2'], (nc - 1 - 17 / 6 - 4 / 3) * Fml, rel=1e-6)
check('its df', fa['ml_test']['df'], 4.0)
check.near("Bartlett's test of sphericity", fa['sphericity']['chi2'], -(nc - 1 - 17 / 6) * math.log(np.linalg.det(R)))
Ri = np.linalg.inv(R)
Aim = -Ri / np.sqrt(np.outer(np.diag(Ri), np.diag(Ri)))
off = ~np.eye(6, dtype=bool)
check.near('Kaiser-Meyer-Olkin MSA', fa['kmo']['overall'], float((R[off] ** 2).sum() / ((R[off] ** 2).sum() + (Aim[off] ** 2).sum())))
fap = call('factor.fit', table=tid, columns=cols, n_factors=2, method='pa', rotation='none')
refp = Factor(Xc, n_factor=2, method='pa').fit()
check('principal axis = statsmodels (up to sign)', np.allclose(np.abs(np.array(fap['unrotated'])), np.abs(refp.loadings_no_rot), atol=1e-6), True)
fav = call('factor.fit', table=tid, columns=cols, n_factors=2, method='ml', rotation='varimax', kaiser=False)
Lv, _ = rotate_factors(ref.loadings_no_rot, 'varimax')
check('ML + varimax = statsmodels rotate_factors (up to order and sign)', np.allclose(np.sort(np.abs(np.array(fav['rotated'])).ravel()), np.sort(np.abs(Lv).ravel()), atol=1e-4), True)
fao = call('factor.fit', table=tid, columns=cols, n_factors=2, method='ml', rotation='promax')
Lp, Tp, Php = np.array(fao['rotated']), np.array(fao['rotation_matrix']), np.array(fao['phi'])
check('promax: the factor correlations have a unit diagonal', np.allclose(np.diag(Php), 1, atol=1e-8), True)
check('promax: L = A (T\')^-1', np.allclose(Lp, A @ np.linalg.inv(Tp.T), atol=1e-6), True)
Vv, _ = rotate_factors(A / np.sqrt((A ** 2).sum(1))[:, None], 'varimax')
Ht = Vv * np.abs(Vv) ** 2
Ut = np.linalg.lstsq(A / np.sqrt((A ** 2).sum(1))[:, None], Ht, rcond=None)[0]
Ut = Ut @ np.diag(np.sqrt(np.diag(np.linalg.inv(Ut.T @ Ut))))
check('promax = Hendrickson-White with power 3 and Kaiser normalization (as SAS)', np.allclose(np.sort(np.abs(Lp).ravel()), np.sort(np.abs(A @ Ut).ravel()), atol=1e-8), True)
Zs = (Xc - Xc.mean(0)) / Xc.std(0, ddof=1)
refv = Factor(Xc, n_factor=2, method='ml').fit()
refv.rotate('varimax')
fsv = call('factor.fit', table=tid, columns=cols, n_factors=2, method='ml', rotation='varimax', kaiser=False)
check('factor scores (regression) = statsmodels factor_scoring, up to order and sign',
      np.allclose(np.sort(np.abs(np.array(fsv['scores'])[:5]).ravel()), np.sort(np.abs(refv.factor_scoring(method='regression')[:5]).ravel()), atol=1e-4), True)

# ---- Discriminant -----------------------------------------------------------------------------------------
from statsmodels.multivariate.cancorr import CanCorr  # noqa: E402
tr = np.random.default_rng(7)
mu = np.array([[0, 0, 0], [2.5, 0.5, 0], [0.5, 2.5, 1]])
yl = np.repeat(np.arange(3), 40)
Yd = mu[yl] + tr.normal(size=(120, 3)) @ np.array([[1, 0.3, 0], [0, 1, 0.2], [0, 0, 1]])
td = table({'y1': Yd[:, 0], 'y2': Yd[:, 1], 'y3': Yd[:, 2], 'grp': [['k1', 'k2', 'k3'][i] for i in yl]})
dr = call('discriminant.fit', table=td, y=['y1', 'y2', 'y3'], x='grp')
means = np.array([Yd[yl == t].mean(0) for t in range(3)])
Sp = sum((Yd[yl == t] - means[t]).T @ (Yd[yl == t] - means[t]) for t in range(3)) / (120 - 3)
Dd = np.array([np.einsum('ij,jk,ik->i', Yd - m, np.linalg.inv(Sp), Yd - m) for m in means]).T
Pd = np.exp(-Dd / 2)
Pd /= Pd.sum(1, keepdims=True)
check.near('linear: posterior probability (direct)', dr['prob'][17][1], float(Pd[17, 1]))
check.near('linear: SqDist = d² - 2 log q', dr['sqdist'][3][2], float(Dd[3, 2] - 2 * math.log(1 / 3)))
check('linear: predictions', dr['pred'], Pd.argmax(1).tolist())
cc = CanCorr(Yd, pd.get_dummies(yl, drop_first=True).to_numpy(float))
check.near('canonical correlations = statsmodels CanCorr', dr['canonical']['cancorr'][0], float(cc.cancorr[0]), rel=1e-7)
lam_ = np.array(dr['canonical']['eigen'])
wil = [x for x in dr['tests'] if x['test'].startswith('Wilks')][0]
check.near("Wilks' lambda (statsmodels MANOVA) = prod 1/(1 + eigenvalue)", wil['value'], float(np.prod(1 / (1 + lam_))))
check.near('likelihood ratio of the first root = Wilks', dr['canonical']['lr'][0], wil['value'])
csc = np.array(dr['canonical']['scores'])
check.near('canonical scores have pooled within variance 1', float(sum(((csc[yl == t, 0] - csc[yl == t, 0].mean()) ** 2).sum() for t in range(3)) / 117), 1.0, rel=1e-8)
check('confusion matrix totals', float(np.sum(dr['confusion'])), 120.0)
nm = int(np.sum(Pd.argmax(1) != yl))
check('number misclassified', dr['summary']['n_mis'], float(nm))
llf = np.sum(np.log(Pd[np.arange(120), yl]))
check.near('entropy RSquare = 1 - loglik / loglik of the shares', dr['summary']['entropy_r2'], float(1 - llf / (120 * math.log(1 / 3))))
dq = call('discriminant.fit', table=td, y=['y1', 'y2', 'y3'], x='grp', method='quadratic')
dens = np.column_stack([stats.multivariate_normal(means[t], np.cov(Yd[yl == t], rowvar=False)).pdf(Yd) for t in range(3)])
Pq = dens / dens.sum(1, keepdims=True)
check.near('quadratic: posterior = normal densities with each group\'s covariance (scipy)', dq['prob'][50][2], float(Pq[50, 2]), rel=1e-7)
dz = call('discriminant.fit', table=td, y=['y1', 'y2', 'y3'], x='grp', method='regularized', lam=1.0, gam=0.0)
check('regularized with lambda 1, gamma 0 is linear', np.allclose(np.array(dz['prob']), Pd, atol=1e-10), True)
st = call('discriminant.stepwise', table=td, y=['y1', 'y2', 'y3'], x='grp', entered=[])
ow = sm.OLS(Yd[:, 0], sm.add_constant(pd.get_dummies(yl, drop_first=True).to_numpy(float))).fit()
check.near('stepwise: F of a covariate with nothing entered = oneway F', st['columns'][0]['F'], float(ow.fvalue))

# ---- Hierarchical Cluster ------------------------------------------------------------------------------------
tiny = np.array([[0, 0], [0, 1], [5, 5], [5, 6], [6, 5], [10, 0.5]], float)
tt = table({'p': tiny[:, 0], 'q': tiny[:, 1]})
for method in ('average', 'single', 'complete', 'centroid', 'ward'):
    h = call('hcluster.fit', table=tt, columns=['p', 'q'], method=method, standardize='none')
    # brute force: merge the pair of clusters with the smallest JMP distance
    cl = [[i] for i in range(6)]
    got, want = [], []
    for s in range(5):
        best = None
        for a_, b_ in itertools.combinations(range(len(cl)), 2):
            A_, B_ = tiny[cl[a_]], tiny[cl[b_]]
            d2 = ((A_[:, None, :] - B_[None, :, :]) ** 2).sum(2)
            dist = {'average': d2.mean(), 'single': d2.min(), 'complete': d2.max(),
                    'centroid': ((A_.mean(0) - B_.mean(0)) ** 2).sum(),
                    'ward': ((A_.mean(0) - B_.mean(0)) ** 2).sum() / (1 / len(A_) + 1 / len(B_))}[method]
            if best is None or dist < best[0] - 1e-12:
                best = (dist, a_, b_)
        want.append(best[0])
        cl[best[1]] = cl[best[1]] + cl[best[2]]
        del cl[best[2]]
    check(f'{method}: joining distances are JMP\'s (brute force)', np.allclose(h['heights'], want), True)
hw = call('hcluster.fit', table=tid, columns=cols, method='ward')
Zw = np.column_stack([np.array(hw['merges'], float), hw['heights'], hw['sizes']])
Zs_ = Zw.copy()
Zs_[:, 2] = np.sqrt(2 * Zs_[:, 2])
lab = fcluster(Zs_, 4, 'maxclust')
Xs = (Xc - Xc.mean(0)) / Xc.std(0, ddof=1)
W4 = sum(((Xs[lab == c] - Xs[lab == c].mean(0)) ** 2).sum() for c in np.unique(lab))
check.near('R-square of the 4-cluster partition', hw['criterion'][3]['r2'], float(1 - W4 / ((Xs - Xs.mean(0)) ** 2).sum()))
# the cubic clustering criterion: SAS's Fisher iris example (PROC CLUSTER,
# METHOD=TWOSTAGE) prints the eigenvalues of the covariance matrix, and per
# number of clusters R-square, the approximate expected R-square and CCC
eig_iris = [422.824171, 24.267075, 7.820950, 2.383509]
for q, r2, er2, cc_ in [(2, .773, .697, 3.83), (3, .874, .827, 3.49), (4, .879, .872, .54), (8, .896, .930, -5.2), (15, .917, .958, -11)]:
    e_, c_ = mv.ccc(eig_iris, 150, q, r2)
    check.near(f'expected R-square, SAS iris example, {q} clusters', e_, er2, abs_=0.0006)
    check.near(f'CCC, SAS iris example, {q} clusters (R-square rounded in the source)', c_, cc_, abs_=0.12 if abs(cc_) < 10 else 0.5)
# FASTCLUS (10 clusters) uses the variances: R2 0.95971, ERSQ 0.82928, CCC 27.077
e_, c_ = mv.ccc([68.5693512, 18.9979418, 311.6277852, 58.1006264], 150, 10, 0.95971)
check.near('expected R-square, SAS FASTCLUS iris example', e_, 0.82928, abs_=5e-6)
check.near('CCC, SAS FASTCLUS iris example', c_, 27.077, abs_=0.005)

# ---- K Means ----------------------------------------------------------------------------------------------------
kr = np.random.default_rng(11)
cent = np.array([[0, 0], [6, 0], [0, 6]], float)
lk = np.repeat(np.arange(3), 50)
Xk = cent[lk] + kr.normal(size=(150, 2))
tk = table({'k1': Xk[:, 0], 'k2': Xk[:, 1]})
km = call('kmeans.fit', table=tk, columns=['k1', 'k2'], k_min=2, k_max=5, standardize=False)
f3 = [f for f in km['fits'] if f['k'] == 3][0]
tabk = pd.crosstab(lk, np.array(f3['labels']))
check('k = 3 recovers the three simulated clusters', int((tabk.to_numpy() > 0).sum()), 3)
check('the best CCC is at 3 clusters', km['best'], 3)
C0 = np.array(f3['centers_scaled'])
cen2, lab2 = kmeans2(Xk, C0, minit='matrix', iter=50)
check('the fit is a fixed point of scipy kmeans2 (Lloyd)', np.allclose(cen2, C0, atol=1e-9), True)
W3 = sum(((Xk[np.array(f3['labels']) == j] - Xk[np.array(f3['labels']) == j].mean(0)) ** 2).sum() for j in range(3))
check.near('within SS', f3['wss'], float(W3))
check.near('pseudo F (Calinski-Harabasz)', f3['pseudo_f'], (f3['r2'] / 2) / ((1 - f3['r2']) / 147))
check('clusters numbered by size', f3['counts'] == sorted(f3['counts'], reverse=True), True)
km2 = call('kmeans.fit', table=tk, columns=['k1', 'k2'], k_min=2, k_max=5, standardize=False)
check('seeded: the same result twice', km2['fits'][1]['labels'] == f3['labels'], True)

# ---- Response Screening -----------------------------------------------------------------------------------------
rs = call('respscreen.fit', table=tid, y=['a', 'b', 'g'], x=['c', 'g', 'd'])
res = {(x['y'], x['x']): x for x in rs['results']}
d_ = pd.DataFrame(Xm, columns=cols).assign(g=grp)
cc_rows = d_[['a', 'g']].dropna()
fit = sm.OLS.from_formula('a ~ C(g)', cc_rows).fit()
check.near('continuous Y by categorical X: ANOVA F p (statsmodels OLS)', res[('a', 'g')]['p'], float(fit.f_pvalue))
check.near('RSquare', res[('a', 'g')]['r2'], float(fit.rsquared))
fr = sm.OLS.from_formula('b ~ c', d_[['b', 'c']].dropna()).fit()
check.near('continuous Y by continuous X: regression p (statsmodels OLS)', res[('b', 'c')]['p'], float(fr.f_pvalue))
lg = sm.MNLogit(pd.Categorical(grp).codes, sm.add_constant(Xm[:, 2])).fit(disp=0)
check.near('categorical Y by continuous X: logistic LR p (statsmodels MNLogit)', res[('g', 'c')]['p'], float(lg.llr_pvalue), rel=1e-6)
allp = np.array([x['p'] for x in rs['results']])
from statsmodels.stats.multitest import multipletests  # noqa: E402
check('FDR p-values = multipletests fdr_bh', np.allclose([x['fdr_p'] for x in rs['results']], multipletests(allp, method='fdr_bh')[1]), True)
check.near('LogWorth = -log10 p', res[('a', 'g')]['logworth'], -math.log10(res[('a', 'g')]['p']))
check('no test of a column against itself', ('g', 'g') in res, False)
iq = np.subtract(*np.quantile(cc_rows['a'], [0.75, 0.25]))
check.near('effect size = sqrt(model mean square) / (IQR/1.349)', res[('a', 'g')]['effect'], math.sqrt(fit.ess / 2) / (iq / 1.3489795))
bin_y = (Xm[:, 0] > 0).astype(float)
tb = table({'yb': np.where(bin_y > 0, 'yes', 'no').tolist(), 'xc': Xm[:, 2]})
rb_ = call('respscreen.fit', table=tb, y=['yb'], x=['xc'])
lb = sm.Logit(bin_y, sm.add_constant(Xm[:, 2])).fit(disp=0)
check.near('binary Y: logistic LR p (statsmodels Logit)', rb_['results'][0]['p'], float(lb.llr_pvalue), rel=1e-7)

# ---- Explore Outliers ---------------------------------------------------------------------------------------------
xo = rng.normal(10, 1, 200)
xo[[5, 60]] = [30, -12]
xo[100] = 9999
to = table({'m': xo, 'n2': rng.normal(size=200)})
qo = call('outliers.quantile', table=to, columns=['m', 'n2'])
lo_, hi_ = np.quantile(xo, [0.1, 0.9], method='weibull')
m0 = qo['columns'][0]
check.near('quantile range: high threshold', m0['high_t'], float(hi_ + 3 * (hi_ - lo_)))
check('quantile range: the planted outliers', sorted(m0['rows']), [5, 60, 100])
check('nines: 9999 as a probable missing value code', [(x['column'], x['value'], x['count']) for x in qo['nines']], [('m', 9999.0, 1)])
from statsmodels.robust.scale import Huber  # noqa: E402
ro = call('outliers.robust', table=to, columns=['m'])
loc_, sc_ = Huber(maxiter=100)(xo)
check.near('robust fit: Huber centre (statsmodels)', ro['columns'][0]['center'], float(loc_), rel=1e-9)
check.near('robust fit: Huber spread (statsmodels)', ro['columns'][0]['spread'], float(sc_), rel=1e-9)
check('robust fit: the planted outliers', sorted(ro['columns'][0]['rows']), [5, 60, 100])
# FAST-MCD against the exact MCD by enumeration (n = 12, h = 7)
xs = np.random.default_rng(3).normal(size=(12, 2))
xs[0] = [6, -6]
best = min(itertools.combinations(range(12), 7), key=lambda s: np.linalg.det(np.cov(xs[list(s)], rowvar=False)))
got = mv.mcd(xs)
check('FAST-MCD finds the exact MCD subset (all 792 subsets enumerated)', got['subset'].tolist(), sorted(best))
Xo2 = np.random.default_rng(4).multivariate_normal([0, 0, 0], [[1, .8, .5], [.8, 1, .4], [.5, .4, 1]], 300)
Xo2[:15] = Xo2[:15] + np.array([0, 0, 0]) + np.array([3, -3, 2])    # 15 outliers against the correlation
tm = table({'u1': Xo2[:, 0], 'u2': Xo2[:, 1], 'u3': Xo2[:, 2]})
mo = call('outliers.multivariate', table=tm, columns=['u1', 'u2', 'u3'])
flag = np.array(mo['robust']) > mo['limit']
check('robust distances flag the 15 planted outliers', bool(flag[:15].all()), True)
check('and about 5% of the others (at most 10%)', int(flag[15:].sum()) <= 28, True)
check.near('the limit is sqrt of the chi-square quantile', mo['limit'], math.sqrt(stats.chi2.ppf(0.95, 3)))
ko = call('outliers.knn', table=tm, columns=['u1', 'u2', 'u3'], k=8)
Zk = mv._robust_scale_cols(Xo2)
dk = np.sqrt(((Zk[:, None, :] - Zk[None, :, :]) ** 2).sum(2))
dk.sort(1)
check.near('kNN: distance to the 3rd neighbour (brute force)', ko['dist']['3'][20], float(dk[20, 3]))
check('kNN: k = 1, 2, 3, 5, 8 (Fibonacci)', ko['ks'], [1, 2, 3, 5, 8])

# ---- Multiple Correspondence Analysis --------------------------------------------------------------------------------------
cr = np.random.default_rng(12)
nm_ = 300
va = cr.choice(['x', 'y', 'z'], nm_)
vb = np.where(cr.random(nm_) < 0.6, np.where(va == 'x', 'p', np.where(va == 'y', 'q', 'r')), cr.choice(['p', 'q', 'r', 's'], nm_))
vc = cr.choice(['u', 'v'], nm_)
tmca = table({'va': va.tolist(), 'vb': vb.tolist(), 'vc': vc.tolist()})
mc = call('mca.fit', table=tmca, columns=['va', 'vb', 'vc'])
check.near('MCA: total inertia = (J - Q)/Q', mc['total_inertia'], (mc['J'] - 3) / 3)
check('MCA: J - Q nontrivial dimensions', mc['K'], mc['J'] - 3)
lv = mc['levels']
for var in ('va', 'vb', 'vc'):
    L_ = [x for x in lv if x['column'] == var]
    check.near(f'MCA: the mass-weighted mean of the {var} level coordinates is 0', float(sum(x['mass'] * x['coords'][0] for x in L_)), 0.0, abs_=1e-12)
burt = np.array(mc['burt'])
check('MCA: the Burt table diagonal holds the level counts', [int(burt[i, i]) for i in range(3)], [int((va == v).sum()) for v in ('x', 'y', 'z')])
# two variables: the MCA inertias are ((1 + s)/2)^2 of the simple CA singular values s
m2 = call('mca.fit', table=tmca, columns=['va', 'vb'])
ct = pd.crosstab(va, vb).to_numpy(float)
Pc = ct / ct.sum()
rr, cc = Pc.sum(1), Pc.sum(0)
s_ca = np.linalg.svd((Pc - np.outer(rr, cc)) / np.sqrt(np.outer(rr, cc)), compute_uv=False)[:2]
check('MCA of two variables: inertias (1 + s)/2 of the simple correspondence analysis singular values s', np.allclose(m2['inertia'][:2], (1 + s_ca) / 2, atol=1e-10), True)
lz = np.array(mc['inertia'])
bz = np.where(lz > 1 / 3, (3 / 2) ** 2 * (lz - 1 / 3) ** 2, 0)
check('MCA: Benzécri-adjusted inertias (Greenacre 1984)', np.allclose(mc['adjusted']['greenacre'], bz), True)
check.near("MCA: Greenacre's adjusted total", mc['adjusted']['greenacre_total'], 1.5 * (float((lz ** 2).sum()) - (mc['J'] - 3) / 9))
Bm = np.array(mc['burt']); Bp = Bm / Bm.sum(); dB = Bp.sum(0)
sB = np.linalg.svd((Bp - np.outer(dB, dB)) / np.sqrt(np.outer(dB, dB)), compute_uv=False)[:mc['K']]
check("MCA: JMP's Inertia = the singular values of the Burt table's analysis", np.allclose(sB, lz, atol=1e-10), True)
tf = table({'va': ['x', 'x', 'y', 'z'], 'vb': ['p', 'q', 'q', 'p'], 'fr': [2, 1, 3, 1]})
tr_ = table({'va': ['x', 'x', 'x', 'y', 'y', 'y', 'z'], 'vb': ['p', 'p', 'q', 'q', 'q', 'q', 'p']})
check('MCA: Freq = replicated rows', np.allclose(call('mca.fit', table=tf, columns=['va', 'vb'], freq='fr')['inertia'], call('mca.fit', table=tr_, columns=['va', 'vb'])['inertia']), True)

# ---- Multidimensional Scaling --------------------------------------------------------------------------------------------------
md = call('mds.fit', table=tid, columns=cols)
check.near('MDS: the eigenvalues are (n - 1) times those of the correlation matrix', md['eigenvalues'][0], float((nc - 1) * ev[0]), rel=1e-8)
pcs = np.array(pc['scores'])
check('MDS of standardized columns = the principal component scores (up to sign)', np.allclose(np.abs(np.array(md['coords'])[:, :2]), np.abs(pcs[:, :2]), atol=1e-8), True)
Xs2 = (Xc - Xc.mean(0)) / Xc.std(0, ddof=1)
from scipy.spatial.distance import pdist  # noqa: E402
d_ = pdist(Xs2)
dh_ = pdist(np.array(md['coords'])[:, :2])
check.near("MDS: Kruskal's stress of the two-dimensional map", md['stress'], float(np.sqrt(((d_ - dh_) ** 2).sum() / (d_ ** 2).sum())))
pts = np.random.default_rng(5).normal(size=(12, 2))
Dm = np.sqrt(((pts[:, None, :] - pts[None, :, :]) ** 2).sum(2))
tdm = table({f'd{j}': Dm[:, j] for j in range(12)})
mm_ = call('mds.fit', table=tdm, columns=[f'd{j}' for j in range(12)], matrix=True)
check.near('MDS of a Euclidean distance matrix in the plane: stress 0', mm_['stress'], 0.0, abs_=1e-9)
check('MDS: the map reproduces the distances', np.allclose(pdist(np.array(mm_['coords'])[:, :2]), pdist(pts), atol=1e-9), True)

# ---- the Python code shown under each result runs on a CSV export of its table ------------------------------------------
import contextlib  # noqa: E402
import io  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402

frames = {
    'main': pd.DataFrame({**{c: Xm[:, j] for j, c in enumerate(cols)}, 'w': wt, 'g': grp}),
    'disc': pd.DataFrame({'y1': Yd[:, 0], 'y2': Yd[:, 1], 'y3': Yd[:, 2], 'grp': [['k1', 'k2', 'k3'][i] for i in yl]}),
    'km': pd.DataFrame({'k1': Xk[:, 0], 'k2': Xk[:, 1]}),
    'mro': pd.DataFrame({'u1': Xo2[:, 0], 'u2': Xo2[:, 1], 'u3': Xo2[:, 2]}),
    'mca': pd.DataFrame({'va': va, 'vb': vb, 'vc': vc}),
    'dm': pd.DataFrame({f'd{j}': Dm[:, j] for j in range(12)}),
}
snippets = [
    ('main', 'multivariate.fit', r), ('main', 'multivariate.fit pairwise', rp), ('main', 'multivariate.fit freq', rw),
    ('main', 'nonparametric spearman', sp), ('main', 'nonparametric kendall', kd), ('main', 'nonparametric hoeffding', hd),
    ('main', 'multivariate.outliers', o), ('main', 'multivariate.reliability', rel),
    ('main', 'pca.fit', pc), ('main', 'pca.fit covariances', pcv), ('main', 'pca.fit unscaled', pcu),
    ('main', 'factor.eigen', call('factor.eigen', table=tid, columns=cols)), ('main', 'factor.fit ml', fa), ('main', 'factor.fit pa', fap), ('main', 'factor.fit varimax', fav),
    ('disc', 'discriminant.fit', dr), ('main', 'hcluster.fit', hw), ('km', 'kmeans.fit', km), ('main', 'respscreen.fit', rs),
    ('mro', 'outliers.multivariate', mo), ('mro', 'outliers.knn', ko), ('mca', 'mca.fit', mc), ('main', 'mds.fit', md), ('dm', 'mds.fit matrix', mm_),
    ('main', 'multivariate.distance', dc), ('main', 'multivariate.distance freq', call('multivariate.distance', table=tid, columns=['a', 'c'], freq='w')),
]
with tempfile.TemporaryDirectory() as tmp:
    here = os.getcwd()
    for key, label, res_ in snippets:
        frames[key].to_csv(os.path.join(tmp, 'data.csv'), index=False)
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                import warnings as _w
                with _w.catch_warnings():
                    _w.simplefilter('ignore')
                    exec(compile(res_['code'], label, 'exec'), {})
            ok_ = True
        except Exception as ex:  # report which snippet failed
            ok_ = f'{type(ex).__name__}: {ex}'
        finally:
            os.chdir(here)
        check(f'the code of {label} runs on the CSV', ok_, True)
    frames['out'] = pd.DataFrame({'m': xo})
    for label, res_ in (('outliers.quantile', call('outliers.quantile', table=to, columns=['m'])), ('outliers.robust huber', call('outliers.robust', table=to, columns=['m'])),
                        ('outliers.robust cauchy', call('outliers.robust', table=to, columns=['m'], method='cauchy')), ('outliers.robust quartile', call('outliers.robust', table=to, columns=['m'], method='quartile'))):
        frames['out'].to_csv(os.path.join(tmp, 'data.csv'), index=False)
        os.chdir(tmp)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(compile(res_['code'], label, 'exec'), {})
            ok_ = True
        except Exception as ex:
            ok_ = f'{type(ex).__name__}: {ex}'
        finally:
            os.chdir(here)
        check(f'the code of {label} runs on the CSV', ok_, True)

# the code of the distance correlations gives the report's numbers
for label_, res_ in (('distance', dc), ('distance freq', call('multivariate.distance', table=tid, columns=['a', 'c'], freq='w'))):
    with tempfile.TemporaryDirectory() as tmp:
        frames['main'].to_csv(os.path.join(tmp, 'data.csv'), index=False)
        here = os.getcwd()
        os.chdir(tmp)
        ns_ = {}
        try:
            with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
                warnings.simplefilter('ignore')
                exec(compile(res_['code'], label_, 'exec'), ns_)
        finally:
            os.chdir(here)
    first_ = res_['pairs'][0]
    check.near(f'the code of {label_}: its x, y give the dCor', float(distance_statistics(ns_['x'], ns_['y']).distance_correlation), first_['dcor'])
    np.random.seed(20260926)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        pv_ = distance_covariance_test(ns_['x'], ns_['y'], method='asym' if res_['asym'] else 'auto')[1]
    check.near(f'the code of {label_}: and the p-value', float(pv_), first_['p'])

# ---- rows = None means every row; By groups use row lists -------------------------------------------------------------
check('rows=None gives every row', call('multivariate.outliers', table=tid, columns=cols, rows=None)['rows'][-1], n - 1)
sub = call('multivariate.fit', table=tid, columns=cols, rows=list(range(0, n, 2)))
check('a row subset', sub['n'], float(len([i for i in range(0, n, 2) if ok[i]])))
sys.exit(check.done())
