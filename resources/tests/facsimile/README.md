# facsimile.html — tests

Six of them: `run.js` checks the numbers against the reference results,
`test-features.js` checks what the model language gained from the FACSIMILE
manuals, `test-limits.js` checks that a long run stays bounded, `test-hdf5.py`
checks the HDF5 file the page writes with the real library, `test-ui.py` checks
the page in a real browser, and `test-worker.py` checks where the work is put.
None of them needs the network.

The page also offers seven solvers ported from DifferentialEquations.jl. They
are a package of their own, `resources/js/ode_julia/`, with its own tests under
`resources/tests/ode_julia/`; what is checked here is only that they are on the
menu and that one of them runs the model in the page.

## The engine

`run.js` drives the browser engine of facsimile.html (the model compiler in
`resources/js/facsimile-model.js` and the solvers in `facsimile-solver.js`)
under Node and compares it with the reference results kept in `ref/`.

```
node resources/tests/facsimile/run.js                 # Jacobian check, then case 13g
node resources/tests/facsimile/run.js 13g 16a 1       # chosen cases
node resources/tests/facsimile/run.js --all           # every preset (about half a minute)
node resources/tests/facsimile/run.js --norm rms --matrix sparse --jacobian numeric 13g
node resources/tests/facsimile/run.js --debug 3.8e8 13g   # Newton and error-test failures after t = 3.8e8 s
```

Options: `--times <file>` (write the model's own output grid to CSV),
`--no-times` (do not build it), `--solver` (`ndf` or `bdf`), `--rtol`, `--atol` (default 1e-30),
`--belowtol` (steps at the floor that may be accepted after failing the error
test), `--autoatol` (let the absolute tolerance follow the solution upwards),
`--norm max|rms`, `--maxorder 1..5`, `--hmax` (seconds), `--matrix
auto|sparse|dense`, `--jacobian analytic|numeric`, `--no-nonneg` (the projection is on by default), `--noscaling`,
`--minnewton 1|2`, `--quiet`.

## What is compared

* `ref/py_<case>.csv` — the Python port (`skbcanister.py`, SciPy BDF with
  the tolerances of `test_skbcanister.py`), subsampled from
  `Scenario_<case>_python.xlsx` at 28 times between 1e-3 h and 500 years.
* `ref/fac_<case>.csv` — **SKB's own delivered FACSIMILE result** for the same
  case, 48 log-spaced rows of the study's result workbooks. There are 38 of
  them, one for nearly every preset. `scripts/gen-facsimile-ref.py` writes
  them from the delivery folders, which are not in this repository; run it
  with `--source` pointing at them, or `--list` to see the matching without
  writing anything.
* `ref/fac_13g_pcair003.csv` — the FACSIMILE output in `Transfer/out*COR13g.prn`
  (case 13g as run there: 3 % air, no argon), used by the preset `13g-fac`.

Both references are used where both exist, and `--ref python` or `--ref
facsimile` picks one. The Python port is what this engine was written against
and agrees with it to about 1e-6; the FACSIMILE result is the model's own
answer and is the one that settles a disagreement between them.

WHICH WORKBOOK IS WHICH CASE is worked out from the numbers rather than read
off the file name: the generator asks the page what each preset starts from
and requires the workbook's own first row to agree. The names invite a wrong
guess — `Scenario7crev1` for a preset called 7, `scenario16prime` for one
called 16p, two different `scenario18` files in two different folders — and
three files match nothing and are reported rather than forced. A second trap
is that the sheets carry blank separator columns, so a header has to be
mapped to its own column index; filtering the blanks out shifts every column
after the first gap and reads one species' numbers under another's name,
which is silent and plausible.

### What the FACSIMILE reference says

Against the delivered results the engine agrees on the quantities the study
reports to between 2e-4 and 6e-3 for most cases: pressure, total water,
nitrogen, ammonia and hydrogen. For case 13g the end of the 500-year run is

| quantity | FACSIMILE | this engine |
|---|---|---|
| water (g) | 65.955 | 65.933 |
| H2 (mol) | 29.069 | 29.071 |
| NH3 (mol) | 0.29914 | 0.29902 |
| N2 (mol) | 0.76402 | 0.76367 |
| pressure (atm) | 0.7531 | 0.7535 |

which also settles a question the page's own Help raises: the 500-year water
figure is 65.96 g, and the engine's 65.93 at its default tolerance is right
to four parts in ten thousand rather than merely self-consistent.

**Nitric acid is the exception, and it is a real difference.** Up to about
15 hours all three agree to under 1 %. After that FACSIMILE keeps HNO3 alive
for two more years while this engine and the Python port destroy it within
about a month: at 1200 h FACSIMILE has 1.7e-6 mol and both of the others have
about 3e-18. The amounts are tiny beside the 0.91 mol of nitrogen, so the
mass balance and every other species are unaffected, but HNO3 is one of the
aggressive species the study reports, and how long it persists is not a
detail. This engine follows the Python port here; whether the port or
FACSIMILE is right is a question about the chemistry, not about the solver,
and nothing in this repository answers it. HNO2 and H2O2 disagree the same
way in cases 13a, 13b, 14, 15 and 16.

The same comparison against the note's own **Table 2**, which prints the
amounts at 500 years for the seven zero-argon cases, separates the two halves
of this cleanly. Where corrosion consumes the water and the products are
hydrogen and ammonia, the engine reproduces the published numbers:

| case | H2 | N2 | NH3 |
|---|---|---|---|
| 16′ | 1.8e-6 | 2.2e-4 | 1.2e-4 |
| 16a | 1.1e-3 | 1.6e-3 | 1.5e-4 |
| 16b | 1.0e-3 | 4.6e-4 | 1.9e-4 |
| 13g | 1.0e-3 | 4.3e-4 | 5.2e-5 |

(relative difference from Table 2.) Where there is no corrosion — 16c and 16d
by construction, 11b because the humidity never reaches 60 % — the acids and
the peroxide are the main products rather than a trace, and the same
difference that is invisible above becomes the headline number:

| case | O2 | H2 | HNO3 | HNO2 | H2O2 | N2 |
|---|---|---|---|---|---|---|
| 16c | 0.76 | 0.60 | 0.27 | 0.97 | 0.36 | 0.14 |
| 16d | 0.67 | 0.76 | 0.32 | 0.97 | 0.47 | 0.07 |
| 11b | 0.13 | 0.39 | 0.16 | 1.00 | 0.80 | 0.006 |

The engine is low on every oxidised-nitrogen product and high on N2, which is
the same story as the HNO3 curve above seen at the end of the run instead of
in the middle. So the agreement on the corroding cases is not evidence that
the whole mechanism matches: it is evidence that hydrogen and ammonia match,
and those cases have little else left at 500 years.

Two smaller differences the matching turned up, both reported by
`gen-facsimile-ref.py --list` for every case:

* The delivered 1-atm PWR runs (12, 13a, 14–21) start from 0.6 % more O2 and
  N2 than the presets built from the report's Table 3-1, and 13d and 13e
  start at 70.5 °C where the page's low-temperature profile starts at 70.
* `scenario22_fixed.xlsx` starts with 0.1 g of water where the page's preset
  22 has 1 g, so it matches no preset and case 22 has no FACSIMILE reference.

For each quantity the report gives the largest relative difference over the
reference rows where the reference exceeds a floor, with linear interpolation
of this engine's solver steps to the reference times. The first table columns
are pressure, water, relative humidity and the amounts of O2, H2, HNO3, HNO2,
H2O2, N2, NH3 and water vapour.

Before the cases run, the analytic Jacobian is compared with finite
differences at the initial state and at a state with every species present;
`0 discrepancies` is the expected result for both.

## What to expect

Through the oxygen-consumption and gas-chemistry phase (the first 1e5 hours)
the engine agrees with the Python port to 0.1–0.2 % on every amount. In the
phase where the anoxic corrosion is throttled by the relative-humidity switch
the water curve follows the reference to within a few per cent and the two
agree, together with the FACSIMILE run, on the water left after 500 years
(64.9 g FACSIMILE, 65.8 g Python, 65.6 g here for 13g). Larger local
differences at single times in that phase are also seen between FACSIMILE and
the Python port, and reflect how sharply each integrator resolves the switch.

Runs take about a second each; the Python port needed 2–30 minutes per case
because it differenced its Jacobian.

## The page

`test-ui.py` drives facsimile.html in headless Chrome over the DevTools
protocol, reusing the driver the HDF5 Browser tests use. Start the server and
the browser as in ../rb/README.md, then

    python3 resources/tests/facsimile/test-ui.py

It resets the page, solves a short case, and then works the fourth chart --
"Your own selection" -- the way a reader does: ticking series one after
another, changing the time axis, toggling the log scale, unticking, clearing,
filtering the list, leaving the tab and coming back, and solving again. It
also checks the other three charts, the table, the Jacobian view and the
console. Where the model has a `<TIMES>` section, the table's row control
offers those times: the checks are that the option appears only then, that
choosing it changes the rows, that the times in the table are the ones the
model asked for and in order, and that the CSV button stops saying "all
steps" while it is selected -- a button that named one thing and wrote
another would be the kind of quiet wrongness nothing else here would catch.

The lower end of a log time axis is checked there too. Left to the data it
starts at the first stored point, a fraction of a second on this model, so
most of the width of every chart goes on the interval before anything has
happened; the *from* box sets it, and the checks are that the axis moves to
what is typed, that the points before it are dropped rather than hidden (so
that the height of the chart is decided by what is visible), that emptying the
box gives the data its say again, and that the box goes away on a linear axis.
That last one is read from the computed style, not from the attribute: an
author `display` beats the browser's own `[hidden] { display: none }`, which
is a trap this page has fallen into once already.

The model text's colouring is checked last, and from a fresh load. It is a
second copy of the text in a `<pre>` under the textarea, with the textarea's
own text made transparent over it, which is the only way to colour a text area
without giving up its undo, its selection and its caret. Everything that
decides where a character lands therefore has to be identical in the two
boxes, and that is what is measured: the computed font, size, line height,
letter spacing, padding, border and tab size, and then the two rectangles to
within half a pixel. A mismatch there is invisible in an empty file and
glaring in a full one. The rest is that the copy holds the same text, that
scrolling the box scrolls the copy with it, that typing repaints the copy at
once (it must be synchronous: the reader is watching the copy, not the text
they are typing), that a word is only coloured as a keyword where it means
something, and that the toggle reaches storage and comes back after a reload.
It runs last and leaves the page as it found it, because that state is
remembered between visits and would otherwise be read by the next run.

The panel on the left is checked too: that the buttons at its foot do not move
when it is scrolled, that a heading folds its section away (measured as the
height of the section, since Chrome hides the contents of a closed `<details>`
with `content-visibility`, which leaves them an `offsetParent` and a stale
geometry), that the edge can be dragged and clamps, that the charts are
re-measured to the new width, and that the width and the folded sections come
back after a reload.

Opening a model by dropping it on the page is checked with real drags, sent
through the browser's own drag machinery (`Input.dispatchDragEvent`) rather
than events made up in the page. What matters is how the page answers the
browser: a drag carrying a file has to be cancelled, or the browser will not
drop it, and a file dropped where the page does not take it is shown by the
browser in place of the page. That last part never happens over DevTools -- a
page with no drop handling at all stays put there too -- so the cancelling is
what is asserted, from a listener on the window. The checks are that the
overlay comes up for a file and not for text, that a file dropped on the
charts or on the editor itself replaces the model text and is compiled, that
text dragged into the editor still goes in where it is let go, that a file
that is not a model, two files at once and a file far larger than any model
are refused with a reason and leave the text alone, and that an overlay left
up by a drag the page never heard leave goes at the next mouse movement.
Open… is checked through the same reading. So is a file dropped during a run:
it is compiled once the run is over or stopped, and the HDF5 file of that run,
caught on its way to the disk, still holds the text the run solved rather than
the one that arrived meanwhile.

The settings are checked in both directions, because they are one thing seen
twice: a value typed into the panel has to appear on its line in the model
text, a value typed into the line has to appear in the panel, and choosing a
scenario has to write itself into the text and then be recognised there. Each
of those waits on the thing it asserts rather than on the status line, which
already says "Model compiled" from the compile before and so is no signal at
all.

The editor is exercised the same way, by typing a new output at the end of
the file one fragment at a time through the browser's own input pipeline: the
compiler objects to the half-written line, and the checks are that the caret
did not move, that nothing was selected, that the text typed next is still
there, and that the finished output can be solved for and plotted.

Every chart check reads back `<traces Plotly holds>:<traces Plotly has
drawn>`, and both halves have to agree. That is not pedantry: a graph div that
has been emptied by hand still reports its traces in `gd.data` and draws none
of them, which is the shape the one real UI bug so far took -- the custom
chart went blank from the second tick onwards, and an earlier version of this
test counted only `gd.data.length` and called it well.

Both bugs the test was written for fail it loudly if the fixes are backed out:
the chart one as `2:0` where `2:2` is wanted, the editor one as "what was typed
is still there: False".

## Where the work runs

    python3 resources/tests/facsimile/test-worker.py

A solve can happen in one of two places, and the page has to take the better
available and be honest when it cannot:

| | runs | |
|---|---|---|
| a worker | everything | and the page stays alive while it runs |
| the page itself | everything | but nothing else can happen meanwhile |

The second is why this test exists. A run on the main thread is a frozen tab:
no repaint, so the progress bar never moves, and no event loop, so Stop cannot
be clicked. For the built-in NDF that lasts a second and nobody notices; for the Julia
ports it lasts minutes and is indistinguishable from a crash, which is how it
was reported.

There was a third rung between these two while SciPy's solvers were offered:
the worker had to be a module worker, because Pyodide refuses to load in
anything else, and a browser that would not start one fell straight to the
bottom. A classic worker was added for it. SciPy is gone and so is the module
worker, which leaves one kind of worker that more browsers will start.

The fallback is forced by taking `Worker` away before the page's own scripts
run. The test checks that a worker is used when there is one, that what cannot
run without one is refused with a reason rather than attempted, and — the
point — that the page is still answering afterwards.

It also checks that the worker and the menu agree about which solvers exist. A
Worker does not inherit the page's cache-busting, so an entry module whose
import list moved on while its own URL did not is served from cache and the
page offers solvers the worker has never heard of. The page now asks the worker
what it can run as soon as it starts.

## What was removed, and why

`ode23s`, and SciPy's `BDF`, `Radau` and `LSODA` through Pyodide, were on the
page. The SciPy three were there as an independent second opinion — a port
checked only against reference results shares whatever its author
misunderstood with its own tests — and they were checked by a `test-scipy.py`
that is also gone. None of the four suited this class of problem:

* `ode23s` re-forms and re-factorises the Jacobian every step at a lower
  order, which costs hundreds of thousands of steps for a handful of years. It
  is also what "it froze and I could not stop it" first turned out to be: see
  the memory ceiling below.
* `LSODA` gave up with repeated convergence failures about two per cent in, at
  every tolerance from 1e-30 to 1e-9, and with its own differenced Jacobian
  exactly as with the analytic one -- so that was LSODA and not the handoff.
* `BDF` and `Radau` never finished a whole 500-year case. Both stopped where
  the step they wanted fell below the spacing between neighbouring times -- BDF
  at about twelve years, Radau at about four -- which is the corrosion switch,
  and which the built-in NDF crosses only by accepting a few steps at its smallest size
  that still fail the error test. Restarting a stalled solver from its last
  accepted state does not help: the rebuilt solver fails on its first step, so
  the obstacle is the state and not the history behind it.

The seven ported solvers do the second-opinion job instead, offline and
without the 22 MB of CPython, NumPy and SciPy that the first SciPy run
downloaded. What `test-ui.py` and `test-worker.py` still assert from all this
is that a solver giving up arrives as an answer and not as a hang: a message
saying how many steps it took and how far it got, the part it did integrate
left on the charts and in the table, and a footer that stops saying "Running…".

## What the model language gained

    node resources/tests/facsimile/test-features.js

Five features were missing against FACSIMILE's own documentation, and
`test-features.js` checks each of them against what the manuals say it means.

* **A reaction may name its net rate.** `RANOX%K : A = B`, or `rate = RANOX`
  in this page's own form, reports that reaction's net rate as a quantity of
  its own — forward less backward, or the absolute rate where one was given.
  It is FACSIMILE's Technical Reference 1.6, and it is what the 170 `FXn`
  parameters of the original canister model are. The check is that the value
  is the flux the derivative is built from, that it can be used in an output,
  and that emitting it leaves the Jacobian alone.
* **`deriv(X)` in `<OUTPUTS>`** is a species' time derivative. The original
  carried five dummy variables to report its apparent G-value for fixed
  nitrogen; that is now one line, and the check is that it equals what the
  solver integrates and that its sign turns over where the chemistry does.
* **Events have a direction and may stop the run.** `down`, `both` and `stop`
  beside the assignments. A decay crossing a threshold downwards is timed
  against the analytic answer, and the default — upward only — is checked by
  showing that the same fall does not fire it.
* **`<TIMES>`** asks for values at times of the model's own choosing, which is
  what a WHEN/WHENEVER list did. They are interpolated between accepted steps
  by the cubic through both ends and both derivatives, so every solver on the
  menu gives the same grid rather than each its own interpolant; against
  `exp(-kt)` at rtol 1e-10 the grid is right to about 6e-9 relative.
* **The functions FACSIMILE has and this did not**: `sin cos tan atan artan
  tanh amod sign stepf`. Their values are checked against the library and
  their derivatives against finite differences through the Jacobian. The one
  trap is at zero, where FACSIMILE's `stepf` is 1 and the `step` this page
  already had is 0; both are kept, and both are checked.

Two more were added after the first five, and they go together because both
are FACSIMILE features whose absence had been described as a limit of the
method rather than of the code.

* **Algebraic variables.** `<ALGEBRAIC>` makes the model a
  differential-algebraic system, `M y' = f` with a zero on the mass diagonal
  wherever a variable has a constraint instead of a derivative. Nothing about
  the formula changes: backward differentiation is what DASSL and IDA are
  built on, and the iteration matrix becomes `M - h*gamma*J`. What had to
  change is the plumbing, and the checks are the two problems everyone checks
  a new DAE code against. The circle of the FACSIMILE User Guide is solved
  from its own documented starting guess and followed to 6e-10 against the
  analytic answer, staying on its constraint to 3e-11. Robertson's problem is
  reproduced at t = 40 and t = 4e10 to the published figures.

  The one that took the longest to see is worth recording. Started from an
  inconsistent value the circle problem **stalls at t = 0** rather than
  failing: the first step moves the algebraic variable by 0.034 to satisfy the
  constraint, the error test measures that jump and rejects the step, and
  halving the step does not shrink the jump, because the constraint has to
  hold at the new point whatever the step is. The step size collapses to the
  denormal floor and 8000 steps later the clock reads 1e-319. Two other
  instances of the same mistake were found the same way: the initial-step
  heuristic read the constraint residual as a derivative, which through `J*y'`
  poisoned the differential rows as well, and the output grid interpolated
  between two states that each satisfy the constraint to give one that does
  not, reporting Robertson's three species summing to 1.0003. All three are
  fixed, the constraints are solved before the run rather than demanded of the
  author, and every grid point is put back on them.

* **Events at a list of values, and firing once.** `expression = v1 v2 v3`
  fires wherever the expression passes each value, and `once` makes an event
  fire one time only. Those two are the whole of FACSIMILE's WHEN against its
  WHENEVER. The checks run `sin(t)` past 0.5 over twenty seconds and count
  four firings without `once` and one with it.

  A limitation is checked as well as documented, because it is silent: a
  crossing is found from the sign at the two ends of a step, so a trigger
  moving faster than the solution can have an excursion missed entirely or a
  crossing located on an interpolant too coarse to place it. Against
  `sin(t) = 0.9` the second crossing comes out at 3.01 where it belongs at
  2.02, and capping the step fixes it.

Both are then exercised together on `resources/data/facsimile-langmuir.fac`,
a worked example that ships with the page: a gas consumed at a fixed rate
against a surface whose coverage is in equilibrium with it at every instant.
It uses an algebraic variable, a named rate, an output grid, an event value
list fired once each, and an event that stops the run, and every one of those
has an exact answer to check against — the gas is `exp(-kt)`, the coverage
follows from the isotherm, and the five events fire at `ln(2)/k` and its
relatives. It is also the check that the page draws a model that is not the
canister one at all: the three fixed charts report quantities that model does
not have, and they now say so rather than throwing inside the redraw.

The last group of checks is on the model the page ships: that the two
corrosion fluxes it reports are now multiples of the reactions' own named
rates rather than a second copy of the rate laws, and that they still equal
what those rate laws gave.

## What keeps a run bounded

    node resources/tests/facsimile/test-limits.js

`test-limits.js` covers the ceiling on the stored points. Every accepted step
used to be kept, which is fine at a few thousand of them and fatal at a few
hundred thousand -- which this model takes as soon as the step size is capped,
and which ode23s took unprompted before it was removed: the memory climbed at
about 3 MB a second until the tab died, and that is what "it froze and I could
not stop it" turned out to be. The store is now thinned as it grows, and the
test checks that the ceiling holds, that it is not thinned further than it has
to be, that the start and the end of the run survive it, and that a run out of
its step budget stops with the right reason and hands back what it had.

## The HDF5 file

`resources/js/kvot-hdf5-write.js` writes HDF5 by hand rather than pulling in
h5wasm, which is 4.7 MB of WebAssembly to fetch in order to *write* a few
hundred kilobytes. So the question that matters is whether libhdf5 agrees that
what it produces is an HDF5 file.

    python3 resources/tests/facsimile/test-hdf5.py         # case 13g
    python3 resources/tests/facsimile/test-hdf5.py 1 16a

It solves a case (`node run.js --h5 <path>` writes the same file the page hands
over), opens it with h5py, and checks the structure, the attributes and the
numbers -- including two things the file has to be internally consistent about:
`/Results/TIMH` is `/time` exactly, and `/Results/O2MOL` is `/Species/O2` times
the free volume in `/Constants`.

`test-ui.py` covers the other end of it: it clicks *View in HDF5 Browser*, waits
for the status line to say the file is open, then attaches to the tab that
opened and asks h5wasm -- the real library again, in the browser -- what it
holds. That the tree shows `/Species` and that `f.get('/Species/H2').value` has
values in it is the writer, the handoff and the browser all answering at once.

## Solver notes that came out of these tests

* The Newton system is solved in variables scaled by `max(|y|, atol/rtol)`.
  Without it the pivoting of the LU (sparse or dense) is decided by the
  largest coefficients and the corrections for the trace species — which span
  forty orders of magnitude — are wrong; Newton then diverged on N, NH and NH2.
* At least two Newton iterations are taken per step. The published method
  accepts after one on the strength of an earlier convergence rate; on the RH switch a
  step-old Jacobian damps the first correction by 1e6 while the residual is far
  from zero, and the run accepted states that over-consumed water.
* The non-negativity projection is on by default. A trace species that a step
  has left slightly negative is read as zero in the rate laws, and the exact
  derivative of that clamp is zero on the negative side; a Jacobian formed there
  let Newton jump into the positive region, where the consumption term is
  enormous, and diverge. Keeping the derivative at one instead made Newton
  converge to wrong states. Projecting after each step keeps the Jacobian on
  the physical side, and every case then runs.
* A step at the smallest allowed size that still fails the error test is
  accepted and counted (`nbelowtol`) up to five times in a row. After an
  event the restart is from an interpolated state in which an ion with a
  lifetime of femtoseconds is off its steady state by more than the
  tolerance; the implicit step mends that, no step size does.

  This is a **departure from the published method**, which is worth stating
  plainly because the rest of this solver is a faithful implementation of it.
  Reaching the same point, a variable-order multistep code raises a
  tolerance-not-met error and returns the partial solution; it never accepts a
  step that failed. Measured over the 39 presets, the escape is used three
  times in total, and with it disabled three presets stop early. There were
  two acceptance sites
  and only one of them was bounded — the other could have accepted any number
  of failing steps and still reported success. It has never fired on these
  presets, which is why it needed the bound rather than the benefit of the
  doubt.
