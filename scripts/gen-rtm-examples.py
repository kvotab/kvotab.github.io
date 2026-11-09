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
    dict(
        id='calciterate',
        group='Reading a run',
        label='Calcite at a rate: pH, SI and measurements',
        about="Calcite dissolving at a rate into water that holds CO2. Run it: the time chart shows the pH and the calcite's saturation index on the right-hand axis, the calcium in mg/kgw — an <OUTPUT> of the text's own — on the left, and made-up measurements from <DATA> as open circles beside them.",
        text='''\
# Calcite dissolving at a rate into water that holds CO2, read as more than
# its species: the pH, the calcite's saturation index, the calcium in mg/kgw
# from <OUTPUT>, and measurements beside them from <DATA>. The constants are
# phreeqc.dat's; the rate and the measurements are made up.

<SETTINGS>
MODE = batch
TEND = 3
TIME_UNIT = day
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+        3e-5
OH-       3e-10
CO2       1e-3
HCO3-     3e-5
CO3-2     1e-12
Ca+2      1e-9
CaHCO3+   1e-12
CaCO3     1e-14
Calcite   0.01  mineral

<EQUILIBRIUM>
 <=> H+ + OH-,                 logK = -14
CO2 + H2O <=> H+ + HCO3-,      logK = -6.352
HCO3- <=> H+ + CO3-2,          logK = -10.329
Ca+2 + HCO3- <=> CaHCO3+,      logK = 1.106
Ca+2 + CO3-2 <=> CaCO3,        logK = 3.224

<PHASES>
Calcite <=> Ca+2 + CO3-2,      logK = -8.48

<PARAMETERS>
kc  all  5e-4                  # mol/kgw a day, far from saturation

<REACTIONS>
Calcite => Ca+2 + CO3-2, r = kc*(1 - SR(Calcite))

<OUTPUT>
Ca_mg  = 40078 * ([Ca+2] + [CaHCO3+] + [CaCO3]),  unit = mg/kgw
alk    = [HCO3-] + 2*[CO3-2] + [CaHCO3+] + 2*[CaCO3] + [OH-] - [H+],  unit = eq/kgw

<DATA>
time   pH     Ca_mg    cell = 0
0.5    6.05   11.2
1      6.70   19.0
1.5    6.95   31.0
2      7.55   35.0
3      7.70   39.5
''',
        view={'tab': 'time', 'picked': ['pH', 'SI(Calcite)', 'Ca_mg'], 'cell': 0, 'logT': False, 'logY': False},
    ),
    dict(
        id='acidcolumn',
        group='Reading a run',
        label='Acid through calcite: contours of pH',
        about='Acid water through a column of calcite held at saturation, the calcite dissolving away cell by cell. Run it: the Gradient tab draws the pH as contours over time and distance, the front a line moving down the column. As a surface turns it into a landscape; SI(Calcite) and tot(Ca) are in the same picker.',
        text='''\
# Acid water through a column of calcite held at saturation: where the
# calcite dissolves away, the acid goes on, and the pH front moves down the
# column a cell at a time. The Gradient tab draws the pH as contours over
# time and distance. phreeqc.dat's constants; D stands for the dispersion.

<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 0.1
VELOCITY = 1e-5
ADVECTION = 1
DIFFUSION = 1
LEFT = robin          # the flow carries the acid in, and nothing else crosses
RIGHT = free
TEND = 2e5
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+        1e-8     D=5e-8  left=1e-3
OH-       1e-6     D=5e-8  left=1e-11
Cl-       2e-3     D=5e-8  left=3e-3
Ca+2      1e-3     D=5e-8  left=1e-3
CO2       1e-4     D=5e-8  left=1e-4
HCO3-     2e-3     D=5e-8  left=0
CO3-2     1e-5     D=5e-8  left=0
CaHCO3+   1e-5     D=5e-8  left=0
CaCO3     1e-6     D=5e-8  left=0
Na+       2e-3     D=5e-8  left=0
Calcite   0.02     mineral

<EQUILIBRIUM>
 <=> H+ + OH-,                 logK = -14
CO2 + H2O <=> H+ + HCO3-,      logK = -6.352
HCO3- <=> H+ + CO3-2,          logK = -10.329
Ca+2 + HCO3- <=> CaHCO3+,      logK = 1.106
Ca+2 + CO3-2 <=> CaCO3,        logK = 3.224
Calcite <=> Ca+2 + CO3-2,      logK = -8.48
''',
        view={'tab': 'gradient', 'grad': {'species': 'pH', 'view': 'contour'}},
    ),
    dict(
        id='salinisation',
        group='What the water is made of',
        label='Salty water into a fresh aquifer: a Piper path',
        about="Salty water into an aquifer with calcite and an exchanger: sodium and magnesium take the exchanger, calcium comes off it. Run it: the Composition tab draws the outlet's water as a path through a Piper diagram, from Ca–HCO3 to Na–Cl by way of a calcium peak, with waters measured there; Schoeller and Stiff diagrams of the same waters are on the Show menu, where calcium is along the column, and a USSL diagram, the outlet's water going from C2-S1 to C4-S3 as the salt comes through.",
        text='''\
# Salty water into a fresh aquifer with calcite and an exchanger: sodium and
# magnesium take the exchanger, calcium comes off it, and the water at the
# outlet goes from Ca-HCO3 to Na-Cl by way of a calcium peak. The Composition
# tab draws its path on a Piper diagram, beside waters measured at the outlet,
# and, from the conductance <CONDUCTANCE> gives, a USSL diagram of its class
# for irrigation. The constants are phreeqc.dat's; the waters and the
# measurements are made up, and D stands for the dispersion.
<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 0.2
VELOCITY = 1e-5
DIFFUSION = 1
ADVECTION = 1
LEFT = robin
RIGHT = free
ACTIVITY = davies
EQUILIBRATE = always
TEND = 6e4

<SPECIES>
Ca+2      1.2e-3   D=1e-7  left=1e-3
Mg+2      2e-4     D=1e-7  left=2e-3
Na+       3e-4     D=1e-7  left=2e-2
K+        5e-5     D=1e-7  left=4e-4
Cl-       3e-4     D=1e-7  left=2.2e-2
SO4-2     1e-4     D=1e-7  left=1.5e-3
HCO3-     2.6e-3   D=1e-7  left=1.5e-3
CO3-2     1e-6     D=1e-7  left=0
CO2       1e-4     D=1e-7  left=1e-4
CaHCO3+   0        D=1e-7
CaCO3     0        D=1e-7
MgHCO3+   0        D=1e-7
CaSO4     0        D=1e-7
MgSO4     0        D=1e-7
NaSO4-    0        D=1e-7
H+        3e-8     D=1e-7  left=3e-8
OH-       3e-7     D=1e-7  left=3e-7
Calcite   0.01     mineral
X-        exchanger 5e-3
NaX       exchange
CaX2      exchange
MgX2      exchange
KX        exchange

<EQUILIBRIUM>
H2O <=> H+ + OH-, logK = -14
CO3-2 + H+ <=> HCO3-, logK = 10.329
CO3-2 + 2 H+ <=> CO2 + H2O, logK = 16.681
Ca+2 + HCO3- <=> CaHCO3+, logK = 1.106
Ca+2 + CO3-2 <=> CaCO3, logK = 3.224
Mg+2 + HCO3- <=> MgHCO3+, logK = 1.07
Ca+2 + SO4-2 <=> CaSO4, logK = 2.25
Mg+2 + SO4-2 <=> MgSO4, logK = 2.37
Na+ + SO4-2 <=> NaSO4-, logK = 0.7
Calcite <=> Ca+2 + CO3-2, logK = -8.48
Na+ + X- <=> NaX, logK = 0
Ca+2 + 2 X- <=> CaX2, logK = 0.8
Mg+2 + 2 X- <=> MgX2, logK = 0.6
K+ + X- <=> KX, logK = 0.7

<CONDUCTANCE>
Ca+2      gfw 40.08  dw 7.92e-10 34 5.411 0 1.046  viscosity 0.359 -0.158 0.042 0.0015 0.00804 2.3
Mg+2      gfw 24.312  dw 7.05e-10 -4 5.569 0 1.047  viscosity 0.426 0 0 0.00166 0.00432 2.461
Na+       gfw 22.9898  dw 1.33e-9 75 3.627 0 0.7037  viscosity 0.1387 -0.0866 0.0125 0.0145 0.0075 1.062
K+        gfw 39.102  dw 1.96e-9 254 3.484 0 0.1964  viscosity 0.116 -0.191 0.0152 0.014 0.0259 0.9028
Cl-       gfw 35.453  dw 2.033e-9 216 3.16 0.2071 0.7432  viscosity 0 0 0 0 0 0 1
SO4-2     gfw 96.064  dw 1.07e-9 -114 17 0.0602 0.0494  viscosity -0.3 0.501 0.00257 0.195 0.0314 2.015 0.605
HCO3-     gfw 61.0191  dw 1.18e-9 -190 11.386  viscosity -0.6 1.366 -0.01216 0 0.03139 -1.135 1.253
CO3-2     gfw 60.0111  dw 9.55e-10 -103 2.246 0.0713 0.3686  viscosity -0.5 0.6521 0.00544 0.00106 -0.0218 1.208 -2.147
CO2       gfw 44.0111  dw 1.92e-9 -120  viscosity 0.0068 0.0903 0.0327 0 0 0 0.18
CaHCO3+   gfw 101.0991  dw 5.06e-10
CaCO3     gfw 100.0911  dw 4.46e-10
MgHCO3+   gfw 85.3311  dw 4.78e-10
CaSO4     gfw 136.144  dw 4.71e-10
MgSO4     gfw 120.376  dw 4.45e-10  viscosity 0.318 -0.00054 -0.0342 0.708 0.0037 0.696
NaSO4-    gfw 119.0538  dw 1.13e-9 -23 8.5 0.392 0.521  viscosity 0.2 -0.0593 -0.0004 0.00846 0.00178 2.308 -0.208
H+        gfw 1.008  dw 9.31e-9 838 6.96 -2.285 0.206 24.01 0  viscosity 0.0935 -0.0831 0.02487 0.000449 0.0201 1.57
OH-       gfw 17.008  dw 5.27e-9 478 0.8695  viscosity -0.0226 0.106 0.02184 -0.0032 0 0.4082 -1.634
H2O       gfw 18.016

<DATA>
time   tot(Ca)  tot(Mg)  tot(Na)  K+       Cl-      tot(S)   alk(CO3)  SC     cell = 19
1e4    1.4e-3   2.4e-4   1.0e-3   5.0e-5   1.2e-3   1.6e-4   2.55e-3   445
2e4    2.05e-3  6.6e-4   1.1e-2   1.9e-4   1.3e-2   9.3e-4   1.95e-3   1880
3e4    1.75e-3  1.25e-3  1.7e-2   3.1e-4   1.95e-2  1.3e-3   1.75e-3   2640
6e4    1.2e-3   2.0e-3   2.05e-2  3.9e-4   2.25e-2  1.55e-3  1.62e-3   3010
''',
        view={'tab': 'composition', 'comp': {'view': 'piper', 'along': 'time', 'cell': 19}},
    ),
    dict(
        id='bjerrum',
        group='Equilibrium diagrams',
        label='Carbonate against pH',
        about="A carbonate water held at each pH from 2 to 12 and speciated there by its own relations. Run it: the Diagrams tab works out the carbonate's distribution — CO2, HCO3-, CO3-2 and the complexes — as shares of the carbon; the saturation indices and log concentrations are on the Show menu.",
        text='''\
# The carbonate in a water, held at each pH from 2 to 12 and speciated there:
# CO2 below pH 6.3, HCO3- to 10.3, CO3-2 above, the classic distribution. The
# Diagrams tab draws it from this water, with its activity coefficients, and
# calcite's saturation index beside it. phreeqc.dat's constants.

<SETTINGS>
MODE = batch
TEND = 1
ACTIVITY = davies
EQUILIBRATE = 1

<SPECIES>
H+        1e-8
OH-       1e-6
Na+       2e-3
Ca+2      5e-4
Cl-       1e-3
CO2       5e-5
HCO3-     2e-3
CO3-2     1e-5
CaHCO3+   1e-5
CaCO3     1e-6
NaHCO3    1e-6
NaCO3-    1e-7

<EQUILIBRIUM>
 <=> H+ + OH-,                 logK = -14
CO2 + H2O <=> H+ + HCO3-,      logK = -6.352
HCO3- <=> H+ + CO3-2,          logK = -10.329
Ca+2 + HCO3- <=> CaHCO3+,      logK = 1.106
Ca+2 + CO3-2 <=> CaCO3,        logK = 3.224
Na+ + HCO3- <=> NaHCO3,        logK = -0.25
Na+ + CO3-2 <=> NaCO3-,        logK = 1.27

<PHASES>
Calcite <=> Ca+2 + CO3-2,      logK = -8.48
''',
        view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'pH', 'sp': '', 'from': '2', 'to': '12', 'n': '101'}, 'y': {'kind': '', 'sp': '', 'from': '-12', 'to': '16', 'n': '41'}, 'show': 'shares', 'el': 'C', 'in': 'water', 'q': 'pH'}},
    ),
    dict(
        id='pourbaix',
        group='Equilibrium diagrams',
        label='Iron: a pe–pH (Pourbaix) diagram',
        about="Iron in a dilute water, Fe+2 and Fe+3, their hydrolysis and ferrihydrite. Run it: the Diagrams tab holds the water at each pH and pe and draws the species that holds most of the iron, in the whole cell, ferrihydrite's field among them, with where water itself gives way drawn across it.",
        text='''\
# Iron in a dilute water: Fe+2 and Fe+3, their hydrolysis and ferrihydrite.
# The Diagrams tab holds the water at each pH and pe and draws the species
# that holds most of the iron -- a Pourbaix diagram -- with where water itself
# gives way, oxygen above and hydrogen below. phreeqc.dat's constants.
<SETTINGS>
MODE = batch
TEND = 1
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+           1e-7
OH-          1e-7
e-           electron  pe=4
Na+          1e-3
Cl-          1e-3
Fe+2         1e-5
Fe+3         0
FeOH+        0
Fe(OH)2      0
Fe(OH)3-     0
FeOH+2       0
Fe(OH)2+     0
Fe(OH)3      0
Fe(OH)4-     0
Ferrihydrite 0  mineral

<EQUILIBRIUM>
 <=> H+ + OH-,                         logK = -14
Fe+2 <=> Fe+3 + e-,                    logK = -13.02
Fe+2 + H2O <=> FeOH+ + H+,             logK = -9.5
Fe+2 + 2 H2O <=> Fe(OH)2 + 2 H+,       logK = -20.57
Fe+2 + 3 H2O <=> Fe(OH)3- + 3 H+,      logK = -31
Fe+3 + H2O <=> FeOH+2 + H+,            logK = -2.19
Fe+3 + 2 H2O <=> Fe(OH)2+ + 2 H+,      logK = -5.67
Fe+3 + 3 H2O <=> Fe(OH)3 + 3 H+,       logK = -12.56
Fe+3 + 4 H2O <=> Fe(OH)4- + 4 H+,      logK = -21.6
Ferrihydrite + 3 H+ <=> Fe+3 + 3 H2O,  logK = 4.891
''',
        view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'pH', 'sp': '', 'from': '2', 'to': '12', 'n': '101'}, 'y': {'kind': 'pe', 'sp': '', 'from': '-12', 'to': '16', 'n': '57'}, 'show': 'predominance', 'el': 'Fe', 'in': 'all', 'q': 'pH'}},
    ),
    dict(
        id='stability',
        group='Equilibrium diagrams',
        label='Calcite or gypsum: a mineral stability diagram',
        about='A calcium water held at each activity of carbonate and of sulfate. Run it: the Diagrams tab draws where calcite is furthest over saturation, where gypsum is and where neither is; contours of either saturation index are on the Show menu.',
        text='''\
# A calcium water held at each activity of carbonate and of sulfate: where
# calcite is furthest over saturation, where gypsum is, and where neither is,
# a mineral stability diagram on the Diagrams tab. phreeqc.dat's constants.

<SETTINGS>
MODE = batch
TEND = 1
ACTIVITY = davies
EQUILIBRATE = 1

<SPECIES>
Ca+2      1e-2
Cl-       2e-2
CO3-2     1e-8
SO4-2     1e-4
CaCO3     1e-8
CaSO4     1e-5

<EQUILIBRIUM>
Ca+2 + CO3-2 <=> CaCO3,        logK = 3.224
Ca+2 + SO4-2 <=> CaSO4,        logK = 2.25

<PHASES>
Calcite <=> Ca+2 + CO3-2,      logK = -8.48
Gypsum <=> Ca+2 + SO4-2 + 2 H2O, logK = -4.58
''',
        view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'la', 'sp': 'CO3-2', 'from': '-10', 'to': '-2', 'n': '81'}, 'y': {'kind': 'la', 'sp': 'SO4-2', 'from': '-6', 'to': '-1', 'n': '51'}, 'show': 'phase', 'el': 'Ca', 'in': 'water', 'q': 'SI(Calcite)'}},
    ),
    dict(
        id='sorptionedge',
        group='Equilibrium diagrams',
        label='Zinc on ferrihydrite: a sorption edge',
        about='Zinc and a ferrihydrite surface, its strong and weak sites as Dzombak and Morel give them. Run it: the Diagrams tab holds the water at each pH from 4 to 9 and draws where the zinc is — dissolved at low pH, on the surface at high — as shares of all of it.',
        text='''\
# Zinc on ferrihydrite, its strong and weak sites as Dzombak and Morel give
# them: held at each pH from 4 to 9, the water gives its zinc to the surface,
# and the Diagrams tab draws where the zinc is -- dissolved below pH 6, on the
# surface above it -- the sorption edge. phreeqc.dat's constants; no double
# layer.

<SETTINGS>
MODE = batch
TEND = 1
ACTIVITY = davies
EQUILIBRATE = 1

<SPECIES>
H+          1e-7
OH-         1e-7
Na+         1e-2
Cl-         1e-2
Zn+2        1e-6
ZnOH+       0
Zn(OH)2     0
ZnCl+       0
Hfo_sOH     surface  sites=5e-6
Hfo_sOH2+   surface
Hfo_sO-     surface
Hfo_sOZn+   surface
Hfo_wOH     surface  sites=2e-4
Hfo_wOH2+   surface
Hfo_wO-     surface
Hfo_wOZn+   surface

<EQUILIBRIUM>
 <=> H+ + OH-,                          logK = -14
Zn+2 + H2O <=> ZnOH+ + H+,              logK = -8.96
Zn+2 + 2 H2O <=> Zn(OH)2 + 2 H+,        logK = -16.9
Zn+2 + Cl- <=> ZnCl+,                   logK = 0.43
Hfo_sOH + H+ <=> Hfo_sOH2+,             logK = 7.29
Hfo_sOH <=> Hfo_sO- + H+,               logK = -8.93
Hfo_sOH + Zn+2 <=> Hfo_sOZn+ + H+,      logK = 0.99
Hfo_wOH + H+ <=> Hfo_wOH2+,             logK = 7.29
Hfo_wOH <=> Hfo_wO- + H+,               logK = -8.93
Hfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+,      logK = -1.99
''',
        view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'pH', 'sp': '', 'from': '4', 'to': '9', 'n': '101'}, 'y': {'kind': '', 'sp': '', 'from': '-12', 'to': '16', 'n': '41'}, 'show': 'shares', 'el': 'Zn', 'in': 'all', 'q': 'pH'}},
    ),
    dict(
        id='exchangesweep',
        group='Sweeps',
        label='An exchange front, its capacity swept',
        about='Calcium chloride water into a column whose exchanger holds sodium. Run it: the Sweeps tab runs it again for four capacities of the exchanger and draws the calcium at the outlet, a curve for each: the larger the capacity, the later the calcium comes.',
        text='''\
# Calcium chloride water into a column whose exchanger holds sodium: the
# chloride arrives with the water, the calcium only once the exchanger has
# taken its fill, the later the larger its capacity. The Sweeps tab runs it
# again for each capacity and draws the calcium at the outlet. Gaines-Thomas
# exchange with phreeqc.dat's constants; D stands for the dispersion.

<SETTINGS>
MODE = transport
CELLS = 30
LENGTH = 0.1
VELOCITY = 1e-5
ADVECTION = 1
DIFFUSION = 1
LEFT = robin
RIGHT = free
EQUILIBRATE = always
TEND = 1e5

<SPECIES>
Na+     1e-3    D=1e-7  left=0
Ca+2    1e-12   D=1e-7  left=6e-4
Cl-     1e-3    D=1e-7  left=1.2e-3
X-      exchanger 2e-3
NaX     exchange
CaX2    exchange

<EQUILIBRIUM>
Na+ + X- <=> NaX,              logK = 0
Ca+2 + 2 X- <=> CaX2,          logK = 0.8
''',
        view={'tab': 'sweep', 'go': True, 'sw': {'what': 'initial:X-', 'values': '1e-3, 2e-3, 4e-3, 8e-3', 'what2': '', 'values2': '', 'cell': 29, 'show': 'time', 'key': 'Ca+2', 'of': 'end', 'logT': False}},
    ),
    dict(
        id='ratesweep',
        group='Sweeps',
        label='Calcite at a rate, over the rate and the CO2',
        about='Calcite dissolving at a rate, run again for nine rates and five amounts of CO2 at the start. Run it: the Sweeps tab draws the calcium after three days over the two, as contours — limited by the rate on one side, by the saturation the CO2 allows on the other.',
        text='''\
# Calcite dissolving at a rate into water that holds CO2, run again for each
# rate and each amount of CO2 at the start: the Sweeps tab draws the calcium
# after three days over the two, as contours. The constants are phreeqc.dat's;
# the rate is made up.

<SETTINGS>
MODE = batch
TEND = 3
TIME_UNIT = day
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+        3e-5
OH-       3e-10
CO2       1e-3
HCO3-     3e-5
CO3-2     1e-12
Ca+2      1e-9
CaHCO3+   1e-12
CaCO3     1e-14
Calcite   0.01  mineral

<EQUILIBRIUM>
 <=> H+ + OH-,                 logK = -14
CO2 + H2O <=> H+ + HCO3-,      logK = -6.352
HCO3- <=> H+ + CO3-2,          logK = -10.329
Ca+2 + HCO3- <=> CaHCO3+,      logK = 1.106
Ca+2 + CO3-2 <=> CaCO3,        logK = 3.224

<PHASES>
Calcite <=> Ca+2 + CO3-2,      logK = -8.48

<PARAMETERS>
kc  all  5e-4                  # mol/kgw a day, far from saturation

<REACTIONS>
Calcite => Ca+2 + CO3-2, r = kc*(1 - SR(Calcite))

<OUTPUT>
Ca_mg  = 40078 * ([Ca+2] + [CaHCO3+] + [CaCO3]),  unit = mg/kgw
alk    = [HCO3-] + 2*[CO3-2] + [CaHCO3+] + 2*[CaCO3] + [OH-] - [H+],  unit = eq/kgw
''',
        view={'tab': 'sweep', 'go': True, 'sw': {'what': 'parameter:kc', 'values': '1e-4 to 1e-2 in 9 log', 'what2': 'initial:CO2', 'values2': '2e-4 to 2e-3 in 5 log', 'cell': 0, 'show': 'contour', 'key': 'Ca_mg', 'of': 'end', 'logT': True}},
    ),
    dict(
        id='ironoxygen',
        group='All together',
        label='Oxygen into iron(II) water: redox, a mineral, exchange',
        about="Water with oxygen in it into a column of anoxic water that holds iron(II), dissolved and on an exchanger: the iron is oxidised and comes out as ferrihydrite, and the acid that leaves takes the pH down at the front. Run it: the Composition tab shows where the iron is along the column — in the water, on the exchanger, in the ferrihydrite. Then the Gradient tab's pe or pH as contours, the Diagrams tab's Pourbaix diagram of the water as the run leaves it, and a sweep of the oxygen flowing in.",
        text='''\
# Water with oxygen in it into a column of anoxic water that holds iron(II),
# in the water and on an exchanger: where the oxygen arrives, the iron is
# oxidised, ferrihydrite comes out of the water and the acid it leaves takes
# the pH down; the exchanger gives up its iron as the water's goes, and holds
# the front back. Redox at one pe, a mineral held at saturation, exchange,
# carbonate and activities together. The Composition tab draws where the iron
# is along the column; the Gradient tab the pH or the pe; the Diagrams tab the
# Pourbaix diagram of the water as the run leaves it. phreeqc.dat's constants;
# D stands for the dispersion.

<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 0.1
VELOCITY = 1e-5
ADVECTION = 1
DIFFUSION = 1
LEFT = robin
RIGHT = free
TEND = 6e4
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+           1e-7     D=1e-7  left=1e-7
OH-          1e-7     D=1e-7  left=1e-7
e-           electron pe=-1
O2           1e-30    D=1e-7  left=2.5e-4
Na+          2e-3     D=1e-7  left=2e-3
Cl-          1e-3     D=1e-7  left=1.4e-3
CO2          2e-4     D=1e-7  left=2e-4
HCO3-        1.4e-3   D=1e-7  left=1e-3
CO3-2        1e-6     D=1e-7  left=1e-6
Fe+2         2e-4     D=1e-7  left=0
Fe+3         1e-20    D=1e-7  left=0
FeOH+        1e-8     D=1e-7  left=0
FeHCO3+      1e-6     D=1e-7  left=0
FeOH+2       1e-20    D=1e-7  left=0
Fe(OH)2+     1e-18    D=1e-7  left=0
Fe(OH)3      1e-18    D=1e-7  left=0
Fe(OH)4-     1e-20    D=1e-7  left=0
Ferrihydrite 0        mineral
X-           exchanger 5e-3
NaX          exchange
FeX2         exchange

<EQUILIBRIUM>
 <=> H+ + OH-,                          logK = -14
2 H2O <=> O2 + 4 H+ + 4 e-,             logK = -86.08
CO2 + H2O <=> H+ + HCO3-,               logK = -6.352
HCO3- <=> H+ + CO3-2,                   logK = -10.329
Fe+2 <=> Fe+3 + e-,                     logK = -13.02
Fe+2 + H2O <=> FeOH+ + H+,              logK = -9.5
Fe+2 + HCO3- <=> FeHCO3+,               logK = 2.0
Fe+3 + H2O <=> FeOH+2 + H+,             logK = -2.19
Fe+3 + 2 H2O <=> Fe(OH)2+ + 2 H+,       logK = -5.67
Fe+3 + 3 H2O <=> Fe(OH)3 + 3 H+,        logK = -12.56
Fe+3 + 4 H2O <=> Fe(OH)4- + 4 H+,       logK = -21.6
Ferrihydrite + 3 H+ <=> Fe+3 + 3 H2O,   logK = 4.891
Na+ + X- <=> NaX,                       logK = 0
Fe+2 + 2 X- <=> FeX2,                   logK = 0.44
''',
        view={'tab': 'composition', 'comp': {'view': 'where', 'element': 'Fe', 'in': 'all', 'as': 'percent', 'along': 'distance', 'times': '15000'}},
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
