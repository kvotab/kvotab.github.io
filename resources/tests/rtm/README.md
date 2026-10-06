# Tests for rtm.html

Three of them. `test-model.js` is the mathematics and needs only Node;
`test-hdf5.py` is the file the page writes and needs Node and `h5py`;
`test-ui.py` is the page and needs the server and browser of `../rb/README.md`.

    node resources/tests/rtm/test-model.js [--verbose]
    python3 resources/tests/rtm/test-hdf5.py
    python3 resources/tests/rtm/test-ui.py

All three exit 0 when every check passes. `test-ui.py` expects the server on
8765 and Chrome on 9222; when another session has those, start yours on other
ports and name them, `RTM_HTTP_PORT=8811 RTM_CDP_PORT=9311 python3 …`.

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
holds its far-field block to, from which this copy was taken. Those cases say
`MATRIX_GRID = reference`, FARFCOMP's own layers, which are no longer the
page's default. The layer
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

**A far-field path as Kompartment has it.** The page's defaults for a rock
matrix are Kompartment's for a new far-field path: twelve layers matched to
diffusion into the rock, the first worked out from the path, and the rock going
on past the release point (`RIGHT = semi-infinite`, with the cells past it
counted as Kompartment counts them). Checked without Kompartment: the defaults
themselves; `TRAVEL_TIME`, `TRANSPORT_RESISTANCE`, `Kd=` and `Kdf=` read back
as the velocity, the wetted surface and the capacities they stand for, and the
refusals where two of them disagree; the extra cells inheriting what a line
reaching the last cell gives, and not a source of the first; the flux through
each end against the column's own balance — what the cells gain is what crosses
the left end less what crosses the right, to 10⁻¹⁴, for six pairs of ends and a
rock matrix; and the model's transfer function, (sI − J)⁻¹ at real s with the
release read off it, against FARF31's exact one from TR 90-01: 2.4 % in ln T
where T is above e⁻⁵, against 9 % for the old layers and a Danckwerts outlet;
four times closer on 40 cells, which is the second order of the fracture's
central scheme; and twelve matched layers no worse than twenty. Then, last
because Kompartment's module is an ES module the test has to wait for, section
9 reads `kompartment/src/domain/farfield.js` itself, on five paths among which
its own far-field example: the matched layers bit for bit, the count of cells
past the release point over twenty pairs of N and Pe, every entry of its
transport matrix and of its chain's ingrowth seen through the capacities
(A = C·J·C⁻¹, C = R in the fracture and a_w·R_m·d_j in layer j) to 5×10⁻¹⁶, and
its release weights.

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

**Sources that follow the clock: a release history.** `t` in a rate law is the
time, checked against the closed form of a loss that fades, k·exp(−t/τ)·[A]; a
Jacobian that reads it is not called constant; a parameter may not be called
`t`. A `<TABLE>` is read in a rate law at the clock -- `name(t)`, with a column
by name or number when it has several, and `loglog` for a power law between
rows -- and never at a concentration. The run is started again at every corner
of such a table (`model.breaks`, handed to the driver), and the check that this
matters is a pulse of ten years in five thousand: with the restarts it is
integrated to the table's own integral, without them the NDF has grown its
steps over the quiet stretch before it and steps clean over it -- the store
comes out exactly zero. The corners follow the argument when it is a line in
`t`, and there are none for one that is not. End to end, a release history
that rises, holds and falls over twenty thousand years, through Kompartment's
default far-field path, is put beside FARF31.html's convolution of the same
history with the path's exact response: for Ra-226 the peak is 30 %, 7.3 % and
1.8 % high on 20, 40 and 80 cells, the second order of the fracture's scheme.

**What skbrtm's databases needed.** Reading skbrtm-main's examples called for
six things the format lacked, and each is checked against a number worked out
independently rather than against the code's own output:

* *The syntax.* `Fe(OH)3` as a name; `[A]**(2/3)` and `10**-3` in a law, and an
  exponent that is a constant of the line or a parameter varying by cell, each
  with a Jacobian that agrees with a difference; `kr = 1.33*10**12` and
  `kb = kf/4` as constants; `c = [B]` as an alias, whose extra Jacobian entry,
  `-k[A]`, is read out of the pattern; arithmetic in settings and species
  lines; and skbrtm's biotite rate law, passed through verbatim, against its
  value by hand.
* *The grids.* A power-law grid's faces at `L(i/N)^3` to 1e-20, `FACES` as a list
  and as an expression in `i`, `GRID_RATIO`, and `SURFACE_LAYER`'s first cell; a
  closed power-law column conserving its content to 4e-15; and skbrtm's own b1
  benchmark -- Crank's slab -- on it: 1.4e-4 at ten days with 50 cells, and
  exactly four times closer with 100, which is second order on a grid this
  uneven.
* *A surface.* `w`, `xl` and `xr` are the cell's width and faces; a site
  density written per m² over `w` is the same amount per m² on three grids; and
  the reason for `SURFACE_LAYER`: a second-order surface reaction whose product
  per m² moves 69 % between 10, 20 and 40 cells without it, and 2.5e-6 % with
  it.
* *Tables.* Interpolated at the cell centres to hand-worked values, held flat
  beyond the ends, the same through `interp(t, x)`, and a `log` table a quarter
  of the way along giving `0.1^(1/4)`; refused when x does not increase, a log
  table holds a zero, or a rate law reads one.
* *Held cells.* A cell held with `fixed` in `<INITIAL>` stays at 1 while feeding
  its neighbours; a species held in cells 5-9 stays at zero there while the
  reaction makes it everywhere else and the reactant still decays under it.
* *The importer.* A small skbrtm case written into the test -- script order and
  time span, decimal commas, bounds, a name in two cases, `<=` and a bare `=`,
  skbrtm's `(kr/kh)`, `boundary_values`, `units:` with a colon, a lone `cell_id`,
  a species constant in one cell, a value per cell width -- opens, compiles and
  runs, with each of skbrtm's four misreadings named. When skbrtm-main is in
  `~/Downloads`, its five cases are opened and run as well.

**The examples the page offers.** Every one of them is compiled and run here,
so the picker cannot hand a reader something broken, and the two with a
published answer are held to it: Robertson (1966) at *t* = 0.4 against
0.9851721, 3.3864e-5, 0.0147939, with *A* + *B* + *C* never leaving 1 by more
than 8e-15; and the matrix-diffusion example against the `erfc` its own comment
claims. The U-238 chain is checked on the thing that makes it a chain — deep in
the rock, where nothing flows, each short-lived daughter sits at its parent's
activity, λ·R_m·C, to within 0.2 %, across capacities from R_m = 1.2 to 143,
which puts the concentrations themselves a hundred times apart. In the fracture
it does not, because flow carries a nuclide away before its daughter catches up.

Until 2026-10-06 this check compared concentrations, λ_parent·C_parent with
λ_daughter·C_daughter, and passed to 0.06 % — because `on = inventory` made a
daughter of the parent's *concentration* times the daughter's own capacity, so
a daughter that sorbs harder than its parent was born with more atoms than the
parent lost (a stable daughter with R_m 100 gained 200 times what a parent with
R_m 0.5 lost). Comparing the chain's ingrowth with Kompartment's, entry for
entry, is what showed it. A daughter is now born of the parent's whole
inventory and takes up its own share, as in Kompartment and FARF31, and a
closed rock cell keeps its atoms to 10⁻¹⁶.

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

**Kompartment's solvers.** The derivative works out only the rates and the
Jacobian only their gradients, so the Jacobian is checked against differences
of the derivative once more. Which models say their Jacobian never moves (a
tracer column and the decay chain do, Robertson and the built-in model do not),
and that Rosenbrock 2-3 then forms it once; Rosenbrock 2-3, Dormand-Prince and
Auto against the NDF on the tracer column, Auto handing that to the NDF and
leaving A → B → C explicit; the other new ports on A → B → C against its
closed solution; and the first step and norm control reaching the NDF.

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

Four models, for the shapes the tree can take: a batch, which is one
cell and so has `/Species` and no `/Cells`; a column, where every cell is a
group of series and `/Grid` says where each of them is; and a dual-porosity
column with more cells than one file should hold datasets for, which is the
case where the rock is deliberately left out and `matrix_written` says so (a
text of its own, forty layers behind a hundred cells: the examples no longer
have that many). The far-field example, read at its right-hand end, has
`/Ends` with both ends and every species, `/Species` holding the end the page
showed, a unit release in at the left and all of a tracer out at the right in
the end, and its cells past the release point in `/Cells` and `/Grid`, past
`LENGTH` and saying so.

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
tab says so, that the Example picker offers all 13 in their groups and loading one brings
its text, its description and a run; that a model in years labels its axis,
its panel and its boxes in years rather than seconds; that the Run button does
not move when the status line below it changes size, which it used to do by
127 px, under the pointer as it was clicked;
that a dual-porosity model compiles with the panel saying how deep and what
enters, that the layer picker appears and the time chart follows it, that the
profile can be drawn into the rock with the fracture at depth zero and falls
inward, and that the gradient draws a rock layer along the fracture —
that the far-field example's panel says its layers are matched, how thick the
first came out and why, how many cells stand past its right-hand end and the
travel time the flow makes, that it runs, that choosing *flux through the right
end* draws the release with a unit release of a tracer all coming out in the
end and no layer to pick, and that a cell again brings the layers back —
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
being typed in — the same characters, the same metrics, every one of the 13
examples through the tokeniser unchanged, since a span too many or an escape
too few puts the caret over the wrong letter — and that turning it off puts
the copy away and is remembered; that the page can build the HDF5 file it
offers and says what it wrote;
that a model file dropped on the page outlines the page while it is held
there, loads, switches to the Model tab, is described in the panel -- power-law
grid, table, held cells -- is coloured without a character changed, and runs,
and that skbrtm's files dropped together, a stray `.md` among them, open as one
model with what skbrtm reads differently written at the top;
that a model using a parameter, an `R=` and an equilibrium at once compiles with
all three reported in the panel, runs, verifies, starts its chart from the
speciated state rather than what was typed, and draws a profile whose mean is
`t/R` times the mean of `G·DOSE` — the parameter, the retardation and the two
closed boundaries all in one number.

That last check was first written expecting the profile to be the shape of the
source. It is not: √(D·t/R) is 2×10⁻⁴ m against a column of 10⁻⁴ m, so by 100 s
the species is very nearly mixed and only the mean is pinned down. Writing it
down wrong is how the check ended up testing something true.

**The (i) beside each setting.** The settings, the two section headings and
the five tab toolbars each have an (i) that opens a panel on the right
(`resources/js/kvot-info.js`, the topics in `rtm-ui.js`), in place of the hover
tooltips they had. The test asks `KvotInfo.audit()` for a slot without a topic
or a "Read more in Help" whose heading is missing, counts an (i) in every one
of the 27 slots, and checks that no `title` is left on the panel or a toolbar.
Then the behaviour: an (i) opens the panel under its own title, between the
header and the footer; the ×, the same (i) and an Escape key press each close
it, the last giving the focus back; the (i) on a section heading leaves the
section open; a topic with choices marks the chosen one and follows the
setting while it is open; its Help link lands on its heading; and the (i)s of
the panel line up at its right-hand edge. A section heading's (i) is in a slot
before its `<details>`, not in the summary, since Chrome reports any control
inside a `<summary>` (`An interactive element was found within a <summary>
element`): the test finds no slot (`audit().inSummary`) and no other control
inside one, and each heading's (i) centred on its line, at its end.

**The full window.** The button at the right end of the tab bar takes away the
site's header, menu and footer, as on smui.html and dose_coefficients.html. The
test presses it with the mouse, so a button covered by something else fails.
It checks that the page then fills the window, that the kvot mark at the left
of the bar leads home, and that the theme switch beside the button works as the
footer's does. The tabs work as before, with the two buttons outside the
tablist. An (i) panel runs from the top of the window to the bottom; before the
fix in `kvot-info.js` it took its height from the hidden header and footer and
had none. A reload is in the full window before `rtm-ui.js` runs. The test
records the page as the parser inserts that script's element: the scripts are
classic, so by readyState `interactive` it would already have run, and only the
page's head can have set the full window. At phone width the tabs scroll
between the mark and the buttons, in either mode, so the last of them can be
reached. The line under the tabs is the bar's background, not a border, because
the scrolling row would clip a tab reaching over a border. So the test also
checks that the open tab reaches the bar's foot in its pane's colour.

The choice is kept in the browser (`kvot.rtm.full`), and the test profile keeps
it from run to run. rtm.html's head reads it before anything else, so the test
clears it before the first load, from `rtm.css`, a file of the same origin that
runs no script. It clears it again after its checks, so an interrupted run
cannot leave the next one without the site's header.
