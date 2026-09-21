#!/usr/bin/env python3
"""Writes resources/js/rtm-examples.js: the models the page offers to load.

Two kinds. Most are written out below, each chosen to show one thing the model
text can do and, wherever there is one, to have an answer that can be checked
against something other than this code. The rest are the twenty HS_case
databases of BRUM_for_Hydrosäk, converted by the same reader that
resources/tests/rtm/verify-brum.py uses, so that what the page offers and what
the tests check are the same conversion.

    python3 scripts/gen-rtm-examples.py [--brum PATH]

The Hydrosäk set is not in this repository. Without it the script writes the
rest and says how many it left out; with it, all of them. Twenty near-identical
reaction sets are 150 kB of text and about 8 kB once served gzipped, which is
why they are embedded rather than fetched: a page opened from a disk can still
load them.
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / 'resources/js/rtm-examples.js'
DEFAULT_BRUM = Path('~/Downloads/Nuclear_fuel_dissolution/BRUM_for_Hydrosäk')

# The reader for the BRUM .in files lives with the test that checks against
# them; importing it rather than copying it keeps one definition of what those
# files mean.
sys.path.insert(0, str(ROOT / 'resources/tests/rtm'))


def brum_reader():
    src = (ROOT / 'resources/tests/rtm/verify-brum.py').read_text().split('def main()')[0]
    ns = {'__file__': str(ROOT / 'resources/tests/rtm/verify-brum.py')}
    exec(compile(src, 'verify-brum', 'exec'), ns)  # noqa: S102 - our own file
    return ns


# ---------------------------------------------------------------------------
# The written examples
# ---------------------------------------------------------------------------
EXAMPLES = [
    dict(
        id='ab', group='Getting started', label='A → B → C',
        about='The smallest thing that runs: three species, two first-order steps, one stirred '
              'cell. B rises and falls; the three always add up to one.',
        text='''\
# The smallest model that does anything: A decays to B, B to C.
# Everything after a # is a comment.

<SETTINGS>
MODE = batch          # one stirred cell, no transport
TEND = 20             # how long to integrate, in the unit below
TIME_UNIT = second

<SPECIES>
A  1.0                # name, then the concentration it starts at
B  0.0
C  0.0

<REACTIONS>
A => B, k = 0.5       # mass action: the rate is k times A
B => C, k = 0.2
''',
    ),
    dict(
        id='mm', group='Getting started', label='Michaelis–Menten',
        about='A rate law of your own rather than mass action: v_max·S/(K_m + S), with the '
              'constants named on the line. Shows the r = form and [S] for a concentration.',
        text='''\
# A rate law written out, instead of mass action.
#
# With k = the rate is k times each reactant raised to its coefficient. With
# r = you write the rate yourself, and a concentration goes in brackets so
# that a name like H+ is never read as arithmetic.

<SETTINGS>
MODE = batch
TEND = 400
TIME_UNIT = second

<SPECIES>
S  1.0E-3             # substrate
P  0.0                # product

<REACTIONS>
S => P, r = vmax*[S]/(km + [S]), vmax = 1.0E-5, km = 2.0E-4
''',
    ),
    dict(
        id='robertson', group='Standard test cases', label='Robertson (1966), stiff kinetics',
        about='The test case stiff solvers are measured against: three rate constants spanning '
              'nine orders, and A + B + C exactly 1 for all time. At t = 0.4 the published '
              'answer is 0.9851721, 3.3864e-5, 0.0147939 — this page gives it to seven figures.',
        reference='H. H. Robertson, "The solution of a set of reaction rate equations", in '
                  'J. Walsh (ed.), Numerical Analysis: An Introduction, Academic Press (1966). '
                  'Used as the stiff benchmark by Hairer & Wanner and by every ODE suite since.',
        text='''\
# Robertson's problem, the classic test of a stiff solver.
#
#   A       -> B         k1 = 0.04
#   B + B   -> C + B     k2 = 3e7      (B is consumed and remade: a catalyst)
#   B + C   -> A + C     k3 = 1e4
#
# A + B + C is exactly 1 for all time, which is the first thing to check: at
# a tight tolerance this page holds it to 3e-15. B rises to 3.65e-5 within the
# first hundredth of a second and then falls away for ever.
#
# The point everyone quotes is t = 0.4, where the answer is
#     A = 0.9851721   B = 3.3864e-5   C = 0.0147939
# Tick all three species, set the time axis to log, and read it off.

<SETTINGS>
MODE = batch
TEND = 1.0E7
TIME_UNIT = second

<SPECIES>
A  1.0
B  0.0
C  0.0

<REACTIONS>
A => B, k = 0.04
B + B => C + B, k = 3.0E7
B + C => A + C, k = 1.0E4
''',
    ),
    dict(
        id='brusselator', group='Standard test cases', label='Brusselator, an oscillator',
        about='A reaction set that does not settle: X and Y go round a limit cycle for ever. '
              'Worth drawing with a linear time axis rather than a log one.',
        reference='Prigogine and Lefever (1968). The parameters here are the usual A = 1, B = 3, '
                  'which is past the Hopf bifurcation at B = 1 + A².',
        text='''\
# The Brusselator: an autocatalytic set with a limit cycle.
#
# A and B are held (fixed), so the set never runs down. With B = 3 > 1 + A²
# the steady state is unstable and X and Y circle it for ever.
#
# Turn the log time axis OFF to see the oscillation.

<SETTINGS>
MODE = batch
TEND = 60
TIME_UNIT = second

<SPECIES>
A  1.0  fixed         # fixed: drives the rates, never changes
B  3.0  fixed
X  1.0
Y  1.0

<REACTIONS>
A => X, k = 1.0                   # X made from the reservoir
B + X => Y, k = 1.0               # and turned into Y
X + X + Y => X + X + X, k = 1.0   # the autocatalytic step
X => , k = 1.0                    # X leaves
''',
    ),
    dict(
        id='carbonate', group='Chemistry', label='Carbonate speciation',
        about='Three coupled equilibria solved before the run: pH, the carbonate system, and the '
              'conserved totals worked out from the stoichiometry alone.',
        text='''\
# Equilibria rather than rates.
#
# EQUILIBRATE = 1 puts the starting concentrations on these relations before
# anything is integrated: a damped Newton iteration in ln C. What it may not
# change is worked out from the relations themselves -- total carbon and
# charge here -- so no table of elements is needed.
#
# Compile this and the panel reports the conserved totals. The starting
# numbers below are deliberately nowhere near equilibrium.

<SETTINGS>
MODE = batch
TEND = 1
TIME_UNIT = second
EQUILIBRATE = 1

<SPECIES>
H+      1.0E-7
OH-     1.0E-7
CO2     1.0E-3
HCO3-   1.0E-5
CO3-2   1.0E-9

<EQUILIBRIUM>
 <=> H+ + OH-,          logK = -14      # water; nothing on the left
CO2 <=> H+ + HCO3-,     logK = -6.35
HCO3- <=> H+ + CO3-2,   logK = -10.33
''',
    ),
    dict(
        id='tracer', group='Transport', label='Tracer in a column',
        about='Advection and dispersion along a column, against the Ogata–Banks solution. The '
              'upwind scheme adds v·Δx/2 of dispersion of its own, which is what the warning '
              'about the grid is for: halve the cells and watch it appear.',
        text='''\
# A tracer entering a column of flowing water.
#
# LEFT = dirichlet holds the face at the concentration on the species line;
# the front then travels at the pore velocity and spreads by D.
#
# The answer is Ogata and Banks (1961), with D + v*dx/2 rather than D --
# first-order upwinding disperses on its own, and the page says so when that
# part gets large. Try CELLS = 20 and read the warning.

<SETTINGS>
MODE = transport
CELLS = 400
LENGTH = 1.0
GRID = linear
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1.0E-6     # m/s, positive left to right
POROSITY = 1
LEFT = dirichlet
RIGHT = neumann
TEND = 3.0E5
TIME_UNIT = second

<SPECIES>
X  0.0  D=2.0E-8  left=1.0

<REACTIONS>
''',
    ),
    dict(
        id='danckwerts', group='Transport', label='Danckwerts inlet and free exit',
        about='The third-type inlet: the flow carries the concentration in and nothing else '
              'crosses. The column then balances exactly — what goes in less what leaves is all '
              'that changes the mass in it, to one part in 10^15.',
        text='''\
# The four kinds of face, and why the inlet matters.
#
#   robin (cauchy)  the flow carries left= in and NOTHING else crosses:
#                   the whole flux through the face is u*c. Danckwerts' inlet.
#   free (outflow)  zero gradient; the flow takes what it takes.
#   dirichlet       the face HELD at left=, which adds a diffusive flux on top
#                   of what the water brings -- more goes in than the flow
#                   carries, and the column's mass balance does not close.
#   neumann         nothing crosses.
#
# Switch LEFT to dirichlet and compare the profiles at the same time.

<SETTINGS>
MODE = transport
CELLS = 40
LENGTH = 1.0
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1.0E-6
LEFT = robin
RIGHT = free
TEND = 2.0E6
TIME_UNIT = second

<SPECIES>
X  0.0  D=2.0E-7  left=1.0

<REACTIONS>
''',
    ),
    dict(
        id='retarded', group='Transport', label='Sorption: a retarded front',
        about='R = on a species line is the coefficient on the left of R·dC/dt = …: a retardation '
              'factor. R = 4 makes the front travel at a quarter of the water speed, and slows '
              'the reactions by the same factor.',
        text='''\
# Sorption as a retardation factor.
#
# R= (or mass=) divides everything that happens to a species, transport and
# reactions alike. Y has R = 4 and so travels at a quarter of X's speed.
# It may also name a parameter, which is how it varies down a column.

<SETTINGS>
MODE = transport
CELLS = 200
LENGTH = 1.0
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1.0E-6
LEFT = robin
RIGHT = free
TEND = 6.0E5
TIME_UNIT = second

<SPECIES>
X  0.0  D=2.0E-8  left=1.0          # unretarded
Y  0.0  D=2.0E-8  left=1.0  R=4     # four times slower

<REACTIONS>
''',
    ),
    dict(
        id='doseprofile', group='Transport', label='A source that varies down the column',
        about='<PARAMETERS> gives a named number that may differ from cell to cell — here a dose '
              'rate dying away from a surface over the range of an alpha particle. The '
              'expression may use x, the cell centre in metres.',
        text='''\
# A parameter that varies with position.
#
# The value is an expression in x (the cell centre, in metres), i (the cell
# index) and any parameter named above it, worked out once when the model
# compiles. This is how a dose rate that dies away from a surface is written,
# or a porosity that changes down a column, or a rate constant following a
# temperature.

<SETTINGS>
MODE = transport
CELLS = 40
LENGTH = 1.0E-4
DIFFUSION = 1
LEFT = neumann
RIGHT = neumann
TEND = 100
TIME_UNIT = second

<SPECIES>
P  0.0  D=1.0E-9

<PARAMETERS>
DOSE  all  0.64*exp(-x/3.0E-5)    # Gy/s, falling over the alpha range

<REACTIONS>
=> P, k = G*DOSE, G = 1.0E-7      # G in mol/J times the dose rate
''',
    ),
    dict(
        id='matrixtracer', group='Dual porosity', label='Matrix diffusion: a tracer',
        about='A fracture beside porous rock. The breakthrough is held back by diffusion into the '
              'stagnant pore water, and follows the erfc solution for a semi-infinite matrix.',
        text='''\
# Dual porosity: water flows along a fracture, the rock beside it is stagnant.
#
# Every cell of the column gets MATRIX_CELLS stagnant cells behind it, reaching
# MATRIX_DEPTH into the rock. The layers grow geometrically from the wall,
# because the gradient is steepest there.
#
# WETTED_SURFACE is the rock surface a cubic metre of flowing water touches;
# APERTURE (2b) says the same thing as 2/aperture.
#
# The breakthrough at the far end follows
#     c/c0 = erfc( aw*tw*sqrt(De*Rm) / (2*sqrt(t - tw)) )
# with tw the water travel time -- to within 0.01 on this grid, and better on
# a finer one. Set MATRIX_CELLS = 0 and the tracer arrives at once instead.

<SETTINGS>
MODE = transport
CELLS = 100
LENGTH = 20            # m; with VELOCITY = 1 the travel time is 20
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1
LEFT = robin
RIGHT = free
MATRIX_CELLS = 40
MATRIX_DEPTH = 60      # m: deep enough to be infinite over this run
MATRIX_FIRST = 1.0E-5  # m at the wall; 0 has it worked out
MATRIX_POROSITY = 0.0018
WETTED_SURFACE = 500   # m2 of wall per m3 of water
TEND = 120
TIME_UNIT = second

<SPECIES>
X  0.0  D=0  left=1.0  Dm=1.0E-3    # Dm: the effective diffusivity in the rock

<REACTIONS>
''',
    ),
    dict(
        id='u238chain', group='Dual porosity',
        label='U-238 chain in a fracture (SKB TR-19-06)',
        about='Six radionuclides decaying into one another while diffusing into the rock and '
              'sorbing there, along a real flow path. Decay is written on = inventory, because it '
              'removes sorbed atoms as readily as dissolved ones.',
        reference='SKB TR-19-06, Appendix B: Table B-2 (nuclide data) and the representative '
                  'trajectory of Figure B-6 — travel time 235.2 a, F = 80 090 a/m, length '
                  '2 237 m, matrix porosity 0.0019, bulk density 2 700 kg/m³, penetration depth '
                  '4.5 m, Peclet number 10.',
        text='''\
# The U-238 chain along a fracture in rock, with matrix diffusion.
#
# Everything here is per YEAR: half-lives, diffusivities in m2/a, the travel
# time. TIME_UNIT = year tells the page so; it converts nothing.
#
# The flow path is the representative trajectory of SKB TR-19-06 Appendix B:
# 2237 m travelled in 235.2 a, so v = 9.511 m/a, and a transport resistance
# F = 80 090 a/m, which is the wall area per unit volume of water times the
# travel time: aw = F/tw = 340.5 m2/m3.
#
# Rm is the rock's capacity for a nuclide, eps_m + rho*Kd, with eps_m = 0.0019
# and rho = 2700 kg/m3. It is what holds the sorbing members of the chain back
# by thousands of years.
#
# DECAY IS on = inventory. A rate law is per unit pore water, and a cubic metre
# of rock holds only eps_m of water -- right for chemistry, wrong for decay,
# which takes the sorbed atoms too. Written as on = water instead, the sorbing
# nuclides would decay at eps_m/Rm of their real rate.

<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 2237          # m
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 9.5110      # m/a: 2237 m in 235.2 a
POROSITY = 1
PECLET = 10
LEFT = robin
RIGHT = free
MATRIX_CELLS = 20
MATRIX_DEPTH = 4.5     # m
MATRIX_POROSITY = 0.0019
WETTED_SURFACE = 340.5 # m2/m3 = F / tw = 80090 / 235.2
TEND = 1.0E6           # a
TIME_UNIT = year

<SPECIES>
#          start  De (m2/a)   Rm = eps + rho*Kd
U238   0  Dm=2.7E-7  Rm=0.5419    # Kd 2.0E-4 m3/kg
U234   0  Dm=2.7E-7  Rm=0.5419    # Kd 2.0E-4
Th230  0  Dm=2.7E-7  Rm=143.1     # Kd 5.3E-2
Ra226  0  Dm=8.5E-7  Rm=1.2169    # Kd 4.5E-4
Pb210  0  Dm=8.5E-7  Rm=67.5      # Kd 2.5E-2
Po210  0  Dm=2.7E-7  Rm=67.5      # Kd 2.5E-2

<PARAMETERS>
# A unit release of U-238 into the first cell: 1 Bq/a over its water volume.
SRC  all  0
SRC  0    0.0089405  fracture      # = 1 / (LENGTH/CELLS) / 1 m2

<REACTIONS>
=> U238, k = SRC

# The chain. Half-lives in years; every one acts on the whole inventory.
U238  => U234,  k = 1.5513E-10, on = inventory   # 4.468e9 a
U234  => Th230, k = 2.8234E-6,  on = inventory   # 245 500 a
Th230 => Ra226, k = 9.1946E-6,  on = inventory   # 75 386 a
Ra226 => Pb210, k = 4.3322E-4,  on = inventory   # 1 600 a
Pb210 => Po210, k = 3.1083E-2,  on = inventory   # 22.3 a
Po210 => ,      k = 1.8289E+0,  on = inventory   # 0.379 a
''',
    ),
]


def hs_examples(root, ns):
    """The twenty HS_case databases, as model text."""
    out = []
    cases = sorted((d for d in root.glob('HS_case*') if d.is_dir()), key=lambda d: int(d.name[7:]))
    for d in cases:
        n = int(d.name[7:])
        text, tend = ns['convert'](d)
        # What makes this case different from the others: how much of each kind
        # of surface site it starts with. Taken from the concentrations
        # themselves rather than from the files' own "# 1%" comments, which
        # three of the twenty do not carry -- so those three came out labelled
        # "the reference parameterisation" and indistinguishable.
        initial, _ = ns['read_solutions'](d / 'databases/solutions.in')
        base = 2.1e-4 * 1 / 4e-5 * 1e-3      # sites_per_m2*surface/thickness*m3_to_L
        marks = []
        for name, short in (('U_site', 'U sites'), ('E_site', 'E sites'),
                            ('UVO2s+', 'U(V)'), ('UVIO2s+2', 'U(VI)')):
            v = initial.get(name)
            if not v:
                continue
            pct = 100 * v / base
            marks.append(f'{short} {pct:g}%')
        # ...and how its mechanism differs, where it does. Five of the twenty
        # replace the two-step reduction of U(VI) by H2 -- through the
        # intermediate `red` -- with a single Langmuir-Hinshelwood step, or
        # drop a step, and two of those name a species their rate law does not
        # use. Without this, cases with the same starting inventory and
        # different chemistry read as the same case.
        rx = (d / 'databases/reaction.in').read_text()
        live = [ln.strip() for ln in rx.splitlines()
                if ln.strip() and not ln.strip().startswith('#')]
        lh = [ln for ln in live if 'E_site + H2 +' in ln]
        mech = None
        if lh:
            consumed = re.match(r'E_site \+ H2 \+ (\S+)', lh[0])
            used = re.search(r'r = k\*\[(\S+?)\]', lh[0])
            c, u = consumed.group(1), used.group(1)
            mech = ('one-step reduction of ' + c
                    + ('' if c == u else f', rate law on [{u}]'))
        elif not any('UO2CO3 + H2 + E_site' in ln for ln in live):
            mech = 'no reduction of the carbonate complex'
        variant = ', '.join(marks) if marks else 'the reference parameterisation'
        if mech:
            variant += f' — {mech}'
        # HS_case20's own database names UVIO2s+ in a stoichiometry whose rate
        # law reads [UVIO2s+2]. They are different species and the first
        # appears nowhere else, so it is driven below zero -- BRUM's own stored
        # answer for it is -2.55e-8. Said here rather than left to be found
        # when the run will not start.
        broken = ''
        if any('UVIO2s+ ' in f'{m} ' for m in [(d / 'databases/reaction.in').read_text()]) \
                and 'E_site + H2 + UVIO2s+ =>' in (d / 'databases/reaction.in').read_text():
            broken = (
                '#\n'
                '# NOTE. This case\'s own database has a typo: the last reaction consumes\n'
                '# UVIO2s+ while its rate law reads [UVIO2s+2]. Those are different species,\n'
                '# and UVIO2s+ appears nowhere else, so nothing replaces what is taken and it\n'
                '# is driven below zero. BRUM\'s own answer for it is negative too.\n'
                '#\n'
                '# So this one will not run until "keep concentrations non-negative" is turned\n'
                '# OFF under Solver -> advanced. With it off, this page reproduces BRUM\'s\n'
                '# result for the case, negative species and all.\n')
        head = (f'# HS_case{n} of BRUM_for_Hydrosäk: spent-fuel dissolution in one stirred cell,\n'
                f'# alpha radiolysis driving a surface mechanism, 1890 days.\n'
                f'# This case: {variant}.\n'
                + broken
                + '#\n'
                '# Converted from the case\'s own reaction.in, sourceterm_alpha.in and\n'
                '# solutions.in by scripts/gen-rtm-examples.py. Rate constants are per second.\n'
                '# resources/tests/rtm/verify-brum.py checks this conversion against the\n'
                '# results.h5 each case ships.\n\n')
        body = text.replace('<SETTINGS>\n', '<SETTINGS>\n', 1)
        body = body.replace(f'TEND = {tend:.10g}\n', f'TEND = {tend:.10g}\nTIME_UNIT = second\n', 1)
        out.append(dict(
            id=f'hs{n}', group='Hydrosäk: spent-fuel dissolution',
            label=f'HS_case{n} — {variant}',
            about=f'One of the twenty cases of BRUM_for_Hydrosäk: {len(re.findall("=>", text))} '
                  'reactions over 35 species, 1890 days. Radiolysis of water at a spent-fuel '
                  'surface drives a uranium dissolution mechanism.'
                  + (' — This case needs "keep concentrations non-negative" turned off: its own '
                     'database has a typo that drives a species below zero. See the note in the '
                     'text.' if broken else ''),
            reference='SKB SE-SFL / BRUM_for_Hydrosäk, HS_case' + str(n)
                      + '. The conversion is checked against the case\'s own results.h5 in '
                        'resources/tests/rtm/verify-brum.py.',
            text=head + body))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--brum', type=Path, default=DEFAULT_BRUM)
    args = ap.parse_args()

    examples = list(EXAMPLES)
    note = ''
    if args.brum.exists():
        examples += hs_examples(args.brum, brum_reader())
    else:
        note = f'  (no Hydrosäk set at {args.brum}: those examples were left out)'

    body = ',\n'.join(
        '  ' + json.dumps({k: v for k, v in e.items()}, ensure_ascii=False, indent=2).replace('\n', '\n  ')
        for e in examples)
    OUT.write_text(f'''/* ==========================================================================
   RTM.HTML: THE EXAMPLE MODELS

   Written by scripts/gen-rtm-examples.py -- edit that, not this.

   Each is a complete model text the Model tab can load, chosen to show one
   thing the format can do and, where there is one, to have an answer that can
   be checked against something other than this code. The Hydrosäk set is
   converted from the BRUM_for_Hydrosäk databases by the same reader
   resources/tests/rtm/verify-brum.py uses.

   resources/tests/rtm/test-model.js compiles every one of them.
   ========================================================================== */

const RTM_EXAMPLES = [
{body}
];

if (typeof module !== 'undefined' && module.exports) {{
  module.exports = {{ RTM_EXAMPLES }};
}}
''', encoding='utf-8')

    # The page's own cache stamp, bumped so that a reader gets the new set.
    page = ROOT / 'rtm.html'
    src = page.read_text()
    pat = re.compile(r'(rtm-examples\.js\?v=)([0-9]{8})([a-z]*)')
    if pat.search(src):
        def bump(m):
            return m.group(1) + m.group(2) + (chr(ord(m.group(3) or '`') + 1) if m.group(3) else 'a')
        page.write_text(pat.sub(bump, src))

    kb = OUT.stat().st_size / 1024
    print(f'{OUT.relative_to(ROOT)}: {len(examples)} examples, {kb:.0f} kB{note}')
    for g in dict.fromkeys(e['group'] for e in examples):
        print(f'  {g}: ' + ', '.join(e['id'] for e in examples if e['group'] == g))


main()
