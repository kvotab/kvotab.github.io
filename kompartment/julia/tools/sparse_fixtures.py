"""The application's sparse LUs, from the Python engine, for the Julia engine's tests.

The Python package's port of them (``engine/solvers/sparselu.py``) is the
application's to the bit (its ``test_engine_sparse.py``), so this writes the
cases that test makes up -- 400 matrices taken through ``iterationMatrix``'s
choice and up to six formations each, and 300 through one LU each -- with what
the Python package makes of them: every choice, every ``info``, every solve.
Doubles travel as little-endian hex, to the bit.

    python3 tools/sparse_fixtures.py OUT_DIR

Run it with the repository's Python package on the path
(``PYTHONPATH=kompartment/python``), and numba installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / 'python' / 'tests'))

from test_engine_sparse import hx, matrix_cases, part_cases, unhx  # noqa: E402

from kompartment.engine.solvers import sparselu as S  # noqa: E402


def _getters() -> Any:
    from numba import njit

    @njit
    def gp(g: Any) -> Any:
        return g.singular, g.nonfinite, g.fail_original, g.lnz, g.unz, g.flops

    @njit
    def rf(r: Any) -> Any:
        return r.ops, r.nnz, r.repivots, r.valid

    @njit
    def bk(b: Any) -> Any:
        return b.ops, b.nnz, S.bk_repivots(b), b.valid

    return gp, rf, bk


def matrix_case(c: Dict[str, Any]) -> Dict[str, Any]:
    """What the Python package makes of a matrix case: the choice, then each formation's
    outcome and info and each solve's answer."""
    n = c['n']
    too_big = n * n * 8 > c['denseMaxBytes']
    if c['mode'] == 'auto' and n < c['denseBelow'] and not too_big:
        return {'made': {'kind': S.DENSE, 'ordering': 'natural', 'fill': None}, 'steps': []}
    mass = unhx(c['mass']) if c['mass'] else None
    sw = S.decide(n, np.array(c['colPtr']), np.array(c['rowIdx']), unhx(c['values']), c['mode'], mass,
                  c['denseFill'], too_big, c['blocks'])
    got = S.state(sw)
    out: Dict[str, Any] = {'made': {'kind': got['kind'], 'ordering': got['ordering'], 'fill': got['fill']},
                           'steps': []}
    if got['kind'] == S.DENSE:
        return out
    for op in c['ops']:
        if 'form' in op:
            f = op['form']
            status = S.form(sw, f['a'], unhx(f['values']), None if f['held'] is None else np.array(f['held']))
            got = S.state(sw)
            step = {'status': status, 'fill': got['fill'], 'repivots': got['repivots'],
                    'fallbacks': got['fallbacks']}
            if status:
                step.update(column=got['column'], nonfinite=got['nonfinite'])
            out['steps'].append(step)
        else:
            out['steps'].append({'x': hx(S.solve(sw, unhx(op['solve'])))})
    return out


def part_case(c: Dict[str, Any], getters: Any) -> Dict[str, Any]:
    """What one LU of the Python package makes of a case's formations and solves."""
    gp_info, rf_info, bk_info = getters
    n = c['n']
    col_ptr = np.array(c['colPtr'], dtype=np.int64)
    row_idx = np.array(c['rowIdx'], dtype=np.int64)
    has_mass = c['mass'] is not None
    mass = unhx(c['mass']) if has_mass else np.ones(n)
    out: Dict[str, Any] = {'steps': []}
    if c['lu'] == 'gp':
        mp, mi, jtom, diag = S.miter_structure(n, col_ptr, row_idx)
        mx = np.zeros(mi.size)
        lu = S.gp_new(n)
        rcm = c['order'] == 'rcm'
        q = np.arange(n)
        if rcm:
            S.miter_update(1e-3, unhx(c['values']), mass, has_mass, mx, jtom, diag)
            q = S.rcm_order(n, mp, mi)
            out['order'] = q.tolist()
        ok = False
        for op in c['ops']:
            if 'form' in op:
                S.miter_update(op['form']['a'], unhx(op['form']['values']), mass, has_mass, mx, jtom, diag)
                S.gp_factorize(lu, mp, mi, mx, q, rcm, np.inf)
                singular, nonfinite, column, lnz, unz, flops = (int(v) for v in gp_info(lu))
                ok = not singular
                out['steps'].append({'singular': bool(singular), 'nonfinite': bool(nonfinite), 'column': column,
                                     'lnz': lnz, 'unz': unz, 'flops': flops})
            elif ok:
                x = np.zeros(n)
                S.gp_solve(lu, unhx(op['solve']), x)
                out['steps'].append({'x': hx(x)})
            else:
                out['steps'].append({'unsolved': True})
        return out
    if c['lu'] == 'blocks':
        nblocks, block = S.block_triangular(n, col_ptr, row_idx)
        out['blocks'] = {'nblocks': int(nblocks), 'block': block.tolist()}
        lu = S.bk_new(n, col_ptr, row_idx, nblocks, block)
        factor, solve, info = S.bk_factor, S.bk_solve, bk_info
    else:
        columns = np.array(c.get('columns') or [], dtype=np.int64)
        lu = S.rf_new(n, col_ptr, row_idx, columns, bool(c.get('columns')))
        factor, solve, info = S.rf_factor, S.rf_solve, rf_info
    ok = False
    for op in c['ops']:
        if 'form' in op:
            ok = bool(factor(lu, op['form']['a'], unhx(op['form']['values']), mass, has_mass))
            ops, nnz, repivots, valid = (int(v) for v in info(lu))
            out['steps'].append({'ok': ok, 'ops': ops, 'nnz': nnz, 'repivots': repivots, 'valid': bool(valid)})
        elif ok:
            x = np.zeros(n)
            solve(lu, unhx(op['solve']), x)
            out['steps'].append({'x': hx(x)})
        else:
            out['steps'].append({'unsolved': True})
    return out


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    target = Path(argv[1])
    target.mkdir(parents=True, exist_ok=True)
    getters = _getters()
    matrices = matrix_cases(7, 400)
    parts = part_cases(3, 300)
    for c in matrices:
        c['expect'] = matrix_case(c)
    for c in parts:
        c['expect'] = part_case(c, getters)
    (target / 'sparselu.json').write_text(json.dumps({'matrices': matrices, 'parts': parts}), 'utf-8')
    print(f'{len(matrices)} matrices and {len(parts)} single LUs into {target / "sparselu.json"}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
