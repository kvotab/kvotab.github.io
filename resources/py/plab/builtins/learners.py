"""The learning algorithms under mlmodels.py, on NumPy arrays only: CART
trees, k nearest neighbours, discriminant analysis, naive Bayes, the SMO
solver for support vector machines (classification and epsilon
regression), linear models (logistic and least squares by L-BFGS, linear
SVMs by dual coordinate descent), multilayer perceptrons, Gaussian
process regression, random Fourier features, and the ensembles (bagging,
AdaBoost, SAMME, LogitBoost, GentleBoost, least-squares boosting).

Classification learners take y as class numbers 0..K-1 and give scores
(n, K); regression learners take y as numbers and give predictions."""
import math

import numpy as np


# ---- CART -------------------------------------------------------------------------------------------------------------------------------

class Tree:
    """A binary tree grown breadth first: classification by the Gini index (or deviance), regression by the squared
    error; up to max_splits splits, a node split only when it has min_parent observations, each child min_leaf."""

    def __init__(self, K=0, max_splits=None, min_leaf=1, min_parent=10, criterion='gdi', nvars=None, rs=None, prior=None):
        self.K = K                       # 0 for regression
        self.max_splits = max_splits
        self.min_leaf = min_leaf
        self.min_parent = min_parent
        self.criterion = criterion
        self.nvars = nvars               # variables tried at each split (a random subset), None for all
        self.rs = rs
        self.prior = prior

    def _impurity(self, counts):
        tot = counts.sum(-1, keepdims=True)
        p = counts / np.where(tot > 0, tot, 1)
        if self.criterion == 'deviance':
            with np.errstate(divide='ignore', invalid='ignore'):
                return -np.nansum(np.where(p > 0, p * np.log(p), 0), axis=-1)
        return 1 - np.sum(p ** 2, axis=-1)

    def fit(self, X, y, w=None):
        n, p = X.shape
        w = np.ones(n) if w is None else np.asarray(w, float)
        maxs = self.max_splits if self.max_splits is not None else n - 1
        cut_var, cut_pt, children, value, size, risk, parent = [], [], [], [], [], [], []

        def node_value(idx):
            if self.K:
                c = np.bincount(y[idx], weights=w[idx], minlength=self.K)
                return c / c.sum() if c.sum() > 0 else np.full(self.K, 1 / self.K)
            return np.average(y[idx], weights=w[idx]) if w[idx].sum() > 0 else 0.0

        def node_risk(idx):
            if self.K:
                c = np.bincount(y[idx], weights=w[idx], minlength=self.K)
                return float(w[idx].sum() * self._impurity(c))
            m = np.average(y[idx], weights=w[idx])
            return float(np.sum(w[idx] * (y[idx] - m) ** 2))

        def new_node(idx, par):
            cut_var.append(-1)
            cut_pt.append(np.nan)
            children.append([-1, -1])
            value.append(node_value(idx))
            size.append(idx.size)
            risk.append(node_risk(idx))
            parent.append(par)
            return len(value) - 1
        root = new_node(np.arange(n), -1)
        queue = [(root, np.arange(n))]
        splits = 0
        while queue and splits < maxs:
            nxt = []
            for node, idx in queue:
                if splits >= maxs:
                    break
                if idx.size < self.min_parent or idx.size < 2 * self.min_leaf or risk[node] <= 1e-12 * max(1.0, w[idx].sum()):
                    continue
                best = self._best_split(X[idx], y[idx], w[idx], risk[node])
                if best is None:
                    continue
                j, c = best
                left = idx[X[idx, j] < c]
                right = idx[X[idx, j] >= c]
                cut_var[node], cut_pt[node] = j, c
                lnode = new_node(left, node)
                rnode = new_node(right, node)
                children[node] = [lnode, rnode]
                splits += 1
                nxt += [(lnode, left), (rnode, right)]
            queue = nxt
        self.cut_var = np.array(cut_var)
        self.cut_pt = np.array(cut_pt)
        self.children = np.array(children)
        self.value = np.array(value)
        self.size = np.array(size)
        self.risk = np.array(risk)
        self.parent = np.array(parent)
        self.p = p
        return self

    def _best_split(self, X, y, w, parent_risk):
        n, p = X.shape
        vars_ = np.arange(p)
        if self.nvars is not None and self.nvars < p:
            vars_ = self.rs.choice(p, self.nvars, replace=False)
        best = None
        best_gain = 1e-12 * max(1.0, abs(parent_risk))
        for j in vars_:
            order = np.argsort(X[:, j], kind='stable')
            xs = X[order, j]
            ok = xs[:-1] < xs[1:]
            pos = np.arange(1, n)
            ok &= (pos >= self.min_leaf) & (n - pos >= self.min_leaf)
            if not ok.any():
                continue
            ws = w[order]
            if self.K:
                onehot = np.zeros((n, self.K))
                onehot[np.arange(n), y[order]] = ws
                cl = np.cumsum(onehot, axis=0)[:-1]
                cr = cl[-1] + onehot[-1] - cl
                wl, wr = cl.sum(1), cr.sum(1)
                r = wl * self._impurity(cl) + wr * self._impurity(cr)
            else:
                ys = y[order]
                cw = np.cumsum(ws)[:-1]
                cy = np.cumsum(ws * ys)[:-1]
                cyy = np.cumsum(ws * ys * ys)[:-1]
                tw, ty, tyy = ws.sum(), np.sum(ws * ys), np.sum(ws * ys * ys)
                rw, ry, ryy = tw - cw, ty - cy, tyy - cyy
                with np.errstate(divide='ignore', invalid='ignore'):
                    r = (cyy - cy ** 2 / np.where(cw > 0, cw, 1)) + (ryy - ry ** 2 / np.where(rw > 0, rw, 1))
            gain = parent_risk - r
            gain = np.where(ok, gain, -np.inf)
            k = int(np.argmax(gain))
            if gain[k] > best_gain:
                best_gain = gain[k]
                best = (int(j), (xs[k] + xs[k + 1]) / 2)
        return best

    def leaves(self, X):
        node = np.zeros(X.shape[0], int)
        active = np.ones(X.shape[0], bool)
        while active.any():
            cv = self.cut_var[node]
            active = cv >= 0
            if not active.any():
                break
            idx = np.flatnonzero(active)
            go_left = X[idx, cv[idx]] < self.cut_pt[node[idx]]
            node[idx] = np.where(go_left, self.children[node[idx], 0], self.children[node[idx], 1])
        return node

    def predict(self, X):
        v = self.value[self.leaves(X)]
        return v


# ---- k nearest neighbours ------------------------------------------------------------------------------------------------------------------

class KNN:
    def __init__(self, K, k=1, distance='euclidean', dist_kw=None, weight='equal', standardize=False, prior=None):
        self.K, self.k, self.distance, self.dist_kw, self.weight, self.standardize = K, k, distance, dist_kw or {}, weight, standardize
        self.prior = prior

    def fit(self, X, y, w=None):
        self.mu = X.mean(0) if self.standardize else np.zeros(X.shape[1])
        sd = X.std(0, ddof=1) if self.standardize else np.ones(X.shape[1])
        self.sd = np.where(sd > 0, sd, 1)
        self.X = (X - self.mu) / self.sd
        self.y = y
        self.w = np.ones(X.shape[0]) if w is None else w
        return self

    def predict(self, X):
        from scipy.spatial.distance import cdist
        Z = (X - self.mu) / self.sd
        name = {'squaredeuclidean': 'sqeuclidean', 'chebychev': 'chebyshev'}.get(self.distance, self.distance)
        D = cdist(Z, self.X, name, **self.dist_kw)
        order = np.argsort(D, axis=1, kind='stable')[:, :self.k]
        d = np.take_along_axis(D, order, axis=1)
        if self.weight == 'inverse':
            wt = 1 / np.maximum(d, 1e-300)
        elif self.weight == 'squaredinverse':
            wt = 1 / np.maximum(d, 1e-300) ** 2
        else:
            wt = np.ones_like(d)
        wt = wt * self.w[order]
        S = np.zeros((X.shape[0], self.K))
        for c in range(self.K):
            S[:, c] = np.sum(wt * (self.y[order] == c), axis=1)
        if self.prior is not None:
            S = S * self.prior[None, :]
        tot = S.sum(1, keepdims=True)
        return S / np.where(tot > 0, tot, 1)


# ---- discriminant analysis and naive Bayes ----------------------------------------------------------------------------------------------------

class Discriminant:
    def __init__(self, K, kind='linear', prior=None, gamma=0.0):
        self.K, self.kind, self.prior, self.gamma = K, kind.lower(), prior, gamma

    def fit(self, X, y, w=None):
        n, p = X.shape
        self.mu = np.array([X[y == c].mean(0) for c in range(self.K)])
        counts = np.array([np.sum(y == c) for c in range(self.K)], float)
        self.prior = counts / n if self.prior is None else self.prior
        if self.kind in ('linear', 'diaglinear', 'pseudolinear'):
            R = X - self.mu[y]
            S = R.T @ R / max(n - self.K, 1)
            if self.gamma:
                S = (1 - self.gamma) * S + self.gamma * np.diag(np.diag(S))
            if self.kind == 'diaglinear':
                S = np.diag(np.diag(S))
            self.Sigma = np.stack([S] * self.K)
        else:
            covs = []
            for c in range(self.K):
                Xc = X[y == c]
                S = np.cov(Xc, rowvar=False).reshape(p, p) if Xc.shape[0] > 1 else np.zeros((p, p))
                if self.kind == 'diagquadratic':
                    S = np.diag(np.diag(S))
                covs.append(S)
            self.Sigma = np.array(covs)
        return self

    def log_post(self, X):
        L = np.empty((X.shape[0], self.K))
        for c in range(self.K):
            S = self.Sigma[c]
            Sinv = np.linalg.pinv(S)
            sign, logdet = np.linalg.slogdet(S)
            if sign <= 0:
                ev = np.linalg.eigvalsh(S)
                logdet = float(np.sum(np.log(ev[ev > 1e-12 * max(ev.max(), 1e-300)])))
            d = X - self.mu[c]
            L[:, c] = np.log(self.prior[c]) - 0.5 * logdet - 0.5 * np.einsum('ij,jk,ik->i', d, Sinv, d)
        return L

    def predict(self, X):
        L = self.log_post(X)
        L -= L.max(1, keepdims=True)
        P = np.exp(L)
        return P / P.sum(1, keepdims=True)


class NaiveBayes:
    def __init__(self, K, dists, prior=None, width=None, rs=None):
        self.K, self.dists, self.prior, self.width = K, dists, prior, width

    def fit(self, X, y, w=None):
        n, p = X.shape
        counts = np.array([np.sum(y == c) for c in range(self.K)], float)
        self.prior = counts / n if self.prior is None else self.prior
        self.params = []
        for j in range(p):
            d = self.dists[j]
            col = []
            for c in range(self.K):
                x = X[y == c, j]
                if d == 'normal':
                    sd = x.std(ddof=1) if x.size > 1 else 0.0
                    col.append((x.mean(), max(sd, 1e-12)))
                elif d == 'kernel':
                    sig = np.median(np.abs(x - np.median(x))) / 0.6745 if x.size else 1.0
                    if sig == 0:
                        sig = x.std(ddof=1) if x.size > 1 else 1.0
                    h = self.width if self.width is not None else max(sig, 1e-12) * (4 / (3 * max(x.size, 1))) ** 0.2
                    col.append((x.copy(), h))
                elif d == 'mvmn':
                    levels = np.unique(X[:, j])
                    cnt = np.array([np.sum(x == lv) for lv in levels], float)
                    col.append((levels, (cnt + 1) / (x.size + levels.size)))
                else:          # 'mn': counts of tokens, the feature's share of the class's total
                    col.append(None)
            self.params.append(col)
        if any(d == 'mn' for d in self.dists):
            tot = np.array([X[y == c].sum(0) for c in range(self.K)])
            self.mn = (tot + 1) / (tot.sum(1, keepdims=True) + X.shape[1])
        return self

    def log_post(self, X):
        from scipy.stats import norm
        L = np.tile(np.log(self.prior), (X.shape[0], 1))
        for j, d in enumerate(self.dists):
            for c in range(self.K):
                prm = self.params[j][c]
                if d == 'normal':
                    L[:, c] += norm.logpdf(X[:, j], prm[0], prm[1])
                elif d == 'kernel':
                    xs, h = prm
                    dens = np.mean(norm.pdf((X[:, j, None] - xs[None, :]) / h), axis=1) / h
                    L[:, c] += np.log(np.maximum(dens, 1e-300))
                elif d == 'mvmn':
                    levels, pr = prm
                    pos = {float(v): i for i, v in enumerate(levels)}
                    L[:, c] += np.log([pr[pos[float(v)]] if float(v) in pos else 1e-300 for v in X[:, j]])
                elif d == 'mn':
                    L[:, c] += X[:, j] * np.log(self.mn[c, j])
        return L

    def predict(self, X):
        L = self.log_post(X)
        L -= L.max(1, keepdims=True)
        P = np.exp(L)
        return P / P.sum(1, keepdims=True)


# ---- support vector machines ---------------------------------------------------------------------------------------------------------------

def kernel(A, B, kind, scale=1.0, order=3, offset=0.0):
    A = A / scale
    B = B / scale
    if kind == 'linear':
        return A @ B.T
    if kind in ('gaussian', 'rbf'):
        sq = np.sum(A ** 2, 1)[:, None] + np.sum(B ** 2, 1)[None, :] - 2 * A @ B.T
        return np.exp(-np.maximum(sq, 0))
    if kind == 'polynomial':
        return (1 + A @ B.T) ** order
    raise ValueError(f'kernel {kind}')


def smo(Q, p, y, C, tol=1e-3, maxit=1000000):
    """min 1/2 a'Qa + p'a, y'a = constant, 0 <= a <= C (C a vector), from a = 0: LIBSVM's SMO with its second-order choice
    of the pair (Fan, Chen and Lin 2005). Gives (a, the gradient, rho)."""
    n = p.size
    a = np.zeros(n)
    G = p.astype(float).copy()
    QD = np.diag(Q).copy()
    tau = 1e-12
    it = 0
    for it in range(maxit):
        up = ((y > 0) & (a < C)) | ((y < 0) & (a > 0))
        low = ((y > 0) & (a > 0)) | ((y < 0) & (a < C))
        mg = -y * G
        if not up.any() or not low.any():
            break
        i = int(np.argmax(np.where(up, mg, -np.inf)))
        Gmax = mg[i]
        Gmin = np.min(np.where(low, mg, np.inf))
        if Gmax - Gmin < tol:
            break
        b = Gmax - mg
        ok = low & (b > 0)
        if not ok.any():
            break
        aij = QD[i] + QD - 2 * y[i] * y * Q[i]
        aij = np.where(aij > 0, aij, tau)
        j = int(np.argmax(np.where(ok, b * b / aij, -np.inf)))
        # the analytic step on the pair, clipped to the box (LIBSVM's update)
        Qi, Qj = Q[i], Q[j]
        Ci, Cj = C[i], C[j]
        ai_old, aj_old = a[i], a[j]
        if y[i] != y[j]:
            quad = QD[i] + QD[j] + 2 * Qi[j]
            quad = quad if quad > 0 else tau
            delta = (-G[i] - G[j]) / quad
            diff = a[i] - a[j]
            a[i] += delta
            a[j] += delta
            if diff > 0:
                if a[j] < 0:
                    a[j] = 0
                    a[i] = diff
            elif a[i] < 0:
                a[i] = 0
                a[j] = -diff
            if diff > Ci - Cj:
                if a[i] > Ci:
                    a[i] = Ci
                    a[j] = Ci - diff
            elif a[j] > Cj:
                a[j] = Cj
                a[i] = Cj + diff
        else:
            quad = QD[i] + QD[j] - 2 * Qi[j]
            quad = quad if quad > 0 else tau
            delta = (G[i] - G[j]) / quad
            s = a[i] + a[j]
            a[i] -= delta
            a[j] += delta
            if s > Ci:
                if a[i] > Ci:
                    a[i] = Ci
                    a[j] = s - Ci
            elif a[j] < 0:
                a[j] = 0
                a[i] = s
            if s > Cj:
                if a[j] > Cj:
                    a[j] = Cj
                    a[i] = s - Cj
            elif a[i] < 0:
                a[i] = 0
                a[j] = s
        G += Qi * (a[i] - ai_old) + Qj * (a[j] - aj_old)
    # rho: the mean of y*G over the free variables, or the middle of the bounds the others set
    yG = y * G
    at_up = a >= C
    at_low = a <= 0
    free = ~at_up & ~at_low
    if free.any():
        rho = float(yG[free].mean())
    else:
        ub_set = (at_up & (y < 0)) | (at_low & (y > 0))
        lb_set = (at_up & (y > 0)) | (at_low & (y < 0))
        ub = float(np.min(yG[ub_set])) if ub_set.any() else np.inf
        lb = float(np.max(yG[lb_set])) if lb_set.any() else -np.inf
        rho = (ub + lb) / 2 if np.isfinite(ub) and np.isfinite(lb) else (ub if np.isfinite(ub) else lb)
    return a, G, rho, it


class SVM:
    """Binary classification (y in {-1, +1}) or epsilon regression, in a kernel's space."""

    def __init__(self, regression=False, kernel_kind='linear', C=1.0, scale=1.0, order=3, epsilon=0.1, standardize=False, tol=1e-3):
        self.regression, self.kind, self.C, self.scale, self.order = regression, kernel_kind, C, scale, order
        self.epsilon, self.standardize, self.tol = epsilon, standardize, tol

    def fit(self, X, y, w=None):
        n = X.shape[0]
        self.mu = X.mean(0) if self.standardize else np.zeros(X.shape[1])
        sd = X.std(0, ddof=1) if self.standardize else np.ones(X.shape[1])
        self.sd = np.where(sd > 0, sd, 1)
        Z = (X - self.mu) / self.sd
        K = kernel(Z, Z, self.kind, self.scale, self.order)
        Cv = np.full(n, float(self.C)) if w is None else float(self.C) * np.asarray(w, float) * n / np.sum(w)
        if not self.regression:
            yy = np.where(y > 0, 1.0, -1.0)
            Q = (yy[:, None] * yy[None, :]) * K
            a, G, rho, self.iters = smo(Q, -np.ones(n), yy, Cv, self.tol)
            coef = a * yy
        else:
            yy = np.concatenate([np.ones(n), -np.ones(n)])
            KK = np.block([[K, K], [K, K]])
            Q = (yy[:, None] * yy[None, :]) * KK
            pvec = np.concatenate([self.epsilon - y, self.epsilon + y])
            a, G, rho, self.iters = smo(Q, pvec, yy, np.concatenate([Cv, Cv]), self.tol)
            coef = a[:n] - a[n:]
            a = np.abs(coef)
        sv = np.abs(coef) > 1e-12 * max(1.0, self.C)
        self.is_sv = sv
        self.alpha = coef[sv]
        self.sv = Z[sv]
        self.bias = -rho
        if self.kind == 'linear':
            self.beta = (self.sv / self.scale).T @ self.alpha
        return self

    def decision(self, X):
        Z = (X - self.mu) / self.sd
        if self.sv.shape[0] == 0:
            return np.full(X.shape[0], self.bias)
        return kernel(Z, self.sv, self.kind, self.scale, self.order) @ self.alpha + self.bias


# ---- linear models ---------------------------------------------------------------------------------------------------------------------------

class Linear:
    """Linear classification ('svm' by dual coordinate descent, 'logistic' by L-BFGS) or regression ('leastsquares' by
    L-BFGS, 'svm' epsilon-insensitive by dual coordinate descent), ridge (lambda/2 |b|^2) or lasso (lambda |b|_1), the bias
    not penalized."""

    def __init__(self, regression, learner, lam, reg='ridge', epsilon=0.1, maxit=1000):
        self.regression, self.learner, self.lam, self.reg, self.epsilon, self.maxit = regression, learner, lam, reg, epsilon, maxit

    def fit(self, X, y, w=None):
        from scipy.optimize import minimize
        n, p = X.shape
        w = np.ones(n) if w is None else np.asarray(w, float) * n / np.sum(w)
        yy = np.where(y > 0, 1.0, -1.0) if not self.regression else np.asarray(y, float)
        lam = self.lam
        if self.learner == 'svm' and self.reg == 'ridge':
            # the dual of 1/n sum loss + lam/2 |b|^2 with a bias column: C = 1/(n lam)
            C = 1.0 / (n * lam)
            Xa = np.column_stack([X, np.ones(n)])
            beta = np.zeros(p + 1)
            QD = np.sum(Xa ** 2, 1)
            rs = np.random.RandomState(0)
            if not self.regression:
                alpha = np.zeros(n)
                for _ in range(self.maxit):
                    maxpg = 0.0
                    for i in rs.permutation(n):
                        G = yy[i] * (Xa[i] @ beta) - 1
                        Ci = C * w[i]
                        pg = min(G, 0) if alpha[i] == 0 else (max(G, 0) if alpha[i] == Ci else G)
                        maxpg = max(maxpg, abs(pg))
                        if pg != 0:
                            old = alpha[i]
                            alpha[i] = min(max(alpha[i] - G / QD[i], 0), Ci)
                            beta += (alpha[i] - old) * yy[i] * Xa[i]
                    if maxpg < 1e-4:
                        break
            else:
                b_ = np.zeros(n)
                eps = self.epsilon
                for _ in range(self.maxit):
                    change = 0.0
                    for i in rs.permutation(n):
                        g = Xa[i] @ beta - yy[i]
                        Ci = C * w[i]
                        old = b_[i]
                        # minimize 1/2 QD d^2 + (g) d + eps |b + d| over b + d in [-C, C]
                        cand = []
                        for s in (1.0, -1.0):
                            v = old - (g + s * eps) / QD[i]
                            if (s > 0 and v > 0) or (s < 0 and v < 0):
                                cand.append(v)
                        cand.append(0.0)
                        best, bv = old, None
                        for v in cand:
                            v = min(max(v, -Ci), Ci)
                            d = v - old
                            val = 0.5 * QD[i] * d * d + g * d + eps * abs(v)
                            if bv is None or val < bv:
                                bv, best = val, v
                        b_[i] = best
                        if best != old:
                            beta += (best - old) * Xa[i]
                            change = max(change, abs(best - old))
                    if change < 1e-6 * C:
                        break
            self.beta, self.bias = beta[:p], beta[p]
            return self
        if self.learner == 'svm':
            raise ValueError("a lasso penalty with the 'svm' learner is not solved here: use 'logistic' or 'leastsquares'")

        def loss_grad(z):
            b, c = z[:p], z[p]
            f = X @ b + c
            if self.regression:
                r = f - yy
                L = np.sum(w * r ** 2) / (2 * n)
                gf = w * r / n
            else:
                m = yy * f
                L = np.sum(w * np.logaddexp(0, -m)) / n
                gf = -w * yy / (1 + np.exp(m)) / n
            return L, np.concatenate([X.T @ gf, [gf.sum()]])
        if self.reg == 'ridge':
            def fun(z):
                L, g = loss_grad(z)
                g[:p] += lam * z[:p]
                return L + lam / 2 * np.sum(z[:p] ** 2), g
            r = minimize(fun, np.zeros(p + 1), jac=True, method='L-BFGS-B', options={'maxiter': self.maxit})
            self.beta, self.bias = r.x[:p], r.x[p]
        else:
            def fun(z):
                bp, bm, c = z[:p], z[p:2 * p], z[2 * p]
                L, g = loss_grad(np.concatenate([bp - bm, [c]]))
                return L + lam * np.sum(bp + bm), np.concatenate([g[:p] + lam, -g[:p] + lam, [g[p]]])
            r = minimize(fun, np.zeros(2 * p + 1), jac=True, method='L-BFGS-B', bounds=[(0, None)] * (2 * p) + [(None, None)],
                         options={'maxiter': self.maxit})
            self.beta, self.bias = r.x[:p] - r.x[p:2 * p], r.x[2 * p]
        return self

    def decision(self, X):
        return X @ self.beta + self.bias


# ---- neural networks -----------------------------------------------------------------------------------------------------------------------

_ACT = {'relu': (lambda z: np.maximum(z, 0), lambda z, a: (z > 0).astype(float)),
        'tanh': (np.tanh, lambda z, a: 1 - a ** 2),
        'sigmoid': (lambda z: 1 / (1 + np.exp(-z)), lambda z, a: a * (1 - a)),
        'none': (lambda z: z, lambda z, a: np.ones_like(z))}


class MLP:
    """Fully connected layers, an activation after each but the last; softmax and cross-entropy for classification, the
    squared error (halved) for regression; L2 penalty lambda/2 on the weights; L-BFGS."""

    def __init__(self, K, sizes=(10,), act='relu', lam=0.0, maxit=1000, standardize=False, rs=None):
        self.K, self.sizes, self.act, self.lam, self.maxit, self.standardize, self.rs = K, list(sizes), act, lam, maxit, standardize, rs

    def _unpack(self, z):
        Ws, bs, k = [], [], 0
        for a, b in zip(self.dims[:-1], self.dims[1:]):
            Ws.append(z[k:k + a * b].reshape(a, b))
            k += a * b
            bs.append(z[k:k + b])
            k += b
        return Ws, bs

    def _forward(self, Z, Ws, bs):
        f, _ = _ACT[self.act]
        acts, pre = [Z], []
        for i, (W, b) in enumerate(zip(Ws, bs)):
            zz = acts[-1] @ W + b
            pre.append(zz)
            acts.append(f(zz) if i < len(Ws) - 1 else zz)
        return acts, pre

    def fit(self, X, y, w=None):
        from scipy.optimize import minimize
        n, p = X.shape
        self.mu = X.mean(0) if self.standardize else np.zeros(p)
        sd = X.std(0, ddof=1) if self.standardize else np.ones(p)
        self.sd = np.where(sd > 0, sd, 1)
        Z = (X - self.mu) / self.sd
        out_dim = self.K if self.K else 1
        self.dims = [p] + self.sizes + [out_dim]
        parts = []
        for a, b in zip(self.dims[:-1], self.dims[1:]):
            lim = math.sqrt(6 / (a + b))
            parts.append(self.rs.uniform(-lim, lim, (a, b)).reshape(-1))
            parts.append(np.zeros(b))
        z0 = np.concatenate(parts)
        if self.K:
            Y = np.zeros((n, self.K))
            Y[np.arange(n), y] = 1
        else:
            Y = np.asarray(y, float).reshape(-1, 1)
        w = np.ones(n) if w is None else np.asarray(w, float) * n / np.sum(w)
        _, df = _ACT[self.act]

        def fun(z):
            Ws, bs = self._unpack(z)
            acts, pre = self._forward(Z, Ws, bs)
            o = acts[-1]
            if self.K:
                o = o - o.max(1, keepdims=True)
                P = np.exp(o)
                P /= P.sum(1, keepdims=True)
                L = -np.sum(w * np.log(np.maximum(np.sum(P * Y, 1), 1e-300))) / n
                delta = (P - Y) * w[:, None] / n
            else:
                r = o - Y
                L = np.sum(w[:, None] * r ** 2) / (2 * n)
                delta = r * w[:, None] / n
            L += self.lam / 2 * sum(np.sum(W ** 2) for W in Ws)
            gW, gb = [None] * len(Ws), [None] * len(Ws)
            for i in range(len(Ws) - 1, -1, -1):
                gW[i] = acts[i].T @ delta + self.lam * Ws[i]
                gb[i] = delta.sum(0)
                if i:
                    delta = (delta @ Ws[i].T) * df(pre[i - 1], acts[i])
            return L, np.concatenate([np.concatenate([a_.reshape(-1), b_]) for a_, b_ in zip(gW, gb)])
        r = minimize(fun, z0, jac=True, method='L-BFGS-B', options={'maxiter': self.maxit, 'gtol': 1e-6})
        self.z = r.x
        self.loss = r.fun
        self.iters = r.nit
        return self

    def raw(self, X):
        Ws, bs = self._unpack(self.z)
        acts, _ = self._forward((X - self.mu) / self.sd, Ws, bs)
        return acts[-1]

    def predict(self, X):
        o = self.raw(X)
        if self.K:
            o = o - o.max(1, keepdims=True)
            P = np.exp(o)
            return P / P.sum(1, keepdims=True)
        return o.reshape(-1)


# ---- Gaussian processes ---------------------------------------------------------------------------------------------------------------------

def gp_kernel(A, B, kind, theta, grad=False):
    """theta: log length scale(s) then log signal sd (and log alpha for 'rationalquadratic'). With grad, also the
    derivatives of K by each theta."""
    if kind == 'ardsquaredexponential':
        ell = np.exp(theta[:-1])
        sf = math.exp(theta[-1])
        As, Bs = A / ell, B / ell
        r2 = np.maximum(np.sum(As ** 2, 1)[:, None] + np.sum(Bs ** 2, 1)[None, :] - 2 * As @ Bs.T, 0)
        K = sf ** 2 * np.exp(-r2 / 2)
        if not grad:
            return K
        dK = [K * (As[:, d, None] - Bs[None, :, d]) ** 2 for d in range(A.shape[1])] + [2 * K]
        return K, dK
    ell, sf = math.exp(theta[0]), math.exp(theta[1])
    r2 = np.maximum(np.sum(A ** 2, 1)[:, None] + np.sum(B ** 2, 1)[None, :] - 2 * A @ B.T, 0) / ell ** 2
    r = np.sqrt(r2)
    s2 = sf ** 2
    if kind == 'squaredexponential':
        K = s2 * np.exp(-r2 / 2)
        dl = K * r2
    elif kind == 'exponential':
        K = s2 * np.exp(-r)
        dl = K * r
    elif kind == 'matern32':
        e = np.exp(-math.sqrt(3) * r)
        K = s2 * (1 + math.sqrt(3) * r) * e
        dl = s2 * 3 * r2 * e
    elif kind == 'matern52':
        e = np.exp(-math.sqrt(5) * r)
        K = s2 * (1 + math.sqrt(5) * r + 5 * r2 / 3) * e
        dl = s2 * (5 / 3) * r2 * (1 + math.sqrt(5) * r) * e
    elif kind == 'rationalquadratic':
        al = math.exp(theta[2])
        base = 1 + r2 / (2 * al)
        K = s2 * base ** (-al)
        dl = s2 * r2 * base ** (-al - 1)
        da = K * (-al * np.log(base) + r2 / (2 * base))
        if grad:
            return K, [dl, 2 * K, da]
        return K
    else:
        raise ValueError(kind)
    if grad:
        return K, [dl, 2 * K]
    return K


class GP:
    """Regression by a Gaussian process with a constant (or none, or linear) basis: the kernel's parameters and the noise
    found by maximizing the marginal likelihood (L-BFGS on their logarithms), the basis coefficients by generalized least
    squares."""

    def __init__(self, kind='squaredexponential', basis='constant', sigma0=None, theta0=None, optimize=True, standardize=False):
        self.kind, self.basis, self.sigma0, self.theta0, self.optimize, self.standardize = kind, basis, sigma0, theta0, optimize, standardize

    def H(self, X):
        n = X.shape[0]
        if self.basis == 'none':
            return np.zeros((n, 0))
        if self.basis == 'linear':
            return np.column_stack([np.ones(n), X])
        return np.ones((n, 1))

    def _nll(self, params, X, y, H, grad=False):
        """The negative log marginal likelihood (the basis coefficients by generalized least squares), and its gradient
        by the log parameters: -1/2 tr((a a' - K^-1) dK)."""
        theta, ls = params[:-1], params[-1]
        n = X.shape[0]
        Kf, dK = gp_kernel(X, X, self.kind, theta, grad=True)
        noise = math.exp(2 * ls)
        K = Kf + (noise + 1e-10 * max(1.0, float(np.mean(np.diag(Kf))))) * np.eye(n)
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return (1e25, np.zeros(params.size)) if grad else (1e25, None)
        Ki = lambda v: np.linalg.solve(L.T, np.linalg.solve(L, v))      # noqa: E731
        if H.shape[1]:
            KiH = Ki(H)
            beta = np.linalg.solve(H.T @ KiH, KiH.T @ y)
        else:
            beta = np.zeros(0)
        r = y - H @ beta
        a = Ki(r)
        nll = 0.5 * r @ a + np.sum(np.log(np.diag(L))) + 0.5 * n * math.log(2 * math.pi)
        if grad:
            Kinv = Ki(np.eye(n))
            W = np.outer(a, a) - Kinv
            g = [-0.5 * np.sum(W * D) for D in dK] + [-0.5 * np.trace(W) * 2 * noise]
            return float(nll), np.array(g)
        return float(nll), (beta, L, a)

    def fit(self, X, y, w=None):
        from scipy.optimize import minimize
        self.mu = X.mean(0) if self.standardize else np.zeros(X.shape[1])
        sd = X.std(0, ddof=1) if self.standardize else np.ones(X.shape[1])
        self.sd = np.where(sd > 0, sd, 1)
        Z = (X - self.mu) / self.sd
        H = self.H(Z)
        ysd = float(np.std(y, ddof=1)) if y.size > 1 else 1.0
        ysd = ysd if ysd > 0 else 1.0
        if self.theta0 is not None:
            th = np.log(np.asarray(self.theta0, float))
        else:
            ell = float(np.mean(np.std(Z, axis=0, ddof=1))) if Z.shape[0] > 1 else 1.0
            ell = ell if ell > 0 else 1.0
            if self.kind == 'ardsquaredexponential':
                ls_ = np.std(Z, axis=0, ddof=1)
                th = np.concatenate([np.log(np.where(ls_ > 0, ls_, 1)), [math.log(ysd / math.sqrt(2))]])
            elif self.kind == 'rationalquadratic':
                th = np.array([math.log(ell), math.log(ysd / math.sqrt(2)), 0.0])
            else:
                th = np.array([math.log(ell), math.log(ysd / math.sqrt(2))])
        s0 = math.log(self.sigma0 if self.sigma0 is not None else ysd / math.sqrt(2))
        p0 = np.concatenate([th, [s0]])
        if self.optimize:
            # length scales within 1e-3 to 1e3 times the inputs' spread, the signal sd within 1e-3 to 1e3 times y's, the noise
            # from 1e-4 times y's sd; from the noise given (or y's sd over sqrt 2), and also from a tenth and a hundredth of
            # that, the best likelihood kept
            spread = float(np.max(np.ptp(Z, axis=0))) if Z.shape[0] > 1 else 1.0
            spread = spread if spread > 0 else 1.0
            bounds = []
            for i in range(th.size):
                if self.kind == 'ardsquaredexponential':
                    bounds.append((math.log(1e-3 * spread), math.log(1e3 * spread)) if i < th.size - 1 else (math.log(1e-3 * ysd), math.log(1e3 * ysd)))
                elif i == 0:
                    bounds.append((math.log(1e-3 * spread), math.log(1e3 * spread)))
                elif i == 1:
                    bounds.append((math.log(1e-3 * ysd), math.log(1e3 * ysd)))
                else:
                    bounds.append((-10, 10))
            bounds.append((math.log(1e-4 * ysd), math.log(1e2 * ysd)))
            best = None
            for shift in ((0.0, math.log(10.0), math.log(100.0)) if self.sigma0 is None else (0.0,)):
                start = p0.copy()
                start[-1] = s0 - shift
                start = np.clip(start, [b[0] for b in bounds], [b[1] for b in bounds])
                r = minimize(lambda q: self._nll(q, Z, y, H, grad=True), start, jac=True, method='L-BFGS-B', bounds=bounds)
                if best is None or r.fun < best.fun:
                    best = r
            p0 = best.x
        self.params = p0
        self.nll, (self.beta, self.L, self.a) = self._nll(p0, Z, y, H)
        self.Z = Z
        self.sigma = math.exp(p0[-1])
        return self

    def predict(self, X, var=False):
        Zs = (X - self.mu) / self.sd
        Ks = gp_kernel(Zs, self.Z, self.kind, self.params[:-1])
        m = self.H(Zs) @ self.beta + Ks @ self.a
        if not var:
            return m
        v = np.linalg.solve(self.L, Ks.T)
        kss = np.diag(gp_kernel(Zs, Zs, self.kind, self.params[:-1]))
        return m, np.maximum(kss - np.sum(v ** 2, 0), 0)


# ---- random Fourier features -------------------------------------------------------------------------------------------------------------

class Features:
    """Random Fourier features of the Gaussian kernel exp(-|x - z|^2/scale^2): sqrt(2/m) cos(x W + b)."""

    def __init__(self, m, scale, rs):
        self.m, self.scale, self.rs = m, scale, rs

    def fit(self, p):
        self.W = self.rs.standard_normal((p, self.m)) * math.sqrt(2) / self.scale
        self.b = self.rs.uniform(0, 2 * math.pi, self.m)
        return self

    def __call__(self, X):
        return math.sqrt(2 / self.m) * np.cos(X @ self.W + self.b)
