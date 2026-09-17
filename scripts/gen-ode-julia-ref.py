#!/usr/bin/env python3
"""Reference solutions for the ode_julia stiff test set, from SciPy.

The point of a reference is that it comes from somewhere else. These are
computed with scipy.integrate.solve_ivp's Radau at a tolerance three or four
orders tighter than anything the tests ask for, so the difference the tests
measure is the tested solver's error and not the reference's.

    python3 scripts/gen-ode-julia-ref.py

Writes resources/tests/ode_julia/ref/<problem>.csv, one row per output time.
"""
import csv
from pathlib import Path

import numpy as np
from scipy.integrate import solve_ivp

OUT = Path(__file__).resolve().parent.parent / 'resources/tests/ode_julia/ref'


def rober(t, y):
    return [-0.04 * y[0] + 1e4 * y[1] * y[2],
            0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] ** 2,
            3e7 * y[1] ** 2]


def hires(t, y):
    return [
        -1.71 * y[0] + 0.43 * y[1] + 8.32 * y[2] + 0.0007,
        1.71 * y[0] - 8.75 * y[1],
        -10.03 * y[2] + 0.43 * y[3] + 0.035 * y[4],
        8.32 * y[1] + 1.71 * y[2] - 1.12 * y[3],
        -1.745 * y[4] + 0.43 * y[5] + 0.43 * y[6],
        -280 * y[5] * y[7] + 0.69 * y[3] + 1.71 * y[4] - 0.43 * y[5] + 0.69 * y[6],
        280 * y[5] * y[7] - 1.81 * y[6],
        -280 * y[5] * y[7] + 1.81 * y[6],
    ]


def orego(t, y):
    s, w, q = 77.27, 0.161, 8.375e-6
    return [s * (y[1] + y[0] * (1 - q * y[0] - y[1])),
            (y[2] - (1 + y[0]) * y[1]) / s,
            w * (y[0] - y[2])]


def vanderpol(t, y):
    mu = 1e6
    return [y[1], mu * ((1 - y[0] ** 2) * y[1] - y[0])]


POLLU_K = [0.35, 0.266e2, 0.123e5, 0.86e-3, 0.82e-3, 0.15e5, 0.13e-3, 0.24e5,
           0.165e5, 0.9e4, 0.22e-1, 0.12e5, 0.188e1, 0.163e5, 0.48e7, 0.35e-3,
           0.175e-1, 0.1e9, 0.444e12, 0.124e4, 0.21e1, 0.578e1, 0.474e-1,
           0.178e4, 0.312e1]


def pollution(t, y):
    k = POLLU_K
    r = [k[0] * y[0], k[1] * y[1] * y[3], k[2] * y[4] * y[1], k[3] * y[6],
         k[4] * y[6], k[5] * y[6] * y[5], k[6] * y[8], k[7] * y[8] * y[5],
         k[8] * y[10] * y[1], k[9] * y[10] * y[0], k[10] * y[12],
         k[11] * y[9] * y[1], k[12] * y[13], k[13] * y[0] * y[5], k[14] * y[2],
         k[15] * y[3], k[16] * y[3], k[17] * y[15], k[18] * y[15],
         k[19] * y[16] * y[5], k[20] * y[18], k[21] * y[18], k[22] * y[0] * y[3],
         k[23] * y[18] * y[0], k[24] * y[19]]
    return [
        -r[0] - r[9] - r[13] - r[22] - r[23] + r[1] + r[2] + r[8] + r[10] + r[11] + r[21] + r[24],
        -r[1] - r[2] - r[8] - r[11] + r[0] + r[20],
        -r[14] + r[0] + r[16] + r[18] + r[21],
        -r[1] - r[15] - r[16] - r[22] + r[14],
        -r[2] + 2 * r[3] + r[5] + r[6] + r[12] + r[19],
        -r[5] - r[7] - r[13] - r[19] + r[2] + 2 * r[17],
        -r[3] - r[4] - r[5] + r[12],
        r[3] + r[4] + r[5] + r[6],
        -r[6] - r[7],
        -r[11] + r[6] + r[8],
        -r[8] - r[9] + r[7] + r[10],
        r[8],
        -r[10] + r[9],
        -r[12] + r[11],
        r[13],
        -r[17] - r[18] + r[15],
        -r[19],
        r[19],
        -r[20] - r[21] - r[23] + r[16] + r[24],
        -r[24] + r[23],
    ]


POLLU_U0 = [0.0] * 20
for i, v in ((1, 0.2), (3, 0.04), (6, 0.1), (7, 0.3), (8, 0.01), (16, 0.007)):
    POLLU_U0[i] = v

PROBLEMS = {
    'rober': (rober, [1, 0, 0], (0, 1e5), np.logspace(-5, 5, 41), 1e-12, 1e-24),
    'hires': (hires, [1, 0, 0, 0, 0, 0, 0, 0.0057], (0, 321.8122),
              np.linspace(0, 321.8122, 41)[1:], 1e-12, 1e-18),
    'orego': (orego, [1, 2, 3], (0, 360), np.linspace(0, 360, 41)[1:], 1e-12, 1e-18),
    'pollution': (pollution, POLLU_U0, (0, 60), np.linspace(0, 60, 41)[1:], 1e-12, 1e-18),
    'vanderpol': (vanderpol, [2, 0], (0, 2), np.linspace(0, 2, 41)[1:], 1e-11, 1e-14),
}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (f, u0, span, teval, rtol, atol) in PROBLEMS.items():
        teval = np.asarray([t for t in teval if span[0] < t <= span[1]])
        sol = solve_ivp(f, span, u0, method='Radau', t_eval=teval, rtol=rtol, atol=atol)
        if not sol.success:
            raise SystemExit(f'{name}: {sol.message}')
        path = OUT / f'{name}.csv'
        with open(path, 'w', newline='') as fh:
            w = csv.writer(fh)
            w.writerow(['t'] + [f'y{i}' for i in range(len(u0))])
            for j, t in enumerate(sol.t):
                w.writerow([repr(float(t))] + [repr(float(v)) for v in sol.y[:, j]])
        print(f'{name}: {len(sol.t)} rows, {sol.nfev} f evaluations, rtol {rtol}')


if __name__ == '__main__':
    main()
