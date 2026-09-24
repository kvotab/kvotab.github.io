# What SALib makes of fixed samples and designs, for the port in
# kompartment/src/domain/salib.js to be checked against.
#
# Every case hands both sides the same numbers: the design or the sample, the
# outputs, and wherever SALib draws random numbers of its own (the bootstrap
# resamples) the draws themselves, replayed from numpy's generator in the order
# SALib makes them. The test functions are the usual made-up ones -- Ishigami,
# a linear function with interactions -- so nothing here is anybody's data.
#
#   python3 -m venv env && env/bin/pip install SALib==1.6.0
#   env/bin/python scripts/gen-salib-ref.py
#
# writes kompartment/test/fixtures/salib-reference.json. Arrays of numbers are
# stored as base64 of their little-endian bytes -- Float64 for values, Int32
# for indices -- which is exact and smaller than decimals; the test decodes
# them.

import base64
import json
import math
import os

from importlib.metadata import version

import numpy as np
from scipy.stats import ks_2samp, norm
from SALib.analyze import dgsm, discrepancy, ff, morris, pawn, radial_ee, rbd_fast, sobol, sobol_jansen
from SALib.sample import finite_diff, latin
from SALib.sample import ff as ff_sample
from SALib.sample import morris as morris_sample
from SALib.sample import sobol as sobol_sample
from SALib.sample.morris.local import LocalOptimisation
from SALib.sample.radial import radial_mc

OUT = os.path.join(os.path.dirname(__file__), "..", "kompartment", "test", "fixtures", "salib-reference.json")


def f64(v):
    return base64.b64encode(np.ascontiguousarray(v, dtype="<f8").tobytes()).decode()


def i32(v):
    return base64.b64encode(np.ascontiguousarray(v, dtype="<i4").tobytes()).decode()


def cols(X):
    return [f64(X[:, k]) for k in range(X.shape[1])]


def ishigami(u):
    """On probabilities: each input mapped onto [-pi, pi] first."""
    x = -math.pi + 2 * math.pi * np.asarray(u)
    return np.sin(x[:, 0]) + 7 * np.sin(x[:, 1]) ** 2 + 0.1 * x[:, 2] ** 4 * np.sin(x[:, 0])


def problem(K):
    return {"num_vars": K, "names": [f"x{k + 1}" for k in range(K)], "bounds": [[0.0, 1.0]] * K}


ref = {"version": version("SALib")}

# --- the Kolmogorov-Smirnov statistic, ties and all.
rng = np.random.default_rng(1)
ks = []
for n1, n2, tied in [(40, 400, False), (37, 250, True), (5, 9, True)]:
    a = rng.normal(size=n1)
    b = rng.normal(size=n2) * 1.3 + 0.2
    if tied:
        a = np.round(a, 1)
        b = np.round(b, 1)
    ks.append({"a": f64(a), "b": f64(b), "statistic": float(ks_2samp(a, b).statistic)})
ref["ks"] = ks

# --- PAWN and discrepancy, on one Latin hypercube sample of Ishigami.
P3 = problem(3)
X = latin.sample(P3, 500, seed=3)
Y = ishigami(X)
ref["sample"] = {"X": cols(X), "Y": f64(Y)}
ref["pawn"] = []
for S in (10, 8, 5):
    si = pawn.analyze(P3, X, Y, S=S, seed=None)
    ref["pawn"].append({"S": S, **{k: f64(si[k]) for k in ("minimum", "mean", "median", "maximum", "CV", "stdev")}})
ref["discrepancy"] = {m: f64(discrepancy.analyze(P3, X, Y, method=m)["s_discrepancy"]) for m in ("WD", "CD", "MD", "L2-star")}

# --- the radial design: elementary effects and Jansen's total index.
N = 60
Xr = radial_mc.sample(P3, N, seed=5)
Yr = ishigami(Xr)
per = 3 + 1
base = Xr[0::per]
step = np.stack([Xr[j * per + 1 + k, k] for j in range(N) for k in range(3)]).reshape(N, 3)
R = 100
seed = 7
ee = radial_ee.analyze(P3, Xr, Yr, sample_sets=N, num_resamples=R, seed=seed)
np.random.seed(seed)
idx = np.random.randint(N, size=(R, N))
jan = sobol_jansen.analyze(P3, Yr, N, num_resamples=R, seed=seed)
# The interval on Sₜ as the port takes it -- the base points resampled, and the
# variance with them -- worked out here on the same resamples, since SALib's
# own is not a bootstrap (see ../kompartment/src/domain/salib.js).
Yb = Yr[0::per]
st = np.stack([Yb - Yr[k + 1::per] for k in range(3)], axis=1)
res = np.array([[np.sum(st[idx[r], k] ** 2) / (2 * N) / np.var(Yb[idx[r]]) for k in range(3)] for r in range(R)])
ref["radial"] = {
    "N": N, "base": cols(base), "step": cols(step), "y": f64(Yr), "indices": i32(idx),
    "mu": f64(ee["mu"]), "mu_star": f64(ee["mu_star"]), "sigma": f64(ee["sigma"]),
    "mu_star_conf": f64(ee["mu_star_conf"]), "ST": f64(jan["ST"]),
    "ST_conf_resampled": f64(norm.ppf(0.975) * res.std(ddof=1, axis=0)),
}

# --- Morris: candidate trajectories, the optimal ones among them, and the
# analysis of those with its bootstrap.
K = 4
P4 = problem(K)
candidates = morris_sample.sample(P4, 24, num_levels=4, optimal_trajectories=None, seed=11)
chosen = LocalOptimisation().find_local_maximum(candidates, 24, K, 6, None)
Xm = morris_sample.sample(P4, 24, num_levels=4, optimal_trajectories=6, local_optimization=True, seed=11)
assert np.array_equal(Xm, np.concatenate([candidates[c * (K + 1):(c + 1) * (K + 1)] for c in chosen]))


def lin4(u):
    u = np.asarray(u)
    return 3 * u[:, 0] + 2 * u[:, 1] ** 2 + u[:, 2] * u[:, 3] + np.sin(4 * u[:, 3])


Ym = lin4(Xm)
mo = morris.analyze(P4, Xm, Ym, num_resamples=R, conf_level=0.95, num_levels=4, seed=13)
g = np.random.default_rng(13)
morris_idx = [g.integers(6, size=(R, 6)) for _ in range(K)]
ref["morris"] = {
    "K": K, "candidates": f64(candidates.ravel()), "chosen": list(map(int, chosen)),
    "X": cols(Xm), "y": f64(Ym), "indices": [i32(v) for v in morris_idx],
    "mu": f64(mo["mu"]), "mu_star": f64(mo["mu_star"]), "sigma": f64(mo["sigma"]),
    "mu_star_conf": f64(mo["mu_star_conf"]),
}
# More candidate sets, for the selection alone.
ref["optimal"] = []
for seed_c, n_c, k_c in [(21, 20, 4), (22, 30, 8), (23, 12, 5)]:
    c = morris_sample.sample(problem(5), n_c, num_levels=6, optimal_trajectories=None, seed=seed_c)
    ref["optimal"].append({
        "K": 5, "candidates": f64(c.ravel()), "N": n_c, "k": k_c,
        "chosen": list(map(int, LocalOptimisation().find_local_maximum(c, n_c, 5, k_c, None))),
    })

# --- Sobol: the bootstrap interval, with pairs.
n = 64
Xs = sobol_sample.sample(P3, n, calc_second_order=True, seed=17)
Ys = ishigami(Xs)
so = sobol.analyze(P3, Ys, calc_second_order=True, num_resamples=50, conf_level=0.95, seed=19)
r = np.random.default_rng(19).integers(n, size=(n, 50))
D = 3
stp = 2 * D + 2
A = Ys[0::stp]
B = Ys[stp - 1::stp]
AB = [Ys[j + 1::stp] for j in range(D)]
BA = [Ys[j + 1 + D::stp] for j in range(D)]
tool = np.concatenate([A, B, *AB, *BA])
ref["sobol"] = {
    "K": D, "n": n, "y": f64(tool), "indices": i32(r.ravel()),
    "S1_conf": f64(so["S1_conf"]), "ST_conf": f64(so["ST_conf"]),
    "S2_conf": f64(np.asarray(so["S2_conf"]).ravel()),
}

# --- the fractional factorial's main and interaction effects.
P5 = problem(5)
names = list(P5["names"])  # before SALib pads the problem with dummy inputs
Xf = ff_sample.sample(P5, seed=23)


def lin5(u):
    u = np.asarray(u)
    return 2 * u[:, 0] - u[:, 1] + 0.5 * u[:, 2] + 3 * u[:, 0] * u[:, 3] - u[:, 1] * u[:, 4]


Yf = lin5(Xf)
fa = ff.analyze(P5, Xf, Yf, second_order=True)
pairs = [
    {"a": names.index(a), "b": names.index(b), "value": float(v)}
    for (a, b), v in zip(fa["interaction_names"], fa["IE"])
    if a in names and b in names
]
ref["ff"] = {"K": 5, "X": cols(Xf), "y": f64(Yf), "ME": f64(fa["ME"][:5]), "pairs": pairs}

# --- RBD-FAST's bias correction.
ref["unskew"] = [
    {"S1": s1, "M": m, "N": nn, "value": float(rbd_fast.unskew_S1(s1, m, nn))}
    for s1, m, nn in [(0.31, 10, 1000), (0.02, 6, 200), (0.9, 4, 64)]
]

# --- DGSM: ν, its spread and the interval on it.
Nd = 40
Xd = finite_diff.sample(P3, Nd, delta=0.01, seed=29)
Yd = ishigami(Xd)
dg = dgsm.analyze(P3, Xd, Yd, num_resamples=50, conf_level=0.95, seed=31)
np.random.seed(31)
dgsm_idx = [np.random.randint(Nd, size=(50, Nd)) for _ in range(3)]
bd = Xd[0::4]
Yb = Yd[0::4]
g_ = np.stack([(Yd[k + 1::4] - Yb) / (Xd[k + 1::4, k] - bd[:, k]) for k in range(3)], axis=1)
ref["dgsm"] = {
    "N": Nd, "g": f64(g_.ravel()), "indices": [i32(v) for v in dgsm_idx],
    "vi": f64(dg["vi"]), "vi_std": f64(dg["vi_std"]), "dgsm_conf": f64(dg["dgsm_conf"]),
}

with open(OUT, "w") as fh:
    json.dump(ref, fh, indent=1)
print("wrote", OUT)
