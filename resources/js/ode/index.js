/**
 * The ODE solvers shared by facsimile.html, rtm.html and Kompartment, less the
 * ported ones: the variable-order NDF/BDF integrator (solvers/), the linear
 * algebra behind its iteration matrix and event location (core/). The solvers
 * ported from DifferentialEquations.jl are a package of their own, julia/. See
 * README.md.
 *
 * facsimile.html and rtm.html load these modules as the single file
 * ../ode-core.js, built by scripts/build-solvers.mjs; Kompartment has an
 * identical copy of core/ and solvers/ in kompartment/src/ode/.
 */

export { EPS, zeros, identity, norm, LU, DenseLU, createMiter } from './core/linalg.js';
export { RefactorLU, PIVOT_THRESHOLD, KEEP_THRESHOLD, OPS_BUDGET } from './core/refactor.js';
export {
	CSC, cscTranspose, cscFromTriplets, cscToDense, cscMulVec, sparseMatVec,
	makeMiterBuilder, SparseLU, reverseCuthillMcKee, reverseCuthillMcKeeOrder,
	colourColumns, differenceIncrement, differenceJacobian,
	DENSE_MAX_BYTES, DENSE_BELOW, DENSE_FILL,
	iterationMatrix, makeIterationMatrix, sparseIterationMatrix,
} from './core/sparse.js';
export { crosses, anyCrossing, crossingTolerance, firstCrossing, locateCrossing } from './core/events.js';
export { ndf, SolverError, NdfFailure, MAX_ORDER } from './solvers/ndf.js';
