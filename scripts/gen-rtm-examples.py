#!/usr/bin/env python3
"""Writes resources/js/rtm-examples.js: the models the page offers to load.

Each is written out below, chosen to show one thing the model text can do and,
wherever there is one, to have an answer that can be checked against something
other than this code.

    python3 scripts/gen-rtm-examples.py

They are embedded rather than fetched, so that a page opened from a disk can
still load them.
"""
import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = ROOT / 'resources/js/rtm-examples.js'


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
# Every cell of the column has layers of rock behind it, reaching MATRIX_DEPTH
# into the rock: twelve unless MATRIX_CELLS says otherwise. They grow
# geometrically from the wall, because the gradient is steepest there, and the
# first is worked out from the path -- here about 9 cm, thin enough for the
# fastest change the outflow can still show. MATRIX_FIRST sets it instead.
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
MATRIX_DEPTH = 60      # m: deep enough to be infinite over this run
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
        id='farfield', group='Dual porosity',
        label='A far-field path, as Kompartment starts one',
        about='Kompartment’s far-field path with its own defaults: a travel time of 100 years, '
              'F = 10⁵ a/m, Péclet number 10, 20 cells, twelve matrix layers matched to diffusion '
              'into 12.5 m of rock, and the rock going on past the release point. Pick “flux '
              'through the right end” on Against time for the release.',
        reference='The path is the one a new far-field block in Kompartment starts with, and this '
                  'text gives the same transport matrix to round-off (resources/tests/rtm, '
                  'section 9). FARF31 solves the same path exactly, in the Laplace domain.',
        text='''\
# A far-field path, said the way SKB describes one, with Kompartment's
# defaults for a new far-field block.
#
# The path is a travel time and a flow-related transport resistance F, the
# wetted surface times the travel time: aw = F/tw = 1000 m2 of wall per m3 of
# water. The rock is MATRIX_DEPTH deep, its porosity and density given, and
# each nuclide brings its De and Kd, which become its capacity in the rock,
# eps + rho*Kd. Kdf= would add sorption on the fracture coating.
#
# The numerics are Kompartment's: 20 cells along the path, twelve matrix
# layers matched to diffusion into the rock with the first worked out from
# the path, and the rock going on past the release point -- RIGHT =
# semi-infinite, with as many cells past the end as the dispersion needs.
# "Flux through the right end" on the time chart is then the release FARF31
# gives, here for a unit release a year into the path from t = 0.
#
# The tracer all comes through in the end, held back by the rock. Ra-226
# sorbs and decays on the way, and of a steady unit release 2.2E-5 a year
# arrives in the end on these 20 cells, where FARF31's exact answer is
# 1.72E-5. The cells along the path decide that, not the layers: 40 give
# 1.84E-5 and 80 give 1.75E-5, a fourth of the error per doubling.

<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 100              # m; any length: TRAVEL_TIME sets the flow
TRAVEL_TIME = 100         # a
DIFFUSION = 1
PECLET = 10
LEFT = robin              # water arriving at left= per m3, one unit a year per m2
RIGHT = semi-infinite
MATRIX_DEPTH = 12.5       # m
MATRIX_POROSITY = 0.0018
MATRIX_DENSITY = 2700     # kg/m3
TRANSPORT_RESISTANCE = 1E5  # a/m: F
TEND = 1.0E6              # a
TIME_UNIT = year

<SPECIES>
#           start   De (m2/a)  Kd (m3/kg)
Tracer      0  left=1  De=1E-4
Ra226       0  left=1  De=1E-4  Kd=4.5E-4

<REACTIONS>
Ra226 => , k = 4.3322E-4, on = inventory   # 1 600 a, of the whole inventory
''',
    ),
    dict(
        id='releasehistory', group='Dual porosity',
        label='A release history through a far-field path',
        about='What a near field lets out, year by year, read from a table at the clock and fed '
              'into Kompartment\u2019s default far-field path: I-129, which the rock hardly holds, and '
              'Cs-135, which it holds back beyond the million years of the run. Pick \u201cflux through the right end\u201d '
              'on Against time for what comes out, and a cell for what the path holds.',
        text='''\
# A release history into a far-field path.
#
# The history is a <TABLE> read at the clock, t: one column per nuclide,
# named in its first row, the times in the model's own unit. A source that
# reads it is a reaction with nothing on the left. IN puts it into the first
# cell, per m2 of the water's cross-section, so that "flux through the right
# end" on the time chart is the release out of the path in the same units as
# the release going in.
#
# The run is started again at every row of the history, so that no pulse in
# it can be stepped over: the panel says how many corners there are. Beyond
# its last row a table holds its last value, so a history that ends, ends in
# zeros.
#
# The path is Kompartment's default far-field path, as in the example before.

<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 100              # m; TRAVEL_TIME sets the flow
TRAVEL_TIME = 100         # a
DIFFUSION = 1
PECLET = 10
LEFT = robin
RIGHT = semi-infinite
MATRIX_DEPTH = 12.5       # m
MATRIX_POROSITY = 0.0018
MATRIX_DENSITY = 2700     # kg/m3
TRANSPORT_RESISTANCE = 1E5  # a/m: F
TEND = 1.0E6              # a
TIME_UNIT = year

<TABLE release>
t         I129    Cs135   # mol a year per m2 of the water's cross-section
0         0       0
1000      0       0       # a canister fails at 1000 years:
1100      1       0.5     # the gap inventory first,
5000      0.4     0.4     # then the fuel dissolving
2.0E4     0.1     0.2
1.0E5     0.01    0.05
1.0E6     0       0

<SPECIES>
#        start          De (m2/a)   Kd (m3/kg)
I129     0  left=0  De=1E-4                  # does not sorb
Cs135    0  left=0  De=1E-4      Kd=0.01

<PARAMETERS>
IN  all  0
IN  0    1/w  fracture        # into the first cell's water

<REACTIONS>
=> I129,  r = IN*release(t, I129)
=> Cs135, r = IN*release(t, Cs135)
I129  => , k = 4.41E-8, on = inventory    # 1.57e7 a
Cs135 => , k = 3.0E-7,  on = inventory    # 2.3e6 a
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
# 2237 m travelled in TRAVEL_TIME = 235.2 a, and a flow-related transport
# resistance F = 80 090 a/m, which is the wall area per unit volume of water
# times the travel time: aw = F/tw = 340.5 m2/m3.
#
# Each nuclide's Kd becomes the rock's capacity for it, eps_m + rho*Kd with
# MATRIX_POROSITY = 0.0019 and MATRIX_DENSITY = 2700 kg/m3. That is what holds
# the sorbing members of the chain back by thousands of years.
#
# The rock goes on past the release point, RIGHT = semi-infinite, and the
# layers are matched to diffusion into the rock, as in Kompartment's far-field
# path. Twenty rather than its twelve: Po-210, half-life 0.38 a, sizes the
# first layer by its own decay, at 5 micrometres, and twelve layers would
# have to grow by 3.4 each to reach 4.5 m -- too coarse at depth for U-238,
# whose releases came out 4 % off. Twenty grow by 2.0, and are 0.2 % off.
#
# DECAY IS on = inventory. A rate law is per unit pore water, and a cubic metre
# of rock holds only eps_m of water -- right for chemistry, wrong for decay,
# which takes the sorbed atoms too. Written as on = water instead, the sorbing
# nuclides would decay at eps_m/Rm of their real rate.

<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 2237          # m
TRAVEL_TIME = 235.2    # a: the flow is LENGTH over it
DIFFUSION = 1
PECLET = 10
LEFT = robin
RIGHT = semi-infinite
MATRIX_CELLS = 20
MATRIX_DEPTH = 4.5     # m
MATRIX_POROSITY = 0.0019
MATRIX_DENSITY = 2700  # kg/m3
TRANSPORT_RESISTANCE = 80090   # a/m: F = aw*tw
TEND = 1.0E6           # a
TIME_UNIT = year

<SPECIES>
#          start  De (m2/a)   Kd (m3/kg)
U238   0  De=2.7E-7  Kd=2.0E-4
U234   0  De=2.7E-7  Kd=2.0E-4
Th230  0  De=2.7E-7  Kd=5.3E-2
Ra226  0  De=8.5E-7  Kd=4.5E-4
Pb210  0  De=8.5E-7  Kd=2.5E-2
Po210  0  De=2.7E-7  Kd=2.5E-2

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


def main():
    examples = list(EXAMPLES)

    body = ',\n'.join(
        '  ' + json.dumps({k: v for k, v in e.items()}, ensure_ascii=False, indent=2).replace('\n', '\n  ')
        for e in examples)
    OUT.write_text(f'''/* ==========================================================================
   RTM.HTML: THE EXAMPLE MODELS

   Written by scripts/gen-rtm-examples.py -- edit that, not this.

   Each is a complete model text the Model tab can load, chosen to show one
   thing the format can do and, where there is one, to have an answer that can
   be checked against something other than this code.

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
    print(f'{OUT.relative_to(ROOT)}: {len(examples)} examples, {kb:.0f} kB')
    for g in dict.fromkeys(e['group'] for e in examples):
        print(f'  {g}: ' + ', '.join(e['id'] for e in examples if e['group'] == g))


main()
