/* ==========================================================================
   ode_julia

   Stiff ODE solvers ported from DifferentialEquations.jl, for the browser and
   for Node. No dependencies.

     import { solve, ODEProblem, Rodas5P } from './ode/julia/index.js';

     const prob = new ODEProblem(f, u0, [0, 1e5], { jac });
     const sol = solve(prob, Rodas5P(), { reltol: 1e-8, abstol: 1e-10 });
     sol.final;            // the state at the end
     sol.at(t);            // anywhere in between
     sol.stats;            // what it cost

   See README.md for the options and for which method to reach for.
   ========================================================================== */

export {
  ODEProblem, ODESolution, ODEError, solve,
  Success, MaxIters, DtLessThanMin, Unstable, Terminated,
} from './core/integrator.js';

export {
  DenseMatrix, CSC, cscFromTriplets, DenseLU, ComplexDenseLU, SparseLU,
  reverseCuthillMcKee,
} from './core/linalg.js';

export { JacobianCache, WFactorization, colourColumns, densePattern } from './core/jacobian.js';
export { NewtonSolver } from './core/newton.js';
export { PIController, initialStep } from './core/controller.js';

export { Rodas5P, rosenbrockAlgorithm } from './solvers/rosenbrock.js';
export { Rodas5PTableau } from './solvers/rodas5p-tableau.js';
export { TRBDF2, KenCarp4, esdirkAlgorithm } from './solvers/esdirk.js';
export { FBDF, fornbergWeights } from './solvers/fbdf.js';
export { QNDF, QBDF, rescaleMatrix } from './solvers/qndf.js';
export { RadauIIA5 } from './solvers/radau.js';
export { RadauIIA5Tableau } from './solvers/radau-tableau.js';
export { TRBDF2Tableau, KenCarp4Tableau } from './solvers/esdirk-tableaus.js';
