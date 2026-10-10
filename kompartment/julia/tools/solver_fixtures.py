"""Reference runs of the Python engine's solvers, for the Julia port's tests.

Runs the NDF (``ndf`` and ``solverset.variable_order``), the Rosenbrock 2-3
and the Dormand-Prince 4-5 of ``kompartment.engine`` on small problems
written in plain numpy, and writes what they produced -- every output row,
every accepted step's time, the counts, the failures' messages -- as JSON,
with every float as ``float.hex`` so that the Julia side compares bits.
The problems' parameters travel in the file too, so the two sides integrate
the same numbers.

    PYTHONPATH=kompartment/python python3 kompartment/julia/tools/solver_fixtures.py
        [--out kompartment/julia/test/solvers/fixtures.json]
    PYTHONPATH=kompartment/python python3 kompartment/julia/tools/solver_fixtures.py --bench

``--bench`` times the Python NDF instead (warm, best of several): Robertson,
and the landscape-like linear system of 2,000 and 20,000 states.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np
import scipy.sparse as sp

from kompartment.engine import solverset
from kompartment.engine.jacobian import Pattern, colour_columns
from kompartment.engine.solvers import SolverError, kernels
from kompartment.engine.solvers.dormand_prince import dormand_prince
from kompartment.engine.solvers.ndf import ndf
from kompartment.engine.solvers.rosenbrock23 import rosenbrock23

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.normpath(os.path.join(HERE, '..', 'test', 'solvers', 'fixtures.json'))


# --- encoding ------------------------------------------------------------------------

def enc(x: Any) -> Any:
    """JSON with every float as its hex string."""
    if x is None or isinstance(x, (bool, np.bool_)):
        return None if x is None else bool(x)
    if isinstance(x, (int, np.integer)):
        return int(x)
    if isinstance(x, (float, np.floating)):
        return float(x).hex()
    if isinstance(x, str):
        return x
    if isinstance(x, dict):
        return {str(k): enc(v) for k, v in x.items()}
    if isinstance(x, (list, tuple, np.ndarray)):
        return [enc(v) for v in x]
    raise TypeError(f'cannot encode {type(x)}')


# --- the problems ----------------------------------------------------------------------
# Each returns (f, jacobian parts, events): the jacobian parts are
# (n, rows, cols, values(t, y) or None, constant) with 0-based rows and cols.

def robertson(p: Dict[str, Any]):
    def f(t, y):
        return np.array([
            -0.04 * y[0] + 1e4 * y[1] * y[2],
            0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] * y[1],
            3e7 * y[1] * y[1],
        ])

    def values(t, y):
        return np.array([-0.04, 0.04, 1e4 * y[2], -1e4 * y[2] - 6e7 * y[1], 6e7 * y[1], 1e4 * y[1], -1e4 * y[1]])

    return f, (3, [0, 1, 0, 1, 2, 0, 1], [0, 0, 1, 1, 1, 2, 2], values, False), None


def vdp(p: Dict[str, Any]):
    mu = p['mu']

    def f(t, y):
        return np.array([y[1], mu * ((1.0 - y[0] * y[0]) * y[1]) - y[0]])

    def values(t, y):
        return np.array([-2.0 * mu * y[0] * y[1] - 1.0, 1.0, mu * (1.0 - y[0] * y[0])])

    return f, (2, [1, 0, 1], [0, 1, 1], values, False), None


def decay3(p: Dict[str, Any]):
    l1, l2, l3 = p['l']

    def f(t, y):
        return np.array([-l1 * y[0], l1 * y[0] - l2 * y[1], l2 * y[1] - l3 * y[2]])

    vals = np.array([-l1, l1, -l2, l2, -l3])
    return f, (3, [0, 1, 1, 2, 2], [0, 0, 1, 1, 2], lambda t, y: vals.copy(), True), None


def orego(p: Dict[str, Any]):
    s, q, w = 77.27, 8.375e-6, 0.161

    def f(t, y):
        return np.array([
            s * (y[1] - y[0] * y[1] + y[0] - q * y[0] * y[0]),
            (-y[1] - y[0] * y[1] + y[2]) / s,
            w * (y[0] - y[2]),
        ])

    return f, None, None


def hires(p: Dict[str, Any]):
    def f(t, y):
        f7 = 280.0 * y[5] * y[7] - 1.81 * y[6]
        return np.array([
            -1.71 * y[0] + 0.43 * y[1] + 8.32 * y[2] + 0.0007,
            1.71 * y[0] - 8.75 * y[1],
            -10.03 * y[2] + 0.43 * y[3] + 0.035 * y[4],
            8.32 * y[1] + 1.71 * y[2] - 1.12 * y[3],
            -1.745 * y[4] + 0.43 * y[5] + 0.43 * y[6],
            -280.0 * y[5] * y[7] + 0.69 * y[3] + 1.71 * y[4] - 0.43 * y[5] + 0.69 * y[6],
            f7,
            -f7,
        ])

    return f, None, None


class BallEvents:
    """The ball reaching the floor: h falling through zero."""
    n = 1
    direction = np.array([-1], dtype=np.int8)

    def fun(self, t, y):
        return np.array([y[0]])


def ball(p: Dict[str, Any]):
    g = 9.81

    def f(t, y):
        return np.array([y[1], -g])

    return f, None, BallEvents()


def nonneg(p: Dict[str, Any]):
    def f(t, y):
        return np.array([-0.5 - 0.1 * y[0] + 0.05 * y[1], 0.1 * y[0] - 0.05 * y[1]])

    return f, (2, [0, 1, 0, 1], [0, 0, 1, 1], None, False), None


def chain(p: Dict[str, Any]):
    k = np.array(p['k'], dtype=float)
    n = k.size

    def f(t, y):
        dy = -k * y
        dy[1:] += k[:-1] * y[:-1]
        return dy

    rows, cols, vals = [], [], []
    for i in range(n):
        rows.append(i)
        cols.append(i)
        vals.append(-k[i])
        if i + 1 < n:
            rows.append(i + 1)
            cols.append(i)
            vals.append(k[i])
    v = np.array(vals)
    return f, (n, rows, cols, lambda t, y: v.copy(), True), None


def landscape_matrix(nb: int, B: int = 10) -> Tuple[int, List[int], List[int], List[float], np.ndarray]:
    """A landscape-like linear system: blocks of B compartments with transfers
    to their neighbours and across, a loss from each, and a drain from each
    block's last compartment to the next block and to the fifth next. Every
    rate is a small integer times a power of two, so that any language makes
    the same numbers."""
    n = nb * B
    rows: List[int] = []
    cols: List[int] = []
    vals: List[float] = []
    out = [0.0] * n

    def rate(i: int, a: int) -> float:
        return math.ldexp(1 + (i * a) % 97, -((i * a) % 13))

    def flow(src: int, dst: int, r: float) -> None:
        rows.append(dst)
        cols.append(src)
        vals.append(r)
        out[src] += r

    for b in range(nb):
        base = b * B
        for j in range(B):
            i = base + j
            if j + 1 < B:
                flow(i, i + 1, rate(i, 7919))
                flow(i + 1, i, rate(i, 104729) * 0.25)
            flow(i, base + (j + 4) % B, rate(i, 1299709) * 0.125)
        last = base + B - 1
        if b + 1 < nb:
            flow(last, base + B, rate(b, 15485863))
        if b + 5 < nb:
            flow(last, base + 5 * B + 1, rate(b, 32452843) * 0.5)
    for i in range(n):
        rows.append(i)
        cols.append(i)
        vals.append(-(out[i] + 1e-3 * (1 + i % 5)))
    src = np.zeros(n)
    src[::B] = 1.0
    return n, rows, cols, vals, src


def landscape(p: Dict[str, Any]):
    n, rows, cols, vals, src = landscape_matrix(int(p['nb']))
    A = sp.csr_matrix((np.array(vals), (np.array(rows), np.array(cols))), shape=(n, n))
    A.sum_duplicates()
    A.sort_indices()

    def f(t, y):
        return A @ y + src

    C = A.tocsc()
    C.sort_indices()
    cr = C.tocoo()
    data = C.data.copy()
    return f, (n, list(cr.row), list(cr.col), lambda t, y: data.copy(), True), None


def robertson_dae(p: Dict[str, Any]):
    """Robertson with its third state algebraic: y1 + y2 + y3 = 1."""
    def f(t, y):
        return np.array([
            -0.04 * y[0] + 1e4 * y[1] * y[2],
            0.04 * y[0] - 1e4 * y[1] * y[2] - 3e7 * y[1] * y[1],
            y[0] + y[1] + y[2] - 1.0,
        ])

    def values(t, y):
        return np.array([-0.04, 0.04, 1.0, 1e4 * y[2], -1e4 * y[2] - 6e7 * y[1], 1.0, 1e4 * y[1], -1e4 * y[1], 1.0])

    return f, (3, [0, 1, 2, 0, 1, 2, 0, 1, 2], [0, 0, 0, 1, 1, 1, 2, 2, 2], values, False), None


def decay3_nan(p: Dict[str, Any]):
    """decay3 whose derivative stops being a number after t = 5."""
    f0, parts, ev = decay3(p)

    def f(t, y):
        dy = f0(t, y)
        if t > 5.0:
            dy[1] = math.nan
        return dy

    return f, parts, ev


def blowup(p: Dict[str, Any]):
    """y' = 1 / (1 - t)^2: no step size will carry it past t = 1."""
    def f(t, y):
        return np.array([1.0]) / ((1.0 - t) * (1.0 - t))

    return f, None, None


PROBLEMS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    'robertson': robertson, 'vdp': vdp, 'decay3': decay3, 'orego': orego, 'hires': hires, 'ball': ball,
    'nonneg': nonneg, 'chain': chain, 'landscape': landscape, 'robertson_dae': robertson_dae,
    'decay3_nan': decay3_nan, 'blowup': blowup,
}


def chain_rates(n: int) -> List[float]:
    return [10.0 ** (-3 + 6 * ((i * 37) % n) / n) for i in range(n)]


# --- the cases -----------------------------------------------------------------------

ROB_T = [0.0, 0.4, 4.0, 40.0, 400.0, 4e3, 4e4, 4e5, 4e6]
CHAIN_T = [0.0, 1e-2, 1e-1, 1.0, 10.0, 100.0, 1000.0]


def case(name: str, problem: str, solver: str, tspan: List[float], y0: List[float], jac: str = 'none',
         params: Optional[Dict[str, Any]] = None, opts: Optional[Dict[str, Any]] = None, restart: Any = False,
         exact: bool = True) -> Dict[str, Any]:
    # A tolerance-only case of many states keeps every tenth state of its outputs.
    stride = 1 if exact or len(y0) < 1000 else 10
    return {'name': name, 'problem': problem, 'solver': solver, 'tspan': tspan, 'y0': y0, 'jac': jac,
            'params': params or {}, 'opts': opts or {}, 'restart': restart, 'exact': exact, 'stride': stride}


def cases() -> List[Dict[str, Any]]:
    rob = dict(problem='robertson', tspan=ROB_T, y0=[1.0, 0.0, 0.0])
    tol6 = {'rtol': 1e-6, 'abstol': 1e-10}
    c80 = {'k': chain_rates(80)}
    c150 = {'k': chain_rates(150)}
    y80 = [1.0] + [0.0] * 79
    y150 = [1.0] + [0.0] * 149
    ball_t = [0.5 * i for i in range(21)]
    nn_t = [float(i) for i in range(21)]
    out = [
        case('rob_exact', solver='ndf', jac='exact', opts=dict(tol6), **rob),
        case('rob_diff', solver='ndf', jac='pattern', opts=dict(tol6), **rob),
        case('rob_nojac', solver='ndf', jac='none', opts=dict(tol6), **rob),
        case('rob_bdf', solver='ndf', jac='exact', opts=dict(tol6, bdf=True), **rob),
        case('rob_order2', solver='ndf', jac='exact', opts=dict(tol6, max_order=2), **rob),
        case('rob_rms', solver='ndf', jac='exact', opts=dict(tol6, error_norm='rms'), **rob),
        case('rob_normctl', solver='ndf', jac='exact', opts=dict(tol6, norm_control=True), **rob),
        case('rob_autoabstol', solver='ndf', jac='exact', opts=dict(rtol=1e-6, abstol=[1e-10, 1e-10, 1e-10],
                                                                     auto_abstol=True), **rob),
        case('rob_h0_hmax', solver='ndf', jac='exact', opts=dict(tol6, h0=1e-8, hmax=1e5), **rob),
        case('rob_steps', solver='ndf', jac='exact', opts=dict(tol6, max_steps=50), **rob),
        case('vdp1000', problem='vdp', solver='ndf', params={'mu': 1000.0}, tspan=[0.0, 500.0, 1000.0, 1500.0,
                                                                                    2000.0, 2500.0, 3000.0],
             y0=[2.0, 0.0], opts={'rtol': 1e-6, 'abstol': 1e-8}),
        case('vdp1000_exact', problem='vdp', solver='ndf', jac='exact', params={'mu': 1000.0},
             tspan=[0.0, 1000.0, 3000.0], y0=[2.0, 0.0], opts={'rtol': 1e-5, 'abstol': 1e-8}),
        case('decay3', problem='decay3', solver='ndf', jac='exact', params={'l': [0.5, 2e-3, 30.0]},
             tspan=[0.0, 1.0, 10.0, 100.0, 1000.0, 1e4], y0=[1.0, 0.0, 0.0], opts={'rtol': 1e-6, 'abstol': 1e-12}),
        case('orego', problem='orego', solver='ndf', tspan=[0.0, 30.0, 60.0, 120.0, 240.0, 360.0],
             y0=[1.0, 2.0, 3.0], opts={'rtol': 1e-6, 'abstol': 1e-8}),
        case('hires', problem='hires', solver='ndf', tspan=[0.0, 5.0, 50.0, 321.8122],
             y0=[1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0057], opts={'rtol': 1e-7, 'abstol': 1e-9}),
        case('ball_stop', problem='ball', solver='ndf', tspan=ball_t, y0=[10.0, 0.0],
             opts={'rtol': 1e-8, 'abstol': 1e-10}),
        case('ball_restart', problem='ball', solver='ndf', tspan=ball_t, y0=[10.0, 0.0],
             opts={'rtol': 1e-8, 'abstol': 1e-10}, restart=True),
        case('nonneg', problem='nonneg', solver='ndf', tspan=nn_t, y0=[1.0, 0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9, 'non_negative': [0]}),
        case('nonneg_exactjac', problem='nonneg', solver='ndf', jac='pattern', tspan=nn_t, y0=[1.0, 0.0],
             opts={'rtol': 1e-5, 'abstol': 1e-8, 'non_negative': [0, 1]}),
        case('chain80_nojac', problem='chain', solver='ndf', params=c80, tspan=CHAIN_T, y0=y80,
             opts={'rtol': 1e-6, 'abstol': 1e-12}),
        case('chain150_dense', problem='chain', solver='ndf', jac='exact', params=c150, tspan=CHAIN_T, y0=y150,
             opts={'rtol': 1e-6, 'abstol': 1e-12, 'matrix': 'dense'}),
        case('chain150_nojac', problem='chain', solver='ndf', params=c150, tspan=CHAIN_T, y0=y150,
             opts={'rtol': 1e-5, 'abstol': 1e-12}),
        case('chain150_diff_dense', problem='chain', solver='ndf', jac='pattern', params=c150, tspan=CHAIN_T,
             y0=y150, opts={'rtol': 1e-6, 'abstol': 1e-12, 'matrix': 'dense'}),
        # through variable_order, the runner's way in
        case('vo_rob', solver='variable_order', jac='exact', opts=dict(tol6, on_step=True), **rob),
        case('vo_rob_steps', solver='variable_order', jac='exact', opts=dict(tol6, max_steps=40), **rob),
        case('vo_chain80_nn', problem='chain', solver='variable_order', jac='exact', params=c80, tspan=CHAIN_T,
             y0=y80, opts={'rtol': 1e-6, 'abstol': 1e-12, 'matrix': 'dense', 'non_negative': [True] * 80,
                           'ends_only': True}),
        case('vo_nonneg', problem='nonneg', solver='variable_order', tspan=nn_t, y0=[1.0, 0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9, 'non_negative': [True, False], 'below_tol_run': 3,
                   'stagnation_tol': 0.5}),
        case('vo_ball', problem='ball', solver='variable_order', tspan=ball_t, y0=[10.0, 0.0],
             opts={'rtol': 1e-8, 'abstol': 1e-10}, restart=True),
        # the Rosenbrock 2-3
        case('ros_rob_exact', solver='ros23', jac='exact', opts={'rtol': 1e-4, 'abstol': 1e-8}, **rob),
        case('ros_rob_diff', solver='ros23', jac='pattern', opts={'rtol': 1e-4, 'abstol': 1e-8}, **rob),
        case('ros_rob_nojac', solver='ros23', opts={'rtol': 1e-4, 'abstol': 1e-8}, **rob),
        case('ros_chain80', problem='chain', solver='ros23', params=c80, tspan=CHAIN_T, y0=y80,
             opts={'rtol': 1e-4, 'abstol': 1e-12}),
        case('ros_decay3_const', problem='decay3', solver='ros23', jac='exact', params={'l': [0.5, 2e-3, 30.0]},
             tspan=[0.0, 1.0, 10.0, 100.0, 1000.0], y0=[1.0, 0.0, 0.0], opts={'rtol': 1e-5, 'abstol': 1e-12}),
        case('ros_ball', problem='ball', solver='ros23', tspan=ball_t, y0=[10.0, 0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9}, restart=True),
        # a constraint that binds: more than a one-step method can carry
        case('ros_nonneg', problem='nonneg', solver='ros23', tspan=nn_t, y0=[1.0, 0.0],
             opts={'rtol': 1e-5, 'abstol': 1e-9, 'non_negative': [True, False], 'max_steps': 3000}),
        case('ros_chain80_nn', problem='chain', solver='ros23', params=c80, tspan=CHAIN_T, y0=y80,
             opts={'rtol': 1e-4, 'abstol': 1e-12, 'non_negative': [True] * 80}),
        case('ros_vdp_steps', problem='vdp', solver='ros23', params={'mu': 1000.0}, tspan=[0.0, 3000.0],
             y0=[2.0, 0.0], opts={'rtol': 1e-6, 'abstol': 1e-8, 'max_steps': 60}),
        # the Dormand-Prince 4-5
        case('dp_vdp1', problem='vdp', solver='dp45', params={'mu': 1.0}, tspan=[0.0, 1.0, 5.0, 10.0, 20.0],
             y0=[2.0, 0.0], opts={'rtol': 1e-6, 'abstol': 1e-9, 'on_step': True}),
        case('dp_decay3', problem='decay3', solver='dp45', params={'l': [0.5, 0.2, 0.1]},
             tspan=[0.0, 1.0, 10.0, 50.0], y0=[1.0, 0.0, 0.0], opts={'rtol': 1e-7, 'abstol': 1e-12}),
        case('dp_ball', problem='ball', solver='dp45', tspan=ball_t, y0=[10.0, 0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9}, restart=True),
        case('dp_nonneg', problem='nonneg', solver='dp45', tspan=nn_t, y0=[1.0, 0.0],
             opts={'rtol': 1e-5, 'abstol': 1e-9, 'non_negative': [True, False], 'hmax': 0.5, 'max_steps': 3000}),
        case('dp_decay3_nn', problem='decay3', solver='dp45', params={'l': [0.5, 0.2, 0.1]},
             tspan=[0.0, 1.0, 10.0, 50.0], y0=[1.0, 0.0, 0.0],
             opts={'rtol': 1e-7, 'abstol': 1e-12, 'non_negative': [True, True, True]}),
        case('dp_rob_steps', solver='dp45', opts={'rtol': 1e-4, 'abstol': 1e-8, 'max_steps': 200}, **rob),
        case('dp_orego_h0', problem='orego', solver='dp45', tspan=[0.0, 1.0, 2.0], y0=[1.0, 2.0, 3.0],
             opts={'rtol': 1e-5, 'abstol': 1e-8, 'h0': 1e-4, 'hmin': 1e-12}),
        # more of the NDF's paths
        case('dae_robertson', problem='robertson_dae', solver='ndf', jac='exact', tspan=ROB_T, y0=[1.0, 0.0, 0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-10, 'mass': [1.0, 1.0, 0.0]}),
        case('ball_restart_floor', problem='ball', solver='ndf', tspan=ball_t, y0=[10.0, 0.0],
             opts={'rtol': 1e-8, 'abstol': 1e-10}, restart='floor'),
        case('dp_ball_floor', problem='ball', solver='dp45', tspan=ball_t, y0=[10.0, 0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9}, restart='floor'),
        case('rob_nanjac', solver='ndf', jac='exact_nan', opts=dict(tol6), **rob),
        # dense beyond 200 states: LAPACK's LU, Accelerate's in Python here and OpenBLAS's in Julia, which
        # round differently -- agreement to the tolerance only
        case('chain240_lapack', problem='chain', solver='ndf', jac='exact', params={'k': chain_rates(240)},
             tspan=CHAIN_T, y0=[1.0] + [0.0] * 239, opts={'rtol': 1e-6, 'abstol': 1e-12, 'matrix': 'dense'},
             exact=False),
        case('chain240_lapack_nojac', problem='chain', solver='ndf', params={'k': chain_rates(240)},
             tspan=CHAIN_T, y0=[1.0] + [0.0] * 239, opts={'rtol': 1e-6, 'abstol': 1e-12}, exact=False),
        case('ros_nanjac', solver='ros23', jac='exact_nan', opts={'rtol': 1e-4, 'abstol': 1e-8}, **rob),
        case('rob_rms_auto', solver='ndf', jac='exact', opts=dict(rtol=1e-6, abstol=[1e-10, 1e-10, 1e-10],
                                                                 auto_abstol=True, error_norm='rms'), **rob),
        case('rob_normctl_auto', solver='ndf', jac='exact', opts=dict(rtol=1e-6, abstol=[1e-10, 1e-10, 1e-10],
                                                                     auto_abstol=True, norm_control=True), **rob),
        case('rob_order1', solver='ndf', jac='exact', opts=dict(rtol=1e-4, abstol=1e-8, max_order=1), **rob),
        case('vo_nan', problem='decay3_nan', solver='variable_order', jac='exact', params={'l': [0.5, 2e-3, 30.0]},
             tspan=[0.0, 1.0, 10.0], y0=[1.0, 0.0, 0.0], opts={'rtol': 1e-6, 'abstol': 1e-12}),
        case('vo_blowup', problem='blowup', solver='variable_order', tspan=[0.0, 0.5, 2.0], y0=[0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9}),
        case('ndf_blowup', problem='blowup', solver='ndf', tspan=[0.0, 0.5, 2.0], y0=[0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9}),
        case('ros_blowup', problem='blowup', solver='ros23', tspan=[0.0, 0.5, 2.0], y0=[0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9}),
        case('dp_blowup', problem='blowup', solver='dp45', tspan=[0.0, 0.5, 2.0], y0=[0.0],
             opts={'rtol': 1e-6, 'abstol': 1e-9}),
        case('ndf_span', solver='ndf', jac='exact', tspan=[1.0, 1.0], y0=[1.0, 0.0, 0.0], problem='robertson',
             opts=dict(tol6)),
        case('vo_span', solver='variable_order', jac='exact', tspan=[1.0, 1.0], y0=[1.0, 0.0, 0.0],
             problem='robertson', opts=dict(tol6)),
        case('dp_span', solver='dp45', tspan=[1.0, 1.0], y0=[1.0, 0.0, 0.0], problem='robertson', opts=dict(tol6)),
        case('ndf_initial_nan', problem='decay3', solver='ndf', jac='exact', params={'l': [0.5, 2e-3, 30.0]},
             tspan=[0.0, 1.0], y0=[1.0, math.nan, 0.0], opts={'rtol': 1e-6, 'abstol': 1e-12}),
        case('vo_initial_nan', problem='decay3', solver='variable_order', jac='exact', params={'l': [0.5, 2e-3, 30.0]},
             tspan=[0.0, 1.0], y0=[1.0, math.nan, 0.0], opts={'rtol': 1e-6, 'abstol': 1e-12}),
        # the sparse path: agreement to the tolerance only (KLU against SuperLU)
        case('rob_sparse', solver='ndf', jac='exact', opts=dict(tol6, matrix='sparse'), exact=False, **rob),
        case('sparse2000_nanjac0', problem='landscape', solver='ndf', jac='exact_nan0', params={'nb': 200},
             tspan=[0.0, 1.0, 10.0], y0=[0.0] * 2000, opts={'rtol': 1e-6, 'abstol': 1e-12}, exact=False),
        case('ros_sparse2000', problem='landscape', solver='ros23', jac='exact', params={'nb': 200},
             tspan=[0.0, 1.0, 10.0, 100.0], y0=[0.0] * 2000, opts={'rtol': 1e-3, 'abstol': 1e-10}, exact=False),
        case('sparse2000', problem='landscape', solver='ndf', jac='exact', params={'nb': 200},
             tspan=[0.0, 1.0, 10.0, 100.0, 1000.0, 1e4, 1e5], y0=[0.0] * 2000,
             opts={'rtol': 1e-6, 'abstol': 1e-12}, exact=False),
        case('sparse2000_diff', problem='landscape', solver='ndf', jac='pattern', params={'nb': 200},
             tspan=[0.0, 1.0, 10.0, 100.0, 1000.0, 1e4, 1e5], y0=[0.0] * 2000,
             opts={'rtol': 1e-6, 'abstol': 1e-12}, exact=False),
    ]
    return out


# --- running a case --------------------------------------------------------------------

def jacobian_of(parts: Any, how: str) -> Optional[Dict[str, Any]]:
    if how == 'none' or parts is None:
        return None
    n, rows, cols, values, constant = parts
    pattern = Pattern(n, np.array(rows, dtype=np.int64), np.array(cols, dtype=np.int64))
    groups = colour_columns(pattern)
    if how == 'pattern':
        return {'pattern': pattern, 'groups': groups, 'constant': False, 'evaluate': None}
    if how == 'exact_nan':
        # Not a number in the third entry after t = 1 (from the start with
        # 'exact_nan0').
        def spoiled(t, y):
            v = np.array(values(t, y), dtype=float)
            if t > 1.0:
                v[2] = math.nan
            return v
        return {'pattern': pattern, 'groups': groups, 'constant': False, 'evaluate': spoiled}
    if how == 'exact_nan0':
        def spoiled0(t, y):
            v = np.array(values(t, y), dtype=float)
            v[2] = math.nan
            return v
        return {'pattern': pattern, 'groups': groups, 'constant': False, 'evaluate': spoiled0}
    return {'pattern': pattern, 'groups': groups, 'constant': constant, 'evaluate': values}


def run_case(c: Dict[str, Any]) -> Dict[str, Any]:
    f, parts, events = PROBLEMS[c['problem']](c['params'])
    jac = jacobian_of(parts, c['jac'])
    tspan = np.array(c['tspan'], dtype=float)
    y0 = np.array(c['y0'], dtype=float)
    steps: List[float] = []
    progress: List[Any] = []

    def on_accepted(t: float, y: np.ndarray) -> None:
        steps.append(float(t))

    opts = dict(c['opts'])
    solver = c['solver']
    if opts.get('on_step'):
        opts['on_step'] = lambda *a: progress.append([float(a[0]), int(a[1]), float(a[2])]) or True
    if 'abstol' in opts and isinstance(opts['abstol'], list):
        opts['abstol'] = np.array(opts['abstol'], dtype=float)
    if 'mass' in opts:
        opts['mass'] = np.array(opts['mass'], dtype=float)

    def solve(span: np.ndarray, y: np.ndarray) -> Dict[str, Any]:
        if solver == 'ndf':
            kw = dict(opts)
            return ndf(f, span, y, jacobian=jac, events=events, on_accepted=on_accepted, **kw)
        o = dict(opts, jacobian=jac, events=events, on_accepted=on_accepted)
        if solver == 'variable_order':
            return solverset.variable_order(f, span, y, o)
        if solver == 'ros23':
            return rosenbrock23(f, span, y, o)
        return dormand_prince(f, span, y, o)

    out: Dict[str, Any] = {}
    try:
        if not c['restart']:
            r = solve(tspan, y0)
            out['result'] = encode_result(r, c['stride'])
        else:
            # The runner's restart at an event (solve_with_events), the ball
            # bouncing back with 0.8 of its speed.
            segments = []
            t = float(tspan[0])
            y = y0
            nxt = 0
            for _ in range(12):
                while nxt < tspan.size and tspan[nxt] <= t:
                    nxt += 1
                if nxt >= tspan.size:
                    break
                span = np.concatenate([[t], tspan[nxt:]])
                r = solve(span, y)
                segments.append(encode_result(r, c['stride']))
                if not r['stopped']:
                    break
                t = r['stopped']['t']
                y = np.array(r['stopped']['y'], dtype=float)
                y[1] = -0.8 * y[1]
                if c['restart'] == 'floor':
                    y[0] = 0.0
            out['segments'] = segments
    except SolverError as e:
        out['error'] = {'kind': e.code, 'message': str(e), 't': e.t,
                        'last_t': e.last_t, 'stats': e.stats, 'trace': e.trace}
    out['steps'] = steps
    out['progress'] = progress
    if c['solver'] == 'ndf' and isinstance(opts.get('abstol'), np.ndarray):
        out['abstol_after'] = opts['abstol']
    return out


def encode_result(r: Dict[str, Any], stride: int = 1) -> Dict[str, Any]:
    stats = {k: v for k, v in r['stats'].items()}
    st = r.get('stopped')
    out = {'t': list(r['t']), 'y': [list(v[::stride]) for v in r['y']], 'stats': stats,
           'stopped': None if not st else {'t': st['t'], 'y': list(st['y']), 'which': list(st['which'])}}
    if 'end' in r:
        out['end'] = {'t': r['end']['t'], 'y': list(r['end']['y'][::stride])}
    return out


def units() -> Dict[str, Any]:
    """The pieces: Python's float repr (the messages' numbers), ulp (its
    log2 rounding), the colouring, and the dense-or-sparse decision."""
    from kompartment.engine.solvers.ndf import ulp
    from kompartment.engine.solvers.matrix import IterationMatrix
    rng = np.random.default_rng(20261010)
    xs: List[float] = [0.0, -0.0, 1.0, -2.5, 0.1, 1e-5, 1e-4, 9.999e-5, 1e16, 9999999999999998.0, 1e17, 123456789.0,
                       5e-324, 2.2250738585072014e-308, 1.7976931348623157e308, math.inf, -math.inf, math.nan,
                       4e6, 0.4, 3.0000000000000004, 1 / 3, 2.0 ** 60, 2.0 ** -60]
    xs += list(10.0 ** rng.uniform(-320, 308, 400))
    xs += list(rng.normal(size=100) * 10.0 ** rng.integers(-20, 20, 100))
    reprs = [[float(x), 'repr:' + repr(float(x))] for x in xs]
    us: List[float] = []
    for k in range(-1074, 1024, 7):
        p2 = 2.0 ** k
        us += [p2, np.nextafter(p2, 0.0), np.nextafter(p2, math.inf)]
    us += list(10.0 ** rng.uniform(-320, 308, 400)) + [0.0, -3.0, 5e-324, math.nan]
    ulps = [[float(x), ulp(float(x))] for x in us]
    colours = []
    for n, density in ((60, 0.08), (200, 0.03), (300, 0.01)):
        m = sp.random(n, n, density=density, random_state=int(rng.integers(1 << 30)), format='coo')
        rows = np.concatenate([m.row, np.arange(n)])
        cols = np.concatenate([m.col, np.arange(n)])
        pat = Pattern(n, rows.astype(np.int64), cols.astype(np.int64))
        colours.append({'n': n, 'rows': list(rows), 'cols': list(cols),
                        'groups': [list(g) for g in colour_columns(pat)]})
    decisions = []
    for n, density, mode in ((40, 0.5, 'auto'), (100, 0.2, 'auto'), (100, 0.02, 'auto'), (100, 0.2, 'sparse'),
                             (100, 0.02, 'dense'), (220, 0.1, 'auto'), (220, 0.005, 'auto')):
        m = sp.random(n, n, density=density, random_state=int(rng.integers(1 << 30)), format='coo')
        rows = np.concatenate([m.row, np.arange(n)])
        cols = np.concatenate([m.col, np.arange(n)])
        pat = Pattern(n, rows.astype(np.int64), cols.astype(np.int64))
        vals = rng.normal(size=pat.nnz)
        W = IterationMatrix(n, pat, vals, mode)
        decisions.append({'n': n, 'rows': list(rows), 'cols': list(cols), 'mode': mode, 'values': list(vals),
                          'sparse': bool(W.sparse)})
    return {'repr': reprs, 'ulp': ulps, 'colour': colours, 'decisions': decisions}


def main_fixtures(path: str) -> None:
    rows = []
    for c in cases():
        t0 = time.perf_counter()
        res = run_case(c)
        ms = (time.perf_counter() - t0) * 1000
        rows.append(enc({**c, **res}))
        what = res.get('error', {}).get('kind') or 'ok'
        nsteps = len(res['steps'])
        print(f"{c['name']:24s} {what:10s} {nsteps:6d} steps {ms:9.1f} ms", file=sys.stderr)
    doc = {'numba': bool(kernels.available()), 'numpy': np.__version__, 'cases': rows, 'units': enc(units())}
    with open(path, 'w') as fh:
        json.dump(doc, fh, indent=None, separators=(',', ':'))
        fh.write('\n')
    print(f'wrote {path} ({len(rows)} cases)', file=sys.stderr)


# --- the benchmark -------------------------------------------------------------------

def best_of(fn: Callable[[], Any], repeat: int) -> Tuple[float, Any]:
    best = math.inf
    out = None
    for _ in range(repeat):
        t0 = time.perf_counter()
        out = fn()
        best = min(best, time.perf_counter() - t0)
    return best, out


BENCH_DENSE = ('rob_exact', 'rob_nojac', 'vdp1000', 'orego', 'hires', 'chain80_nojac', 'chain150_dense',
               'ros_rob_exact', 'ros_chain80', 'dp_vdp1')


def main_bench() -> None:
    print(f'numba kernels active: {kernels.available()}')
    byname = {c['name']: c for c in cases()}
    for name in BENCH_DENSE:
        c = byname[name]
        f, parts, events = PROBLEMS[c['problem']](c['params'])
        jac = jacobian_of(parts, c['jac'])
        tspan = np.array(c['tspan'], dtype=float)
        y0 = np.array(c['y0'], dtype=float)
        opts = dict(c['opts'])
        if c['solver'] == 'ndf':
            def run() -> Any:
                return ndf(f, tspan, y0, jacobian=jac, **opts)
        else:
            fn = rosenbrock23 if c['solver'] == 'ros23' else dormand_prince
            o = dict(opts, jacobian=jac)
            o.pop('on_step', None)

            def run() -> Any:
                return fn(f, tspan, y0, o)
        run()
        sec, r = best_of(run, 10)
        print(f"{name:16s} {sec * 1e3:9.3f} ms per solve, {r['stats']['nsteps']} steps")
    for nb, repeat in ((200, 5), (2000, 3)):
        f, parts, _ = landscape({'nb': nb})
        jac = jacobian_of(parts, 'exact')
        n = nb * 10
        span = np.array([0.0, 1.0, 10.0, 100.0, 1000.0, 1e4, 1e5])
        y0 = np.zeros(n)
        ndf(f, span, y0, rtol=1e-6, abstol=1e-12, jacobian=jac)
        sec, r = best_of(lambda: ndf(f, span, y0, rtol=1e-6, abstol=1e-12, jacobian=jac), repeat)
        s = r['stats']
        print(f"landscape n={n}: {sec * 1e3:.1f} ms, {s['nsteps']} steps, {s['nfailed']} failed, "
              f"{s['ndecomps']} decomps, {s['nsolves']} solves, lu={s['lu']}, fill={s['fill']}")


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', default=DEFAULT_OUT)
    ap.add_argument('--bench', action='store_true')
    a = ap.parse_args()
    if a.bench:
        main_bench()
    else:
        main_fixtures(a.out)
