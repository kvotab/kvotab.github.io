/* ==========================================================================
   RTM.HTML: THE EXAMPLE MODELS

   Written by scripts/gen-rtm-examples.py -- edit that, not this.

   Each is a complete model text the Model tab can load, chosen to show one
   thing the format can do and, where there is one, to have an answer that can
   be checked against something other than this code.

   resources/tests/rtm/test-model.js compiles every one of them.
   ========================================================================== */

const RTM_EXAMPLES = [
  {
    "id": "ab",
    "group": "Getting started",
    "label": "A → B → C",
    "about": "The smallest thing that runs: three species, two first-order steps, one stirred cell. B rises and falls; the three always add up to one.",
    "text": "# The smallest model that does anything: A decays to B, B to C.\n# Everything after a # is a comment.\n\n<SETTINGS>\nMODE = batch          # one stirred cell, no transport\nTEND = 20             # how long to integrate, in the unit below\nTIME_UNIT = second\n\n<SPECIES>\nA  1.0                # name, then the concentration it starts at\nB  0.0\nC  0.0\n\n<REACTIONS>\nA => B, k = 0.5       # mass action: the rate is k times A\nB => C, k = 0.2\n"
  },
  {
    "id": "mm",
    "group": "Getting started",
    "label": "Michaelis–Menten",
    "about": "A rate law of your own rather than mass action: v_max·S/(K_m + S), with the constants named on the line. Shows the r = form and [S] for a concentration.",
    "text": "# A rate law written out, instead of mass action.\n#\n# With k = the rate is k times each reactant raised to its coefficient. With\n# r = you write the rate yourself, and a concentration goes in brackets so\n# that a name like H+ is never read as arithmetic.\n\n<SETTINGS>\nMODE = batch\nTEND = 400\nTIME_UNIT = second\n\n<SPECIES>\nS  1.0E-3             # substrate\nP  0.0                # product\n\n<REACTIONS>\nS => P, r = vmax*[S]/(km + [S]), vmax = 1.0E-5, km = 2.0E-4\n"
  },
  {
    "id": "robertson",
    "group": "Standard test cases",
    "label": "Robertson (1966), stiff kinetics",
    "about": "The test case stiff solvers are measured against: three rate constants spanning nine orders, and A + B + C exactly 1 for all time. At t = 0.4 the published answer is 0.9851721, 3.3864e-5, 0.0147939 — this page gives it to seven figures.",
    "reference": "H. H. Robertson, \"The solution of a set of reaction rate equations\", in J. Walsh (ed.), Numerical Analysis: An Introduction, Academic Press (1966). Used as the stiff benchmark by Hairer & Wanner and by every ODE suite since.",
    "text": "# Robertson's problem, the classic test of a stiff solver.\n#\n#   A       -> B         k1 = 0.04\n#   B + B   -> C + B     k2 = 3e7      (B is consumed and remade: a catalyst)\n#   B + C   -> A + C     k3 = 1e4\n#\n# A + B + C is exactly 1 for all time, which is the first thing to check: at\n# a tight tolerance this page holds it to 3e-15. B rises to 3.65e-5 within the\n# first hundredth of a second and then falls away for ever.\n#\n# The point everyone quotes is t = 0.4, where the answer is\n#     A = 0.9851721   B = 3.3864e-5   C = 0.0147939\n# Tick all three species, set the time axis to log, and read it off.\n\n<SETTINGS>\nMODE = batch\nTEND = 1.0E7\nTIME_UNIT = second\n\n<SPECIES>\nA  1.0\nB  0.0\nC  0.0\n\n<REACTIONS>\nA => B, k = 0.04\nB + B => C + B, k = 3.0E7\nB + C => A + C, k = 1.0E4\n"
  },
  {
    "id": "brusselator",
    "group": "Standard test cases",
    "label": "Brusselator, an oscillator",
    "about": "A reaction set that does not settle: X and Y go round a limit cycle for ever. Worth drawing with a linear time axis rather than a log one.",
    "reference": "Prigogine and Lefever (1968). The parameters here are the usual A = 1, B = 3, which is past the Hopf bifurcation at B = 1 + A².",
    "text": "# The Brusselator: an autocatalytic set with a limit cycle.\n#\n# A and B are held (fixed), so the set never runs down. With B = 3 > 1 + A²\n# the steady state is unstable and X and Y circle it for ever.\n#\n# Turn the log time axis OFF to see the oscillation.\n\n<SETTINGS>\nMODE = batch\nTEND = 60\nTIME_UNIT = second\n\n<SPECIES>\nA  1.0  fixed         # fixed: drives the rates, never changes\nB  3.0  fixed\nX  1.0\nY  1.0\n\n<REACTIONS>\nA => X, k = 1.0                   # X made from the reservoir\nB + X => Y, k = 1.0               # and turned into Y\nX + X + Y => X + X + X, k = 1.0   # the autocatalytic step\nX => , k = 1.0                    # X leaves\n"
  },
  {
    "id": "carbonate",
    "group": "Chemistry",
    "label": "Carbonate speciation",
    "about": "Three coupled equilibria solved before the run: pH, the carbonate system, and the conserved totals worked out from the stoichiometry alone.",
    "text": "# Equilibria rather than rates.\n#\n# EQUILIBRATE = 1 puts the starting concentrations on these relations before\n# anything is integrated: a damped Newton iteration in ln C. What it may not\n# change is worked out from the relations themselves -- total carbon and\n# charge here -- so no table of elements is needed.\n#\n# Compile this and the panel reports the conserved totals. The starting\n# numbers below are deliberately nowhere near equilibrium.\n\n<SETTINGS>\nMODE = batch\nTEND = 1\nTIME_UNIT = second\nEQUILIBRATE = 1\n\n<SPECIES>\nH+      1.0E-7\nOH-     1.0E-7\nCO2     1.0E-3\nHCO3-   1.0E-5\nCO3-2   1.0E-9\n\n<EQUILIBRIUM>\n <=> H+ + OH-,          logK = -14      # water; nothing on the left\nCO2 <=> H+ + HCO3-,     logK = -6.35\nHCO3- <=> H+ + CO3-2,   logK = -10.33\n"
  },
  {
    "id": "tracer",
    "group": "Transport",
    "label": "Tracer in a column",
    "about": "Advection and dispersion along a column, against the Ogata–Banks solution. The upwind scheme adds v·Δx/2 of dispersion of its own, which is what the warning about the grid is for: halve the cells and watch it appear.",
    "text": "# A tracer entering a column of flowing water.\n#\n# LEFT = dirichlet holds the face at the concentration on the species line;\n# the front then travels at the pore velocity and spreads by D.\n#\n# The answer is Ogata and Banks (1961), with D + v*dx/2 rather than D --\n# first-order upwinding disperses on its own, and the page says so when that\n# part gets large. Try CELLS = 20 and read the warning.\n\n<SETTINGS>\nMODE = transport\nCELLS = 400\nLENGTH = 1.0\nGRID = linear\nDIFFUSION = 1\nADVECTION = 1\nVELOCITY = 1.0E-6     # m/s, positive left to right\nPOROSITY = 1\nLEFT = dirichlet\nRIGHT = neumann\nTEND = 3.0E5\nTIME_UNIT = second\n\n<SPECIES>\nX  0.0  D=2.0E-8  left=1.0\n\n<REACTIONS>\n"
  },
  {
    "id": "danckwerts",
    "group": "Transport",
    "label": "Danckwerts inlet and free exit",
    "about": "The third-type inlet: the flow carries the concentration in and nothing else crosses. The column then balances exactly — what goes in less what leaves is all that changes the mass in it, to one part in 10^15.",
    "text": "# The four kinds of face, and why the inlet matters.\n#\n#   robin (cauchy)  the flow carries left= in and NOTHING else crosses:\n#                   the whole flux through the face is u*c. Danckwerts' inlet.\n#   free (outflow)  zero gradient; the flow takes what it takes.\n#   dirichlet       the face HELD at left=, which adds a diffusive flux on top\n#                   of what the water brings -- more goes in than the flow\n#                   carries, and the column's mass balance does not close.\n#   neumann         nothing crosses.\n#\n# Switch LEFT to dirichlet and compare the profiles at the same time.\n\n<SETTINGS>\nMODE = transport\nCELLS = 40\nLENGTH = 1.0\nDIFFUSION = 1\nADVECTION = 1\nVELOCITY = 1.0E-6\nLEFT = robin\nRIGHT = free\nTEND = 2.0E6\nTIME_UNIT = second\n\n<SPECIES>\nX  0.0  D=2.0E-7  left=1.0\n\n<REACTIONS>\n"
  },
  {
    "id": "retarded",
    "group": "Transport",
    "label": "Sorption: a retarded front",
    "about": "R = on a species line is the coefficient on the left of R·dC/dt = …: a retardation factor. R = 4 makes the front travel at a quarter of the water speed, and slows the reactions by the same factor.",
    "text": "# Sorption as a retardation factor.\n#\n# R= (or mass=) divides everything that happens to a species, transport and\n# reactions alike. Y has R = 4 and so travels at a quarter of X's speed.\n# It may also name a parameter, which is how it varies down a column.\n\n<SETTINGS>\nMODE = transport\nCELLS = 200\nLENGTH = 1.0\nDIFFUSION = 1\nADVECTION = 1\nVELOCITY = 1.0E-6\nLEFT = robin\nRIGHT = free\nTEND = 6.0E5\nTIME_UNIT = second\n\n<SPECIES>\nX  0.0  D=2.0E-8  left=1.0          # unretarded\nY  0.0  D=2.0E-8  left=1.0  R=4     # four times slower\n\n<REACTIONS>\n"
  },
  {
    "id": "doseprofile",
    "group": "Transport",
    "label": "A source that varies down the column",
    "about": "<PARAMETERS> gives a named number that may differ from cell to cell — here a dose rate dying away from a surface over the range of an alpha particle. The expression may use x, the cell centre in metres.",
    "text": "# A parameter that varies with position.\n#\n# The value is an expression in x (the cell centre, in metres), i (the cell\n# index) and any parameter named above it, worked out once when the model\n# compiles. This is how a dose rate that dies away from a surface is written,\n# or a porosity that changes down a column, or a rate constant following a\n# temperature.\n\n<SETTINGS>\nMODE = transport\nCELLS = 40\nLENGTH = 1.0E-4\nDIFFUSION = 1\nLEFT = neumann\nRIGHT = neumann\nTEND = 100\nTIME_UNIT = second\n\n<SPECIES>\nP  0.0  D=1.0E-9\n\n<PARAMETERS>\nDOSE  all  0.64*exp(-x/3.0E-5)    # Gy/s, falling over the alpha range\n\n<REACTIONS>\n=> P, k = G*DOSE, G = 1.0E-7      # G in mol/J times the dose rate\n"
  },
  {
    "id": "matrixtracer",
    "group": "Dual porosity",
    "label": "Matrix diffusion: a tracer",
    "about": "A fracture beside porous rock. The breakthrough is held back by diffusion into the stagnant pore water, and follows the erfc solution for a semi-infinite matrix.",
    "text": "# Dual porosity: water flows along a fracture, the rock beside it is stagnant.\n#\n# Every cell of the column gets MATRIX_CELLS stagnant cells behind it, reaching\n# MATRIX_DEPTH into the rock. The layers grow geometrically from the wall,\n# because the gradient is steepest there.\n#\n# WETTED_SURFACE is the rock surface a cubic metre of flowing water touches;\n# APERTURE (2b) says the same thing as 2/aperture.\n#\n# The breakthrough at the far end follows\n#     c/c0 = erfc( aw*tw*sqrt(De*Rm) / (2*sqrt(t - tw)) )\n# with tw the water travel time -- to within 0.01 on this grid, and better on\n# a finer one. Set MATRIX_CELLS = 0 and the tracer arrives at once instead.\n\n<SETTINGS>\nMODE = transport\nCELLS = 100\nLENGTH = 20            # m; with VELOCITY = 1 the travel time is 20\nDIFFUSION = 1\nADVECTION = 1\nVELOCITY = 1\nLEFT = robin\nRIGHT = free\nMATRIX_CELLS = 40\nMATRIX_DEPTH = 60      # m: deep enough to be infinite over this run\nMATRIX_FIRST = 1.0E-5  # m at the wall; 0 has it worked out\nMATRIX_POROSITY = 0.0018\nWETTED_SURFACE = 500   # m2 of wall per m3 of water\nTEND = 120\nTIME_UNIT = second\n\n<SPECIES>\nX  0.0  D=0  left=1.0  Dm=1.0E-3    # Dm: the effective diffusivity in the rock\n\n<REACTIONS>\n"
  },
  {
    "id": "u238chain",
    "group": "Dual porosity",
    "label": "U-238 chain in a fracture (SKB TR-19-06)",
    "about": "Six radionuclides decaying into one another while diffusing into the rock and sorbing there, along a real flow path. Decay is written on = inventory, because it removes sorbed atoms as readily as dissolved ones.",
    "reference": "SKB TR-19-06, Appendix B: Table B-2 (nuclide data) and the representative trajectory of Figure B-6 — travel time 235.2 a, F = 80 090 a/m, length 2 237 m, matrix porosity 0.0019, bulk density 2 700 kg/m³, penetration depth 4.5 m, Peclet number 10.",
    "text": "# The U-238 chain along a fracture in rock, with matrix diffusion.\n#\n# Everything here is per YEAR: half-lives, diffusivities in m2/a, the travel\n# time. TIME_UNIT = year tells the page so; it converts nothing.\n#\n# The flow path is the representative trajectory of SKB TR-19-06 Appendix B:\n# 2237 m travelled in 235.2 a, so v = 9.511 m/a, and a transport resistance\n# F = 80 090 a/m, which is the wall area per unit volume of water times the\n# travel time: aw = F/tw = 340.5 m2/m3.\n#\n# Rm is the rock's capacity for a nuclide, eps_m + rho*Kd, with eps_m = 0.0019\n# and rho = 2700 kg/m3. It is what holds the sorbing members of the chain back\n# by thousands of years.\n#\n# DECAY IS on = inventory. A rate law is per unit pore water, and a cubic metre\n# of rock holds only eps_m of water -- right for chemistry, wrong for decay,\n# which takes the sorbed atoms too. Written as on = water instead, the sorbing\n# nuclides would decay at eps_m/Rm of their real rate.\n\n<SETTINGS>\nMODE = transport\nCELLS = 20\nLENGTH = 2237          # m\nDIFFUSION = 1\nADVECTION = 1\nVELOCITY = 9.5110      # m/a: 2237 m in 235.2 a\nPOROSITY = 1\nPECLET = 10\nLEFT = robin\nRIGHT = free\nMATRIX_CELLS = 20\nMATRIX_DEPTH = 4.5     # m\nMATRIX_POROSITY = 0.0019\nWETTED_SURFACE = 340.5 # m2/m3 = F / tw = 80090 / 235.2\nTEND = 1.0E6           # a\nTIME_UNIT = year\n\n<SPECIES>\n#          start  De (m2/a)   Rm = eps + rho*Kd\nU238   0  Dm=2.7E-7  Rm=0.5419    # Kd 2.0E-4 m3/kg\nU234   0  Dm=2.7E-7  Rm=0.5419    # Kd 2.0E-4\nTh230  0  Dm=2.7E-7  Rm=143.1     # Kd 5.3E-2\nRa226  0  Dm=8.5E-7  Rm=1.2169    # Kd 4.5E-4\nPb210  0  Dm=8.5E-7  Rm=67.5      # Kd 2.5E-2\nPo210  0  Dm=2.7E-7  Rm=67.5      # Kd 2.5E-2\n\n<PARAMETERS>\n# A unit release of U-238 into the first cell: 1 Bq/a over its water volume.\nSRC  all  0\nSRC  0    0.0089405  fracture      # = 1 / (LENGTH/CELLS) / 1 m2\n\n<REACTIONS>\n=> U238, k = SRC\n\n# The chain. Half-lives in years; every one acts on the whole inventory.\nU238  => U234,  k = 1.5513E-10, on = inventory   # 4.468e9 a\nU234  => Th230, k = 2.8234E-6,  on = inventory   # 245 500 a\nTh230 => Ra226, k = 9.1946E-6,  on = inventory   # 75 386 a\nRa226 => Pb210, k = 4.3322E-4,  on = inventory   # 1 600 a\nPb210 => Po210, k = 3.1083E-2,  on = inventory   # 22.3 a\nPo210 => ,      k = 1.8289E+0,  on = inventory   # 0.379 a\n"
  }
];

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { RTM_EXAMPLES };
}
