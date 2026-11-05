"""Statistics and machine learning, run natively (CPython with numpy,
scipy and scikit-learn, which serves only as the reference): distances
against scipy.spatial, k-means, hierarchical clustering, DBSCAN,
silhouettes and cluster criteria, Gaussian mixtures, PCA, MDS, Procrustes
and canonical correlation against SciPy and scikit-learn; then the
classifiers and regressions (trees, kNN, discriminants, naive Bayes,
SVMs, linear models, Gaussian processes) against scikit-learn's, the
ensembles, ECOC and networks by what they achieve, partitions and
cross-validation, confusion matrices and ROC curves.

    python3 test_ml.py          (from any folder)
"""
import asyncio
import math
import os
import sys

import numpy as np
import scipy.cluster.hierarchy as sch
from scipy.spatial import distance as ssd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', '..', 'py'))

from plab import runtime as R  # noqa: E402
from plab.values import Char  # noqa: E402

R.setup()


PRESET = {}


def run(code):
    R.BASE.clear()
    R.BASE.update(PRESET)
    R.take_output()
    asyncio.run(R.execute(code))
    return dict(R.BASE), R.take_output()


class Checks:
    def __init__(self):
        self.n = 0
        self.failed = []

    def __call__(self, label, ok, detail=''):
        self.n += 1
        if not ok:
            self.failed.append(label)
            print(f'FAIL  {label}  {detail}')
        return ok

    def done(self):
        print(f'\n{self.n - len(self.failed)} of {self.n} checks passed')
        return 1 if self.failed else 0


C = Checks()


def a(x):
    if isinstance(x, tuple):
        return np.concatenate([np.asarray(v, dtype=float).reshape(-1) for v in x])
    return np.asarray(x, dtype=float)


def near(label, got, want, tol=1e-10):
    g, w = a(got), a(want)
    ok = g.shape == w.shape and np.allclose(g, w, rtol=tol, atol=tol, equal_nan=True)
    return C(label, ok, f'got {np.round(g, 8).tolist() if g.size < 30 else g.shape}, want {np.round(w, 8).tolist() if w.size < 30 else w.shape}')


def same(label, got, want):
    return C(label, got == want, f'got {got!r}, want {want!r}')


def raises(code, words):
    W, _ = run(f"try, {code}; e = ''; catch ex, e = ex.message; end")
    msg = W['e'].str() if isinstance(W['e'], Char) else str(W['e'])
    return C(f'refused: {code}', words in msg, msg)


def mat(M):
    M = np.atleast_2d(M)
    return '[' + '; '.join(' '.join(f'{v:.17g}' for v in row) for row in M) + ']'


def partition(lab):
    lab = np.asarray(lab).reshape(-1)
    return sorted(tuple(np.flatnonzero(lab == v)) for v in np.unique(lab[lab >= 0]))


rs = np.random.RandomState(3)
X = np.vstack([rs.randn(25, 3), rs.randn(25, 3) + [4, 0, 1], rs.randn(25, 3) + [0, 5, -2]])
Xs = mat(X)
PRESET['Xd'] = np.array(X)

# ---- distances ----------------------------------------------------------------------------------------------------------------------------
for name, sname, kw in (('euclidean', 'euclidean', {}), ('squaredeuclidean', 'sqeuclidean', {}), ('cityblock', 'cityblock', {}),
                        ('chebychev', 'chebyshev', {}), ('cosine', 'cosine', {}), ('correlation', 'correlation', {}),
                        ('seuclidean', 'seuclidean', {'V': np.var(X, axis=0, ddof=1)}), ('mahalanobis', 'mahalanobis', {'VI': np.linalg.inv(np.cov(X, rowvar=False))})):
    W, _ = run(f"D = pdist({Xs}, '{name}');")
    near(f'pdist {name} (scipy)', W['D'], ssd.pdist(X, sname, **kw).reshape(1, -1), 1e-10)
W, _ = run(f"D = pdist({Xs}, 'minkowski', 3); S = pdist({Xs}, 'spearman'); F = pdist(Xd(1:4, :), @(a, b) sum(abs(a - b), 2));")
near('pdist minkowski 3', W['D'], ssd.pdist(X, 'minkowski', p=3).reshape(1, -1))
from scipy.stats import rankdata  # noqa: E402
near('pdist spearman: correlation of the ranks', W['S'], ssd.pdist(np.apply_along_axis(rankdata, 1, X), 'correlation').reshape(1, -1))
near('pdist with a function handle', W['F'], ssd.pdist(X[:4], 'cityblock').reshape(1, -1))
W, _ = run(f"X = {Xs}; Q = squareform(pdist(X)); v = squareform(Q); [D2, I2] = pdist2(X(1:5, :), X, 'euclidean', 'Smallest', 2); "
           "[idx, d] = knnsearch(X, X(1:4, :), 'K', 3); [ri, rd] = rangesearch(X, X(1, :), 1.5); r1 = ri{1}; d1 = rd{1};")
near('squareform both ways', (W['Q'], W['v']), (ssd.squareform(ssd.pdist(X)), ssd.pdist(X).reshape(1, -1)))
Dfull = ssd.cdist(X[:5], X)
near("pdist2 'Smallest': the two smallest in each column, and where", (W['D2'], W['I2']), (np.sort(Dfull, axis=0)[:2], np.argsort(Dfull, axis=0, kind='stable')[:2] + 1))
Dq = ssd.cdist(X[:4], X)
near('knnsearch: the nearest rows, nearest first', (W['idx'], W['d']), (np.argsort(Dq, axis=1, kind='stable')[:, :3] + 1, np.sort(Dq, axis=1)[:, :3]))
inside = np.flatnonzero(ssd.cdist(X[:1], X)[0] <= 1.5)
near('rangesearch: within the radius, nearest first', W['r1'], (inside[np.argsort(ssd.cdist(X[:1], X)[0][inside], kind='stable')] + 1).reshape(1, -1))

# ---- clustering --------------------------------------------------------------------------------------------------------------------------------
from sklearn.cluster import KMeans, DBSCAN  # noqa: E402
W, _ = run(f"rng(1); [idx, Cc, sumd, D] = kmeans({Xs}, 3, 'Replicates', 5); [i2, c2] = kmeans({Xs}, 3, 'Distance', 'cityblock');")
km = KMeans(3, n_init=10, random_state=0).fit(X)
same('kmeans: the three clusters (scikit-learn KMeans)', partition(W['idx']), partition(km.labels_))
near('kmeans centroids and sums of squared distances', (np.sort(a(W['Cc'])[:, 0]), a(W['sumd']).sum()), (np.sort(km.cluster_centers_[:, 0]), km.inertia_), 1e-8)
i2 = a(W['i2']).astype(int).reshape(-1)
near("'cityblock': each centroid the median of its cluster", a(W['c2']), np.array([np.median(X[i2 == k], axis=0) for k in range(1, 4)]))
W, _ = run(f"rng(2); [idx, Cm, sumd, D, midx] = kmedoids(Xd(1:12, :), 2, 'Distance', 'euclidean');")
Dm = ssd.squareform(ssd.pdist(X[:12]))
best = min(((i, j) for i in range(12) for j in range(i + 1, 12)), key=lambda p: Dm[:, list(p)].min(1).sum())
same('kmedoids: the best pair of medoids (all pairs tried)', sorted(int(v) for v in a(W['midx']).reshape(-1)), [best[0] + 1, best[1] + 1])
for method in ('single', 'complete', 'average', 'weighted', 'ward', 'centroid', 'median'):
    W, _ = run(f"Z = linkage({Xs}, '{method}');")
    Zs = sch.linkage(X, method)
    near(f'linkage {method} (scipy)', W['Z'], np.column_stack([Zs[:, :2] + 1, Zs[:, 2]]))
W, _ = run(f"X = {Xs}; Y = pdist(X); Z1 = linkage(Y, 'single'); Z2 = linkage(Y, 'average'); Zw = linkage(X, 'ward');")
near('linkage of a variable (pdist\'s row, the data) twice over: SciPy given a copy, not the shared array',
     (W['Z1'], W['Z2'], W['Zw']), tuple(np.column_stack([z[:, :2] + 1, z[:, 2]]) for z in (sch.linkage(ssd.pdist(X), 'single'), sch.linkage(ssd.pdist(X), 'average'), sch.linkage(X, 'ward'))))
W, _ = run(f"X = {Xs}; Z = linkage(X, 'average'); T = cluster(Z, 'MaxClust', 3); T2 = cluster(Z, 'Cutoff', 1.2); Td = cluster(Z, 'Cutoff', 3, 'Criterion', 'distance'); "
           "[c, dd] = cophenet(Z, pdist(X)); Y = inconsistent(Z); o = optimalleaforder(Z, pdist(X)); T3 = clusterdata(X, 'MaxClust', 3, 'Linkage', 'average'); "
           "f = figure('Visible', 'off'); [H, TT, perm] = dendrogram(Z, 0); nh = numel(H); [H2, T30, p30] = dendrogram(Z);")
Zs = sch.linkage(X, 'average')
same('cluster MaxClust: the partition fcluster gives', partition(W['T']), partition(sch.fcluster(Zs, 3, 'maxclust')))
same('cluster by inconsistency and by distance', (partition(W['T2']), partition(W['Td'])), (partition(sch.fcluster(Zs, 1.2, 'inconsistent')), partition(sch.fcluster(Zs, 3, 'distance'))))
near('cophenet and inconsistent (scipy)', (W['c'], W['dd'], W['Y']), (sch.cophenet(Zs, ssd.pdist(X))[0], sch.cophenet(Zs, ssd.pdist(X))[1].reshape(1, -1), sch.inconsistent(Zs)), 1e-10)
near('optimalleaforder (scipy optimal_leaf_ordering)', W['o'], sch.leaves_list(sch.optimal_leaf_ordering(Zs, ssd.pdist(X))).reshape(1, -1) + 1)
same('clusterdata: linkage and cluster', partition(W['T3']), partition(W['T']))
near('dendrogram: a line for each link, the leaves in scipy\'s order', (W['nh'], W['perm']), (74, sch.dendrogram(Zs, no_plot=True)['leaves'] + np.ones(75)), 0)
near('dendrogram of 75 points shows 30 leaves; T says which', (a(W['p30']).size, a(W['T30']).max()), (30, 30))
W, _ = run(f"idx = dbscan({Xs}, 1.2, 4); [~, core] = dbscan({Xs}, 1.2, 4);")
db = DBSCAN(eps=1.2, min_samples=4).fit(X)
same('dbscan: the clusters and the noise (scikit-learn DBSCAN)', (partition(a(W['idx']) - 1), list(np.flatnonzero(a(W['idx']).reshape(-1) == -1))),
     (partition(db.labels_), list(np.flatnonzero(db.labels_ == -1))))
same('dbscan core points', list(np.flatnonzero(a(W['core']).reshape(-1))), list(db.core_sample_indices_))
from sklearn.metrics import silhouette_samples, calinski_harabasz_score, davies_bouldin_score  # noqa: E402
lab = km.labels_ + 1
W, _ = run(f"s = silhouette({Xs}, {mat(lab).replace(';', ' ')}', 'Euclidean'); s2 = silhouette({Xs}, {mat(lab).replace(';', ' ')}'); "
           f"e = evalclusters({Xs}, {mat(np.column_stack([lab, (lab % 2) + 1]))}, 'CalinskiHarabasz'); ch = e.CriterionValues; ok = e.OptimalK; "
           f"e2 = evalclusters({Xs}, {mat(np.column_stack([lab, (lab % 2) + 1]))}, 'DaviesBouldin'); dbv = e2.CriterionValues; "
           f"rng(4); e3 = evalclusters({Xs}, 'kmeans', 'silhouette', 'KList', 2:4); k3 = e3.OptimalK;")
near('silhouette (scikit-learn silhouette_samples), Euclidean and squared Euclidean (unless given)', (W['s'], W['s2']),
     (silhouette_samples(X, lab).reshape(-1, 1), silhouette_samples(X, lab, metric='sqeuclidean').reshape(-1, 1)), 1e-10)
near('evalclusters: Calinski-Harabasz and Davies-Bouldin (scikit-learn), the best k', (W['ch'], W['dbv'], W['ok']),
     ([calinski_harabasz_score(X, lab), calinski_harabasz_score(X, (lab % 2) + 1)], [davies_bouldin_score(X, lab), davies_bouldin_score(X, (lab % 2) + 1)], 3), 1e-9)
near("evalclusters 'kmeans' by silhouette finds the three", W['k3'], 3)

from sklearn.mixture import GaussianMixture  # noqa: E402
W, _ = run(f"rng(5); gm = fitgmdist({Xs}, 3, 'Replicates', 3); nll = gm.NegativeLogLikelihood; P = posterior(gm, {Xs}); idx = cluster(gm, {Xs}); "
           f"p = pdf(gm, Xd(1:3, :)); mu = gm.mu; S = gm.Sigma; w = gm.ComponentProportion; aic = gm.AIC; bic = gm.BIC; R = random(gm, 5);")
skg = GaussianMixture(3, n_init=5, random_state=0, tol=1e-8, reg_covar=0).fit(X)
C('fitgmdist: a log-likelihood at least as good as scikit-learn GaussianMixture\'s best of five', W['nll'] <= -skg.score(X) * X.shape[0] + 1e-4, (W['nll'], -skg.score(X) * X.shape[0]))
same('cluster of a gmdistribution: the most probable component', list(a(W['idx']).reshape(-1)), list(np.argmax(a(W['P']), 1) + 1.0))
from scipy.stats import multivariate_normal  # noqa: E402
mu, S, w = a(W['mu']), a(W['S']), a(W['w']).reshape(-1)
pdf_ref = sum(w[k] * multivariate_normal.pdf(X[:3], mu[k], S[:, :, k]) for k in range(3))
near('pdf of the mixture; posteriors sum to one', (W['p'], a(W['P']).sum(1)), (pdf_ref.reshape(-1, 1), np.ones(75)), 1e-10)
near('AIC and BIC from the parameter count (3 means, 3 full covariances, 2 proportions)', (W['aic'], W['bic']),
     (2 * W['nll'] + 2 * 29, 2 * W['nll'] + 29 * math.log(75)), 1e-9)
raises("gm = gmdistribution([0 0; 4 3], eye(2)); pdf(gm, [1 2 3])", "a column for each of the mixture's 2 dimensions")
W, _ = run("close all; X = [randn(20, 2); randn(20, 2) + 6]; idx = [ones(20, 1); 2*ones(20, 1)]; silhouette(X, idx); b = findobj(gca, 'Type', 'bar'); "
           "nb = numel(b.YData); hz = b.Horizontal; xl = get(get(gca, 'XLabel'), 'String'); yd = get(gca, 'YDir');")
C('silhouette drawn: horizontal bars laid out by barh, a bar for each point, its axis labelled, clusters from the top',
  W['nb'] == 40 and W['hz'].str() == 'on' and W['xl'].str() == 'Silhouette Value' and W['yd'].str() == 'reverse', (W['nb'], W['hz'], W['xl'], W['yd']))
W, _ = run("close all; gm = gmdistribution([0 0; 4 3], eye(2)); fcontour(@(x, y) pdf(gm, [x y]), [-3 7 -4 8]); nk = numel(get(gca, 'Children'));")
C('fcontour of a function not written for arrays (pdf of a mixture at [x y]): evaluated point by point, drawn', W['nk'] >= 1, W['nk'])
W, _ = run("gm = gmdistribution([0 0; 5 5], cat(3, eye(2), 2*eye(2)), [0.3 0.7]); p = pdf(gm, [0 0; 5 5]); rng(1); r = random(gm, 2000); m = mean(r);")
near('gmdistribution made by hand: its pdf', W['p'], (0.3 * multivariate_normal.pdf([[0, 0], [5, 5]], [0, 0], np.eye(2)) + 0.7 * multivariate_normal.pdf([[0, 0], [5, 5]], [5, 5], 2 * np.eye(2))).reshape(-1, 1))
near('random from it: the mean near 0.3*0 + 0.7*5', W['m'], [[3.5, 3.5]], 0.15)
Xw = np.vstack([rs.randn(25, 3), rs.randn(25, 3) + [8, 0, 2], rs.randn(25, 3) + [0, 9, -4]])
W, _ = run(f"rng(6); idx = spectralcluster({mat(Xw)}, 3); rng(5); gm = fitgmdist({mat(Xw)}, 3); ig = cluster(gm, {mat(Xw)});")
same('spectralcluster and fitgmdist find three separate clusters', (partition(W['idx']), partition(W['ig'])), ([tuple(range(0, 25)), tuple(range(25, 50)), tuple(range(50, 75))],) * 2)

# ---- reducing dimensions -------------------------------------------------------------------------------------------------------------------------
from sklearn.decomposition import PCA  # noqa: E402
W, _ = run(f"[coeff, score, latent, t2, explained, mu] = pca({Xs}); [c2, s2] = pca({Xs}, 'NumComponents', 2); [cv, lv, ev] = pcacov(cov({Xs}));")
sk = PCA().fit(X)
cf = a(W['coeff'])
near('pca: the variances and their shares (scikit-learn PCA)', (W['latent'], W['explained']), (sk.explained_variance_.reshape(-1, 1), 100 * sk.explained_variance_ratio_.reshape(-1, 1)), 1e-10)
near('pca: the components (each column\'s largest element positive)', np.abs(cf), np.abs(sk.components_.T), 1e-10)
C(' and the sign rule holds', np.all(cf[np.argmax(np.abs(cf), axis=0), np.arange(3)] > 0), cf)
near('pca: scores = centred X * coeff, mu the mean, Hotelling T^2', (W['score'], W['mu'], W['t2']),
     ((X - X.mean(0)) @ cf, X.mean(0).reshape(1, -1), np.sum(((X - X.mean(0)) @ cf) ** 2 / sk.explained_variance_, 1).reshape(-1, 1)), 1e-9)
near("'NumComponents' 2; pcacov of the covariance", (np.abs(a(W['c2'])), W['lv']), (np.abs(cf[:, :2]), sk.explained_variance_.reshape(-1, 1)), 1e-9)
W, _ = run(f"rng(7); [coeff, score, pcvar, mu, v] = ppca({Xs}, 2);")
P1 = a(W['coeff'])
ang = np.linalg.svd(P1.T @ sk.components_[:2].T, compute_uv=False)
near('ppca on complete data: the plane of the first two principal components', ang, [1, 1], 1e-4)
near('and its noise variance: the mean of the variances left out', W['v'], sk.explained_variance_[2:].mean() * 74 / 75, 1e-3)
W, _ = run(f"D = pdist({Xs}); [Y, e] = cmdscale(D); DY = pdist(Y); [Ym, stress] = mdscale(D, 3, 'Criterion', 'metricstress'); "
           f"[Yn, sn, disp] = mdscale(D, 2); dn = pdist(Yn);")
near('cmdscale of Euclidean distances gives them back exactly', W['DY'], ssd.pdist(X).reshape(1, -1), 1e-9)
C("mdscale 'metricstress' in three dimensions: stress near zero", W['stress'] < 1e-4, W['stress'])
dd, dsp = ssd.pdist(X), a(W['disp']).reshape(-1)
C('nonmetric mdscale: the disparities in the order of the dissimilarities', np.all(np.diff(dsp[np.argsort(dd, kind='stable')]) >= -1e-9), None)
from scipy.spatial import procrustes as sp_proc  # noqa: E402
Y2 = X[:, :2] @ np.array([[0.6, -0.8], [0.8, 0.6]]) * 2 + 3 + 0.01 * rs.randn(75, 2)
W, _ = run(f"[d, Z, tr] = procrustes({mat(X[:, :2])}, {mat(Y2)}); b = tr.b;")
near('procrustes: d as scipy.spatial.procrustes gives its disparity', W['d'], sp_proc(X[:, :2], Y2)[2], 1e-10)
near('and the scale found (1/2)', W['b'], 0.5, 1e-2)
W, _ = run(f"[A, B, r, U, V] = canoncorr({mat(X[:, :2])}, {mat(X[:, 2:])}); cU = corr(U, V);")
Xc, Yc = X[:, :2] - X[:, :2].mean(0), X[:, 2:] - X[:, 2:].mean(0)
r_ref = np.linalg.svd(np.linalg.qr(Xc)[0].T @ np.linalg.qr(Yc)[0], compute_uv=False)
near('canoncorr: the canonical correlations, and the variates correlate by them', (W['r'], a(W['cU']).reshape(-1)[0]), (r_ref.reshape(1, -1), r_ref[0]), 1e-10)
W, _ = run(f"rng(8); Y = tsne({Xs}, 'Perplexity', 10); [~, Dk] = knnsearch(Y, Y, 'K', 6);")
from sklearn.manifold import trustworthiness  # noqa: E402
C('tsne keeps neighbours together (trustworthiness over 0.9)', trustworthiness(X, a(W['Y']), n_neighbors=5) > 0.9, trustworthiness(X, a(W['Y']), n_neighbors=5))
A_ = np.abs(X)
W, _ = run(f"rng(9); [Wn, Hn, Dn] = nnmf({mat(A_)}, 2); [Wm, Hm, Dm] = nnmf({mat(A_)}, 2, 'Algorithm', 'mult', 'Replicates', 3);")
Wn, Hn = a(W['Wn']), a(W['Hn'])
C('nnmf: W and H not negative, H\'s rows of unit length, D the rms residual', np.all(Wn >= 0) and np.all(Hn >= 0) and np.allclose(np.linalg.norm(Hn, axis=1), 1)
  and abs(W['Dn'] - np.linalg.norm(A_ - Wn @ Hn) / math.sqrt(A_.size)) < 1e-12, (W['Dn'],))
C('nnmf of rank 2 nearly as good as the best rank 2 (the SVD)', W['Dn'] < 1.6 * np.linalg.norm(A_ - (lambda u, s, v: (u[:, :2] * s[:2]) @ v[:2])(*np.linalg.svd(A_, full_matrices=False))) / math.sqrt(A_.size), W['Dn'])
W, _ = run(f"[R, s] = corrcov(cov({Xs}));")
near('corrcov', (W['R'], W['s']), (np.corrcoef(X, rowvar=False), np.std(X, axis=0, ddof=1).reshape(-1, 1)), 1e-12)
F = rs.randn(200, 2)
L = np.array([[0.9, 0], [0.8, 0.1], [0.7, 0.2], [0, 0.9], [0.1, 0.8], [0.2, 0.7]])
Xf = F @ L.T + 0.3 * rs.randn(200, 6)
W, _ = run(f"[lam, psi, T, stats] = factoran({mat(Xf)}, 2); p = stats.p; [B, T2] = rotatefactors(lam, 'Method', 'promax');")
lam, psi = a(W['lam']), a(W['psi']).reshape(-1)
Rf = np.corrcoef(Xf, rowvar=False)
C('factoran: the model lam*lam\' + diag(psi) fits the correlations', np.max(np.abs(lam @ lam.T + np.diag(psi) - Rf)) < 0.08, np.max(np.abs(lam @ lam.T + np.diag(psi) - Rf)))
C('varimax: each variable loads mainly on one factor, as made', sorted(np.argmax(np.abs(lam), axis=1)[:3].tolist()) == [int(np.argmax(np.abs(lam[0])))] * 3, lam)
C('factoran stats: a p-value; promax rotates', 0 <= W['p'] <= 1 and a(W['T2']).shape == (2, 2), W['p'])
raises("kmeans([1 2; 3 4], 3)", 'fewer rows than k')
raises("linkage([1 2; 3 4], 'nearest')", "The method is")
raises("pdist([1 2; 3 4], 'manhattan')", 'is not a distance')

# ---- classification -----------------------------------------------------------------------------------------------------------------------------
yb = np.r_[np.zeros(25), np.ones(25), np.ones(25)]
y3 = np.r_[np.zeros(25), np.ones(25), 2 * np.ones(25)]
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor  # noqa: E402
W, _ = run(f"t = fitctree({Xs}, {mat(y3).replace(';', ' ')}'); [l, s] = predict(t, {Xs}); e = resubLoss(t); n = t.NumNodes; "
           f"t1 = fitctree({Xs}, {mat(y3).replace(';', ' ')}', 'MinParentSize', 2); e1 = resubLoss(t1);")
skt = DecisionTreeClassifier(min_samples_split=10, random_state=0).fit(X, y3)
near('fitctree (MinParentSize 10): the resubstitution error of scikit-learn\'s tree split as far', W['e'], 1 - skt.score(X, y3), 1e-12)
near('a full tree (MinParentSize 2): no training error', W['e1'], 0)
from sklearn.neighbors import KNeighborsClassifier  # noqa: E402
W, _ = run(f"k = fitcknn({Xs}, {mat(y3).replace(';', ' ')}', 'NumNeighbors', 5); [l, s] = predict(k, Xd(1:20, :) + 0.3);")
kn = KNeighborsClassifier(5).fit(X, y3)
near('fitcknn: the neighbours\' votes (scikit-learn KNeighborsClassifier)', W['s'], kn.predict_proba(X[:20] + 0.3), 1e-12)
from sklearn.discriminant_analysis import QuadraticDiscriminantAnalysis, LinearDiscriminantAnalysis  # noqa: E402
W, _ = run(f"q = fitcdiscr({Xs}, {mat(y3).replace(';', ' ')}', 'DiscrimType', 'quadratic'); [l, s] = predict(q, {Xs}); "
           f"d = fitcdiscr({Xs}, {mat(y3).replace(';', ' ')}'); [ld, sd] = predict(d, {Xs});")
near('fitcdiscr quadratic: the posteriors (scikit-learn QDA)', W['s'], QuadraticDiscriminantAnalysis().fit(X, y3).predict_proba(X), 1e-9)
near('fitcdiscr linear: the classes (scikit-learn LDA)', W['ld'], LinearDiscriminantAnalysis().fit(X, y3).predict(X).reshape(-1, 1))
mus = np.array([X[y3 == c].mean(0) for c in range(3)])
Sp = sum((X[y3 == c] - mus[c]).T @ (X[y3 == c] - mus[c]) for c in range(3)) / (75 - 3)
lp = np.column_stack([multivariate_normal.logpdf(X, mus[c], Sp) for c in range(3)]) + np.log(1 / 3)
post = np.exp(lp - lp.max(1, keepdims=True))
near('fitcdiscr linear: the posteriors with the pooled covariance (n - K)', W['sd'], post / post.sum(1, keepdims=True), 1e-9)
W, _ = run(f"nb = fitcnb({Xs}, {mat(y3).replace(';', ' ')}'); [l, s] = predict(nb, Xd(1:5, :));")
from scipy.stats import norm  # noqa: E402
lpn = np.column_stack([np.log(1 / 3) + norm.logpdf(X[:5], X[y3 == c].mean(0), X[y3 == c].std(0, ddof=1)).sum(1) for c in range(3)])
pn = np.exp(lpn - lpn.max(1, keepdims=True))
near('fitcnb: normal per class and variable (unbiased sd)', W['s'], pn / pn.sum(1, keepdims=True), 1e-10)
from sklearn.svm import SVC, SVR  # noqa: E402
for kf, skk in (('linear', 'linear'), ('gaussian', 'rbf'), ('polynomial', 'poly')):
    W, _ = run(f"s = fitcsvm({Xs}, {mat(yb).replace(';', ' ')}', 'KernelFunction', '{kf}', 'BoxConstraint', 0.5, 'DeltaGradientTolerance', 1e-8); [l, sc] = predict(s, {Xs}); b = s.Bias;")
    svc = SVC(kernel=skk, C=0.5, gamma=1.0, coef0=1, degree=3, tol=1e-10).fit(X, yb)
    near(f'fitcsvm {kf}: the decision values (scikit-learn SVC)', a(W['sc'])[:, 1], svc.decision_function(X), 1e-5)
yr = X[:, 0] ** 2 + np.sin(X[:, 1])
q = np.subtract(*np.percentile(yr, [75, 25]))
W, _ = run(f"r = fitrsvm({Xs}, {mat(yr).replace(';', ' ')}', 'KernelFunction', 'gaussian', 'DeltaGradientTolerance', 1e-8); p = predict(r, {Xs}); e = r.Epsilon;")
svr = SVR(kernel='rbf', C=q / 1.349, epsilon=q / 13.49, gamma=1.0, tol=1e-10).fit(X, yr)
near('fitrsvm: BoxConstraint iqr/1.349 and Epsilon iqr/13.49 unless given; predictions (scikit-learn SVR)', (W['e'], a(W['p']).reshape(-1)), (q / 13.49, svr.predict(X)), 1e-5)
from sklearn.linear_model import LogisticRegression  # noqa: E402
W, _ = run(f"l = fitclinear({Xs}, {mat(yb).replace(';', ' ')}', 'Learner', 'logistic', 'Lambda', 0.01); b = l.Beta; c = l.Bias;")
lr = LogisticRegression(C=1 / (75 * 0.01), tol=1e-10, max_iter=10000).fit(X, yb)
near("fitclinear 'logistic': (1/n) sum loss + lambda/2 |b|^2 (scikit-learn with C = 1/(n lambda))", (W['b'], W['c']), (lr.coef_.reshape(-1, 1), lr.intercept_[0]), 1e-4)
W, _ = run(f"l = fitrlinear({Xs}, {mat(yr).replace(';', ' ')}', 'Learner', 'leastsquares', 'Lambda', 0.1); b = l.Beta; c = l.Bias;")
Xm = X - X.mean(0)
beta_ref = np.linalg.solve(Xm.T @ Xm / 75 + 0.1 * np.eye(3), Xm.T @ (yr - yr.mean()) / 75)
near("fitrlinear 'leastsquares' ridge: the closed form (the bias free)", (W['b'], W['c']), (beta_ref.reshape(-1, 1), yr.mean() - X.mean(0) @ beta_ref), 1e-5)
W, _ = run(f"l = fitclinear({Xs}, {mat(yb).replace(';', ' ')}'); e = resubLoss(l); l2 = fitclinear({Xs}, {mat(yb).replace(';', ' ')}', 'Learner', 'logistic', 'Regularization', 'lasso', 'Lambda', 0.05); b2 = l2.Beta;")
from sklearn.svm import LinearSVC  # noqa: E402
C("fitclinear 'svm' (dual coordinate descent): about as good as scikit-learn's LinearSVC", W['e'] <= 1 - LinearSVC(C=1.0).fit(X, yb).score(X, yb) + 0.03, W['e'])
C('lasso: some coefficients exactly zero', np.sum(np.abs(a(W['b2'])) < 1e-8) >= 1, W['b2'])
from sklearn.gaussian_process import GaussianProcessRegressor  # noqa: E402
from sklearn.gaussian_process.kernels import RBF, ConstantKernel as Ck, WhiteKernel  # noqa: E402
ygp = np.sin(X[:, 0]) + 0.05 * rs.randn(75)
W, _ = run(f"g = fitrgp({Xs}, {mat(ygp).replace(';', ' ')}', 'BasisFunction', 'none'); ll = g.LogLikelihood; [p, sdv] = predict(g, Xd(1:5, :)); sg = g.Sigma;")
gp = GaussianProcessRegressor(Ck() * RBF() + WhiteKernel(), n_restarts_optimizer=5, random_state=0).fit(X, ygp)
C('fitrgp: the log marginal likelihood at least scikit-learn\'s (its optimum)', W['ll'] >= gp.log_marginal_likelihood_value_ - 1e-4, (W['ll'], gp.log_marginal_likelihood_value_))
near('and its predictions near scikit-learn\'s', a(W['p']).reshape(-1), gp.predict(X[:5]), 0.02)
near('the noise sd found (0.05)', W['sg'], 0.05, 0.03)
W, _ = run(f"rng(10); e = fitcecoc({Xs}, {mat(y3).replace(';', ' ')}'); l = resubLoss(e); M = e.CodingMatrix; e2 = fitcecoc({Xs}, {mat(y3).replace(';', ' ')}', 'Coding', 'onevsall', 'Learners', templateTree('MaxNumSplits', 5)); l2 = resubLoss(e2); M2 = e2.CodingMatrix;")
near('fitcecoc: one-vs-one SVMs, the coding matrix; one-vs-all trees', (W['M'], W['M2']), ([[1, 1, 0], [-1, 0, 1], [0, -1, -1]], 2 * np.eye(3) - 1))
C('and both fit these classes', W['l'] < 0.05 and W['l2'] < 0.05, (W['l'], W['l2']))
W, _ = run(f"rng(11); a1 = fitcensemble({Xs}, {mat(yb).replace(';', ' ')}'); m1 = a1.Method; e1 = resubLoss(a1); "
           f"a2 = fitcensemble({Xs}, {mat(y3).replace(';', ' ')}'); m2 = a2.Method; e2 = resubLoss(a2); "
           f"b = fitcensemble({Xs}, {mat(y3).replace(';', ' ')}', 'Method', 'Bag', 'NumLearningCycles', 50); o = oobLoss(b); "
           f"g = fitcensemble({Xs}, {mat(yb).replace(';', ' ')}', 'Method', 'LogitBoost', 'NumLearningCycles', 30); eg = resubLoss(g); "
           f"r = fitrensemble({Xs}, {mat(yr).replace(';', ' ')}'); er = resubLoss(r); rt = resubLoss(fitrtree({Xs}, {mat(yr).replace(';', ' ')}', 'MaxNumSplits', 10));")
same('fitcensemble: AdaBoostM1 for two classes, AdaBoostM2 for three', (W['m1'].str(), W['m2'].str()), ('AdaBoostM1', 'AdaBoostM2'))
C('boosting fits, bagging predicts out of bag, LogitBoost fits', W['e1'] < 0.02 and W['e2'] < 0.05 and W['o'] < 0.15 and W['eg'] < 0.05, (W['e1'], W['e2'], W['o'], W['eg']))
C('fitrensemble (LSBoost) fits better than one of its trees', W['er'] < 0.5 * W['rt'], (W['er'], W['rt']))
W, _ = run(f"rng(12); n = fitcnet({Xs}, {mat(y3).replace(';', ' ')}', 'LayerSizes', [8 4]); e = resubLoss(n); ls = n.LayerSizes; "
           f"rng(12); r = fitrnet({Xs}, {mat(yr).replace(';', ' ')}', 'Standardize', true); er = resubLoss(r);")
C('fitcnet fits the three classes; fitrnet the regression', W['e'] < 0.03 and W['er'] < 0.1 * np.var(yr), (W['e'], W['er']))
W, _ = run(f"rng(13); k = fitckernel({Xs}, {mat(yb).replace(';', ' ')}'); e = resubLoss(k); rk = fitrkernel({Xs}, {mat(yr).replace(';', ' ')}', 'Learner', 'leastsquares'); er = resubLoss(rk);")
C('fitckernel and fitrkernel (random features) fit', W['e'] < 0.1 and W['er'] < np.var(yr), (W['e'], W['er']))
W, _ = run(f"rng(14); tb = TreeBagger(30, {Xs}, {mat(y3).replace(';', ' ')}'); [l, s] = predict(tb, Xd(1:3, :)); cl = class(l); o = oobLoss(tb);")
same('TreeBagger: predictions as text', (W['cl'].str(), [x.str() for x in W['l'].a.reshape(-1)]), ('cell', ['0', '0', '0']))
labels_txt = ['red'] * 25 + ['green'] * 25 + ['blue'] * 25
W, _ = run(f"y = [repmat({{'red'}}, 25, 1); repmat({{'green'}}, 25, 1); repmat({{'blue'}}, 25, 1)]; t = fitctree({Xs}, y); cn = t.ClassNames; [l, s] = predict(t, Xd(26, :)); "
           f"c = categorical(y); tc = fitcknn({Xs}, c); lc = predict(tc, Xd(1, :)); lcc = class(lc); "
           f"T = array2table({Xs}, 'VariableNames', {{'a', 'b', 'c'}}); T.y = y; tt = fitctree(T, 'y ~ a + b'); pn = tt.PredictorNames; lt = predict(tt, T(1:2, :));")
same('text classes, in order; predictions of the same kind; categorical; a table with a formula',
     ([x.str() for x in W['cn'].a.reshape(-1)], W['l'].a[0, 0].str(), W['lcc'].str(), [x.str() for x in W['pn'].a.reshape(-1)]),
     (['blue', 'green', 'red'], 'green', 'categorical', ['a', 'b']))

# ---- partitions, cross-validation, evaluation --------------------------------------------------------------------------------------------------
W, _ = run(f"rng(15); c = cvpartition(75, 'KFold', 5); ts = c.TestSize; tr1 = training(c, 1); te1 = test(c, 1); "
           f"g = [ones(60, 1); 2*ones(15, 1)]; cs = cvpartition(g, 'KFold', 5); share = arrayfun(@(i) mean(g(test(cs, i)) == 2), 1:5); "
           f"h = cvpartition(100, 'HoldOut', 0.3); hs = h.TestSize; lo = cvpartition(10, 'Leaveout'); ln = lo.NumTestSets;")
near('cvpartition: k folds of equal size, training and test complementary', (W['ts'], np.all(a(W['tr1']) != a(W['te1']))), ([[15, 15, 15, 15, 15]], 1))
near('stratified by a grouping: each fold a fifth of the second group', W['share'], [[0.2] * 5], 1e-12)
near('hold-out and leave-one-out', (W['hs'], W['ln']), (30, 10))
W, _ = run(f"rng(16); m = fitcknn({Xs}, {mat(y3).replace(';', ' ')}', 'NumNeighbors', 3); c = cvpartition({mat(y3).replace(';', ' ')}', 'KFold', 5); cv = crossval(m, 'CVPartition', c); "
           f"L = kfoldLoss(cv); Li = kfoldLoss(cv, 'Mode', 'individual'); lp = kfoldPredict(cv); "
           f"y = {mat(y3).replace(';', ' ')}'; X = {Xs}; err = 0; for i = 1:5, tr = training(c, i); te = test(c, i); mi = fitcknn(X(tr, :), y(tr), 'NumNeighbors', 3); err = err + sum(predict(mi, X(te, :)) ~= y(te)); end; err = err / 75; "
           f"cv2 = fitcknn(X, y, 'NumNeighbors', 3, 'CVPartition', c); L2 = kfoldLoss(cv2); cls = class(cv);")
near('kfoldLoss: each fold\'s model on the observations it left out; the same as by hand, and as the fit with CVPartition', (W['L'], W['L2']), (W['err'], W['err']), 1e-12)
same('the cross-validated model\'s class', W['cls'].str(), 'ClassificationPartitionedModel')
W, _ = run(f"rng(17); v = crossval(@(xtr, ytr, xte, yte) numel(yte), {Xs}, {mat(y3).replace(';', ' ')}', 'KFold', 5); "
           f"mse = crossval('mse', {Xs}, {mat(yr).replace(';', ' ')}', 'Predfun', @(xtr, ytr, xte) xte * (xtr \\ ytr), 'KFold', 5);")
near('crossval of a function: a value for each fold', W['v'], np.full((5, 1), 15))
C("crossval('mse', ..., 'Predfun', f): the mean squared error of the folds", W['mse'] > 0, W['mse'])
from sklearn.metrics import confusion_matrix, roc_auc_score, roc_curve  # noqa: E402
pred = (X[:, 0] > 2).astype(float)
W, _ = run(f"[Cm, order] = confusionmat({mat(yb).replace(';', ' ')}', {mat(pred).replace(';', ' ')}'); [Ct, ot] = confusionmat({{'a'; 'b'; 'a'}}, {{'b'; 'b'; 'a'}}); ott = ot';")
near('confusionmat (scikit-learn confusion_matrix)', (W['Cm'], W['order']), (confusion_matrix(yb, pred), [[0], [1]]))
same('of text, in order', ([x.str() for x in W['ott'].a.reshape(-1)], a(W['Ct']).tolist()), (['a', 'b'], [[1.0, 1.0], [0.0, 1.0]]))
sc = X[:, 0] + 0.5 * rs.randn(75)
W, _ = run(f"[fx, fy, t, auc, opt] = perfcurve({mat(yb).replace(';', ' ')}', {mat(sc).replace(';', ' ')}', 1); [rx, ry, ~, aupr] = perfcurve({mat(yb).replace(';', ' ')}', {mat(sc).replace(';', ' ')}', 1, 'XCrit', 'reca', 'YCrit', 'prec');")
fpr, tpr, _ = roc_curve(yb, sc, drop_intermediate=False)
near('perfcurve: the ROC curve and its area (scikit-learn roc_curve, roc_auc_score)', (W['fx'], W['fy'], W['auc']), (fpr.reshape(-1, 1), tpr.reshape(-1, 1), roc_auc_score(yb, sc)), 1e-12)
C('other criteria: precision against recall', 0 < W['aupr'] <= 1, W['aupr'])
W, out = run(f"f = figure('Visible', 'off'); cm = confusionchart({mat(yb).replace(';', ' ')}', {mat(pred).replace(';', ' ')}'); v = cm.NormalizedValues; cm.Normalization = 'row-normalized'; v2 = cm.NormalizedValues; "
             f"view(fitctree({Xs}, {mat(y3).replace(';', ' ')}', 'MaxNumSplits', 2))")
near('confusionchart: its values, normalized by row when asked', (W['v'], a(W['v2']).sum(1)), (confusion_matrix(yb, pred), [1, 1]), 1e-12)
same('view of a tree: its rules', 'Decision tree for classification' in out and 'then node 2' in out, True)
raises("fitcsvm(rand(9, 2), [1 1 1 2 2 2 3 3 3]')", 'two classes')
raises("fitcknn(rand(4, 2), [1 2 1]')", 'as many rows')
raises("fitctree(rand(4, 2), [1 2 1 2]', 'Depth', 3)", "is not an option of fitctree")
raises("kfoldLoss(fitctree(rand(4, 2), [1 2 1 2]'))", 'cross-validated model')

# corrcov: a zero variance leaves NaN, its diagonal too; single stays single
W, _ = run("z = corrcov(zeros(2)); z1 = corrcov([4 0; 0 0]); sg = corrcov(single([4 2; 2 9]));")
near('corrcov of zero variances: NaN in their rows and columns, the diagonal too', (W['z'], W['z1']), (np.full((2, 2), np.nan), [[1, np.nan], [np.nan, np.nan]]))
same('corrcov of single is single', np.asarray(W['sg']).dtype.name, 'float32')
near('corrcov of single: the correlation', W['sg'], [[1, 1 / 3], [1 / 3, 1]], 1e-6)

sys.exit(C.done())
