# facsimile.html — tests

Five of them: `run.js` checks the numbers against the reference results,
`test-limits.js` checks that a long run stays bounded, `test-hdf5.py` checks
the HDF5 file the page writes with the real library, `test-ui.py` checks the
page in a real browser, and `test-worker.py` checks where the work is put.
None of them needs the network.

The page also offers seven solvers ported from DifferentialEquations.jl. They
are a package of their own, `resources/js/ode_julia/`, with its own tests under
`resources/tests/ode_julia/`; what is checked here is only that they are on the
menu and that one of them runs the model in the page.

## The engine

`run.js` drives the browser engine of facsimile.html (the model compiler in
`resources/js/facsimile-model.js` and the solvers in `facsimile-ode.js`)
under Node and compares it with the reference results kept in `ref/`.

```
node resources/tests/facsimile/run.js                 # Jacobian check, then case 13g
node resources/tests/facsimile/run.js 13g 16a 1       # chosen cases
node resources/tests/facsimile/run.js --all           # every preset (about half a minute)
node resources/tests/facsimile/run.js --norm rms --matrix sparse --jacobian numeric 13g
node resources/tests/facsimile/run.js --debug 3.8e8 13g   # Newton and error-test failures after t = 3.8e8 s
```

Options: `--solver` (`ndf` or `bdf`), `--rtol`, `--atol` (default 1e-30),
`--belowtol` (steps at the floor that may be accepted after failing the error
test), `--autoatol` (let the absolute tolerance follow the solution upwards),
`--norm max|rms`, `--maxorder 1..5`, `--hmax` (seconds), `--matrix
auto|sparse|dense`, `--jacobian analytic|numeric`, `--no-nonneg` (the projection is on by default), `--noscaling`,
`--minnewton 1|2`, `--quiet`.

## What is compared

* `ref/py_<case>.csv` — the Python port (`skbcanister.py`, SciPy BDF with
  the tolerances of `test_skbcanister.py`), subsampled from
  `Scenario_<case>_python.xlsx` at 28 times between 1e-3 h and 500 years.
* `ref/fac_13g_pcair003.csv` — the FACSIMILE output in `Transfer/out*COR13g.prn`
  (case 13g as run there: 3 % air, no argon), used by the preset `13g-fac`.

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
console.

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

The panel on the left is checked too: that the buttons at its foot do not move
when it is scrolled, that a heading folds its section away (measured as the
height of the section, since Chrome hides the contents of a closed `<details>`
with `content-visibility`, which leaves them an `offsetParent` and a stale
geometry), that the edge can be dragged and clamps, that the charts are
re-measured to the new width, and that the width and the folded sections come
back after a reload.

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
