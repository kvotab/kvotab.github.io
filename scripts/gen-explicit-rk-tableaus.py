#!/usr/bin/env python3
"""Emit resources/js/ode/julia/solvers/tsit5-tableau.js and vern7-tableau.js
from the Julia sources.

The coefficients are read out of OrdinaryDiffEq.jl's tsit_tableaus.jl and
verner_tableaus.jl as raw text tokens -- the Float64 literals of the
`CompiledFloats` methods, which are the numbers Julia itself runs with -- and
spliced into JavaScript without ever being retyped. A tableau with one wrong
digit still runs and still reports converged steps; it is just quietly of a
lower order, so the numbers are never typed by hand.

    python3 scripts/gen-explicit-rk-tableaus.py [dir]

`dir` holds tsit_tableaus.jl and verner_tableaus.jl (the src/ folders of
OrdinaryDiffEqTsit5 and OrdinaryDiffEqVerner, copied side by side, or either
package's src/ for its own file). With no argument both are downloaded from
the SciML repository. Nothing is written unless the coefficients satisfy the
identities they must: the rows of `a` sum to `c`, `b` sums to one, `btilde`
to zero, and each interpolant reproduces the step's own solution at θ = 1.
"""
import re
import subprocess
import sys
from pathlib import Path

BASE = 'https://raw.githubusercontent.com/SciML/OrdinaryDiffEq.jl/master/lib/'
SOURCES = {
    'tsit_tableaus.jl': BASE + 'OrdinaryDiffEqTsit5/src/tsit_tableaus.jl',
    'verner_tableaus.jl': BASE + 'OrdinaryDiffEqVerner/src/verner_tableaus.jl',
}
ROOT = Path(__file__).resolve().parent.parent
OUT_TSIT5 = ROOT / 'resources/js/ode/julia/solvers/tsit5-tableau.js'
OUT_VERN7 = ROOT / 'resources/js/ode/julia/solvers/vern7-tableau.js'


def source(name: str) -> str:
    if len(sys.argv) > 1:
        for p in (Path(sys.argv[1]) / name, Path(sys.argv[1])):
            if p.is_file() and p.name == name:
                return p.read_text()
        raise SystemExit(f'{name} not found under {sys.argv[1]}')
    return subprocess.run(['curl', '-sSf', SOURCES[name]], capture_output=True, text=True,
                          check=True).stdout


def compiled_block(text: str, name: str) -> dict[str, str]:
    """The `x = convert(T, literal)` assignments of the Float64 method of `name`.

    That is the method whose signature restricts T to CompiledFloats; the other
    one builds the same numbers from rationals and BigFloats for wider types.
    """
    for m in re.finditer(rf'^(?:@fold )?function {name}\((.*?)\)(?: where \{{(.*?)\}})?\n', text,
                         re.S | re.M):
        signature = m.group(0)
        if 'CompiledFloats' not in signature:
            continue
        body = text[m.end():]
        end = re.search(r'^end\b', body, re.M)
        body = body[:end.start()]
        out = {}
        for line in body.splitlines():
            line = line.split('#', 1)[0].strip()
            a = re.fullmatch(r'(\w+) = convert\(T2?, ([-+0-9.eE]+)\)', line)
            if a:
                out[a.group(1)] = a.group(2)
        if not out:
            raise SystemExit(f'{name}: no coefficients parsed')
        return out
    raise SystemExit(f'{name}: no CompiledFloats method found')


def num(tok: str) -> float:
    return float(tok)


def js(tok: str) -> str:
    """A literal as JavaScript reads it: the same token, with an integer kept exact."""
    return tok if re.search(r'[.eE]', tok) else f'{tok}.0' if tok.lstrip('-').isdigit() else tok


def poly_at_one(coeffs: list[str]) -> float:
    return sum(num(c) for c in coeffs)


def require(ok: bool, what: str) -> None:
    if not ok:
        raise SystemExit(f'refusing to write: {what}')


def tsit5() -> str:
    text = source('tsit_tableaus.jl')
    t = compiled_block(text, 'Tsit5ConstantCacheActual')
    r = compiled_block(text, 'Tsit5Interp')
    c = ['0'] + [t[f'c{i}'] for i in range(1, 7)]           # stages 1..7; c5 = c6 = 1
    a = [[]] + [[t[f'a{i}{j}'] for j in range(1, i)] for i in range(2, 8)]
    b = a[6] + ['0']                                          # FSAL: u is stage 7's point
    btilde = [t[f'btilde{j}'] for j in range(1, 8)]
    # b_jΘ = Θ·(r11 + r12Θ + r13Θ² + r14Θ³) for j = 1, Θ²·(rj2 + rj3Θ + rj4Θ²) otherwise
    interp = [[r['r11'], r['r12'], r['r13'], r['r14']]]
    for j in range(2, 8):
        interp.append([r[f'r{j}2'], r[f'r{j}3'], r[f'r{j}4']])

    for i in range(1, 7):
        s = sum(num(x) for x in a[i])
        require(abs(s - num(c[i])) <= 1e-14 * max(1.0, max(abs(num(x)) for x in a[i])),
                f'Tsit5 row {i + 1} of a sums to {s!r}, not c = {c[i]}')
    require(abs(sum(num(x) for x in b) - 1) <= 1e-14, 'Tsit5 b does not sum to one')
    require(abs(sum(num(x) for x in btilde)) <= 1e-14, 'Tsit5 btilde does not sum to zero')
    for j in range(7):
        at1 = poly_at_one(interp[j])
        require(abs(at1 - num(b[j])) <= 1e-13 * max(1.0, max(abs(num(x)) for x in interp[j])),
                f'Tsit5 interpolant {j + 1} is {at1!r} at θ = 1, not b = {b[j]}')

    rows = ',\n'.join('    [' + ', '.join(js(x) for x in row) + ']' for row in a)
    irows = ',\n'.join('    [' + ', '.join(js(x) for x in row) + ']' for row in interp)
    return f'''/* ==========================================================================
   ode_julia / solvers / tsit5-tableau

   GENERATED -- do not edit by hand.
   Written by scripts/gen-explicit-rk-tableaus.py from the Float64 method of
   Tsit5ConstantCacheActual and Tsit5Interp in
   OrdinaryDiffEqTsit5/src/tsit_tableaus.jl.

   Tsit5: Tsitouras's 5(4) pair, seven stages, first same as last, with a
   free fourth-order interpolant.

     Tsitouras, Ch. (2011). Runge-Kutta pairs of order 5(4) satisfying only
     the first column simplifying assumption. Computers & Mathematics with
     Applications 62, 770-775.

   Shapes. `a` is strictly lower triangular and ragged: row i has i entries,
   so row 0 is empty. `b` is row 7 of `a` with a trailing zero: the solution
   is the point stage 7 is evaluated at, and k7 = f(u) is the next step's k1.
   `interp[0]` holds r11..r14 of b1(Θ) = Θ·(r11 + r12·Θ + r13·Θ² + r14·Θ³);
   `interp[j]` for j > 0 holds rj2..rj4 of bj(Θ) = Θ²·(rj2 + rj3·Θ + rj4·Θ²).
   ========================================================================== */

export const Tsit5Tableau = {{
  name: 'Tsit5',
  stages: 7,
  order: 5,
  errorOrder: 4,
  // The width of the method's stability region along the negative real axis,
  // which the stiffness test of the automatic switch divides by
  // (alg_stability_size in OrdinaryDiffEqTsit5/src/alg_utils.jl).
  stabilitySize: 3.5068,
  c: [{', '.join(js(x) for x in c)}],
  a: [
{rows},
  ],
  b: [{', '.join(js(x) for x in b)}],
  btilde: [{', '.join(js(x) for x in btilde)}],
  interp: [
{irows},
  ],
}};
'''


def vern7() -> str:
    text = source('verner_tableaus.jl')
    t = compiled_block(text, 'Vern7Tableau')
    x = compiled_block(text, 'Vern7ExtraStages')
    r = compiled_block(text, 'Vern7InterpolationCoefficients')

    def key(i, j):
        return f'a{i:02d}{j}' if i < 10 else f'a{i}{j}'

    # The ten stages of the step. Stage i's row lists a_ij for j < i, zero where
    # the source has none (Vern7's a_i2 vanish beyond row 3, and so on).
    c = ['0', t['c2'], t['c3'], t['c4'], t['c5'], t['c6'], t['c7'], t['c8'], '1', '1']
    a = [[]]
    for i in range(2, 11):
        row = []
        for j in range(1, i):
            k = key(i, j)
            row.append(t.get(k, '0'))
        a.append(row)
    b = [t.get(f'b{j}', '0') for j in range(1, 11)]
    btilde = [t.get(f'btilde{j}', '0') for j in range(1, 11)]
    # The six extra stages the interpolant needs, 11..16, computed only when a
    # point inside the step is asked for. Row 11 has entries against stages
    # 1..9, rows 12..16 against 1..9 and 11..(i-1); stage 10 is never used.
    xc = [x[f'c{i}'] for i in range(11, 17)]
    xa = []
    for i in range(11, 17):
        row = [x.get(f'a{i}0{j}', '0') for j in range(1, 10)]
        row.append('0')                                      # against stage 10
        row += [x.get(f'a{i}{j}', '0') for j in range(11, i)]
        xa.append(row)
    # b_jΘ = Θ·(r011 + r012Θ + … + r017Θ⁶) for j = 1, Θ²·(rj2 + … + rj7Θ⁵)
    # for j in 4..9 and 11..16; the stages 2, 3 and 10 do not appear.
    interp_stages = [1, 4, 5, 6, 7, 8, 9, 11, 12, 13, 14, 15, 16]
    interp = []
    for j in interp_stages:
        if j == 1:
            interp.append([r[f'r01{m}'] for m in range(1, 8)])
        else:
            pre = f'r0{j}' if j < 10 else f'r{j}'
            interp.append([r[f'{pre}{m}'] for m in range(2, 8)])

    for i in range(1, 10):
        s = sum(num(v) for v in a[i])
        require(abs(s - num(c[i])) <= 1e-13 * max(1.0, max(abs(num(v)) for v in a[i])),
                f'Vern7 row {i + 1} of a sums to {s!r}, not c = {c[i]}')
    for i in range(6):
        s = sum(num(v) for v in xa[i])
        require(abs(s - num(xc[i])) <= 1e-13 * max(1.0, max(abs(num(v)) for v in xa[i])),
                f'Vern7 extra stage {i + 11} sums to {s!r}, not c = {xc[i]}')
    require(abs(sum(num(v) for v in b) - 1) <= 1e-14, 'Vern7 b does not sum to one')
    require(abs(sum(num(v) for v in btilde)) <= 1e-14, 'Vern7 btilde does not sum to zero')
    # Stage 11 is the solution itself (c11 = 1, its row is b), which is what lets
    # the interpolant end on the step's own value.
    require(all(abs(num(xa[0][j]) - num(b[j])) <= 1e-15 for j in range(9)),
            'Vern7 extra stage 11 is not the solution')
    for j, stage in enumerate(interp_stages):
        at1 = poly_at_one(interp[j])
        want = num(b[stage - 1]) if stage <= 10 else 0.0
        require(abs(at1 - want) <= 1e-11 * max(1.0, max(abs(num(v)) for v in interp[j])),
                f'Vern7 interpolant for stage {stage} is {at1!r} at θ = 1, not {want!r}')

    rows = ',\n'.join('    [' + ', '.join(js(v) for v in row) + ']' for row in a)
    xrows = ',\n'.join('    [' + ', '.join(js(v) for v in row) + ']' for row in xa)
    irows = ',\n'.join('    [' + ', '.join(js(v) for v in row) + ']' for row in interp)
    return f'''/* ==========================================================================
   ode_julia / solvers / vern7-tableau

   GENERATED -- do not edit by hand.
   Written by scripts/gen-explicit-rk-tableaus.py from the Float64 methods of
   Vern7Tableau, Vern7ExtraStages and Vern7InterpolationCoefficients in
   OrdinaryDiffEqVerner/src/verner_tableaus.jl.

   Vern7: Verner's "most efficient" 7(6) pair, ten stages, not first same as
   last, with a seventh-order interpolant that needs six more stages -- worked
   out only when a point inside the step is asked for ("lazy").

     Verner, J. H. (2010). Numerically optimal Runge-Kutta pairs with
     interpolants. Numerical Algorithms 53, 383-396.

   Shapes. `a` is strictly lower triangular and ragged: row i has i entries
   (zeros where the source has none). `extraA[m]` is stage 11 + m against
   stages 1..10 and then 11..(10 + m); its entry against stage 10 is zero.
   `interpStages` lists which stages the interpolant reads (1-based, as in the
   source), and `interp` their polynomials: the first is
   Θ·(r011 + r012·Θ + … + r017·Θ⁶), every other Θ²·(rj2 + … + rj7·Θ⁵).
   ========================================================================== */

export const Vern7Tableau = {{
  name: 'Vern7',
  stages: 10,
  order: 7,
  errorOrder: 6,
  // alg_stability_size in OrdinaryDiffEqVerner/src/alg_utils.jl.
  stabilitySize: 4.64,
  c: [{', '.join(js(v) for v in c)}],
  a: [
{rows},
  ],
  b: [{', '.join(js(v) for v in b)}],
  btilde: [{', '.join(js(v) for v in btilde)}],
  extraC: [{', '.join(js(v) for v in xc)}],
  extraA: [
{xrows},
  ],
  interpStages: [{', '.join(str(s) for s in interp_stages)}],
  interp: [
{irows},
  ],
}};
'''


def main() -> int:
    OUT_TSIT5.write_text(tsit5())
    print(f'wrote {OUT_TSIT5}')
    OUT_VERN7.write_text(vern7())
    print(f'wrote {OUT_VERN7}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
