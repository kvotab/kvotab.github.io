#!/usr/bin/env python3
"""Emit resources/js/ode_julia/solvers/rodas5p-tableau.js from the Julia source.

The coefficients are read out of OrdinaryDiffEq.jl's rosenbrock_tableaus.jl as
raw text tokens and spliced into JavaScript without ever being retyped, because
one wrong digit in a Rosenbrock tableau costs the method its order and says
nothing about it: the solver still runs, still reports converged steps, and is
quietly second order.

    python3 scripts/gen-rodas5p-tableau.py [path/to/rosenbrock_tableaus.jl]

With no argument it downloads the file from the SciML repository.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

URL = ('https://raw.githubusercontent.com/SciML/OrdinaryDiffEq.jl/master/'
       'lib/OrdinaryDiffEqRosenbrock/src/rosenbrock_tableaus.jl')
OUT = Path(__file__).resolve().parent.parent / 'resources/js/ode_julia/solvers/rodas5p-tableau.js'


def source() -> str:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).read_text()
    return subprocess.run(['curl', '-sS', URL], capture_output=True, text=True, check=True).stdout


def block(text: str, name: str) -> list[list[str]]:
    """The rows of `const <name> = [ ... ]`, as raw tokens."""
    m = re.search(rf'const {name} = \[(.*?)\n\]', text, re.S)
    if not m:
        raise SystemExit(f'{name} not found')
    rows = []
    for line in m.group(1).strip().splitlines():
        line = line.strip().rstrip(',')
        if not line:
            continue
        rows.append([tok for tok in re.split(r'[,\s]+', line) if tok])
    return rows


def lower(rows):
    """Strictly lower triangular, ragged: row i keeps its first i tokens."""
    return [row[:i] for i, row in enumerate(rows)]


def flat(rows):
    return [tok for row in rows for tok in row]


def js_rows(rows, indent='    '):
    body = ',\n'.join(indent + '[' + ', '.join(r) + ']' for r in rows)
    return '[\n' + body + ',\n  ]'


def main() -> int:
    text = source()
    A = block(text, 'RODAS5PA')
    C = block(text, 'RODAS5PC')
    c = flat(block(text, 'RODAS5Pc'))
    d = flat(block(text, 'RODAS5Pd'))
    H = block(text, 'RODAS5PH')

    gm = re.search(r'function Rodas5PTableau.*?gamma = ([0-9.eE+-]+)', text, re.S)
    if not gm:
        raise SystemExit('gamma not found')
    gamma = gm.group(1)

    s = len(A)
    if s != 8 or len(c) != 8 or len(d) != 8 or len(H) != 3:
        raise SystemExit(f'unexpected shape: A {s}, c {len(c)}, d {len(d)}, H {len(H)}')
    # RODAS5PC is 8 rows of 7 columns; the strict lower triangle is what is used.
    b = A[s - 1][:s - 1] + ['1.0']
    btilde = ['0.0'] * (s - 1) + ['1.0']

    # Invariants that hold for Rodas5P and would not survive a mangled parse.
    if float(d[0]) != float(gamma):
        raise SystemExit('d[1] should equal gamma')
    if abs(float(c[1]) - 3 * float(gamma)) > 1e-15:
        raise SystemExit('c[2] should be 3*gamma')

    OUT.write_text(f'''/* ==========================================================================
   ode_julia / solvers / rodas5p-tableau

   GENERATED -- do not edit by hand.
   Written by scripts/gen-rodas5p-tableau.py from the coefficients in
   OrdinaryDiffEqRosenbrock/src/rosenbrock_tableaus.jl (RODAS5PA, RODAS5PC,
   RODAS5Pc, RODAS5Pd, RODAS5PH).

   Rodas5P: a 5th-order L-stable Rosenbrock-Wanner method in 8 stages, stiffly
   accurate, with a 4th-order embedded estimate and a 3rd-order dense output.

     Steinebach, G. (2023). Construction of Rosenbrock-Wanner method Rodas5P
     and numerical benchmarks within the Julia DifferentialEquations package.
     BIT Numerical Mathematics 63, 27.

   Shapes. `a` and `C` are strictly lower triangular and ragged: row i has
   exactly i entries, so row 0 is empty. `H` is 3x8 and produces the three
   vectors the interpolant is written in. `b` is row 8 of A with a trailing 1,
   which is what makes the method stiffly accurate: the solution is the last
   stage value plus its own increment. `btilde` is the eighth unit vector, so
   the error estimate is simply k8.
   ========================================================================== */

export const Rodas5PTableau = {{
  name: 'Rodas5P',
  stages: {s},
  order: 5,
  errorOrder: 4,
  interpOrder: 3,
  gamma: {gamma},
  a: {js_rows(lower(A))},
  C: {js_rows(lower(C))},
  c: [{', '.join(c)}],
  d: [{', '.join(d)}],
  b: [{', '.join(b)}],
  btilde: [{', '.join(btilde)}],
  H: {js_rows(H)},
}};
''')
    print(f'wrote {OUT}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
