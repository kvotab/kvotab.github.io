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


# ---------------------------------------------------------------------------
# Diffusion into the rock against the exact solution: the profile into a slab
# held at C0 on one face and closed on the other, under <DATA> in depth.
# ---------------------------------------------------------------------------
def _slab(y, t, dp, d):
    """C/C0 at depth y and time t in a slab of depth d, held at C0 at y = 0 and closed at y = d, by the method of
    images (Crank 1975, chapter 4): a sum of erfc terms, which keeps its precision where the profile is small, where
    1 - (the trigonometric series) is all cancellation."""
    import math
    s2 = 2 * math.sqrt(dp * t)
    c = 0.0
    for n in range(400):
        term = math.erfc((2 * n * d + y) / s2) + math.erfc((2 * (n + 1) * d - y) / s2)
        c += -term if n % 2 else term
        if term == 0 or (n > 2 and term < 1e-17 * c):
            break
    return c


def _slab_data():
    de, eps, d = 3.15576e-5, 0.005, 0.5        # m2/a (1e-12 m2/s), the porosity, m
    depths = [0, 0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.08, 0.1, 0.12, 0.15, 0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5]
    out = []
    for t in (0.25, 1, 4):
        out.append(f'depth  X  cell = 0  at = {t}')
        # To where the profile falls below a hundredth of the fracture's water.
        out.extend(f'{y:<6g} {c:.6g}' for y, c in ((y, _slab(y, t, de / eps, d)) for y in depths) if c >= 0.01)
    return '\n'.join(out)


_after('matrixtracer', dict(
    id='rockdiffusion',
    group='Dual porosity',
    label='Diffusion into the rock, against the exact solution',
    about='A tracer diffusing from a fracture whose water is held at 1 into half a metre of rock, closed at its far face, against the exact profile into such a slab, under <DATA> as tables in depth behind cell 0 at a quarter of a year, one and four, to where it falls below a hundredth. Run it: Against distance draws the rock behind cell 0 with the exact points, and the Fit tab\'s the run against what was measured, one to one, gives the Nash–Sutcliffe efficiency, 0.99998 on these 30 layers from a first of 1 mm.',
    text='''\
# A tracer diffusing into the rock from a fracture whose water is held at 1:
# half a metre of rock, closed at its far face, its effective diffusivity
# De = 1e-12 m2/s (3.15576e-5 m2/a here, the time in years) and its porosity
# 0.005, so that the tracer moves through its pore water at De/0.005. The
# exact profile into such a slab, by the method of images,
#     C/C0 = sum over n of (-1)^n [erfc((2nd + y)/(2 sqrt(Dp t)))
#                                  + erfc((2(n+1)d - y)/(2 sqrt(Dp t)))]
# (Crank 1975, chapter 4; Dp = De/porosity, d the depth), is under <DATA> as
# tables in depth behind cell 0, at a quarter of a year, one and four. Run it:
# Against distance draws the rock behind cell 0 with the exact points beside
# the run, and the Fit tab's the run against what was measured, one to one,
# gives the Nash-Sutcliffe efficiency.
#
# The tables stop where the profile falls below a hundredth of the fracture's
# water. Further in, the layers are centimetres thick beside a tail that falls
# tenfold in a few centimetres, and the run's tail lies above the exact one:
# at a quarter of a year, twice it where it is a ten-thousandth (tick log
# concentration to see it).
#
# MATRIX_FIRST sets the first layer at 1 mm: with no flow and no decay, nothing
# in the model sizes it, and left alone it would start at a millionth of the
# depth, finer than the profile needs and coarser further in (0.9987 against
# the exact points; 0.99998 with the millimetre). The 30 layers grow from it
# to the far face. Fewer, or a first layer much thinner or thicker than a
# fortieth of how far the tracer has got by the first table (some 4 cm), and
# the run falls further from the exact profile.

<SETTINGS>
MODE = transport
CELLS = 2
LENGTH = 2
ADVECTION = 0
DIFFUSION = 0
MATRIX_CELLS = 30
MATRIX_DEPTH = 0.5
MATRIX_FIRST = 0.001
MATRIX_POROSITY = 0.005
APERTURE = 0.0001
TEND = 4
TIME_UNIT = year

<SPECIES>
X  0  De=3.15576e-5     # m2/a: 1e-12 m2/s

<INITIAL>
X  all  1  fixed        # the fracture's water held at 1; the rock starts at 0

<REACTIONS>

<DATA>
''' + _slab_data() + '\n',
    view={'tab': 'profile', 'profile': {'species': 'X', 'times': '0.25, 1, 4', 'axis': 'matrix', 'layer': 0, 'log': False}},
))

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
# PHREEQC's own column beside the run: the model written from an input with a
# TRANSPORT, PHREEQC's cells under <DATA>, the Fit tab's Nash-Sutcliffe.
# ---------------------------------------------------------------------------
_after('inversecolumn', dict(
    id='besidecolumn',
    group='Through PHREEQC',
    label="Fresh water through a salty column with calcite, beside PHREEQC's own",
    about="A fresh water pushes a salty one through 2 m of a column with calcite, written from PHREEQC with PHREEQC's own column, to set beside the run, ticked: PHREEQC's TRANSPORT of the same input is under <DATA>, its cells at ten times. Run it: Against distance draws PHREEQC's cells as points beside the run's calcium, and the Fit tab's the run against what was measured, one to one, gives each column's Nash–Sutcliffe efficiency, 0.999 for the pH and every total on these 40 cells. The calcite, in excess, hardly changes: its efficiency is small however close the two are.",
    text='''# A fresh water pushes a salty one through 2 m of a column with calcite, the
# calcite in every cell at saturation, the salty water diluted as it goes and
# calcite dissolving a little where the two mix, the pH rising to the fresh
# water's. Written from PHREEQC by From PHREEQC... on the Model tab (the
# relations held exactly, the phases kept) with PHREEQC's own column, to set
# beside the run, ticked: PHREEQC ran the input's TRANSPORT as well, and its
# cells are under <DATA> at the end, a table in distance at each of ten times.
# Run it, and they are the points beside the run; the Fit tab's Show, the run
# against what was measured, one to one, gives each column's Nash-Sutcliffe
# efficiency: 0.999 for the pH and every total on these 40 cells, the two
# schemes meeting as the cells are refined. The input, to phreeqc.dat:
#   SOLUTION 0  a fresh water, flowing in    SOLUTION 1-40  a salty water
#    units mmol/kgw; pH 8.4                   units mmol/kgw; pH 7.8
#    Na 0.2; Ca 0.3; C(4) 0.6; Cl charge      Na 60; Ca 2; C(4) 1.5; Cl charge
#   brought to saturation with calcite first  EQUILIBRIUM_PHASES 1-40: Calcite 0 1
#   TRANSPORT: -cells 40, -lengths 0.05, -shifts 80, -time_step 1577880,
#    -diffusion_coefficient 1e-9, -dispersivities 0.01, -punch_frequency 8

<SETTINGS>
MODE = transport
CELLS = 40
LENGTH = 2
DIFFUSION = 1
ADVECTION = 1
ADVECTION_SCHEME = limited
VELOCITY = 3.1688087814029e-8
PECLET = 200
LEFT = robin
RIGHT = free
TEND = 127019340
TIME_UNIT = second
EQUILIBRATE = always
ACTIVITY = debye-huckel
TEMPERATURE = 25

<SPECIES>
H+       1.68046985326473e-8     a=9  b=0  D=1e-9  left=2.21453154300016e-9
OH-      9.00457151494907e-7     a=3.5  b=0  D=1e-9  left=0.0000049223967134953
Cl-      0.0625267847827729      a=3.63  b=0.017  D=1e-9  left=0.000191861549662591
Na+      0.0599532310679241      a=4.08  b=0.082  D=1e-9  left=0.000199904670258228
Ca+2     0.00199556919941082     a=5  b=0.165  D=1e-9  left=0.000307951968415587
HCO3-    0.00140410424951514     a=5.4  b=0  D=1e-9  left=0.000590639540796665
NaHCO3   0.0000467734466264255   b=0.2  D=1e-9  left=9.53463158108196e-8
CO2      0.0000360438976119392   b=0.066  D=1e-9  left=0.00000273220089836545
CO3-2    0.00000866024554271369  a=5.4  b=0  D=1e-9  left=0.0000145062962139732
CaCO3    0.00000547927962419258  D=1e-9  left=0.00000556166605960952
CaHCO3+  0.00000471098366244234  a=6  b=0  D=1e-9  left=6.03865670723928e-7
CaOH+    1.27254329282809e-8     D=1e-9  left=2.1393077796564e-8
HCl      2.27504812358149e-10    b=0.4256  D=1e-9  left=1.35761737058884e-13
CO2_2    2.39625487592276e-11    D=1e-9  left=1.37031594833731e-13
H2       2.58044983655888e-15    D=1e-9  left=0
O2       3.16637531429213e-23    D=1e-9  left=3.16633353073568e-11
Calcite  0.999994303209499       mineral

<EQUILIBRIUM>
CO3-2 + H+ <=> HCO3-,          analytic = 107.8871 0.03252849 -5151.79 -38.92561 563713.9              # here 9.9844
Na+ + HCO3- <=> NaHCO3,        logK = -0.0600000000, dH = 21                                           # here -0.2552
CO3-2 + 2 H+ <=> CO2 + H2O,    analytic = 464.1965 0.09344813 -26986.16 -165.75951 2248628.9           # here 16.1684
Ca+2 + CO3-2 <=> CaCO3,        analytic = -1228.732 -0.29944 35512.75 485.818                          # here 2.5011
Ca+2 + CO3-2 + H+ <=> CaHCO3+, analytic = -6.009 0.03377 2044                                          # here 10.2101
H2O <=> OH- + H+,              analytic = 293.29227 0.1360833 -10576.913 -123.73158 0 -0.00006996455   # here -13.8201
Ca+2 + H2O <=> CaOH+ + H+,     logK = -12.7800000000                                                   # here -12.9700
H+ + Cl- <=> HCl,              analytic = 0.3340000000000011 -0.002684 1.015                           # here -0.6645
2 CO2 <=> CO2_2,               analytic = 8.679999999999891 -0.0103 -2190                              # here -1.7341
Calcite <=> CO3-2 + Ca+2,      analytic = 17.118 -0.046528 -3496                                       # here -7.7624

<VOLUMES>
OH-      -9.66  28.5  80  -22.9  1.89  0  1.09  0  0  1
Cl-      4.465  4.801  4.325  -2.847  1.748  0  -0.331  20.16  0  1
Na+      2.28  -4.38  -4.1  -0.586  0.09  4  0.3  52  -0.00333  0.566
Ca+2     -0.3456  -7.252  6.149  -2.479  1.239  5  1.6  -57.1  -0.00612  1
HCO3-    10.26  -2.92  -12.58  -0.241  2.23  0  -5.49  320  0.0283  1.144
NaHCO3   7.95  0  0  0  0.609
CO2      7.29  0.92  2.07  -1.23  -1.6
CO3-2    6.09  -2.78  -0.405  -5.3  5.02  0  0.169  101  -0.0138  0.9316
CaCO3    -0.243  -8.3748  9.0417  -2.4328  -0.03
CaHCO3+  30.19  0.01  5.75  -2.78  0.308  5.4
CO2_2    14.58  1.84  4.14  -2.46  -3.2
H2       6.52  0.78  0.12
O2       5.7889  6.3536  3.2528  -3.0417  -0.3943
Calcite  36.9

<CONDUCTANCE>
H+       gfw 1.008  dw 9.31e-9 838 6.96 -2.285 0.206 24.01 0  viscosity 0.0935 -0.0831 0.02487 0.000449 0.0201 1.57
OH-      gfw 17.008  dw 5.27e-9 478 0.8695  viscosity -0.0226 0.106 0.02184 -0.0032 0 0.4082 -1.634
Cl-      gfw 35.453  dw 2.033e-9 216 3.16 0.2071 0.7432  viscosity 0 0 0 0 0 0 1
Na+      gfw 22.9898  dw 1.33e-9 75 3.627 0 0.7037  viscosity 0.1387 -0.0866 0.0125 0.0145 0.0075 1.062
Ca+2     gfw 40.08  dw 7.92e-10 34 5.411 0 1.046  viscosity 0.359 -0.158 0.042 0.0015 0.00804 2.3
HCO3-    gfw 61.0191  dw 1.18e-9 -190 11.386  viscosity -0.6 1.366 -0.01216 0 0.03139 -1.135 1.253
NaHCO3   gfw 84.0089  dw 6.73e-10  viscosity -0.04 -2.717 0.0000167
CO2      gfw 44.0111  dw 1.92e-9 -120  viscosity 0.0068 0.0903 0.0327 0 0 0 0.18
CO3-2    gfw 60.0111  dw 9.55e-10 -103 2.246 0.0713 0.3686  viscosity -0.5 0.6521 0.00544 0.00106 -0.0218 1.208 -2.147
CaCO3    gfw 100.0911  dw 4.46e-10
CaHCO3+  gfw 101.0991  dw 5.06e-10
CaOH+    gfw 57.088
HCl      gfw 36.461  viscosity 0.921 -0.765 0.00832 0.000825 0.00253 4.223
CO2_2    gfw 88.0222  dw 1.92e-9 -120  viscosity 0.0136 0.1806 0.0327 0 0 0 0.36
H2       gfw 2.016  dw 5.13e-9
O2       gfw 32  dw 2.35e-9
H2O      gfw 18.016

<REACTIONS>
# Your kinetic reactions here, in the same species and units.

<DATA>
# PHREEQC's own TRANSPORT of the input this model was written from, run in the page: a cell of PHREEQC's
# after shift k as this model's cell half a time step later, at its centre.
# The run goes on to TEND = 127019340, half a time step past the last shift, where its last cells are read.
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 13411980
0.025  8.652807  0.0006282065  0.000340236  0.00112919  0.001099211  0.9999878
0.075  8.632679  0.0006414744  0.000365127  0.002034843  0.001968035  0.9999869
0.125  8.590672  0.0006675135  0.0004142793  0.003835794  0.003695748  0.9999918
0.175  8.527571  0.0007074161  0.0004898352  0.006613847  0.006360829  0.9999924
0.225  8.446784  0.0007633295  0.0005957477  0.01050971  0.01009826  0.9999926
0.275  8.354995  0.0008358898  0.0007331165  0.0155595  0.0149427  0.9999927
0.325  8.260525  0.0009227622  0.0008975372  0.02160196  0.02073943  0.9999928
0.375  8.170674  0.001018875  0.001079532  0.02829373  0.02715908  0.999993
0.425  8.090542  0.001117401  0.001266303  0.03516974  0.03375546  0.9999933
0.475  8.02298  0.001211119  0.001444231  0.04173118  0.04005007  0.9999936
0.525  7.968912  0.001293932  0.001601708  0.04754895  0.04563126  0.9999938
0.575  7.927813  0.001361947  0.001731241  0.05234236  0.05022974  0.999994
0.625  7.898192  0.001413866  0.001830244  0.05601106  0.05374925  0.9999941
0.675  7.878024  0.001450676  0.001900504  0.05861743  0.05624963  0.9999942
0.725  7.86511  0.00147489  0.001946751  0.06033427  0.05789665  0.9999942
0.775  7.857372  0.001489642  0.001974941  0.06138125  0.05890105  0.9999942
0.825  7.853057  0.001497951  0.001990821  0.0619712  0.05946702  0.9999942
0.875  7.850828  0.001502265  0.001999067  0.06227763  0.05976098  0.9999942
0.925  7.849767  0.001504324  0.002003004  0.06242392  0.05990132  0.9999942
0.975  7.849304  0.001505225  0.002004725  0.06248788  0.05996268  0.9999942
1.025  7.849119  0.001505583  0.002005411  0.06251338  0.05998715  0.9999942
1.075  7.849053  0.001505713  0.00200566  0.06252261  0.059996  0.9999942
1.125  7.849031  0.001505756  0.002005741  0.06252562  0.05999888  0.9999942
1.175  7.849024  0.001505768  0.002005764  0.06252649  0.05999973  0.9999942
1.225  7.849023  0.001505771  0.00200577  0.06252672  0.05999994  0.9999942
1.275  7.849022  0.001505772  0.002005772  0.06252677  0.05999999  0.9999942
1.325  7.849022  0.001505772  0.002005772  0.06252678  0.06  0.9999942
1.375  7.849022  0.001505772  0.002005772  0.06252678  0.06  0.9999942
1.425  7.849022  0.001505772  0.002005772  0.06252678  0.06  0.9999942
1.475  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.525  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.575  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.625  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.675  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.725  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.775  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.825  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.875  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.925  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
1.975  7.849022  0.001505772  0.002005772  0.06252679  0.06  0.9999942
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 26035020
0.025  8.669767  0.0006147451  0.0003152527  0.0002314114  0.0002379415  0.9999876
0.075  8.669088  0.0006154073  0.0003164709  0.0002747351  0.0002795034  0.9999864
0.125  8.667521  0.0006168609  0.00031915  0.0003702253  0.0003711104  0.9999911
0.175  8.664496  0.0006194584  0.0003239527  0.0005420543  0.0005359518  0.9999916
0.225  8.658925  0.0006238054  0.0003320263  0.0008324273  0.0008145164  0.9999919
0.275  8.649171  0.0006307086  0.000344916  0.001298883  0.001262003  0.9999922
0.325  8.633208  0.0006411389  0.0003644956  0.002011792  0.001945921  0.9999925
0.375  8.609024  0.0006562084  0.0003929102  0.003051614  0.002943458  0.9999928
0.425  8.575186  0.0006771043  0.0004324275  0.004502573  0.004335411  0.999993
0.475  8.531337  0.0007049598  0.000485182  0.006442667  0.006196609  0.9999931
0.525  8.478381  0.0007406749  0.0005528401  0.008931628  0.008584354  0.9999932
0.575  8.418314  0.0007847101  0.0006362333  0.01199835  0.01152636  0.9999932
0.625  8.3538  0.0008369064  0.0007350406  0.01563022  0.01501054  0.9999932
0.675  8.287697  0.0008963821  0.0008476062  0.01976691  0.018979  0.9999933
0.725  8.222662  0.0009615425  0.0009709516  0.0243006  0.02332833  0.9999933
0.775  8.160905  0.001030206  0.001100998  0.02908351  0.02791673  0.9999934
0.825  8.104084  0.001099829  0.001232974  0.03394191  0.03257757  0.9999935
0.875  8.053294  0.001167789  0.00136193  0.0386947  0.03713708  0.9999937
0.925  8.009112  0.001231669  0.001483285  0.04317301  0.04143327  0.9999938
0.975  7.971683  0.001289508  0.001593289  0.04723768  0.04533264  0.9999939
1.025  7.940799  0.001339962  0.001689352  0.05079143  0.04874188  0.999994
1.075  7.915992  0.001382367  0.001770167  0.05378429  0.05161303  0.9999941
1.125  7.896613  0.001416705  0.001835661  0.05621194  0.05394196  0.9999942
1.175  7.881909  0.001443491  0.001886786  0.05810834  0.05576124  0.9999942
1.225  7.871088  0.001463617  0.001925217  0.05953472  0.05712962  0.9999942
1.275  7.863377  0.001478177  0.001953032  0.0605675  0.0581204  0.9999942
1.325  7.858063  0.001488317  0.001972408  0.06128716  0.05881079  0.9999942
1.375  7.854528  0.001495112  0.001985394  0.0617696  0.05927361  0.9999942
1.425  7.85226  0.001499492  0.001993766  0.06208064  0.059572  0.9999942
1.475  7.850859  0.001502206  0.001998954  0.06227341  0.05975693  0.9999942
1.525  7.850026  0.001503821  0.002002043  0.0623882  0.05986706  0.9999942
1.575  7.84955  0.001504746  0.002003809  0.06245385  0.05993003  0.9999942
1.625  7.849289  0.001505253  0.002004779  0.06248988  0.0599646  0.9999942
1.675  7.849152  0.00150552  0.00200529  0.06250885  0.0599828  0.9999942
1.725  7.849083  0.001505654  0.002005547  0.06251842  0.05999198  0.9999942
1.775  7.849049  0.00150572  0.002005672  0.06252305  0.05999642  0.9999942
1.825  7.849034  0.00150575  0.002005729  0.06252518  0.05999847  0.9999942
1.875  7.849027  0.001505763  0.002005755  0.06252613  0.05999938  0.9999942
1.925  7.849024  0.001505768  0.002005765  0.06252652  0.05999975  0.9999942
1.975  7.849023  0.00150577  0.002005769  0.06252666  0.05999989  0.9999942
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 38658060
0.025  8.670337  0.0006141714  0.0003141986  0.0001939813  0.0002020336  0.9999876
0.075  8.6703  0.0006142089  0.0003142674  0.0001964207  0.0002043738  0.9999864
0.125  8.670216  0.0006142948  0.0003144252  0.000202023  0.0002097482  0.9999911
0.175  8.670054  0.0006144589  0.0003147267  0.0002127266  0.0002200165  0.9999916
0.225  8.669756  0.0006147565  0.0003152737  0.000232159  0.0002386587  0.9999918
0.275  8.669226  0.0006152747  0.0003162268  0.0002660472  0.0002711689  0.9999921
0.325  8.668309  0.0006161414  0.0003178229  0.0003228896  0.0003256996  0.9999923
0.375  8.666759  0.000617538  0.0003204  0.0004148725  0.0004139419  0.9999924
0.425  8.664189  0.0006197105  0.0003244199  0.0005588089  0.0005520251  0.9999925
0.475  8.660026  0.0006229786  0.0003304877  0.0007769626  0.0007613073  0.9999927
0.525  8.653474  0.0006277399  0.0003393642  0.001097616  0.001068921  0.9999928
0.575  8.643538  0.0006344714  0.0003519678  0.001555159  0.001507857  0.9999929
0.625  8.62912  0.0006437232  0.0003693602  0.002189468  0.002116372  0.999993
0.675  8.609193  0.0006561043  0.0003927136  0.003044406  0.002936543  0.9999932
0.725  8.582999  0.0006722552  0.00042325  0.004165316  0.004011869  0.9999933
0.775  8.550228  0.0006928025  0.0004621529  0.005595555  0.005383946  0.9999934
0.825  8.511106  0.0007182981  0.0005104507  0.007372266  0.007088405  0.9999934
0.875  8.466389  0.0007491455  0.0005688844  0.009521764  0.009150492  0.9999934
0.925  8.417254  0.0007855251  0.0006377764  0.01205508  0.01158079  0.9999934
0.975  8.36514  0.0008273332  0.000716921  0.01496429  0.01437169  0.9999934
1.025  8.311583  0.000874145  0.0008055196  0.01822026  0.01749526  0.9999934
1.075  8.258064  0.0009252108  0.000902172  0.02177231  0.02090286  0.9999935
1.125  8.205906  0.0009794889  0.001004933  0.02555003  0.02452695  0.9999935
1.175  8.156215  0.001035711  0.001111428  0.02946728  0.0282849  0.9999936
1.225  8.109845  0.001092472  0.001219021  0.033428  0.03208456  0.9999937
1.275  8.067405  0.001148337  0.001325005  0.03733319  0.03583093  0.9999938
1.325  8.029272  0.001201949  0.001426807  0.04108813  0.03943317  0.9999938
1.375  7.995615  0.001252121  0.001522169  0.0446092  0.04281106  0.9999939
1.425  7.966428  0.001297915  0.001609288  0.04782926  0.04590017  0.999994
1.475  7.941563  0.001338683  0.001686914  0.05070119  0.04865531  0.9999941
1.525  7.92076  0.001374084  0.001754375  0.05319921  0.05105174  0.9999941
1.575  7.903673  0.001404069  0.001811554  0.05531815  0.05308452  0.9999942
1.625  7.889907  0.001428842  0.001858822  0.05707093  0.05476602  0.9999942
1.675  7.879034  0.001448804  0.001896929  0.05848474  0.05612234  0.9999942
1.725  7.870623  0.001464491  0.001926886  0.05959669  0.05718907  0.9999942
1.775  7.864255  0.001476511  0.001949848  0.06044926  0.05800696  0.9999942
1.825  7.859543  0.001485484  0.001966994  0.06108604  0.05861785  0.9999942
1.875  7.856167  0.001491957  0.001979365  0.06154559  0.05905871  0.9999942
1.925  7.853929  0.001496268  0.001987604  0.06185168  0.05935235  0.9999942
1.975  7.852789  0.001498468  0.001991809  0.06200794  0.05950226  0.9999942
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 51281100
0.025  8.670367  0.0006141409  0.0003141425  0.0001919891  0.0002001224  0.9999876
0.075  8.670365  0.0006141432  0.0003141467  0.0001921398  0.000200267  0.9999864
0.125  8.670359  0.0006141486  0.0003141567  0.0001924939  0.0002006066  0.9999911
0.175  8.670349  0.0006141593  0.0003141764  0.0001931926  0.000201277  0.9999915
0.225  8.670329  0.0006141796  0.0003142136  0.0001945111  0.0002025418  0.9999918
0.275  8.670293  0.0006142164  0.0003142813  0.0001969139  0.0002048469  0.9999921
0.325  8.670229  0.0006142814  0.0003144006  0.0002011503  0.0002089111  0.9999923
0.375  8.67012  0.0006143926  0.0003146047  0.0002083972  0.0002158632  0.9999924
0.425  8.669936  0.0006145773  0.0003149442  0.0002204524  0.0002274282  0.9999925
0.475  8.669635  0.0006148763  0.0003154939  0.0002399846  0.0002461661  0.9999926
0.525  8.66915  0.000615348  0.0003163617  0.0002708473  0.0002757737  0.9999927
0.575  8.668382  0.0006160738  0.0003176984  0.0003184517  0.0003214422  0.9999928
0.625  8.667183  0.0006171638  0.0003197091  0.0003901881  0.0003902614  0.9999928
0.675  8.665332  0.0006187623  0.0003226639  0.0004958693  0.0004916449  0.9999929
0.725  8.662519  0.0006210523  0.0003269083  0.0006481541  0.0006377369  0.999993
0.775  8.658314  0.000624259  0.0003328709  0.0008628962  0.0008437463  0.999993
0.825  8.652167  0.0006286518  0.0003410684  0.001159344  0.001128139  0.9999931
0.875  8.643427  0.000634544  0.000352104  0.001560116  0.001512613  0.9999932
0.925  8.631392  0.0006422896  0.0003666611  0.002090864  0.002021778  0.9999933
0.975  8.615392  0.0006522768  0.0003854871  0.002779566  0.002682472  0.9999933
1.025  8.594886  0.0006649158  0.0004093665  0.003655399  0.003522689  0.9999934
1.075  8.569549  0.0006806197  0.0004390824  0.004747198  0.004570088  0.9999935
1.125  8.539338  0.0006997777  0.0004753653  0.006081545  0.005850173  0.9999935
1.175  8.504515  0.0007227223  0.000518832  0.007680605  0.007384205  0.9999936
1.225  8.465622  0.0007496924  0.0005699204  0.009559867  0.009187045  0.9999936
1.275  8.423429  0.0007807979  0.000628826  0.01172601  0.0112651  0.9999936
1.325  8.378853  0.0008159896  0.0006954493  0.01417512  0.01361461  0.9999936
1.375  8.332879  0.0008550398  0.0007693612  0.01689149  0.01622052  0.9999936
1.425  8.286482  0.0008975368  0.0008497917  0.01984722  0.01905605  0.9999936
1.475  8.240576  0.0009428937  0.0009356455  0.02300269  0.0220832  0.9999936
1.525  8.195965  0.0009903729  0.001025545  0.02630798  0.02525408  0.9999936
1.575  8.153325  0.001039123  0.001117895  0.02970522  0.02851316  0.9999937
1.625  8.113194  0.001088226  0.00121097  0.03313152  0.03180013  0.9999937
1.675  8.075971  0.001136748  0.00130301  0.03652242  0.03505314  0.9999938
1.725  8.041927  0.001183785  0.001392306  0.03981511  0.03821192  0.9999939
1.775  8.011234  0.001228494  0.00147725  0.04295018  0.0412195  0.9999939
1.825  7.984032  0.001270033  0.001556236  0.04586799  0.04401865  0.999994
1.875  7.960778  0.001307034  0.001626646  0.04847123  0.04651603  0.9999941
1.925  7.94291  0.001336433  0.001682628  0.05054255  0.04850312  0.9999941
1.975  7.932915  0.001353254  0.001714676  0.05172892  0.04964125  0.9999942
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 63904140
0.025  8.670369  0.000614139  0.0003141391  0.0001918698  0.0002000079  0.9999876
0.075  8.670368  0.0006141392  0.0003141394  0.0001918797  0.0002000174  0.9999864
0.125  8.670368  0.0006141396  0.0003141401  0.0001919032  0.00020004  0.9999911
0.175  8.670367  0.0006141403  0.0003141414  0.0001919506  0.0002000855  0.9999915
0.225  8.670366  0.0006141417  0.000314144  0.0001920423  0.0002001734  0.9999918
0.275  8.670363  0.0006141443  0.0003141488  0.0001922141  0.0002003382  0.9999921
0.325  8.670359  0.0006141491  0.0003141576  0.0001925266  0.000200638  0.9999923
0.375  8.67035  0.0006141576  0.0003141732  0.0001930801  0.000201169  0.9999924
0.425  8.670336  0.0006141723  0.0003142002  0.0001940368  0.0002020868  0.9999925
0.475  8.670312  0.0006141971  0.0003142457  0.0001956529  0.0002036372  0.9999926
0.525  8.670272  0.0006142381  0.000314321  0.0001983246  0.0002062002  0.9999927
0.575  8.670207  0.0006143044  0.0003144429  0.0002026509  0.0002103506  0.9999928
0.625  8.670103  0.0006144097  0.0003146363  0.0002095187  0.0002169391  0.9999928
0.675  8.66994  0.0006145736  0.0003149375  0.0002202132  0.0002271987  0.9999929
0.725  8.669688  0.0006148239  0.0003153975  0.0002365581  0.0002428789  0.9999929
0.775  8.669304  0.0006151989  0.0003160873  0.0002610871  0.0002664104  0.999993
0.825  8.668727  0.0006157507  0.0003171032  0.000297246  0.0003010989  0.999993
0.875  8.667867  0.000616548  0.0003185727  0.0003496224  0.0003513453  0.9999931
0.925  8.666597  0.0006176791  0.0003206608  0.0004241924  0.0004228829  0.9999931
0.975  8.664742  0.0006192553  0.0003235766  0.0005285706  0.0005230165  0.9999931
1.025  8.66206  0.0006214132  0.0003275783  0.0006722414  0.0006608446  0.9999932
1.075  8.658236  0.0006243162  0.0003329775  0.0008667431  0.0008474367  0.9999932
1.125  8.65288  0.000628156  0.0003401417  0.001125773  0.001095933  0.9999933
1.175  8.645532  0.0006331522  0.0003494938  0.001465177  0.001421535  0.9999933
1.225  8.6357  0.0006395508  0.0003615085  0.001902781  0.001841343  0.9999934
1.275  8.622894  0.0006476212  0.0003767051  0.002458043  0.002374025  0.9999934
1.325  8.606684  0.0006576504  0.0003956341  0.003151495  0.003039276  0.9999935
1.375  8.586752  0.0006699339  0.000418858  0.004003964  0.003857079  0.9999935
1.425  8.562939  0.0006847625  0.0004469265  0.005035596  0.004846759  0.9999936
1.475  8.53527  0.0007024062  0.0004803444  0.006264706  0.006025885  0.9999936
1.525  8.503964  0.000723094  0.0005195362  0.00770651  0.007409057  0.9999936
1.575  8.469416  0.0007469932  0.0005648079  0.009371826  0.009006651  0.9999936
1.625  8.432167  0.0007741875  0.0006163092  0.01126579  0.0108236  0.9999936
1.675  8.392863  0.0008046566  0.0006739962  0.01338658  0.01285814  0.9999936
1.725  8.352226  0.0008382494  0.0007375826  0.01572364  0.01510016  0.9999936
1.775  8.311061  0.0008746212  0.000806421  0.01825339  0.01752703  0.9999936
1.825  8.2704  0.0009130385  0.000879132  0.02092551  0.02009049  0.9999937
1.875  8.23227  0.0009514718  0.0009518851  0.02359966  0.02265589  0.9999937
1.925  8.200987  0.0009848522  0.001015089  0.0259235  0.02488523  0.9999939
1.975  8.182861  0.001004993  0.001053236  0.02732642  0.0262311  0.9999941
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 76527180
0.025  8.670369  0.0006141389  0.0003141389  0.0001918621  0.0002000005  0.9999876
0.075  8.670369  0.0006141389  0.0003141389  0.0001918628  0.0002000012  0.9999864
0.125  8.670369  0.000614139  0.000314139  0.0001918644  0.0002000028  0.9999911
0.175  8.670369  0.000614139  0.0003141391  0.0001918677  0.0002000059  0.9999915
0.225  8.670369  0.0006141391  0.0003141393  0.0001918742  0.0002000122  0.9999918
0.275  8.670368  0.0006141393  0.0003141396  0.0001918867  0.0002000241  0.9999921
0.325  8.670368  0.0006141397  0.0003141403  0.0001919099  0.0002000464  0.9999923
0.375  8.670367  0.0006141403  0.0003141414  0.0001919519  0.0002000866  0.9999924
0.425  8.670366  0.0006141414  0.0003141435  0.0001920264  0.0002001581  0.9999925
0.475  8.670364  0.0006141434  0.0003141472  0.0001921559  0.0002002824  0.9999926
0.525  8.670361  0.0006141468  0.0003141534  0.0001923769  0.0002004944  0.9999927
0.575  8.670355  0.0006141525  0.0003141638  0.0001927468  0.0002008492  0.9999928
0.625  8.670346  0.0006141618  0.000314181  0.0001933553  0.000201433  0.9999928
0.675  8.670332  0.0006141769  0.0003142087  0.0001943397  0.0002023774  0.9999929
0.725  8.670308  0.000614201  0.0003142529  0.0001959061  0.0002038801  0.9999929
0.775  8.670271  0.0006142386  0.000314322  0.0001983593  0.0002062336  0.999993
0.825  8.670214  0.0006142966  0.0003144285  0.000202142  0.0002098624  0.999993
0.875  8.670127  0.0006143847  0.0003145904  0.0002078865  0.0002153733  0.9999931
0.925  8.669997  0.0006145164  0.0003148324  0.0002164806  0.0002236179  0.9999931
0.975  8.669802  0.0006147105  0.000315189  0.0002291502  0.0002357723  0.9999931
1.025  8.669517  0.0006149921  0.0003157069  0.0002475591  0.0002534326  0.9999931
1.075  8.669101  0.000615395  0.0003164482  0.0002739273  0.0002787285  0.9999932
1.125  8.668501  0.0006159629  0.000317494  0.000311166  0.0003144529  0.9999932
1.175  8.667642  0.0006167516  0.0003189483  0.0003630264  0.0003642043  0.9999932
1.225  8.666422  0.0006178314  0.0003209423  0.0004342566  0.0004325378  0.9999932
1.275  8.664702  0.0006192883  0.0003236376  0.0005307577  0.0005251146  0.9999933
1.325  8.662299  0.0006212257  0.0003272303  0.0006597281  0.0006488403  0.9999933
1.375  8.658978  0.000623766  0.0003319529  0.0008297798  0.0008119766  0.9999933
1.425  8.654452  0.0006270505  0.0003380767  0.00105101  0.00102421  0.9999934
1.475  8.648386  0.0006312401  0.0003459111  0.001335008  0.001296659  0.9999934
1.525  8.640413  0.0006365144  0.0003558026  0.001694774  0.001641795  0.9999934
1.575  8.630157  0.0006430699  0.0003681301  0.002144524  0.002073255  0.9999935
1.625  8.617268  0.0006511159  0.0003832965  0.002699327  0.002605497  0.9999935
1.675  8.601461  0.0006608668  0.0004017116  0.00337444  0.003253155  0.9999936
1.725  8.582567  0.0006725226  0.0004237561  0.00418391  0.004029707  0.9999936
1.775  8.560627  0.0006862176  0.0004496818  0.005136914  0.004943956  0.9999937
1.825  8.536092  0.0007018741  0.0004793365  0.006227627  0.005990315  0.9999937
1.875  8.510569  0.0007186572  0.0005111309  0.007397291  0.007112413  0.9999937
1.925  8.487996  0.0007339913  0.0005401797  0.008465923  0.008137588  0.9999939
1.975  8.474331  0.0007435187  0.0005582268  0.009129766  0.008774434  0.9999941
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 89150220
0.025  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002000001  0.9999876
0.075  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002000001  0.9999864
0.125  8.670369  0.0006141389  0.0003141389  0.0001918618  0.0002000002  0.9999911
0.175  8.670369  0.0006141389  0.0003141389  0.000191862  0.0002000004  0.9999915
0.225  8.670369  0.0006141389  0.0003141389  0.0001918625  0.0002000009  0.9999918
0.275  8.670369  0.0006141389  0.0003141389  0.0001918634  0.0002000018  0.9999921
0.325  8.670369  0.000614139  0.000314139  0.0001918651  0.0002000034  0.9999923
0.375  8.670369  0.000614139  0.0003141391  0.0001918683  0.0002000065  0.9999924
0.425  8.670369  0.0006141391  0.0003141392  0.0001918741  0.000200012  0.9999925
0.475  8.670368  0.0006141393  0.0003141395  0.0001918843  0.0002000219  0.9999926
0.525  8.670368  0.0006141395  0.00031414  0.0001919022  0.000200039  0.9999927
0.575  8.670368  0.00061414  0.0003141409  0.0001919329  0.0002000685  0.9999928
0.625  8.670367  0.0006141408  0.0003141424  0.0001919847  0.0002001182  0.9999928
0.675  8.670366  0.0006141421  0.0003141448  0.0001920709  0.0002002008  0.9999929
0.725  8.670363  0.0006141443  0.0003141488  0.0001922121  0.0002003363  0.9999929
0.775  8.67036  0.0006141478  0.0003141552  0.0001924403  0.0002005552  0.999993
0.825  8.670355  0.0006141534  0.0003141654  0.0001928038  0.0002009039  0.999993
0.875  8.670346  0.0006141621  0.0003141815  0.0001933752  0.0002014522  0.9999931
0.925  8.670333  0.0006141757  0.0003142065  0.0001942616  0.0002023025  0.9999931
0.975  8.670312  0.0006141966  0.0003142448  0.0001956187  0.0002036044  0.9999931
1.025  8.670282  0.000614228  0.0003143026  0.00019767  0.0002055722  0.9999931
1.075  8.670236  0.000614275  0.0003143888  0.0002007314  0.0002085092  0.9999932
1.125  8.670167  0.0006143442  0.0003145159  0.0002052439  0.0002128382  0.9999932
1.175  8.670068  0.0006144449  0.000314701  0.0002118136  0.0002191407  0.9999932
1.225  8.669924  0.0006145897  0.000314967  0.0002212625  0.0002282054  0.9999932
1.275  8.669717  0.0006147953  0.0003153449  0.0002346891  0.000241086  0.9999933
1.325  8.669423  0.0006150836  0.0003158752  0.000253541  0.0002591712  0.9999933
1.375  8.669009  0.0006154831  0.0003166103  0.0002796978  0.0002842643  0.9999933
1.425  8.668429  0.0006160298  0.0003176174  0.000315565  0.0003186729  0.9999933
1.475  8.667623  0.0006167691  0.0003189805  0.000364174  0.0003653052  0.9999933
1.525  8.666509  0.0006177562  0.0003208033  0.0004292857  0.0004277691  0.9999933
1.575  8.664979  0.0006190581  0.0003232115  0.0005154843  0.0005104623  0.9999934
1.625  8.662896  0.0006207536  0.000326354  0.0006282391  0.0006186318  0.9999934
1.675  8.660087  0.0006229324  0.0003304018  0.0007738679  0.0007583385  0.9999934
1.725  8.656354  0.0006256902  0.0003355384  0.0009592213  0.0009361542  0.9999934
1.775  8.651503  0.0006291118  0.0003419284  0.001190516  0.001158043  0.9999935
1.825  8.645429  0.0006332212  0.0003496231  0.00146988  0.001426046  0.9999935
1.875  8.638419  0.0006378051  0.0003582271  0.001783121  0.001726549  0.9999936
1.925  8.631681  0.0006421072  0.000366318  0.002078331  0.002009754  0.9999938
1.975  8.627376  0.000644819  0.0003714242  0.002264907  0.002188742  0.9999941
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 101773260
0.025  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999876
0.075  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999864
0.125  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999911
0.175  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999915
0.225  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002000001  0.9999918
0.275  8.670369  0.0006141389  0.0003141389  0.0001918617  0.0002000001  0.9999921
0.325  8.670369  0.0006141389  0.0003141389  0.0001918618  0.0002000003  0.9999923
0.375  8.670369  0.0006141389  0.0003141389  0.0001918621  0.0002000005  0.9999924
0.425  8.670369  0.0006141389  0.0003141389  0.0001918625  0.0002000009  0.9999925
0.475  8.670369  0.0006141389  0.0003141389  0.0001918633  0.0002000017  0.9999926
0.525  8.670369  0.000614139  0.000314139  0.0001918647  0.0002000031  0.9999927
0.575  8.670369  0.000614139  0.0003141391  0.0001918673  0.0002000055  0.9999928
0.625  8.670369  0.0006141391  0.0003141392  0.0001918716  0.0002000096  0.9999928
0.675  8.670368  0.0006141392  0.0003141394  0.0001918789  0.0002000167  0.9999929
0.725  8.670368  0.0006141394  0.0003141397  0.0001918912  0.0002000284  0.9999929
0.775  8.670368  0.0006141397  0.0003141403  0.0001919115  0.0002000479  0.999993
0.825  8.670367  0.0006141402  0.0003141412  0.0001919447  0.0002000798  0.999993
0.875  8.670367  0.000614141  0.0003141427  0.0001919983  0.0002001312  0.9999931
0.925  8.670365  0.0006141423  0.0003141451  0.0001920838  0.0002002132  0.9999931
0.975  8.670363  0.0006141444  0.0003141489  0.0001922185  0.0002003424  0.9999931
1.025  8.67036  0.0006141476  0.0003141548  0.0001924282  0.0002005437  0.9999931
1.075  8.670355  0.0006141526  0.0003141639  0.0001927513  0.0002008536  0.9999932
1.125  8.670348  0.0006141601  0.0003141778  0.0001932433  0.0002013255  0.9999932
1.175  8.670337  0.0006141715  0.0003141987  0.0001939842  0.0002020363  0.9999932
1.225  8.67032  0.0006141884  0.0003142298  0.0001950879  0.0002030952  0.9999932
1.275  8.670296  0.0006142134  0.0003142756  0.0001967144  0.0002046555  0.9999933
1.325  8.67026  0.0006142498  0.0003143424  0.0001990855  0.0002069302  0.9999933
1.375  8.670209  0.0006143022  0.0003144388  0.0002025056  0.0002102113  0.9999933
1.425  8.670135  0.0006143771  0.0003145763  0.0002073871  0.0002148942  0.9999933
1.475  8.67003  0.0006144827  0.0003147704  0.0002142812  0.0002215079  0.9999933
1.525  8.669883  0.0006146303  0.0003150417  0.0002239153  0.0002307503  0.9999933
1.575  8.669677  0.0006148342  0.0003154165  0.0002372346  0.0002435279  0.9999934
1.625  8.669393  0.0006151127  0.0003159286  0.0002554428  0.0002609956  0.9999934
1.675  8.669004  0.0006154881  0.0003166196  0.000280027  0.0002845801  0.9999934
1.725  8.668476  0.0006159865  0.0003175376  0.0003127192  0.0003159429  0.9999934
1.775  8.667773  0.0006166336  0.0003187306  0.0003552569  0.0003567507  0.9999934
1.825  8.666867  0.0006174431  0.0003202248  0.0004086074  0.0004079317  0.9999935
1.875  8.665789  0.0006183758  0.0003219488  0.000470264  0.0004670809  0.9999935
1.925  8.664724  0.0006192704  0.0003236046  0.0005295742  0.0005239792  0.9999938
1.975  8.664029  0.000619841  0.0003246616  0.0005674803  0.0005603438  0.9999941
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 114396300
0.025  8.670369  0.0006141389  0.0003141389  0.0001918615  0.0002  0.9999876
0.075  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999864
0.125  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999911
0.175  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999915
0.225  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999918
0.275  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999921
0.325  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999923
0.375  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002000001  0.9999924
0.425  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002000001  0.9999925
0.475  8.670369  0.0006141389  0.0003141389  0.0001918617  0.0002000001  0.9999926
0.525  8.670369  0.0006141389  0.0003141389  0.0001918618  0.0002000003  0.9999927
0.575  8.670369  0.0006141389  0.0003141389  0.000191862  0.0002000005  0.9999928
0.625  8.670369  0.0006141389  0.0003141389  0.0001918624  0.0002000008  0.9999928
0.675  8.670369  0.0006141389  0.0003141389  0.000191863  0.0002000014  0.9999929
0.725  8.670369  0.000614139  0.000314139  0.000191864  0.0002000024  0.9999929
0.775  8.670369  0.000614139  0.000314139  0.0001918658  0.0002000041  0.999993
0.825  8.670369  0.000614139  0.0003141391  0.0001918687  0.0002000069  0.999993
0.875  8.670369  0.0006141391  0.0003141392  0.0001918736  0.0002000115  0.9999931
0.925  8.670368  0.0006141392  0.0003141395  0.0001918815  0.0002000191  0.9999931
0.975  8.670368  0.0006141394  0.0003141398  0.0001918942  0.0002000313  0.9999931
1.025  8.670368  0.0006141397  0.0003141404  0.0001919145  0.0002000508  0.9999931
1.075  8.670367  0.0006141402  0.0003141413  0.0001919465  0.0002000815  0.9999932
1.125  8.670367  0.000614141  0.0003141427  0.0001919965  0.0002001295  0.9999932
1.175  8.670366  0.0006141422  0.0003141449  0.0001920739  0.0002002038  0.9999932
1.225  8.670364  0.000614144  0.0003141482  0.0001921925  0.0002003175  0.9999932
1.275  8.670361  0.0006141467  0.0003141533  0.0001923722  0.0002004899  0.9999933
1.325  8.670357  0.0006141509  0.0003141609  0.0001926422  0.0002007489  0.9999933
1.375  8.670351  0.000614157  0.0003141722  0.0001930437  0.0002011341  0.9999933
1.425  8.670342  0.0006141661  0.0003141888  0.000193635  0.0002017014  0.9999933
1.475  8.670329  0.0006141794  0.0003142132  0.0001944977  0.0002025289  0.9999933
1.525  8.670311  0.0006141985  0.0003142483  0.0001957438  0.0002037244  0.9999933
1.575  8.670284  0.0006142258  0.0003142985  0.0001975257  0.0002054339  0.9999934
1.625  8.670246  0.0006142645  0.0003143695  0.0002000463  0.0002078519  0.9999934
1.675  8.670193  0.0006143185  0.0003144687  0.000203567  0.0002112295  0.9999934
1.725  8.67012  0.0006143927  0.000314605  0.0002084061  0.0002158717  0.9999934
1.775  8.670021  0.0006144922  0.0003147879  0.0002149001  0.0002221017  0.9999934
1.825  8.669893  0.0006146204  0.0003150235  0.0002232695  0.0002301308  0.9999934
1.875  8.669741  0.0006147717  0.0003153016  0.0002331506  0.00023961  0.9999935
1.925  8.669591  0.0006149192  0.0003155728  0.0002427913  0.0002488586  0.9999938
1.975  8.669494  0.0006150142  0.0003157475  0.000249  0.0002548149  0.9999941
distance  pH  tot(C)  tot(Ca)  tot(Cl)  tot(Na)  Calcite  at = 127019340
0.025  8.670369  0.0006141389  0.0003141389  0.0001918615  0.0002  0.9999876
0.075  8.670369  0.0006141389  0.0003141389  0.0001918615  0.0002  0.9999864
0.125  8.670369  0.0006141389  0.0003141389  0.0001918615  0.0002  0.9999911
0.175  8.670369  0.0006141389  0.0003141389  0.0001918615  0.0002  0.9999915
0.225  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999918
0.275  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999921
0.325  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999923
0.375  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999924
0.425  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999925
0.475  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999926
0.525  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002  0.9999927
0.575  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002000001  0.9999928
0.625  8.670369  0.0006141389  0.0003141389  0.0001918616  0.0002000001  0.9999928
0.675  8.670369  0.0006141389  0.0003141389  0.0001918617  0.0002000001  0.9999929
0.725  8.670369  0.0006141389  0.0003141389  0.0001918618  0.0002000002  0.9999929
0.775  8.670369  0.0006141389  0.0003141389  0.0001918619  0.0002000004  0.999993
0.825  8.670369  0.0006141389  0.0003141389  0.0001918622  0.0002000006  0.999993
0.875  8.670369  0.0006141389  0.0003141389  0.0001918626  0.000200001  0.9999931
0.925  8.670369  0.0006141389  0.0003141389  0.0001918633  0.0002000017  0.9999931
0.975  8.670369  0.000614139  0.000314139  0.0001918645  0.0002000028  0.9999931
1.025  8.670369  0.000614139  0.000314139  0.0001918663  0.0002000046  0.9999931
1.075  8.670369  0.000614139  0.0003141391  0.0001918694  0.0002000075  0.9999932
1.125  8.670369  0.0006141391  0.0003141393  0.0001918742  0.0002000122  0.9999932
1.175  8.670368  0.0006141392  0.0003141395  0.0001918819  0.0002000196  0.9999932
1.225  8.670368  0.0006141394  0.0003141398  0.0001918939  0.0002000311  0.9999932
1.275  8.670368  0.0006141397  0.0003141403  0.0001919126  0.000200049  0.9999933
1.325  8.670368  0.0006141401  0.0003141411  0.0001919413  0.0002000765  0.9999933
1.375  8.670367  0.0006141408  0.0003141424  0.000191985  0.0002001184  0.9999933
1.425  8.670366  0.0006141418  0.0003141442  0.000192051  0.0002001818  0.9999933
1.475  8.670364  0.0006141433  0.000314147  0.0001921499  0.0002002767  0.9999933
1.525  8.670362  0.0006141456  0.0003141511  0.0001922966  0.0002004174  0.9999933
1.575  8.670359  0.0006141489  0.0003141572  0.0001925121  0.0002006241  0.9999934
1.625  8.670354  0.0006141537  0.000314166  0.0001928252  0.0002009245  0.9999934
1.675  8.670348  0.0006141606  0.0003141787  0.0001932744  0.0002013554  0.9999934
1.725  8.670338  0.0006141703  0.0003141965  0.0001939075  0.0002019628  0.9999934
1.775  8.670325  0.0006141837  0.000314221  0.0001947773  0.0002027972  0.9999934
1.825  8.670308  0.0006142012  0.0003142533  0.0001959211  0.0002038945  0.9999934
1.875  8.670287  0.0006142222  0.0003142919  0.0001972927  0.0002052103  0.9999935
1.925  8.670267  0.000614243  0.00031433  0.0001986446  0.0002065072  0.9999938
1.975  8.670254  0.0006142564  0.0003143547  0.0001995199  0.000207347  0.9999941
''',
    view={'tab': 'profile', 'profile': {'species': 'tot(Ca)', 'times': '13411980, 38658060, 63904140, 127019340'}},
))


_after('besidecolumn', dict(
    id='exchangebeside',
    group='Through PHREEQC',
    label="Ions off an exchanger, beside PHREEQC's own column",
    about="A calcium-magnesium water pushes a sodium-potassium one through 10 cm of a column with an exchanger, written from PHREEQC with PHREEQC's own column, to set beside the run, ticked: the water PHREEQC's column lets out, at every shift, is under <DATA>. Run it: Against time at the outlet, in pore volumes, the sodium leaving first, then the potassium at nearly five times what the column held, then the magnesium, above what flows in at first, and the calcium, as the exchanger holds each more strongly than the last, PHREEQC's points beside the run; the Fit tab's the run against what was measured, one to one, gives each column's Nash–Sutcliffe efficiency, 0.998 or more.",
    text='''# A calcium-magnesium water pushes a sodium-potassium water through 10 cm of
# a column whose exchanger holds the column's sodium and potassium. The
# exchanger holds calcium most strongly, then magnesium, potassium and
# sodium, and the water leaving the column changes in that order: the
# bromide, which nothing holds, after one pore volume; the sodium first; then
# the potassium, at nearly five times what the column's water held, as the
# ions behind push it ahead; then, after two pore volumes, the magnesium and
# the calcium together, the magnesium at first above what flows in (0.37
# mmol/kgw against 0.25) as the calcium takes its place on the exchanger.
# Written from PHREEQC by From PHREEQC... on the Model tab (the relations held
# exactly, the exchanger as PHREEQC has it) with PHREEQC's own column, to set
# beside the run, ticked: PHREEQC punched only its last cell, so the water it
# lets out is under <DATA> as a table in time there, at every shift. Run it:
# Against time at the outlet, in pore volumes, PHREEQC's points beside the
# run; the Fit tab's Show, the run against what was measured, one to one,
# gives each column's Nash-Sutcliffe efficiency: 0.998 or more on these 50
# cells, the magnesium's the least, its overshoot the sharpest thing in the
# run. The input, to phreeqc.dat:
#   SOLUTION 0  flowing in                SOLUTION 1-50  the column's water
#    units mmol/kgw; pH 7.2                units mmol/kgw; pH 7.2
#    Ca 0.5; Mg 0.25; Br 0.1; Cl charge    Na 1.2; K 0.3; Cl charge
#   EXCHANGE 1-50: -equilibrate 1; X 0.0015
#   TRANSPORT: -cells 50, -lengths 0.002, -shifts 150, -time_step 600,
#    -diffusion_coefficient 1e-9, -dispersivities 0.002, -punch_cells 50,
#    -punch_frequency 1

<SETTINGS>
MODE = transport
CELLS = 50
LENGTH = 0.1
DIFFUSION = 1
ADVECTION = 1
ADVECTION_SCHEME = limited
VELOCITY = 0.00000333333333333333
PECLET = 50
LEFT = robin
RIGHT = free
TEND = 90300
TIME_UNIT = second
EQUILIBRATE = always
ACTIVITY = debye-huckel
TEMPERATURE = 25

<SPECIES>
H+     6.57240208603836e-8   a=9  b=0  D=1e-9  left=6.62548028156351e-8
OH-    1.6754744098754e-7    a=3.5  b=0  D=1e-9  left=1.69111640278445e-7
Cl-    0.00149989818969531   a=3.63  b=0.017  D=1e-9  left=0.0013998836926721
Na+    0.00120000000011562   a=4.08  b=0.082  D=1e-9  left=1.1999999999988e-15
K+     0.000300000000030014  a=3.5  b=0.015  D=1e-9  left=2.99999999999699e-16
HCl    3.1170013239737e-11   b=0.4256  D=1e-9  left=2.88034587595825e-11
Br-    1.00000000000096e-16  a=3  b=0  D=1e-9  left=0.00010000000000869
Ca+2   7.71100568525448e-19  a=5  b=0.165  D=1e-9  left=0.000499998872173221
Mg+2   6.10505257711276e-19  a=5.5  b=0.2  D=1e-9  left=0.00024998766370725
MgOH+  3.09289424130553e-23  a=6.5  b=0  D=1e-9  left=1.23363662474942e-8
CaOH+  1.78580997801332e-24  D=1e-9  left=1.12797580408182e-9
H2     2.81740962173119e-26  D=1e-9  left=2.81692313145818e-26
X-                           exchanger
KX     0.000834211608137761  exchange  a=3.5  b=0.015
NaX    0.000665788393768282  exchange  a=4.08  b=0.082
CaX2   4.99228897645161e-16  exchange  a=5  b=0.165
MgX2   2.49389463813098e-16  exchange  a=5.5  b=0.2

<EQUILIBRIUM>
H2O <=> OH- + H+,          analytic = 293.29227 0.1360833 -10576.913 -123.73158 0 -0.00006996455   # here -13.9581
H+ + Cl- <=> HCl,          analytic = 0.3340000000000159 -0.002684 1.015                           # here -0.5000
Mg+2 + H2O <=> MgOH+ + H+, logK = -11.4400000000, dH = 66.743168                                   # here -11.4776
Ca+2 + H2O <=> CaOH+ + H+, logK = -12.7800000000                                                   # here -12.8176
K+ + X- <=> KX,            logK = 0.7000000000, dH = -4.3                                          # here 0.7000
Na+ + X- <=> NaX,          logK = -0.0000000000                                                    # here -0.0000
Ca+2 + 2 X- <=> CaX2,      logK = 0.8000000000, dH = 7.2                                           # here 0.8000
Mg+2 + 2 X- <=> MgX2,      logK = 0.6000000000, dH = 7.4                                           # here 0.6000

<VOLUMES>
OH-   -9.66  28.5  80  -22.9  1.89  0  1.09  0  0  1
Cl-   4.465  4.801  4.325  -2.847  1.748  0  -0.331  20.16  0  1
Na+   2.28  -4.38  -4.1  -0.586  0.09  4  0.3  52  -0.00333  0.566
K+    3.322  -1.473  6.534  -2.712  0.0906  3.5  0  29.7  0  1
Br-   6.72  2.85  4.21  -3.14  1.38  0  -0.0956  7.08  -0.00156  1
Ca+2  -0.3456  -7.252  6.149  -2.479  1.239  5  1.6  -57.1  -0.00612  1
Mg+2  -1.41  -8.6  11.13  -2.39  1.332  5.5  1.29  -32.9  -0.00586  1
H2    6.52  0.78  0.12

<CONDUCTANCE>
H+     gfw 1.008  dw 9.31e-9 838 6.96 -2.285 0.206 24.01 0  viscosity 0.0935 -0.0831 0.02487 0.000449 0.0201 1.57
OH-    gfw 17.008  dw 5.27e-9 478 0.8695  viscosity -0.0226 0.106 0.02184 -0.0032 0 0.4082 -1.634
Cl-    gfw 35.453  dw 2.033e-9 216 3.16 0.2071 0.7432  viscosity 0 0 0 0 0 0 1
Na+    gfw 22.9898  dw 1.33e-9 75 3.627 0 0.7037  viscosity 0.1387 -0.0866 0.0125 0.0145 0.0075 1.062
K+     gfw 39.102  dw 1.96e-9 254 3.484 0 0.1964  viscosity 0.116 -0.191 0.0152 0.014 0.0259 0.9028
HCl    gfw 36.461  viscosity 0.921 -0.765 0.00832 0.000825 0.00253 4.223
Br-    gfw 79.904  dw 2.09e-9 208 3.5 0 0.5737  viscosity -0.0698 -0.141 0.0178 0.159 0.00776 0.0625 0.859
Ca+2   gfw 40.08  dw 7.92e-10 34 5.411 0 1.046  viscosity 0.359 -0.158 0.042 0.0015 0.00804 2.3
Mg+2   gfw 24.312  dw 7.05e-10 -4 5.569 0 1.047  viscosity 0.426 0 0 0.00166 0.00432 2.461
MgOH+  gfw 41.32
CaOH+  gfw 57.088
H2     gfw 2.016  dw 5.13e-9
H2O    gfw 18.016

<REACTIONS>
# Your kinetic reactions here, in the same species and units.

<DATA>
# PHREEQC's own TRANSPORT of the input this model was written from, run in the page: a cell of PHREEQC's
# after shift k as this model's cell half a time step later, at its centre.
# The run goes on to TEND = 90300, half a time step past the last shift, where its last cells are read.
time  pH  Br-  tot(Ca)  tot(Cl)  K+  tot(Mg)  Na+  cell = 49
900  7.2  0  0  0.001499898  0.0003  0  0.0012
1500  7.2  0  0  0.001499898  0.0003  0  0.0012
2100  7.2  0  0  0.001499898  0.0003  0  0.0012
2700  7.2  0  0  0.001499898  0.0003  0  0.0012
3300  7.2  0  0  0.001499898  0.0003  0  0.0012
3900  7.2  0  0  0.001499898  0.0003  0  0.0012
4500  7.2  0  0  0.001499898  0.0003  0  0.0012
5100  7.2  0  0  0.001499898  0.0003  0  0.0012
5700  7.2  0  0  0.001499898  0.0003  0  0.0012
6300  7.2  0  0  0.001499898  0.0003  0  0.0012
6900  7.2  1.675374e-21  0  0.001499898  0.0003  0  0.0012
7500  7.2  1.073613e-18  0  0.001499898  0.0003  0  0.0012
8100  7.2  1.134266e-16  0  0.001499898  0.0003  0  0.0012
8700  7.2  4.205918e-15  0  0.001499898  0.0003  0  0.0012
9300  7.2  7.774118e-14  0  0.001499898  0.0003  0  0.0012
9900  7.2  8.724423e-13  0  0.001499898  0.0003  0  0.0012
10500  7.2  6.726092e-12  0  0.001499898  0.0003  0  0.0012
11100  7.2  3.870613e-11  0  0.001499898  0.0003  0  0.0012
11700  7.2  1.763022e-10  0  0.001499898  0.0003  0  0.0012
12300  7.2  6.635663e-10  0  0.001499898  0.0003  0  0.0012
12900  7.200001  2.13198e-9  0  0.001499896  0.0003  0  0.0012
13500  7.200002  5.996349e-9  0  0.001499892  0.0003  0  0.0012
14100  7.200004  1.506011e-8  0  0.001499883  0.0003  0  0.0012
14700  7.200009  3.431924e-8  0  0.001499864  0.0003  0  0.0012
15300  7.200019  7.188877e-8  0  0.001499826  0.0003  0  0.0012
15900  7.200038  1.399116e-7  0  0.001499758  0.0003  0  0.0012
16500  7.200069  2.552687e-7  0  0.001499643  0.0003  0  0.0012
17100  7.200119  4.399063e-7  0  0.001499458  0.0003  0  0.0012
17700  7.200194  7.20637e-7  0  0.001499177  0.0003  0  0.0012
18300  7.200304  0.000001128345  0  0.00149877  0.0003  0  0.0012
18900  7.200458  0.000001696614  0  0.001498201  0.0003  0  0.0012
19500  7.200664  0.000002459893  0  0.001497438  0.0003  0  0.0012
20100  7.200931  0.00000345137  0  0.001496446  0.0003  0  0.0012
20700  7.201268  0.000004700773  0  0.001495197  0.0003  0  0.0012
21300  7.201681  0.000006232313  0  0.001493665  0.0003  0  0.0012
21900  7.202174  0.000008062969  0  0.001491834  0.0003000001  0  0.0012
22500  7.202749  0.00001020125  0  0.001489695  0.0003000001  0  0.0012
23100  7.203407  0.0000126465  0  0.00148725  0.0003000002  0  0.0012
23700  7.204144  0.00001538883  0  0.001484507  0.0003000005  0  0.0012
24300  7.204956  0.00001840956  0  0.001481486  0.000300001  0  0.001199999
24900  7.205834  0.00002168216  0  0.001478213  0.0003000018  0  0.001199998
25500  7.206771  0.00002517348  0  0.001474721  0.0003000034  0  0.001199997
26100  7.207754  0.00002884537  0  0.001471049  0.0003000062  0  0.001199994
26700  7.208774  0.00003265624  0  0.001467237  0.000300011  0  0.001199989
27300  7.209818  0.00003656277  0  0.00146333  0.000300019  0  0.001199981
27900  7.210876  0.00004052146  0  0.001459371  0.0003000322  0  0.001199968
28500  7.211934  0.00004449  0  0.001455402  0.0003000535  0  0.001199946
29100  7.212983  0.00004842853  0  0.001451463  0.0003000875  0  0.001199912
29700  7.214014  0.0000523005  0  0.00144759  0.0003001407  0  0.001199859
30300  7.215017  0.00005607345  0  0.001443817  0.0003002227  0  0.001199777
30900  7.215985  0.00005971941  0  0.00144017  0.0003003476  0  0.001199652
31500  7.216913  0.00006321515  0  0.001436674  0.0003005354  0  0.001199465
32100  7.217795  0.00006654221  0  0.001433346  0.0003008144  0  0.001199186
32700  7.218627  0.00006968675  0  0.001430201  0.0003012247  0  0.001198775
33300  7.219408  0.00007263933  0  0.001427248  0.000301822  0  0.001198178
33900  7.220137  0.00007539449  0  0.001424493  0.0003026837  0  0.001197316
34500  7.220812  0.00007795037  0  0.001421937  0.0003039157  0  0.001196084
35100  7.221434  0.00008030824  0  0.001419578  0.0003056625  0  0.001194337
35700  7.222005  0.00008247199  0  0.001417414  0.0003081188  0  0.001191881
36300  7.222526  0.00008444768  0  0.001415438  0.0003115441  0  0.001188456
36900  7.222999  0.00008624313  0  0.001413643  0.00031628  0  0.00118372
37500  7.223427  0.00008786741  0  0.001412018  0.0003227677  0  0.001177232
38100  7.223812  0.00008933056  0  0.001410555  0.0003315643  0  0.001168436
38700  7.224157  0.00009064318  0  0.001409242  0.0003433517  0  0.001156648
39300  7.224466  0.00009181618  0  0.001408069  0.0003589301  0  0.00114107
39900  7.224741  0.00009286053  0  0.001407024  0.0003791825  0  0.001120818
40500  7.224984  0.00009378705  0  0.001406098  0.000405  0  0.001095
41100  7.2252  0.00009460626  0  0.001405278  0.0004371594  0  0.001062841
41700  7.225389  0.00009532826  0  0.001404556  0.0004761625  0  0.001023838
42300  7.225556  0.00009596262  0  0.001403922  0.0005220723  0  0.0009779278
42900  7.225702  0.00009651833  0  0.001403366  0.0005744022  0  0.0009255978
43500  7.225829  0.00009700378  0  0.00140288  0.0006321118  0  0.0008678882
44100  7.22594  0.0000974267  0  0.001402457  0.000693727  0  0.0008062731
44700  7.226037  0.00009779419  0  0.00140209  0.0007575473  0  0.0007424527
45300  7.226121  0.00009811273  0  0.001401771  0.0008218724  0  0.0006781276
45900  7.226193  0.00009838817  0  0.001401496  0.0008851824  4.078506e-26  0.0006148176
46500  7.226255  0.00009862581  0  0.001401258  0.0009462445  8.64997e-25  0.0005537555
47100  7.226309  0.00009883038  1.537809e-26  0.001401054  0.001004147  1.588328e-23  0.0004958527
47700  7.226355  0.00009900611  3.581583e-25  0.001400878  0.001058285  2.670485e-22  0.0004417152
48300  7.226395  0.00009915676  7.396063e-24  0.001400727  0.001108313  4.151246e-21  0.0003916867
48900  7.226428  0.00009928567  1.419687e-22  0.001400598  0.001154098  6.009818e-20  0.0003459021
49500  7.226457  0.00009939575  2.555862e-21  0.001400488  0.00119566  8.154363e-19  0.0003043396
50100  7.226482  0.00009948959  4.354569e-20  0.001400394  0.001233135  1.045057e-17  0.0002668654
50700  7.226503  0.00009956946  7.051682e-19  0.001400314  0.001266729  1.271491e-16  0.0002332709
51300  7.226521  0.0000996373  1.091506e-17  0.001400246  0.001296698  1.477737e-15  0.0002033018
51900  7.226536  0.00009969485  1.628603e-16  0.001400189  0.001323323  1.651457e-14  0.0001766775
52500  7.226549  0.00009974359  2.336916e-15  0.00140014  0.001346891  1.776394e-13  0.0001531092
53100  7.226559  0.0000997848  3.264519e-14  0.001400099  0.001367692  1.856368e-12  0.0001323081
53700  7.226569  0.0000998196  4.437497e-13  0.001400064  0.00138601  1.88531e-11  0.0001139898
54300  7.226576  0.00009984894  5.859758e-12  0.001400035  0.001402111  1.863072e-10  0.00009788854
54900  7.226583  0.00009987365  7.69991e-11  0.00140001  0.001416253  1.821578e-9  0.00008374315
55500  7.226586  0.00009989443  9.77352e-10  0.001399989  0.001428643  1.727217e-8  0.00007132073
56100  7.226576  0.00009991188  1.227894e-8  0.001399972  0.001439251  1.618168e-7  0.0000604009
56700  7.226447  0.00009992652  1.506923e-7  0.001399957  0.001445982  0.000001480654  0.00005075486
57300  7.225342  0.00009993879  0.000001677421  0.001399945  0.001429701  0.00001241703  0.00004211021
57900  7.217987  0.00009994906  0.00001580364  0.001399935  0.001262185  0.00008619758  0.00003381275
58500  7.206657  0.00009995764  0.00005186927  0.001399926  0.0009617184  0.0002040368  0.00002646952
59100  7.199714  0.00009996481  0.00009251776  0.001399919  0.0007373694  0.0002783576  0.00002087986
59700  7.195608  0.00009997079  0.0001314845  0.001399913  0.0005751134  0.0003226701  0.00001657738
60300  7.193103  0.00009997577  0.0001670757  0.001399908  0.0004535982  0.0003495172  0.00001321593
60900  7.191582  0.00009997992  0.0001990519  0.001399904  0.0003605148  0.0003654075  0.00001056643
61500  7.190704  0.00009998338  0.0002276258  0.0013999  0.000288149  0.0003740667  0.000008466149
62100  7.190261  0.00009998625  0.0002531288  0.001399897  0.0002313061  0.0003778209  0.000006794585
62700  7.190118  0.00009998863  0.0002759053  0.001399895  0.0001863158  0.0003782066  0.000005460294
63300  7.190182  0.0000999906  0.0002962778  0.001399893  0.0001504985  0.0003762765  0.000004392795
63900  7.19039  0.00009999224  0.0003145358  0.001399891  0.0001218521  0.0003727696  0.000003537197
64500  7.190695  0.0000999936  0.0003309343  0.00139989  0.00009885467  0.0003682131  0.000002850427
65100  7.191065  0.00009999472  0.0003456959  0.001399889  0.0000803349  0.0003629874  0.0000022985
65700  7.191476  0.00009999565  0.0003590134  0.001399888  0.00006538186  0.0003573684  0.000001854487
66300  7.19191  0.00009999642  0.0003710541  0.001399887  0.0000532816  0.0003515566  0.000001496976
66900  7.192353  0.00009999705  0.0003819628  0.001399887  0.00004347091  0.0003456973  0.000001208901
67500  7.192798  0.00009999758  0.0003918648  0.001399886  0.00003550316  0.0003398953  9.766258e-7
68100  7.193236  0.00009999801  0.000400869  0.001399886  0.00002902255  0.0003342251  7.892377e-7
68700  7.193663  0.00009999836  0.0004090703  0.001399885  0.00002374458  0.0003287384  6.37988e-7
69300  7.194076  0.00009999866  0.0004165512  0.001399885  0.00001944105  0.0003234703  5.158549e-7
69900  7.194472  0.0000999989  0.0004233842  0.001399885  0.00001592836  0.000318443  4.171959e-7
70500  7.19485  0.0000999991  0.0004296328  0.001399885  0.00001305848  0.0003136692  3.374727e-7
71100  7.195208  0.00009999926  0.000435353  0.001399884  0.00001071176  0.0003091546  2.730319e-7
71700  7.195547  0.00009999939  0.0004405944  0.001399884  0.000008791361  0.0003048995  2.209303e-7
72300  7.195867  0.0000999995  0.0004454009  0.001399884  0.000007218714  0.0003009003  1.787954e-7
72900  7.196167  0.00009999959  0.0004498117  0.001399884  0.000005930017  0.0002971509  1.447137e-7
73500  7.196449  0.00009999967  0.0004538618  0.001399884  0.000004873374  0.0002936429  1.17141e-7
74100  7.196713  0.00009999973  0.0004575826  0.001399884  0.00000400653  0.0002903668  9.483054e-8
74700  7.196959  0.00009999978  0.0004610022  0.001399884  0.000003295035  0.0002873119  7.677546e-8
75300  7.197189  0.00009999982  0.0004641462  0.001399884  0.000002710777  0.0002844673  6.216227e-8
75900  7.197403  0.00009999985  0.0004670376  0.001399884  0.000002230797  0.0002818218  5.033353e-8
76500  7.197602  0.00009999988  0.0004696973  0.001399884  0.000001836328  0.0002793642  4.075774e-8
77100  7.197787  0.0000999999  0.0004721442  0.001399884  0.000001512014  0.0002770833  3.300513e-8
77700  7.197959  0.00009999992  0.0004743956  0.001399884  0.000001245287  0.0002749684  2.672811e-8
78300  7.198118  0.00009999993  0.0004764673  0.001399884  0.000001025852  0.0002730089  2.164551e-8
78900  7.198266  0.00009999995  0.0004783738  0.001399884  8.452691e-7  0.0002711948  1.752981e-8
79500  7.198403  0.00009999996  0.0004801281  0.001399884  6.966179e-7  0.0002695165  1.419692e-8
80100  7.198529  0.00009999996  0.0004817425  0.001399884  5.7422e-7  0.0002679646  1.149784e-8
80700  7.198646  0.00009999997  0.0004832281  0.001399884  4.73414e-7  0.0002665306  9.311977e-9
81300  7.198754  0.00009999998  0.0004845949  0.001399884  3.903717e-7  0.0002652061  7.541693e-9
81900  7.198854  0.00009999998  0.0004858525  0.001399884  3.219482e-7  0.0002639835  6.107951e-9
82500  7.198946  0.00009999998  0.0004870093  0.001399884  2.655583e-7  0.0002628554  4.946754e-9
83100  7.199031  0.00009999999  0.0004880735  0.001399884  2.190768e-7  0.000261815  4.006285e-9
83700  7.19911  0.00009999999  0.0004890522  0.001399884  1.807558e-7  0.0002608558  3.244581e-9
84300  7.199182  0.00009999999  0.0004899522  0.001399884  1.491572e-7  0.0002599719  2.627663e-9
84900  7.199249  0.00009999999  0.0004907797  0.001399884  1.230975e-7  0.0002591577  2.128011e-9
85500  7.19931  0.00009999999  0.0004915404  0.001399884  1.016025e-7  0.0002584079  1.723336e-9
86100  7.199367  0.0001  0.0004922397  0.001399884  8.387005e-8  0.0002577177  1.395588e-9
86700  7.199419  0.0001  0.0004928824  0.001399884  6.923963e-8  0.0002570825  1.130147e-9
87300  7.199467  0.0001  0.0004934729  0.001399884  5.716699e-8  0.0002564981  9.151701e-10
87900  7.199511  0.0001  0.0004940154  0.001399884  4.720376e-8  0.0002559607  7.410671e-10
88500  7.199551  0.0001  0.0004945137  0.001399884  3.89804e-8  0.0002554665  6.000692e-10
89100  7.199588  0.0001  0.0004949714  0.001399884  3.219235e-8  0.0002550123  4.858841e-10
89700  7.199623  0.0001  0.0004953916  0.001399884  2.65885e-8  0.0002545949  3.93415e-10
90300  7.199654  0.0001  0.0004957774  0.001399884  2.19618e-8  0.0002542115  3.185339e-10
''',
    view={'tab': 'time', 'picked': ['Br-', 'Na+', 'K+', 'tot(Mg)', 'tot(Ca)'], 'cell': 49, 'timeIn': 'pv', 'logT': False, 'logY': False},
))


_after('exchangebeside', dict(
    id='sulphidebeside',
    group='Through PHREEQC',
    label="Sulphide from sulphate at a rate, beside PHREEQC's own column",
    about="A sulphate water flows through 1 m of a column whose rock holds organic carbon, which bacteria oxidise with the sulphate at a rate: written from PHREEQC, its RATES as a rate law and the electrons held at one pe, with PHREEQC's own column, to set beside the run, ticked. Run it: Against distance draws the sulphide coming up along the column at four times, PHREEQC's cells the points beside the run; the Fit tab's the run against what was measured, one to one, gives each column's Nash–Sutcliffe efficiency, 0.999 or more for the pH and the totals of each valence state.",
    text='''# A sulphate water flows through 1 m of a column whose rock holds organic
# carbon, which bacteria oxidise with the sulphate at a rate in it,
# k [S(6)] / (Ks + [S(6)]): the sulphate goes down along the column and
# sulphide comes up in its place, the water gaining carbonate and hydrogen
# sulphide, a weak acid, and its pH falling from 7.4 to 7.0. Written from
# PHREEQC by From PHREEQC... on the Model tab with PHREEQC's own column, to set
# beside the run, ticked: the rate is PHREEQC's RATES as a rate law, and the
# electrons the organic carbon gives are held at one pe with the sulphate and
# the sulphide, which the water starts with none of. PHREEQC's cells are under
# <DATA>, a table in distance at each of ten times, each cell at its downstream
# face, where the water in it has come to and reacted for as long. Run it:
# Against distance draws the sulphide coming up along the column, PHREEQC's
# cells the points beside the run; the Fit tab's Show, the run against what
# was measured, one to one, gives each column's Nash-Sutcliffe efficiency:
# 0.999 or more for the pH and the totals of each valence state on these 20
# cells. The input, to phreeqc.dat:
#   RATES Sulphate_reduction: rate = PARM(1) * s / (PARM(2) + s), s = TOT("S(6)")
#   SOLUTION 0, and 1-20 the same: units mmol/kgw; pH 7.4; Na 25; Ca 1;
#    Cl 22 charge; S(6) 2.5; C(4) 3
#   KINETICS 1-20: Sulphate_reduction, -formula CH2O 2, -m 1, -parms 1e-10 1e-4
#   TRANSPORT: -cells 20, -lengths 0.05, -shifts 60, -time_step 788940,
#    -diffusion_coefficient 1e-9, -dispersivities 0.005, -punch_frequency 6

<SETTINGS>
MODE = transport
CELLS = 20
LENGTH = 1
DIFFUSION = 1
ADVECTION = 1
ADVECTION_SCHEME = limited
VELOCITY = 6.33761756280579e-8
PECLET = 200
LEFT = robin
RIGHT = free
TEND = 47336400
TIME_UNIT = second
EQUILIBRATE = always
ACTIVITY = debye-huckel
TEMPERATURE = 25

<SPECIES>
H+                  4.5491223206984e-8      a=9  b=0  D=1e-9  left=4.5491223206984e-8
OH-                 3.00442585437961e-7     a=3.5  b=0  D=1e-9  left=3.00442585437961e-7
Na+                 0.0245366918448597      a=4.08  b=0.082  D=1e-9  left=0.0245366918448597
Cl-                 0.0192015681894972      a=3.63  b=0.017  D=1e-9  left=0.0192015681894972
HCO3-               0.00273610534887941     a=5.4  b=0  D=1e-9  left=0.00273610534887941
SO4-2               0.00198784383819433     a=5  b=-0.04  D=1e-9  left=0.00198784383819433
Ca+2                0.000901559501080946    a=5  b=0.165  D=1e-9  left=0.000901559501080946
NaSO4-              0.000421077122883917    a=5.5  b=0  D=1e-9  left=0.000421077122883917
CO2                 0.000209181013575586    b=0.066  D=1e-9  left=0.000209181013575586
CaSO4               0.0000910741953050396   D=1e-9  left=0.0000910741953050396
NaHCO3              0.0000422310322563727   b=0.2  D=1e-9  left=0.0000422310322563727
CaHCO3+             0.00000511905221857525  a=6  b=0  D=1e-9  left=0.00000511905221857525
CO3-2               0.00000511710291747376  a=5.4  b=0  D=1e-9  left=0.00000511710291747376
CaCO3               0.00000224484036270757  D=1e-9  left=0.00000224484036270757
HSO4-               4.81542655973321e-9     D=1e-9  left=4.81542655973321e-9
CaOH+               2.38284257422043e-9     D=1e-9  left=2.38284257422043e-9
CO2_2               8.04894941548927e-10    D=1e-9  left=8.04894941548927e-10
HCl                 2.16829245962995e-10    b=0.4256  D=1e-9  left=2.16829245962995e-10
CaHSO4+             2.81901589040987e-11    D=1e-9  left=2.81901589040987e-11
H2                  1.11448967702238e-26    D=1e-9  left=1.11448967702238e-26
H2S_2               0                       D=1e-9  left=0
CH4                 0                       D=1e-9  left=0
H2S                 0                       D=1e-9  left=0
HS-                 0                       a=3.5  b=0  D=1e-9  left=0
O2                  0                       D=1e-9  left=0
S-2                 0                       a=5  b=0  D=1e-9  left=0
e-                                          electron
Sulphate_reduction  1                       mineral

<EQUILIBRIUM>
CO3-2 + H+ <=> HCO3-,                 analytic = 107.8871 0.03252849 -5151.79 -38.92561 563713.9              # here 10.0702
Na+ + SO4-2 <=> NaSO4-,               analytic = 255.903 0.10057 0 -111.138 -859830                           # here 0.9362
CO3-2 + 2 H+ <=> CO2 + H2O,           analytic = 464.1965 0.09344813 -26986.16 -165.75951 2248628.9           # here 16.2956
Ca+2 + SO4-2 <=> CaSO4,               logK = 2.2500000000, dH = 5.5438                                        # here 1.7060
Na+ + HCO3- <=> NaHCO3,               logK = -0.0600000000, dH = 21                                           # here -0.2013
Ca+2 + CO3-2 + H+ <=> CaHCO3+,        analytic = -6.008999999999999 0.03377 2044                              # here 10.3872
Ca+2 + CO3-2 <=> CaCO3,               analytic = -1228.732 -0.29944 35512.75 485.818                          # here 2.6872
H2O <=> OH- + H+,                     analytic = 293.29227 0.1360833 -10576.913 -123.73158 0 -0.00006996455   # here -13.8643
SO4-2 + H+ <=> HSO4-,                 analytic = -56.889 0.006473 2307.9 19.8858                              # here 1.7263
Ca+2 + H2O <=> CaOH+ + H+,            logK = -12.7800000000                                                   # here -12.9200
2 CO2 <=> CO2_2,                      analytic = 8.679999999999888 -0.0103 -2190                              # here -1.7353
H+ + Cl- <=> HCl,                     analytic = 0.3340000000000001 -0.002684 1.015                           # here -0.6051
Ca+2 + HSO4- <=> CaHSO4+,             logK = 1.0800000000                                                     # here 0.8125
2 H+ + 2 e- <=> H2,                   logK = -3.1500000000, dH = -7.359656                                    # here -3.2688
2 H2S <=> H2S_2,                      analytic = 10.227 -0.01384 -2200                                        # here -1.2753
CO3-2 + 10 H+ + 8 e- <=> CH4 + 3 H2O, logK = 41.0710000000, dH = -255.387176                                  # here 40.2222
HS- + H+ <=> H2S,                     analytic = -11.17 0.02386 3279                                          # here 6.8079
SO4-2 + 9 H+ + 8 e- <=> HS- + 4 H2O,  logK = 33.6500000000, dH = -251.62576                                   # here 32.9295
2 H2O <=> O2 + 4 H+ + 4 e-,           logK = -86.0800000000, dH = 563.96136                                   # here -85.8520
HS- <=> S-2 + H+,                     logK = -12.9180000000, dH = 50.6264                                     # here -12.6606

<VOLUMES>
OH-      -9.66  28.5  80  -22.9  1.89  0  1.09  0  0  1
Na+      2.28  -4.38  -4.1  -0.586  0.09  4  0.3  52  -0.00333  0.566
Cl-      4.465  4.801  4.325  -2.847  1.748  0  -0.331  20.16  0  1
HCO3-    10.26  -2.92  -12.58  -0.241  2.23  0  -5.49  320  0.0283  1.144
SO4-2    -7.77  43.17  176  -51.45  3.794  0  42.99  -541  -0.145  0.45
Ca+2     -0.3456  -7.252  6.149  -2.479  1.239  5  1.6  -57.1  -0.00612  1
NaSO4-   1.99  -10.78  21.88  -12.7  1.601  5  32.38  501  0.01565  0.2325
CO2      7.29  0.92  2.07  -1.23  -1.6
CaSO4    2.791  -0.9666  6.13  -2.739  -0.001
NaHCO3   7.95  0  0  0  0.609
CaHCO3+  30.19  0.01  5.75  -2.78  0.308  5.4
CO3-2    6.09  -2.78  -0.405  -5.3  5.02  0  0.169  101  -0.0138  0.9316
CaCO3    -0.243  -8.3748  9.0417  -2.4328  -0.03
HSO4-    8.2  9.259  2.1108  -3.1618  1.1748  0  -0.3  15  0  1
CO2_2    14.58  1.84  4.14  -2.46  -3.2
H2       6.52  0.78  0.12
H2S_2    36.41  -71.95  0  0  2.58
CH4      9.01  -1.11  0  -1.85  -1.5
H2S      1.39  28.3  0  -7.22  -0.59
HS-      5.0119  4.9799  3.4765  -2.9849  1.441
O2       5.7889  6.3536  3.2528  -3.0417  -0.3943

<CONDUCTANCE>
H+       gfw 1.008  dw 9.31e-9 838 6.96 -2.285 0.206 24.01 0  viscosity 0.0935 -0.0831 0.02487 0.000449 0.0201 1.57
OH-      gfw 17.008  dw 5.27e-9 478 0.8695  viscosity -0.0226 0.106 0.02184 -0.0032 0 0.4082 -1.634
Na+      gfw 22.9898  dw 1.33e-9 75 3.627 0 0.7037  viscosity 0.1387 -0.0866 0.0125 0.0145 0.0075 1.062
Cl-      gfw 35.453  dw 2.033e-9 216 3.16 0.2071 0.7432  viscosity 0 0 0 0 0 0 1
HCO3-    gfw 61.0191  dw 1.18e-9 -190 11.386  viscosity -0.6 1.366 -0.01216 0 0.03139 -1.135 1.253
SO4-2    gfw 96.064  dw 1.07e-9 -114 17 0.0602 0.0494  viscosity -0.3 0.501 0.00257 0.195 0.0314 2.015 0.605
Ca+2     gfw 40.08  dw 7.92e-10 34 5.411 0 1.046  viscosity 0.359 -0.158 0.042 0.0015 0.00804 2.3
NaSO4-   gfw 119.0538  dw 1.13e-9 -23 8.5 0.392 0.521  viscosity 0.2 -0.0593 -0.0004 0.00846 0.00178 2.308 -0.208
CO2      gfw 44.0111  dw 1.92e-9 -120  viscosity 0.0068 0.0903 0.0327 0 0 0 0.18
CaSO4    gfw 136.144  dw 4.71e-10
NaHCO3   gfw 84.0089  dw 6.73e-10  viscosity -0.04 -2.717 0.0000167
CaHCO3+  gfw 101.0991  dw 5.06e-10
CO3-2    gfw 60.0111  dw 9.55e-10 -103 2.246 0.0713 0.3686  viscosity -0.5 0.6521 0.00544 0.00106 -0.0218 1.208 -2.147
CaCO3    gfw 100.0911  dw 4.46e-10
HSO4-    gfw 97.072  dw 1.22e-9 1000 15 2.861  viscosity 0.5 -0.0697 0.0607 0.00001 -0.1333 0.4865 0.7987
CaOH+    gfw 57.088
CO2_2    gfw 88.0222  dw 1.92e-9 -120  viscosity 0.0136 0.1806 0.0327 0 0 0 0.36
HCl      gfw 36.461  viscosity 0.921 -0.765 0.00832 0.000825 0.00253 4.223
CaHSO4+  gfw 137.152
H2       gfw 2.016  dw 5.13e-9
H2S_2    gfw 68.16  dw 2.1e-9
CH4      gfw 16.0431  dw 1.85e-9
H2S      gfw 34.08  dw 2.1e-9
HS-      gfw 33.072  dw 1.73e-9
O2       gfw 32  dw 2.35e-9
S-2      gfw 32.064  dw 7.31e-10
H2O      gfw 18.016

<REACTIONS>
# Sulphate_reduction: PHREEQC's RATES Sulphate_reduction, M its moles, M0 1, PARM 1e-10 0.0001, a time step TIME:
#   10 s = TOT("S(6)")
#   20 rate = PARM(1) * s / (PARM(2) + s)
#   30 SAVE rate * TIME
Sulphate_reduction => 2 CO3-2 + 12 H+ + 8 e-, r = rate, p1 = 1e-10, p2 = 0.0001, rate = p1*([SO4-2] + [NaSO4-] + [CaSO4] + [HSO4-] + [CaHSO4+])/(p2 + ([SO4-2] + [NaSO4-] + [CaSO4] + [HSO4-] + [CaHSO4+]))

<DATA>
# PHREEQC's own TRANSPORT of the input this model was written from, run in the page: a cell of PHREEQC's
# after shift k as this model's cell half a time step later, at its centre.
# With KINETICS, its water at the cell's downstream face at the shift instead, carried as many cells as it
# has reacted time steps, as the water there has; the run is read there between its cells' centres.
# Left out, PHREEQC's cells holding each at one value: tot(Ca), tot(Cl), tot(Na).
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 4733640
0.05  7.284336  0.003218922  1.999777e-7  0.002390633  0.0001093631
0.1  7.235467  0.003353362  3.315131e-7  0.002323476  0.0001765186
0.15  7.193041  0.00350139  4.873144e-7  0.002249537  0.0002504559
0.2  7.163663  0.003626741  6.300922e-7  0.00218693  0.000313061
0.25  7.142545  0.00373158  7.582945e-7  0.002134572  0.0003654172
0.3  7.128436  0.003809851  8.597854e-7  0.002095486  0.0004045027
0.35  7.11995  0.003860543  9.283479e-7  0.002070173  0.0004298146
0.4  7.115485  0.003888393  9.670096e-7  0.002056267  0.0004437205
0.45  7.113531  0.003900847  9.845332e-7  0.002050048  0.000449939
0.5  7.112871  0.003905097  9.905464e-7  0.002047926  0.000452061
0.55  7.112729  0.00390601  9.918398e-7  0.00204747  0.0004525166
0.6  7.112732  0.003905991  9.918131e-7  0.00204748  0.0004525072
0.65  7.11275  0.003905872  9.916447e-7  0.002047539  0.0004524479
0.7  7.11276  0.003905812  9.915592e-7  0.002047569  0.0004524178
0.75  7.112763  0.003905793  9.915322e-7  0.002047579  0.0004524083
0.8  7.112763  0.003905788  9.915262e-7  0.002047581  0.0004524062
0.85  7.112764  0.003905788  9.915252e-7  0.002047581  0.0004524058
0.9  7.112764  0.003905788  9.915251e-7  0.002047581  0.0004524058
0.95  7.112764  0.003905788  9.915251e-7  0.002047581  0.0004524058
1  7.112764  0.003905788  9.915251e-7  0.002047581  0.0004524058
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 9467280
0.05  7.283854  0.003220097  2.010923e-7  0.002390047  0.0001099499
0.1  7.233891  0.00335828  3.364906e-7  0.00232102  0.0001789749
0.15  7.189095  0.00351701  5.045275e-7  0.002241735  0.0002582573
0.2  7.155385  0.003666212  6.77366e-7  0.002167217  0.000332773
0.25  7.127546  0.003815035  8.666918e-7  0.002092897  0.0004070912
0.3  7.104328  0.003961834  0.000001072495  0.002019598  0.0004803888
0.35  7.084894  0.004104471  0.000001293092  0.001948386  0.0005515983
0.4  7.068657  0.00424047  0.00000152481  0.0018805  0.0006194827
0.45  7.05526  0.004366396  0.000001760256  0.001817653  0.0006823288
0.5  7.044443  0.00447858  0.000001988843  0.001761673  0.0007383074
0.55  7.03598  0.004573793  0.000002198188  0.001714169  0.0007858099
0.6  7.029624  0.004650059  0.000002376922  0.001676124  0.0008238542
0.65  7.025086  0.004707216  0.000002517772  0.001647615  0.0008523628
0.7  7.022035  0.004746974  0.000002619419  0.001627786  0.000872191
0.75  7.020125  0.004772446  0.000002686188  0.001615083  0.0008848936
0.8  7.019022  0.004787361  0.000002725899  0.001607645  0.0008923319
0.85  7.018441  0.004795278  0.00000274716  0.001603697  0.0008962793
0.9  7.018166  0.004799045  0.000002757326  0.001601818  0.0008981582
0.95  7.01805  0.004800627  0.000002761601  0.00160103  0.0008989467
1  7.018011  0.004801166  0.000002763061  0.001600761  0.0008992158
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 14200920
0.05  7.283848  0.003220111  2.011056e-7  0.00239004  0.0001099569
0.1  7.233869  0.003358347  3.365584e-7  0.002320986  0.0001790083
0.15  7.189031  0.003517265  5.048104e-7  0.002241607  0.0002583849
0.2  7.155218  0.003667027  6.783556e-7  0.00216681  0.0003331804
0.25  7.127158  0.003817308  8.697278e-7  0.002091762  0.0004082262
0.3  7.103506  0.003967469  0.000001080808  0.002016784  0.0004832025
0.35  7.083304  0.004117065  0.000001313634  0.001942099  0.0005578851
0.4  7.065815  0.004266073  0.000001570978  0.001867721  0.0006322613
0.45  7.050541  0.004414097  0.000001855174  0.001793848  0.0007061325
0.5  7.03712  0.004560558  0.000002168196  0.001720772  0.0007792072
0.55  7.025295  0.004704524  0.000002511  0.001648957  0.0008510201
0.6  7.014887  0.004844645  0.000002882736  0.00157908  0.0009208956
0.65  7.005775  0.00497912  0.000003279778  0.001512039  0.0009879354
0.7  6.997875  0.005105766  0.000003694805  0.001448921  0.001051052
0.75  6.991126  0.00522221  0.000004116349  0.001390908  0.001109064
0.8  6.985472  0.005326186  0.000004529272  0.001339125  0.001160846
0.85  6.980849  0.005415888  0.000004916483  0.001294465  0.001205504
0.9  6.977184  0.005490238  0.00000526146  0.001257461  0.001242507
0.95  6.974446  0.005547727  0.000005544466  0.001228858  0.00127111
1  6.972865  0.005581706  0.000005718862  0.001211954  0.001288013
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 18934560
0.05  7.283848  0.003220111  2.011058e-7  0.002390039  0.000109957
0.1  7.233869  0.003358348  3.365595e-7  0.002320986  0.0001790088
0.15  7.18903  0.00351727  5.048152e-7  0.002241605  0.000258387
0.2  7.155215  0.003667043  6.783744e-7  0.002166802  0.0003331882
0.25  7.127149  0.003817357  8.697931e-7  0.002091738  0.0004082506
0.3  7.103486  0.00396761  0.000001081015  0.002016714  0.0004832725
0.35  7.083258  0.004117435  0.000001314239  0.001941915  0.0005580695
0.4  7.065716  0.004266973  0.000001572617  0.001867272  0.0006327108
0.45  7.050343  0.00441614  0.000001859313  0.001792829  0.0007071519
0.5  7.036746  0.004564886  0.000002177973  0.001718612  0.0007813668
0.55  7.024627  0.004713123  0.000002532679  0.001644669  0.0008553087
0.6  7.013756  0.004860706  0.000002927978  0.001571072  0.0009289037
0.65  7.003956  0.005007407  0.00000336883  0.00149794  0.001002035
0.7  6.995089  0.005152865  0.000003860422  0.001425453  0.001074519
0.75  6.98705  0.005296542  0.000004407791  0.001353886  0.001146085
0.8  6.979761  0.005437659  0.000005015144  0.001283629  0.00121634
0.85  6.973169  0.005575135  0.000005684707  0.001215223  0.001284744
0.9  6.967244  0.005707408  0.000006414264  0.001149449  0.001350517
0.95  6.962187  0.005827371  0.000007160988  0.001089839  0.001410126
1  6.958966  0.005907393  0.000007711058  0.001050101  0.001449863
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 23668200
0.05  7.283848  0.003220111  2.011058e-7  0.002390039  0.000109957
0.1  7.233869  0.003358348  3.365595e-7  0.002320986  0.0001790089
0.15  7.18903  0.00351727  5.048153e-7  0.002241605  0.0002583871
0.2  7.155215  0.003667043  6.783747e-7  0.002166802  0.0003331883
0.25  7.127149  0.003817358  8.697945e-7  0.002091737  0.0004082511
0.3  7.103485  0.003967613  0.00000108102  0.002016712  0.000483274
0.35  7.083256  0.004117444  0.000001314254  0.00194191  0.0005580741
0.4  7.065713  0.004266998  0.000001572662  0.00186726  0.0006327231
0.45  7.050337  0.004416203  0.000001859441  0.001792798  0.0007071833
0.5  7.036733  0.004565038  0.000002178316  0.001718537  0.0007814424
0.55  7.0246  0.004713468  0.000002533553  0.001644496  0.000855481
0.6  7.013704  0.004861453  0.000002930096  0.0015707  0.0009292761
0.65  7.003859  0.005008942  0.00000337372  0.001497175  0.0010028
0.7  6.994914  0.005155868  0.000003871199  0.001423958  0.001076015
0.75  6.98675  0.00530214  0.000004430496  0.001351098  0.001148872
0.8  6.979267  0.005447622  0.000005060936  0.00127867  0.001221299
0.85  6.972388  0.005592084  0.000005773223  0.001206793  0.001293175
0.9  6.96606  0.005734896  0.000006577724  0.001135786  0.00136418
0.95  6.960516  0.005868536  0.00000743838  0.001069394  0.00143057
1  6.956915  0.005959831  0.000008096781  0.001024075  0.001475889
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 28401840
0.05  7.283848  0.003220111  2.011058e-7  0.002390039  0.000109957
0.1  7.233869  0.003358348  3.365595e-7  0.002320986  0.0001790089
0.15  7.18903  0.00351727  5.048153e-7  0.002241605  0.0002583871
0.2  7.155215  0.003667043  6.783747e-7  0.002166802  0.0003331883
0.25  7.127149  0.003817358  8.697945e-7  0.002091737  0.0004082511
0.3  7.103485  0.003967613  0.00000108102  0.002016712  0.0004832741
0.35  7.083256  0.004117444  0.000001314254  0.00194191  0.0005580742
0.4  7.065713  0.004266999  0.000001572663  0.001867259  0.0006327234
0.45  7.050337  0.004416205  0.000001859444  0.001792797  0.0007071841
0.5  7.036733  0.004565042  0.000002178326  0.001718535  0.0007814446
0.55  7.024599  0.004713479  0.00000253358  0.001644491  0.0008554865
0.6  7.013702  0.004861479  0.00000293017  0.001570687  0.0009292892
0.65  7.003855  0.005009001  0.000003373911  0.001497145  0.001002829
0.7  6.994906  0.005155999  0.000003871669  0.001423892  0.00107608
0.75  6.986735  0.005302414  0.000004431611  0.001350962  0.001149009
0.8  6.97924  0.005448174  0.000005063484  0.001278395  0.001221574
0.85  6.972339  0.005593148  0.000005778827  0.001206263  0.001293704
0.9  6.965977  0.005736848  0.000006589497  0.001134816  0.00136515
0.95  6.960385  0.005871773  0.000007460685  0.001067787  0.001432178
1  6.956747  0.005964194  0.000008129833  0.00102191  0.001478054
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 33135480
0.05  7.283848  0.003220111  2.011058e-7  0.002390039  0.000109957
0.1  7.233869  0.003358348  3.365595e-7  0.002320986  0.0001790089
0.15  7.18903  0.00351727  5.048153e-7  0.002241605  0.0002583871
0.2  7.155215  0.003667043  6.783747e-7  0.002166802  0.0003331883
0.25  7.127149  0.003817358  8.697945e-7  0.002091737  0.0004082511
0.3  7.103485  0.003967613  0.00000108102  0.002016712  0.0004832741
0.35  7.083256  0.004117444  0.000001314254  0.00194191  0.0005580742
0.4  7.065713  0.004266999  0.000001572663  0.001867259  0.0006327234
0.45  7.050337  0.004416205  0.000001859444  0.001792797  0.0007071841
0.5  7.036733  0.004565043  0.000002178326  0.001718535  0.0007814446
0.55  7.024599  0.00471348  0.000002533581  0.001644491  0.0008554866
0.6  7.013702  0.00486148  0.000002930173  0.001570686  0.0009292895
0.65  7.003855  0.005009003  0.000003373917  0.001497144  0.00100283
0.7  6.994906  0.005156003  0.000003871686  0.00142389  0.001076082
0.75  6.986735  0.005302425  0.000004431654  0.001350957  0.001149014
0.8  6.979239  0.005448197  0.000005063591  0.001278384  0.001221585
0.85  6.972337  0.005593197  0.000005779084  0.001206239  0.001293728
0.9  6.965972  0.005736945  0.000006590086  0.001134768  0.001365198
0.95  6.960378  0.005871946  0.00000746188  0.001067701  0.001432264
1  6.956738  0.005964435  0.000008131669  0.00102179  0.001478174
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 37869120
0.05  7.283848  0.003220111  2.011058e-7  0.002390039  0.000109957
0.1  7.233869  0.003358348  3.365595e-7  0.002320986  0.0001790089
0.15  7.18903  0.00351727  5.048153e-7  0.002241605  0.0002583871
0.2  7.155215  0.003667043  6.783747e-7  0.002166802  0.0003331883
0.25  7.127149  0.003817358  8.697945e-7  0.002091737  0.0004082511
0.3  7.103485  0.003967613  0.00000108102  0.002016712  0.0004832741
0.35  7.083256  0.004117444  0.000001314254  0.00194191  0.0005580742
0.4  7.065713  0.004266999  0.000001572663  0.001867259  0.0006327234
0.45  7.050337  0.004416205  0.000001859444  0.001792797  0.0007071841
0.5  7.036733  0.004565043  0.000002178326  0.001718535  0.0007814446
0.55  7.024599  0.00471348  0.000002533581  0.001644491  0.0008554866
0.6  7.013702  0.00486148  0.000002930173  0.001570686  0.0009292896
0.65  7.003855  0.005009003  0.000003373917  0.001497144  0.00100283
0.7  6.994906  0.005156003  0.000003871686  0.00142389  0.001076082
0.75  6.986735  0.005302425  0.000004431655  0.001350956  0.001149014
0.8  6.979239  0.005448198  0.000005063595  0.001278383  0.001221586
0.85  6.972336  0.005593199  0.000005779094  0.001206238  0.001293729
0.9  6.965972  0.005736949  0.00000659011  0.001134766  0.0013652
0.95  6.960378  0.005871954  0.00000746193  0.001067697  0.001432267
1  6.956737  0.005964446  0.000008131748  0.001021784  0.001478179
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 42602760
0.05  7.283848  0.003220111  2.011058e-7  0.002390039  0.000109957
0.1  7.233869  0.003358348  3.365595e-7  0.002320986  0.0001790089
0.15  7.18903  0.00351727  5.048153e-7  0.002241605  0.0002583871
0.2  7.155215  0.003667043  6.783747e-7  0.002166802  0.0003331883
0.25  7.127149  0.003817358  8.697945e-7  0.002091737  0.0004082511
0.3  7.103485  0.003967613  0.00000108102  0.002016712  0.0004832741
0.35  7.083256  0.004117444  0.000001314254  0.00194191  0.0005580742
0.4  7.065713  0.004266999  0.000001572663  0.001867259  0.0006327234
0.45  7.050337  0.004416205  0.000001859444  0.001792797  0.0007071841
0.5  7.036733  0.004565043  0.000002178326  0.001718535  0.0007814446
0.55  7.024599  0.00471348  0.000002533581  0.001644491  0.0008554866
0.6  7.013702  0.00486148  0.000002930173  0.001570686  0.0009292896
0.65  7.003855  0.005009003  0.000003373917  0.001497144  0.00100283
0.7  6.994906  0.005156003  0.000003871686  0.00142389  0.001076082
0.75  6.986735  0.005302425  0.000004431655  0.001350956  0.001149014
0.8  6.979239  0.005448198  0.000005063595  0.001278383  0.001221586
0.85  6.972336  0.005593199  0.000005779094  0.001206238  0.001293729
0.9  6.965972  0.005736949  0.000006590111  0.001134766  0.0013652
0.95  6.960378  0.005871954  0.000007461932  0.001067697  0.001432267
1  6.956737  0.005964446  0.000008131751  0.001021784  0.001478179
distance  pH  tot(C(4))  tot(C(-4))  tot(S(6))  tot(S(-2))  at = 47336400
0.05  7.283848  0.003220111  2.011058e-7  0.002390039  0.000109957
0.1  7.233869  0.003358348  3.365595e-7  0.002320986  0.0001790089
0.15  7.18903  0.00351727  5.048153e-7  0.002241605  0.0002583871
0.2  7.155215  0.003667043  6.783747e-7  0.002166802  0.0003331883
0.25  7.127149  0.003817358  8.697945e-7  0.002091737  0.0004082511
0.3  7.103485  0.003967613  0.00000108102  0.002016712  0.0004832741
0.35  7.083256  0.004117444  0.000001314254  0.00194191  0.0005580742
0.4  7.065713  0.004266999  0.000001572663  0.001867259  0.0006327234
0.45  7.050337  0.004416205  0.000001859444  0.001792797  0.0007071841
0.5  7.036733  0.004565043  0.000002178326  0.001718535  0.0007814446
0.55  7.024599  0.00471348  0.000002533581  0.001644491  0.0008554866
0.6  7.013702  0.00486148  0.000002930173  0.001570686  0.0009292896
0.65  7.003855  0.005009003  0.000003373917  0.001497144  0.00100283
0.7  6.994906  0.005156003  0.000003871686  0.00142389  0.001076082
0.75  6.986735  0.005302425  0.000004431655  0.001350956  0.001149014
0.8  6.979239  0.005448198  0.000005063595  0.001278383  0.001221586
0.85  6.972336  0.005593199  0.000005779094  0.001206238  0.001293729
0.9  6.965972  0.005736949  0.000006590111  0.001134766  0.0013652
0.95  6.960378  0.005871954  0.000007461932  0.001067697  0.001432267
1  6.956737  0.005964446  0.000008131751  0.001021784  0.001478179
''',
    view={'tab': 'profile', 'timeIn': 'pv', 'profile': {'species': 'tot(S(-2))', 'times': '0.3, 0.6, 1.2, 3', 'log': False}},
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
    label='Zinc on ferrihydrite: its sorption edges and isotherm fitted',
    about="Zinc and a ferrihydrite surface, as in Zinc on ferrihydrite, with the share of the zinc on the surface measured at eight pHs, again at a hundred times the zinc -- the second table's own water, Zn+2 = 1e-4 on its line -- and at pH 6.5 at eight totals of zinc, an isotherm: a table against sys(Zn), the zinc in the cell, its line holding the pH. Each measurement has a standard deviation of 1 %, all made up for the purpose. Run it: the Fit tab moves the log K of the zinc on the strong sites and on the weak ones from phreeqc.dat's 0.99 and -1.99 until the edges and the isotherm go through what <DATA> measured, as PhreePlot fits sorption data, and draws them through their measurements, the edges against pH and, under against, the isotherm against the zinc in the cell: 1.311 and -1.595, chi-square 12.2 on 22 degrees of freedom. The second edge, its strong sites full, halves the standard error of the weak sites' constant that one edge leaves it, and the isotherm halves it again.",
    text=_retitled(_text('sorptionedge'), '''# Zinc on ferrihydrite, its strong and weak sites as Dzombak and Morel give
# them, and the share of the zinc on the surface measured at eight pHs, in
# <DATA>: a table against pH is of the water held at each pH, as the Diagrams
# tab holds it. The Fit tab moves the log K of the zinc on each kind of site
# until the edges go through the measurements, as PhreePlot fits them, each
# measurement weighed by its standard deviation, sd(Zn_sorbed): the misfit is
# then chi-square. A second edge at a hundred times the zinc, Zn+2 = 1e-4 on
# its table's line, fills the strong sites and pins the weak sites' constant
# down; an isotherm at pH 6.5, a table against sys(Zn) -- the zinc in the
# cell, dissolved and sorbed -- pins it down further. phreeqc.dat's
# constants; no double layer; the measurements and their deviations are made
# up.''') + '''
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

sys(Zn)   Zn_sorbed   sd(Zn_sorbed)   pH = 6.5
1e-7      97.3        1
3e-7      95.7        1
1e-6      96.5        1
3e-6      93.4        1
1e-5      78.9        1
3e-5      63.9        1
1e-4      55.0        1
3e-4      38.5        1
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
    # Each text opens with its title, the label the picker gives it, written ## as the panel's Model reads a title. Put
    # here, where the texts are written out, so that an example made from another's text takes that text untitled.
    examples = [dict(e, text=f"## {e['label']}\n{e['text']}") for e in EXAMPLES]

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
