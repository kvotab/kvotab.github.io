# src/ode/julia

Stiff ODE solvers ported from [DifferentialEquations.jl][sciml], for the
browser and for Node. No dependencies. Licence: MIT, as the original; the
notice is in `LICENSE` beside this file.

```js
import { solve, ODEProblem, FBDF } from './index.js';

const f = (t, u, du) => { du[0] = -0.04 * u[0] + 1e4 * u[1] * u[2]; /* … */ };
const prob = new ODEProblem(f, [1, 0, 0], [0, 1e5], { jac });
const sol = solve(prob, FBDF(), { reltol: 1e-8, abstol: 1e-12 });

sol.final;      // the state at the end
sol.at(1e3);    // anywhere in between
sol.stats;      // what it cost
sol.retcode;    // 'Success', or why not
```

[sciml]: https://docs.sciml.ai/DiffEqDocs/stable/

## The methods

| | order | stages | kind | good for |
|---|---|---|---|---|
| `FBDF()` | 1–5, adaptive | multistep | fixed-leading-coefficient BDF | large systems, long smooth runs |
| `QNDF()` | 1–5, adaptive | multistep | quasi-constant-step NDF | the same, and compatibility |
| `QBDF()` | 1–5, adaptive | multistep | `QNDF` with every κ = 0: plain variable-step BDF | a control on what κ buys |
| `Rodas5P()` | 5 | 8 | Rosenbrock-Wanner, L-stable | where a Newton iteration struggles |
| `RadauIIA5()` | 5 | 3 | fully implicit Radau IIA, L-stable | accuracy, and the worst stiffness |
| `KenCarp4()` | 4 | 6 | ESDIRK, L-stable | a good default at moderate tolerances |
| `TRBDF2()` | 2 | 3 | ESDIRK, L-stable | loose tolerances, cheaply |

**Which to reach for.** `FBDF` first for anything large: it reuses one matrix
factorisation across many steps, which on a system of hundreds of states is
most of the cost. `Rodas5P` when something will not converge — it has no
nonlinear iteration at all, so there is nothing to fail. `RadauIIA5` when the
answer has to be right: it suffers the least order reduction on stiff problems
and is the one to believe when two others disagree. `KenCarp4` is a reasonable
middle. `TRBDF2` is fast and forgiving at loose tolerances; read the warning
below before using it at tight ones.

`QNDF` and `FBDF` are the two BDF methods in DifferentialEquations.jl and they
overlap heavily. `QNDF` is the numerical differentiation formulas of Shampine
and Reichelt exactly — the same κ, the same backward-difference rescaling — so
reach for it when you want those, or as a check on another implementation of
them. `FBDF` is what
SciML recommends for the largest stiff systems and is the steadier of the two
here. `QBDF()` is `QNDF` with every κ set to zero, which is the plain
variable-step BDF — SciML's own alias, and the same thing — and a useful
control: κ is precisely what makes an NDF out of a BDF, so running both says
what those terms are worth on your problem. For a fixed order, pass
`maxOrder` and `minOrder` equal; there is no separate `QNDF1`/`QNDF2` here.

## Options

Passed as the third argument to `solve`.

| | default | |
|---|---|---|
| `reltol`, `abstol` | `1e-3`, `1e-6` | `abstol` may be a per-component array |
| `dt` | chosen | the first step; required when `adaptive: false` |
| `dtmax`, `dtmin` | `Infinity`, per-`t` | `dtmin` defaults to sixteen ulp of the current time |
| `adaptive` | `true` | `false` marches at `dt` and ignores the error estimate |
| `maxiters` | `1e7` | |
| `saveat` | — | a list of times, or an interval; uses the method's interpolant |
| `saveEverystep` | `true` | ignored when `saveat` is given |
| `maxPoints` | — | a ceiling on the stored points, thinned by halving |
| `tstops` | — | times the solver must land on exactly |
| `nonNegative` | — | `true`, or a boolean per component, to clamp at zero |
| `matrix` | `'auto'` | `'sparse'` or `'dense'` to decide the linear algebra |
| `norm` | `'rms'` | `'max'` for the maximum norm |
| `central` | `false` | central differences for a differenced Jacobian |
| `maxJacAge` | `20` | steps a Jacobian may be reused for |
| `kappa` | `1e-3` | how tightly each stage's Newton must converge |
| `belowTolRun` | `0` | steps at the smallest representable size that may be accepted after failing the error test |
| `autoAbstol` | `false` | let `abstol` follow the solution upwards, per component |
| `progress` | — | `(t, nsteps) => false` to stop |
| `onAccepted` | — | `(t, u)` after each accepted step |
| `history` | — | solution before `t0`, so a multistep method starts at full order |

On the problem: `jac(t, u, J)` fills the Jacobian in place, `jacPattern` gives
its sparsity, `tgrad(t, u, dT)` gives ∂f/∂t, and `events` is
`{ n, fun(t, u, out), direction, terminal, apply(t, u) }`.

## Things worth knowing

**Give it a Jacobian if you have one.** Without `jac`, df/du is differenced,
which costs one evaluation of `f` per group of structurally orthogonal columns.
Give `jacPattern` even when the matrix will be handled densely: a chemical
Jacobian of 63 species needs about 45 groups rather than 64 evaluations.

**Give Rosenbrock a `tgrad` on a non-autonomous problem.** Rodas5P carries a
∂f/∂t term. Differenced, that term is the accuracy floor before the step size
is; with an exact one, order 5 holds all the way down. (Measured on a
manufactured problem: 5.00 either way now, but only because the difference step
is scaled by `max(|t|, |h|)` — scaled by `|t|` alone, as it was at first, it
collapses near `t = 0` and the method quietly converges at order 3.)

**TRBDF2 has a cliff.** It is second order, and on a problem with sharp
transients a low order costs phase accuracy long before it costs local
accuracy. On the Oregonator at `reltol = 1e-5` it is about 3000 tolerance units
out; at `1e-4` it is 10¹¹ out, and reports success both times. Use it at loose
tolerances on smooth problems, or use `KenCarp4`.

**Radau always factorises its complex half densely.** The Newton system splits
into one real and one complex n×n solve, and this package has no complex sparse
LU. Below a few hundred states that is unnoticeable; above a few thousand,
use `FBDF`.

**QNDF holds its step size over a wide band.** Every change of step rescales
the backward differences, and that rescale is approximate — truncated at order
k, it leaves about a per cent of relative error in the highest difference even
for a ratio of 0.9. The highest differences are what the error estimates are
read from, so rescaling on most steps corrupts the estimate, which asks for
another change. `qsteadyMin`/`qsteadyMax` therefore default to 0.25 and 4 here
rather than OrdinaryDiffEq's 0.9 and 1.2. Measured across the stiff set that is
worth one to two orders of magnitude of accuracy and usually fewer steps: on
the Oregonator, 2×10⁴ tolerance units in 17045 steps becomes 264 units in 9159.

**Letting `abstol` follow the solution.** With `autoAbstol`, after each
accepted step `abstol[i]` is raised to `reltol·|u[i]|` where that is larger, and
never lowered again, so each component is judged against the largest it has ever
been rather than against a floor fixed before the run. On a chemical system that
is often the right question — a radical that rose to 1e-5 and decayed to 1e-40
is otherwise still held to the original `abstol`, orders below anything it ever
was. It only ever loosens, which is both the point and the risk. What it is
worth depends on the method: on the Hairer set FBDF goes from 967 steps to 757
on Robertson and 894 to 624 on HIRES, while on one stiff chemistry model it
halves FBDF's work and doubles QNDF's.

The Newton iteration keeps the tolerance it started with. The two uses want
opposite things: the error test asks whether a component is accurate enough,
where its history is a fair measure, and the Newton test asks how well a stage
has been solved, where it is not.

**A step at the floor that fails anyway.** When the step a solver wants is
smaller than the smallest one that changes the clock at the current time, there
is nothing left to try. By default every method here stops and hands back what
it has, which is what the published methods do — a tolerance-not-met error
and a return — and what DifferentialEquations.jl does.
`belowTolRun: n` accepts up to `n` such steps in a row instead, counting them in
`stats.nbelowtol` so a run that leaned on it says so. It is off by default
because accepting a step known to be inaccurate should be asked for, not
assumed.

**No mass matrices.** These solve `u' = f(t, u)`. `M·u' = f` is a natural
extension and is not implemented.

**The Newton tolerance is tighter than SciML's.** `kappa` defaults to `1e-3`
here against OrdinaryDiffEq's `1e-2`, and the η convergence forecast is not
believed on the first iteration. Both were measured, not chosen: at `1e-2` the
left-over Newton error in an ESDIRK's stages contaminates its embedded error
estimate, which is a small difference of those same stages. The symptom is a
step-size controller acting on a corrupted number — TRBDF2 walked the pollution
problem up to 10⁹ in components that belong between 0 and 1. At `1e-3` it is
correct and, no longer being lied to, several times cheaper.

## How it was ported, and how it is checked

The tableaux were generated from the Julia sources rather than retyped, by
scripts that refused to write unless the coefficients satisfied the identities
they must (row sums of `a` equal `c`, `b` sums to one, `btilde` sums to zero,
the Radau eigenvalues sum to s²).

That is not enough on its own, because a tableau with one wrong digit does not
fail — it quietly loses its order, and no accuracy check at a working tolerance
notices. So the observed order of convergence of every method was measured
against a manufactured problem with a known solution, at fixed steps, over
four halvings: all six hit their advertised orders, and FBDF, QNDF and QBDF
each hit every order from 1 to 5 with their history seeded. All six were then
run against the standard Hairer and Wanner set — Robertson, HIRES, the
Oregonator, pollution, van der Pol at μ = 10⁶ — against references from
`scipy.integrate` Radau at `rtol = 1e-12`. The checks that ship with the
application are in `test/run.js`, under *the ported DifferentialEquations.jl
solvers*.

## Layout

```
core/linalg.js       dense, complex and sparse LU; CSC; reverse Cuthill-McKee
core/jacobian.js     df/du by colour groups, and W = I − γh·J, factorised and reused
core/newton.js       the simplified Newton iteration and its convergence tests
core/controller.js   the PI step-size controller, and the starting step
core/integrator.js   the loop: stepping, saving, dense output, event location
solvers/             one file per family, plus a generated tableau beside each
```

## Changes made for this application

Three, all of them worth taking back upstream.

1. **`core/jacobian.js` — a `jac` may decline a point.** `userJac(t, u, J)`
   answering `false` now means "not this time", and the cache differences that
   one call instead. The application's analytic Jacobian refuses a point where
   an entry would come out non-finite and differences for it, which is exactly
   this; without the hook it would have had to hand over a matrix with an
   infinity in it.

2. **`core/jacobian.js` — the differencing machinery is built even when a `jac`
   was given**, because of (1): the fall-through needs the colour groups and the
   perturbation buffers. It costs one colouring at construction.

3. **`core/integrator.js` — a root at the instant the solve began is not a
   crossing.** This is a bug fix rather than an adaptation. A caller that stops
   at a terminal event and restarts from it hands back the state *at* the root,
   where `g` is zero to rounding; whether that leaves it at `-1e-17` or
   `+1e-17` is luck, and on the unlucky side the first step of the new run
   crosses it again. The same event then fires twice, a duplicate row lands in
   the output, and a caller that restarts on every event can be walked round
   that loop indefinitely. `KenCarp4` did this on
   `examples/recorders.json`; the other five methods happened to land on the
   lucky side of the same root.
