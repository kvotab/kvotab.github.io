#!/usr/bin/env python3
"""Emit resources/js/ode/julia/solvers/radau-tableau.js from the Julia source.

    python3 scripts/gen-radau-tableau.py [path/to/firk_tableaus.jl]

The T and T-inverse entries are decimal literals in the Julia and are copied
token for token. Everything else (c1, c2, the eigenvalues gamma/alpha/beta of
the inverse Butcher matrix, and the error weights) is closed form there and is
recomputed here from the same expressions in exact arithmetic, then checked
against the identities the tableau must satisfy.
"""
import re
import subprocess
import sys
from decimal import Decimal, getcontext
from pathlib import Path

getcontext().prec = 40
URL = ('https://raw.githubusercontent.com/SciML/OrdinaryDiffEq.jl/master/'
       'lib/OrdinaryDiffEqFIRK/src/firk_tableaus.jl')
OUT = Path(__file__).resolve().parent.parent / 'resources/js/ode/julia/solvers/radau-tableau.js'


def source():
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).read_text()
    return subprocess.run(['curl', '-sS', URL], capture_output=True, text=True, check=True).stdout


def main():
    text = source()
    m = re.search(r'function RadauIIA5Tableau\(.*?\n(.*?)\nend', text, re.S)
    if not m:
        raise SystemExit('RadauIIA5Tableau not found')
    body = m.group(1)

    names = ['T11', 'T12', 'T13', 'T21', 'T22', 'T23', 'T31',
             'TI11', 'TI12', 'TI13', 'TI21', 'TI22', 'TI23', 'TI31', 'TI32', 'TI33']
    vals = {}
    for nm in names:
        mm = re.search(rf'\b{nm} = convert\(T, ([^)]+)\)', body)
        if not mm:
            raise SystemExit(f'{nm} not found')
        vals[nm] = mm.group(1).strip()

    # Closed forms, exactly as the Julia writes them.
    s6 = 6 ** 0.5
    c1 = (4 - s6) / 10
    c2 = (4 + s6) / 10
    cbrt9 = 9 ** (1 / 3)
    gp = (6.0 + cbrt9 * (cbrt9 - 1)) / 30
    ap = (12.0 - cbrt9 * (cbrt9 - 1)) / 60
    bp = cbrt9 * (cbrt9 + 1) * (3 ** 0.5) / 60
    scale = ap * ap + bp * bp
    gamma = 1 / gp
    alpha = ap / scale
    beta = bp / scale
    e1 = -(13 + 7 * s6) / 3
    e2 = (-13 + 7 * s6) / 3
    e3 = -1 / 3

    # For an s-stage Radau IIA matrix, trace(inv(A)) = s^2 -- here 9. The three
    # eigenvalues are gamma and alpha +/- i*beta, so their sum is gamma + 2*alpha
    # and must be 9. A mistyped closed form above fails this.
    trace = gamma + 2 * alpha
    if abs(trace - 9) > 1e-12:
        raise SystemExit(f'eigenvalue trace {trace} is not 9; a closed form is wrong')
    # c1 and c2 are the two non-unit Radau points; they and c3 = 1 are the roots
    # of the Radau quadrature, whose sum for s = 3 is 9/5.
    if abs((c1 + c2 + 1) - 1.8) > 1e-14:
        raise SystemExit(f'the abscissae sum to {c1 + c2 + 1}, not 9/5')
    # T32 and T33 are 1 and 0 by the normalisation Hairer uses; the Julia
    # relies on that rather than storing them.
    # Matched on the assignment form only: the source carries `#= T33 = 0 =#`
    # as a comment, and a looser pattern reads that as a definition.
    body_defines = set(re.findall(r'\b(T3[23]) = convert\(', body))
    if body_defines:
        raise SystemExit(f'the source now stores {body_defines}; the generator assumes it does not')

    def num(x):
        return repr(float(x))

    lines = '\n'.join(f'  {k}: {v},' for k, v in vals.items())
    OUT.write_text(f'''/* ==========================================================================
   ode_julia / solvers / radau-tableau

   GENERATED -- do not edit by hand.
   Written by scripts/gen-radau-tableau.py from RadauIIA5Tableau in
   OrdinaryDiffEqFIRK/src/firk_tableaus.jl.

   The three-stage Radau IIA collocation method, order 5, L-stable, stiffly
   accurate. Hairer & Wanner, Solving ODEs II, section IV.8.

   T and TI are the change of basis that diagonalises the inverse of the
   Butcher matrix; gamma is its real eigenvalue and alpha +/- i*beta the
   complex pair. T32 = 1 and T33 = 0 by Hairer's normalisation and are not
   stored -- the step writes them in. c3 = 1, which is what makes the method
   stiffly accurate. e1, e2, e3 weight the stages in the error estimate.
   ========================================================================== */

export const RadauIIA5Tableau = {{
  name: 'RadauIIA5',
  stages: 3,
  order: 5,
  errorOrder: 3,
{lines}
  c1: {num(c1)},
  c2: {num(c2)},
  c3: 1,
  gamma: {num(gamma)},
  alpha: {num(alpha)},
  beta: {num(beta)},
  e1: {num(e1)},
  e2: {num(e2)},
  e3: {num(e3)},
}};
''')
    print(f'wrote {OUT}')


if __name__ == '__main__':
    main()
