"""Statistics and machine learning, without a response: distances (pdist,
pdist2, squareform, knnsearch, rangesearch), clustering (kmeans,
kmedoids, linkage, cluster, clusterdata, dendrogram, cophenet,
inconsistent, optimalleaforder, dbscan, spectralcluster, fitgmdist and
gmdistribution, silhouette, evalclusters), and reducing dimensions (pca,
pcacov, ppca, factoran, rotatefactors, cmdscale, mdscale, tsne,
procrustes, canoncorr, barttest, nnmf, corrcov).

Random starts (kmeans++, t-SNE, nnmf, ...) draw from the generator rng
sets, so a seed repeats a result."""
import math

import numpy as np

from . import bi as _register, REG
from ._util import err, nargchk, num, is_str, darr, out, arr
from ..values import MError, Obj, FH, Char, Cell, Struct, EMPTY, numel, py_str, text_list
from .. import runtime as R


def bi(*names, **kw):
    kw.setdefault('arr', False)

    def deco(f):
        def g(*a):
            try:
                return f(*a)
            except MError:
                raise
            except (ValueError, TypeError, IndexError, np.linalg.LinAlgError) as e:
                raise err(f'stats:{names[0]}:invalidInput', f'{names[0]}: {e}', names[0])
        g.__name__, g.__doc__ = f.__name__, f.__doc__
        return _register(*names, **kw)(g)
    return deco


def _rs():
    from .elmat import RNG
    return RNG.rs


def _mat(v, fn, what='X'):
    a = np.asarray(darr(v), float)
    if a.ndim != 2:
        raise err(f'stats:{fn}:matrix', f'{what} is a matrix, a row for each observation.', fn)
    return a


def _pairs(args, fn, names):
    """Name-value pairs, names matched without regard to case: {lower name: value}."""
    if len(args) % 2:
        raise err(f'stats:{fn}:pairs', f'The options of {fn} come as names and values.', fn)
    o = {}
    for i in range(0, len(args), 2):
        k = py_str(args[i]).lower()
        if k not in names:
            raise err(f'stats:{fn}:option', f"'{py_str(args[i])}' is not an option of {fn}.", fn)
        o[k] = args[i + 1]
    return o


def _flag(v):
    if is_str(v):
        return py_str(v).lower() in ('on', 'true', 'yes')
    return bool(np.all(darr(v)))


def _int(v):
    return int(round(float(num(v))))


# ---- distances ------------------------------------------------------------------------------------------------------------------------

_SCIPY = {'euclidean': 'euclidean', 'squaredeuclidean': 'sqeuclidean', 'seuclidean': 'seuclidean', 'cityblock': 'cityblock',
          'minkowski': 'minkowski', 'chebychev': 'chebyshev', 'mahalanobis': 'mahalanobis', 'cosine': 'cosine',
          'correlation': 'correlation', 'spearman': 'correlation', 'hamming': 'hamming', 'jaccard': 'jaccard'}


def _metric(args, X, fn):
    """(name, scipy keyword arguments, a function handle or None) from the distance argument(s)."""
    if not args:
        return 'euclidean', {}, None
    d = args[0]
    if isinstance(d, FH):
        return 'custom', {}, d
    name = py_str(d).lower()
    name = {'sqeuclidean': 'squaredeuclidean', 'chebyshev': 'chebychev'}.get(name, name)
    if name not in _SCIPY:
        raise err(f'stats:{fn}:distance', f"'{py_str(d)}' is not a distance: euclidean, squaredeuclidean, seuclidean, cityblock, minkowski, chebychev, mahalanobis, cosine, correlation, spearman, hamming, jaccard, or a function handle.", fn)
    kw = {}
    p = args[1] if len(args) > 1 else None
    if name == 'minkowski':
        kw['p'] = float(num(p)) if p is not None else 2.0
    elif name == 'seuclidean':
        s = np.asarray(darr(p), float).reshape(-1) if p is not None else np.std(X, axis=0, ddof=1)
        kw['V'] = s ** 2
    elif name == 'mahalanobis':
        C = np.asarray(darr(p), float) if p is not None else np.cov(X, rowvar=False)
        kw['VI'] = np.linalg.inv(np.atleast_2d(C))
    return name, kw, None


def _ranks(X):
    from scipy.stats import rankdata
    return np.apply_along_axis(rankdata, 1, X)


def _cdist(XA, XB, name, kw, fh):
    from scipy.spatial.distance import cdist
    if fh is not None:
        D = np.empty((XA.shape[0], XB.shape[0]))
        for i in range(XA.shape[0]):
            D[i] = np.asarray(darr(fh.scall(1, out(XA[i:i + 1]), out(XB))), float).reshape(-1)
        return D
    if name == 'spearman':
        XA, XB = _ranks(XA), _ranks(XB)
    return cdist(XA, XB, _SCIPY[name], **kw)


def _pdist(X, name, kw, fh):
    from scipy.spatial.distance import pdist as sp_pdist
    if fh is not None:
        n = X.shape[0]
        outv = []
        for i in range(n - 1):
            outv.append(np.asarray(darr(fh.scall(1, out(X[i:i + 1]), out(X[i + 1:]))), float).reshape(-1))
        return np.concatenate(outv) if outv else np.zeros(0)
    if name == 'spearman':
        X = _ranks(X)
    return sp_pdist(X, _SCIPY[name], **kw)


@bi('pdist')
def pdist(nargout, *args):
    """D = pdist(X), pdist(X, distance), pdist(X, 'minkowski', p): the distance between each pair of rows, a row in the order (1,2), (1,3), ..., (2,3), ..."""
    nargchk(args, 1, 3, 'pdist')
    X = _mat(args[0], 'pdist')
    name, kw, fh = _metric(args[1:], X, 'pdist')
    return out(_pdist(X, name, kw, fh).reshape(1, -1))


@bi('pdist2', nout=2)
def pdist2(nargout, *args):
    """D = pdist2(X, Y), pdist2(X, Y, distance, param), [D, I] = pdist2(..., 'Smallest', K): the distance from each row of X to each row of Y (or the K smallest in each column)."""
    nargchk(args, 2, 6, 'pdist2')
    X, Y = _mat(args[0], 'pdist2'), _mat(args[1], 'pdist2', 'Y')
    if X.shape[1] != Y.shape[1]:
        raise err('stats:pdist2:SizeMismatch', 'X and Y have as many columns.', 'pdist2')
    rest = list(args[2:])
    k, largest = None, False
    if len(rest) >= 2 and is_str(rest[-2]) and py_str(rest[-2]).lower() in ('smallest', 'largest'):
        largest = py_str(rest[-2]).lower() == 'largest'
        k = _int(rest[-1])
        rest = rest[:-2]
    name, kw, fh = _metric(rest, X, 'pdist2')
    if name == 'seuclidean' and len(rest) < 2:
        kw['V'] = np.var(X, axis=0, ddof=1)
    if name == 'mahalanobis' and len(rest) < 2:
        kw['VI'] = np.linalg.inv(np.atleast_2d(np.cov(X, rowvar=False)))
    D = _cdist(X, Y, name, kw, fh)
    if k is None:
        return out(D)
    order = np.argsort(-D if largest else D, axis=0, kind='stable')[:k]
    Dk = np.take_along_axis(D, order, axis=0)
    return (out(Dk), out(order + 1.0)) if nargout > 1 else out(Dk)


@bi('squareform')
def squareform(nargout, *args):
    """Z = squareform(y): a distance row (pdist) as the square matrix, or a square matrix (zero diagonal) as the row; squareform(..., 'tovector'|'tomatrix')."""
    nargchk(args, 1, 2, 'squareform')
    from scipy.spatial.distance import squareform as sq
    a = np.asarray(darr(args[0]), float)
    force = py_str(args[1]).lower() if len(args) > 1 else 'no'
    if force == 'tovector' or (force == 'no' and a.ndim == 2 and a.shape[0] == a.shape[1] and a.shape[0] > 1):
        return out(sq(a, force='tovector', checks=False).reshape(1, -1))
    return out(sq(a.reshape(-1), force='tomatrix', checks=False))


@bi('knnsearch', nout=2)
def knnsearch(nargout, *args):
    """[Idx, D] = knnsearch(X, Y), knnsearch(..., 'K', k, 'Distance', d, 'P', p, 'Scale', s, 'Cov', C): for each row of Y, the rows of X nearest it (nearest first)."""
    nargchk(args, 2, 12, 'knnsearch')
    X, Y = _mat(args[0], 'knnsearch'), _mat(args[1], 'knnsearch', 'Y')
    o = _pairs(args[2:], 'knnsearch', ('k', 'distance', 'p', 'scale', 'cov', 'nsmethod', 'includeties', 'bucketsize', 'sortindices'))
    k = _int(o.get('k', 1.0))
    margs = [o['distance']] if 'distance' in o else []
    if margs:
        nm = py_str(margs[0]).lower() if not isinstance(margs[0], FH) else ''
        extra = o.get('p') if nm == 'minkowski' else o.get('scale') if nm == 'seuclidean' else o.get('cov') if nm == 'mahalanobis' else None
        if extra is not None:
            margs.append(extra)
    name, kw, fh = _metric(margs, X, 'knnsearch')
    D = _cdist(Y, X, name, kw, fh)
    order = np.argsort(D, axis=1, kind='stable')[:, :k]
    Dk = np.take_along_axis(D, order, axis=1)
    return (out(order + 1.0), out(Dk)) if nargout > 1 else out(order + 1.0)


@bi('rangesearch', nout=2)
def rangesearch(nargout, *args):
    """[Idx, D] = rangesearch(X, Y, r), rangesearch(..., 'Distance', d): for each row of Y, the rows of X within r of it, nearest first (cells)."""
    nargchk(args, 3, 9, 'rangesearch')
    X, Y = _mat(args[0], 'rangesearch'), _mat(args[1], 'rangesearch', 'Y')
    r = float(num(args[2]))
    o = _pairs(args[3:], 'rangesearch', ('distance', 'p', 'scale', 'cov', 'nsmethod', 'bucketsize', 'sortindices'))
    margs = [o['distance']] if 'distance' in o else []
    name, kw, fh = _metric(margs, X, 'rangesearch')
    D = _cdist(Y, X, name, kw, fh)
    I, Dd = Cell.empty((Y.shape[0], 1)), Cell.empty((Y.shape[0], 1))
    for i in range(Y.shape[0]):
        idx = np.flatnonzero(D[i] <= r)
        idx = idx[np.argsort(D[i, idx], kind='stable')]
        I.a[i, 0] = out(idx.reshape(1, -1) + 1.0)
        Dd.a[i, 0] = out(D[i, idx].reshape(1, -1))
    return (I, Dd) if nargout > 1 else I


# ---- k-means and k-medoids ----------------------------------------------------------------------------------------------------------------

def _kmeans_dist(X, C, dist):
    if dist == 'sqeuclidean':
        return ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1)
    if dist == 'cityblock':
        return np.abs(X[:, None, :] - C[None, :, :]).sum(-1)
    if dist in ('cosine', 'correlation'):
        return 1 - X @ C.T
    if dist == 'hamming':
        return (X[:, None, :] != C[None, :, :]).mean(-1)
    raise ValueError(dist)


def _kmeans_center(Xk, dist):
    if dist == 'sqeuclidean':
        return Xk.mean(0)
    if dist == 'cityblock':
        return np.median(Xk, axis=0)
    if dist in ('cosine', 'correlation'):
        c = Xk.mean(0)
        nrm = np.linalg.norm(c)
        return c / nrm if nrm > 0 else c
    return (Xk.mean(0) >= 0.5).astype(float)


def _plus_start(X, k, dist, rs):
    n = X.shape[0]
    first = int(rs.randint(n))
    C = [X[first]]
    d = _kmeans_dist(X, np.array(C), dist)[:, 0]
    for _ in range(1, k):
        w = np.maximum(d, 0)
        if w.sum() <= 0:
            i = int(rs.randint(n))
        else:
            i = int(np.searchsorted(np.cumsum(w / w.sum()), rs.random_sample()))
            i = min(i, n - 1)
        C.append(X[i])
        d = np.minimum(d, _kmeans_dist(X, np.array([X[i]]), dist)[:, 0])
    return np.array(C)


@bi('kmeans', nout=4)
def kmeans(nargout, *args):
    """[idx, C, sumd, D] = kmeans(X, k, 'Distance', d, 'Replicates', r, 'MaxIter', m, 'Start', s, 'EmptyAction', a): k clusters of the rows of X by Lloyd's iterations from k-means++ starts."""
    nargchk(args, 2, 20, 'kmeans')
    X0 = _mat(args[0], 'kmeans')
    o = _pairs(args[2:], 'kmeans', ('distance', 'replicates', 'maxiter', 'start', 'emptyaction', 'display', 'options', 'onlinephase'))
    dist = py_str(o.get('distance', Char.of('sqeuclidean'))).lower()
    if dist not in ('sqeuclidean', 'cityblock', 'cosine', 'correlation', 'hamming'):
        raise err('stats:kmeans:distance', "The distance is 'sqeuclidean', 'cityblock', 'cosine', 'correlation' or 'hamming'.", 'kmeans')
    keep = ~np.any(np.isnan(X0), axis=1)
    X = X0[keep]
    if dist == 'correlation':
        X = X - X.mean(1, keepdims=True)
    if dist in ('cosine', 'correlation'):
        nr = np.linalg.norm(X, axis=1, keepdims=True)
        X = X / np.where(nr > 0, nr, 1)
    start = o.get('start', Char.of('plus'))
    starts = None
    if not is_str(start):
        S = np.asarray(darr(start), float)
        starts = [S] if S.ndim == 2 else [S[:, :, r] for r in range(S.shape[2])]
        k = starts[0].shape[0]
    else:
        k = _int(args[1])
    reps = _int(o['replicates']) if 'replicates' in o else (len(starts) if starts else 1)
    maxit = _int(o['maxiter']) if 'maxiter' in o else 100
    if 'options' in o and isinstance(o['options'], Struct):
        mi = o['options'].f.get('MaxIter')
        if mi is not None and numel(mi.item(0)):
            maxit = _int(mi.item(0))
    empty = py_str(o.get('emptyaction', Char.of('singleton'))).lower()
    n = X.shape[0]
    if k > n:
        raise err('stats:kmeans:TooManyClusters', 'X has fewer rows than k.', 'kmeans')
    rs = _rs()
    best = None
    for r in range(reps):
        sname = py_str(start).lower() if is_str(start) else ''
        if starts is not None:
            C = starts[r % len(starts)].copy()
        elif sname == 'plus':
            C = _plus_start(X, k, dist, rs)
        elif sname == 'sample':
            C = X[rs.choice(n, k, replace=False)]
        elif sname == 'uniform':
            lo, hi = X.min(0), X.max(0)
            C = lo + rs.random_sample((k, X.shape[1])) * (hi - lo)
        elif sname == 'cluster':
            sub = X[rs.choice(n, max(k, n // 10), replace=False)]
            C = _plus_start(sub, k, dist, rs)
        else:
            raise err('stats:kmeans:start', "'Start' is 'plus', 'sample', 'uniform', 'cluster' or a matrix of centroids.", 'kmeans')
        idx = None
        converged = False
        for it in range(maxit):
            D = _kmeans_dist(X, C, dist)
            new = np.argmin(D, axis=1)
            for j in range(k):
                if not np.any(new == j):
                    if empty == 'error':
                        raise err('stats:kmeans:EmptyCluster', f'A cluster became empty at iteration {it + 1}.', 'kmeans')
                    if empty == 'drop':
                        C[j] = np.nan
                        continue
                    far = int(np.argmax(D[np.arange(n), new]))
                    new[far] = j
            if idx is not None and np.array_equal(new, idx):
                converged = True
                break
            idx = new
            for j in range(k):
                if np.any(idx == j):
                    C[j] = _kmeans_center(X[idx == j], dist)
        D = _kmeans_dist(X, C, dist)
        sumd = np.array([D[idx == j, j].sum() for j in range(k)])
        if not converged:
            R.warn('stats:kmeans:FailedToConverge', f'Failed to converge in {maxit} iterations during replicate {r + 1}.')
        if best is None or sumd.sum() < best[2].sum():
            best = (idx.copy(), C.copy(), sumd, D)
    idx, C, sumd, D = best
    full = np.full(X0.shape[0], np.nan)
    full[keep] = idx + 1
    Dfull = np.full((X0.shape[0], k), np.nan)
    Dfull[keep] = D
    res = (out(full.reshape(-1, 1)), out(C), out(sumd.reshape(-1, 1)), out(Dfull))
    return res[:nargout] if nargout > 1 else res[0]


@bi('kmedoids', nout=5)
def kmedoids(nargout, *args):
    """[idx, C, sumd, D, midx] = kmedoids(X, k, 'Distance', d, 'Replicates', r, 'Start', s): k clusters, each centred on one of its rows (the medoid)."""
    nargchk(args, 2, 20, 'kmedoids')
    X = _mat(args[0], 'kmedoids')
    k = _int(args[1])
    o = _pairs(args[2:], 'kmedoids', ('distance', 'replicates', 'start', 'algorithm', 'options', 'onlinephase', 'numsamples', 'percentneighbors'))
    margs = [o['distance']] if 'distance' in o else [Char.of('sqeuclidean')]
    name, kw, fh = _metric(margs, X, 'kmedoids')
    Dall = _cdist(X, X, name, kw, fh)
    n = X.shape[0]
    rs = _rs()
    reps = _int(o.get('replicates', 1.0))
    best = None
    for _ in range(reps):
        # k-means++ seeding on the distances, then each medoid moved to the row of its cluster nearest the rest, then swaps
        first = int(rs.randint(n))
        med = [first]
        d = Dall[:, first].copy()
        for _j in range(1, k):
            w = d / d.sum() if d.sum() > 0 else np.full(n, 1 / n)
            i = min(int(np.searchsorted(np.cumsum(w), rs.random_sample())), n - 1)
            med.append(i)
            d = np.minimum(d, Dall[:, i])
        med = np.array(med)
        for _it in range(100):
            idx = np.argmin(Dall[:, med], axis=1)
            new = med.copy()
            for j in range(k):
                members = np.flatnonzero(idx == j)
                if members.size:
                    new[j] = members[np.argmin(Dall[np.ix_(members, members)].sum(0))]
            if np.array_equal(new, med):
                break
            med = new
        cost = Dall[:, med].min(1).sum()
        improved = True
        while improved:
            improved = False
            for j in range(k):
                for cand in range(n):
                    if cand in med:
                        continue
                    trial = med.copy()
                    trial[j] = cand
                    c = Dall[:, trial].min(1).sum()
                    if c < cost - 1e-12:
                        med, cost, improved = trial, c, True
        if best is None or cost < best[1]:
            best = (med, cost)
    med = best[0]
    idx = np.argmin(Dall[:, med], axis=1)
    D = Dall[:, med]
    sumd = np.array([D[idx == j, j].sum() for j in range(k)])
    res = (out(idx.reshape(-1, 1) + 1.0), out(X[med]), out(sumd.reshape(-1, 1)), out(D), out(med.reshape(-1, 1) + 1.0))
    return res[:nargout] if nargout > 1 else res[0]


# ---- hierarchical clustering -----------------------------------------------------------------------------------------------------------------

def _condensed(v, fn):
    a = np.asarray(darr(v), float)
    if a.ndim == 2 and a.shape[0] == 1:
        m = (1 + math.sqrt(1 + 8 * a.size)) / 2
        if m != int(m):
            raise err(f'stats:{fn}:distances', 'A row of distances has m(m-1)/2 values (pdist).', fn)
        return a.reshape(-1)
    return None


@bi('linkage')
def linkage(nargout, *args):
    """Z = linkage(X), linkage(X, method, metric), linkage(y, method): an agglomerative hierarchical cluster tree ('single' unless given, 'complete', 'average', 'weighted', 'centroid', 'median', 'ward')."""
    nargchk(args, 1, 4, 'linkage')
    from scipy.cluster.hierarchy import linkage as sp_link
    method = py_str(args[1]).lower() if len(args) > 1 else 'single'
    if method not in ('single', 'complete', 'average', 'weighted', 'centroid', 'median', 'ward'):
        raise err('stats:linkage:method', "The method is 'single', 'complete', 'average', 'weighted', 'centroid', 'median' or 'ward'.", 'linkage')
    y = _condensed(args[0], 'linkage')
    if y is None:
        X = _mat(args[0], 'linkage')
        if len(args) > 2 and not (is_str(args[2]) and py_str(args[2]).lower() == 'savememory'):
            name, kw, fh = _metric(args[2:], X, 'linkage')
            y = _pdist(X, name, kw, fh)
        elif method in ('centroid', 'median', 'ward'):
            Z = sp_link(X, method)
            return out(np.column_stack([Z[:, :2] + 1, Z[:, 2]]))
        else:
            y = _pdist(X, 'euclidean', {}, None)
    Z = sp_link(y, method)
    return out(np.column_stack([Z[:, :2] + 1, Z[:, 2]]))


def _scipy_Z(v, fn):
    Z = np.asarray(darr(v), float)
    if Z.ndim != 2 or Z.shape[1] != 3:
        raise err(f'stats:{fn}:Z', 'Z is a tree from linkage (three columns).', fn)
    m = Z.shape[0] + 1
    counts = np.zeros(Z.shape[0])
    size = np.ones(2 * m - 1)
    for i, (a_, b_, _) in enumerate(Z):
        size[m + i] = size[int(a_) - 1] + size[int(b_) - 1]
        counts[i] = size[m + i]
    return np.column_stack([Z[:, :2] - 1, Z[:, 2], counts])


def _renumber(T):
    first = {}
    for v in T:
        first.setdefault(v, len(first) + 1)
    return np.array([first[v] for v in T], float)


@bi('cluster')
def cluster(nargout, *args):
    """T = cluster(Z, 'MaxClust', n), cluster(Z, 'Cutoff', c, 'Criterion', 'inconsistent'|'distance', 'Depth', d): clusters cut from a linkage tree, numbered by their first observation."""
    nargchk(args, 3, 7, 'cluster')
    from scipy.cluster.hierarchy import fcluster
    Zs = _scipy_Z(args[0], 'cluster')
    o = _pairs(args[1:], 'cluster', ('maxclust', 'cutoff', 'criterion', 'depth'))
    if 'maxclust' in o:
        ks = np.asarray(darr(o['maxclust']), float).reshape(-1)
        cols = [_renumber(fcluster(Zs, int(k), 'maxclust')) for k in ks]
        return out(np.column_stack(cols))
    crit = py_str(o.get('criterion', Char.of('inconsistent'))).lower()
    cs = np.asarray(darr(o['cutoff']), float).reshape(-1)
    depth = _int(o.get('depth', 2.0))
    cols = [_renumber(fcluster(Zs, float(c), 'distance' if crit == 'distance' else 'inconsistent', depth=depth)) for c in cs]
    return out(np.column_stack(cols))


@bi('clusterdata')
def clusterdata(nargout, *args):
    """T = clusterdata(X, cutoff), clusterdata(X, 'MaxClust', n, 'Linkage', method, 'Distance', d, 'Criterion', c, 'Depth', d): linkage and cluster in one."""
    nargchk(args, 2, 14, 'clusterdata')
    X = args[0]
    if len(args) == 2:
        c = float(num(args[1]))
        Z = linkage(1, X, Char.of('single'))
        return cluster(1, Z, Char.of('MaxClust'), float(c)) if c >= 2 else cluster(1, Z, Char.of('Cutoff'), c)
    o = _pairs(args[1:], 'clusterdata', ('maxclust', 'cutoff', 'criterion', 'depth', 'linkage', 'distance', 'savememory'))
    meth = o.get('linkage', Char.of('single'))
    Z = linkage(1, X, meth, o['distance']) if 'distance' in o else linkage(1, X, meth)
    rest = []
    for k in ('maxclust', 'cutoff', 'criterion', 'depth'):
        if k in o:
            rest += [Char.of(k), o[k]]
    return cluster(1, Z, *rest)


@bi('cophenet', nout=2)
def cophenet(nargout, *args):
    """[c, d] = cophenet(Z, Y): the cophenetic correlation of a linkage tree with the distances it came from, and the cophenetic distances."""
    nargchk(args, 2, 2, 'cophenet')
    from scipy.cluster.hierarchy import cophenet as cph
    c, d = cph(_scipy_Z(args[0], 'cophenet'), np.asarray(darr(args[1]), float).reshape(-1))
    return (float(c), out(d.reshape(1, -1))) if nargout > 1 else float(c)


@bi('inconsistent')
def inconsistent(nargout, *args):
    """Y = inconsistent(Z, depth): for each link, the mean and standard deviation of the heights of the links below it to depth (2), their number, and its inconsistency coefficient."""
    nargchk(args, 1, 2, 'inconsistent')
    from scipy.cluster.hierarchy import inconsistent as inc
    return out(inc(_scipy_Z(args[0], 'inconsistent'), _int(args[1]) if len(args) > 1 else 2))


@bi('optimalleaforder')
def optimalleaforder(nargout, *args):
    """order = optimalleaforder(Z, D): the leaf order of a tree that puts the nearest leaves side by side (the sum of their distances least)."""
    nargchk(args, 2, 6, 'optimalleaforder')
    from scipy.cluster.hierarchy import optimal_leaf_ordering, leaves_list
    D = np.asarray(darr(args[1]), float)
    y = D.reshape(-1) if D.ndim == 2 and D.shape[0] == 1 else __import__('scipy.spatial.distance', fromlist=['squareform']).squareform(D, checks=False)
    Zo = optimal_leaf_ordering(_scipy_Z(args[0], 'optimalleaforder'), y)
    return out(leaves_list(Zo).reshape(1, -1) + 1.0)


@bi('dendrogram', nout=3)
def dendrogram(nargout, *args):
    """[H, T, outperm] = dendrogram(Z), dendrogram(Z, P, 'Orientation', o, 'ColorThreshold', t, 'Labels', names, 'Reorder', order): a linkage tree drawn, at most P leaves (30) shown."""
    nargchk(args, 1, 14, 'dendrogram')
    from scipy.cluster.hierarchy import dendrogram as sp_den
    from .graphics import newplot
    from ..graphics_base import Line
    Zs = _scipy_Z(args[0], 'dendrogram')
    rest = list(args[1:])
    P = 30
    if rest and not is_str(rest[0]):
        P = _int(rest.pop(0))
    o = _pairs(rest, 'dendrogram', ('orientation', 'colorthreshold', 'labels', 'reorder', 'checkcrossing', 'leaforder'))
    m = Zs.shape[0] + 1
    kw = {'no_plot': True}
    if P and m > P:
        kw.update(truncate_mode='lastp', p=P)
    ct = None
    if 'colorthreshold' in o:
        ct = 0.7 * Zs[:, 2].max() if is_str(o['colorthreshold']) else float(num(o['colorthreshold']))
    d = sp_den(Zs, color_threshold=ct if ct is not None else 0, above_threshold_color='k', **kw)
    leaves = np.array(d['leaves'])
    ax = newplot(None)
    palette = [(0.0, 0.447, 0.741), (0.85, 0.325, 0.098), (0.929, 0.694, 0.125), (0.494, 0.184, 0.556), (0.466, 0.674, 0.188), (0.301, 0.745, 0.933), (0.635, 0.078, 0.184)]
    ori = py_str(o.get('orientation', Char.of('top'))).lower()
    handles = []
    for ic, dc, col in zip(d['icoord'], d['dcoord'], d['color_list']):
        # SciPy puts leaves at 5, 15, 25, ...: here at 1, 2, 3, ...
        xs = (np.array(ic) - 5) / 10 + 1
        ys = np.array(dc)
        L = Line(ax)
        if ori in ('left', 'right'):
            xs, ys = ys, xs
        L.props['XData'], L.props['YData'] = xs.reshape(1, -1), ys.reshape(1, -1)
        if ct is None:
            L.props['Color'] = (0.0, 0.447, 0.741)
        elif col == 'k':
            L.props['Color'] = (0.0, 0.0, 0.0)
        else:
            L.props['Color'] = palette[(int(col[1:]) - 1) % len(palette)] if col[1:].isdigit() else (0.0, 0.447, 0.741)
        handles.append(L)
    names = [str(x) for x in text_list(o['labels'])] if 'labels' in o else None
    ticks = np.arange(1, leaves.size + 1, dtype=float)
    labels = [(names[i] if names and i < m else str(i + 1)) if i < m else str(i + 1) for i in leaves]
    if kw.get('truncate_mode'):
        labels = [str(k + 1) for k in range(leaves.size)]
    if ori in ('left', 'right'):
        ax.set_value('YTick', ticks.reshape(1, -1))
        ax.set_value('YTickLabel', Cell.of_list([Char.of(s_) for s_ in labels]))
        ax.set_value('YLim', np.array([[0.5, leaves.size + 0.5]]))
        if ori == 'left':
            ax.set_value('XDir', Char.of('reverse'))
    else:
        ax.set_value('XTick', ticks.reshape(1, -1))
        ax.set_value('XTickLabel', Cell.of_list([Char.of(s_) for s_ in labels]))
        ax.set_value('XLim', np.array([[0.5, leaves.size + 0.5]]))
        if ori == 'bottom':
            ax.set_value('YDir', Char.of('reverse'))
    ax.touch()
    from ..graphics_base import HArr
    H = HArr.of(handles, col=True)
    # T: for each observation, the leaf drawn (from the left) that holds it
    T = np.zeros(m)

    def members(node):
        if node < m:
            return [node]
        a_, b_ = int(Zs[node - m, 0]), int(Zs[node - m, 1])
        return members(a_) + members(b_)
    import sys
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 4 * m + 100))
    for pos, node in enumerate(leaves):
        for obs in members(int(node)):
            T[obs] = pos + 1
    outperm = (leaves + 1.0) if not kw.get('truncate_mode') else np.arange(1, leaves.size + 1, dtype=float)
    res = (H, out(T.reshape(-1, 1)), out(outperm.reshape(1, -1)))
    return res[:nargout] if nargout > 1 else (res[0] if nargout else None)


# ---- density-based and spectral clustering -------------------------------------------------------------------------------------------------

@bi('dbscan', nout=2)
def dbscan(nargout, *args):
    """[idx, corepts] = dbscan(X, epsilon, minpts), dbscan(..., 'Distance', d), dbscan(D, epsilon, minpts, 'Distance', 'precomputed'): clusters of points with minpts neighbours within epsilon; -1 for noise."""
    nargchk(args, 3, 7, 'dbscan')
    X = _mat(args[0], 'dbscan')
    eps, minpts = float(num(args[1])), _int(args[2])
    o = _pairs(args[3:], 'dbscan', ('distance', 'p', 'cov', 'scale'))
    if 'distance' in o and is_str(o['distance']) and py_str(o['distance']).lower() == 'precomputed':
        D = X
    else:
        margs = [o['distance']] if 'distance' in o else []
        name, kw, fh = _metric(margs, X, 'dbscan')
        D = _cdist(X, X, name, kw, fh)
    n = D.shape[0]
    nbrs = [np.flatnonzero(D[i] <= eps) for i in range(n)]
    core = np.array([nb.size >= minpts for nb in nbrs])
    idx = np.full(n, -1.0)
    c = 0
    for i in range(n):
        if idx[i] != -1 or not core[i]:
            continue
        c += 1
        idx[i] = c
        stack = [i]
        while stack:
            j = stack.pop()
            if not core[j]:
                continue
            for q in nbrs[j]:
                if idx[q] == -1:
                    idx[q] = c
                    stack.append(q)
    res = (out(idx.reshape(-1, 1)), out(core.reshape(-1, 1)))
    return res if nargout > 1 else res[0]


@bi('spectralcluster', nout=3)
def spectralcluster(nargout, *args):
    """[idx, V, D] = spectralcluster(X, k, 'Distance', d, 'SimilarityGraph', 'knn'|'epsilon', 'NumNeighbors', n, 'Radius', r, 'KernelScale', s, 'LaplacianNormalization', 'randomwalk'|'symmetric'|'none'): clusters from the eigenvectors of a similarity graph's Laplacian."""
    nargchk(args, 2, 18, 'spectralcluster')
    X = _mat(args[0], 'spectralcluster')
    k = _int(args[1])
    o = _pairs(args[2:], 'spectralcluster', ('distance', 'similaritygraph', 'numneighbors', 'radius', 'kernelscale', 'laplaciannormalization', 'clustermethod', 'p', 'cov', 'scale'))
    n = X.shape[0]
    if 'distance' in o and is_str(o['distance']) and py_str(o['distance']).lower() == 'precomputed':
        D = X
    else:
        name, kw, fh = _metric([o['distance']] if 'distance' in o else [], X, 'spectralcluster')
        D = _cdist(X, X, name, kw, fh)
    graph = py_str(o.get('similaritygraph', Char.of('knn'))).lower()
    s = float(num(o['kernelscale'])) if 'kernelscale' in o and not is_str(o['kernelscale']) else 1.0
    if 'kernelscale' in o and is_str(o['kernelscale']):
        s = float(np.median(D[np.triu_indices(n, 1)]))
    W = np.exp(-(D / s) ** 2)
    if graph == 'knn':
        nn = _int(o['numneighbors']) if 'numneighbors' in o else max(1, int(math.ceil(math.log(n))))
        order = np.argsort(D, axis=1, kind='stable')[:, 1:nn + 1]
        A = np.zeros((n, n), bool)
        A[np.repeat(np.arange(n), nn), order.reshape(-1)] = True
        A = A | A.T
    else:
        r = float(num(o['radius'])) if 'radius' in o else np.inf
        A = D <= r
    np.fill_diagonal(A, False)
    W = np.where(A, W, 0.0)
    deg = W.sum(1)
    norm = py_str(o.get('laplaciannormalization', Char.of('randomwalk'))).lower()
    L = np.diag(deg) - W
    from scipy.linalg import eigh
    if norm == 'none':
        vals, vecs = eigh(L)
    elif norm == 'symmetric':
        dm = 1 / np.sqrt(np.where(deg > 0, deg, 1))
        vals, vecs = eigh(dm[:, None] * L * dm[None, :])
    else:
        vals, vecs = eigh(L, np.diag(np.where(deg > 0, deg, 1)))
    V = vecs[:, :k]
    lam = vals[:k]
    U = V / np.linalg.norm(V, axis=1, keepdims=True).clip(1e-300) if norm == 'symmetric' else V
    idx = kmeans(1, out(U), float(k), Char.of('Replicates'), 5.0)
    res = (idx, out(V), out(lam.reshape(-1, 1)))
    return res[:nargout] if nargout > 1 else res[0]


# ---- Gaussian mixtures -------------------------------------------------------------------------------------------------------------------------

class GMM(Obj):
    """gmdistribution: k multivariate normals and their proportions."""
    cls = 'gmdistribution'

    def __init__(self, mu, Sigma, p, cov_type='full', shared=False, fitinfo=None):
        self.mu = np.asarray(mu, float)
        self.k, self.d = self.mu.shape
        self.Sigma = Sigma            # (k, d, d) full matrices (shared or diagonal kept as given for the properties)
        self.p = np.asarray(p, float).reshape(-1)
        self.p = self.p / self.p.sum()
        self.cov_type = cov_type
        self.shared = shared
        self.fit = fitinfo or {}

    def covs(self):
        return self.Sigma

    def log_comp(self, X):
        """log(p_j N(x; mu_j, Sigma_j)) for each row and component."""
        from scipy.stats import multivariate_normal
        return np.column_stack([np.log(self.p[j]) + multivariate_normal.logpdf(X, self.mu[j], self.Sigma[j], allow_singular=True).reshape(-1)
                                for j in range(self.k)])

    def sigma_value(self):
        if self.cov_type == 'diagonal':
            S = np.stack([np.diag(s) for s in self.Sigma], axis=0)
            vals = S[:1] if self.shared else S
            return out(vals.reshape(vals.shape[0], 1, self.d).transpose(1, 2, 0) if not self.shared else vals.reshape(1, self.d))
        if self.shared:
            return out(self.Sigma[0])
        return out(np.transpose(self.Sigma, (1, 2, 0)))

    def getprop(self, name):
        k = name.lower()
        f = self.fit
        table = {'mu': lambda: out(self.mu), 'sigma': self.sigma_value, 'componentproportion': lambda: out(self.p.reshape(1, -1)),
                 'numcomponents': lambda: float(self.k), 'numvariables': lambda: float(self.d), 'covariancetype': lambda: Char.of(self.cov_type),
                 'sharedcovariance': lambda: bool(self.shared), 'distributionname': lambda: Char.of('gaussian mixture distribution'),
                 'negativeloglikelihood': lambda: f.get('nll', EMPTY()), 'aic': lambda: f.get('aic', EMPTY()), 'bic': lambda: f.get('bic', EMPTY()),
                 'converged': lambda: f.get('converged', EMPTY()), 'numiterations': lambda: f.get('iters', EMPTY()),
                 'regularizationvalue': lambda: f.get('reg', 0.0), 'probabilitytolerance': lambda: 1e-8}
        if k in table:
            return table[k]()
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class 'gmdistribution'.")

    def propnames(self):
        return ['NumVariables', 'DistributionName', 'NumComponents', 'ComponentProportion', 'SharedCovariance', 'NumIterations', 'RegularizationValue',
                'NegativeLogLikelihood', 'CovarianceType', 'mu', 'Sigma', 'AIC', 'BIC', 'Converged', 'ProbabilityTolerance']

    def display_lines(self):
        lines = [f'  Gaussian mixture distribution with {self.k} components in {self.d} dimensions']
        for j in range(self.k):
            lines.append(f'  Component {j + 1}:')
            lines.append(f'  Mixing proportion: {self.p[j]:.6f}')
            lines.append('  Mean: ' + '  '.join(f'{v:9.4f}' for v in self.mu[j]))
        return lines


def _gm(v, fn):
    if not isinstance(v, GMM):
        raise err(f'stats:{fn}:gm', f'{fn} takes a gmdistribution.', fn)
    return v


@bi('gmdistribution')
def gmdistribution(nargout, *args):
    """gm = gmdistribution(mu, sigma), gmdistribution(mu, sigma, p): a Gaussian mixture: a row of mu for each component, sigma d-by-d-by-k (or d-by-d shared, or 1-by-d diagonal), p the proportions."""
    nargchk(args, 2, 3, 'gmdistribution')
    mu = _mat(args[0], 'gmdistribution', 'mu')
    k, d = mu.shape
    S = np.asarray(darr(args[1]), float)
    diag = False
    shared = False
    if S.ndim == 2 and S.shape == (1, d):
        Ss, diag, shared = np.stack([np.diag(S.reshape(-1))] * k), True, True
    elif S.ndim == 2 and S.shape == (d, d):
        Ss, shared = np.stack([S] * k), True
    elif S.ndim == 3 and S.shape[0] == 1 and S.shape[1] == d:
        Ss, diag = np.stack([np.diag(S[0, :, j]) for j in range(k)]), True
    elif S.ndim == 3 and S.shape[:2] == (d, d) and S.shape[2] == k:
        Ss = np.transpose(S, (2, 0, 1))
    elif d == 1 and S.size == k:
        Ss = S.reshape(k, 1, 1)
    else:
        raise err('stats:gmdistribution:sigma', 'sigma is d-by-d-by-k, d-by-d (shared), or 1-by-d-by-k or 1-by-d (diagonal).', 'gmdistribution')
    p = np.asarray(darr(args[2]), float).reshape(-1) if len(args) > 2 else np.ones(k)
    return GMM(mu, Ss, p, 'diagonal' if diag else 'full', shared)


@bi('fitgmdist')
def fitgmdist(nargout, *args):
    """gm = fitgmdist(X, k, 'CovarianceType', 'full'|'diagonal', 'SharedCovariance', tf, 'RegularizationValue', r, 'Replicates', n, 'Start', s, 'Options', statset): a Gaussian mixture fitted by EM from k-means++ starts."""
    nargchk(args, 2, 16, 'fitgmdist')
    X = _mat(args[0], 'fitgmdist')
    X = X[~np.any(np.isnan(X), axis=1)]
    k = _int(args[1])
    o = _pairs(args[2:], 'fitgmdist', ('covariancetype', 'sharedcovariance', 'regularizationvalue', 'replicates', 'start', 'options', 'probabilitytolerance'))
    ctype = py_str(o.get('covariancetype', Char.of('full'))).lower()
    shared = _flag(o['sharedcovariance']) if 'sharedcovariance' in o else False
    reg = float(num(o['regularizationvalue'])) if 'regularizationvalue' in o else 0.0
    reps = _int(o.get('replicates', 1.0))
    maxit, tol = 100, 1e-6
    if 'options' in o and isinstance(o['options'], Struct):
        for key, val in o['options'].elem(0).items():
            if key.lower() == 'maxiter' and numel(val):
                maxit = _int(val)
            if key.lower() == 'tolfun' and numel(val):
                tol = float(num(val))
    n, d = X.shape
    rs = _rs()
    best = None
    start = o.get('start', Char.of('plus'))
    for _ in range(reps):
        if not is_str(start):
            init = np.asarray(darr(start), float).reshape(-1).astype(int) - 1
            R_ = np.zeros((n, k))
            R_[np.arange(n), init] = 1
        else:
            if py_str(start).lower() == 'randsample':
                C = X[rs.choice(n, k, replace=False)]
            else:
                C = _plus_start(X, k, 'sqeuclidean', rs)
            lab = np.argmin(_kmeans_dist(X, C, 'sqeuclidean'), axis=1)
            R_ = np.zeros((n, k))
            R_[np.arange(n), lab] = 1
        prev = None
        conv = False
        it = 0
        for it in range(1, maxit + 1):
            Nk = R_.sum(0) + 1e-300
            p = Nk / n
            mu = (R_.T @ X) / Nk[:, None]
            covs = []
            for j in range(k):
                Xc = X - mu[j]
                S = (R_[:, j, None] * Xc).T @ Xc / Nk[j]
                covs.append(S)
            covs = np.array(covs)
            if shared:
                Sh = np.tensordot(p, covs, axes=1)
                covs = np.stack([Sh] * k)
            if ctype == 'diagonal':
                covs = np.stack([np.diag(np.diag(S)) for S in covs])
            covs = covs + reg * np.eye(d)[None]
            gm = GMM(mu, covs, p, ctype, shared)
            LC = gm.log_comp(X)
            mx = LC.max(1, keepdims=True)
            ll = float(np.sum(mx.reshape(-1) + np.log(np.exp(LC - mx).sum(1))))
            R_ = np.exp(LC - mx)
            R_ /= R_.sum(1, keepdims=True)
            if prev is not None and abs(ll - prev) < tol * abs(ll):
                conv = True
                break
            prev = ll
        npar = k * d + (k - 1) + (d * (d + 1) // 2 if ctype == 'full' else d) * (1 if shared else k)
        gm.fit = {'nll': -ll, 'aic': 2 * npar - 2 * ll, 'bic': npar * math.log(n) - 2 * ll, 'converged': conv, 'iters': float(it), 'reg': reg}
        if best is None or -ll < best.fit['nll']:
            best = gm
    if not best.fit['converged']:
        R.warn('stats:gmdistribution:FailedToConverge', f'Failed to converge in {maxit} iterations for gmdistribution with {k} components.')
    return best


def _gm_cluster(nargout, gm, X, *rest):
    X = _mat(X, 'cluster')
    LC = gm.log_comp(X)
    mx = LC.max(1, keepdims=True)
    P = np.exp(LC - mx)
    P /= P.sum(1, keepdims=True)
    idx = np.argmax(P, axis=1) + 1.0
    nll = -float(np.sum(mx.reshape(-1) + np.log(np.exp(LC - mx).sum(1))))
    res = (out(idx.reshape(-1, 1)), nll, out(P))
    return res[:nargout] if nargout > 1 else res[0]


@bi('posterior', nout=2)
def posterior(nargout, *args):
    """[P, nlogL] = posterior(gm, X): the probability of each component given each row."""
    nargchk(args, 2, 2, 'posterior')
    gm = _gm(args[0], 'posterior')
    r = _gm_cluster(3, gm, args[1])
    return (r[2], r[1]) if nargout > 1 else r[2]


def _gm_pdf(nargout, gm, X, *rest):
    X = _mat(X, 'pdf')
    LC = gm.log_comp(X)
    return out(np.exp(LC).sum(1).reshape(-1, 1))


def _gm_random(nargout, gm, *rest):
    n = _int(rest[0]) if rest else 1
    rs = _rs()
    comp = rs.choice(gm.k, n, p=gm.p)
    Y = np.empty((n, gm.d))
    for j in range(gm.k):
        sel = comp == j
        if sel.any():
            Lc = np.linalg.cholesky(gm.Sigma[j] + 1e-12 * np.eye(gm.d))
            Y[sel] = gm.mu[j] + rs.standard_normal((sel.sum(), gm.d)) @ Lc.T
    return (out(Y), out(comp.reshape(-1, 1) + 1.0)) if nargout > 1 else out(Y)


def _gm_mahal(nargout, gm, X, *rest):
    X = _mat(X, 'mahal')
    D = np.column_stack([np.einsum('ij,jk,ik->i', X - gm.mu[j], np.linalg.pinv(gm.Sigma[j]), X - gm.mu[j]) for j in range(gm.k)])
    return out(D)


# ---- how good clusters are ---------------------------------------------------------------------------------------------------------------------

def _silhouette_values(X, lab, name, kw, fh):
    D = _cdist(X, X, name, kw, fh)
    ks = np.unique(lab[lab >= 0])
    s = np.full(X.shape[0], np.nan)
    for i in range(X.shape[0]):
        if lab[i] < 0:
            continue
        own = (lab == lab[i])
        if own.sum() == 1:
            s[i] = 0.0
            continue
        a_ = D[i, own].sum() / (own.sum() - 1)
        b_ = min(D[i, lab == c].mean() for c in ks if c != lab[i]) if ks.size > 1 else np.nan
        s[i] = (b_ - a_) / max(a_, b_) if np.isfinite(b_) and max(a_, b_) > 0 else 0.0
    return s


@bi('silhouette', nout=2)
def silhouette(nargout, *args):
    """[s, h] = silhouette(X, clust), silhouette(X, clust, distance): how well each point sits in its cluster, (b - a)/max(a, b); drawn as bars when no output is asked for."""
    nargchk(args, 2, 4, 'silhouette')
    from .statdesc import groups
    X = _mat(args[0], 'silhouette')
    labels, lab = groups(args[1], X.shape[0], 'silhouette')
    margs = list(args[2:]) if len(args) > 2 else [Char.of('sqeuclidean')]
    name, kw, fh = _metric(margs, X, 'silhouette')
    s = _silhouette_values(X, lab, name, kw, fh)
    if nargout == 0 or nargout > 1:
        from .graphics import newplot
        from ..graphics_base import Series
        ax = newplot(None)
        order = []
        ticks = []
        for c in range(len(labels)):
            members = np.flatnonzero(lab == c)
            members = members[np.argsort(-s[members], kind='stable')]
            ticks.append(len(order) + (members.size + 1) / 2 + 2 * c)
            order += list(members)
        ypos = []
        pos = 0
        for c in range(len(labels)):
            members = np.flatnonzero(lab == c)
            ypos += list(pos + 1 + np.arange(members.size))
            pos += members.size + 2
        h = Series(ax, 'bar')
        h.props['XData'] = np.array(ypos, float).reshape(1, -1)
        h.props['YData'] = s[order].reshape(1, -1)
        h.props['Horizontal'] = True
        h.props['BarWidth'] = 1.0
        ax.set_value('YDir', Char.of('reverse'))
        ax.set_value('YTick', np.array(ticks, float).reshape(1, -1))
        ax.set_value('YTickLabel', Cell.of_list([Char.of(x) for x in labels]))
        ax.xlabel_text = 'Silhouette Value'
        ax.touch()
        if nargout == 0:
            return None
        return out(s.reshape(-1, 1)), h
    return out(s.reshape(-1, 1))


class EvalClusters(Obj):
    cls = 'clustering.evaluation.ClusterCriterion'

    def __init__(self, crit, ks, vals, sols, method):
        self.crit, self.ks, self.vals, self.sols, self.method = crit, ks, vals, sols, method
        good = np.where(np.isfinite(vals), vals, np.nan)
        if crit in ('daviesbouldin',):
            self.best = int(np.nanargmin(good))
        elif crit == 'gap':
            self.best = int(np.nanargmax(good))
        else:
            self.best = int(np.nanargmax(good))

    def getprop(self, name):
        k = name.lower()
        names = {'calinskiharabasz': 'CalinskiHarabasz', 'daviesbouldin': 'DaviesBouldin', 'silhouette': 'Silhouette', 'gap': 'Gap'}
        table = {'optimalk': lambda: float(self.ks[self.best]), 'criterionvalues': lambda: out(self.vals.reshape(1, -1)),
                 'inspectedk': lambda: out(np.array(self.ks, float).reshape(1, -1)), 'optimaly': lambda: out(self.sols[:, self.best:self.best + 1]),
                 'criterionname': lambda: Char.of(names[self.crit]), 'clusteringfunction': lambda: Char.of(self.method),
                 'numobservations': lambda: float(self.sols.shape[0])}
        if k in table:
            return table[k]()
        raise MError('MATLAB:noSuchMethodOrField', f"Unrecognized property '{name}' for class '{self.cls}'.")

    def propnames(self):
        return ['NumObservations', 'InspectedK', 'CriterionValues', 'OptimalK', 'OptimalY', 'CriterionName', 'ClusteringFunction']

    def display_lines(self):
        names = {'calinskiharabasz': 'CalinskiHarabasz', 'daviesbouldin': 'DaviesBouldin', 'silhouette': 'Silhouette', 'gap': 'Gap'}
        return [f'  {names[self.crit]}Evaluation with properties:', '', f'    NumObservations: {self.sols.shape[0]}',
                '         InspectedK: ' + ' '.join(str(k) for k in self.ks), '    CriterionValues: ' + ' '.join(f'{v:.4g}' for v in self.vals),
                f'           OptimalK: {self.ks[self.best]}']


def _ch(X, lab):
    ks = np.unique(lab)
    k, n = ks.size, X.shape[0]
    if k < 2:
        return np.nan
    m = X.mean(0)
    B = sum((lab == c).sum() * np.sum((X[lab == c].mean(0) - m) ** 2) for c in ks)
    W = sum(np.sum((X[lab == c] - X[lab == c].mean(0)) ** 2) for c in ks)
    return (B / (k - 1)) / (W / (n - k)) if W > 0 else np.inf


def _db(X, lab):
    ks = np.unique(lab)
    if ks.size < 2:
        return np.nan
    C = np.array([X[lab == c].mean(0) for c in ks])
    S = np.array([np.mean(np.linalg.norm(X[lab == c] - C[i], axis=1)) for i, c in enumerate(ks)])
    vals = []
    for i in range(ks.size):
        vals.append(max((S[i] + S[j]) / np.linalg.norm(C[i] - C[j]) for j in range(ks.size) if j != i))
    return float(np.mean(vals))


@bi('evalclusters')
def evalclusters(nargout, *args):
    """eva = evalclusters(X, clust, criterion, 'KList', ks): the number of clusters a criterion ('CalinskiHarabasz', 'DaviesBouldin', 'silhouette', 'gap') prefers, clust 'kmeans', 'linkage', 'gmdistribution' or a matrix of solutions."""
    nargchk(args, 3, 13, 'evalclusters')
    X = _mat(args[0], 'evalclusters')
    crit = py_str(args[2]).lower()
    if crit not in ('calinskiharabasz', 'daviesbouldin', 'silhouette', 'gap'):
        raise err('stats:evalclusters:criterion', "The criterion is 'CalinskiHarabasz', 'DaviesBouldin', 'silhouette' or 'gap'.", 'evalclusters')
    o = _pairs(args[3:], 'evalclusters', ('klist', 'distance', 'b', 'referencedistribution', 'searchmethod'))
    clust = args[1]
    if is_str(clust):
        method = py_str(clust).lower()
        ks = [int(k) for k in np.asarray(darr(o['klist'])).reshape(-1)] if 'klist' in o else None
        if ks is None:
            raise err('stats:evalclusters:KList', "Give the numbers of clusters to try: 'KList', [2 3 4].", 'evalclusters')

        def solve(Xd, k):
            if method == 'kmeans':
                return np.asarray(darr(kmeans(1, out(Xd), float(k), Char.of('Replicates'), 5.0)), float).reshape(-1)
            if method == 'linkage':
                return np.asarray(darr(clusterdata(1, out(Xd), Char.of('MaxClust'), float(k), Char.of('Linkage'), Char.of('ward'))), float).reshape(-1)
            if method == 'gmdistribution':
                g = fitgmdist(1, out(Xd), float(k), Char.of('Replicates'), 3.0, Char.of('RegularizationValue'), 1e-6)
                return np.asarray(darr(_gm_cluster(1, g, out(Xd))), float).reshape(-1)
            raise err('stats:evalclusters:method', "clust is 'kmeans', 'linkage', 'gmdistribution' or a matrix of solutions.", 'evalclusters')
        sols = np.column_stack([solve(X, k) for k in ks])
    else:
        method = 'user'
        sols = np.asarray(darr(clust), float)
        sols = sols.reshape(-1, 1) if sols.ndim == 1 else sols
        ks = [len(np.unique(sols[:, j][np.isfinite(sols[:, j])])) for j in range(sols.shape[1])]
    vals = []
    for j, k in enumerate(ks):
        lab = sols[:, j].astype(int)
        if crit == 'calinskiharabasz':
            vals.append(_ch(X, lab))
        elif crit == 'daviesbouldin':
            vals.append(_db(X, lab))
        elif crit == 'silhouette':
            vals.append(float(np.nanmean(_silhouette_values(X, lab, 'squaredeuclidean', {}, None))) if k > 1 else np.nan)
        else:
            vals.append(np.nan)
    if crit == 'gap':
        B = _int(o.get('b', 100.0))
        rs = _rs()
        lo, hi = X.min(0), X.max(0)

        def logW(Xd, lab):
            return math.log(sum(np.sum((Xd[lab == c] - Xd[lab == c].mean(0)) ** 2) for c in np.unique(lab)) + 1e-300)
        vals = []
        for j, k in enumerate(ks):
            ref = []
            for _ in range(B):
                Xr = lo + rs.random_sample(X.shape) * (hi - lo)
                if method == 'user':
                    labr = np.asarray(darr(kmeans(1, out(Xr), float(k))), float).reshape(-1).astype(int)
                else:
                    labr = solve(Xr, k).astype(int)
                ref.append(logW(Xr, labr))
            vals.append(float(np.mean(ref) - logW(X, sols[:, j].astype(int))))
    return EvalClusters(crit, ks, np.array(vals, float), sols, method)


# ---- principal components and factors ------------------------------------------------------------------------------------------------------

def _signs(coeff):
    """Each column's largest element (in size) made positive."""
    idx = np.argmax(np.abs(coeff), axis=0)
    s = np.sign(coeff[idx, np.arange(coeff.shape[1])])
    s[s == 0] = 1
    return coeff * s, s


@bi('pca', nout=6)
def pca(nargout, *args):
    """[coeff, score, latent, tsquared, explained, mu] = pca(X), pca(X, 'NumComponents', k, 'Centered', tf, 'Economy', tf, 'Rows', 'complete'|'all', 'Weights', w, 'VariableWeights', vw|'variance'): principal components by the SVD."""
    nargchk(args, 1, 17, 'pca')
    X = _mat(args[0], 'pca')
    o = _pairs(args[1:], 'pca', ('numcomponents', 'centered', 'economy', 'rows', 'weights', 'variableweights', 'algorithm', 'options', 'coeff0', 'score0'))
    rows = py_str(o.get('rows', Char.of('complete'))).lower()
    keep = ~np.any(np.isnan(X), axis=1)
    if rows == 'all' and not keep.all():
        raise err('stats:pca:NaNs', "X has NaNs: 'Rows', 'all' takes complete data ('complete' leaves those rows out).", 'pca')
    Xk = X[keep]
    n, p = Xk.shape
    w = np.asarray(darr(o['weights']), float).reshape(-1)[keep] if 'weights' in o else np.ones(n)
    w = w * n / w.sum()          # weights scaled to sum to n
    vw = o.get('variableweights')
    if vw is not None and is_str(vw):
        vw = 1 / np.var(Xk, axis=0, ddof=1)
    elif vw is not None:
        vw = np.asarray(darr(vw), float).reshape(-1)
    centered = _flag(o['centered']) if 'centered' in o else True
    mu = (w @ Xk) / w.sum() if centered else np.zeros(p)
    Xc = Xk - mu
    Xs = Xc * np.sqrt(w)[:, None]
    if vw is not None:
        Xs = Xs * np.sqrt(vw)[None, :]
    U, S, Vt = np.linalg.svd(Xs, full_matrices=False)
    latent = S ** 2 / (n - 1 if centered else n)
    coeff = Vt.T
    if vw is not None:
        coeff = coeff / np.sqrt(vw)[:, None]
    coeff, sg = _signs(coeff)
    economy = _flag(o['economy']) if 'economy' in o else True
    rank = int(np.sum(S > max(n, p) * np.finfo(float).eps * (S[0] if S.size else 0)))
    dofk = min(n - (1 if centered else 0), p)
    k = _int(o['numcomponents']) if 'numcomponents' in o else (dofk if economy else p)
    k = min(k, coeff.shape[1]) if economy or 'numcomponents' in o else k
    if not economy and coeff.shape[1] < p:
        from scipy.linalg import null_space
        extra = null_space(coeff.T) if coeff.size else np.eye(p)
        coeff = np.column_stack([coeff, extra])
        latent = np.concatenate([latent, np.zeros(p - latent.size)])
    coeffk = coeff[:, :k]
    score = Xc @ (coeffk * (vw[:, None] if vw is not None else 1))
    full_score = np.full((X.shape[0], k), np.nan)
    full_score[keep] = score
    lat = latent[:k] if 'numcomponents' in o else latent[:max(k, min(dofk, latent.size))]
    # Hotelling's T^2 over the components that carry variance
    r = min(rank, dofk)
    Ssc = Xc @ (coeff[:, :r] * (vw[:, None] if vw is not None else 1))
    t2 = np.sum(Ssc ** 2 / latent[:r], axis=1) if r else np.zeros(n)
    t2f = np.full(X.shape[0], np.nan)
    t2f[keep] = t2
    explained = 100 * latent / latent.sum() if latent.sum() > 0 else latent
    res = (out(coeffk), out(full_score), out(lat.reshape(-1, 1)), out(t2f.reshape(-1, 1)), out(explained[:max(k, lat.size)].reshape(-1, 1)), out(mu.reshape(1, -1)))
    return res[:nargout] if nargout > 1 else res[0]


@bi('pcacov', nout=3)
def pcacov(nargout, *args):
    """[coeff, latent, explained] = pcacov(V): principal components of a covariance matrix."""
    nargchk(args, 1, 1, 'pcacov')
    V = _mat(args[0], 'pcacov', 'V')
    U, S, _ = np.linalg.svd(V)
    coeff, _ = _signs(U)
    res = (out(coeff), out(S.reshape(-1, 1)), out((100 * S / S.sum()).reshape(-1, 1)))
    return res[:nargout] if nargout > 1 else res[0]


@bi('ppca', nout=6)
def ppca(nargout, *args):
    """[coeff, score, pcvar, mu, v, S] = ppca(Y, k), ppca(..., 'Options', statset): probabilistic PCA by EM, rows with missing values (NaN) used as far as they go."""
    nargchk(args, 2, 8, 'ppca')
    Y = _mat(args[0], 'ppca', 'Y')
    k = _int(args[1])
    o = _pairs(args[2:], 'ppca', ('options', 'w0', 'v0'))
    maxit, tolx, tolf = 1000, 1e-6, 1e-6
    if 'options' in o and isinstance(o['options'], Struct):
        for key, val in o['options'].elem(0).items():
            if numel(val):
                if key.lower() == 'maxiter':
                    maxit = _int(val)
                elif key.lower() == 'tolx':
                    tolx = float(num(val))
                elif key.lower() == 'tolfun':
                    tolf = float(num(val))
    n, p = Y.shape
    M = ~np.isnan(Y)
    rs = _rs()
    W = np.asarray(darr(o['w0']), float) if 'w0' in o else rs.standard_normal((p, k))
    v = float(num(o['v0'])) if 'v0' in o else float(rs.random_sample())
    mu = np.nanmean(Y, axis=0)
    prev = None
    for it in range(maxit):
        Ex = np.zeros((n, k))
        Exx = np.zeros((n, k, k))
        nll = 0.0
        for i in range(n):
            o_ = M[i]
            Wo = W[o_]
            Minv = np.linalg.inv(Wo.T @ Wo + v * np.eye(k))
            yc = Y[i, o_] - mu[o_]
            Ex[i] = Minv @ Wo.T @ yc
            Exx[i] = v * Minv + np.outer(Ex[i], Ex[i])
            C = Wo @ Wo.T + v * np.eye(o_.sum())
            sign, logdet = np.linalg.slogdet(C)
            nll += 0.5 * (logdet + yc @ np.linalg.solve(C, yc) + o_.sum() * math.log(2 * math.pi))
        # M step
        mu = np.array([np.sum(M[:, j] * (np.where(M[:, j], Y[:, j], 0) - Ex @ W[j])) / M[:, j].sum() for j in range(p)])
        Wn = np.empty_like(W)
        for j in range(p):
            rows = M[:, j]
            A = Exx[rows].sum(0)
            b = (Ex[rows] * (Y[rows, j] - mu[j])[:, None]).sum(0)
            Wn[j] = np.linalg.solve(A, b)
        vs = 0.0
        cnt = 0
        for i in range(n):
            o_ = M[i]
            yc = Y[i, o_] - mu[o_]
            Wo = Wn[o_]
            vs += yc @ yc - 2 * Ex[i] @ Wo.T @ yc + np.trace(Exx[i] @ Wo.T @ Wo)
            cnt += o_.sum()
        vn = vs / cnt
        dW = np.max(np.abs(Wn - W))
        W, v = Wn, max(vn, 1e-12)
        if prev is not None and (abs(prev - nll) < tolf * max(1.0, abs(nll)) and dW < tolx):
            break
        prev = nll
    # orthogonal components: the eigenvectors of W W'
    U, S, Vt = np.linalg.svd(W, full_matrices=False)
    coeff, sg = _signs(U)
    pcvar = S ** 2
    score = (Ex @ Vt.T) * S * sg          # Y - mu ~ Ex W' = Ex V S U': the scores on coeff = U
    Yfull = Ex @ W.T + mu
    res = (out(coeff), out(score), out(pcvar.reshape(-1, 1)), out(mu.reshape(1, -1)), float(v),
           Struct.scalar({'W': out(W), 'Xexp': out(Ex), 'Recon': out(Yfull), 'v': float(v), 'NumIter': float(it + 1), 'nloglk': float(nll)}))
    return res[:nargout] if nargout > 1 else res[0]


def _orthomax(A, gamma, normalize, tol, maxit):
    """Orthomax rotation (gamma 1 varimax, 0 quartimax, m/2 equamax): T maximizing the criterion, by the SVD iteration."""
    p, m = A.shape
    h = np.sqrt(np.sum(A ** 2, axis=1)) if normalize else np.ones(p)
    h = np.where(h > 0, h, 1)
    An = A / h[:, None]
    T = np.eye(m)
    d = 0
    for _ in range(maxit):
        L = An @ T
        G = An.T @ (L ** 3 - (gamma / p) * L @ np.diag(np.sum(L ** 2, axis=0)))
        U, S, Vt = np.linalg.svd(G)
        T = U @ Vt
        dold, d = d, S.sum()
        if dold != 0 and d < dold * (1 + tol):
            break
    return (An @ T) * h[:, None], T


@bi('rotatefactors', nout=2)
def rotatefactors(nargout, *args):
    """[B, T] = rotatefactors(A, 'Method', m, 'Normalize', tf, 'Reltol', t, 'Maxit', n, 'Coeff', gamma, 'Power', k): loadings rotated: 'varimax' (unless given), 'quartimax', 'equamax', 'parsimax', 'orthomax' (with 'Coeff'), 'promax' (oblique)."""
    nargchk(args, 1, 13, 'rotatefactors')
    A = _mat(args[0], 'rotatefactors', 'A')
    o = _pairs(args[1:], 'rotatefactors', ('method', 'normalize', 'reltol', 'maxit', 'coeff', 'power', 'userargs', 'type'))
    method = py_str(o.get('method', Char.of('varimax'))).lower()
    norm = _flag(o['normalize']) if 'normalize' in o else True
    tol = float(num(o['reltol'])) if 'reltol' in o else math.sqrt(np.finfo(float).eps)
    maxit = _int(o.get('maxit', 250.0))
    p, m = A.shape
    gam = {'varimax': 1.0, 'quartimax': 0.0, 'equamax': m / 2, 'parsimax': p * (m - 1) / (p + m - 2) if p + m > 2 else 1.0}
    if method in gam or method == 'orthomax':
        g = float(num(o['coeff'])) if method == 'orthomax' and 'coeff' in o else gam.get(method, 1.0)
        B, T = _orthomax(A, g, norm, tol, maxit)
    elif method == 'promax':
        power = float(num(o.get('power', 4.0)))
        Bv, Tv = _orthomax(A, 1.0, norm, tol, maxit)
        target = np.sign(Bv) * np.abs(Bv) ** power
        Tp = np.linalg.lstsq(Bv, target, rcond=None)[0]
        Tp = Tp / np.sqrt(np.sum(Tp ** 2, axis=0))
        # columns scaled so that the rotated factors keep unit variance
        S = np.linalg.inv(Tp.T @ Tp)
        Tp = Tp @ np.diag(np.sqrt(np.diag(S)))
        T = Tv @ Tp
        B = A @ T
    else:
        raise err('stats:rotatefactors:method', "The method is 'varimax', 'quartimax', 'equamax', 'parsimax', 'orthomax' or 'promax'.", 'rotatefactors')
    return (out(B), out(T)) if nargout > 1 else out(B)


@bi('factoran', nout=5)
def factoran(nargout, *args):
    """[lambda, psi, T, stats, F] = factoran(X, m), factoran(..., 'Xtype', 'data'|'covariance', 'Rotate', method, 'Scores', 'wls'|'regression', 'Nobs', n): a factor analysis model by maximum likelihood."""
    nargchk(args, 2, 14, 'factoran')
    from scipy.optimize import minimize
    from scipy import stats as st
    X = _mat(args[0], 'factoran')
    m = _int(args[1])
    o = _pairs(args[2:], 'factoran', ('xtype', 'rotate', 'scores', 'nobs', 'start', 'delta', 'optimopts', 'maxit', 'normalize', 'reltol', 'coeff', 'power', 'userargs'))
    xtype = py_str(o.get('xtype', Char.of('data'))).lower()
    if xtype == 'covariance':
        S = X
        n = _int(o['nobs']) if 'nobs' in o else None
        data = None
    else:
        data = X[~np.any(np.isnan(X), axis=1)]
        n = data.shape[0]
        S = np.cov(data, rowvar=False)
    sd = np.sqrt(np.diag(S))
    Rm = S / np.outer(sd, sd)
    d = Rm.shape[0]
    delta = float(num(o.get('delta', 0.005)))

    def loadings(psi):
        sp = np.sqrt(psi)
        Sstar = Rm / np.outer(sp, sp)
        vals, vecs = np.linalg.eigh(Sstar)
        vals, vecs = vals[::-1][:m], vecs[:, ::-1][:, :m]
        return sp[:, None] * vecs * np.sqrt(np.maximum(vals - 1, 0))

    def nll(psi):
        L = loadings(psi)
        Sig = L @ L.T + np.diag(psi)
        sign, ld = np.linalg.slogdet(Sig)
        return ld + np.trace(np.linalg.solve(Sig, Rm)) - np.linalg.slogdet(Rm)[1] - d
    psi0 = (1 - m / (2 * d)) / np.diag(np.linalg.inv(Rm))
    psi0 = np.clip(psi0, delta, 1)
    res = minimize(nll, psi0, method='L-BFGS-B', bounds=[(delta, 1)] * d, options={'maxiter': 500})
    psi = res.x
    L = loadings(psi)
    rot = o.get('rotate', Char.of('varimax'))
    T = np.eye(m)
    if m > 1 and not (is_str(rot) and py_str(rot).lower() == 'none'):
        Lr, Tr = rotatefactors(2, out(L), Char.of('Method'), rot)
        L, T = np.asarray(darr(Lr), float).reshape(d, m), np.asarray(darr(Tr), float).reshape(m, m)
    L, sg = _signs_cols(L)
    T = T * sg[None, :]
    stats = {'loglike': -res.fun, 'dfe': ((d - m) ** 2 - (d + m)) / 2}
    if n is not None and stats['dfe'] > 0:
        chisq = (n - 1 - (2 * d + 5) / 6 - 2 * m / 3) * res.fun
        stats['chisq'] = chisq
        stats['p'] = float(st.chi2.sf(chisq, stats['dfe']))
    F = EMPTY()
    if data is not None and nargout > 4:
        Z = (data - data.mean(0)) / sd
        how = py_str(o.get('scores', Char.of('wls'))).lower()
        if how == 'regression':
            F = Z @ np.linalg.solve(Rm, L)
        else:
            Pi = np.diag(1 / psi)
            F = Z @ Pi @ L @ np.linalg.inv(L.T @ Pi @ L)
        F = out(F)
    res_ = (out(L), out(psi.reshape(-1, 1)), out(T), Struct.scalar({k: float(v) for k, v in stats.items()}), F)
    return res_[:nargout] if nargout > 1 else res_[0]


def _signs_cols(L):
    s = np.sign(L.sum(0))
    s[s == 0] = 1
    return L * s, s


# ---- scaling and embedding --------------------------------------------------------------------------------------------------------------------

def _dissim(v, fn):
    D = np.asarray(darr(v), float)
    if D.ndim == 2 and D.shape[0] == 1:
        from scipy.spatial.distance import squareform as sq
        D = sq(D.reshape(-1), checks=False)
    if D.shape[0] != D.shape[1]:
        raise err(f'stats:{fn}:D', 'D is a square matrix of dissimilarities or a row from pdist.', fn)
    return D


@bi('cmdscale', nout=2)
def cmdscale(nargout, *args):
    """[Y, e] = cmdscale(D), cmdscale(D, p): classical multidimensional scaling: points whose distances are near D (exactly, when D is Euclidean), and the eigenvalues."""
    nargchk(args, 1, 2, 'cmdscale')
    D = _dissim(args[0], 'cmdscale')
    n = D.shape[0]
    J = np.eye(n) - 1 / n
    B = -0.5 * J @ (D ** 2) @ J
    vals, vecs = np.linalg.eigh((B + B.T) / 2)
    order = np.argsort(-vals, kind='stable')
    vals, vecs = vals[order], vecs[:, order]
    tol = max(abs(vals[0]), 1) * n * np.finfo(float).eps * 10
    pos = vals > tol
    p = _int(args[1]) if len(args) > 1 else int(pos.sum())
    Y = vecs[:, :p] * np.sqrt(np.maximum(vals[:p], 0))
    Y, _ = _signs(Y) if Y.size else (Y, None)
    return (out(Y), out(vals.reshape(-1, 1))) if nargout > 1 else out(Y)


def _pava(y, w=None):
    """Isotonic regression (pool adjacent violators): the nondecreasing fit to y."""
    y = np.asarray(y, float)
    w = np.ones_like(y) if w is None else np.asarray(w, float)
    vals, wts, sizes = [], [], []
    for yi, wi in zip(y, w):
        vals.append(yi)
        wts.append(wi)
        sizes.append(1)
        while len(vals) > 1 and vals[-2] > vals[-1]:
            v2, w2, s2 = vals.pop(), wts.pop(), sizes.pop()
            v1, w1, s1 = vals.pop(), wts.pop(), sizes.pop()
            vals.append((v1 * w1 + v2 * w2) / (w1 + w2))
            wts.append(w1 + w2)
            sizes.append(s1 + s2)
    return np.repeat(vals, sizes)


@bi('mdscale', nout=3)
def mdscale(nargout, *args):
    """[Y, stress, disparities] = mdscale(D, p), mdscale(..., 'Criterion', c, 'Start', s, 'Replicates', r, 'Options', statset): points in p dimensions whose distances match D: nonmetric ('stress', unless given, 'sstress') or metric ('metricstress', 'metricsstress', 'sammon', 'strain')."""
    nargchk(args, 2, 14, 'mdscale')
    from scipy.optimize import minimize
    from scipy.spatial.distance import pdist as sp_pdist, squareform as sq
    D = _dissim(args[0], 'mdscale')
    p = _int(args[1])
    o = _pairs(args[2:], 'mdscale', ('criterion', 'start', 'replicates', 'options', 'weights'))
    crit = py_str(o.get('criterion', Char.of('stress'))).lower()
    if crit not in ('stress', 'sstress', 'metricstress', 'metricsstress', 'sammon', 'strain'):
        raise err('stats:mdscale:criterion', "The criterion is 'stress', 'sstress', 'metricstress', 'metricsstress', 'sammon' or 'strain'.", 'mdscale')
    n = D.shape[0]
    dvec = sq(D, checks=False)
    if crit == 'strain':
        Y = np.asarray(darr(cmdscale(1, out(D), float(p))), float)
        dist = sp_pdist(Y)
        stress = math.sqrt(np.sum((dist - dvec) ** 2) / np.sum(dvec ** 2))
        res = (out(Y), stress, out(dvec.reshape(1, -1)))
        return res[:nargout] if nargout > 1 else res[0]
    maxit = 200
    if 'options' in o and isinstance(o['options'], Struct):
        mi = {k.lower(): v for k, v in o['options'].elem(0).items()}.get('maxiter')
        if mi is not None and numel(mi):
            maxit = _int(mi)
    start = o.get('start', Char.of('cmdscale'))
    reps = _int(o.get('replicates', 1.0))
    rs = _rs()
    order = np.argsort(dvec, kind='stable')
    best = None
    for r_ in range(reps):
        if not is_str(start):
            Y0 = np.asarray(darr(start), float)
        elif py_str(start).lower() == 'random':
            Y0 = rs.standard_normal((n, p))
        else:
            Y0 = np.asarray(darr(cmdscale(1, out(D))), float)
            Y0 = Y0[:, :p] if Y0.shape[1] >= p else np.column_stack([Y0, 1e-3 * rs.standard_normal((n, p - Y0.shape[1]))])
        nonmetric = crit in ('stress', 'sstress')
        squared = crit in ('sstress', 'metricsstress')
        disp = dvec.copy()

        def objective(yflat, disp):
            Y = yflat.reshape(n, p)
            diff = Y[:, None, :] - Y[None, :, :]
            dist = np.sqrt(np.sum(diff ** 2, -1)) + np.eye(n)
            iu = np.triu_indices(n, 1)
            dv = dist[iu]
            if crit == 'sammon':
                c = dvec.sum()
                w = 1 / np.where(dvec > 0, dvec, 1)
                f = np.sum(w * (dv - dvec) ** 2) / c
                G = np.zeros((n, n))
                G[iu] = 2 * w * (dv - dvec) / c / dv
            elif squared:
                t = disp ** 2
                den = np.sum(t ** 2) if crit == 'metricsstress' else np.sum(dv ** 4)
                num_ = np.sum((dv ** 2 - t) ** 2)
                f = num_ / den
                G = np.zeros((n, n))
                if crit == 'metricsstress':
                    G[iu] = 4 * (dv ** 2 - t) / den
                else:
                    G[iu] = (4 * (dv ** 2 - t) * den - num_ * 4 * dv ** 2) / den ** 2
            else:
                den = np.sum(dv ** 2) if crit == 'stress' else np.sum(disp ** 2)
                num_ = np.sum((dv - disp) ** 2)
                f = num_ / den
                G = np.zeros((n, n))
                if crit == 'stress':
                    G[iu] = (2 * (dv - disp) * den - num_ * 2 * dv) / den ** 2 / dv
                else:
                    G[iu] = 2 * (dv - disp) / den / dv
            G = G + G.T
            grad = (G.sum(1)[:, None] * Y - G @ Y)
            return f, grad.reshape(-1)
        y = Y0.reshape(-1)
        for _it in range(maxit if nonmetric else 1):
            if nonmetric:
                Y = y.reshape(n, p)
                dv = sp_pdist(Y)
                fit = _pava(dv[order] ** (2 if squared else 1))
                disp = np.empty_like(dvec)
                disp[order] = np.sqrt(np.maximum(fit, 0)) if squared else fit
            r = minimize(objective, y, args=(disp,), jac=True, method='L-BFGS-B', options={'maxiter': 50 if nonmetric else maxit * 10})
            change = np.max(np.abs(r.x - y))
            y = r.x
            if nonmetric and change < 1e-7:
                break
        f, _ = objective(y, disp)
        stress = math.sqrt(f) if crit in ('stress', 'metricstress', 'sstress', 'metricsstress') else f
        if best is None or stress < best[1]:
            best = (y.reshape(n, p) - y.reshape(n, p).mean(0), stress, disp)
    Y, stress, disp = best
    res = (out(Y), float(stress), out(disp.reshape(1, -1)))
    return res[:nargout] if nargout > 1 else res[0]


def _tsne_P(D2, perplexity):
    n = D2.shape[0]
    P = np.zeros((n, n))
    target = math.log(perplexity)
    for i in range(n):
        lo, hi, beta = None, None, 1.0
        d = np.delete(D2[i], i)
        for _ in range(100):
            e = np.exp(-(d - d.min()) * beta)
            s = e.sum()
            H = math.log(s) + beta * np.sum((d - d.min()) * e) / s
            if abs(H - target) < 1e-5:
                break
            if H > target:
                lo = beta
                beta = beta * 2 if hi is None else (beta + hi) / 2
            else:
                hi = beta
                beta = beta / 2 if lo is None else (beta + lo) / 2
        row = e / s
        P[i, np.arange(n) != i] = row
    P = (P + P.T) / (2 * n)
    return np.maximum(P, 1e-12)


@bi('tsne', nout=2)
def tsne(nargout, *args):
    """[Y, loss] = tsne(X, 'NumDimensions', d, 'Perplexity', p, 'Exaggeration', e, 'LearnRate', r, 'NumPCAComponents', k, 'Distance', dist, 'Standardize', tf, 'Options', statset): a t-distributed stochastic neighbour embedding (computed exactly)."""
    nargchk(args, 1, 23, 'tsne')
    X = _mat(args[0], 'tsne')
    o = _pairs(args[1:], 'tsne', ('numdimensions', 'perplexity', 'exaggeration', 'learnrate', 'numpcacomponents', 'distance', 'standardize', 'options', 'algorithm', 'initialy', 'numprint', 'theta', 'verbose', 'cache'))
    X = X[~np.any(np.isnan(X), axis=1)]
    n = X.shape[0]
    nd = _int(o.get('numdimensions', 2.0))
    perp = float(num(o.get('perplexity', 30.0)))
    if perp >= n:
        raise err('stats:tsne:perplexity', f'The perplexity ({perp:g}) is less than the number of points ({n}).', 'tsne')
    exag = float(num(o.get('exaggeration', 4.0)))
    lr = float(num(o.get('learnrate', 500.0)))
    if 'standardize' in o and _flag(o['standardize']):
        sd = X.std(0, ddof=1)
        X = (X - X.mean(0)) / np.where(sd > 0, sd, 1)
    k = _int(o.get('numpcacomponents', 0.0))
    if k:
        Xc = X - X.mean(0)
        U, S, Vt = np.linalg.svd(Xc, full_matrices=False)
        X = Xc @ Vt[:k].T
    margs = [o['distance']] if 'distance' in o else []
    name, kw, fh = _metric(margs, X, 'tsne')
    D = _cdist(X, X, name, kw, fh)
    D2 = D ** 2 if name in ('euclidean', 'seuclidean', 'mahalanobis', 'minkowski') else D
    P = _tsne_P(D2, perp)
    maxit = 1000
    if 'options' in o and isinstance(o['options'], Struct):
        mi = {kk.lower(): v for kk, v in o['options'].elem(0).items()}.get('maxiter')
        if mi is not None and numel(mi):
            maxit = _int(mi)
    rs = _rs()
    Y = np.asarray(darr(o['initialy']), float) if 'initialy' in o else 1e-4 * rs.standard_normal((n, nd))
    vel = np.zeros_like(Y)
    gains = np.ones_like(Y)
    loss = 0.0
    for it in range(maxit):
        Pm = P * exag if it < 99 else P
        sq = np.sum(Y ** 2, 1)
        num_ = 1 / (1 + sq[:, None] + sq[None, :] - 2 * Y @ Y.T)
        np.fill_diagonal(num_, 0)
        Q = np.maximum(num_ / num_.sum(), 1e-12)
        PQ = (Pm - Q) * num_
        grad = 4 * (np.diag(PQ.sum(1)) - PQ) @ Y
        mom = 0.5 if it < 250 else 0.8
        gains = np.where(np.sign(grad) != np.sign(vel), gains + 0.2, gains * 0.8)
        gains = np.maximum(gains, 0.01)
        vel = mom * vel - lr * gains * grad
        Y = Y + vel
        Y = Y - Y.mean(0)
        if it == maxit - 1 or (it > 100 and np.max(np.abs(grad)) < 1e-10):
            loss = float(np.sum(P * np.log(P / Q)))
            break
    return (out(Y), loss) if nargout > 1 else out(Y)


@bi('procrustes', nout=3)
def procrustes(nargout, *args):
    """[d, Z, transform] = procrustes(X, Y), procrustes(..., 'Scaling', tf, 'Reflection', tf|'best'): Y turned, scaled and moved to fit X best; d the residual sum of squares relative to X's."""
    nargchk(args, 2, 6, 'procrustes')
    X, Y = _mat(args[0], 'procrustes'), _mat(args[1], 'procrustes', 'Y')
    o = _pairs(args[2:], 'procrustes', ('scaling', 'reflection'))
    scaling = _flag(o['scaling']) if 'scaling' in o else True
    refl = o.get('reflection', Char.of('best'))
    n, m = X.shape
    if Y.shape[1] < m:
        Y = np.column_stack([Y, np.zeros((n, m - Y.shape[1]))])
    muX, muY = X.mean(0), Y.mean(0)
    X0, Y0 = X - muX, Y - muY
    ssX, ssY = np.sum(X0 ** 2), np.sum(Y0 ** 2)
    nX, nY = math.sqrt(ssX), math.sqrt(ssY)
    X0n, Y0n = X0 / nX, Y0 / nY
    A = X0n.T @ Y0n
    U, S, Vt = np.linalg.svd(A)
    T = Vt.T @ U.T
    if not (is_str(refl) and py_str(refl).lower() == 'best'):
        want = _flag(refl)
        if (np.linalg.det(T) < 0) != want:
            Vt[-1] *= -1
            S[-1] *= -1
            T = Vt.T @ U.T
    tr = S.sum()
    if scaling:
        b = tr * nX / nY
        d = 1 - tr ** 2
        Z = nX * tr * Y0n @ T + muX
    else:
        b = 1.0
        d = 1 + ssY / ssX - 2 * tr * nY / nX
        Z = nY * Y0n @ T + muX
    c = muX - b * muY @ T
    tf = Struct.scalar({'T': out(T), 'b': float(b), 'c': out(np.tile(c, (n, 1)))})
    res = (float(d), out(Z), tf)
    return res[:nargout] if nargout > 1 else res[0]


@bi('canoncorr', nout=6)
def canoncorr(nargout, *args):
    """[A, B, r, U, V, stats] = canoncorr(X, Y): canonical correlation: the combinations of X's and Y's columns most correlated, and the tests of how many are."""
    nargchk(args, 2, 2, 'canoncorr')
    from scipy import stats as st
    X, Y = _mat(args[0], 'canoncorr'), _mat(args[1], 'canoncorr', 'Y')
    n = X.shape[0]
    X0, Y0 = X - X.mean(0), Y - Y.mean(0)
    Q1, T11 = np.linalg.qr(X0)
    Q2, T22 = np.linalg.qr(Y0)
    p1 = int(np.linalg.matrix_rank(T11))
    p2 = int(np.linalg.matrix_rank(T22))
    d = min(p1, p2)
    L, D, Mt = np.linalg.svd(Q1[:, :p1].T @ Q2[:, :p2])
    A = np.linalg.solve(T11[:p1, :p1], L[:, :d]) * math.sqrt(n - 1)
    B = np.linalg.solve(T22[:p2, :p2], Mt.T[:, :d]) * math.sqrt(n - 1)
    r = np.clip(D[:d], 0, 1)
    U, V = X0[:, :p1] @ A, Y0[:, :p2] @ B
    k = np.arange(d)
    wilks = np.array([np.prod(1 - r[j:] ** 2) for j in k])
    df1 = (p1 - k) * (p2 - k)
    chisq = -(n - 0.5 * (p1 + p2 + 3)) * np.log(wilks)
    pc = st.chi2.sf(chisq, df1)
    stats = Struct.scalar({'Wilks': out(wilks.reshape(1, -1)), 'df1': out(df1.reshape(1, -1).astype(float)), 'chisq': out(chisq.reshape(1, -1)),
                           'pChisq': out(pc.reshape(1, -1)), 'dfe': float(n - 1)})
    res = (out(A), out(B), out(r.reshape(1, -1)), out(U), out(V), stats)
    return res[:nargout] if nargout > 1 else res[0]


@bi('barttest', nout=3)
def barttest(nargout, *args):
    """[ndim, prob, chisquare] = barttest(X, alpha): Bartlett's test of how many principal components differ: the smallest k for which the last p - k eigenvalues may be equal."""
    nargchk(args, 1, 2, 'barttest')
    from scipy import stats as st
    X = _mat(args[0], 'barttest')
    alpha = float(num(args[1])) if len(args) > 1 else 0.05
    n, p = X.shape
    lam = np.sort(np.linalg.eigvalsh(np.cov(X, rowvar=False)))[::-1]
    probs, chis = [], []
    ndim = None
    for k in range(p - 1):
        tail = lam[k:]
        q = p - k
        nu = n - 1 - (2 * p + 5) / 6 - 2 * k / 3
        chi = -nu * (np.sum(np.log(tail)) - q * math.log(tail.mean()))
        df = (q - 1) * (q + 2) / 2
        pr = float(st.chi2.sf(chi, df))
        probs.append(pr)
        chis.append(chi)
        if ndim is None and pr > alpha:
            ndim = k
    if ndim is None:
        ndim = p - 1
        R.warn('stats:barttest:NotEnoughDims', 'Every test was significant: no smaller number of dimensions was found.')
    res = (float(ndim), out(np.array(probs).reshape(-1, 1)), out(np.array(chis).reshape(-1, 1)))
    return res[:nargout] if nargout > 1 else res[0]


@bi('nnmf', nout=3)
def nnmf(nargout, *args):
    """[W, H, D] = nnmf(A, k), nnmf(..., 'Algorithm', 'als'|'mult', 'Replicates', r, 'W0', W0, 'H0', H0, 'Options', statset): A ~ W*H with W and H not negative; D the rms residual."""
    nargchk(args, 2, 14, 'nnmf')
    A = _mat(args[0], 'nnmf', 'A')
    if np.any(A < 0):
        raise err('stats:nnmf:NegativeValues', 'A has no negative values.', 'nnmf')
    k = _int(args[1])
    o = _pairs(args[2:], 'nnmf', ('algorithm', 'replicates', 'w0', 'h0', 'options'))
    alg = py_str(o.get('algorithm', Char.of('als'))).lower()
    reps = _int(o.get('replicates', 1.0))
    maxit, tolx, tolf = 100, 1e-4, 1e-4
    if 'options' in o and isinstance(o['options'], Struct):
        for key, val in o['options'].elem(0).items():
            if numel(val):
                kl = key.lower()
                if kl == 'maxiter':
                    maxit = _int(val)
                elif kl == 'tolx':
                    tolx = float(num(val))
                elif kl == 'tolfun':
                    tolf = float(num(val))
    n, m = A.shape
    rs = _rs()
    best = None
    sqrt_eps = math.sqrt(np.finfo(float).eps)
    for r in range(reps):
        W = np.asarray(darr(o['w0']), float) if 'w0' in o and r == 0 else rs.random_sample((n, k))
        H = np.asarray(darr(o['h0']), float) if 'h0' in o and r == 0 else rs.random_sample((k, m))
        d0 = None
        for it in range(maxit):
            if alg == 'mult':
                H1 = H * (W.T @ A) / (W.T @ W @ H + np.finfo(float).eps)
                W1 = W * (A @ H1.T) / (W @ H1 @ H1.T + np.finfo(float).eps)
            else:
                H1 = np.maximum(np.linalg.lstsq(W, A, rcond=None)[0], 0)
                W1 = np.maximum(np.linalg.lstsq(H1.T, A.T, rcond=None)[0].T, 0)
            d = np.linalg.norm(A - W1 @ H1) / math.sqrt(n * m)
            dw = np.max(np.abs(W1 - W)) / (sqrt_eps + np.max(np.abs(W)))
            dh = np.max(np.abs(H1 - H)) / (sqrt_eps + np.max(np.abs(H)))
            W, H = W1, H1
            if d0 is not None and (abs(d0 - d) <= tolf * max(1, d0) or max(dw, dh) <= tolx):
                break
            d0 = d
        if best is None or d < best[2]:
            best = (W, H, d)
    W, H, d = best
    # H's rows of unit length, W scaled to match; the columns in order of their size
    hn = np.sqrt(np.sum(H ** 2, axis=1))
    hn = np.where(hn > 0, hn, 1)
    H = H / hn[:, None]
    W = W * hn[None, :]
    order = np.argsort(-np.sum(W ** 2, axis=0), kind='stable')
    res = (out(W[:, order]), out(H[order]), float(d))
    return res[:nargout] if nargout > 1 else res[0]


@bi('corrcov', nout=2)
def corrcov(nargout, *args):
    """[R, sigma] = corrcov(C): the correlation matrix of a covariance matrix, and the standard deviations."""
    nargchk(args, 1, 1, 'corrcov')
    single = arr(args[0], 'corrcov').dtype == np.float32
    C = _mat(args[0], 'corrcov', 'C')
    if C.shape[0] != C.shape[1] or not np.allclose(C, C.T, equal_nan=True):
        raise err('stats:corrcov:BadCovariance', 'C is a symmetric covariance matrix.', 'corrcov')
    s = np.sqrt(np.diag(C))
    with np.errstate(invalid='ignore', divide='ignore'):
        Rm = C / np.outer(s, s)
    Rm = (Rm + Rm.T) / 2
    big = np.abs(Rm) > 1                   # round-off past 1 is cut back; a zero variance leaves NaN, its diagonal too
    Rm[big] = np.sign(Rm[big])
    np.fill_diagonal(Rm, np.sign(np.diag(Rm)))
    if single:
        Rm, s = Rm.astype(np.float32), s.astype(np.float32)
    return (out(Rm), out(s.reshape(-1, 1))) if nargout > 1 else out(Rm)


# ---- the builtins that take a gmdistribution too ---------------------------------------------------------------------------------------------

def _wrap(name, handler, test):
    info = REG.get(name)
    if info is None:
        return
    orig = info.fn
    ws, aw = info.ws, info.aw
    if aw:
        async def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return await orig(*a)
    else:
        def f(*a):
            args = a[2:] if ws else a[1:]
            if args and test(args[0]):
                return handler(a[1] if ws else a[0], *args)
            return orig(*a)
    info.fn = f
    info.nout = max(info.nout, 3)


@bi('mahal')
def mahal(nargout, *args):
    """d = mahal(Y, X): the squared Mahalanobis distance of each row of Y from the sample X (its mean and covariance); mahal(gm, X) from each component of a Gaussian mixture."""
    nargchk(args, 2, 2, 'mahal')
    if isinstance(args[0], GMM):
        return _gm_mahal(nargout, args[0], args[1])
    Y, X = _mat(args[0], 'mahal', 'Y'), _mat(args[1], 'mahal')
    if Y.shape[1] != X.shape[1]:
        raise err('stats:mahal:InputSizeMismatch', 'Y and X have as many columns.', 'mahal')
    if X.shape[0] <= X.shape[1]:
        raise err('stats:mahal:TooFewRows', 'X has more rows than columns.', 'mahal')
    mu = X.mean(0)
    Q, Rr = np.linalg.qr(X - mu)
    Z = np.linalg.solve(Rr.T, (Y - mu).T)
    return out((np.sum(Z ** 2, axis=0) * (X.shape[0] - 1)).reshape(-1, 1))


_is_gm = lambda v: isinstance(v, GMM)        # noqa: E731
_wrap('cluster', _gm_cluster, _is_gm)
_wrap('pdf', _gm_pdf, _is_gm)
_wrap('random', _gm_random, _is_gm)
