"""The compiled inner loops against what they replace.

With numba installed the solvers factorise a small dense iteration matrix with
the application's own LU compiled (``engine/solvers/kernels.py``) and sum the
derivative with a compiled kernel (``engine/assembly.py``). Each is checked
here against its reference, bit for bit:

* the LU against ``src/ode/core/linalg.js`` itself, through Node -- factors,
  pivots, solutions and where a singular matrix fails;
* the error norm and the sign checks against their numpy forms;
* the derivative sum against the ordered ``bincount`` it replaces, on every
  bundled example;

and the LAPACK path, taken without numba, against the compiled one to round-off.
"""

from __future__ import annotations

import math
import unittest

import numpy as np

from helpers import example, needs_app
from test_engine_lang import engine, number
from test_engine_parity import EXAMPLES

from kompartment.engine import assembly
from kompartment.engine.builder import build_system
from kompartment.engine.jacobian import Pattern
from kompartment.engine.project import Project
from kompartment.engine.solvers import kernels
from kompartment.engine.solvers.matrix import IterationMatrix

needs_numba = unittest.skipUnless(kernels.available(), 'numba is not installed: nothing is compiled')


def random_pattern(rng: np.random.Generator, n: int, density: float) -> np.ndarray:
    return (rng.uniform(size=(n, n)) < density) | np.eye(n, dtype=bool)


def csc(mask: np.ndarray):
    cols, rows = np.nonzero(mask.T)
    col_ptr = np.concatenate([[0], np.cumsum(mask.sum(axis=0))]).astype(np.int64)
    return col_ptr, rows.astype(np.int64)


@needs_numba
@needs_app
class DenseLU(unittest.TestCase):
    def test_the_applications_lu_to_the_last_bit(self) -> None:
        rng = np.random.default_rng(11)
        cases = []
        for n in (1, 2, 3, 7, 16, 23, 40, 90):
            for _ in range(4):
                col_ptr, rows = csc(random_pattern(rng, n, rng.uniform(0.1, 0.7)))
                cases.append({'n': n, 'a': float(10 ** rng.uniform(-3, 2)), 'colPtr': col_ptr.tolist(),
                              'rowIdx': rows.tolist(),
                              'values': (rng.normal(size=rows.size) * 10 ** rng.uniform(-3, 3, rows.size)).tolist(),
                              'b': rng.normal(size=n).tolist()})
        # Singular: an algebraic row (mass 0) whose column holds nothing.
        n = 6
        mask = random_pattern(rng, n, 0.5)
        mask[:, 3] = False
        mask[3, :] = False
        col_ptr, rows = csc(mask)
        mass = [1.0] * n
        mass[3] = 0.0
        cases.append({'n': n, 'a': 0.1, 'colPtr': col_ptr.tolist(), 'rowIdx': rows.tolist(),
                      'values': rng.normal(size=rows.size).tolist(), 'mass': mass, 'b': [1.0] * n})
        js = engine('lu', cases=cases)
        form, solve = kernels.kernel('pattern'), kernels.kernel('solve')
        singular = 0
        for c, j in zip(cases, js):
            n = c['n']
            lu, piv, fail = np.zeros((n, n)), np.zeros(n, dtype=np.int64), np.zeros(2)
            status = form(c['a'], np.array(c['colPtr'], dtype=np.int64), np.array(c['rowIdx'], dtype=np.int64),
                          np.array(c['values']), np.zeros(n, dtype=np.bool_),
                          np.array(c.get('mass') or [1.0] * n), lu, piv, fail)
            with self.subTest(n=n):
                if j.get('singular'):
                    singular += 1
                    self.assertNotEqual(status, kernels.OK)
                    self.assertEqual(int(fail[0]), j['column'])
                    continue
                self.assertEqual(status, kernels.OK)
                self.assertTrue(np.array_equal(lu, np.array(j['lu'])))
                self.assertEqual(piv.tolist(), j['piv'])
                x = solve(lu, piv, np.array(c['b']), np.zeros(n))
                self.assertTrue(np.array_equal(x, np.array([number(v) for v in j['x']])))
        self.assertEqual(singular, 1)


@needs_numba
class SmallKernels(unittest.TestCase):
    def test_the_error_norm_is_the_numpy_one(self) -> None:
        rng = np.random.default_rng(5)
        k = kernels.kernel('weighted')
        out = np.zeros(2)
        for trial in range(400):
            n = int(rng.integers(0, 30))
            v, ya, yb = (rng.normal(size=n) * 10 ** rng.uniform(-8, 8, n) for _ in range(3))
            th = 10 ** rng.uniform(-10, 0, n)
            if n and trial % 7 == 0:
                (v if trial % 2 else yb)[int(rng.integers(n))] = math.nan
            if n and trial % 11 == 0:
                v[int(rng.integers(n))] = math.inf
            k(v, ya, yb, th, out)
            worst, at = kernels.weighted_py(v, ya, yb, th)
            self.assertTrue((out[0] == worst) or (math.isnan(out[0]) and math.isnan(worst)), trial)
            self.assertEqual(int(out[1]), at)

    def test_the_sign_checks(self) -> None:
        above, below = kernels.kernel('all_above_zero'), kernels.kernel('any_below_zero')
        idx = np.array([0, 2], dtype=np.int64)
        for y, a, b in (([1, -1, 2], True, False), ([0, 5, 1], False, False), ([1, 5, -0.5], False, True),
                        ([math.nan, 1, 1], False, False)):
            y = np.array(y, dtype=float)
            self.assertEqual(bool(above(y, idx)), a, y)
            self.assertEqual(bool(below(y, idx)), b, y)


@needs_numba
class DerivativeSum(unittest.TestCase):
    def test_the_compiled_sum_is_the_ordered_bincount(self) -> None:
        for name in EXAMPLES:
            s = build_system(Project(example(name)), jacobian=False)
            if not s.nstate:
                continue
            rng = np.random.default_rng(3)
            for _ in range(5):
                y = rng.uniform(0, 10, s.nstate) * 10 ** rng.uniform(-3, 3, s.nstate)
                t = s.start_time + (s.end_time - s.start_time) * rng.uniform()
                compiled = s.dydt(t, y).copy()
                kept = s._assemble._sum
                s._assemble._sum = None
                try:
                    summed = s.dydt(t, y).copy()
                finally:
                    s._assemble._sum = kept
                with self.subTest(example=name):
                    self.assertTrue(kept is not None and assembly.KERNEL_TERMS == 0)
                    self.assertTrue(np.array_equal(compiled, summed))


class LapackFallback(unittest.TestCase):
    def test_lapack_solves_what_the_compiled_lu_solves(self) -> None:
        rng = np.random.default_rng(8)
        for n in (3, 17, 60):
            mask = random_pattern(rng, n, 0.3)
            col_ptr, rows = csc(mask)
            p = Pattern(n, rows, np.repeat(np.arange(n), np.diff(col_ptr)))
            values = rng.normal(size=rows.size)
            b = rng.normal(size=n)
            W = IterationMatrix(n, p, values, 'dense')
            W.form(0.3, values)
            x = W.solve(b)
            W._kernels = False
            W.form(0.3, values)
            y = W.solve(b)
            self.assertTrue(np.allclose(x, y, rtol=1e-10, atol=1e-12), n)


if __name__ == '__main__':
    unittest.main()
