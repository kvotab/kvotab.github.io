"""Two Krylov solvers SciPy does not have, written from their published
algorithms and run through the same wrapper as pcg, gmres and the rest:
symmlq (Paige and Saunders, 1975: the Lanczos process with an LQ
factorization of its tridiagonal matrix, for symmetric A, positive definite
or not) and bicgstabl (BiCGStab(l) of Sleijpen and Fokkema, 1993, with
l = 2: BiCG steps followed by a minimal-residual polynomial of degree l,
for any square A)."""
import numpy as np

from .matfun import _SOLVERS, _iterative


def _op(A):
    return (lambda x: A @ x) if not hasattr(A, 'matvec') else A.matvec


def _prec(M):
    if M is None:
        return lambda r: r
    return M.matvec if hasattr(M, 'matvec') else (lambda r: M @ r)


def symmlq(A, b, rtol=1e-6, atol=0.0, x0=None, maxiter=None, M=None, callback=None):
    """SYMMLQ: (x, info) as SciPy's solvers give them; the LQ iterate, or the CG point when that meets the tolerance first."""
    Ax, Minv = _op(A), _prec(M)
    n = b.size
    x0 = np.zeros(n) if x0 is None else np.asarray(x0, float).reshape(-1)
    maxiter = n if maxiter is None else maxiter
    nb = np.linalg.norm(b)
    r1 = b - Ax(x0)
    y = Minv(r1)
    beta1 = float(np.sqrt(max(r1 @ y, 0.0)))
    if beta1 == 0:
        return x0, 0
    # preconditioned Lanczos: r vectors and y = M\r; v = y/beta enters x
    r_old = np.zeros(n)
    beta_old = 0.0
    beta = beta1
    r = r1
    v = y / beta
    x = x0.copy()
    wbar = v.copy()
    zeta_prev2 = zeta_prev1 = 0.0
    eps_k = 0.0
    delta_bar = None
    gamma_bar = None
    k = 0
    while k < maxiter:
        k += 1
        p = Ax(v)
        alpha = float(v @ p)
        r_new = p - (alpha / beta) * r - ((beta / beta_old) * r_old if beta_old else 0.0)
        y_new = Minv(r_new)
        beta_new = float(np.sqrt(max(r_new @ y_new, 0.0)))
        if k == 1:
            gamma_bar, delta_bar = alpha, beta_new
            eps_next = 0.0
            delta_k = 0.0
        else:
            # the rotation of the step before finishes this column of L
            delta_k = c * delta_bar + s * alpha
            gamma_bar_new = s * delta_bar - c * alpha
            eps_next = s * beta_new
            delta_bar = -c * beta_new
            gamma_bar = gamma_bar_new
        gamma = float(np.hypot(gamma_bar, beta_new))
        # the CG point uses gamma_bar; the LQ iterate gamma
        zeta = -(eps_k * zeta_prev2 + delta_k * zeta_prev1) / gamma if k > 1 else beta1 / gamma
        zeta_bar = -(eps_k * zeta_prev2 + delta_k * zeta_prev1) / gamma_bar if k > 1 and gamma_bar != 0 else (beta1 / gamma_bar if gamma_bar else np.inf)
        if gamma == 0:
            break
        c, s = gamma_bar / gamma, beta_new / gamma
        v_new = y_new / beta_new if beta_new > 0 else np.zeros(n)
        w = c * wbar + s * v_new
        x_cg = x + zeta_bar * wbar if np.isfinite(zeta_bar) else None
        x = x + zeta * w
        wbar = s * wbar - c * v_new
        if callback is not None:
            callback(x)
        res = np.linalg.norm(b - Ax(x))
        if res <= rtol * nb:
            return x, 0
        if x_cg is not None and np.linalg.norm(b - Ax(x_cg)) <= rtol * nb:
            return x_cg, 0
        if beta_new == 0:
            break
        eps_k = eps_next
        zeta_prev2, zeta_prev1 = zeta_prev1, zeta
        r_old, r = r, r_new
        beta_old, beta = beta, beta_new
        v = v_new
    return x, maxiter


def bicgstabl(A, b, rtol=1e-6, atol=0.0, x0=None, maxiter=None, M=None, callback=None, ell=2):
    """BiCGStab(l), right preconditioned: (x, info) as SciPy's solvers give them."""
    Ax, Minv = _op(A), _prec(M)
    n = b.size
    x0 = np.zeros(n) if x0 is None else np.asarray(x0, float).reshape(-1)
    maxiter = n if maxiter is None else maxiter
    nb = np.linalg.norm(b)

    def B(z):
        return Ax(Minv(z))
    r = b - Ax(x0)
    rt = r.copy()
    y = np.zeros(n)
    u = np.zeros(n)
    rho0, alpha, omega = 1.0, 0.0, 1.0
    for it in range(1, maxiter + 1):
        rhat = [r] + [None] * ell
        uhat = [u] + [None] * ell
        rho0 = -omega * rho0
        for j in range(ell):
            rho1 = float(rhat[j] @ rt)
            if rho0 == 0:
                return Minv(y) + x0, -10
            beta = alpha * rho1 / rho0
            rho0 = rho1
            for i in range(j + 1):
                uhat[i] = rhat[i] - beta * uhat[i]
            uhat[j + 1] = B(uhat[j])
            gam = float(uhat[j + 1] @ rt)
            if gam == 0:
                return Minv(y) + x0, -10
            alpha = rho0 / gam
            for i in range(j + 1):
                rhat[i] = rhat[i] - alpha * uhat[i + 1]
            rhat[j + 1] = B(rhat[j])
            y = y + alpha * uhat[0]
        tau = np.zeros((ell + 1, ell + 1))
        sigma = np.zeros(ell + 1)
        gp = np.zeros(ell + 1)
        for j in range(1, ell + 1):
            for i in range(1, j):
                tau[i, j] = float(rhat[j] @ rhat[i]) / sigma[i] if sigma[i] else 0.0
                rhat[j] = rhat[j] - tau[i, j] * rhat[i]
            sigma[j] = float(rhat[j] @ rhat[j])
            gp[j] = float(rhat[0] @ rhat[j]) / sigma[j] if sigma[j] else 0.0
        g = np.zeros(ell + 1)
        g[ell] = gp[ell]
        omega = g[ell]
        for j in range(ell - 1, 0, -1):
            g[j] = gp[j] - sum(tau[j, i] * g[i] for i in range(j + 1, ell + 1))
        gpp = np.zeros(ell + 1)
        for j in range(1, ell):
            gpp[j] = g[j + 1] + sum(tau[j, i] * g[i + 1] for i in range(j + 1, ell))
        y = y + g[1] * rhat[0]
        rhat[0] = rhat[0] - gp[ell] * rhat[ell]
        uhat[0] = uhat[0] - g[ell] * uhat[ell]
        for j in range(1, ell):
            uhat[0] = uhat[0] - g[j] * uhat[j]
            y = y + gpp[j] * rhat[j]
            rhat[0] = rhat[0] - gp[j] * rhat[j]
        u, r = uhat[0], rhat[0]
        x = x0 + Minv(y)
        if callback is not None:
            callback(x)
        if np.linalg.norm(b - Ax(x)) <= rtol * nb:
            return x, 0
        if omega == 0:
            return x, -10
    return x0 + Minv(y), maxiter


_SOLVERS['symmlq'] = symmlq
_SOLVERS['bicgstabl'] = bicgstabl
_iterative('symmlq')
_iterative('bicgstabl')
