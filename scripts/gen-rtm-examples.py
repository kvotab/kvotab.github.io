#!/usr/bin/env python3
"""Writes resources/js/rtm-examples.js: the models the page offers to load.

Each is written out below, chosen to show one thing the model text can do and,
wherever there is one, to have an answer that can be checked against something
other than this code.

    python3 scripts/gen-rtm-examples.py

They are embedded rather than fetched, so that a page opened from a disk can
still load them.
"""
import datetime
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
              'that changes the mass in it, to one part in 10^15. It opens on Against time in pore '
              'volumes, X at four cells a quarter of the column apart: at a Péclet number of 5 the '
              'front spreads as it goes, half-way up at 0.29 pore volumes a quarter of the way along '
              'and at 0.86 at the outlet.',
        view={'tab': 'time', 'picked': ['X'], 'cells': '9, 19, 29, 39', 'timeIn': 'pv', 'logT': False, 'logY': False},
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
        label='Iron: an Eh–pH (Pourbaix) diagram',
        about="Iron in a dilute water, Fe+2 and Fe+3, their hydrolysis and ferrihydrite. Run it: the Diagrams tab holds the water at each pH and Eh and draws the species that holds most of the iron, in the whole cell, ferrihydrite's field among them, with where water itself gives way drawn across it.",
        text='''\
# Iron in a dilute water: Fe+2 and Fe+3, their hydrolysis and ferrihydrite.
# The Diagrams tab holds the water at each pH and Eh and draws the species
# that holds most of the iron -- a Pourbaix diagram -- with where water itself
# gives way, oxygen above and hydrogen below. pe on its menu draws the same in
# pe. phreeqc.dat's constants.
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
        view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'pH', 'sp': '', 'from': '2', 'to': '12', 'n': '101'}, 'y': {'kind': 'Eh', 'sp': '', 'from': '-0.8', 'to': '1.2', 'n': '81'}, 'show': 'predominance', 'el': 'Fe', 'in': 'all', 'q': 'pH'}},
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
        id='silicates',
        group='Equilibrium diagrams',
        label='K-feldspar, muscovite, kaolinite, gibbsite: a silicate stability diagram',
        about="Which of K-feldspar, muscovite, kaolinite and gibbsite is stable, the aluminium kept in the solids, over the activity of silica and that of potassium over the hydrogen ion's. Run it: the Diagrams tab draws Garrels and Christ's diagram, each phase weighed per mole of aluminium, quartz and amorphous silica dotted where they come to saturation.",
        text='''\
# K-feldspar, muscovite (K_mica), kaolinite and gibbsite: which of them is
# stable, the aluminium kept in the solids, over the activity of silica and
# that of potassium over the hydrogen ion's -- the diagram of Garrels and
# Christ. The Diagrams tab weighs each phase per mole of aluminium, so that
# what is dissolved of it does not matter, and dots quartz and amorphous
# silica where they come to saturation. No ACTIVITY: the axes are activities,
# and the water's own is 1, as the diagram takes it. phreeqc.dat's constants
# at 25 C, quartz's and amorphous silica's from its analytic expressions.
<SETTINGS>
MODE = batch
TEND = 1
EQUILIBRATE = always

<SPECIES>
H+        1e-7
OH-       1e-7
K+        1e-4
Na+       1e-3
Cl-       1.1e-3
Al+3      1e-9
AlOH+2    0
Al(OH)2+  0
Al(OH)3   0
Al(OH)4-  0
H4SiO4    1e-4
H3SiO4-   0

<EQUILIBRIUM>
 <=> H+ + OH-,                       logK = -14
Al+3 + H2O <=> AlOH+2 + H+,          logK = -5
Al+3 + 2 H2O <=> Al(OH)2+ + 2 H+,    logK = -10.1
Al+3 + 3 H2O <=> Al(OH)3 + 3 H+,     logK = -16.9
Al+3 + 4 H2O <=> Al(OH)4- + 4 H+,    logK = -22.7
H4SiO4 <=> H3SiO4- + H+,             logK = -9.83

<PHASES>
K_feldspar + 8 H2O <=> K+ + Al(OH)4- + 3 H4SiO4,   logK = -20.573
Kaolinite + 6 H+ <=> H2O + 2 H4SiO4 + 2 Al+3,      logK = 7.435
Gibbsite + 3 H+ <=> Al+3 + 3 H2O,                  logK = 8.11
K_mica + 10 H+ <=> K+ + 3 Al+3 + 3 H4SiO4,         logK = 12.703
Quartz + 2 H2O <=> H4SiO4,                         logK = -3.9804
SiO2(a) + 2 H2O <=> H4SiO4,                        logK = -2.7118
''',
        view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'la', 'sp': 'H4SiO4', 'from': '-6', 'to': '-2', 'n': '81'}, 'y': {'kind': 'ratio', 'sp': 'K+', 'from': '0', 'to': '10', 'n': '101'}, 'show': 'stable', 'el': 'Al', 'in': 'water', 'q': 'pH'}},
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



# ---------------------------------------------------------------------------
# Fitting, uncertainty, the irrigation classes, principal components and an
# inverse model through PHREEQC: each opens, once run, on the view that shows
# it, and two are the text of another example read another way.
# ---------------------------------------------------------------------------
def _text(eid):
    return next(e['text'] for e in EXAMPLES if e['id'] == eid)


def _retitled(text, head):
    """The text with its opening comment, every line up to the first that is not one, put in place of head."""
    lines = text.split('\n')
    k = next(i for i, ln in enumerate(lines) if not ln.startswith('#'))
    return head.rstrip('\n') + '\n' + '\n'.join(lines[k:])


def _after(eid, *new):
    i = next(k for k, e in enumerate(EXAMPLES) if e['id'] == eid)
    EXAMPLES[i + 1:i + 1] = list(new)


_after('silicates', dict(
    id='gibbsite',
    group='Equilibrium diagrams',
    label='Gibbsite: its solubility against pH',
    about="The aluminium a water of 10 mM NaCl holds at saturation with gibbsite, at every pH from 4 to 10, as PhreePlot's solubility diagrams draw it from PHREEQC. Run it: the Diagrams tab draws what dissolves, falling with the pH as Al³⁺, least near pH 6.4 and rising again as Al(OH)₄⁻, each species of the aluminium beside it. Write Al(OH)3(a) after Gibbsite, with a comma, and work it out again: the amorphous solid's line comes above, nearly three orders of magnitude more soluble.",
    text='''\
# The aluminium a water holds at saturation with gibbsite, at every pH: the
# solubility diagram PhreePlot draws from PHREEQC. 10 mM NaCl gives the water
# its ionic strength, under Davies' activity coefficients. The Diagrams tab
# sets the aluminium at each pH so that gibbsite's saturation index is 0, as
# PHREEQC's SOLUTION does with "Al 1 Gibbsite 0"; amorphous Al(OH)3 is in
# <PHASES> too, to be named beside it. phreeqc.dat's constants at 25 C.
<SETTINGS>
MODE = batch
TEND = 1
ACTIVITY = davies
EQUILIBRATE = 1

<SPECIES>
H+        1e-7
OH-       1e-7
Na+       1e-2
Cl-       1e-2
Al+3      1e-9
AlOH+2    0
Al(OH)2+  0
Al(OH)3   0
Al(OH)4-  0

<EQUILIBRIUM>
 <=> H+ + OH-,                       logK = -14
Al+3 + H2O <=> AlOH+2 + H+,          logK = -5
Al+3 + 2 H2O <=> Al(OH)2+ + 2 H+,    logK = -10.1
Al+3 + 3 H2O <=> Al(OH)3 + 3 H+,     logK = -16.9
Al+3 + 4 H2O <=> Al(OH)4- + 4 H+,    logK = -22.7

<PHASES>
Gibbsite + 3 H+ <=> Al+3 + 3 H2O,     logK = 8.11
Al(OH)3(a) + 3 H+ <=> Al+3 + 3 H2O,   logK = 10.8
''',
    view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'pH', 'sp': '', 'from': '4', 'to': '10', 'n': '121'},
                                               'y': {'kind': 'sat', 'sp': '', 'from': '-12', 'to': '16', 'n': '41', 'phases': 'Gibbsite'},
                                               'show': 'solubility', 'el': 'Al', 'in': 'water', 'q': 'pH', 'satAt': 0}},
))


_after('salinisation', dict(
    id='sodicwater',
    group='What the water is made of',
    label='Sodic water on a soil: a Wilcox diagram',
    about="A sodic well water — sodium and bicarbonate, little calcium — onto a soil with calcite and an exchanger. Run it: the Composition tab draws the water leaving the soil on Wilcox's diagram, excellent to good while the exchanger takes the sodium and lets calcium go, then doubtful to unsuitable as the well water comes through; the USSL diagram of the same waters, from the conductance <CONDUCTANCE> gives, is on the Show menu.",
    text='''# A sodic well water -- sodium and bicarbonate, little calcium -- onto a soil
# whose water is calcium and bicarbonate, with calcite and an exchanger. The
# exchanger takes the sodium and lets calcium go for as long as it can, and
# then the well water comes through as it is. The Composition tab draws the
# water leaving the soil on Wilcox's diagram, from excellent to good to where
# the well water's sodium puts it; the USSL diagram of the same waters, from
# the conductance <CONDUCTANCE> gives, is on the Show menu. The constants are
# phreeqc.dat's; the waters are made up, and D stands for the dispersion.
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
TEND = 1.2e5

<SPECIES>
Ca+2      1.5e-3   D=1e-7  left=2e-4
Mg+2      5e-4     D=1e-7  left=1e-4
Na+       5e-4     D=1e-7  left=1.2e-2
K+        5e-5     D=1e-7  left=1e-4
Cl-       5e-4     D=1e-7  left=2.5e-3
SO4-2     2e-4     D=1e-7  left=1e-3
HCO3-     3.4e-3   D=1e-7  left=8e-3
CO3-2     1e-6     D=1e-7  left=2e-5
CO2       2e-4     D=1e-7  left=3e-4
CaHCO3+   0        D=1e-7
CaCO3     0        D=1e-7
MgHCO3+   0        D=1e-7
CaSO4     0        D=1e-7
MgSO4     0        D=1e-7
NaSO4-    0        D=1e-7
NaHCO3    0        D=1e-7
H+        3e-8     D=1e-7  left=5e-9
OH-       3e-7     D=1e-7  left=2e-6
Calcite   0.01     mineral
X-        exchanger 1e-2
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
Na+ + HCO3- <=> NaHCO3, logK = -0.25
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
NaHCO3    gfw 84.0071  dw 6.73e-10
H+        gfw 1.008  dw 9.31e-9 838 6.96 -2.285 0.206 24.01 0  viscosity 0.0935 -0.0831 0.02487 0.000449 0.0201 1.57
OH-       gfw 17.008  dw 5.27e-9 478 0.8695  viscosity -0.0226 0.106 0.02184 -0.0032 0 0.4082 -1.634
H2O       gfw 18.016
''',
    view={'tab': 'composition', 'comp': {'view': 'wilcox', 'along': 'time', 'cell': 19}},
), dict(
    id='salinitypca',
    group='What the water is made of',
    label='Salty water into a fresh aquifer: principal components',
    about="The salty water and the aquifer of the Piper path. Run it: the Composition tab's principal components of the outlet's water, from its pH and each element dissolved, as their logs: the first, near nine tenths of the variance, is the salt coming through; the water bows out along the second where the calcium peaks as the exchanger lets it go, the calcium's arrow pointing there.",
    text=_retitled(_text('salinisation'), '''# Salty water into a fresh aquifer with calcite and an exchanger, as in the
# Piper path: sodium and magnesium take the exchanger, calcium comes off it.
# The Composition tab's principal components of the water at the outlet: the
# first the salt coming through, the second the calcium peak. The constants
# are phreeqc.dat's; the waters and the measurements are made up, and D stands
# for the dispersion.'''),
    view={'tab': 'composition', 'comp': {'view': 'pca', 'along': 'time', 'cell': 19, 'pcaVars': '', 'pcaLog': True}},
))

_after('ratesweep', dict(
    id='calcitefit',
    group='Fitting and uncertainty',
    label='Calcite at a rate: kc and the CO2 fitted',
    about="Calcite dissolving at a rate into water that holds CO2, as in Reading a run, its rate constant kc and its CO2 at the start fitted to the made-up measurements of pH and calcium in <DATA>, as PhreePlot fits PHREEQC. Run it: the Fit tab moves them from 1e-4 and 5e-4 until the run meets the measurements as nearly as it can — about 5.1e-4 and 1.0e-3 — and gives their standard errors and their correlation, with the run at the fitted numbers beside the measurements.",
    text=_retitled(_text('calciterate'), '''# Calcite dissolving at a rate into water that holds CO2, its rate constant kc
# and its CO2 at the start fitted to the measurements of pH and calcium below:
# the Fit tab moves them from 1e-4 and 5e-4 until the run is as near as it can
# be to what <DATA> measured. The constants are phreeqc.dat's; the rate and the
# measurements are made up.'''),
    view={'tab': 'fit', 'fit': {'params': [{'what': 'parameter:kc', 'start': '1e-4'}, {'what': 'initial:CO2', 'start': '5e-4'}],
                                'off': []}, 'go': True},
), dict(
    id='frontuncertainty',
    group='Fitting and uncertainty',
    label='A sorbing front: its uncertainty',
    about="A sorbing radionuclide and a tracer through a column, the sorbing one's retardation factor and the flow uncertain. Run it: the Uncertainty tab draws Rf from a lognormal distribution about 4, a factor of 1.5 either way, and the velocity from a normal one about 1e-6 m/s, ten per cent either way, runs the column a hundred times by Latin hypercube, and draws the sorbing one at the outlet as bands, with the model as written through them; the spread of one value and what matters most, by rank correlation, are on its Show menu.",
    text='''# A sorbing radionuclide and a tracer through a column: the sorbing one is
# held back by its retardation factor Rf, the tracer is not. How uncertain is
# the sorbing one's breakthrough when Rf and the flow are? The Uncertainty
# tab draws Rf from a lognormal distribution about 4 and the velocity from a
# normal one about 1e-6 m/s, runs the column for each draw -- a hundred, by
# Latin hypercube -- and draws Y at the outlet as bands: half the runs within
# the inner one, nine tenths within the outer, and their median. The numbers
# are made up, and D stands for the dispersion.

<SETTINGS>
MODE = transport
CELLS = 50
LENGTH = 1.0
DIFFUSION = 1
ADVECTION = 1
VELOCITY = 1.0E-6
LEFT = robin
RIGHT = free
TEND = 1.0E7

<SPECIES>
X  0.0  D=2.0E-8  left=1.0          # a tracer
Y  0.0  D=2.0E-8  left=1.0  R=Rf    # sorbing, held back by Rf

<PARAMETERS>
Rf  all  4

<REACTIONS>
''',
    view={'tab': 'uncertainty', 'unc': {'rows': [{'what': 'parameter:Rf', 'family': 'lognormal', 'a': '4', 'b': '1.5', 'c': ''},
                                                {'what': 'setting:VELOCITY', 'family': 'normal', 'a': '1e-6', 'b': '1e-7', 'c': ''}],
                                       'n': '100', 'scheme': 'lhs', 'seed': '1', 'cell': 49, 'show': 'time', 'key': 'Y', 'of': 'end',
                                       'logT': False, 'logY': False},
          'go': True},
), dict(
    id='inversecolumn',
    group='Through PHREEQC',
    label="Calcite and gypsum: PHREEQC's inverse model",
    about="Water with CO2 in it through a column of calcite and gypsum, written from PHREEQC: each dissolves to saturation and the water leaves with what they gave it. Run it: the PHREEQC tab's inverse model between the water flowing in and the outlet's at the end gives back what the column dissolved — 1.268e-3 mol/kgw of calcite and 1.470e-2 of gypsum, the run's own to the four figures PHREEQC prints — with how far each could go at 5 %. PHREEQC is fetched the first time it is used.",
    text='''# Water with CO2 in it through a column of calcite and gypsum: each dissolves
# to saturation in every cell, and the water leaves with the calcium, the
# carbonate and the sulfate they gave it. Run it: the PHREEQC tab's inverse
# model between the water flowing in and the water at the outlet gives back
# how much of each the column dissolved, to the four figures PHREEQC prints.
# Written from PHREEQC by From PHREEQC... on the Model tab (the relations held
# exactly, the phases kept), from this input to phreeqc.dat:
#   SOLUTION 0  water with CO2 in it        SOLUTION 1-10  the column's water
#    units mmol/kgw; pH 4.5 charge           units mmol/kgw; pH 7 charge
#    Na 1; Cl 1; C(4) 2                      Na 1; Cl 1
#   EQUILIBRIUM_PHASES 1-10: Calcite 0 0.5; Gypsum 0 0.5
#   TRANSPORT: -cells 10, -lengths 0.01, -shifts 100, -time_step 1000,
#    -dispersivities 0.01, -diffusion_coefficient 0
# A hundred shifts are ten pore volumes, which leave none of the column's
# first water at the outlet to be taken for something the minerals did.

<SETTINGS>
MODE = transport
CELLS = 10
LENGTH = 0.1
DIFFUSION = 1
ADVECTION = 1
ADVECTION_SCHEME = limited
VELOCITY = 0.00001
PECLET = 10
LEFT = robin
RIGHT = free
TEND = 100000
TIME_UNIT = second
EQUILIBRATE = always
ACTIVITY = debye-huckel
TEMPERATURE = 25

<SPECIES>
H+       1.0418985597979e-9      a=9  b=0  left=0.0000306593623849765
OH-      0.0000137509137905349   a=3.5  b=0  left=3.54324005786337e-10
Ca+2     0.0105696963338049      a=5  b=0.165  left=1.51935710034064e-14
SO4-2    0.0104795001243387      a=5  b=-0.04  left=1.49243808631723e-14
CaSO4    0.00461017623357934     left=3.02798833888261e-26
Cl-      0.000999453835837602    a=3.63  b=0.017  left=0.000999990169325606
Na+      0.000923986146512614    a=4.08  b=0.082  left=0.000999975169643162
NaSO4-   0.00007545968144215     a=5.5  b=0  left=2.10430055551905e-16
HCO3-    0.0000145611636568978   a=5.4  b=0  left=0.0000306438981520566
CaCO3    0.00000550816911404106  left=1.0355851167145e-21
CO3-2    0.00000130113928160075  a=5.4  b=0  left=5.39951746409692e-11
CaOH+    0.0000011587286746389   left=7.65039749016765e-23
CaHCO3+  2.90084162828088e-7     a=6  b=0  left=1.55649803173546e-18
CO2      2.43909485825177e-8     b=0.066  left=0.0019691888523922
NaHCO3   8.00812779576895e-9     b=0.2  left=2.48325930946573e-8
HSO4-    5.2943386670754e-10     left=3.86128601949146e-17
CaHSO4+  3.3045059735033e-11     left=6.11431785102803e-30
HCl      2.43576592777162e-13    b=0.4256  left=9.83067439395726e-9
H2       3.74802355074833e-17    left=1.01893883343386e-39
CO2_2    1.09545887917615e-17    left=7.11814327794138e-8
O2       5.40132007425576e-27    left=4.01176110779945e-15
Calcite  0.499705225091214       mineral
Gypsum   0.484561781430842       mineral

<EQUILIBRIUM>
Ca+2 + SO4-2 <=> CaSO4,          logK = 2.2500000000, dH = 5.5438                                        # here 1.6193
Na+ + SO4-2 <=> NaSO4-,          analytic = 255.903 0.10057 0 -111.138 -859830                           # here 0.8917
CO3-2 + H+ <=> HCO3-,            analytic = 107.8871 0.03252849 -5151.79 -38.92561 563713.9              # here 10.0310
H2O <=> OH- + H+,                analytic = 293.29227 0.1360833 -10576.913 -123.73158 0 -0.00006996455   # here -13.8438
Ca+2 + CO3-2 <=> CaCO3,          analytic = -1228.732 -0.29944 35512.75 485.818                          # here 2.6026
Ca+2 + H2O <=> CaOH+ + H+,       logK = -12.7800000000                                                   # here -12.9423
Ca+2 + CO3-2 + H+ <=> CaHCO3+,   analytic = -6.008999999999999 0.03377 2044                              # here 10.3063
CO3-2 + 2 H+ <=> CO2 + H2O,      analytic = 464.1965 0.09344813 -26986.16 -165.75951 2248628.9           # here 16.2373
Na+ + HCO3- <=> NaHCO3,          logK = -0.0600000000, dH = 21                                           # here -0.2253
SO4-2 + H+ <=> HSO4-,            analytic = -56.889 0.006473 2307.9 19.8858                              # here 1.6856
Ca+2 + HSO4- <=> CaHSO4+,        logK = 1.0800000000                                                     # here 0.7712
H+ + Cl- <=> HCl,                analytic = 0.33399999999999946 -0.002684 1.015                          # here -0.6310
2 CO2 <=> CO2_2,                 analytic = 8.679999999999891 -0.0103 -2190                              # here -1.7349
Calcite <=> CO3-2 + Ca+2,        analytic = 17.118 -0.046528 -3496                                       # here -7.8616
Gypsum <=> Ca+2 + SO4-2 + 2 H2O, analytic = 93.7 0.00599 -4000 -35.019                                   # here -3.9556
''',
    view={'tab': 'phreeqc', 'pqInv': {'from': 'inflow', 'fromAt': 'start', 'to': '9', 'toAt': 'end', 'phases': 'Calcite, Gypsum',
                                      'u': '0.05', 'range': True, 'minimal': True, 'db': 'builtin', 'fill': False}, 'go': True},
))


# ---------------------------------------------------------------------------
# What matters, by sensitivity indices, and a Durov diagram: each opens, once
# run, on the view that shows it.
# ---------------------------------------------------------------------------
_after('salinitypca', dict(
    id='freshening',
    group='What the water is made of',
    label='Fresh water through a salty aquifer: a Durov diagram',
    about="Fresh water, calcium and bicarbonate, through an aquifer that still holds brackish water, with calcite and an exchanger loaded from it — the Piper path the other way round. Run it: the Composition tab draws the outlet's water on a Durov diagram, from Na–Cl through Na–HCO₃, the exchanger giving up its sodium for the fresh water's calcium and the pH rising near 9, and Mg–HCO₃ to Ca–HCO₃, a freshening aquifer's sequence, beside waters measured there; the pH is under the square, and the total dissolved solids, falling from near 3700 mg/kgw to 500, to its right. Against time draws the outlet's calcium, magnesium, sodium and chloride in mg/kgw, each by its atomic weight, beside the same measurements.",
    text='''# Fresh water, calcium and bicarbonate, through an aquifer that still holds
# brackish water, with calcite and an exchanger loaded from it: the exchanger
# gives up its sodium, then its magnesium, for the fresh water's calcium, and
# calcite dissolves where the calcium is taken. The water at the outlet goes
# from Na-Cl through Na-HCO3, its pH near 9, and Mg-HCO3 to Ca-HCO3, the
# sequence of an aquifer freshening. The Composition tab draws its path on a
# Durov diagram, the pH under the square and the total dissolved solids to its
# right, beside waters measured at the outlet. The constants are
# phreeqc.dat's; the waters and the measurements are made up, and D stands
# for the dispersion.
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
TEND = 6e5

<SPECIES>
Ca+2      1e-3     D=1e-7  left=2.5e-3
Mg+2      5.3e-3   D=1e-7  left=5e-4
Na+       4.9e-2   D=1e-7  left=6e-4
K+        1e-3     D=1e-7  left=1e-4
Cl-       5.5e-2   D=1e-7  left=7e-4
SO4-2     2.8e-3   D=1e-7  left=3e-4
HCO3-     2e-3     D=1e-7  left=5.4e-3
CO3-2     1e-5     D=1e-7  left=1e-5
CO2       1e-4     D=1e-7  left=5e-4
CaHCO3+   0        D=1e-7
CaCO3     0        D=1e-7
MgHCO3+   0        D=1e-7
CaSO4     0        D=1e-7
MgSO4     0        D=1e-7
NaSO4-    0        D=1e-7
NaHCO3    0        D=1e-7
H+        3e-8     D=1e-7  left=1e-7
OH-       3e-7     D=1e-7  left=1e-7
Calcite   0.05     mineral
X-        exchanger 6e-2
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
Na+ + HCO3- <=> NaHCO3, logK = -0.25
Calcite <=> Ca+2 + CO3-2, logK = -8.48
Na+ + X- <=> NaX, logK = 0
Ca+2 + 2 X- <=> CaX2, logK = 0.8
Mg+2 + 2 X- <=> MgX2, logK = 0.6
K+ + X- <=> KX, logK = 0.7

<DATA>
time   tot(Ca)  tot(Mg)  tot(Na)  K+       Cl-      tot(S)   alk(CO3)  cell = 19
1e4    1.0e-3   5.5e-3   5.0e-2   1.0e-3   5.6e-2   2.7e-3   2.1e-3
4.5e4  7e-5     1.6e-4   8.4e-3   2.0e-4   1.0e-3   3.1e-4   7.0e-3
1e5    5.6e-4   2.5e-3   1.0e-3   2.4e-4   7.5e-4   3.0e-4   5.9e-3
4e5    2.3e-3   5.2e-4   6.5e-4   1.0e-4   7.0e-4   3.0e-4   5.4e-3
''',
    view={'tab': 'composition', 'comp': {'view': 'durov', 'along': 'time', 'cell': 19, 'logT': False},
          'picked': ['tot(Ca)', 'tot(Mg)', 'tot(Na)', 'Cl-'], 'cell': 19, 'logT': False, 'logY': True, 'unit': 'mg'},
))

_after('frontuncertainty', dict(
    id='nuclideindices',
    group='Fitting and uncertainty',
    label='A decaying nuclide: what matters, by sensitivity indices',
    about="A nuclide with a half-life of 30 years through ten metres of a rock it sorbs on, four of its numbers uncertain: its retardation factor, the water's velocity, the dispersivity and the concentration flowing in. Run it: the Uncertainty tab runs the column three hundred times by Latin hypercube and works out how much each explains of what reaches the outlet by the end, beside a dummy drawn and never used: the retardation factor most and the velocity next, their first-order indices and deltas clear of the dummy's; the dispersivity and the concentration flowing in sit with it. The outlet's breakthrough as bands is on its Show menu.",
    text='''# A nuclide with a half-life of 30 years through ten metres of a rock it
# sorbs on: how much of it reaches the far end once the column is steady, and
# which of four uncertain numbers decides that? Its retardation factor Rf,
# the water's velocity, the dispersivity -- LENGTH/PECLET, a metre here -- and
# the concentration flowing in are each drawn from a distribution, three
# hundred times by Latin hypercube, and the Uncertainty tab's sensitivity
# indices say how much each explains of the outlet's concentration at the
# end, beside a dummy drawn and never used: the retardation factor most, the
# velocity next, both clear of the dummy, the other two with it. By the end
# the column is steady, and what reaches its outlet is what Wehner and
# Wilhelm's formula for these boundaries gives (1956), whose own first-order
# indices -- 0.71, 0.23, 0.01 and 0.004 -- are each inside the page's
# interval. Times are in years, so the velocity is in metres a year. The
# numbers are made up.

<SETTINGS>
MODE = transport
CELLS = 50
LENGTH = 10
TIME_UNIT = year
VELOCITY = 1
ADVECTION = 1
ADVECTION_SCHEME = limited
DIFFUSION = 1
PECLET = 10
LEFT = robin
RIGHT = free
TEND = 1000

<SPECIES>
Nuclide  0  left=1  R=Rf      # held back by its retardation factor

<PARAMETERS>
Rf  all  10

<REACTIONS>
# ln 2 / 30 a, in the water and on the rock alike.
Nuclide => , k = 0.023104906, on = inventory
''',
    view={'tab': 'uncertainty', 'unc': {'rows': [{'what': 'parameter:Rf', 'family': 'lognormal', 'a': '10', 'b': '2', 'c': ''},
                                                {'what': 'setting:VELOCITY', 'family': 'lognormal', 'a': '1', 'b': '1.5', 'c': ''},
                                                {'what': 'setting:PECLET', 'family': 'lognormal', 'a': '10', 'b': '2', 'c': ''},
                                                {'what': 'left:Nuclide', 'family': 'uniform', 'a': '0.9', 'b': '1.1', 'c': ''}],
                                       'n': '300', 'scheme': 'lhs', 'seed': '1', 'cell': 49, 'show': 'indices', 'key': 'Nuclide',
                                       'of': 'end', 'logT': True, 'logY': False},
          'go': True},
))


_after('pourbaix', dict(
    id='redoxladder',
    group='Equilibrium diagrams',
    label="A groundwater's redox ladder at pH 7",
    about="A groundwater with nitrogen, sulfate, carbonate and a little iron, phreeqc.dat's couples between their valence states. Run it: the Diagrams tab holds the water at pH 7 and at each pe and draws where each couple turns over — the pe at which the water holds as much of the element in the couple's oxidised state as in its reduced one — as a ladder: nitrate to nitrogen near pe 12, to nitrite and to ammonium near 7 and 6, ferric iron to ferrous near 4.5, sulfate to sulfide and carbonate to methane below −3.5, between where water itself gives way, O₂ above and H₂ below; and the water itself, at pe 4, dotted between iron and sulfate. Eh in place of pe draws the same in volts.",
    text='''# The redox ladder of a groundwater: where each of its couples turns over at
# pH 7, the pe at which the water holds as much of the element in the
# couple's oxidised state as in its reduced one. Nitrate goes first, to
# nitrogen near pe 12, then to nitrite and ammonium; ferric iron to ferrous
# near pe 4.5; sulfate to sulfide and carbonate to methane below -3.5: the
# order in which a water's oxidants are used up as it grows more reducing.
# The Diagrams tab holds the water at pH 7 and at each pe, its own totals,
# complexes and activities kept, and draws the ladder between where water
# itself gives way, O2 above and H2 below at 1 atm. The water itself is at
# pe 4: its nitrate gone to nitrogen, its iron ferrous, its sulfate not yet
# touched. The constants are phreeqc.dat's; the water is made up.

<SETTINGS>
MODE = batch
TEND = 1
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+        2e-7
OH-       5e-8
e-        electron  pe=4
Na+       2e-3
Ca+2      1.5e-3
Cl-       1e-3
NO3-      0
NO2-      0
N2        1e-4
NH4+      0
NH3       0
SO4-2     1e-3
HSO4-     0
HS-       0
H2S       0
CO3-2     0
HCO3-     2e-3
CO2       1e-3
CH4       0
CaHCO3+   0
CaSO4     0
Fe+2      1e-5
FeOH+     0
Fe+3      0
FeOH+2    0
Fe(OH)2+  0
Fe(OH)3   0
Fe(OH)4-  0

<EQUILIBRIUM>
H2O <=> H+ + OH-,                       logK = -14
NO3- + 2 H+ + 2 e- <=> NO2- + H2O,      logK = 28.57
2 NO3- + 12 H+ + 10 e- <=> N2 + 6 H2O,  logK = 207.08
NO3- + 10 H+ + 8 e- <=> NH4+ + 3 H2O,   logK = 119.077
NH4+ <=> NH3 + H+,                      logK = -9.252
SO4-2 + H+ <=> HSO4-,                   logK = 1.988
SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O,    logK = 33.65
HS- + H+ <=> H2S,                       logK = 6.994
CO3-2 + H+ <=> HCO3-,                   logK = 10.329
CO3-2 + 2 H+ <=> CO2 + H2O,             logK = 16.681
CO3-2 + 10 H+ + 8 e- <=> CH4 + 3 H2O,   logK = 41.071
Ca+2 + CO3-2 + H+ <=> CaHCO3+,          logK = 10.91
Ca+2 + SO4-2 <=> CaSO4,                 logK = 2.25
Fe+2 + H2O <=> FeOH+ + H+,              logK = -9.5
Fe+2 <=> Fe+3 + e-,                     logK = -13.02
Fe+3 + H2O <=> FeOH+2 + H+,             logK = -2.19
Fe+3 + 2 H2O <=> Fe(OH)2+ + 2 H+,       logK = -5.67
Fe+3 + 3 H2O <=> Fe(OH)3 + 3 H+,        logK = -12.56
Fe+3 + 4 H2O <=> Fe(OH)4- + 4 H+,       logK = -21.6
''',
    view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'pe', 'sp': '', 'from': '-8', 'to': '15', 'n': '231'},
                                               'y': {'kind': 'pHheld', 'sp': '', 'from': '7', 'to': '', 'n': '41'}, 'show': 'ladder',
                                               'el': '', 'in': 'water', 'q': 'pH'}},
))


_after('carbonate', dict(
    id='redoxzones',
    group='Chemistry',
    label="Redox zones: organic carbon through a groundwater's oxidants",
    about="Organic carbon oxidised in a groundwater at a steady rate, its electrons taken by the water's oxidants one after another, as PhreePlot draws a water titrated with organic carbon. Run it: the time chart draws the oxygen used up first, then the nitrate; manganese(2) and iron(2) appearing as pyrolusite and ferrihydrite dissolve; the sulfate reduced, its sulfide taking the iron(2) as FeS until the iron is gone; and methane last — each element's total in a valence state, as PHREEQC's TOT(\"Fe(2)\") gives it, in the order the redox ladder places their couples.",
    text='''# Organic carbon oxidised in a groundwater at a steady rate, a hundredth of a
# millimole a day, its electrons taken by the water's oxidants one after
# another: the oxygen, the nitrate to nitrogen, the manganese(4) of
# pyrolusite, the iron(3) of ferrihydrite, the sulfate to sulfide -- the
# ferrous iron and the sulfide meeting as FeS -- and last carbon to methane:
# the redox zones of a groundwater, in the order a redox ladder places their
# couples, as PhreePlot draws a water titrated with organic carbon. Each is
# drawn as its element's total in a valence state, tot(N(5)) as PHREEQC's
# TOT("N(5)"). Nitrogen gas is left inert, as it is in a groundwater: there is
# no ammonium here. FeS is the one mineral that can form. The constants are
# phreeqc.dat's; the water is made up.

<SETTINGS>
MODE = batch
TIME_UNIT = day
TEND = 160
MAX_STEP = 1          # a day at most, so that the chart draws each zone's turn
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+           2.2e-7
OH-          4.5e-8
e-           electron
Na+          1.5e-3
K+           5e-5
Ca+2         6e-4
Mg+2         2e-4
Cl-          6e-4
O2           2.5e-4
NO3-         1.5e-4
NO2-         0
N2           0
SO4-2        3e-4
HSO4-        0
HS-          0
H2S          0
CO3-2        0
HCO3-        1.8e-3
CO2          1e-3
CH4          0
Fe+2         0
FeOH+        0
Fe+3         0
FeOH+2       0
Fe(OH)2+     0
Fe(OH)3      0
Fe(OH)4-     0
Mn+2         0
Pyrolusite   1e-4   mineral
Ferrihydrite 2e-4   mineral
FeS_ppt      0      mineral

<EQUILIBRIUM>
H2O <=> H+ + OH-,                       logK = -14
2 H2O <=> O2 + 4 H+ + 4 e-,             logK = -86.08
NO3- + 2 H+ + 2 e- <=> NO2- + H2O,      logK = 28.57
2 NO3- + 12 H+ + 10 e- <=> N2 + 6 H2O,  logK = 207.08
SO4-2 + H+ <=> HSO4-,                   logK = 1.988
SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O,    logK = 33.65
HS- + H+ <=> H2S,                       logK = 6.994
CO3-2 + H+ <=> HCO3-,                   logK = 10.329
CO3-2 + 2 H+ <=> CO2 + H2O,             logK = 16.681
CO3-2 + 10 H+ + 8 e- <=> CH4 + 3 H2O,   logK = 41.071
Fe+2 + H2O <=> FeOH+ + H+,              logK = -9.5
Fe+2 <=> Fe+3 + e-,                     logK = -13.02
Fe+3 + H2O <=> FeOH+2 + H+,             logK = -2.19
Fe+3 + 2 H2O <=> Fe(OH)2+ + 2 H+,       logK = -5.67
Fe+3 + 3 H2O <=> Fe(OH)3 + 3 H+,        logK = -12.56
Fe+3 + 4 H2O <=> Fe(OH)4- + 4 H+,       logK = -21.6
Pyrolusite + 4 H+ + 2 e- <=> Mn+2 + 2 H2O,     logK = 41.38
Ferrihydrite + 3 H+ <=> Fe+3 + 3 H2O,          logK = 4.891
FeS_ppt + H+ <=> Fe+2 + HS-,                   logK = -3.915

<REACTIONS>
# CH2O, as it is oxidised: CO3-2 + 6 H+ + 4 e-, less 2 H2O. Its electrons go
# to whatever in the water takes them, as the couples have it.
=> CO3-2 + 6 H+ + 4 e-, k = 1e-5
''',
    view={'tab': 'time', 'picked': ['O2', 'tot(N(5))', 'Mn+2', 'tot(Fe(2))', 'tot(S(6))', 'tot(S(-2))', 'tot(C(-4))'], 'cell': 0,
          'logT': False, 'logY': False},
))


_after('redoxladder', dict(
    id='redoxcouples',
    group='Equilibrium diagrams',
    label="The same groundwater's couples across pH: a pe–pH diagram",
    about="The groundwater of the redox ladder, its couples traced across pH 4 to 10: each a line where the water holds as much of the element in the couple's oxidised state as in its reduced one, the ladder's rung at every pH. Run it: the Diagrams tab draws nitrate's three lines, ferric to ferrous, sulfate to sulfide and carbonate to methane on a pe–pH diagram, between where water itself gives way, O₂ above and H₂ below, the water itself marked at its pH and pe.",
    text=_retitled(_text('redoxladder'), '''# The groundwater of the redox ladder, its couples traced across pH 4 to 10:
# each a line where the water holds as much of the element in the couple's
# oxidised state as in its reduced one, the ladder's rung at every pH. The
# Diagrams tab draws them on a pe-pH diagram between where water itself gives
# way, O2 above and H2 below, the water itself marked at its pH and pe. The
# constants are phreeqc.dat's; the water is made up.'''),
    view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'pH', 'sp': '', 'from': '4', 'to': '10', 'n': '61'},
                                               'y': {'kind': 'pe', 'sp': '', 'from': '-10', 'to': '17', 'n': '55'}, 'show': 'couples',
                                               'el': '', 'in': 'water', 'q': 'pH'}},
))


_after('redoxzones', dict(
    id='redoxplume',
    group='Chemistry',
    label="Redox zones along a plume: leachate into an oxic aquifer",
    about="Leachate rich in organic carbon flowing into an oxic aquifer whose sediment holds pyrolusite, ferrihydrite and calcite, the organic carbon oxidised at a rate as it travels and its electrons taken by the couples. Run it: the Gradient tab draws the pe over time and distance as contours, the zones in space and moving downstream as each oxidant is used up -- from the inlet the leachate's sulfate reduced and then methane, the iron zone where ferrihydrite dissolves and siderite takes the iron(2), the manganese zone, the nitrate, and the oxic water ahead of the plume. Against distance draws what is ticked against time together at the end, on a log axis from 1e-10: the pe on the right, its steps the zones, and the oxygen, the nitrate, manganese(2), ferrihydrite and siderite, the sulfate, the methane and the organic carbon left, each rising or falling through its zone.",
    text='''# Leachate rich in organic carbon flowing into an oxic aquifer whose sediment
# holds pyrolusite, ferrihydrite and calcite: the organic carbon, CH2O, is
# oxidised at a rate as it travels, its electrons taken by the couples, and
# the zones form in space. From the inlet: the leachate's sulfate reduced,
# FeS taking the sulfide, then methane where the oxidants are used up; the
# iron zone, ferrihydrite dissolving and siderite taking the iron(2); the
# manganese zone; the nitrate; and the oxic water ahead of the plume. Each
# moves downstream as its oxidant is used up. Times are in days and the
# velocity in metres a day. The constants are phreeqc.dat's; the waters and
# the sediment are made up.

<SETTINGS>
MODE = transport
CELLS = 30
LENGTH = 30
VELOCITY = 0.5
TIME_UNIT = day
ADVECTION = 1
ADVECTION_SCHEME = limited
DIFFUSION = 1
PECLET = 100
LEFT = robin
RIGHT = free
TEND = 40
ACTIVITY = davies
EQUILIBRATE = always

<SPECIES>
H+           2.2e-7   left=2e-7
OH-          4.5e-8   left=5e-8
e-           electron
Na+          1.5e-3   left=9.5e-3
K+           5e-5     left=5e-5
Ca+2         6e-4     left=1e-3
Mg+2         2e-4     left=2e-4
Cl-          6e-4     left=3e-3
O2           2.5e-4   left=0
NO3-         1.5e-4   left=0
NO2-         0
N2           0
SO4-2        3e-4     left=2e-4
HSO4-        0
HS-          0
H2S          0
CO3-2        0
HCO3-        1.8e-3   left=1e-2
CO2          1e-3     left=5e-3
CH4          0
CaHCO3+      0
CaCO3        0
CH2O         0        left=3e-3     # the leachate's organic carbon
Fe+2         0
FeOH+        0
Fe+3         0
FeOH+2       0
Fe(OH)2+     0
Fe(OH)3      0
Fe(OH)4-     0
Mn+2         0
Pyrolusite   5e-4     mineral
Ferrihydrite 5e-3     mineral
Calcite      5e-3     mineral
FeS_ppt      0        mineral
Siderite     0        mineral

<EQUILIBRIUM>
H2O <=> H+ + OH-,                       logK = -14
2 H2O <=> O2 + 4 H+ + 4 e-,             logK = -86.08
NO3- + 2 H+ + 2 e- <=> NO2- + H2O,      logK = 28.57
2 NO3- + 12 H+ + 10 e- <=> N2 + 6 H2O,  logK = 207.08
SO4-2 + H+ <=> HSO4-,                   logK = 1.988
SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O,    logK = 33.65
HS- + H+ <=> H2S,                       logK = 6.994
CO3-2 + H+ <=> HCO3-,                   logK = 10.329
CO3-2 + 2 H+ <=> CO2 + H2O,             logK = 16.681
CO3-2 + 10 H+ + 8 e- <=> CH4 + 3 H2O,   logK = 41.071
Ca+2 + CO3-2 + H+ <=> CaHCO3+,          logK = 10.91
Ca+2 + CO3-2 <=> CaCO3,                 logK = 3.224
Fe+2 + H2O <=> FeOH+ + H+,              logK = -9.5
Fe+2 <=> Fe+3 + e-,                     logK = -13.02
Fe+3 + H2O <=> FeOH+2 + H+,             logK = -2.19
Fe+3 + 2 H2O <=> Fe(OH)2+ + 2 H+,       logK = -5.67
Fe+3 + 3 H2O <=> Fe(OH)3 + 3 H+,        logK = -12.56
Fe+3 + 4 H2O <=> Fe(OH)4- + 4 H+,       logK = -21.6
Pyrolusite + 4 H+ + 2 e- <=> Mn+2 + 2 H2O,     logK = 41.38
Ferrihydrite + 3 H+ <=> Fe+3 + 3 H2O,          logK = 4.891
Calcite <=> Ca+2 + CO3-2,                      logK = -8.48
FeS_ppt + H+ <=> Fe+2 + HS-,                   logK = -3.915
Siderite <=> Fe+2 + CO3-2,                     logK = -10.89

<PARAMETERS>
kdoc  all  0.05      # a day: a twentieth of the organic carbon oxidised each day

<REACTIONS>
# CH2O, as it is oxidised: CO3-2 + 6 H+ + 4 e-, less 2 H2O. Its electrons go
# to whatever in the water takes them, as the couples have it.
CH2O => CO3-2 + 6 H+ + 4 e-, r = kdoc*[CH2O]
''',
    view={'tab': 'gradient', 'grad': {'species': 'pe', 'view': 'contour', 'logT': False},
          'profile': {'species': '*ticked', 'times': '', 'log': True, 'from': '1e-10'},
          'picked': ['pe', 'O2', 'tot(N(5))', 'Mn+2', 'Ferrihydrite', 'Siderite', 'tot(S(6))', 'tot(C(-4))', 'tot(C(0))'],
          'logT': False, 'logY': True, 'yFrom': '1e-10'},
))


_after('calcitefit', dict(
    id='zincfit',
    group='Fitting and uncertainty',
    label='Zinc on ferrihydrite: its sorption edge fitted',
    about="Zinc and a ferrihydrite surface, as in Zinc on ferrihydrite, with the share of the zinc on the surface measured at eight pHs, and again at a hundred times the zinc -- the second table's own water, Zn+2 = 1e-4 on its line -- each measurement with a standard deviation of 1 %, all made up for the purpose. Run it: the Fit tab moves the log K of the zinc on the strong sites and on the weak ones from phreeqc.dat's 0.99 and -1.99 until both edges go through what <DATA> measured, as PhreePlot fits sorption edges, and draws each edge through its measurements: 1.326 and -1.592, chi-square 8.1 on 14 degrees of freedom. The second edge, its strong sites full, pins the weak sites' constant down to half the standard error one edge leaves it.",
    text=_retitled(_text('sorptionedge'), '''# Zinc on ferrihydrite, its strong and weak sites as Dzombak and Morel give
# them, and the share of the zinc on the surface measured at eight pHs, in
# <DATA>: a table against pH is of the water held at each pH, as the Diagrams
# tab holds it. The Fit tab moves the log K of the zinc on each kind of site
# until the edges go through the measurements, as PhreePlot fits them, each
# measurement weighed by its standard deviation, sd(Zn_sorbed): the misfit is
# then chi-square. A second edge at a hundred times the zinc, Zn+2 = 1e-4 on
# its table's line, fills the strong sites and pins the weak sites' constant
# down. phreeqc.dat's constants; no double layer; the measurements and their
# deviations are made up.''') + '''
<OUTPUT>
Zn_sorbed = 100 * ([Hfo_sOZn+] + [Hfo_wOZn+]) / ([Zn+2] + [ZnOH+] + [Zn(OH)2] + [ZnCl+] + [Hfo_sOZn+] + [Hfo_wOZn+]),  unit = %

<DATA>
pH    Zn_sorbed   sd(Zn_sorbed)
4.5   0.5         1
5.0   2.7         1
5.5   17.3        1
6.0   36.1        1
6.5   72.0        1
7.0   93.4        1
7.5   99.1        1
8.0   99.5        1

pH    Zn_sorbed   sd(Zn_sorbed)   Zn+2 = 1e-4
4.5   0.6         1
5.0   1.1         1
5.5   4.7         1
6.0   13.4        1
6.5   47.1        1
7.0   75.2        1
7.5   90.6        1
8.0   95.0        1
''',
    view={'tab': 'fit', 'fit': {'params': [{'what': 'logK:Hfo_sOH + Zn+2 <=> Hfo_sOZn+ + H+', 'start': '0.99'},
                                           {'what': 'logK:Hfo_wOH + Zn+2 <=> Hfo_wOZn+ + H+', 'start': '-1.99'}], 'off': []}, 'go': True},
))


_after('pourbaix', dict(
    id='pourbaixsolids',
    group='Equilibrium diagrams',
    label='Iron and carbonate: an Eh–pH diagram with hematite and siderite',
    about="Iron at 1e-6 mol/kgw in a water with carbonate, its species dissolved and two of its solids from phreeqc.dat, hematite and siderite. Run it: the Diagrams tab holds the water at each pH and Eh and draws the species or the phase that holds most of the iron -- the textbook Pourbaix diagram with its solids: Fe+3 in acid and oxidising water, Fe+2 in acid and reducing, hematite over most of the rest, and siderite where reducing water meets the carbonate, between where water itself gives way.",
    text='''\
# Iron at 1e-6 mol/kgw in a water with carbonate, its species dissolved and
# two of its solids, hematite and siderite. The Diagrams tab holds the water
# at each pH and Eh and draws the species or the phase that holds most of the
# iron: where a solid is at saturation or over, the most stable of them per
# mole of iron; elsewhere the species dissolved holding most of it -- the
# Eh-pH diagram textbooks draw at a total of 1e-6, with where water itself
# gives way. phreeqc.dat's constants at 25 C.
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
CO2          1e-4
HCO3-        1e-3
CO3-2        1e-6
Fe+2         1e-6
Fe+3         0
FeOH+        0
Fe(OH)2      0
Fe(OH)3-     0
FeOH+2       0
Fe(OH)2+     0
Fe(OH)3      0
Fe(OH)4-     0
FeCO3        0
FeHCO3+      0

<EQUILIBRIUM>
 <=> H+ + OH-,                         logK = -14
CO2 + H2O <=> H+ + HCO3-,              logK = -6.352
HCO3- <=> H+ + CO3-2,                  logK = -10.329
Fe+2 <=> Fe+3 + e-,                    logK = -13.02
Fe+2 + H2O <=> FeOH+ + H+,             logK = -9.5
Fe+2 + 2 H2O <=> Fe(OH)2 + 2 H+,       logK = -20.57
Fe+2 + 3 H2O <=> Fe(OH)3- + 3 H+,      logK = -31
Fe+3 + H2O <=> FeOH+2 + H+,            logK = -2.19
Fe+3 + 2 H2O <=> Fe(OH)2+ + 2 H+,      logK = -5.67
Fe+3 + 3 H2O <=> Fe(OH)3 + 3 H+,       logK = -12.56
Fe+3 + 4 H2O <=> Fe(OH)4- + 4 H+,      logK = -21.6
Fe+2 + CO3-2 <=> FeCO3,                logK = 4.38
Fe+2 + HCO3- <=> FeHCO3+,              logK = 2

<PHASES>
Hematite + 6 H+ <=> 2 Fe+3 + 3 H2O,    logK = -4.008
Siderite <=> Fe+2 + CO3-2,             logK = -10.89
''',
    view={'tab': 'diagram', 'go': True, 'dg': {'cell': 0, 'at': 'start', 'x': {'kind': 'pH', 'sp': '', 'from': '0', 'to': '14', 'n': '141'},
                                               'y': {'kind': 'Eh', 'sp': '', 'from': '-0.8', 'to': '1.2', 'n': '81'}, 'show': 'mixed',
                                               'el': 'Fe', 'in': 'water', 'q': 'pH'}},
))


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
    # Today's date and a letter, the next letter on a day it was bumped already: a, b ... z, za, zb ... -- each later than the
    # one before, in a string's order too. The letter alone, past z, made a stamp of '{'.
    pat = re.compile(r'(rtm-examples\.js\?v=)([0-9]{8})([a-z]*)')
    if pat.search(src):
        today = datetime.date.today().strftime('%Y%m%d')

        def bump(m):
            s = m.group(3)
            if m.group(2) != today or not s:
                return m.group(1) + today + 'a'
            return m.group(1) + today + (s + 'a' if s[-1] == 'z' else s[:-1] + chr(ord(s[-1]) + 1))
        page.write_text(pat.sub(bump, src))

    kb = OUT.stat().st_size / 1024
    print(f'{OUT.relative_to(ROOT)}: {len(examples)} examples, {kb:.0f} kB')
    for g in dict.fromkeys(e['group'] for e in examples):
        print(f'  {g}: ' + ', '.join(e['id'] for e in examples if e['group'] == g))


main()
