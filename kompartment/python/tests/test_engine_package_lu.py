"""The Julia-derived solvers' sparse LU (``engine/solvers/julia/packagelu.py``)
against the application's (``SparseLU`` in ``src/ode/julia/core/linalg.js``):
every factorisation's outcome and fill and every solve's answer, to the bit,
on matrices of every shape the solvers meet -- random patterns, chains and
blocks, in the reverse Cuthill-McKee order and in their own, with zeros,
ties, NaN and singular columns."""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

import numpy as np

from helpers import needs_app
from test_engine_lang import engine

from kompartment.engine.solvers.julia.linalg import csc_from_triplets, reverse_cuthill_mckee

try:
    from kompartment.engine.solvers.julia import packagelu
except ImportError:  # pragma: no cover - numba is optional
    packagelu = None


def hx(v: Any) -> str:
    return np.ascontiguousarray(v, dtype='<f8').tobytes().hex()


def unhx(h: str) -> np.ndarray:
    return np.frombuffer(bytes.fromhex(h), dtype='<f8').copy()


def cases(seed: int, count: int) -> List[Dict[str, Any]]:
    """Patterns of four kinds, each factorised up to four times with values
    of every scale (some zeroed, some NaN, some of a few values only, so that
    pivots tie) and solved with in between."""
    rng = np.random.default_rng(seed)
    out = []
    for c in range(count):
        n = int(rng.integers(1, 60))
        kind = c % 4
        rows: List[int] = []
        cols: List[int] = []
        for j in range(n):
            rows.append(j)
            cols.append(j)
            if kind == 0:                      # random entries in the column
                for _ in range(int(rng.integers(0, 4))):
                    rows.append(int(rng.integers(0, n)))
                    cols.append(j)
            elif kind == 1:                    # a chain feeding down, with a little back flow
                if j + 1 < n:
                    rows.append(j + 1)
                    cols.append(j)
                if j > 0 and rng.uniform() < 0.3:
                    rows.append(j - 1)
                    cols.append(j)
            elif kind == 2:                    # blocks of cells one way round
                if j % 5 != 4 and j + 1 < n:
                    rows.append(j + 1)
                    cols.append(j)
                if j % 5 != 0:
                    rows.append(j - 1)
                    cols.append(j)
                if j + 5 < n:
                    rows.append(j + 5)
                    cols.append(j)
            else:                              # anywhere
                for _ in range(int(rng.integers(0, 8))):
                    rows.append(int(rng.integers(0, n)))
                    cols.append(int(rng.integers(0, n)))
        cp, ri = csc_from_triplets(n, np.array(rows), np.array(cols))
        nnz = int(cp[n])
        ops: List[Dict[str, Any]] = []
        for _ in range(int(rng.integers(1, 5))):
            v = rng.normal(size=nnz) * 10 ** rng.uniform(-3, 3, nnz)
            r = rng.uniform()
            if r < 0.1:
                v[rng.integers(0, nnz, size=max(1, nnz // 3))] = 0.0
            elif r < 0.15:
                v[rng.integers(0, nnz)] = np.nan
            elif r < 0.2:
                v[:] = rng.choice([-2.0, -1.0, 0.5, 1.0, 2.0], size=nnz)
            ops.append({'values': hx(v)})
            for _ in range(int(rng.integers(0, 3))):
                ops.append({'b': hx(rng.normal(size=n))})
        out.append({'n': n, 'colPtr': cp.tolist(), 'rowIdx': ri.tolist(), 'rcm': c % 3 != 0, 'ops': ops})
    return out


@needs_app
@unittest.skipIf(packagelu is None, 'needs numba')
class PackageLU(unittest.TestCase):
    def test_every_factorisation_and_solve_is_the_applications(self) -> None:
        cs = cases(1, 600)
        ref = engine('package_lu', cases=cs)
        seen = {'factor': 0, 'singular': 0, 'solve': 0}
        for k, (c, r) in enumerate(zip(cs, ref)):
            n = c['n']
            cp = np.array(c['colPtr'], dtype=np.int64)
            ri = np.array(c['rowIdx'], dtype=np.int64)
            perm = reverse_cuthill_mckee(n, cp, ri) if c['rcm'] else None
            with self.subTest(case=k):
                self.assertEqual(None if perm is None else perm.tolist(), r['perm'])
                lu = packagelu.SparseLU(n, cp, ri, perm)
                ok = False
                for op, step in zip(c['ops'], r['steps']):
                    if 'values' in op:
                        ok = lu.factor(unhx(op['values']))
                        seen['factor'] += 1
                        seen['singular'] += not ok
                        self.assertEqual((ok, lu.singular, lu.fill), (step['ok'], step['singular'], step['fill']))
                    elif ok:
                        seen['solve'] += 1
                        self.assertEqual(hx(lu.solve(unhx(op['b']))), step['x'])
        # Every kind of outcome was met.
        self.assertGreater(seen['singular'], 50)
        self.assertGreater(seen['factor'] - seen['singular'], 500)
        self.assertGreater(seen['solve'], 500)

    def test_a_solve_leaves_its_right_hand_side(self) -> None:
        cp, ri = csc_from_triplets(3, np.array([0, 1, 2, 1, 2]), np.array([0, 1, 2, 0, 1]))
        lu = packagelu.SparseLU(3, cp, ri, reverse_cuthill_mckee(3, cp, ri))
        self.assertTrue(lu.factor(np.array([2.0, 1.0, 3.0, 1.0, 4.0])))
        b = np.array([1.0, 2.0, 3.0])
        x = lu.solve(b)
        self.assertEqual(b.tolist(), [1.0, 2.0, 3.0])
        A = np.zeros((3, 3))
        A[ri, np.repeat(np.arange(3), np.diff(cp))] = [2.0, 1.0, 3.0, 1.0, 4.0]
        np.testing.assert_allclose(A @ x, b, rtol=1e-15)


if __name__ == '__main__':
    unittest.main()
