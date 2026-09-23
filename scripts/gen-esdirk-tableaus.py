#!/usr/bin/env python3
"""Emit resources/js/ode/julia/solvers/esdirk-tableaus.js from a transcription
of OrdinaryDiffEqSDIRK's TRBDF2 and KenCarp4 tableaux.

    python3 scripts/gen-esdirk-tableaus.py path/to/esdirk.json

The JSON is the machine-checked transcription of `TRBDF2Tableau`
(sdirk_tableaus.jl) and `KenCarp4ESDIRKIMEXTableau` (imex_tableaus.jl); see
resources/tests/ode/julia/README.md for how it was made and checked.
"""
import json
import sys
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / 'resources/js/ode/julia/solvers/esdirk-tableaus.js'


def rows(m, indent='    '):
    return '[\n' + ',\n'.join(indent + '[' + ', '.join(repr(float(v)) for v in r) + ']'
                              for r in m) + ',\n  ]'


def vec(v):
    return '[' + ', '.join(repr(float(x)) for x in v) + ']'


def alpha_matrix(alpha, s):
    """The Newton seed weights, as a ragged lower-triangular matrix."""
    m = [[0.0] * i for i in range(s)]
    for key, val in alpha.items():
        # keys are like 'a31': stage 3 seeded from stage 1 (both 1-based)
        digits = key[1:]
        i = int(digits[0]) - 1
        j = int(digits[1]) - 1
        m[i][j] = float(val)
    return m


def check(name, tab):
    s = tab['stages']
    a = tab['a']
    c = tab['c']
    b = tab['b']
    for i in range(s):
        if abs(sum(a[i]) - c[i]) > 1e-14 * max(1.0, abs(c[i])):
            raise SystemExit(f'{name}: row {i} of a sums to {sum(a[i])}, not c[{i}] = {c[i]}')
    if abs(sum(b) - 1) > 1e-14:
        raise SystemExit(f'{name}: b sums to {sum(b)}, not 1')
    if abs(sum(tab['btilde'])) > 1e-13:
        raise SystemExit(f'{name}: btilde sums to {sum(tab["btilde"])}, not 0')
    for i in range(1, s):
        if abs(a[i][i] - tab['gamma']) > 1e-15:
            raise SystemExit(f'{name}: a[{i}][{i}] is not gamma')
    if a[0][0] != 0:
        raise SystemExit(f'{name}: a[0][0] should be 0 for an ESDIRK')


def main():
    src = json.load(open(sys.argv[1]))
    for name in ('TRBDF2', 'KenCarp4'):
        check(name, src[name])

    def block(name, order, error_order):
        t = src[name]
        s = t['stages']
        return f'''export const {name}Tableau = {{
  name: '{name}',
  stages: {s},
  order: {order},
  errorOrder: {error_order},
  gamma: {float(t['gamma'])!r},
  a: {rows(t['a'])},
  b: {vec(t['b'])},
  btilde: {vec(t['btilde'])},
  c: {vec(t['c'])},
  alpha: {rows(alpha_matrix(t.get('alpha', {}), s))},
  stifflyAccurate: {str(bool(t.get('stifflyAccurate'))).lower()},
}};'''

    OUT.write_text(f'''/* ==========================================================================
   ode_julia / solvers / esdirk-tableaus

   GENERATED -- do not edit by hand.
   Written by scripts/gen-esdirk-tableaus.py from a checked transcription of
   OrdinaryDiffEqSDIRK's TRBDF2Tableau (sdirk_tableaus.jl) and
   KenCarp4ESDIRKIMEXTableau (imex_tableaus.jl, the one the solver actually
   uses -- a second, unreferenced KenCarp4Tableau exists in sdirk_tableaus.jl
   and differs in one Newton-seed coefficient).

   Both are ESDIRK: the first stage is explicit (a[0][0] = 0), every later
   stage has the same diagonal gamma, and both are stiffly accurate, so the
   solution is the last stage value and f at the end of the step comes free.

   `a` is the full lower triangle INCLUDING the diagonal. `alpha` holds the
   weights that seed each stage's Newton iterate from the stages already
   solved; they cost nothing and save an iteration or two per stage.

   TRBDF2: 2nd order, 3 stages. A trapezoidal half-step followed by a BDF2
     half-step, so that both halves reuse one factorisation.
     Hosea & Shampine (1996), Applied Numerical Mathematics 20, 21-37.

   KenCarp4: 4th order, 6 stages. The implicit half of the additive
     ARK4(3)6L[2]SA pair; used here on its own.
     Kennedy & Carpenter (2003), Applied Numerical Mathematics 44, 139-181.

   The generator checks, and refuses to write, unless every row of `a` sums to
   its `c`, `b` sums to 1, `btilde` sums to 0 and the diagonal is constant.
   ========================================================================== */

{block('TRBDF2', 2, 2)}

{block('KenCarp4', 4, 3)}
''')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
