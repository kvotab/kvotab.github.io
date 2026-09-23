# ode_core

The stiff-solver core shared by `facsimile.html`, `rtm.html` and Kompartment:
the variable-order NDF/BDF integrator (orders 1–5, Shampine and Reichelt's
numerical differentiation formulas, with the BDFs as the case κ = 0), the
linear algebra behind its iteration matrix, and event location. It runs in a
page, in a worker and in Node, with no dependencies.

```js
import { ndf } from './ode_core/index.js';

const f = (t, y, out) => { out[0] = -0.04 * y[0] + 1e4 * y[1] * y[2]; /* … */ return out; };
const res = ndf(f, [0, 1, 10, 100], Float64Array.of(1, 0, 0), {
  rtol: 1e-6, abstol: 1e-10,
  jacobian: { pattern, evaluate: (t, y) => values },   // or leave it out: differenced
});

res.t, res.y;     // one row per time asked for in tspan
res.end;          // {t, y}: where the run stopped
res.stopped;      // the event it stopped at, or null
res.stats;        // steps, failures, factorisations, which LU, its fill
```

`f(t, y, out)` fills `out` and returns it, or returns an array of its own;
the return value is what is read.

## Where it lives

The ES modules here are the source of truth. Two things are made from them by
`node scripts/build-solvers.mjs`:

- `../ode-core.js`, a single file for a plain `<script>` tag and a classic
  worker, which puts the same names on `OdeCore`. `facsimile.html`,
  `rtm.html` and `rdc.html` load it before `facsimile-solver.js`, which is
  those pages' side of it: the integrator in their calling convention and with
  their settings, and the model driver.
- `kompartment/src/ode/{linalg,refactor,sparse,events,ndf}.js`, the same
  bytes, since Kompartment is self-contained and cannot reach up into
  `resources/js/`. Kompartment's `variable-order.js` is its side of it.

`node scripts/build-solvers.mjs --check` fails when either is not what the
modules build to, which is what `resources/tests/ode_julia/test-build.mjs`
runs. Edit the modules, then run the script. The core's own checks are
`resources/tests/ode_core/test-core.mjs`.

| module | what it holds |
|---|---|
| `linalg.js` | the dense LU with partial pivoting, which also forms Mass − a·J from a pattern |
| `refactor.js` | the sparse LU that keeps its pivots from one factorisation to the next |
| `sparse.js` | CSC, the Gilbert-Peierls LU, reverse Cuthill-McKee, column colouring, differenced Jacobians, and `iterationMatrix`: which LU, decided by measured fill |
| `events.js` | the earliest zero-crossing in a step, by safeguarded regula falsi on the interpolant |
| `ndf.js` | the integrator |

The ported DifferentialEquations.jl solvers are a package of their own,
`../ode_julia/`, and keep their own linear algebra: column-major storage, a
complex LU for Radau's stages, and a sparse LU written against its own
Jacobian cache. It was not merged with this one. What the two have in common
is small next to what the merge would have had to change in both.

## The integrator's options

| | default | |
|---|---|---|
| `rtol`, `abstol` | `1e-3`, `1e-6` | `abstol` per state or one number |
| `autoAbstol` | off | each `abstol` rises to `rtol·|y|` as the run goes; a `Float64Array` `abstol` is updated in place, so a caller that restarts keeps the high-water mark |
| `errorNorm`, `normControl` | `'max'`, off | `'rms'` is CVODE's and SciPy's; norm control weighs the whole vector |
| `maxOrder`, `bdf` | 5, off | `bdf` zeroes every κ |
| `hmax`, `h0` | a tenth of the span, chosen | |
| `maxSteps` | 1e6 | |
| `nonNegative` | none | state indices integrated as the projected system |
| `mass`, `suppressAlgebraic` | identity, off | the diagonal of M: 1 differential, 0 algebraic |
| `jacobian` | differenced densely | an array of rows, a function, `{pattern, evaluate, groups, constant}`, `{evaluateDense}` |
| `matrix` | `'auto'` | `'refactor'`, `'sparse'` (the searching Gilbert-Peierls LU) or `'dense'` |
| `denseBelow`, `denseFill` | 24, 0.15 | when `auto` takes the dense LU |
| `scaling` | off | the Newton system in the variables y_i / w_i |
| `minNewton` | 1 | Newton iterations a step must take unless the correction is under the floors |
| `stagnationTol` | 0 | take a correction that has stopped shrinking when it is this far under rtol, at a fresh Jacobian |
| `belowTolRun` | unset | failing steps at the smallest step that may be taken in a row, of either kind; unset is 20 failed error tests and no failed Newton iteration |
| `stallWindow` | 2000 | accepted steps the stall guard looks back over |
| `events`, `tStart` | none, `tspan[0]` | `{n, direction, enabled, fun}`; every event stops the run |
| `hints` | none | `{singular, noPattern}`: a sentence a page adds to those messages |
| `onAccepted`, `onOutput`, `onStep`, `debug`, `endsOnly` | | |

A failure is a `SolverError` (Kompartment imports it as `NdfFailure`) with a
`code` -- `span`, `tolerance`, `nonfinite`, `singular`, `stalled`, `steps`,
`jacobian`, `aborted` -- and, when it happens inside the run, the last twelve
accepted steps in `trace`.

## What each page passes

The defaults above are Kompartment's. facsimile.html and rtm.html pass their
own through `facsimile-solver.js`:

| | Kompartment | facsimile.html, rtm.html | why |
|---|---|---|---|
| `scaling` | off | on | the canister model's species span forty orders of magnitude; unscaled, the pivots are chosen by the largest coefficients and the trace species' corrections come out wrong |
| `minNewton` | 1 | 2 | how far a contraction rate remembered from an earlier step is trusted |
| `belowTolRun` | unset (20, and 0) | 5 | failing steps at the floor accepted in a row |
| `stallWindow`, `maxSteps` | 2000, 1e6 | 4000, 2e6 | |
| `denseBelow`, `denseFill` | 24, 0.15 | 0, 0.35 | measured on each page's own models: compartment chains, and chemistry and transport |
| `stagnationTol` | 0 | 0; rtm.html 0.5 | rtm.html's reaction networks cancel so heavily that their residual cannot be evaluated finer than a part in 1e7 |
| `hints` | about compartments and the Generated code tab | none | |

These are tunings, not different methods, and each was measured where it was
set. Making them one set of values would change the answers of one page or
another at round-off level, which is a decision about those pages, not about
this code.

## How the merge was checked

Before the two integrators were replaced by this one, every page's runs were
recorded as a hash of every stored value at full precision, and the same runs
were repeated after:

- facsimile.html: five cases of the canister model under fourteen settings
  (the LUs, the finite-difference Jacobian, both norms, no scaling, minNewton
  1, belowTolRun 0, maxOrder 2, BDF, stall tolerance, no non-negativity), 70
  runs; `rdc.html`'s decay chain through `saveAt`, three ways; and
  `resources/tests/facsimile/run.js --all`, all 38 cases against the Python
  port and SKB's FACSIMILE results, whose output is the same to the digit.
- rtm.html: its eleven examples and its default model, as a column and as a
  batch, under six settings. 78 runs.
- Kompartment: its ten examples under fifteen settings, the Rosenbrock solver
  included, and the SFK FSAR model of 9,120 states. 152 runs.

All but two groups are bit-identical. The two that are not were changed on
purpose, and are the places where the pages had drifted apart without a
reason:

- **The floating absolute tolerance** (`autoAbstol`, off by default
  everywhere) is raised from the state the run keeps, once the step is
  complete, the last step included. facsimile.html raised it from the
  corrector's value before the step was folded in, which after an event is a
  state beyond the one the run stopped at. Against the references, five
  canister cases run with it before and after are equally accurate: the
  medians agree, and the worst errors move both ways by amounts of the size
  a nudge of rtol makes.
- **`matrix: 'sparse'`** is the searching Gilbert-Peierls LU, as facsimile.html
  and rtm.html always had it. In Kompartment it meant whichever sparse LU was
  cheaper, and now that is `auto`; Kompartment offers `refactor` too.

Differences in failure messages were settled on one wording. Beyond those, the
merged code behaves as the better of the two in some cases that never occur in
a correct run: a Jacobian entry that is not a number is refused before any LU
uses it, and a dense iteration matrix larger than a quarter of a gigabyte is
never allocated.
