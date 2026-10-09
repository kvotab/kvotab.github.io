#!/usr/bin/env python3
"""Analyze > Multivariate Methods, Clustering and Screening: the backend
(resources/py/smui/multivariate.py), checked against statsmodels and scipy
called directly, against brute-force computations of the definitions JMP
documents, and against published values (the cubic clustering criterion of
the Fisher iris example in the SAS PROC CLUSTER and FASTCLUS documentation;
the distance correlation of a bivariate normal, Székely, Rizzo and Bakirov
2007, Theorem 7). The data are simulated here from fixed seeds.

Item Reliability's intraclass correlations are checked against Shrout and
Fleiss's (1979) published coefficients (from their mean squares), McGraw and
Wong's (1996) formulas, least squares on the stacked ratings, the pivots of the
exact intervals and pingouin's intraclass_corr; Kendall's W against scipy's
friedmanchisquare, its definition with pandas' ranks and pingouin's friedman.
pingouin (GPL) is only called as a reference, its example read at run time.

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

# ---- Test Many Responses -----------------------------------------------------------------------------------------
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

# ======================================================================================================================
# Item Reliability: intraclass correlations and Kendall's W
# ======================================================================================================================
# Checked against the published mean squares and coefficients of Shrout and
# Fleiss's (1979) example (Table 2: results, not their data), McGraw and Wong's
# (1996) formulas written out here, least squares on the stacked ratings,
# scipy's friedmanchisquare, pandas' rank correlations, and pingouin's
# intraclass_corr and friedman (GPL: a reference only; its wine-rating example
# read at run time) when it is installed.
import statsmodels.formula.api as smf  # noqa: E402
try:
    import pingouin as pg  # noqa: E402
except ImportError:
    pg = None
    print('pingouin is not installed: its reference checks are skipped')

sf = mv.icc_forms(11.24, 32.49, 1.02, 6.26, 6, 4)
check("Shrout and Fleiss's example (their mean squares, 6 targets, 4 judges): the six published coefficients",
      {k_: round(v_[0], 2) for k_, v_ in sf.items()}, {'ICC(1,1)': 0.17, 'ICC(1,k)': 0.44, 'ICC(C,1)': 0.71, 'ICC(C,k)': 0.91, 'ICC(A,1)': 0.29, 'ICC(A,k)': 0.62})

rng_icc = np.random.default_rng(1979)
nt, kr = 30, 5
Xr = rng_icc.normal(size=(nt, 1)) * 1.2 + rng_icc.normal(size=(nt, kr)) + np.array([0, 0.3, -0.2, 0.6, 0.1])
Xrm = Xr.copy()
Xrm[4, 2] = np.nan                                            # a target one rater missed: left out
rcols = [f'r{j}' for j in range(kr)]
tid_icc = table({c: Xrm[:, j].tolist() for j, c in enumerate(rcols)})
ic = call('multivariate.icc', table=tid_icc, columns=rcols)
Xc_ = np.delete(Xr, 4, axis=0)
ncs = len(Xc_)
check('ICC: the targets rated by every rater, one row left out (and a note says so)', (ic['n'], ic['k'], ic['left_out'], any('left out' in t for t in ic['notes'])), (float(ncs), kr, 1, True))
av = {x['source']: x for x in ic['anova']}
longr = pd.DataFrame(Xc_, columns=rcols).reset_index().melt(id_vars='index', var_name='rater', value_name='y')
a2 = sm.stats.anova_lm(smf.ols('y ~ C(index) + C(rater)', longr).fit())
check.near('Between Targets SS = least squares on the stacked ratings', av['Between Targets']['ss'], float(a2.loc['C(index)', 'sum_sq']), rel=1e-10)
check.near('Between Raters SS', av['Between Raters']['ss'], float(a2.loc['C(rater)', 'sum_sq']), rel=1e-10)
check.near('Residual SS', av['Residual']['ss'], float(a2.loc['Residual', 'sum_sq']), rel=1e-10)
check('the DF', (av['Between Targets']['df'], av['Between Raters']['df'], av['Residual']['df'], av['Within Targets']['df'], av['Total']['df']),
      (float(ncs - 1), float(kr - 1), float((ncs - 1) * (kr - 1)), float(ncs * (kr - 1)), float(ncs * kr - 1)))
a1 = sm.stats.anova_lm(smf.ols('y ~ C(index)', longr).fit())
check.near('Within Targets MS = the error of the one-way model', av['Within Targets']['ms'], float(a1.loc['Residual', 'mean_sq']), rel=1e-10)
check.near("Between Raters F = the stacked fit's", av['Between Raters']['f'], float(a2.loc['C(rater)', 'F']), rel=1e-10)
MSR, MSC, MSE, MSW = (float(a2.loc['C(index)', 'mean_sq']), float(a2.loc['C(rater)', 'mean_sq']), float(a2.loc['Residual', 'mean_sq']), float(a1.loc['Residual', 'mean_sq']))
nn, kk = ncs, kr
want = {'ICC(1,1)': (MSR - MSW) / (MSR + (kk - 1) * MSW), 'ICC(A,1)': (MSR - MSE) / (MSR + (kk - 1) * MSE + kk * (MSC - MSE) / nn),
        'ICC(C,1)': (MSR - MSE) / (MSR + (kk - 1) * MSE), 'ICC(1,k)': (MSR - MSW) / MSR, 'ICC(A,k)': (MSR - MSE) / (MSR + (MSC - MSE) / nn), 'ICC(C,k)': (MSR - MSE) / MSR}
got = {x['form']: x for x in ic['icc']}
check('the six forms in order, with Shrout and Fleiss\'s names', [(x['form'], x['sf']) for x in ic['icc']],
      [('ICC(1,1)', 'ICC(1,1)'), ('ICC(A,1)', 'ICC(2,1)'), ('ICC(C,1)', 'ICC(3,1)'), ('ICC(1,k)', 'ICC(1,k)'), ('ICC(A,k)', 'ICC(2,k)'), ('ICC(C,k)', 'ICC(3,k)')])
for f_, v_ in want.items():
    check.near(f'{f_} = McGraw and Wong\'s formula from the stacked fit\'s mean squares', got[f_]['icc'], v_, rel=1e-10)
for f_ in ('ICC(1,1)', 'ICC(1,k)'):
    check.near(f'{f_}: F = MSR/MSW', got[f_]['f'], MSR / MSW, rel=1e-10)
    check.near(f'{f_}: its p-value on (n - 1, n(k - 1)) DF', got[f_]['p'], float(stats.f.sf(MSR / MSW, nn - 1, nn * (kk - 1))), rel=1e-9)
for f_ in ('ICC(A,1)', 'ICC(C,1)', 'ICC(A,k)', 'ICC(C,k)'):
    check.near(f'{f_}: F = MSR/MSE', got[f_]['f'], MSR / MSE, rel=1e-10)
    check('... on (n - 1, (n - 1)(k - 1)) DF', (got[f_]['df1'], got[f_]['df2']), (float(nn - 1), float((nn - 1) * (kk - 1))))
# the exact intervals invert the F distribution: at each limit the pivot is the quantile
fq_ = stats.f.ppf(0.975, nn - 1, (nn - 1) * (kk - 1))
L_ = got['ICC(C,1)']['lower']
check.near('ICC(C,1): at the lower limit, F (1 - L)/(1 + (k - 1)L) is the 97.5% quantile', (MSR / MSE) * (1 - L_) / (1 + (kk - 1) * L_), fq_, rel=1e-9)
U_ = got['ICC(C,1)']['upper']
check.near('ICC(C,1): at the upper limit, the 2.5% quantile', (MSR / MSE) * (1 - U_) / (1 + (kk - 1) * U_), stats.f.ppf(0.025, nn - 1, (nn - 1) * (kk - 1)), rel=1e-9)
L_ = got['ICC(1,1)']['lower']
check.near('ICC(1,1): the same with MSW', (MSR / MSW) * (1 - L_) / (1 + (kk - 1) * L_), stats.f.ppf(0.975, nn - 1, nn * (kk - 1)), rel=1e-9)
for one, many in (('ICC(1,1)', 'ICC(1,k)'), ('ICC(C,1)', 'ICC(C,k)'), ('ICC(A,1)', 'ICC(A,k)')):
    sb = lambda x: kk * x / (1 + (kk - 1) * x)  # noqa: E731 (Spearman-Brown)
    check.near(f'{many} = Spearman-Brown of {one}', got[many]['icc'], sb(got[one]['icc']), rel=1e-10)
    check.near(f'{many}: its limits are Spearman-Brown of {one}\'s', got[many]['lower'] + got[many]['upper'], sb(got[one]['lower']) + sb(got[one]['upper']), rel=1e-10)
# absolute agreement: McGraw and Wong's approximate interval, written out
r_ = want['ICC(A,1)']
a_, b_ = kk * r_ / (nn * (1 - r_)), 1 + kk * r_ * (nn - 1) / (nn * (1 - r_))
v_ = (a_ * MSC + b_ * MSE) ** 2 / ((a_ * MSC) ** 2 / (kk - 1) + (b_ * MSE) ** 2 / ((nn - 1) * (kk - 1)))
Fs_, Ft_ = stats.f.ppf(0.975, nn - 1, v_), stats.f.ppf(0.975, v_, nn - 1)
check.near("ICC(A,1): McGraw and Wong's lower limit (Satterthwaite's DF)", got['ICC(A,1)']['lower'], nn * (MSR - Fs_ * MSE) / (Fs_ * (kk * MSC + (kk * nn - kk - nn) * MSE) + nn * MSR), rel=1e-9)
check.near('... and upper limit', got['ICC(A,1)']['upper'], nn * (Ft_ * MSR - MSE) / (kk * MSC + (kk * nn - kk - nn) * MSE + nn * Ft_ * MSR), rel=1e-9)
ic90 = {x['form']: x for x in call('multivariate.icc', table=tid_icc, columns=rcols, alpha=0.1)['icc']}
check('α = 0.1 gives narrower intervals', all(ic90[f_]['lower'] > got[f_]['lower'] and ic90[f_]['upper'] < got[f_]['upper'] for f_ in want), True)
if pg is not None:
    pgi = pg.intraclass_corr(data=longr, targets='index', raters='rater', ratings='y').set_index('Type')
    for f_ in want:
        check.near(f'{f_} = pingouin intraclass_corr', got[f_]['icc'], float(pgi.loc[f_, 'ICC']), rel=1e-10)
        check.near(f'{f_}: F and its DF = pingouin\'s', got[f_]['f'] + got[f_]['df1'] + got[f_]['df2'], float(pgi.loc[f_, 'F'] + pgi.loc[f_, 'df1'] + pgi.loc[f_, 'df2']), rel=1e-10)
        check.near(f'{f_}: its p-value = pingouin\'s', got[f_]['p'], float(pgi.loc[f_, 'pval']), rel=1e-8)
        lo_, hi_ = pgi.loc[f_, 'CI95']
        check(f'{f_}: its 95% interval = pingouin\'s (which rounds to two decimals)', (abs(got[f_]['lower'] - lo_) <= 0.005 + 1e-12, abs(got[f_]['upper'] - hi_) <= 0.005 + 1e-12), (True, True))
    wine = pg.read_dataset('icc')                              # pingouin's example: 8 wines, 4 judges
    ww = wine.pivot(index='Wine', columns='Judge', values='Scores')
    iw = {x['form']: x for x in call('multivariate.icc', table=table({str(j): ww[j].tolist() for j in ww.columns}), columns=[str(j) for j in ww.columns])['icc']}
    pgw = pg.intraclass_corr(data=wine, targets='Wine', raters='Judge', ratings='Scores').set_index('Type')
    check("pingouin's wine example: the six coefficients", [round(iw[f_]['icc'], 12) for f_ in want], [round(float(pgw.loc[f_, 'ICC']), 12) for f_ in want])
    check("... and their F ratios", [round(iw[f_]['f'], 10) for f_ in want], [round(float(pgw.loc[f_, 'F']), 10) for f_ in want])
# Freq counts a row that many times
fr_ = np.where(np.arange(nt) % 4 == 0, 2.0, 1.0)
icf = {x['form']: x for x in call('multivariate.icc', table=table({**{c: Xr[:, j].tolist() for j, c in enumerate(rcols)}, 'f': fr_.tolist()}), columns=rcols, freq='f')['icc']}
rep_ = np.repeat(np.arange(nt), fr_.astype(int))
ice = {x['form']: x for x in call('multivariate.icc', table=table({c: Xr[rep_, j].tolist() for j, c in enumerate(rcols)}), columns=rcols)['icc']}
check.near('Freq: the ICC(A,1) of the rows counted twice = that of the repeated rows', icf['ICC(A,1)']['icc'], ice['ICC(A,1)']['icc'], rel=1e-10)
check.near('Freq: its interval too', icf['ICC(A,1)']['lower'], ice['ICC(A,1)']['lower'], rel=1e-9)
check('constant ratings: an error, not a division by zero', 'error' in call('multivariate.icc', table=table({'a': [1.0] * 5, 'b': [1.0] * 5}), columns=['a', 'b']), True)
check('one rater: an error', 'error' in call('multivariate.icc', table=tid_icc, columns=['r0']), True)

# ---- Kendall's W ----------------------------------------------------------------------------------------------------
kw = call('multivariate.kendall_w', table=tid_icc, columns=rcols)
fr_st = stats.friedmanchisquare(*Xc_)
check("Kendall's W: the objects rated by every rater", (kw['n'], kw['m'], kw['left_out'], kw['df']), (ncs, kr, 1, ncs - 1))
check.near("Kendall's W = Friedman's chi-square / (m (n - 1)) (no ties)", kw['w'], float(fr_st.statistic) / (kr * (ncs - 1)), rel=1e-10)
check.near('its chi-square = scipy friedmanchisquare', kw['chi2'], float(fr_st.statistic), rel=1e-10)
check.near('its p-value', kw['p'], float(fr_st.pvalue), rel=1e-9)
Rk = pd.DataFrame(Xc_).rank(axis=0).to_numpy()                 # pandas' ranks, independently
Sk = float(((Rk.sum(1) - Rk.sum(1).mean()) ** 2).sum())
check.near("W = 12 S/(m² (n³ - n)) by the definition", kw['w'], 12 * Sk / (kr ** 2 * (ncs ** 3 - ncs)), rel=1e-10)
sp_ = pd.DataFrame(Xc_).corr(method='spearman').to_numpy()
check.near('the mean Spearman ρ of the pairs of raters (pandas)', kw['mean_spearman'], float(sp_[np.triu_indices(kr, 1)].mean()), rel=1e-10)
check.near('... = (m W - 1)/(m - 1) without ties', kw['mean_spearman'], (kr * kw['w'] - 1) / (kr - 1), rel=1e-9)
Xt = rng_icc.integers(1, 6, size=(18, 4)).astype(float)       # ratings 1 to 5: many ties
Xt[:, 1] = np.clip(Xt[:, 0] + rng_icc.integers(-1, 2, 18), 1, 5)
tid_t = table({f'j{j}': Xt[:, j].tolist() for j in range(4)})
kt = call('multivariate.kendall_w', table=tid_t, columns=[f'j{j}' for j in range(4)])
ft_ = stats.friedmanchisquare(*Xt)
check.near("ties: the chi-square = scipy's Friedman statistic, ties corrected", kt['chi2'], float(ft_.statistic), rel=1e-10)
check.near('ties: W = chi-square / (m (n - 1))', kt['w'], float(ft_.statistic) / (4 * 17), rel=1e-10)
Tt = 0.0
for j in range(4):   # t³ - t for each group of t tied objects of a rater (pandas' counts)
    c_ = pd.Series(Xt[:, j]).value_counts().to_numpy()
    Tt += float((c_ ** 3 - c_).sum())
Rt = pd.DataFrame(Xt).rank(axis=0).to_numpy()
St = float(((Rt.sum(1) - Rt.sum(1).mean()) ** 2).sum())
check.near('ties: W = 12 S/(m² (n³ - n) - m T) by the definition', kt['w'], 12 * St / (16 * (18 ** 3 - 18) - 4 * Tt), rel=1e-10)
check('ties: the correction term T', kt['ties'], Tt)
if pg is not None:
    lt = pd.DataFrame(Xt).reset_index().melt(id_vars='index', var_name='rater', value_name='y')
    pgf = pg.friedman(data=lt, dv='y', within='index', subject='rater')
    check.near("pingouin friedman: Kendall's W", kt['w'], float(pgf['W'].iloc[0]), rel=1e-9)
    check.near('pingouin friedman: Q', kt['chi2'], float(pgf['Q'].iloc[0]), rel=1e-9)
same = np.tile(np.arange(8.0)[:, None], (1, 3)) * np.array([1.0, 2.0, 0.5])
check.near('raters that rank alike: W = 1', call('multivariate.kendall_w', table=table({f'a{j}': same[:, j].tolist() for j in range(3)}), columns=['a0', 'a1', 'a2'])['w'], 1.0, rel=1e-12)
check.near('two raters in reverse order: W = 0', call('multivariate.kendall_w', table=table({'u': list(range(6)), 'v': list(range(6, 0, -1))}), columns=['u', 'v'])['w'], 0.0, abs_=1e-12)
check('every object tied by every rater: an error', 'error' in call('multivariate.kendall_w', table=table({'a': [2.0] * 4, 'b': [3.0] * 4}), columns=['a', 'b']), True)

# ---- their code, on the table exported as CSV -----------------------------------------------------------------------
import contextlib as _cl  # noqa: E402
import io as _io  # noqa: E402
import os as _os  # noqa: E402
import tempfile as _tf  # noqa: E402


def run_csv(code, frame):
    here = _os.getcwd()
    with _tf.TemporaryDirectory() as tmp_:
        frame.to_csv(_os.path.join(tmp_, 'data.csv'), index=False)
        _os.chdir(tmp_)
        ns_ = {}
        try:
            with _cl.redirect_stdout(_io.StringIO()):
                exec(compile(code, 'report code', 'exec'), ns_)
            return ns_, None
        except Exception as ex:  # reported as a failed check
            return ns_, f'{type(ex).__name__}: {ex}'
        finally:
            _os.chdir(here)


ns_i, err = run_csv(ic['code'], pd.DataFrame({c: Xrm[:, j] for j, c in enumerate(rcols)}))
check('the code of the intraclass correlations runs on the CSV', err, None)
if not err:
    check.near('... its six coefficients are the report\'s', max(abs(ns_i['icc'][f_] - got[f_]['icc']) for f_ in want), 0.0, abs_=1e-12)
    check.near('... and their intervals', max(abs(ns_i['ci'][f_][0] - got[f_]['lower']) + abs(ns_i['ci'][f_][1] - got[f_]['upper']) for f_ in want), 0.0, abs_=1e-10)
icw = call('multivariate.icc', table=table({**{c: Xr[:, j].tolist() for j, c in enumerate(rcols)}, 'f': fr_.tolist()}), columns=rcols, freq='f')
ns_w, err = run_csv(icw['code'], pd.DataFrame({**{c: Xr[:, j] for j, c in enumerate(rcols)}, 'f': fr_}))
check('the code with a Freq column runs', err, None)
if not err:
    check.near('... and gives the report\'s ICC(A,k)', ns_w['icc']['ICC(A,k)'], {x['form']: x for x in icw['icc']}['ICC(A,k)']['icc'], rel=1e-12)
ns_k, err = run_csv(kt['code'], pd.DataFrame({f'j{j}': Xt[:, j] for j in range(4)}))
check("the code of Kendall's W runs on the CSV", err, None)
if not err:
    check.near("... its W is the report's", float(ns_k['W']), kt['w'], rel=1e-12)
    check.near("... its chi-square", float(ns_k['chi2']), kt['chi2'], rel=1e-12)


# ======================================================================================================================
# The graphs' matplotlib code, and the rows the code leaves out
# ======================================================================================================================
# Every graph's code block is run with matplotlib's Agg backend on the whole
# table's CSV export (as File > Export CSV writes it: a date as text), and its
# figure is checked against the report's numbers: the points, lines, bars,
# heatmaps, bands, texts, labels and titles (test_charts' figure probe). The
# report runs on a By group with rows excluded, so the code must keep the group
# (its where line) and drop the rows the report leaves out. The scatterplot
# matrix's code is the page's: test-ui-multivariate.py checks it.
import datetime as _dt  # noqa: E402
import tempfile as _tempfile  # noqa: E402

from backend import data  # noqa: E402
from test_charts import close, run_snippet  # noqa: E402

PAL = ['#2f6690', '#d9822b', '#3a7d44', '#b0413e', '#6c5b7b', '#1f9e89', '#c0a000', '#8c564b', '#e377c2', '#7f7f7f', '#17becf', '#9467bd']
_tmp = _tempfile.mkdtemp(prefix='smui-mv-charts-')


def export(tid):
    """The table as File > Export CSV writes it: every column; a date column as its day."""
    t = data.TABLES[tid]
    out = {}
    for name, v in t['cols'].items():
        m = t['meta'][name]
        if m.get('dataType') == 'numeric' and (m.get('format') or {}).get('kind') == 'date':
            out[name] = [(_dt.datetime(1970, 1, 1) + _dt.timedelta(milliseconds=float(x))).strftime('%Y-%m-%d') if np.isfinite(x) else '' for x in v]
        elif m.get('dataType') == 'numeric':
            out[name] = np.asarray(v, dtype=float)
        else:
            out[name] = pd.Series(list(v), dtype=object)
    return pd.DataFrame(out)


def figure(label, code, tid):
    """Run a graph's code on the table's CSV; its one figure (as the probe reads it), or a blank one."""
    figs, err = run_snippet(code, export(tid), 'data', _tmp)
    check(f'{label}: the code runs', err, None)
    check(f'{label}: it ends with plt.show()', code.rstrip().split('\n')[-1], 'plt.show()')
    check(f'{label}: one figure', len(figs or []), 1)
    blank = {'lines': [], 'bars': [], 'scatter': [], 'polys': [], 'patches': [], 'texts': [], 'segments': [], 'legend': [], 'images': [],
             'title': '', 'xlabel': '', 'ylabel': '', 'xticklabels': [], 'yticklabels': [], 'xlim': [], 'ylim': [], 'visible': True}
    return figs[0] if figs else {'axes': [blank, blank], 'suptitle': '', 'legend': []}


def arr(v):
    return np.array([np.nan if x is None else x for x in np.asarray(v, dtype=object).ravel()], dtype=float)


def gap(a, b):
    """The largest difference of two arrays, NaN where both are NaN; inf when they differ in shape or NaN."""
    a, b = arr(a), arr(b)
    if a.shape != b.shape or not a.size or (np.isnan(a) != np.isnan(b)).any():
        return float('inf')
    ok = ~np.isnan(a)
    return float(np.max(np.abs(a[ok] - b[ok]))) if ok.any() else 0.0


def pts(ax, k=0):
    return np.asarray(ax['scatter'][k]['xy'], dtype=float) if len(ax['scatter']) > k and ax['scatter'][k]['xy'] else np.zeros((0, 2))


def texts(ax):
    return [t['s'] for t in ax['texts'] if t['s']]


def page_ellipse(mx, my, sx, sy, r, level):
    """The page's density ellipse (smui-p-multivariate.js), written again here."""
    c = math.sqrt(-2 * math.log(1 - level))
    rr = max(-0.999999, min(0.999999, r or 0))
    t = [2 * math.pi * k / 72 for k in range(73)]
    return [mx + c * sx * math.cos(u) for u in t], [my + c * sy * (rr * math.cos(u) + math.sqrt(1 - rr * rr) * math.sin(u)) for u in t]


def has_line(ax, x, y, rel=1e-9, color=None, **props):
    """Whether the axes have a line with these data (None: any) and properties, its colour by its hex (without alpha)."""
    for ln in ax['lines']:
        if x is not None and not close(ln['x'], x, rel, 1e-9):
            continue
        if y is not None and not close(ln['y'], y, rel, 1e-9):
            continue
        if color is not None and (ln['color'] or '')[:7] != color:
            continue
        if any(ln.get(k) != v for k, v in props.items()):
            continue
        return True
    return False


def keeps(label, code, where_line, dropped):
    """The code keeps the By group's rows and drops those the report leaves out."""
    check(f'{label}: the code keeps the By group', where_line in code, True)
    check(f'{label}: ... and drops the rows the report leaves out', f'df = df.drop(index={dropped})   # the rows the report leaves out' in code, True)


cr_ = np.random.default_rng(20260929)
nq = 90
zq = cr_.normal(size=(nq, 2))
Xq = np.column_stack([zq[:, 0] + 0.3 * cr_.normal(size=nq), zq[:, 0] + 0.5 * cr_.normal(size=nq), zq[:, 1] + 0.4 * cr_.normal(size=nq),
                      zq[:, 1] - 0.3 * zq[:, 0] + 0.6 * cr_.normal(size=nq), 0.5 * zq[:, 0] + 0.5 * zq[:, 1] + 0.7 * cr_.normal(size=nq)]).round(4)
Xq[7, 1] = np.nan
day0 = _dt.datetime(2024, 1, 1)
dts = [((day0 + _dt.timedelta(days=int(d))) - _dt.datetime(1970, 1, 1)).total_seconds() * 1000 for d in (40 * zq[:, 0] + 3 * np.arange(nq)).round()]
gq = ['hi' if v > 0.3 else 'lo' if v < -0.5 else 'mid' for v in zq[:, 0]]
kq = np.arange(nq) % 3
uq = (np.array([0, 6, 0])[kq] + cr_.normal(size=nq)).round(3)
vq = (np.array([0, 0, 6])[kq] + cr_.normal(size=nq)).round(3)
q1 = [['A', 'B', 'C'][k] if cr_.uniform() < 0.7 else ['A', 'B', 'C'][int(cr_.integers(3))] for k in kq]
q2 = [['x', 'y', 'y'][k] if cr_.uniform() < 0.6 else ['x', 'y'][int(cr_.integers(2))] for k in kq]
q3 = [float(1 + (i % 2)) if cr_.uniform() < 0.8 else 3.0 for i in range(nq)]
wq = cr_.uniform(0.5, 2, nq).round(3)
fq = cr_.integers(1, 4, nq).astype(float)
fq[11] = 0.0
ybq = ['yes' if a > 0.2 else 'no' for a in np.nan_to_num(Xq[:, 0])]
colsq = ['a', 'b', 'c', 'd', 'e']
tq = table({'id': [f'R{i + 1}' for i in range(nq)], **{c: Xq[:, j] for j, c in enumerate(colsq)}, 'dt': dts, 'g': gq, 'w': wq, 'f': fq,
            'u': uq, 'v': vq, 'q1': q1, 'q2': q2, 'q3': q3, 'yb': ybq},
           types={'q3': 'nominal'}, levels={'g': ['mid', 'hi', 'lo'], 'q1': ['C', 'A', 'B'], 'q2': ['y', 'x'], 'q3': [2.0, 1.0, 3.0], 'yb': ['no', 'yes']})
data.TABLES[tq]['meta']['dt']['format'] = {'kind': 'date'}      # a date column: milliseconds in the page, a day in the CSV
hi = [i for i in range(nq) if gq[i] == 'hi']
excluded = sorted({hi[0], hi[3], 5, 30, 41})                     # rows excluded in the page, two of them in the group g = hi
grp_rows = [i for i in hi if i not in excluded]                  # the By group g = hi, with some rows excluded
grp_drop = [i for i in hi if i in excluded]
where_hi = [{'column': 'g', 'value': 'hi'}]
WHERE_HI = 'df = df[df["g"] == "hi"]   # only the rows where g is hi'
all_rows = [i for i in range(nq) if i not in excluded]           # every group, some rows excluded

# ---- Multivariate: the colour maps (a date column among the Y columns) -----------------------------------------------
cm_cols = ['a', 'b', 'c', 'dt', 'e']
for label, kw in (('row-wise', {}), ('pairwise', {'method': 'pairwise'}), ('row-wise, Freq', {'freq': 'f'}), ('pairwise, Weight and Freq', {'method': 'pairwise', 'weight': 'w', 'freq': 'f'})):
    r = call('multivariate.fit', table=tq, columns=cm_cols, rows=grp_rows, where=where_hi, **kw)
    R_ = arr(r['corr']).reshape(5, 5)
    P_ = arr(r['p']).reshape(5, 5)
    order_ = call('multivariate.cluster_order', corr=r['corr'])['order']
    for key, title, Z, names_, txt in (('cm_corr_code', 'Color Map On Correlations', R_, cm_cols, lambda v: f'{v:.2f}'.replace('-', '−')),
                                       ('cm_p_code', 'Color Map On p-values', P_, cm_cols, None),
                                       ('cm_cluster_code', 'Cluster the Correlations', R_[np.ix_(order_, order_)], [cm_cols[k] for k in order_], lambda v: f'{v:.2f}'.replace('-', '−'))):
        tag = f'{title} ({label})'
        code_ = r[key]
        if key == 'cm_corr_code' and label == 'row-wise':
            keeps(tag, code_, WHERE_HI, grp_drop)
            check(f'{tag}: the date column turned back into the page\'s number', 'df["dt"] = (pd.to_datetime(df["dt"]) - pd.Timestamp(0)) / pd.Timedelta(milliseconds=1)' in code_, True)
        F = figure(tag, code_, tq)
        ax = F['axes'][0]
        img = arr(ax['images'][0]['data']).reshape(5, 5) if ax['images'] else np.zeros((5, 5))
        check.near(f'{tag}: the cells are the report\'s {"p-values" if "p-values" in title else "correlations"}', gap(img, Z), 0.0, abs_=1e-12)
        check(f'{tag}: the columns in the page\'s order, the first at the top', ([t for t in ax['xticklabels'] if t], [t for t in ax['yticklabels'] if t], ax['yinverted']), (names_, names_, True))
        want_txt = [txt(v) for v in Z.ravel()] if txt else [('' if i == j else ('.' if np.isnan(Z[i, j]) else ('<.0001' if Z[i, j] < 0.0001 else f'{Z[i, j]:.4f}') + ('*' if Z[i, j] < 0.05 else ''))) for i in range(5) for j in range(5)]
        check(f'{tag}: the values in the cells, as the page writes them', [t['s'] for t in ax['texts']], want_txt)
        check(f'{tag}: the title and a colour bar', (ax['title'], len(F['axes'])), (title, 2))

# ---- Multivariate: the outlier distances ----------------------------------------------------------------------------
o_ = call('multivariate.outliers', table=tq, columns=colsq, rows=grp_rows, where=where_hi)
for key, field, ucl, title, ytitle in (('mahal_code', 'mahal', 'ucl_mahal', 'Mahalanobis Distances', 'Mahalanobis Distance'), ('jack_code', 'jack', 'ucl_jack', 'Jackknife Distances', 'Jackknife Distance'),
                                       ('t2_code', 't2', 'ucl_t2', 'T²', 'T²')):
    F = figure(title, o_[key], tq)
    ax = F['axes'][0]
    P = pts(ax)
    check.near(f'{title}: the points are the rows (row number, distance)', max(gap(P[:, 0], np.array(o_['rows']) + 1), gap(P[:, 1], o_[field])), 0.0, abs_=1e-9)
    check(f'{title}: the dashed UCL', has_line(ax, None, [o_[ucl], o_[ucl]], ls='--', color='#c0392b'), True)
    check(f'{title}: the UCL written at its line, as the page writes it', texts(ax), [f'UCL {o_[ucl]:.5g}'])
    check(f'{title}: the titles', (ax['xlabel'], ax['ylabel'], ax['title']), ('Row Number', ytitle, title))
keeps('Mahalanobis Distances', o_['mahal_code'], WHERE_HI, grp_drop)

# ---- Principal Components ----------------------------------------------------------------------------------------------
for label, kw, a_, b_ in (('on correlations, Prin2 by Prin3, ellipse, varimax', {'rotation': 'varimax', 'n_rotate': 2}, 1, 2),
                          ('on covariances, Freq, promax of 3', {'on': 'covariances', 'freq': 'f', 'rotation': 'promax', 'n_rotate': 3}, 0, 1),
                          ('unscaled, Weight, the same component twice', {'on': 'unscaled', 'weight': 'w', 'rotation': 'quartimin', 'n_rotate': 2, 'kaiser': False}, 2, 2)):
    pc_ = call('pca.fit', table=tq, columns=colsq, rows=all_rows, plot={'x': a_, 'y': b_, 'ellipse': True}, **kw)
    ev_, sc_, ld_ = np.array(pc_['eigenvalues']), arr(pc_['scores']).reshape(-1, 5), arr(pc_['loadings']).reshape(5, 5)
    on_ = kw.get('on', 'correlations')
    F = figure(f'PCA {label}: eigenvalues', pc_['eigen_code'], tq)
    ax = F['axes'][0]
    check.near(f'PCA {label}: the bars are the eigenvalues', gap([b['h'] for b in ax['bars']], ev_), 0.0, abs_=1e-12)
    check(f'PCA {label}: the dotted line at an eigenvalue of 1, on correlations only', has_line(ax, None, [1, 1], ls=':'), on_ == 'correlations')
    F = figure(f'PCA {label}: scree plot', pc_['scree_code'], tq)
    ax = F['axes'][0]
    check(f'PCA {label}: the scree line', has_line(ax, list(range(1, 6)), list(ev_), rel=1e-12), True)
    check(f'PCA {label}: the scree plot\'s titles', (ax['xlabel'], ax['ylabel'], ax['title']), ('Number of Components', 'Eigenvalue', 'Scree Plot'))
    for key, size in (('score_summary_code', [3.0, 2.8]), ('score_code', [4.4, 3.8])):
        F = figure(f'PCA {label}: {key}', pc_[key], tq)
        ax = F['axes'][0]
        P = pts(ax)
        check.near(f'PCA {label}: {key}: the points are the report\'s scores', max(gap(P[:, 0], sc_[:, a_]), gap(P[:, 1], sc_[:, b_])), 0.0, abs_=1e-9)
        x_, y_ = sc_[:, a_], sc_[:, b_]
        ex, ey = page_ellipse(x_.mean(), y_.mean(), x_.std(ddof=1), y_.std(ddof=1), 0 if a_ == b_ else float(np.corrcoef(x_, y_)[0, 1]), 0.95)
        check(f'PCA {label}: {key}: the 95% ellipse of the scores', has_line(ax, ex, ey, rel=1e-7), True)
        check(f'PCA {label}: {key}: the titles and the size', (ax['xlabel'], ax['ylabel'], ax['title'], F['size']), (f'Prin{a_ + 1}', f'Prin{b_ + 1}', 'Score Plot', size))
    for key in ('loading_summary_code', 'loading_code'):
        F = figure(f'PCA {label}: {key}', pc_[key], tq)
        ax = F['axes'][0]
        P = pts(ax)
        check.near(f'PCA {label}: {key}: the diamonds are the loadings', max(gap(P[:, 0], ld_[:, a_]), gap(P[:, 1], ld_[:, b_])), 0.0, abs_=1e-9)
        check(f'PCA {label}: {key}: a ray to each column', all(has_line(ax, [0, ld_[i, a_]], [0, ld_[i, b_]], color='#786b5d') for i in range(5)), True)
        check(f'PCA {label}: {key}: the names at the ends', texts(ax), colsq)
        circ = [p for p in ax['patches'] if p['type'] == 'ellipse']
        unit = on_ != 'unscaled'
        check(f'PCA {label}: {key}: the unit circle (not unscaled), the axes to ±1.15', (len(circ) == 1 and close(circ[0]['center'], [0, 0]) and close([circ[0]['w'], circ[0]['h']], [2, 2]), ax['xlim'] == [-1.15, 1.15]) if unit else (len(circ), False), (True, True) if unit else (0, False))
    F = figure(f'PCA {label}: biplot', pc_['biplot_code'], tq)
    ax = F['axes'][0]
    P = pts(ax)
    s_ = 0.85 * max(np.abs(sc_[:, a_]).max(), np.abs(sc_[:, b_]).max()) / max(np.abs(ld_[:, a_]).max(), np.abs(ld_[:, b_]).max())
    check.near(f'PCA {label}: biplot: the points', max(gap(P[:, 0], sc_[:, a_]), gap(P[:, 1], sc_[:, b_])), 0.0, abs_=1e-9)
    check(f'PCA {label}: biplot: the rays scaled to the spread of the scores', all(has_line(ax, [0, s_ * ld_[i, a_]], [0, s_ * ld_[i, b_]], rel=1e-9, color='#c0392b') for i in range(5)), True)
    rl_ = arr(pc_['rotation']['loadings']).reshape(5, -1)
    F = figure(f'PCA {label}: rotated components', pc_['rotated_code'], tq)
    ax = F['axes'][0]
    P = pts(ax)
    check.near(f'PCA {label}: the rotated loadings ({pc_["rotation"]["label"]})', max(gap(P[:, 0], rl_[:, 0]), gap(P[:, 1], rl_[:, 1])), 0.0, abs_=1e-9)
    check(f'PCA {label}: the rotated loading plot\'s titles', (ax['xlabel'], ax['ylabel'], ax['title']), ('Factor 1', 'Factor 2', 'Loading Plot'))

# ---- Factor Analysis -------------------------------------------------------------------------------------------------------
fe_ = call('factor.eigen', table=tq, columns=colsq, rows=grp_rows, where=where_hi)
F = figure('Factor Analysis: scree plot', fe_['scree_code'], tq)
ax = F['axes'][0]
check('Factor Analysis: the scree line is the eigenvalues of the correlations', has_line(ax, list(range(1, 6)), fe_['eigen']['values'], rel=1e-12), True)
keeps('Factor Analysis: scree plot', fe_['scree_code'], WHERE_HI, grp_drop)
for label, kw, a_, b_ in (('ML, varimax', {'n_factors': 2, 'method': 'ml', 'rotation': 'varimax'}, 0, 1), ('principal axis, promax, Freq, 3 factors', {'n_factors': 3, 'method': 'pa', 'rotation': 'promax', 'freq': 'f'}, 2, 1),
                          ('ML, one factor, Weight', {'n_factors': 1, 'method': 'ml', 'rotation': 'varimax', 'weight': 'w'}, 0, 1), ('ML, the default number, oblimin', {'n_factors': None, 'method': 'ml', 'rotation': 'oblimin', 'gamma': 0.3}, 0, 1)):
    fa_ = call('factor.fit', table=tq, columns=colsq, rows=all_rows, plot={'x': a_, 'y': b_}, **kw)
    kk_ = fa_['k']
    a2, b2 = min(a_, kk_ - 1), min(b_, kk_ - 1)
    L_, S_ = arr(fa_['rotated']).reshape(5, kk_), arr(fa_['scores']).reshape(-1, kk_)
    if kk_ >= 2:
        F = figure(f'Factor Analysis {label}: loading plot', fa_['loading_code'], tq)
        ax = F['axes'][0]
        P = pts(ax)
        check.near(f'Factor Analysis {label}: the loadings plotted are the report\'s', max(gap(P[:, 0], L_[:, a2]), gap(P[:, 1], L_[:, b2])), 0.0, abs_=1e-9)
        check(f'Factor Analysis {label}: the loading plot\'s titles', (ax['xlabel'], ax['ylabel']), (f'Factor {a2 + 1}', f'Factor {b2 + 1}'))
    else:
        check(f'Factor Analysis {label}: one factor, no loading plot', 'loading_code' in fa_, False)
    F = figure(f'Factor Analysis {label}: score plot', fa_['score_code'], tq)
    ax = F['axes'][0]
    P = pts(ax)
    check.near(f'Factor Analysis {label}: the scores plotted are the report\'s', max(gap(P[:, 0], S_[:, a2]), gap(P[:, 1], S_[:, b2] if kk_ > 1 else np.zeros(len(S_)))), 0.0, abs_=1e-9)

# ---- Discriminant -----------------------------------------------------------------------------------------------------------
for label, kw, xc in (('linear', {}, 'g'), ('quadratic, Freq', {'method': 'quadratic', 'freq': 'f'}, 'g'), ('regularized, proportional priors', {'method': 'regularized', 'lam': 0.3, 'gam': 0.2, 'priors': 'proportional'}, 'g'),
                      ('two groups (one canonical variable), priors given', {'priors': 'other', 'prior_values': {'no': 1, 'yes': 3}}, 'yb')):
    dr_ = call('discriminant.fit', table=tq, y=['a', 'c', 'd', 'e'], x=xc, rows=all_rows, plot={'points': True, 'cl': True, 'c50': True, 'rays': True}, **kw)
    C_ = dr_['canonical']
    m_ = C_['m']
    cs_, cm_, std_ = arr(C_['scores']).reshape(-1, m_), arr(C_['means']).reshape(-1, m_), arr(C_['std']).reshape(4, m_)
    labs = [str(v) for v in dr_['levels']]
    F = figure(f'Discriminant {label}: canonical plot', dr_['canonical_code'], tq)
    ax = F['axes'][0]
    P = pts(ax)
    act = np.array(dr_['actual'])
    if m_ >= 2:
        check.near(f'Discriminant {label}: the rows\' canonical scores', max(gap(P[:, 0], cs_[:, 0]), gap(P[:, 1], cs_[:, 1])), 0.0, abs_=1e-9)
    else:
        hh_ = np.sin(np.arange(len(act)) * 12.9898 + 78.233) * 43758.5453
        check.near(f'Discriminant {label}: the rows by their group, jittered as the page', max(gap(P[:, 0], cs_[:, 0]), gap(P[:, 1], act + (hh_ - np.floor(hh_) - 0.5) * 0.5)), 0.0, abs_=1e-9)
    check(f'Discriminant {label}: each row in its group\'s colour', [c_[:7] for c_ in ax['scatter'][0]['colors']] if ax['scatter'] else None, [PAL[t % 12] for t in act])
    two = m_ >= 2
    means_ok, cl_ok, c50_ok = True, True, True
    for t, n_t in enumerate(dr_['counts']):
        mx, my = cm_[t, 0], (cm_[t, 1] if two else t)
        means_ok &= has_line(ax, [mx], [my], marker='+', color=PAL[t])
        if two:
            ex, ey = page_ellipse(mx, my, 1 / math.sqrt(n_t), 1 / math.sqrt(n_t), 0, 0.95)
            cl_ok &= has_line(ax, ex, ey, rel=1e-7, color=PAL[t])
            ex, ey = page_ellipse(mx, my, 1, 1, 0, 0.5)
            c50_ok &= has_line(ax, ex, ey, rel=1e-7, color=PAL[t], ls=':')
        else:
            hw = 1.96 / math.sqrt(n_t)
            cl_ok &= has_line(ax, [mx - hw, mx + hw], [my, my], color=PAL[t])
            c50_ok &= has_line(ax, [mx - 0.6745, mx + 0.6745], [my + 0.3, my + 0.3], color=PAL[t], ls=':')
    check(f'Discriminant {label}: a + at each group\'s mean, in its colour', means_ok, True)
    check(f'Discriminant {label}: the 95% confidence regions of the means', cl_ok, True)
    check(f'Discriminant {label}: the normal 50% contours', c50_ok, True)
    oy = 0 if two else len(labs) - 0.5
    check(f'Discriminant {label}: the biplot rays, 1.5 × the standardized coefficients', all(has_line(ax, [0, 1.5 * std_[j, 0]], [oy, oy + (1.5 * std_[j, 1] if two else 0.25 * (j + 1) / 4)], color='#786b5d') for j in range(4)), True)
    check(f'Discriminant {label}: the covariates at the rays\' ends, the groups in the legend', (texts(ax), ax['legend']), (['a', 'c', 'd', 'e'], labs))
    check(f'Discriminant {label}: the canonical plot\'s axes', (ax['xlabel'], ax['ylabel'] if two else [t_ for t_ in ax['yticklabels'] if t_]), ('Canonical1', 'Canonical2' if two else labs))
    F = figure(f'Discriminant {label}: scores by row', dr_['scores_code'], tq)
    ax = F['axes'][0]
    mis = np.array(dr_['misclassified'], bool)
    rows_ = np.array(dr_['rows']) + 1
    nll_ = arr(dr_['neg_log_prob'])
    P0, P1 = pts(ax, 0), pts(ax, 1)
    check.near(f'Discriminant {label}: the rows\' −log(probability of their group)', max(gap(P0[:, 0], rows_[~mis]), gap(P0[:, 1], nll_[~mis])), 0.0, abs_=1e-9)
    check.near(f'Discriminant {label}: the misclassified rows, apart in red', max(gap(P1[:, 0], rows_[mis]), gap(P1[:, 1], nll_[mis])) if mis.any() else 0.0, 0.0, abs_=1e-9)
    check(f'Discriminant {label}: the titles', (ax['xlabel'], ax['ylabel'], ax['title']), ('Row Number', '−Log(Prob(Actual))', 'Discriminant scores by row'))
dr_ = call('discriminant.fit', table=tq, y=['a', 'c'], x='q1', rows=grp_rows, where=where_hi, plot={})
keeps('Discriminant: canonical plot', dr_['canonical_code'], WHERE_HI, grp_drop)

# ---- Hierarchical Cluster ------------------------------------------------------------------------------------------------------
HC_K = "k = None   # Number of Clusters: None takes the report's default"
for label, kw in (('Ward, unstandardized', {'method': 'ward', 'standardize': 'none'}), ('average, columns standardized', {'method': 'average'}),
                  ('centroid, rows standardized', {'method': 'centroid', 'standardize': 'rows'}), ('single', {'method': 'single'}), ('complete', {'method': 'complete'})):
    hc_ = call('hcluster.fit', table=tq, columns=['u', 'v', 'a'], rows=all_rows, label='id', two_way=True, **kw)
    n_ = hc_['n']
    merges_, heights_, order_ = np.array(hc_['merges']), np.array(hc_['heights']), np.array(hc_['order'])
    best, ratio = min(3, n_), -np.inf              # the page's default number of clusters
    for q in range(2, min(10, n_ - 1) + 1):
        up, down = heights_[n_ - q], heights_[n_ - q - 1]
        rr = up / down if down > 0 else (np.inf if up > 0 else 0)
        if rr > ratio:
            best, ratio = q, rr
    pos = np.zeros(2 * n_ - 1)
    hh = np.zeros(2 * n_ - 1)
    pos[order_] = np.arange(n_)
    for s_, (a1, b1) in enumerate(merges_):
        pos[n_ + s_], hh[n_ + s_] = (pos[a1] + pos[b1]) / 2, heights_[s_]
    segs = [[[hh[a1], pos[a1]], [heights_[s_], pos[a1]], [heights_[s_], pos[b1]], [hh[b1], pos[b1]]] for s_, (a1, b1) in enumerate(merges_)]
    names_ = [f'R{r + 1}' for r in hc_['rows']]
    for k_, colored in ((None, False), (5, True)):
        kk_ = best if k_ is None else k_
        code_ = hc_['dendro_code'] if k_ is None else call('hcluster.fit', table=tq, columns=['u', 'v', 'a'], rows=all_rows, label='id', two_way=True, n_clusters=k_, **kw)['dendro_code']
        if colored:     # the page writes Color Clusters into the code
            code_ = code_.replace('color_clusters = False   # Color Clusters', 'color_clusters = True   # Color Clusters')
        tag = f'dendrogram ({label}, {"the default" if k_ is None else k_} clusters{", coloured" if colored else ""})'
        F = figure(tag, code_, tq)
        ax = F['axes'][0]
        got = ax['segments'][0]['segs'] if ax['segments'] else []
        check.near(f'{tag}: each join where the page draws it', max(gap(np.array(g_, float), np.array(w_, float)) for g_, w_ in zip(got, segs)) if len(got) == len(segs) else 1e9, 0.0, abs_=1e-9)
        cut = (heights_[n_ - kk_ - 1] + heights_[n_ - kk_]) / 2
        check(f'{tag}: the cut between the joins, at {kk_} clusters', (has_line(ax, [cut, cut], None, ls='--'), texts(ax)), (True, [f' {kk_} clusters']))
        P = pts(ax)
        check.near(f'{tag}: a leaf for each row, in the order of the tree', max(gap(P[:, 0], np.zeros(n_)), gap(P[:, 1], np.arange(n_))), 0.0, abs_=0)
        check(f'{tag}: the rows\' labels', [t_ for t_ in ax['yticklabels'] if t_], [names_[i] for i in order_])
        if colored:
            root = np.arange(2 * n_ - 1)
            parent = np.full(2 * n_ - 1, -1)
            for s_, (a1, b1) in enumerate(merges_):
                parent[a1] = parent[b1] = n_ + s_
            for v_ in range(2 * n_ - kk_ - 1, -1, -1):
                if 0 <= parent[v_] < 2 * n_ - kk_:
                    root[v_] = root[parent[v_]]
            num = {}
            for leaf in order_:
                num.setdefault(root[leaf], len(num))
            check(f'{tag}: the leaves in their clusters\' colours', [c_[:7] for c_ in ax['scatter'][0]['colors']], [PAL[num[root[leaf]] % 12] for leaf in order_])
    F = figure(f'distance graph ({label})', hc_['distgraph_code'], tq)
    ax = F['axes'][0]
    ks_ = np.arange(1, min(n_ - 1, 60) + 1)
    check(f'distance graph ({label}): the distance of the last joins by the clusters left', has_line(ax, list(ks_), list(heights_[n_ - 1 - ks_]), rel=1e-12), True)
    check(f'distance graph ({label}): the dashed line at the clusters shown, the axis reversed', (has_line(ax, [best, best], None, ls='--'), ax['xlim'][0] > ax['xlim'][1]), (True, True))
    F = figure(f'cubic clustering criterion ({label})', hc_['ccc_code'], tq)
    ax = F['axes'][0]
    crit_ = [c_['ccc'] for c_ in hc_['criterion']]
    check(f'cubic clustering criterion ({label}): the CCC of each number of clusters', has_line(ax, [c_['k'] for c_ in hc_['criterion']], crit_, rel=1e-9), True)
    F = figure(f'two way clustering ({label})', hc_['twoway_code'], tq)
    ax = F['axes'][0]
    Xs_ = arr(hc_['data']).reshape(n_, 3)
    col_order = hc_['col_order']
    check.near(f'two way clustering ({label}): the values, rows in the dendrogram\'s order and columns in theirs', gap(arr(ax['images'][0]['data']).reshape(n_, 3) if ax['images'] else [], Xs_[np.ix_(order_, col_order)]), 0.0, abs_=1e-12)
    check(f'two way clustering ({label}): the columns and rows named', ([t_ for t_ in ax['xticklabels'] if t_], [t_ for t_ in ax['yticklabels'] if t_][:3]), ([['u', 'v', 'a'][j] for j in col_order], [names_[i] for i in order_[:3]]))
hc_ = call('hcluster.fit', table=tq, columns=['u', 'v'], rows=grp_rows, where=where_hi)
keeps('dendrogram', hc_['dendro_code'], WHERE_HI, grp_drop)

# ---- K Means ----------------------------------------------------------------------------------------------------------------------
KM_RAYS = 'show_rays = True   # Biplot Rays'
for label, kw in (('2 to 4 clusters, in their units', {'k_min': 2, 'k_max': 4, 'standardize': False}), ('3 clusters, scaled, Freq', {'k_min': 3, 'freq': 'f'}),
                  ('2 to 3 clusters, Weight, 4 restarts', {'k_min': 2, 'k_max': 3, 'weight': 'w', 'restarts': 4})):
    km_ = call('kmeans.fit', table=tq, columns=['u', 'v', 'a'], rows=all_rows, **kw)
    pcs_ = arr(km_['pca']['scores']).reshape(-1, 3)
    V_ = arr(km_['pca']['vectors']).reshape(3, 3)
    for f_ in km_['fits']:
        tag = f'K Means {label}: k = {f_["k"]}'
        lab_ = np.array(f_['labels'])
        for rays in (True, False):
            code_ = f_['biplot_code'] if rays else f_['biplot_code'].replace(KM_RAYS, 'show_rays = False   # Biplot Rays')
            F = figure(f'{tag}: biplot{"" if rays else " without rays"}', code_, tq)
            ax = F['axes'][0]
            P = pts(ax)
            check.near(f'{tag}: the rows on the first two principal components', max(gap(P[:, 0], pcs_[:, 0]), gap(P[:, 1], pcs_[:, 1])), 0.0, abs_=1e-9)
            check(f'{tag}: each row in its cluster\'s colour', [c_[:7] for c_ in ax['scatter'][0]['colors']], [PAL[c_ % 12] for c_ in lab_])
            cen = [s_ for s_ in ax['scatter'][1:] if s_['label'].startswith('Cluster')]
            want_c = [[pcs_[lab_ == c_, 0].mean(), pcs_[lab_ == c_, 1].mean()] for c_ in range(f_['k'])]
            check.near(f'{tag}: a circle at each cluster\'s mean', gap([q_['xy'][0] for q_ in cen], want_c), 0.0, abs_=1e-9)
            check.near(f'{tag}: ... as large as its share of the rows', gap([q_['sizes'][0] for q_ in cen], [(0.72 * (10 + 22 * math.sqrt(cnt / km_['n']))) ** 2 for cnt in f_['counts']]), 0.0, abs_=1e-9)
            ell_ok = True
            for c_ in range(f_['k']):
                xs_, ys_ = pcs_[lab_ == c_, 0], pcs_[lab_ == c_, 1]
                if len(xs_) > 2:
                    Cv = np.cov(xs_, ys_)
                    ex, ey = page_ellipse(xs_.mean(), ys_.mean(), math.sqrt(Cv[0, 0]), math.sqrt(Cv[1, 1]), Cv[0, 1] / math.sqrt(Cv[0, 0] * Cv[1, 1]), 0.9)
                    ell_ok &= has_line(ax, ex, ey, rel=1e-7, color=PAL[c_])
            check(f'{tag}: the 90% ellipse of each cluster', ell_ok, True)
            s_ = 0.8 * np.abs(pcs_[:, :2]).max() / np.abs(V_[:, :2]).max()
            got_rays = all(has_line(ax, [0, s_ * V_[j, 0]], [0, s_ * V_[j, 1]], rel=1e-9, color='#786b5d') for j in range(3))
            check(f'{tag}: the columns\' rays {"drawn" if rays else "left out (Biplot Rays off)"}', (got_rays, sorted(t_ for t_ in texts(ax) if t_ in ('u', 'v', 'a'))), (rays, ['a', 'u', 'v'] if rays else []))
            ev_k = np.array(km_['pca']['eigenvalues'])
            check(f'{tag}: the axes\' shares of the variance, the title', (ax['xlabel'], ax['ylabel'], ax['title']),
                  (f'Prin1 ({100 * ev_k[0] / np.maximum(ev_k, 0).sum():.1f}%)', f'Prin2 ({100 * ev_k[1] / np.maximum(ev_k, 0).sum():.1f}%)', f'Biplot, {f_["k"]} clusters'))
        F = figure(f'{tag}: parallel coordinates', f_['parallel_code'], tq)
        ax = F['axes'][0]
        mu_, sd_ = np.array(km_['mean']), np.array(km_['sd'])
        means_ = arr(f_['means']).reshape(f_['k'], 3)
        check(f'{tag}: each cluster\'s standardized mean', all(has_line(ax, [0, 1, 2], list((means_[c_] - mu_) / sd_), rel=1e-9, marker='o', label=f'Cluster {c_ + 1}') for c_ in range(f_['k'])), True)
        check(f'{tag}: a line for each row, in its cluster\'s set', [len(s_['segs']) for s_ in ax['segments']], [int((lab_ == c_).sum()) for c_ in range(f_['k'])])
        check(f'{tag}: the columns on the axis', [t_ for t_ in ax['xticklabels'] if t_], ['u', 'v', 'a'])

# ---- Test Many Responses ------------------------------------------------------------------------------------------------------------
for label, kw in (('', {}), (' (Freq)', {'freq': 'f'}), (' (Weight, rows left out)', {'weight': 'w', 'rows': all_rows})):
    rs_ = call('respscreen.fit', table=tq, y=['a', 'b', 'q1', 'yb', 'q3'], x=['c', 'q1', 'd', 'q3'], **kw)
    R_ = rs_['results']
    good = [x_ for x_ in R_ if x_['p'] is not None]
    F = figure(f'FDR PValue Plot{label}', rs_['fdr_code'], tq)
    ax = F['axes'][0]
    byr = sorted(good, key=lambda x_: x_['rank_fraction'])
    check.near(f'FDR PValue Plot{label}: the p-values by rank fraction', gap(pts(ax, 0), [[x_['rank_fraction'], max(x_['p'], 1e-300)] for x_ in byr]), 0.0, abs_=1e-12)
    check.near(f'FDR PValue Plot{label}: the FDR p-values', gap(pts(ax, 1), [[x_['rank_fraction'], max(x_['fdr_p'], 1e-300)] for x_ in byr]), 0.0, abs_=1e-12)
    qs_ = [max(1e-3, q_ / 50) for q_ in range(51)]
    check(f'FDR PValue Plot{label}: the α line and the FDR threshold α × rank fraction', (has_line(ax, [0, 1], [0.05, 0.05]), has_line(ax, qs_, [0.05 * q_ for q_ in qs_], ls=':')), (True, True))
    check(f'FDR PValue Plot{label}: a log axis, the legend', (ax['yscale'], ax['legend']), ('log', ['PValue', 'FDR PValue', 'α = 0.05', 'FDR threshold for p']))
    F = figure(f'FDR LogWorth by Effect Size{label}', rs_['effect_code'], tq)
    ax = F['axes'][0]
    check.near(f'FDR LogWorth by Effect Size{label}: the tests', gap(pts(ax), [[x_['effect'], x_['fdr_logworth']] for x_ in good]), 0.0, abs_=1e-9)
    check(f'FDR LogWorth by Effect Size{label}: red where significant', [c_[:7] for c_ in ax['scatter'][0]['colors']], ['#c0392b' if x_['fdr_p'] < 0.05 else '#786b5d' for x_ in good])
    F = figure(f'FDR LogWorth by RSquare{label}', rs_['r2_code'], tq)
    ax = F['axes'][0]
    check.near(f'FDR LogWorth by RSquare{label}: the continuous responses\' tests', gap(pts(ax), [[x_['r2'], x_['fdr_logworth']] for x_ in good if x_['r2'] is not None]), 0.0, abs_=1e-9)

# ---- Explore Outliers ---------------------------------------------------------------------------------------------------------------------
mo_ = call('outliers.multivariate', table=tq, columns=['a', 'c', 'd'], rows=grp_rows, where=where_hi, alpha=0.1)
F = figure('Multivariate Robust Outliers: robust distances by row', mo_['robust_code'], tq)
ax = F['axes'][0]
check.near('robust distances by row: the report\'s robust distances (the same FAST-MCD, seed and reweighting)', max(gap(pts(ax)[:, 0], np.array(mo_['rows']) + 1), gap(pts(ax)[:, 1], mo_['robust'])), 0.0, abs_=1e-9)
check('robust distances by row: the limit and its label', (has_line(ax, None, [mo_['limit']] * 2, ls='--'), texts(ax)), (True, [f'√χ²(0.9, 3) {mo_["limit"]:.5g}']))
keeps('robust distances by row', mo_['robust_code'], WHERE_HI, grp_drop)
F = figure('Multivariate Robust Outliers: distance-distance plot', mo_['dd_code'], tq)
ax = F['axes'][0]
check.near('distance-distance plot: classical against robust', gap(pts(ax), np.column_stack([mo_['classical'], mo_['robust']])), 0.0, abs_=1e-9)
check('distance-distance plot: the limit on both axes', (has_line(ax, None, [mo_['limit']] * 2, ls='--'), has_line(ax, [mo_['limit']] * 2, None, ls='--')), (True, True))
bigo = np.random.default_rng(31).normal(size=(1600, 2)) @ np.array([[1, 0.6], [0, 0.8]])
bigo[:20] += 4
tbo = table({'p1': bigo[:, 0], 'p2': bigo[:, 1]})
mb_ = call('outliers.multivariate', table=tbo, columns=['p1', 'p2'])
F = figure('robust distances of 1600 rows (FAST-MCD on a subsample)', mb_['robust_code'], tbo)
check.near('robust distances of 1600 rows: the report\'s', gap(pts(F['axes'][0])[:, 1], mb_['robust']), 0.0, abs_=1e-9)
ko_ = call('outliers.knn', table=tq, columns=['a', 'c', 'd'], rows=all_rows, k=5)
check('k nearest neighbours: a graph\'s code for each k', [x_['k'] for x_ in ko_['plots']], ko_['ks'])
for x_ in ko_['plots']:
    F = figure(f'k = {x_["k"]}', x_['plot_code'], tq)
    ax = F['axes'][0]
    check.near(f'k = {x_["k"]}: the distance of each row to its neighbour', gap(pts(ax), np.column_stack([np.array(ko_['rows']) + 1, ko_['dist'][str(x_['k'])]])), 0.0, abs_=1e-12)
    check(f'k = {x_["k"]}: the titles', (ax['ylabel'], ax['title']), (f'Distance to neighbor {x_["k"]}', f'k = {x_["k"]}'))

# ---- Multiple Correspondence Analysis, Multidimensional Scaling -----------------------------------------------------------------------------
for label, kw, pl in (('c1 by c2', {}, {'x': 0, 'y': 1}), ('c3 by c2, Freq, a By group', {'freq': 'f', 'rows': grp_rows, 'where': where_hi}, {'x': 2, 'y': 1})):
    mc_ = call('mca.fit', table=tq, columns=['q1', 'q2', 'q3'], plot=pl, **kw)
    K_ = mc_['K']
    a_, b_ = min(pl['x'], K_ - 1), min(pl['y'], K_ - 1)
    F = figure(f'MCA ({label}): correspondence analysis', mc_['plot_code'], tq)
    ax = F['axes'][0]
    for i, c_ in enumerate(['q1', 'q2', 'q3']):
        L_ = [lv for lv in mc_['levels'] if lv['column'] == c_]
        check.near(f'MCA ({label}): the levels of {c_} in principal coordinates', gap(pts(ax, i), [[lv['coords'][a_], lv['coords'][b_]] for lv in L_]), 0.0, abs_=1e-12)
    want_t = [str(int(lv['level'])) if isinstance(lv['level'], float) else str(lv['level']) for lv in mc_['levels']]
    check(f'MCA ({label}): the levels named, the columns in the legend', (texts(ax), ax['legend']), (want_t, ['q1', 'q2', 'q3']))
    check(f'MCA ({label}): the axes\' shares of the inertia', (ax['xlabel'], ax['ylabel']), (f'c{a_ + 1} ({mc_["percent"][a_]:.1f}%)', f'c{b_ + 1} ({mc_["percent"][b_]:.1f}%)'))
    F = figure(f'MCA ({label}): row plot', mc_['rows_code'], tq)
    Fr = arr(mc_['row_coords']).reshape(len(mc_['rows']), -1)
    check.near(f'MCA ({label}): the rows in principal coordinates', gap(pts(F['axes'][0]), Fr[:, [min(a_, Fr.shape[1] - 1), min(b_, Fr.shape[1] - 1)]]), 0.0, abs_=1e-12)
    if 'where' in kw:
        keeps(f'MCA ({label})', mc_['plot_code'], WHERE_HI, grp_drop)
for label, kw, tbl_ in (('standardized, labels', {'label': 'id', 'rows': grp_rows, 'where': where_hi}, tq), ('in their units', {'standardize': False}, tq)):
    md_ = call('mds.fit', table=tbl_, columns=['a', 'c', 'd', 'e'], **kw)
    F = figure(f'MDS ({label}): the map', md_['plot_code'], tbl_)
    ax = F['axes'][0]
    X_ = arr(md_['coords']).reshape(md_['n'], -1)
    check.near(f'MDS ({label}): the objects\' coordinates', gap(pts(ax), X_[:, :2]), 0.0, abs_=1e-9)
    check(f'MDS ({label}): the objects named (up to 60)', texts(ax), ([f'R{r + 1}' for r in md_['rows']] if 'label' in kw else [str(r + 1) for r in md_['rows']]) if md_['n'] <= 60 else [])
    F = figure(f'MDS ({label}): the Shepard diagram', md_['shepard_code'], tbl_)
    ax = F['axes'][0]
    check.near(f'MDS ({label}): each pair\'s distance in the data and in the map', gap(pts(ax), np.column_stack([md_['shepard']['d'], md_['shepard']['dhat']])), 0.0, abs_=1e-9)
    mx_ = max(max(md_['shepard']['d']), max(md_['shepard']['dhat']))
    check(f'MDS ({label}): the line on which the map is exact', has_line(ax, [0, mx_], [0, mx_], rel=1e-12), True)
    if 'where' in kw:
        keeps(f'MDS ({label})', md_['plot_code'], WHERE_HI, grp_drop)
pbig = np.random.default_rng(33).normal(size=(95, 3))
tbm = table({'x1': pbig[:, 0], 'x2': pbig[:, 1], 'x3': pbig[:, 2]})
md_ = call('mds.fit', table=tbm, columns=['x1', 'x2', 'x3'])
F = figure('MDS of 95 objects: the Shepard diagram of a sample of 3000 pairs', md_['shepard_code'], tbm)
check.near('MDS of 95 objects: the sampled pairs are the report\'s', gap(pts(F['axes'][0]), np.column_stack([md_['shepard']['d'], md_['shepard']['dhat']])), 0.0, abs_=1e-9)
Dm2 = np.sqrt(((pbig[:12, None, :2] - pbig[None, :12, :2]) ** 2).sum(2))
tdm2 = table({f'd{j}': Dm2[:, j] for j in range(12)})
mm2 = call('mds.fit', table=tdm2, columns=[f'd{j}' for j in range(12)], matrix=True)
F = figure('MDS of a distance matrix: the map', mm2['plot_code'], tdm2)
check.near('MDS of a distance matrix: the coordinates', gap(pts(F['axes'][0]), arr(mm2['coords']).reshape(12, -1)[:, :2]), 0.0, abs_=1e-9)

# ---- the statistics' code leaves out the rows the report leaves out --------------------------------------------------------------------------
# A By group (g = hi) with rows excluded: every result's code keeps the group
# and drops those rows, and run on the whole table's CSV gives the report's numbers.
def ns_of(res, label):
    here_ = os.getcwd()
    export(tq).to_csv(os.path.join(_tmp, 'data.csv'), index=False)
    os.chdir(_tmp)
    ns_ = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            exec(compile(res['code'], label, 'exec'), ns_)
        err_ = None
    except Exception as ex:  # reported as a failed check
        err_ = f'{type(ex).__name__}: {ex}'
    finally:
        os.chdir(here_)
    check(f'{label}: the code runs on the whole table\'s CSV', err_, None)
    keeps(label, res['code'], WHERE_HI, grp_drop)
    return ns_


G = dict(rows=grp_rows, where=where_hi)
X4 = ['a', 'c', 'd', 'e']
Xg = pd.DataFrame(Xq, columns=colsq).loc[grp_rows, X4].dropna()
r_ = call('multivariate.fit', table=tq, columns=X4, **G)
ns = ns_of(r_, 'the correlations of a By group')
check.near('... its correlations are the report\'s', gap(np.asarray(ns.get('R', np.zeros((4, 4)))), arr(r_['corr']).reshape(4, 4)), 0.0, abs_=1e-12)
check('... on the group\'s rows', len(ns.get('Xc', [])), len(Xg))
r_ = call('multivariate.nonparametric', table=tq, columns=X4, measure='spearman', **G)
ns = ns_of(r_, 'Spearman\'s ρ of a By group')
check.near('... ρ of the first pair is the report\'s', float(stats.spearmanr(ns.get('x', [0, 1, 2]), ns.get('y', [0, 1, 2])).statistic), r_['pairs'][0]['value'], rel=1e-12)
r_ = call('multivariate.distance', table=tq, columns=['a', 'c'], **G)
ns = ns_of(r_, 'the distance correlation of a By group')
check.near('... dCor is the report\'s', float(distance_statistics(ns.get('x', np.zeros(4)), ns.get('y', np.zeros(4))).distance_correlation), r_['pairs'][0]['dcor'], rel=1e-12)
r_ = call('multivariate.outliers', table=tq, columns=X4, **G)
ns = ns_of(r_, 'the outlier distances of a By group')
check.near('... T² is the report\'s', gap(ns.get('M2', []), r_['t2']), 0.0, abs_=1e-9)
r_ = call('multivariate.reliability', table=tq, columns=X4, **G)
ns = ns_of(r_, 'Cronbach\'s α of a By group')
check.near('... α is the report\'s', float(ns['k'] * ns['c'] / (ns['v'] + (ns['k'] - 1) * ns['c'])) if 'c' in ns else None, r_['alpha'], rel=1e-12)
r_ = call('multivariate.icc', table=tq, columns=X4, **G)
ns = ns_of(r_, 'the intraclass correlations of a By group')
check.near('... ICC(C,1) is the report\'s', float(ns.get('icc', {}).get('ICC(C,1)', 0)), {x_['form']: x_ for x_ in r_['icc']}['ICC(C,1)']['icc'], rel=1e-12)
r_ = call('multivariate.kendall_w', table=tq, columns=X4, **G)
ns = ns_of(r_, 'Kendall\'s W of a By group')
check.near('... W is the report\'s', float(ns.get('W', 0)), r_['w'], rel=1e-12)
r_ = call('pca.fit', table=tq, columns=X4, **G)
ns = ns_of(r_, 'principal components of a By group')
check.near('... the eigenvalues are the report\'s', gap(np.asarray(ns.get('eig', [])), r_['eigenvalues']), 0.0, abs_=1e-12)
r_ = call('factor.eigen', table=tq, columns=X4, **G)
ns = ns_of(r_, 'the factor analysis eigenvalues of a By group')
check.near('... the eigenvalues are the report\'s', gap(ns.get('ev', []), r_['eigen']['values']), 0.0, abs_=1e-12)
r_ = call('factor.fit', table=tq, columns=['a', 'b', 'c', 'd', 'e'], n_factors=1, method='pa', rotation=None, **G)
ns = ns_of(r_, 'a factor fit of a By group')
check.near('... the communalities are the report\'s', gap(np.asarray(ns['res'].communality) if 'res' in ns else [], r_['communality']), 0.0, abs_=1e-6)
r_ = call('discriminant.fit', table=tq, y=['a', 'c'], x='q2', **G)
ns = ns_of(r_, 'a discriminant analysis of a By group')
check.near('... the posterior probabilities are the report\'s (linear, equal priors; the groups in either order)', gap(np.sort(np.asarray(ns.get('P', np.zeros((1, 1)))), axis=1), np.sort(arr(r_['prob']).reshape(len(r_['rows']), -1), axis=1)), 0.0, abs_=1e-9)
r_ = call('hcluster.fit', table=tq, columns=['u', 'v'], **G)
ns = ns_of(r_, 'a hierarchical clustering of a By group')
check('... the joins are the report\'s', np.asarray(ns['Z'])[:, :2].astype(int).tolist() if 'Z' in ns else None, r_['merges'])
r_ = call('kmeans.fit', table=tq, columns=['u', 'v'], k_min=3, **G)
ns = ns_of(r_, 'k-means of a By group')
check('... on the group\'s rows', len(ns.get('X', [])), len(r_['rows']))
r_ = call('respscreen.fit', table=tq, y=['a', 'q1'], x=['c', 'q2'], **G)
ns = ns_of(r_, 'test many responses of a By group')
check.near('... the p-values are the report\'s', gap(ns['res']['PValue'] if 'res' in ns else [], [x_['p'] for x_ in r_['results']]), 0.0, abs_=1e-12)
for fn_, extra in (('outliers.quantile', {}), ('outliers.robust', {})):
    r_ = call(fn_, table=tq, columns=['a', 'c'], **G, **extra)
    ns = ns_of(r_, f'{fn_} of a By group')
    check(f'... {fn_}: the rows of the group', len(ns.get('v', [])), int(np.isfinite(Xq[grp_rows, 2]).sum()))
r_ = call('outliers.multivariate', table=tq, columns=['a', 'c'], **G)
ns = ns_of(r_, 'the classical distances of Multivariate Robust Outliers, a By group')
check.near('... the classical distances are the report\'s', gap(ns.get('md', []), r_['classical']), 0.0, abs_=1e-9)
r_ = call('outliers.knn', table=tq, columns=['a', 'c'], k=3, **G)
ns = ns_of(r_, 'the k nearest neighbours of a By group')
check('... on the group\'s rows', len(ns.get('X', [])), len(r_['rows']))
r_ = call('mca.fit', table=tq, columns=['q1', 'q2'], **G)
ns = ns_of(r_, 'multiple correspondence analysis of a By group')
check.near('... the inertias are the report\'s', gap(ns.get('inertia', []), r_['inertia']), 0.0, abs_=1e-12)
r_ = call('mds.fit', table=tq, columns=X4, **G)
ns = ns_of(r_, 'multidimensional scaling of a By group')
check.near('... the eigenvalues are the report\'s', gap(np.asarray(ns.get('ev', []))[:len(r_['eigenvalues'])], r_['eigenvalues']), 0.0, abs_=1e-9)


# ---- the statistics' code of Discriminant, K Means, Test Many Responses, Factor Analysis and Hierarchical Cluster -----------
# Each result's code, run on the whole table's CSV, gives the report's numbers:
# the report's method, priors, weights and order of the categories; its own
# seeded k-means with the restarts; the tests with Weight and Freq; the
# weighted correlations and the report's rotation with its normalization; the
# clusters at the report's number, or at the page's default.
def run_code(label, code, tid):
    here_ = os.getcwd()
    export(tid).to_csv(os.path.join(_tmp, 'data.csv'), index=False)
    os.chdir(_tmp)
    ns_ = {}
    try:
        with contextlib.redirect_stdout(io.StringIO()), warnings.catch_warnings():
            warnings.simplefilter('ignore')
            exec(compile(code, label, 'exec'), ns_)
        err_ = None
    except Exception as ex:  # reported as a failed check
        import traceback
        err_ = f'{type(ex).__name__}: {ex} {traceback.format_exc(limit=-2)}'
    finally:
        os.chdir(here_)
    check(f'{label}: the code runs on the whole table\'s CSV', err_, None)
    return ns_ if err_ is None else None


def val(ns_, key, dflt=None):
    return ns_.get(key, dflt) if ns_ else dflt


# Discriminant: every method, the priors, the weights, the table's order of the categories, a By group
for label, kw in (('linear, equal priors', {'y': ['a', 'c', 'd', 'e'], 'x': 'g'}),
                  ('quadratic, Freq', {'y': ['a', 'c', 'd'], 'x': 'g', 'method': 'quadratic', 'freq': 'f'}),
                  ('regularized, proportional priors, Weight', {'y': ['a', 'c', 'd', 'e'], 'x': 'g', 'method': 'regularized', 'lam': 0.3, 'gam': 0.2, 'priors': 'proportional', 'weight': 'w'}),
                  ('two groups, priors given, Weight and Freq', {'y': ['a', 'c'], 'x': 'yb', 'priors': 'other', 'prior_values': {'no': 1, 'yes': 3}, 'weight': 'w', 'freq': 'f'}),
                  ('the categories of a nominal number, a By group with excluded rows', {'y': ['a', 'c'], 'x': 'q3', 'rows': grp_rows, 'where': where_hi})):
    r_ = call('discriminant.fit', table=tq, **kw)
    tag = f'discriminant.fit\'s code ({label})'
    ns = run_code(tag, r_['code'], tq)
    if not ns:
        continue
    check(tag + ': the categories in the table\'s order', [str(int(v)) if isinstance(v, float) else str(v) for v in ns['levels']], [str(int(v)) if isinstance(v, float) else str(v) for v in r_['levels']])
    check.near(tag + ': the posterior probabilities are the report\'s', gap(ns['P'], r_['prob']), 0.0, abs_=1e-9)
    check.near(tag + ': the squared distances (SqDist)', gap(ns['SqDist'], r_['sqdist']), 0.0, abs_=1e-9)
    check.near(tag + ': the confusion matrix', gap(ns['conf'], r_['confusion']), 0.0, abs_=1e-9)
    S_ = r_['summary']
    got_ = [float(ns['w'][ns['mis']].sum()), float(100 * ns['w'][ns['mis']].sum() / ns['w'].sum()), float(1 - ns['ll'] / ns['ll0']), float(-2 * ns['ll'])]
    check.near(tag + ': the Score Summaries: misclassified, percent, entropy RSquare, −2LogLikelihood', gap(got_, [S_['n_mis'], S_['pct_mis'], S_['entropy_r2'], S_['m2ll']]), 0.0, abs_=1e-9)
    check.near(tag + ': the canonical correlations', gap(ns['cancorr'], r_['canonical']['cancorr']), 0.0, abs_=1e-9)
    names_ = {"Wilks' lambda": "Wilks' Lambda", "Pillai's trace": "Pillai's Trace", 'Hotelling-Lawley trace': 'Hotelling-Lawley', "Roy's greatest root": "Roy's Max Root"}
    tst = ns['tests']
    got_ = [[float(tst.loc[k_, c_]) for c_ in ('Value', 'F Value', 'Num DF', 'Den DF', 'Pr > F')] for k_ in names_]
    want_ = [[x_[c_] for c_ in ('value', 'F', 'numdf', 'dendf', 'p')] for x_ in r_['tests']]
    check.near(tag + ': the multivariate tests (Wilks, Pillai, Hotelling-Lawley, Roy)', gap(got_, want_), 0.0, abs_=1e-9)
    if kw.get('method') in (None, 'linear') and kw.get('priors') in (None, 'equal') and not kw.get('weight') and not kw.get('freq'):
        continue
    check(tag + ': says which method and priors', ({'quadratic': 'quadratic:', 'regularized': 'regularized:'}.get(kw.get('method'), 'linear:') in r_['code'],
                                                   {'proportional': 'proportional to occurrence', 'other': 'the priors given'}.get(kw.get('priors'), 'equal probabilities') in r_['code']), (True, True))

# K Means: the report's own k-means (seeded k-means++ starts, Lloyd, the best of the restarts) over a range of k
for label, kw in (('2 to 5 clusters, in their units', {'columns': ['u', 'v', 'a'], 'k_min': 2, 'k_max': 5, 'standardize': False}),
                  ('3 clusters, scaled, Freq', {'columns': ['u', 'v', 'a'], 'k_min': 3, 'freq': 'f'}),
                  ('2 to 4 clusters, Weight, 4 restarts, another seed', {'columns': ['u', 'v'], 'k_min': 2, 'k_max': 4, 'weight': 'w', 'restarts': 4, 'seed': 7}),
                  ('a By group with excluded rows', {'columns': ['u', 'v', 'c'], 'k_min': 2, 'k_max': 3, 'rows': grp_rows, 'where': where_hi})):
    r_ = call('kmeans.fit', table=tq, **kw)
    tag = f'kmeans.fit\'s code ({label})'
    ns = run_code(tag, r_['code'], tq)
    if not ns:
        continue
    check(tag + ': the report\'s own k-means, not scipy\'s single start', ('kmeans2' in r_['code'], f'default_rng({r_["seed"]})' in r_['code']), (False, True))
    comp = {c_['NCluster']: c_ for c_ in ns['comparison']}
    for f_ in r_['fits']:
        k_ = f_['k']
        check(tag + f': k = {k_}: each row\'s cluster is the report\'s', ns['fits'][k_].tolist() if k_ in ns['fits'] else None, f_['labels'])
        c_ = comp.get(k_, {})
        check.near(tag + f': k = {k_}: the Cluster Comparison (CCC, pseudo F, RSquare, within SS)', gap([c_.get('CCC'), c_.get('Pseudo F'), c_.get('RSquare'), c_.get('Within SS')],
                                                                                                        [f_['ccc'], f_['pseudo_f'], f_['r2'], f_['wss']]), 0.0, abs_=1e-9)
        check(tag + f': k = {k_}: the steps and the criterion', (c_.get('Step'), close(c_.get('Criterion'), f_['criterion'], 1e-9, 1e-15)), (f_['iterations'], True))
    lab_ = ns['fits'][r_['fits'][-1]['k']]
    w_, X0_ = ns['w'], ns['X0']
    kk_ = r_['fits'][-1]['k']
    means_ = [(w_[lab_ == c_, None] * X0_[lab_ == c_]).sum(0) / w_[lab_ == c_].sum() for c_ in range(kk_)]
    check.near(tag + ': the last fit\'s Cluster Means', gap(means_, r_['fits'][-1]['means']), 0.0, abs_=1e-9)

# Test Many Responses: every test with Weight and Freq as the report uses them
for label, kw in (('', {}), (' (Freq)', {'freq': 'f'}), (' (Weight)', {'weight': 'w'}), (' (Weight and Freq, rows excluded)', {'weight': 'w', 'freq': 'f', 'rows': all_rows}),
                  (' (a By group)', {'rows': grp_rows, 'where': where_hi})):
    r_ = call('respscreen.fit', table=tq, y=['a', 'b', 'q1', 'yb', 'q3'], x=['c', 'q1', 'd', 'q3'], **kw)
    tag = f'respscreen.fit\'s code{label}'
    ns = run_code(tag, r_['code'], tq)
    if not ns:
        continue
    res_ = ns['res']
    R_ = r_['results']
    check(tag + ': a line for each pair, in the report\'s order', list(zip(res_['Y'], res_['X'])), [(x_['y'], x_['x']) for x_ in R_])
    for col_, key_ in (('PValue', 'p'), ('FDR_PValue', 'fdr_p'), ('LogWorth', 'logworth'), ('FDR_LogWorth', 'fdr_logworth'), ('Effect_Size', 'effect'), ('Rank_Fraction', 'rank_fraction'),
                       ('RSquare', 'r2'), ('Count', 'count'), ('Statistic', 'stat'), ('DF', 'df')):
        check.near(tag + f': its {col_} are the report\'s', gap(res_[col_], [x_[key_] for x_ in R_]), 0.0, abs_=1e-9)
    check(tag + ': the tests named as the report names them', [None if t_ is None else t_ for t_ in res_['Test']], [x_['test'] for x_ in R_])
    if kw.get('weight') or kw.get('freq'):
        check(tag + ': Weight and Freq as frequency weights', 'frequency weights' in r_['code'], True)

# Factor Analysis: the weighted correlations, the report's rotation with Kaiser's normalization (or without it)
for label, kw in (('ML, varimax', {'n_factors': 2, 'method': 'ml', 'rotation': 'varimax'}),
                  ('ML, varimax without Kaiser\'s normalization', {'n_factors': 2, 'method': 'ml', 'rotation': 'varimax', 'kaiser': False}),
                  ('principal axis, promax, Freq, 3 factors', {'n_factors': 3, 'method': 'pa', 'rotation': 'promax', 'freq': 'f'}),
                  ('ML, quartimin, Weight', {'n_factors': 2, 'method': 'ml', 'rotation': 'quartimin', 'weight': 'w'}),
                  ('ML, the default number, oblimin γ 0.3, Weight and Freq', {'n_factors': None, 'method': 'ml', 'rotation': 'oblimin', 'gamma': 0.3, 'weight': 'w', 'freq': 'f'}),
                  ('principal axis, equamax, prior 1', {'n_factors': 2, 'method': 'pa', 'prior': 'pc', 'rotation': 'equamax'}),
                  ('ML, no rotation, a By group', {'n_factors': 1, 'method': 'ml', 'rotation': None, 'rows': grp_rows, 'where': where_hi})):
    r_ = call('factor.fit', table=tq, columns=['a', 'b', 'c', 'd', 'e'], **kw)
    tag = f'factor.fit\'s code ({label})'
    ns = run_code(tag, r_['code'], tq)
    if not ns:
        continue
    kk_ = r_['k']
    check(tag + ': the number of factors', int(ns['k']), kk_)
    check.near(tag + ': the (rotated) loadings are the report\'s', gap(ns['L'], r_['rotated']), 0.0, abs_=1e-9)
    check.near(tag + ': the rotation matrix', gap(ns['T'], r_['rotation_matrix']), 0.0, abs_=1e-9)
    check.near(tag + ': the communalities and uniquenesses', max(gap(ns['comm'], r_['communality']), gap(ns['uniq'], r_['uniqueness'])), 0.0, abs_=1e-9)
    check.near(tag + ': the variance explained by each factor', gap(ns['variance'], [v_['variance'] for v_ in r_['variance']]), 0.0, abs_=1e-9)
    if r_.get('oblique'):
        check.near(tag + ': the factors\' correlations', gap(ns['Phi'], r_['phi']), 0.0, abs_=1e-9)
    if kw['method'] == 'ml':
        t_ = r_['ml_test']
        check.near(tag + ': the test that the factors are enough (Bartlett\'s chi-square, DF)', gap([ns['chi2'], ns['dfm']], [t_['chi2'], t_['df']]), 0.0, abs_=1e-9)
    check.near(tag + ': the factor scores (Save Rotated Components)', gap(ns['scores'], r_['scores']), 0.0, abs_=1e-9)
    if kw.get('rotation') and kk_ > 1:
        check(tag + ': Kaiser\'s normalization when the report uses it', ("Kaiser's normalization" in r_['code']), kw.get('kaiser', True))

# Hierarchical Cluster: the clusters at the report's number of clusters, or the page's default


def page_clusters(merges, n, k, order):
    """The page's clustersAt (smui-p-multivariate.js), written again here: the
    union of the first n - k joins, the clusters numbered in the order of the leaves."""
    root = list(range(2 * n - 1))

    def find(i):
        while root[i] != i:
            root[i] = root[root[i]]
            i = root[i]
        return i
    for s_ in range(n - k):
        a_, b_ = merges[s_]
        root[find(a_)] = n + s_
        root[find(b_)] = n + s_
    lab, num = [0] * n, {}
    for leaf in order:
        r0 = find(leaf)
        num.setdefault(r0, len(num))
        lab[leaf] = num[r0]
    return lab


def page_default(heights, n):
    """The page's defaultClusters, written again here."""
    best, ratio = min(3, n), -math.inf
    for q_ in range(2, min(10, n - 1) + 1):
        up, down = heights[n - q_], heights[n - q_ - 1]
        rr = up / down if down > 0 else (math.inf if up > 0 else 0)
        if rr > ratio:
            best, ratio = q_, rr
    return best


for label, kw in (('Ward, unstandardized, 4 clusters chosen', {'method': 'ward', 'standardize': 'none', 'n_clusters': 4}),
                  ('average, the page\'s default', {'method': 'average'}),
                  ('centroid, rows standardized, 2 clusters', {'method': 'centroid', 'standardize': 'rows', 'n_clusters': 2}),
                  ('single, the default, the rows named', {'method': 'single', 'label': 'id'}),
                  ('complete, 7 clusters, a By group with excluded rows', {'method': 'complete', 'n_clusters': 7, 'rows': grp_rows, 'where': where_hi})):
    r_ = call('hcluster.fit', table=tq, columns=['u', 'v', 'a'], **kw)
    tag = f'hcluster.fit\'s code ({label})'
    ns = run_code(tag, r_['code'], tq)
    if not ns:
        continue
    n_ = r_['n']
    kk_ = kw.get('n_clusters') or page_default(r_['heights'], n_)
    check(tag + f': the number of clusters: {"the report\'s" if kw.get("n_clusters") else "the page\'s default"}', int(ns['k']), kk_)
    want_ = [c_ + 1 for c_ in page_clusters(r_['merges'], n_, kk_, r_['order'])]
    check(tag + ': each row\'s cluster, as the page numbers them (Save Clusters)', ns['cluster'].tolist(), want_)
    Xc_ = export(tq).loc[r_['rows'], ['u', 'v', 'a']]
    check.near(tag + ': the Cluster Means', gap(ns['X'].groupby(ns['cluster']).mean().to_numpy(), Xc_.groupby(want_).mean().to_numpy()), 0.0, abs_=1e-12)
    check.near(tag + ': the Clustering History\'s distances', gap([h_[1] for h_ in ns['history']], r_['heights']), 0.0, abs_=1e-12)
    rep_ = list(range(n_)) + [0] * (n_ - 1)
    lj = []
    for s_, (a_, b_) in enumerate(r_['merges']):
        lead, join = sorted((rep_[a_], rep_[b_]))
        rep_[n_ + s_] = lead
        lj.append((lead, join))
    names_ = [f'R{r0 + 1}' if kw.get('label') else str(r0 + 1) for r0 in r_['rows']]
    check(tag + ': the leaders and joiners', [(h_[2], h_[3]) for h_ in ns['history']], [(names_[a_], names_[b_]) for a_, b_ in lj])
    check(tag + ': the graphs\' code at the same number of clusters', all(f'k = {kk_}   #' in r_[k2] for k2 in ('dendro_code', 'distgraph_code')) if kw.get('n_clusters') else all("k = None   # Number of Clusters: None takes the report's default" in r_[k2] for k2 in ('code', 'dendro_code', 'distgraph_code')), True)


# ======================================================================================================================
# Saved columns for every row, and live formulas (Save Principal Components, Save Rotated Components, K Means'
# Save Clusters, Cluster Formula and Distance Formulas, Hierarchical Cluster's Save Formula for Closest Cluster,
# Discriminant's Save Formulas and Save Canonical Scores)
# ======================================================================================================================
# A formula is evaluated by the page's own formula language (smui-formula.js, in node, as test-formula.js runs it) on
# the whole table: every row whose columns are present gets a value, excluded rows and the other By groups' rows
# included (the other groups: missing, for their fits are their own). The numbers are checked against the reports'
# own scores on their rows and against numpy by another route on the others.
import shutil as _shutil  # noqa: E402
import subprocess as _sp  # noqa: E402

_NODE = _shutil.which('node')
_FORMULA_JS = r'''
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
  out.push({ name: c.name, values: Array.from(c.values, (v) => (typeof v === 'number' && !Number.isFinite(v) ? null : v)), type: c.dataType });
}
process.stdout.write(JSON.stringify(out));
'''


def formula_values(tid, saved):
    """The saved formulas (in order, {{col:j}} naming the j-th of them) computed by the page's formula language on
    every row of the table: a list of {'name', 'values'} (None for missing), or None without node."""
    if not _NODE:
        return None
    t = data.TABLES[tid]
    cols = []
    for name, v in t['cols'].items():
        char = t['meta'][name].get('dataType') != 'numeric'
        cols.append({'name': name, 'char': char, 'values': [None if x is None or (not char and not np.isfinite(x)) else (str(x) if char else float(x)) for x in v]})
    d = _tempfile.mkdtemp(prefix='smui-mv-formula-')
    js, sp_ = os.path.join(d, 'f.js'), os.path.join(d, 's.json')
    with open(js, 'w') as fh:
        fh.write(_FORMULA_JS)
    with open(sp_, 'w') as fh:
        json.dump({'js': os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'js')), 'columns': cols,
                   'saved': [{'name': c['name'], 'formula': c['formula']} for c in saved]}, fh)
    r_ = _sp.run([_NODE, js, sp_], capture_output=True, text=True, timeout=300)
    if r_.returncode:
        raise RuntimeError(r_.stderr)
    return json.loads(r_.stdout)


def fvals(res, j):
    """The j-th formula's values as floats (NaN for missing)."""
    return np.array([np.nan if v is None else v for v in res[j]['values']], dtype=float)


import json  # noqa: E402

if not _NODE:
    print('note: node is not installed; the formula checks are skipped')
Xall = export(tq)
cq = ['a', 'b', 'c', 'd', 'e']
present_all = np.isfinite(Xall[cq].to_numpy(float)).all(1)
hi_all = np.array([g_ == 'hi' for g_ in gq])

# ---- Principal Components: Save Principal Components and Save Rotated Components as formulas -----------------
for on in ('correlations', 'covariances', 'unscaled'):
    for label, kw in (('every group, rows excluded', {'rows': all_rows}), ('the By group hi, rows excluded, Weight', {'rows': grp_rows, 'where': where_hi, 'weight': 'w'})):
        tag = f'Save Principal Components ({on}, {label})'
        fit_ = call('pca.fit', table=tq, columns=cq, on=on, **kw)
        sv = call('pca.save', table=tq, columns=cq, on=on, n=3, **kw)
        check(f'{tag}: three formula columns Prin1 to Prin3', [c_['name'] for c_ in sv['columns']], ['Prin1', 'Prin2', 'Prin3'])
        fr_ = formula_values(tq, sv['columns'])
        if fr_ is None:
            continue
        F = np.column_stack([fvals(fr_, j) for j in range(3)])
        S_ = arr(fit_['scores']).reshape(len(fit_['rows']), -1)[:, :3]
        check.near(f'{tag}: the formulas give the report\'s scores on its rows', gap(F[fit_['rows']], S_), 0.0, abs_=1e-10)
        # every other row of the group whose columns are present: the fitted means, scale and eigenvectors by numpy
        grp_ = hi_all if kw.get('where') else np.ones(nq, dtype=bool)
        others = [i for i in range(nq) if grp_[i] and present_all[i] and i not in fit_['rows']]
        Z_ = (Xall.loc[others, cq].to_numpy(float) - np.array(fit_['center'])) / np.array(fit_['scale'])
        check.near(f'{tag}: the excluded rows scored by the same fit', gap(F[others], Z_ @ arr(fit_['eigenvectors']).reshape(5, -1)[:, :3]), 0.0, abs_=1e-10)
        check(f'{tag}: {len(others)} excluded rows scored', len(others) > 0 and bool(np.isfinite(F[others]).all()), True)
        check(f'{tag}: the row with a missing value has none', bool(np.isnan(F[7]).all()), True)
        if kw.get('where'):
            check(f'{tag}: the other groups\' rows have none (their fits are their own)', bool(np.isnan(F[~hi_all]).all()), True)
rot_ = {'rotation': 'varimax', 'n_rotate': 2}
fit_ = call('pca.fit', table=tq, columns=cq, rows=all_rows, **rot_)
sv = call('pca.save', table=tq, columns=cq, rows=all_rows, what='rotated', **rot_)
fr_ = formula_values(tq, sv['columns'])
if fr_ is not None:
    F = np.column_stack([fvals(fr_, j) for j in range(2)])
    check.near('Save Rotated Components (varimax, 2): the formulas give the rotated scores', gap(F[fit_['rows']], arr(fit_['rotation']['scores']).reshape(-1, 2)), 0.0, abs_=1e-10)
    check('Save Rotated Components: named Rotated Prin1, Rotated Prin2', [c_['name'] for c_ in sv['columns']], ['Rotated Prin1', 'Rotated Prin2'])
check('Save Rotated Components without a rotation: an error', 'error' in call('pca.save', table=tq, columns=cq, what='rotated'), True)

# ---- Factor Analysis: the factor scores as formulas ----------------------------------------------------------------
for method in ('ml', 'pa'):
    kw = {'rows': all_rows, 'n_factors': 2, 'method': method, 'rotation': 'promax'}
    fit_ = call('factor.fit', table=tq, columns=cq, **kw)
    sv = call('factor.save', table=tq, columns=cq, **kw)
    fr_ = formula_values(tq, sv['columns'])
    if fr_ is None:
        continue
    F = np.column_stack([fvals(fr_, j) for j in range(2)])
    check.near(f'Factor Analysis ({method}, promax): the formulas give Thurstone\'s scores on the report\'s rows', gap(F[fit_['rows']], arr(fit_['scores']).reshape(-1, 2)), 0.0, abs_=1e-10)
    Xr_ = Xall.loc[fit_['rows'], cq].to_numpy(float)
    others = [i for i in range(nq) if present_all[i] and i not in fit_['rows']]
    want_ = (Xall.loc[others, cq].to_numpy(float) - Xr_.mean(0)) / Xr_.std(0, ddof=1) @ arr(fit_['score_coef']).reshape(5, 2)
    check.near(f'Factor Analysis ({method}): the excluded rows scored by the report\'s means, standard deviations and coefficients', gap(F[others], want_), 0.0, abs_=1e-10)

# ---- K Means: Save Clusters for every row, the Cluster Formula and the Distance Formulas ----------------------------
for std in (True, False):
    for label, kw in (('rows excluded', {'rows': all_rows}), ('the By group hi', {'rows': grp_rows, 'where': where_hi})):
        tag = f'K Means ({"scaled" if std else "unscaled"}, {label})'
        base_ = {'table': tq, 'columns': ['u', 'v', 'b'], 'k_min': 3, 'standardize': std, **kw}
        fit_ = call('kmeans.fit', **base_)
        f_ = fit_['fits'][0]
        sv = call('kmeans.save', k=3, what='clusters', **base_)
        cl_, di_ = sv['columns']
        lab_ = dict(zip(cl_['rows'], cl_['values']))
        dd_ = dict(zip(di_['rows'], di_['values']))
        grp_ = hi_all if kw.get('where') else np.ones(nq, dtype=bool)
        U_ = Xall[['u', 'v', 'b']].to_numpy(float)
        want_rows = [i for i in range(nq) if grp_[i] and np.isfinite(U_[i]).all()]
        check(f'{tag}: Save Clusters gives every row of the group with its columns, excluded ones too', sorted(lab_), want_rows)
        check(f'{tag}: ... the report\'s clusters on its rows', [lab_[r_] for r_ in fit_['rows']], [c_ + 1 for c_ in f_['labels']])
        check.near(f'{tag}: ... and its squared distances (JMP\'s Distance)', gap([dd_[r_] for r_ in fit_['rows']], f_['distance']), 0.0, abs_=1e-12)
        mu_, sd_ = np.array(fit_['mean']), np.array(fit_['sd'])
        C_ = arr(f_['centers_scaled']).reshape(3, 3)
        Zo = (U_[want_rows] - mu_) / sd_ if std else U_[want_rows]
        D_ = ((Zo[:, None, :] - C_[None]) ** 2).sum(2)
        check(f'{tag}: every row in the cluster of its nearest centre', [lab_[r_] for r_ in want_rows], (D_.argmin(1) + 1).tolist())
        check.near(f'{tag}: its Distance the squared Euclidean distance to it, where the clustering is', gap([dd_[r_] for r_ in want_rows], D_.min(1)), 0.0, abs_=1e-12)
        fo = call('kmeans.save', k=3, what='formula', **base_)
        fd = call('kmeans.save', k=3, what='distances', **base_)
        check(f'{tag}: Cluster Formula and three Distance Formulas', [c_['name'] for c_ in fo['columns'] + fd['columns']], ['Cluster Formula', 'Distance to Cluster 1', 'Distance to Cluster 2', 'Distance to Cluster 3'])
        fr_ = formula_values(tq, fo['columns'] + fd['columns'])
        if fr_ is None:
            continue
        cf = fvals(fr_, 0)
        check(f'{tag}: the Cluster Formula = Save Clusters on every row', [cf[r_] for r_ in want_rows], [float(lab_[r_]) for r_ in want_rows])
        check(f'{tag}: ... missing where a column is (row 8) and outside the group', (bool(np.isnan(cf[7])), bool(np.isnan(cf[~grp_]).all()) if kw.get('where') else True), (True, True))
        Df = np.column_stack([fvals(fr_, j) for j in range(1, 4)])
        check.near(f'{tag}: the Distance Formulas = the squared distances to the centres', gap(Df[want_rows], D_), 0.0, abs_=1e-10)

# ---- Hierarchical Cluster: Save Formula for Closest Cluster ------------------------------------------------------
from scipy.cluster.hierarchy import fcluster, linkage  # noqa: E402,F811
from scipy.spatial.distance import pdist, squareform  # noqa: E402

for label, kw, std in (('Ward, columns standardized', {'method': 'ward'}, 'columns'), ('average, unstandardized, 4 clusters', {'method': 'average', 'standardize': 'none', 'n_clusters': 4}, 'none'),
                       ('complete, rows standardized', {'method': 'complete', 'standardize': 'rows'}, 'rows'), ('Ward, robust, By group', {'method': 'ward', 'robust': True, 'rows': grp_rows, 'where': where_hi}, 'columns')):
    tag = f'Save Formula for Closest Cluster ({label})'
    kw2 = {'rows': all_rows, **kw}
    fit_ = call('hcluster.fit', table=tq, columns=['u', 'v', 'a'], **kw2)
    sv = call('hcluster.save', table=tq, columns=['u', 'v', 'a'], **kw2)
    k_ = sv['k']
    n_ = fit_['n']
    check(f'{tag}: the number of clusters is the report\'s', k_, kw.get('n_clusters') or page_default(fit_['heights'], n_))
    fr_ = formula_values(tq, sv['columns'])
    if fr_ is None:
        continue
    f_ = fvals(fr_, 0)
    U_ = Xall[['u', 'v', 'a']].to_numpy(float)
    Xc_ = U_[fit_['rows']]
    if std == 'columns':
        cen, sca = np.array(fit_['center']), np.array(fit_['scale'])
        Zs_ = lambda A: (A - cen) / sca  # noqa: E731
    elif std == 'rows':
        Zs_ = lambda A: (A - A.mean(1, keepdims=True)) / A.std(1, ddof=1)[:, None]  # noqa: E731
    else:
        Zs_ = lambda A: A  # noqa: E731
    labs_ = page_clusters(fit_['merges'], n_, k_, fit_['order'])
    M_ = np.array([Zs_(Xc_)[np.array(labs_) == c_].mean(0) for c_ in range(k_)])
    grp_ = hi_all if kw.get('where') else np.ones(nq, dtype=bool)
    rows_ = [i for i in range(nq) if grp_[i] and np.isfinite(U_[i]).all()]
    D_ = ((Zs_(U_[rows_])[:, None, :] - M_[None]) ** 2).sum(2)
    check(f'{tag}: every row of the group with its columns: the cluster of the nearest centroid (squared Euclidean, the clustering\'s space)', f_[rows_].tolist(), (D_.argmin(1) + 1).astype(float).tolist())
    same_ = np.mean(f_[fit_['rows']] == np.array(labs_) + 1)
    check(f'{tag}: ... most of the tree\'s rows keep their own cluster ({100 * same_:.0f}%)', same_ > 0.8, True)
check('Save Formula for Closest Cluster of a distance matrix: refused', 'error' in call('hcluster.save', table=tq, columns=['u', 'v'], matrix=True), True)

# ---- Hierarchical Cluster: Standardize Robustly, Missing value imputation, a distance matrix, the Distance option ----
from statsmodels.robust.scale import Huber as _Huber  # noqa: E402

Uc = Xall.loc[all_rows, ['a', 'b', 'c']].dropna()
Uv = Uc.to_numpy(float)
hr = call('hcluster.fit', table=tq, columns=['a', 'b', 'c'], rows=all_rows, method='average', robust=True)
hub_ = [tuple(float(np.asarray(x_)) for x_ in _Huber(maxiter=100)(Uv[:, j])) for j in range(3)]
check.near('Standardize Robustly: the centres are statsmodels\' Huber locations', gap(hr['center'], [h_[0] for h_ in hub_]), 0.0, abs_=1e-12)
check.near('... the scales its Huber scales', gap(hr['scale'], [h_[1] for h_ in hub_]), 0.0, abs_=1e-12)
Zr_ = linkage(pdist((Uv - [h_[0] for h_ in hub_]) / [h_[1] for h_ in hub_], 'sqeuclidean'), 'average')
check.near('... and the joins those of the robustly standardized rows (scipy)', gap(hr['heights'], Zr_[:, 2]), 0.0, abs_=1e-10)


def em_mvn(X, iters=2000, tol=1e-13):
    """A textbook EM for a multivariate normal with missing values (the E step's conditional means and covariances),
    written here, independently of tables.mvn_em."""
    X = np.asarray(X, float)
    n, p = X.shape
    M = np.isnan(X)
    mu = np.nanmean(X, 0)
    S = np.diag(np.nanvar(X, 0))
    for _ in range(iters):
        Xh = np.where(M, 0.0, X)
        C = np.zeros((p, p))
        for i in range(n):
            m, o = M[i], ~M[i]
            if m.any():
                K = S[np.ix_(m, o)] @ np.linalg.inv(S[np.ix_(o, o)])
                Xh[i, m] = mu[m] + K @ (X[i, o] - mu[o])
                C[np.ix_(m, m)] += S[np.ix_(m, m)] - K @ S[np.ix_(o, m)]
        mu2 = Xh.mean(0)
        S2 = (Xh - mu2).T @ (Xh - mu2) / n + C / n
        done = np.abs(mu2 - mu).max() < tol and np.abs(S2 - S).max() < tol
        mu, S = mu2, S2
        if done:
            break
    return Xh


Xmiss = Xall.loc[all_rows, ['a', 'b', 'c', 'd']].to_numpy(float)
hi_ = call('hcluster.fit', table=tq, columns=['a', 'b', 'c', 'd'], rows=all_rows, method='ward', impute=True)
check('Missing value imputation keeps the rows with a missing value', hi_['n'], len(all_rows))
Xh_ = em_mvn(Xmiss)
check.near('... each missing value the conditional mean under the EM fit (a textbook EM written here)', gap(arr(hi_['values']).reshape(-1, 4), Xh_), 0.0, abs_=1e-6)
Zi_ = linkage((Xh_ - Xh_.mean(0)) / Xh_.std(0, ddof=1), 'ward')
check.near('... and the Ward joins of the completed rows (scipy)', gap(hi_['heights'], Zi_[:, 2] ** 2 / 2), 0.0, abs_=1e-6)
check('... the report says how many values it imputed', any('imputed' in t_ for t_ in hi_['notes']), True)
check('Missing value imputation with one numeric column: refused', 'error' in call('hcluster.fit', table=tq, columns=['b'], impute=True), True)

# a distance matrix: a column per row, one side of the diagonal given
pts_ = Xall.loc[:11, ['u', 'v']].to_numpy(float)
Dm_ = squareform(pdist(pts_))
Dlo = Dm_.copy()
Dlo[np.triu_indices(12, 1)] = np.nan
tm_ = table({'obj': [f'o{i}' for i in range(12)], **{f'o{j}': Dlo[:, j] for j in range(12)}})
mcols_ = [f'o{j}' for j in range(12)]
for method in ('single', 'complete', 'average', 'ward', 'centroid'):
    hm_ = call('hcluster.fit', table=tm_, columns=mcols_, method=method, matrix=True, label='obj')
    want_ = linkage(pdist(pts_), method) if method in ('single', 'complete', 'average') else linkage(pts_, method)
    h_ = want_[:, 2] ** 2 / 2 if method == 'ward' else want_[:, 2] ** 2 if method == 'centroid' else want_[:, 2]
    check.near(f'distance matrix ({method}): the joins of the distances given (scipy; Ward and Centroid in JMP\'s heights)', gap(hm_['heights'], h_), 0.0, abs_=1e-9)
keep_ = [0, 1, 2, 3, 5, 6, 7, 8, 9, 10, 11]
hm_ = call('hcluster.fit', table=tm_, columns=mcols_, method='average', matrix=True, rows=keep_)
check.near('distance matrix with a row excluded: its row and column left out', gap(hm_['heights'], linkage(pdist(pts_[keep_]), 'average')[:, 2]), 0.0, abs_=1e-9)
check('... the rows clustered', hm_['rows'], keep_)
check('distance matrix of the wrong shape: refused', 'error' in call('hcluster.fit', table=tm_, columns=mcols_[:5], method='average', matrix=True), True)
bad_ = Dlo.copy()
bad_[3, 1] = np.nan
check('distance matrix missing on both sides: refused', 'error' in call('hcluster.fit', table=table({f'o{j}': bad_[:, j] for j in range(12)}), columns=mcols_, method='average', matrix=True), True)
ns = run_code('distance matrix (average)', hm_['code'], tm_)
# (the code of a report of every row: the report above leaves row 5 out)
hm_all = call('hcluster.fit', table=tm_, columns=mcols_, method='average', matrix=True, label='obj')
ns = run_code('distance matrix (average, every row)', hm_all['code'], tm_)
if ns:
    check.near('distance matrix: the code\'s joins are the report\'s', gap(ns['heights'], hm_all['heights']), 0.0, abs_=1e-12)

# the Distance option of Single, Complete and Average
Xd_ = Xall.loc[all_rows, ['u', 'v', 'a']].dropna().to_numpy(float)
Xds = (Xd_ - Xd_.mean(0)) / Xd_.std(0, ddof=1)
for dist in ('euclidean', 'cityblock', 'chebyshev', 'correlation', 'mahalanobis'):
    extra_ = {'VI': np.linalg.pinv(np.cov(Xds, rowvar=False))} if dist == 'mahalanobis' else {}
    for method in ('single', 'complete', 'average'):
        hd_ = call('hcluster.fit', table=tq, columns=['u', 'v', 'a'], rows=all_rows, method=method, distance=dist)
        Zd_ = linkage(pdist(Xds, dist, **extra_), method)
        check(f'Distance {dist}, {method}: the joins = scipy linkage of pdist', (np.array(hd_['merges']).tolist() == Zd_[:, :2].astype(int).tolist(), float(gap(hd_['heights'], Zd_[:, 2])) < 1e-12), (True, True))
    ns = run_code(f'Distance {dist} (average)', hd_['code'], tq)
    if ns:
        check.near(f'Distance {dist}: the code\'s joins are the report\'s', gap(ns['heights'], hd_['heights']), 0.0, abs_=1e-12)
check('Ward with the city block distance: refused (Ward needs squared Euclidean distances)', 'error' in call('hcluster.fit', table=tq, columns=['u', 'v'], method='ward', distance='cityblock'), True)
# Jaccard: present (not 0) or absent
bj = (np.random.default_rng(3).random((40, 5)) < 0.4).astype(float)
tj = table({f'b{j}': bj[:, j] for j in range(5)})
hj = call('hcluster.fit', table=tj, columns=[f'b{j}' for j in range(5)], method='average', distance='jaccard')
check.near('Distance Jaccard: the joins = scipy\'s Jaccard of the 0/1 rows', gap(hj['heights'], linkage(pdist(bj != 0, 'jaccard'), 'average')[:, 2]), 0.0, abs_=1e-12)
ns = run_code('Distance Jaccard', hj['code'], tj)
if ns:
    check.near('Distance Jaccard: the code\'s joins are the report\'s', gap(ns['heights'], hj['heights']), 0.0, abs_=1e-12)
# Gower on numeric and nominal columns: by brute force
okg = [i for i in all_rows if np.isfinite(Xall.loc[i, ['a', 'b']].to_numpy(float)).all()]
Gx = Xall.loc[okg, ['a', 'b']].to_numpy(float)
Gq = np.array([q1[i] for i in okg])
Gq3 = np.array([q3[i] for i in okg])
rg_ = Gx.max(0) - Gx.min(0)
Gb = np.array([[(abs(Gx[i, 0] - Gx[j, 0]) / rg_[0] + abs(Gx[i, 1] - Gx[j, 1]) / rg_[1] + (Gq[i] != Gq[j]) + (Gq3[i] != Gq3[j])) / 4 for j in range(len(okg))] for i in range(len(okg))])
for method in ('single', 'complete', 'average'):
    hg = call('hcluster.fit', table=tq, columns=['a', 'b', 'q1', 'q3'], rows=all_rows, method=method, distance='gower')
    check.near(f'Distance Gower ({method}, two numeric and two nominal columns, one of them numeric): the joins of Gower\'s brute-force dissimilarities', gap(hg['heights'], linkage(squareform(Gb, checks=False), method)[:, 2]), 0.0, abs_=1e-12)
check('... Gower with nominal columns has no coordinates (no CCC, two-way clustering or closest-cluster formula)', (hg['coords'], hg['criterion'], 'error' in call('hcluster.save', table=tq, columns=['a', 'b', 'q1'], rows=all_rows, method='average', distance='gower')), (False, [], True))
ns = run_code('Distance Gower (average)', hg['code'], tq)
if ns:
    check.near('Distance Gower: the code\'s joins are the report\'s', gap(ns['heights'], hg['heights']), 0.0, abs_=1e-12)
check('a nominal column without Gower: refused', 'error' in call('hcluster.fit', table=tq, columns=['a', 'q1'], method='average'), True)

# ---- Hierarchical Cluster: silhouettes (beyond JMP) against scikit-learn ----------------------------------------
from sklearn.metrics import silhouette_samples, silhouette_score  # noqa: E402

for label, kw, D_of in (('Ward: Euclidean distances', {'method': 'ward'}, lambda h: squareform(pdist(arr(h['data']).reshape(h['n'], -1)))),
                        ('average, city block', {'method': 'average', 'distance': 'cityblock'}, lambda h: squareform(pdist(arr(h['data']).reshape(h['n'], -1), 'cityblock'))),
                        ('average, Gower with nominal columns', {'method': 'average', 'distance': 'gower'}, lambda h: Gb),
                        ('a distance matrix, complete', {'method': 'complete', 'matrix': True}, lambda h: Dm_)):
    for nc in (None, 4):
        cols_ = mcols_ if kw.get('matrix') else (['a', 'b', 'q1', 'q3'] if kw.get('distance') == 'gower' else ['u', 'v', 'a'])
        t_ = tm_ if kw.get('matrix') else tq
        h_ = call('hcluster.fit', table=t_, columns=cols_, rows=None if kw.get('matrix') else all_rows, silhouette=True, n_clusters=nc, **kw)
        S_ = h_['silhouette']
        tag = f'silhouettes ({label}, {"the default" if nc is None else nc} clusters)'
        lab_ = np.array(page_clusters(h_['merges'], h_['n'], S_['k'], h_['order']))
        Dsk = D_of(h_)
        check.near(f'{tag}: each row\'s = scikit-learn\'s silhouette_samples', gap(S_['values'], silhouette_samples(Dsk, lab_, metric='precomputed')), 0.0, abs_=1e-12)
        check.near(f'{tag}: the mean', S_['mean'], float(silhouette_score(Dsk, lab_, metric='precomputed')), rel=1e-12)
        pth = {q_['k']: q_['mean'] for q_ in S_['path']}
        want_ = {q_: float(silhouette_score(Dsk, np.array(page_clusters(h_['merges'], h_['n'], q_, h_['order'])), metric='precomputed')) for q_ in pth}
        check.near(f'{tag}: the mean for every number of clusters (2 to {max(pth)})', max(abs(pth[q_] - want_[q_]) for q_ in pth), 0.0, abs_=1e-12)
        check(f'{tag}: the best number is the largest mean', S_['best'], max(want_, key=want_.get))
        check(f'{tag}: each cluster\'s count and mean', [(c_['count'], round(c_['mean'], 12)) for c_ in S_['clusters']], [(int((lab_ == c_).sum()), round(float(np.mean(silhouette_samples(Dsk, lab_, metric='precomputed')[lab_ == c_])), 12)) for c_ in range(S_['k'])])
        if nc == 4:
            F = figure(tag, h_['silhouette_code'], t_)
            ax = F['axes'][0]
            o_ = np.lexsort((-np.array(S_['values']), lab_))
            check.near(f'{tag}: the code\'s bars are the rows\' silhouettes, by cluster', gap([b_['w'] for b_ in ax['bars']], np.array(S_['values'])[o_]), 0.0, abs_=1e-12)
            check(f'{tag}: ... in their clusters\' colours, the mean dashed', ([b_['fc'][:7] for b_ in ax['bars']] == [PAL[c_ % 12] for c_ in lab_[o_]], has_line(ax, [S_['mean'], S_['mean']], None, ls='--')), (True, True))
            F = figure(f'{tag}: the mean by number of clusters', h_['silhouette_k_code'], t_)
            ax = F['axes'][0]
            check(f'{tag}: the code draws the mean silhouette of each number of clusters', has_line(ax, list(pth), [pth[q_] for q_ in pth], rel=1e-10), True)

# ---- Hierarchical Cluster: the parallel coordinate plot's code ---------------------------------------------------
for label, kw in (('Ward, 3 clusters', {'method': 'ward', 'n_clusters': 3}), ('average, imputed, By group', {'method': 'average', 'impute': True, 'rows': grp_rows, 'where': where_hi})):
    cols_ = ['a', 'b', 'c', 'd']
    h_ = call('hcluster.fit', table=tq, columns=cols_, **{'rows': all_rows, **kw})
    k_ = kw.get('n_clusters') or page_default(h_['heights'], h_['n'])
    tag = f'parallel coordinates ({label})'
    F = figure(tag, h_['parallel_code'], tq)
    ax = F['axes'][0]
    lab_ = np.array(page_clusters(h_['merges'], h_['n'], k_, h_['order']))
    V_ = arr(h_['values']).reshape(h_['n'], -1) if kw.get('impute') else Xall.loc[h_['rows'], cols_].to_numpy(float)
    mu_, sd_ = V_.mean(0), V_.std(0, ddof=1)
    means_ = [(V_[lab_ == c_].mean(0) - mu_) / sd_ for c_ in range(k_)]
    check(f'{tag}: each cluster\'s mean line, standardized', all(has_line(ax, [0, 1, 2, 3], list(m_), rel=1e-9, color=PAL[c_]) for c_, m_ in enumerate(means_)), True)
    segs_ = [np.asarray(s_, float) for sgm in ax['segments'] for s_ in sgm['segs']]
    check.near(f'{tag}: every row\'s line', gap(np.sort(np.array([s_[:, 1] for s_ in segs_]), axis=0), np.sort((V_ - mu_) / sd_, axis=0)), 0.0, abs_=1e-9)
    if kw.get('where'):
        keeps(tag, h_['parallel_code'], WHERE_HI, grp_drop)

# ---- K Means: Single Step (JMP's) and the criteria by number of clusters -------------------------------------------
base_ = {'table': tq, 'columns': ['u', 'v'], 'rows': all_rows, 'k_min': 2, 'k_max': 5, 'seed': 77}
one_ = call('kmeans.fit', restarts=1, **base_)
go_ = call('kmeans.fit', single=True, steps={str(k_): None for k_ in range(2, 6)}, **base_)
for f1, fs in zip(one_['fits'], go_['fits']):
    a_, b_ = np.array(f1['labels']), np.array(fs['labels'])
    same_ = all(len(set(b_[a_ == c_])) == 1 for c_ in range(f1['k'])) and all(len(set(a_[b_ == c_])) == 1 for c_ in range(f1['k']))
    check(f'Single Step, Go ({f1["k"]} clusters): the partition of the fit with one restart (the same start)', (same_, fs['converged']), (True, True))
    check.near(f'Single Step, Go ({f1["k"]} clusters): the same within sum of squares', fs['wss'], f1['wss'], rel=1e-10)
s0 = call('kmeans.fit', single=True, steps={}, **base_)
check('Single Step before a step: no clusters, the starting centres only (JMP: no cluster assignments)', [(f_['k'], f_['labels'], f_['step'], len(f_['seeds'])) for f_ in s0['fits']], [(k_, None, 0, k_) for k_ in range(2, 6)])
U_ = Xall.loc[go_['rows'], ['u', 'v']].to_numpy(float)
mu_, sd_ = np.array(go_['mean']), np.array(go_['sd'])
Z_ = (U_ - mu_) / sd_
for k_ in (3, 4):
    C0 = arr(s0['fits'][k_ - 2]['centers_scaled']).reshape(k_, 2)
    check.near(f'Single Step ({k_} clusters): the starting centres in the columns\' units', gap(s0['fits'][k_ - 2]['seeds'], mu_ + sd_ * C0), 0.0, abs_=1e-12)
    C_ = C0.copy()
    for step_ in (1, 2, 3):
        lab_ = ((Z_[:, None] - C_[None]) ** 2).sum(2).argmin(1)   # a step by hand: the nearest centre, then the means
        C_ = np.array([Z_[lab_ == c_].mean(0) if (lab_ == c_).any() else C_[c_] for c_ in range(k_)])
        st_ = call('kmeans.fit', single=True, steps={str(k_): step_}, **{**base_, 'k_min': k_, 'k_max': k_})
        # (the start of k is the k-th draw of the stream: with k_min = k the stream starts there; draw the earlier starts too)
        st_ = call('kmeans.fit', single=True, steps={str(k_): step_}, **base_)['fits'][k_ - 2]
        check(f'Single Step ({k_} clusters), step {step_}: the rows assigned to the nearest centres of the step before', np.array(st_['labels']).tolist(), lab_.tolist())
        check.near(f'Single Step ({k_} clusters), step {step_}: the cluster means', gap(st_['means'], [U_[lab_ == c_].mean(0) for c_ in range(k_)]), 0.0, abs_=1e-12)
        check(f'Single Step ({k_} clusters), step {step_}: the step', st_['step'], step_)
sv1 = call('kmeans.save', k=3, what='clusters', single=True, steps={'3': 1}, **base_)
f1_ = call('kmeans.fit', single=True, steps={'3': 1}, **base_)['fits'][1]
lab1 = dict(zip(sv1['columns'][0]['rows'], sv1['columns'][0]['values']))
check('Single Step, one step: Save Clusters keeps the report\'s clusters on its rows', [lab1[r_] for r_ in go_['rows']], [c_ + 1 for c_ in f1_['labels']])
check('Single Step before the first step: no clusters to save', 'error' in call('kmeans.save', k=3, what='clusters', single=True, steps={}, **base_), True)
ns = run_code('Single Step: the report\'s code', call('kmeans.fit', single=True, steps={'2': 1, '3': None}, **base_)['code'], tq)
if ns:
    mix_ = call('kmeans.fit', single=True, steps={'2': 1, '3': None}, **base_)
    check('Single Step: the code\'s clusters are the report\'s (one step, Go, and no step)', [np.asarray(ns['fits'][f_['k']]).tolist() for f_ in mix_['fits'] if f_['labels'] is not None], [f_['labels'] for f_ in mix_['fits'] if f_['labels'] is not None])
for label, r_ in (('restarts', call('kmeans.fit', **base_)), ('Single Step, Go', go_)):
    tag = f'the criteria by number of clusters ({label})'
    F = figure(tag, r_['comparison_code'], tq)
    ks_ = [f_['k'] for f_ in r_['fits']]
    for q_, key in enumerate(('ccc', 'pseudo_f', 'r2', 'wss')):
        ax = F['axes'][q_]
        check(f'{tag}: the {key} of each number of clusters', has_line(ax, ks_, [f_[key] for f_ in r_['fits']], rel=1e-9), True)
        check(f'{tag}: ... the Optimal CCC dashed', has_line(ax, [r_['best'], r_['best']], None, ls='--'), True)
check('the criteria\'s code only with two or more fits', 'comparison_code' in call('kmeans.fit', table=tq, columns=['u', 'v'], k_min=3), False)

# ---- Discriminant: the Validation role, Save Formulas, the curves and the Decision Threshold -----------------------------
from sklearn.metrics import roc_auc_score  # noqa: E402

vq = np.array([1.0 if i % 4 == 0 else 2.0 if i % 9 == 0 else 0.0 for i in range(nq)])
tqv = table({**{c_: Xall[c_].to_numpy(float) for c_ in ('a', 'b', 'c', 'u', 'v')}, 'g': gq, 'yb': ybq, 'val': vq, 'valt': [['Training', 'Validation', 'Test'][int(x_)] for x_ in vq], 'w': wq},
            levels={'g': ['mid', 'hi', 'lo']})
Xv = export(tqv)
okv = np.isfinite(Xv[['a', 'b', 'c']].to_numpy(float)).all(1)
tr_ = okv & (vq == 0)
Yv, gv = Xv[['a', 'b', 'c']].to_numpy(float), np.array(gq)
lv_ = ['mid', 'hi', 'lo']
for method in ('linear', 'quadratic'):
    for vcol in ('val', 'valt'):
        tag = f'Discriminant with a Validation column ({method}, {"0/1/2" if vcol == "val" else "words"})'
        dv = call('discriminant.fit', table=tqv, y=['a', 'b', 'c'], x='g', method=method, validation=vcol, curves=True)
        means_ = np.array([Yv[tr_ & (gv == l_)].mean(0) for l_ in lv_])
        check.near(f'{tag}: the group means are the training rows\'', gap(dv['means'], means_), 0.0, abs_=1e-12)
        E_ = sum((Yv[tr_ & (gv == l_)] - means_[t_]).T @ (Yv[tr_ & (gv == l_)] - means_[t_]) for t_, l_ in enumerate(lv_))
        Sp_ = E_ / (tr_.sum() - 3)
        rows_v = np.flatnonzero(okv)
        if method == 'linear':
            lp = np.column_stack([stats.multivariate_normal(means_[t_], Sp_).logpdf(Yv[rows_v]) for t_ in range(3)])
        else:
            lp = np.column_stack([stats.multivariate_normal(means_[t_], np.cov(Yv[tr_ & (gv == l_)], rowvar=False)).logpdf(Yv[rows_v]) for t_, l_ in enumerate(lv_)])
        Pw = np.exp(lp - lp.max(1, keepdims=True))
        Pw /= Pw.sum(1, keepdims=True)
        check.near(f'{tag}: every row scored by the training rows\' normal densities (scipy)', gap(dv['prob'], Pw), 0.0, abs_=1e-10)
        check(f'{tag}: the sets of the rows', dv['sets'], vq[rows_v].astype(int).tolist())
        act = np.array([lv_.index(g_) for g_ in gv[rows_v]])
        for s_ in dv['summaries']:
            k_ = ['Training', 'Validation', 'Test'].index(s_['set'])
            m_ = vq[rows_v] == k_
            check(f'{tag}: {s_["set"]} misclassified', s_['n_mis'], float(np.sum(Pw[m_].argmax(1) != act[m_])))
            sh_ = np.array([np.sum(act[vq[rows_v] == 0] == t_) for t_ in range(3)]) / np.sum(vq[rows_v] == 0)
            ll_, ll0_ = np.sum(np.log(Pw[m_][np.arange(m_.sum()), act[m_]])), np.sum(np.log(sh_[act[m_]]))
            check.near(f'{tag}: {s_["set"]} entropy RSquare (the training shares)', s_['entropy_r2'], 1 - ll_ / ll0_, rel=1e-9)
        for rc_ in dv['fit']['roc']:
            k_ = ['Training', 'Validation', 'Test'].index(rc_['set'])
            m_ = vq[rows_v] == k_
            j_ = dv['fit']['levels'].index(rc_['level'])
            check.near(f'{tag}: the {rc_["set"]} AUC of {rc_["level"]} = scikit-learn\'s', rc_['auc'], float(roc_auc_score(act[m_] == j_, Pw[m_, j_])), rel=1e-12)
        ns = run_code(f'{tag}: the code', dv['code'], tqv)
        if ns:
            check.near(f'{tag}: the code\'s probabilities are the report\'s', gap(ns['P'], dv['prob']), 0.0, abs_=1e-10)
        F = figure(f'{tag}: the validation ROC curve', f'{dv["fit"]["plots"]["head_code"]}\n\n# ----\n{dv["fit"]["plots"]["roc"]["Validation"]}', tqv)
        vroc = [rc_ for rc_ in dv['fit']['roc'] if rc_['set'] == 'Validation']
        check(f'{tag}: ... its code draws the report\'s curves', all(has_line(F['axes'][0], rc_['fpr'], rc_['tpr'], rel=1e-9) for rc_ in vroc if len(rc_['fpr']) < 400), True)
dvw = call('discriminant.fit', table=tqv, y=['a', 'b', 'c'], x='g', weight='w', validation='val', curves=True)
Pw_, act_, st_w = arr(dvw['prob']).reshape(-1, 3), np.array(dvw['actual']), np.array(dvw['sets'])
w_v = wq[dvw['rows']]
check.near('Discriminant with a Weight: each set\'s AUC = scikit-learn\'s with the weights (the curves count rows by Weight x Freq)',
           max(abs(rc_['auc'] - roc_auc_score(act_[st_w == ['Training', 'Validation', 'Test'].index(rc_['set'])] == dvw['fit']['levels'].index(rc_['level']),
                                               Pw_[st_w == ['Training', 'Validation', 'Test'].index(rc_['set']), dvw['fit']['levels'].index(rc_['level'])],
                                               sample_weight=w_v[st_w == ['Training', 'Validation', 'Test'].index(rc_['set'])])) for rc_ in dvw['fit']['roc']), 0.0, abs_=1e-12)
F = figure('Discriminant with a Weight: the validation lift curves', f'{dvw["fit"]["plots"]["head_code"]}\n\n# ----\n{dvw["fit"]["plots"]["lift"]["Validation"]}', tqv)
check('... its lift code draws the report\'s curves', all(has_line(F['axes'][0], lc_['portion'], lc_['lift'], rel=1e-9) for lc_ in dvw['fit']['lift'] if lc_['set'] == 'Validation' and len(lc_['portion']) < 300), True)
check('Discriminant: a Validation column with k folds is refused', 'error' in call('discriminant.fit', table=table({'a': Yv[:, 0], 'b': Yv[:, 1], 'g': gq, 'f': [float(i % 5) for i in range(nq)]}), y=['a', 'b'], x='g', validation='f'), True)
st_ = call('discriminant.stepwise', table=tqv, y=['a', 'b', 'c'], x='g', validation='val', entered=[])
okt = tr_
ow_ = sm.OLS(Yv[okt, 0], sm.add_constant(pd.get_dummies(gv[okt], drop_first=True).to_numpy(float))).fit()
check.near('Discriminant stepwise with a Validation column: the F test on the training rows', st_['columns'][0]['F'], float(ow_.fvalue), rel=1e-9)
# the Decision Threshold of two groups (WP3's report, fed with every row's probabilities)
d2 = call('discriminant.fit', table=tqv, y=['a', 'b', 'c'], x='yb', validation='val', decision=True)
th = d2['threshold']
check('Decision Threshold: two levels, every row\'s set and group', (th['levels'], th['points']['set'], th['points']['actual']), (d2['levels'], d2['sets'], d2['actual']))
check.near('Decision Threshold: the probabilities of the second level are the report\'s', gap(th['models'][0]['p'], arr(d2['prob']).reshape(-1, 2)[:, 1]), 0.0, abs_=1e-15)
check('Decision Threshold: only with two groups', 'threshold' in call('discriminant.fit', table=tqv, y=['a', 'b', 'c'], x='g', decision=True), False)
# Save Formulas: SqDist, Prob and Pred for every row, and Save Canonical Scores
for method, kw in (('linear', {}), ('quadratic', {}), ('regularized', {'lam': 0.3, 'gam': 0.2}), ('linear, proportional priors, Validation', {'priors': 'proportional', 'validation': 'val'}),
                   ('linear, other priors, the By group hi, rows excluded', {'priors': 'other', 'prior_values': {'k1': 0.2, 'k2': 0.5, 'k3': 0.3}})):
    tag = f'Discriminant Save Formulas ({method})'
    meth = method.split(',')[0]
    kw2 = {'table': tqv, 'y': ['a', 'b', 'c'], 'x': 'g', 'method': meth, **kw}
    if 'By group' in method:
        kw2 = {**kw2, 'rows': [i for i in grp_rows], 'where': where_hi, 'x': 'yb', 'prior_values': {'no': 0.3, 'yes': 0.7}}
    dr_ = call('discriminant.fit', **kw2)
    sv = call('discriminant.save', **kw2)
    names_ = [c_['name'] for c_ in sv['columns']]
    L_ = [str(v_) for v_ in dr_['levels']]
    check(f'{tag}: SqDist[…], Prob[…] and Pred {kw2["x"]}', names_, [f'SqDist[{l_}]' for l_ in L_] + [f'Prob[{l_}]' for l_ in L_] + [f'Pred {kw2["x"]}'])
    fr_ = formula_values(tqv, sv['columns'])
    if fr_ is None:
        continue
    T_ = len(L_)
    Sq = np.column_stack([fvals(fr_, j) for j in range(T_)])
    Pq = np.column_stack([fvals(fr_, T_ + j) for j in range(T_)])
    rr_ = dr_['rows']
    check.near(f'{tag}: the SqDist formulas give the report\'s', gap(Sq[rr_], dr_['sqdist']), 0.0, abs_=1e-9)
    check.near(f'{tag}: the Prob formulas give its posterior probabilities', gap(Pq[rr_], dr_['prob']), 0.0, abs_=1e-12)
    check(f'{tag}: Pred is its most probable group', [fr_[-1]['values'][r_] for r_ in rr_], [L_[t_] for t_ in dr_['pred']])
    grp_ = hi_all if 'By group' in method else np.ones(nq, dtype=bool)
    others = [i for i in range(nq) if grp_[i] and okv[i] and i not in rr_]
    if others:
        check(f'{tag}: the rows the report leaves out are scored too ({len(others)})', bool(np.isfinite(Pq[others]).all()) and all(fr_[-1]['values'][i] is not None for i in others), True)
        check.near(f'{tag}: ... their probabilities sum to 1', gap(Pq[others].sum(1), np.ones(len(others))), 0.0, abs_=1e-12)
    check(f'{tag}: a row with a missing covariate has none', (bool(np.isnan(Pq[7]).all()), fr_[-1]['values'][7]), (True, None))
    if 'By group' in method:
        check(f'{tag}: the other groups\' rows have none', bool(np.isnan(Pq[~hi_all]).all()), True)
dr_ = call('discriminant.fit', table=tqv, y=['a', 'b', 'c'], x='g')
sv = call('discriminant.save', table=tqv, y=['a', 'b', 'c'], x='g', what='canonical')
fr_ = formula_values(tqv, sv['columns'])
if fr_ is not None:
    check.near('Save Canonical Scores: the formulas give the canonical scores', gap(np.column_stack([fvals(fr_, j) for j in range(2)])[dr_['rows']], dr_['canonical']['scores']), 0.0, abs_=1e-10)
pr_ = call('discriminant.probs', table=tqv, y=['a', 'b', 'c'], x='g', rows=all_rows)
check('discriminant.probs: every row with its covariates, excluded ones too', pr_['rows'], np.flatnonzero(okv).tolist())
# the Scatterplot Matrix with the groups' ellipses: its code
for method in ('linear', 'quadratic'):
    ds = call('discriminant.fit', table=tqv, y=['a', 'b', 'c'], x='g', method=method, plot={'splom': {'width': 400, 'height': 380, 'level': 0.9}})
    tag = f'Discriminant scatterplot matrix ({method})'
    F = figure(tag, ds['splom_code'], tqv)
    axes_ = [ax for ax in F['axes'] if ax.get('visible', True) and (ax['scatter'] or ax['lines'])]
    check(f'{tag}: three cells below the diagonal', len(axes_), 3)
    rows_d = ds['rows']
    ax = axes_[0]
    check.near(f'{tag}: its points are the rows\' covariates (b by a)', gap(pts(ax), Xv.loc[rows_d, ['a', 'b']].to_numpy(float)), 0.0, abs_=1e-12)
    Sg = [arr(c_).reshape(3, 3) for c_ in ds['model_cov']]
    want_ok = []
    for t_ in range(3):
        m_ = np.array(ds['means'][t_])
        sx, sy = math.sqrt(Sg[t_][0, 0]), math.sqrt(Sg[t_][1, 1])
        ex, ey = page_ellipse(m_[0], m_[1], sx, sy, Sg[t_][0, 1] / (sx * sy), 0.9)
        want_ok.append(has_line(ax, list(ex), list(ey), rel=1e-9, color=PAL[t_]))
    check(f'{tag}: each group\'s 90% ellipse from its mean and the method\'s covariance', want_ok, [True] * 3)
    if method == 'linear':
        check(f'{tag}: the linear method\'s ellipses share the pooled covariance', all(np.allclose(Sg[0], S_) for S_ in Sg), True)

sys.exit(check.done())
