# ode_julia — tests

Three of them, and they answer three different questions.

```
node resources/tests/ode/julia/test-linalg.mjs
node resources/tests/ode/julia/test-order.mjs
node resources/tests/ode/julia/test-stiff.mjs [--verbose]
node resources/tests/ode/test-build.mjs           # the bundles and Kompartment's copies are up to date
```

Nothing here needs a browser or a network. The package under test is
`resources/js/ode/julia/`; see its README for what the solvers are and when to
use them.

## Is the linear algebra right?

`test-linalg` checks the dense, complex-dense and sparse LU factorisations by
**residual** rather than against stored numbers: for a linear solve, ‖Ax − b‖
is the whole truth, and a factorisation that matches a stored answer to six
digits on one matrix can still be wrong. The complex solve is checked a second
way, against the equivalent real system of twice the size, which is a genuinely
independent route to the same answer.

Half the matrices are built so that **every step must pivot** — a zero
diagonal, or a reversed one. That is not decoration. The first version of the
dense factorisation swapped whole rows, LAPACK style, while its solve applied
the interchanges one at a time between eliminations, LINPACK style. The two
conventions are individually correct and cannot be mixed, and the mixture is
invisible on any diagonally dominant matrix, which is what every first draft of
this test used.

## Are the tableaux right?

`test-order` measures the **observed order of convergence** of every method
against a manufactured problem whose exact solution is written down: fixed
steps, four halvings, and the slope of log(error) against log(dt).

This is the test that proves a tableau was transcribed correctly, and it is the
only one that does. A Rosenbrock or Runge-Kutta method with one mistyped
coefficient does not crash, does not report an error, and passes any reasonable
accuracy check at a working tolerance. It just quietly loses its order.

Two things had to be arranged for the measurement to mean anything.

*The problem is only mildly stiff.* Classical order is a statement about the
limit h·λ → 0, and every one-step method here loses order on a genuinely stiff
problem — order reduction is well documented and Rodas5P is partly designed
around it. The same problem at three stiffnesses gives Rodas5P 5.00, 4.9 and
about 3.5.

*The Newton iteration is held far tighter than any real run would hold it.*
Otherwise its stopping criterion puts a floor under the error. For RadauIIA5,
which works to Hairer's deliberately loosened internal tolerance, that floor is
around 5e-13, and the measured order falls away beneath it while saying nothing
about the tableau.

The three multistep methods — FBDF, QNDF and QBDF — are measured at each of
orders 1 to 5 separately, with the history before t₀ seeded from the exact
solution. A k-step formula has nothing to be order k with until it has k past
points, so started cold its first steps are order 1 and 2 and the measurement
sees those instead of the formula. QNDF against QBDF is also a check on
Shampine's κ: the two differ only in those coefficients, and QNDF is duly the
more accurate at orders 1 to 3 and identical at order 5, where κ is zero.
Adaptively the two trade places by problem and tolerance, which is the honest
picture — κ shrinks the error constant and costs a little stability.

Two real bugs were caught here and nowhere else: a time-derivative difference
step that collapsed near t = 0 and cost Rodas5P two orders, and a Newton update
scaled by γh because the residual assumed one form of W and the code built the
other.

## Do they survive real stiff problems?

`test-stiff` runs all five against the standard set from Hairer and Wanner's
second volume — Robertson, HIRES, the Oregonator, pollution, and van der Pol at
μ = 10⁶ — which were chosen decades ago precisely because solvers fall over on
them. It tests everything the order test does not: the step-size control, the
Newton convergence heuristics, the order selection, the Jacobian reuse.

The references in `ref/` come from `scipy.integrate` Radau at `rtol = 1e-12`,
three orders tighter than anything asked for here and somebody else's
arithmetic. Regenerate with `python3 scripts/gen-ode-julia-ref.py`.

Two decisions about how to compare, both of which cost an afternoon before they
were got right:

*Errors are measured in units of the tolerance the solver was given*,
`|got − want| / (atol + rtol·|want|)`, not as relative differences. Robertson's
third component is 1.6e-11 at the first sampled decade; at `atol = 1e-14` every
method's error there is a fraction of one tolerance unit and none of them is
doing anything wrong, yet measured relatively they all look 1e-4 out.

*The reference times are step endpoints* (`saveat` together with `tstops`), so
what is compared is the integration and not the interpolant. Measured through
the interpolant, the worst error on Robertson is always at the first sampled
decade, inside one enormous opening step — a fair test of an interpolant and no
test at all of a solver. That is also how a genuine bug surfaced: the Radau
interpolant had been written with OrdinaryDiffEq's *extrapolation* formula,
whose argument is a step ratio rather than a position within a step, so it did
not return the solver's own answer even at the ends of the step.

TRBDF2 runs at a looser tolerance than the rest and is held to ten times the
slack, because it is second order and a pointwise comparison on a problem with
sharp transients measures phase. See the README's note on its cliff.

## What the stiff set found

Everything below was found by these tests and would not have been found by
inspection.

* The step-size controller was shrinking a rejected step using the error of the
  last *accepted* one, so the factor was always near 1 and a solver meeting a
  sharp transition needed tens of thousands of rejections to get through.
* `dtmin` was derived from the larger end of the time span, which forbids at
  t = 0 the small steps every stiff solver needs there. FBDF was stopped dead
  three steps into Robertson with nothing wrong with the method.
* The Jacobian was re-evaluated whenever `t` had moved — every step — so the
  reuse the whole design is built around never happened once.
* A Newton tolerance of 1/100, which is OrdinaryDiffEq's, leaves enough
  left-over error in an ESDIRK's stages to corrupt its embedded error estimate.
  TRBDF2 walked the pollution problem up to 10⁹ in components that belong
  between 0 and 1, reporting success throughout.
* QNDF rescaling its backward differences on most steps: the rescale is
  approximate, the error estimates are read from the very differences it
  degrades, and the two feed each other. Rejecting half its steps and returning
  answers 10³ tolerance units out; holding the step over a wider band fixed
  both at once.
