"""The application's sparse LUs, compiled (``engine/solvers/sparselu.py``),
against the application's own.

For a sparse iteration matrix ``src/ode/core/sparse.js`` chooses between a
Gilbert-Peierls LU in two column orders, the LU that keeps its pivots
(``refactor.js``) and that LU a block at a time (``blocks.js``), and the
Python engine, with numba, factorises with a port of them. Checked here
through Node, bit for bit:

* the choice, ``info`` after every formation and every solve's answer, on
  made-up matrices of every shape the choice meets -- chains of cells, blocks
  one way round, matrices that fill in, singular ones and ones with a value
  that is not a number, held rows, algebraic rows, values that move far enough
  for the kept pivots to be chosen again, from a step past the first and from
  the start -- and on the far-field example's own first matrix;
* each LU on its own, the kept-pivot one in fixed column orders as well;

and that the solvers take it: an iteration matrix with numba is the
application's, and SuperLU's where the port is not there, and the two solve
alike to round-off.
"""

from __future__ import annotations

import re
import unittest
from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

from helpers import example, needs_app
from test_engine_lang import engine

from kompartment.engine.runner import run
from kompartment.engine.solvers import kernels
from kompartment.engine.solvers import matrix as matrix_module
from kompartment.engine.solvers.matrix import IterationMatrix

needs_numba = unittest.skipUnless(kernels.available(), 'numba is not installed: nothing is compiled')


def sparselu() -> Any:
    from kompartment.engine.solvers import sparselu as S
    return S


def hx(a: Any) -> str:
    return np.ascontiguousarray(a, dtype='<f8').tobytes().hex()


def unhx(h: str) -> np.ndarray:
    return np.frombuffer(bytes.fromhex(h), dtype='<f8').copy()


def made_up_pattern(rng: np.random.Generator, n: int, kind: str) -> Tuple[int, List[int], List[int]]:
    """A pattern of one of the shapes the choice meets: random, a chain of
    cells for each of a chain of nuclides (blocks one way round), one that
    fills in, a decay chain (blocks of one state), one with gaps on the diagonal."""
    cols: List[List[int]] = []
    if kind == 'chain':
        cells = int(rng.integers(2, 12))
        nuclides = max(1, n // cells)
        n = cells * nuclides
        for j in range(n):
            nuclide, c = divmod(j, cells)
            rows = {j}
            if c > 0:
                rows.add(j - 1)
            if c < cells - 1:
                rows.add(j + 1)
            if nuclide < nuclides - 1:
                rows.add(j + cells)
            cols.append(sorted(rows))
    else:
        for j in range(n):
            if kind == 'random':
                rows = set(rng.choice(n, size=min(n, int(rng.integers(0, 5))), replace=False).tolist())
                if rng.random() < 0.85:
                    rows.add(j)
            elif kind == 'fills':
                rows = set(rng.choice(n, size=max(1, int(0.35 * n)), replace=False).tolist()) | {j}
            elif kind == 'decay':
                rows = {j, j + 1} if j + 1 < n else {j}
            else:
                rows = set(rng.choice(n, size=min(n, 2), replace=False).tolist())
            cols.append(sorted(rows))
    col_ptr = [0]
    row_idx: List[int] = []
    for rows in cols:
        row_idx += rows
        col_ptr.append(len(row_idx))
    return n, col_ptr, row_idx


def made_up_values(rng: np.random.Generator, nnz: int, style: str) -> np.ndarray:
    if style == 'ties':
        # Halves, ones and twos: entries equal in size, where a pivot is chosen by a tie's rule.
        return rng.choice([-2.0, -1.0, -0.5, 0.5, 1.0, 2.0], size=nnz)
    v = rng.normal(size=nnz) * np.exp(rng.normal(size=nnz) * (3 if style == 'wild' else 1))
    if style == 'zeros':
        v[rng.random(nnz) < 0.3] = 0.0
    elif style == 'nan':
        v[int(rng.integers(nnz))] = np.nan
    elif style == 'inf':
        v[int(rng.integers(nnz))] = np.inf
    return v


def formations(rng: np.random.Generator, n: int, nnz: int, base: np.ndarray, odd: bool,
               held: bool) -> List[Dict[str, Any]]:
    """A few formations, each solved with once or twice: values near the
    start's, or far from them (which makes the kept pivots fail their test),
    values that tie, now and then a value that is not a number, held rows."""
    ops: List[Dict[str, Any]] = []
    for _ in range(int(rng.integers(1, 7))):
        style = ['plain', 'wild', 'zeros', 'ties', 'nan', 'inf'][int(rng.integers(0, 6 if odd else 4))]
        if style == 'ties':
            # With a step of a half, one or two, I - a*J ties too.
            ops.append({'form': {'a': float(rng.choice([0.5, 1.0, 2.0])),
                                 'values': hx(made_up_values(rng, nnz, style)), 'held': None}})
            ops.append({'solve': hx(rng.normal(size=n))})
            continue
        if style in ('nan', 'inf'):
            values = made_up_values(rng, nnz, style)
        elif rng.random() < 0.5:
            values = base * (1 + (0.05 if rng.random() < 0.5 else 2.0) * rng.normal(size=nnz))
        else:
            values = made_up_values(rng, nnz, style)
        rows = (rng.random(n) < 0.2).astype(int).tolist() if held and rng.random() < 0.4 else None
        ops.append({'form': {'a': float(10 ** rng.uniform(-4, 3)), 'values': hx(values), 'held': rows}})
        for _ in range(int(rng.integers(1, 3))):
            ops.append({'solve': hx(rng.normal(size=n))})
    return ops


def matrix_cases(seed: int, count: int) -> List[Dict[str, Any]]:
    rng = np.random.default_rng(seed)
    cases = []
    for k in range(count):
        kind = ['random', 'chain', 'fills', 'decay', 'gaps', 'random', 'chain'][k % 7]
        n, col_ptr, row_idx = made_up_pattern(rng, int(rng.integers(1, 60)) if k % 11 else int(rng.integers(100, 300)),
                                              kind)
        nnz = col_ptr[-1]
        mass = None
        if k % 9 == 4:
            mass = np.ones(n)
            mass[rng.random(n) < 0.2] = 0.0
        base = made_up_values(rng, nnz, 'plain')
        cases.append({'lu': 'matrix', 'n': n, 'colPtr': col_ptr, 'rowIdx': row_idx, 'values': hx(base),
                      'mode': ['auto', 'auto', 'refactor', 'sparse'][k % 4],
                      'mass': hx(mass) if mass is not None else None, 'denseBelow': 0 if k % 3 else 24,
                      'denseFill': 0.15, 'denseMaxBytes': 256 * 1024 * 1024, 'blocks': k % 13 != 5,
                      'ops': formations(rng, n, nnz, base, k % 5 == 0, True)})
    return cases


def part_cases(seed: int, count: int) -> List[Dict[str, Any]]:
    rng = np.random.default_rng(seed)
    cases = []
    for k in range(count):
        n, col_ptr, row_idx = made_up_pattern(rng, int(rng.integers(2, 120)),
                                              ['random', 'chain', 'fills', 'decay', 'chain'][k % 5])
        nnz = col_ptr[-1]
        mass = None
        if k % 6 == 1:
            mass = np.ones(n)
            mass[rng.random(n) < 0.15] = 0.0
        base = made_up_values(rng, nnz, 'plain')
        c: Dict[str, Any] = {'n': n, 'colPtr': col_ptr, 'rowIdx': row_idx, 'values': hx(base),
                             'mass': hx(mass) if mass is not None else None,
                             'ops': formations(rng, n, nnz, base, k % 7 == 0, False)}
        which = k % 5
        if which == 0:
            c['lu'] = 'refactor'
        elif which == 1:
            c['lu'] = 'refactor'
            c['columns'] = rng.permutation(n).tolist() if rng.random() < 0.5 else list(range(n))
        elif which == 2:
            c['lu'] = 'blocks'
        else:
            c['lu'] = 'gp'
            c['order'] = 'rcm' if which == 4 else None
        cases.append(c)
    return cases


def column_of(message: str) -> Tuple[Optional[int], bool]:
    m = re.search(r'column (\d+)', message)
    return (int(m.group(1)) if m else None), ('not a number' in message)


def replay_matrix(S: Any, c: Dict[str, Any], app: Dict[str, Any], seen: Counter) -> Optional[str]:
    """The case through the port as the application took it: what differs, or None."""
    n = c['n']
    too_big = n * n * 8 > c['denseMaxBytes']
    if c['mode'] == 'auto' and n < c['denseBelow'] and not too_big:
        seen['dense, small'] += 1
        return None if app['made']['lu'] == 'dense' else f"dense by size, the application's {app['made']}"
    mass = unhx(c['mass']) if c['mass'] else None
    sw = S.decide(n, np.array(c['colPtr']), np.array(c['rowIdx']), unhx(c['values']), c['mode'], mass,
                  c['denseFill'], too_big, c['blocks'])
    got = S.state(sw)
    made = {'sparse': got['kind'] != S.DENSE, 'lu': got['lu'], 'fill': got['fill'], 'ordering': got['ordering'],
            'repivots': got['repivots'], 'fallbacks': got['fallbacks']}
    if made != app['made']:
        return f"chose {made}, the application {app['made']}"
    seen[got['ordering'] if got['kind'] != S.DENSE else 'dense, by fill'] += 1
    if got['kind'] == S.DENSE:
        return None
    if mass is not None:
        seen['algebraic rows'] += 1
    failed = False
    for i, (op, step) in enumerate(zip(c['ops'], app['steps'])):
        if 'form' in op:
            f = op['form']
            status = S.form(sw, f['a'], unhx(f['values']), None if f['held'] is None else np.array(f['held']))
            got = S.state(sw)
            info = {'sparse': True, 'lu': got['lu'], 'fill': got['fill'], 'ordering': got['ordering'],
                    'repivots': got['repivots'], 'fallbacks': got['fallbacks']}
            if f['held'] is not None:
                seen['held rows'] += 1
            if info != step['info']:
                return f"form {i}: {info}, the application's {step['info']}"
            failed = 'error' in step
            if failed:
                column, not_a_number = column_of(step['error'])
                seen['not a number' if not_a_number else 'singular'] += 1
                if status == S.OK or (column, not_a_number) != (got['column'], got['nonfinite']):
                    return f"form {i}: {status} at {got['column']}, the application: {step['error']}"
            elif status != S.OK:
                return f'form {i} failed ({status}), not in the application'
            if got['repivots'] >= 2:
                seen['pivots chosen again'] += 1
            if got['fallbacks']:
                seen['declined, factorised elsewhere'] += 1
        elif 'x' in step:
            if hx(S.solve(sw, unhx(op['solve']))) != step['x']:
                return f'solve {i} differs'
        elif failed:
            # After a failed formation the solvers stop; the port answers NaN.
            if not np.all(np.isnan(S.solve(sw, unhx(op['solve'])))):
                return f'solve {i} after a failed formation is not NaN'
    return None


@needs_numba
@needs_app
class TheApplicationsSparseLUs(unittest.TestCase):
    def test_every_choice_and_every_formation_to_the_last_bit(self) -> None:
        S = sparselu()
        cases = matrix_cases(7, 400)
        answer = engine('sparse_lu', cases=cases)
        seen: Counter = Counter()
        for k, (c, app) in enumerate(zip(cases, answer['results'])):
            with self.subTest(case=k, n=c['n'], mode=c['mode']):
                self.assertNotIn('refused', app)
                self.assertIsNone(replay_matrix(S, c, app, seen))
        # Every choice was made, and every way a formation goes was gone.
        for what in ('natural', 'reverse Cuthill-McKee', 'threshold Markowitz',
                     'block triangular, threshold Markowitz', 'dense, by fill', 'dense, small', 'held rows',
                     'algebraic rows', 'singular', 'not a number', 'pivots chosen again',
                     'declined, factorised elsewhere'):
            self.assertGreater(seen[what], 0, what)
        self.assertGreater(answer['counts']['partial'], 0)
        self.assertGreater(answer['counts']['again'], 0)

    def test_each_lu_on_its_own(self) -> None:
        S = sparselu()
        cases = part_cases(3, 300)
        answer = engine('sparse_lu', cases=cases)
        seen: Counter = Counter()
        for k, (c, app) in enumerate(zip(cases, answer['results'])):
            n = c['n']
            col_ptr = np.array(c['colPtr'], dtype=np.int64)
            row_idx = np.array(c['rowIdx'], dtype=np.int64)
            has_mass = c['mass'] is not None
            mass = unhx(c['mass']) if has_mass else np.ones(n)
            with self.subTest(case=k, lu=c['lu'], n=n):
                if c['lu'] == 'gp':
                    mp, mi, jtom, diag = S.miter_structure(n, col_ptr, row_idx)
                    mx = np.zeros(mi.size)
                    lu = S.gp_new(n)
                    rcm = c['order'] == 'rcm'
                    q = np.arange(n)
                    if rcm:
                        S.miter_update(1e-3, unhx(c['values']), mass, has_mass, mx, jtom, diag)
                        q = S.rcm_order(n, mp, mi)
                        self.assertEqual(q.tolist(), app['order'])
                    for op, step in zip(c['ops'], app['steps']):
                        if 'form' in op:
                            S.miter_update(op['form']['a'], unhx(op['form']['values']), mass, has_mass, mx, jtom, diag)
                            S.gp_factorize(lu, mp, mi, mx, q, rcm, np.inf)
                            got = dict(zip(('singular', 'nonFinite', 'column', 'lnz', 'unz', 'flops'), _gp(lu)))
                            got['singular'], got['nonFinite'] = bool(got['singular']), bool(got['nonFinite'])
                            if got['singular']:
                                seen['singular'] += 1
                                got = {k: got[k] for k in ('singular', 'nonFinite', 'column')}
                                self.assertEqual(got, {k: step[k] for k in got})
                            else:
                                self.assertEqual(got, step)
                        elif 'x' in step:
                            x = np.zeros(n)
                            S.gp_solve(lu, unhx(op['solve']), x)
                            self.assertEqual(hx(x), step['x'])
                    continue
                if c['lu'] == 'blocks':
                    nblocks, block = S.block_triangular(n, col_ptr, row_idx)
                    self.assertEqual({'nblocks': int(nblocks), 'block': block.tolist()}, app['blocks'])
                    lu = S.bk_new(n, col_ptr, row_idx, nblocks, block)
                    factor, solve, info = S.bk_factor, S.bk_solve, _bk
                else:
                    columns = np.array(c.get('columns') or [], dtype=np.int64)
                    lu = S.rf_new(n, col_ptr, row_idx, columns, bool(c.get('columns')))
                    factor, solve, info = S.rf_factor, S.rf_solve, _rf
                label = c['lu'] + (' in a fixed column order' if c.get('columns') else '')
                for op, step in zip(c['ops'], app['steps']):
                    if 'form' in op:
                        ok = factor(lu, op['form']['a'], unhx(op['form']['values']), mass, has_mass)
                        got = dict(zip(('ops', 'nnz', 'repivots', 'valid'), (int(v) for v in info(lu))))
                        got['ok'], got['valid'] = bool(ok), bool(got['valid'])
                        self.assertEqual(got, step)
                        seen[label + (', made' if ok else ', declined')] += 1
                        if got['repivots'] >= 2:
                            seen[label + ', pivots chosen again'] += 1
                    elif 'x' in step:
                        x = np.zeros(n)
                        solve(lu, unhx(op['solve']), x)
                        self.assertEqual(hx(x), step['x'])
        for what in ('refactor, made', 'refactor, declined', 'refactor, pivots chosen again',
                     'refactor in a fixed column order, made', 'refactor in a fixed column order, pivots chosen again',
                     'blocks, made', 'blocks, pivots chosen again', 'singular'):
            self.assertGreater(seen[what], 0, what)
        self.assertGreater(answer['counts']['partial'], 0)
        self.assertGreater(answer['counts']['again'], 0)

    def test_the_far_field_examples_matrix(self) -> None:
        S = sparselu()
        n, pattern, values = far_field_matrix()
        rng = np.random.default_rng(5)
        ops: List[Dict[str, Any]] = []
        for a in (1e-3, 0.37, 41.0, 5e3):
            held = (rng.random(n) < 0.05).astype(int).tolist() if a > 1 else None
            ops.append({'form': {'a': a, 'values': hx(values * (1 + 0.5 * rng.normal(size=values.size))),
                                 'held': held}})
            ops.append({'solve': hx(rng.normal(size=n))})
        cases = [{'lu': 'matrix', 'n': n, 'colPtr': pattern.col_ptr.tolist(), 'rowIdx': pattern.row_idx.tolist(),
                  'values': hx(values), 'mode': mode, 'mass': None, 'denseBelow': 24, 'denseFill': 0.15,
                  'denseMaxBytes': 256 * 1024 * 1024, 'blocks': True, 'ops': ops}
                 for mode in ('auto', 'refactor', 'sparse')]
        answer = engine('sparse_lu', cases=cases)
        seen: Counter = Counter()
        for c, app in zip(cases, answer['results']):
            with self.subTest(mode=c['mode']):
                self.assertIsNone(replay_matrix(S, c, app, seen))
        self.assertEqual(seen['block triangular, threshold Markowitz'], 2)
        self.assertEqual(seen['reverse Cuthill-McKee'] + seen['natural'], 1)


def _gp(lu: Any) -> Any:
    return _getters()[0](lu)


def _rf(lu: Any) -> Any:
    return _getters()[1](lu)


def _bk(lu: Any) -> Any:
    return _getters()[2](lu)


_GETTERS: List[Any] = []


def _getters() -> List[Any]:
    """What the tests read of each LU, compiled (a structref's fields are compiled code's)."""
    if not _GETTERS:
        from numba import njit
        S = sparselu()

        @njit
        def gp(g: Any) -> Any:
            return g.singular, g.nonfinite, g.fail_original, g.lnz, g.unz, g.flops

        @njit
        def rf(r: Any) -> Any:
            return r.ops, r.nnz, r.repivots, r.valid

        @njit
        def bk(b: Any) -> Any:
            return b.ops, b.nnz, S.bk_repivots(b), b.valid

        _GETTERS.extend((gp, rf, bk))
    return _GETTERS


_FAR_FIELD: List[Any] = []


def far_field_matrix() -> Tuple[int, Any, np.ndarray]:
    """The far-field example's first iteration matrix, as the NDF starts it:
    its size, its pattern and the Jacobian's values."""
    if not _FAR_FIELD:
        made = matrix_module.IterationMatrix.__init__

        def catch(self: Any, n: int, pattern: Any, values: Any, *args: Any, **kwargs: Any) -> None:
            if pattern is not None and not _FAR_FIELD:
                _FAR_FIELD.append((n, pattern, np.array(values, dtype=float)))
            made(self, n, pattern, values, *args, **kwargs)

        model = example('farfield')
        model['simulation'].update(solver='ndf', end_time=1.0)
        matrix_module.IterationMatrix.__init__ = catch  # type: ignore[method-assign]
        try:
            run(model, compiled=False, workers=1)
        finally:
            matrix_module.IterationMatrix.__init__ = made  # type: ignore[method-assign]
    return _FAR_FIELD[0]


@needs_numba
class TheSolversTakeThem(unittest.TestCase):
    def test_a_sparse_matrix_is_the_applications_and_superlus_without_it(self) -> None:
        n, pattern, values = far_field_matrix()
        W = IterationMatrix(n, pattern, values, 'auto')
        self.assertTrue(W.sparse)
        self.assertIsNotNone(W._sw)
        self.assertEqual((W.info['lu'], W.info['ordering'], W.info['fill']),
                         ('refactor', 'block triangular, threshold Markowitz', 5788))
        rng = np.random.default_rng(2)
        b = rng.normal(size=n)
        W.form(0.37, values)
        x = W.solve(b)
        # The same matrix by SuperLU, where the port is not there.
        was = matrix_module._SPARSE_LU[:]
        matrix_module._SPARSE_LU[:] = [None]
        try:
            V = IterationMatrix(n, pattern, values, 'auto')
        finally:
            matrix_module._SPARSE_LU[:] = was
        self.assertIsNone(V._sw)
        self.assertEqual(V.info['lu'], 'SuperLU')
        V.form(0.37, values)
        y = V.solve(b)
        self.assertLess(np.max(np.abs(x - y)) / np.max(np.abs(y)), 1e-12)

    def test_auto_goes_sparse_from_64_states(self) -> None:
        # A decay chain of 63 states is factorised densely, of 64 sparsely
        # (the application goes sparse from 24; the Julia engine from 64).
        for size, sparse in ((63, False), (64, True)):
            p = chain_pattern(size)
            W = IterationMatrix(size, p, -np.ones(p.nnz), 'auto')
            self.assertEqual(W.sparse, sparse)

    def test_a_singular_matrix_says_where(self) -> None:
        # A decay chain whose middle state's column is all zeros, its row
        # algebraic: the constraint does not determine it.
        size = 30
        p = chain_pattern(size)
        values = -np.ones(p.nnz)
        mass = np.ones(size)
        mass[12] = 0.0
        W = IterationMatrix(size, p, values, 'refactor', mass, {'singular': 'A hint.'})
        self.assertEqual(W.info['ordering'], 'block triangular, threshold Markowitz')
        values[p.col_ptr[12]:p.col_ptr[13]] = 0.0
        with self.assertRaisesRegex(RuntimeError, 'singular at the algebraic variable in column 12'):
            W.form(0.5, values)
        self.assertEqual(W.info['fallbacks'], 1)
        # After it, no solve: the solvers stop there, and this answers NaN.
        self.assertTrue(np.all(np.isnan(W.solve(np.ones(size)))))
        values[:] = -1.0
        values[0] = np.inf
        V = IterationMatrix(size, p, -np.ones(p.nnz), 'sparse', None, {'singular': 'A hint.'})
        with self.assertRaisesRegex(RuntimeError, r'not a number \(inf\) at column 0'):
            V.form(0.5, values)
        # I - a*J is singular where a column of it is: 1 - a*J_55 = 0, J_65 = 0.
        values[0] = -1.0
        values[p.col_ptr[5]] = 2.0
        values[p.col_ptr[5] + 1] = 0.0
        with self.assertRaisesRegex(RuntimeError, r'I - h\*J is singular at column 5\. A hint\.'):
            V.form(0.5, values)


def chain_pattern(size: int) -> Any:
    """A decay chain's pattern: each state feeds the next."""
    from kompartment.engine.jacobian import Pattern
    rows = [r for j in range(size) for r in ((j, j + 1) if j + 1 < size else (j,))]
    cols = [j for j in range(size) for _ in ((j, j + 1) if j + 1 < size else (j,))]
    return Pattern(size, np.array(rows, dtype=np.int64), np.array(cols, dtype=np.int64))


if __name__ == '__main__':
    unittest.main()
