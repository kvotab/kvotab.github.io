# Tests for rtm.html

Three of them. `test-model.js` is the mathematics and needs only Node;
`test-hdf5.py` is the file the page writes and needs Node and `h5py`;
`test-ui.py` is the page and needs the server and browser of `../rb/README.md`.

    node resources/tests/rtm/test-model.js [--verbose]
    python3 resources/tests/rtm/test-hdf5.py
    python3 resources/tests/rtm/test-ui.py

All three exit 0 when every check passes.

## What test-model.js checks, and why those things

A reactive-transport code can be wrong in a way that still looks like
chemistry — the curves bend the right way and settle somewhere plausible — so
nothing here is judged by eye or against a stored result. Every check is
against something independent:

**Chemistry.** A → B → C against the closed solution; 2A → B against the
second-order form, which is the one that catches a stoichiometric coefficient
not being read as an order; a Michaelis–Menten law read straight off the rhs;
a source and a sink reaching source/sink; a reversible pair settling at
kf/kb while conserving A + B; and a `fixed` species driving a rate without
being consumed.

**The functions.** Every one the Help lists, each given an argument whose
answer is only right if the function is the one it claims to be (`log` is the
natural one, `ramp` is zero below zero, `sign` is −1 below), and each checked
against a central difference as well — a function is not much use in a rate law
if it cannot be differentiated. Then the three that are refused there, each for
its own reason, and the same three working in `<PARAMETERS>`, which is where
they are allowed.

**The two ends of the column.** The third-type (`robin`/`cauchy`) inlet and the
`free` outlet are Danckwerts' pair, and together they make the column a closed
account: what the flow brings in, less what it takes out, is all that changes
the mass. That is an identity, so it is checked as one — it holds to 6e-16,
while a `dirichlet` inlet is 6.7 % out, because it adds a diffusive flux on top
of what the water carries. Then the profile against van Genuchten and Alves'
flux-type closed solution, at two grids, since the error has to fall by four per
doubling or it is the formulation that is wrong rather than the resolution; and
the same comparison for a `dirichlet` inlet, which is solving a different
problem and must not come out looking like this one.

That solution needs an `erfc` the rest of this file does not. Its third term
multiplies `erfc` by `exp(v·x/D)`, which reaches e⁵⁰ at the far end of the test
column, and Abramowitz & Stegun 7.1.26 — used everywhere else here — carries an
*absolute* error bound of 1.5e-7, which that factor turns into 1e14. The block
uses the Numerical Recipes form instead, whose bound is fractional.

**Transport.** Diffusion against `erfc`, and not at one grid: the error has to
fall by four each time the cells are doubled, which is a far stronger statement
than any single number being close. Advection against Ogata–Banks, compared at
`D + v·Δx/2` because upwind differencing adds exactly that much numerical
dispersion. Mass in a closed box, on both the linear and the log grid, to
within 1e-12. A closed box relaxing flat to the mean. And a species with no
diffusion coefficient staying exactly where it was put.

**The Jacobian.** Against a central difference, on the built-in model in both
modes and in two states. Central rather than forward for a specific reason: a
rate quadratic in a species — and the radiolysis set is full of them — has a
true derivative of zero where that species is zero, and a forward difference
returns `k·h` there. That is an error in the question, not in the Jacobian, and
an earlier version of the check reported hundreds of them.

**Dual porosity: a rock matrix beside the fracture.** Two references that know
nothing of each other. First, SKB's own implementation of the formulation in
TR-19-06 (FARFCOMP), whose layer thicknesses, rates and release curves were
dumped once into `farf-fixture.json` — the same dump the `kompartment` tool
holds its far-field block to, from which this copy was taken. The layer
thicknesses come out bit for bit (the FARFCOMP root-find is reproduced step for
step), every rate — advection, dispersion, wall exchange, layer to layer — to
one part in 10¹⁴ in five cases, twenty layers from 4×10⁻⁸ m among them, and two
release curves to 2×10⁻⁹ and 2×10⁻¹⁰ against a bar of 10⁻⁷ at rtol 10⁻⁹. Second,
Neretnieks' closed solution for a step into a fracture beside a semi-infinite
matrix, which the breakthrough follows and converges on at the upwind scheme's
first order as the fracture is refined. Then a closed dual-porosity box
conserving mass to 10⁻¹⁴ and settling to exactly the capacity share between
water and rock; a first-order loss in the rock running at ε·k/R_m on the water
and at k on the inventory; and the refusals and warnings.

Three things the block taught, kept as comments:

* The Neretnieks convergence levelled off at 10⁻² whatever the fracture did,
  because the *matrix* grid was the floor: 24 layers from 10⁻⁴ m. With 80 from
  10⁻⁶ m the fracture's own first order shows through (ratios 1.87, 1.83,
  1.71). A convergence test has to know which grid it is refining.
* A `<PARAMETERS>` line naming a fracture cell also applied to the rock behind
  it, so a unit source into the water also fed every layer of rock — and a
  unit release delivered 5.5, which is exactly 1 + a_w·ε_m·d_max. The `fracture`
  and `matrix` words on those lines exist because of it.
* Decay written as a rate on the water is wrong by more than half in a sorbing
  matrix (0.717 against 0.116), because it should remove the same share of the
  sorbed mass too. `on = inventory` is the difference, and the "sorbing" release
  case is what proves it: to 2×10⁻¹⁰ one way, 0.6 out the other.

**The examples the page offers.** Every one of them is compiled and run here,
so the picker cannot hand a reader something broken, and the two with a
published answer are held to it: Robertson (1966) at *t* = 0.4 against
0.9851721, 3.3864e-5, 0.0147939, with *A* + *B* + *C* never leaving 1 by more
than 8e-15; and the matrix-diffusion example against the `erfc` its own comment
claims. The U-238 chain is checked on the thing that makes it a chain — deep in
the rock, where nothing flows, each short-lived daughter sits at
λ_parent/λ_daughter of its parent, to within 0.06 %, across capacities from
R_m = 0.54 to 143. In the fracture it does not, because flow carries a nuclide
away before its daughter catches up, and radium runs 2.4 times its equilibrium
share there.

That last check was first written the other way round — that decay written
`on = water` would leave *more* Th-230 in the rock, since its own removal is
throttled by ε/R_m. It leaves 3e6 times *less*, because the same throttle is on
its production from U-234, and the source dominates. The secular-equilibrium
form says something true about the chain instead of something plausible about
one term of it.

**The time unit.** `TIME_UNIT` converts nothing, so the check is that two models
differing only in the word give the same numbers, that every spelling resolves
(`s`, `min`, `h`, `d`, `a`, `yr`, `YEARS`), and that one it does not know is
refused.

**The pattern the Jacobian tab draws.** The whole pattern cannot be posted to
the page for a long column, so the worker folds it into three blocks — a cell
against itself and against each of its two neighbours. `test-model.js` checks
that those three put the matrix back together exactly (20×363 + 19×27 + 19×27 =
8286, the model's own `nnz`) and that nothing reaches past one neighbour, so the
picture cannot be silently incomplete. `test-ui.py` then counts painted pixels
on the canvas: an earlier version filled each cell's block solid, which made a
batch model a single square and told the reader nothing, and a filled block is
exactly what a pixel count catches.

Read the counts it prints with one thing in mind. An entry far below the
largest in its column cannot be measured by differencing at all: the change it
makes to the row is lost under the change the big ones make. Those are counted
as *below the noise floor* rather than as failures, and the floor is derived —
roughly `eps·|f_r|/h` — rather than guessed at. Guessing it is what let an
earlier version call an exact zero a disagreement.

**Per-cell parameters.** A dose profile `1.0·exp(-x/3e-5)` against the analytic
profile it is meant to be, in every cell, with the Jacobian still exact; a later
line overriding an earlier one; and a name that is neither parameter nor species
still refused.

**The mass matrix.** `R=2.5` against `exp(-kt/R)`, which is the statement that R
divides the reactions and not just the transport; `R=4` against `erfc` at `D/R`,
which is the statement that it divides the transport too; a per-cell `R` taken
from a parameter; and `R=0` refused rather than quietly turned into an algebraic
equation.

**Equilibrium.** Water autoprotolysis from a badly wrong start, checked on three
counts at once — the product reaches `Kw`, the two come out equal, and the charge
difference is the one it began with — because a speciation routine that hits `K`
by quietly losing mass is the likely way for this to be wrong. Then a carbonate
system of three coupled equilibria, where no hand-written start is right, with
all three `K`, the total carbon and the charge all checked. Then `kf` given as
well, so the pair is integrated: the product has to stay at `K` while the rest
of the chemistry carries on unchanged. Then a transport model, to catch a
speciation that only ever ran in cell 0.

What the conserved totals are is worked out from the stoichiometry alone — the
left null space of the equilibrium matrix — so the check that the basis comes
out as expected is a check on that derivation, not on a table of elements the
page does not have.

**The model text.** Nine things that must be refused with a message that says
what is wrong, and chemical names (`e-`, `H+`, `C2O4-2`, `UO2+2`) surviving the
parser, since those are what a chemist writes.

## A limitation the browser test found

The first version of the speciation put every species into the Newton
iteration, including ones no equilibrium mentions. That is fine until such a
species starts at zero — `ln 0` — and the matrix comes out singular. The model
tests all happened to speciate systems where everything took part; the browser
test, which put a product starting at zero next to a water equilibrium, did
not. Speciation is now restricted to the species the equilibria touch, and
`test-model.js` checks that a bystander at zero is left at zero.

## Two mistakes this file made, kept as comments

Both were the test being wrong about a correct answer, which is the failure
mode worth remembering:

* it read `y[1]` as B in a model whose species are declared `W, A, B`, and got
  A — which was exactly `exp(-5.5)`, the right answer to a question it was not
  asking;
* it expected the half-height of an advecting front at `v·t`. At this Péclet
  number the Ogata–Banks solution is 0.586 there, not 0.5. It now compares
  against the analytic half-height, which the model matches to a fiftieth of a
  cell.

## What test-hdf5.py checks

`resources/js/kvot-hdf5-write.js` writes HDF5 by hand rather than through a
library, so the question is whether libhdf5 agrees that the result is a file.
`write-h5.js` runs a model through the page's own worker handler and hands the
reply to `rtm-hdf5.js`, which is exactly what rtm.html sends the HDF5 Browser;
`test-hdf5.py` opens the result with h5py.

Three models, for the three shapes the tree can take: a batch, which is one
cell and so has `/Species` and no `/Cells`; a column, where every cell is a
group of series and `/Grid` says where each of them is; and a dual-porosity
column with more cells than one file should hold datasets for, which is the
case where the rock is deliberately left out and `matrix_written` says so.

The numbers are checked, not only the structure: A → B → C ends with the A
spent and nearly all of it in C, and the dose-profile column ends with more in
its first cell than in its last, which is what catches a cell group holding
some other cell's series.

Every series is one-dimensional on purpose. A field of one matrix per species
would be a tidier file and unreadable in the browser it is written for: a
2-D dataset there is a set of realisations, and one that is not probabilistic
is drawn against a clock as long as its first column alone.

## What test-ui.py checks

The wiring rather than the mathematics: that the text compiles through the
worker, that a transport run reaches both chart tabs, that ticking a species
draws it and the chip removes it again, that *Check Jacobian* answers and finds
nothing wrong, that switching to batch recompiles to one cell and the profile
tab says so, that the Example picker offers all 11 in their groups and loading one brings
its text, its description and a run; that a model in years labels its axis,
its panel and its boxes in years rather than seconds; that the Run button does
not move when the status line below it changes size, which it used to do by
127 px, under the pointer as it was clicked;
that a dual-porosity model compiles with the panel saying how deep and what
enters, that the layer picker appears and the time chart follows it, that the
profile can be drawn into the rock with the fracture at depth zero and falls
inward, and that the gradient draws a rock layer along the fracture —
that the boundary aliases reach the panel as the names they mean and that a
third-type inlet leaves its first cell below the inlet concentration, that a
`robin` face with no flow into it and a `free` face with nothing to carry
anything out are both warned about rather than silently behaving as `neumann`,
that a model naming an undeclared species is refused by name,
that the *Gradient* tab draws a heatmap with a row per cell and time along x
with distance running down y, starting at the *from* time rather than the
solver's first femtosecond, that *log concentration* puts the logarithm into the
data and says so on the colour bar, that smoothing is off unless asked for, that
a batch says there is no distance to plot against —
that the profile's *Times* field draws the times it is given and no others —
with units, as bare seconds, back to the automatic spread when emptied, and
reporting a token it could not read or a time past the end of the run rather
than dropping it silently — that a model typed from scratch runs and puts the
right number on the chart, and
that the syntax colouring lays a second copy of the text exactly over the box
being typed in — the same characters, the same metrics, every one of the 11
examples through the tokeniser unchanged, since a span too many or an escape
too few puts the caret over the wrong letter — and that turning it off puts
the copy away and is remembered; that the page can build the HDF5 file it
offers and says what it wrote;
that a model using a parameter, an `R=` and an equilibrium at once compiles with
all three reported in the panel, runs, verifies, starts its chart from the
speciated state rather than what was typed, and draws a profile whose mean is
`t/R` times the mean of `G·DOSE` — the parameter, the retardation and the two
closed boundaries all in one number.

That last check was first written expecting the profile to be the shape of the
source. It is not: √(D·t/R) is 2×10⁻⁴ m against a column of 10⁻⁴ m, so by 100 s
the species is very nearly mixed and only the mean is pinned down. Writing it
down wrong is how the check ended up testing something true.
