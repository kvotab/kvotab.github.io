/**
 * ode_core: the stiff-solver core shared by facsimile.html, rtm.html and
 * Kompartment -- the variable-order NDF/BDF integrator, the linear algebra
 * behind its iteration matrix, and event location. See README.md.
 *
 * facsimile.html and rtm.html load it as the single file ../ode-core.js,
 * built from these modules by scripts/build-solvers.mjs; Kompartment has an
 * identical copy of the modules in kompartment/src/ode/.
 */

export { EPS, zeros, identity, norm, LU, DenseLU, createMiter } from './linalg.js';
export { RefactorLU, PIVOT_THRESHOLD, KEEP_THRESHOLD, OPS_BUDGET } from './refactor.js';
export {
	CSC, cscTranspose, cscFromTriplets, cscToDense, cscMulVec, sparseMatVec,
	makeMiterBuilder, SparseLU, reverseCuthillMcKee, reverseCuthillMcKeeOrder,
	colourColumns, differenceIncrement, differenceJacobian,
	DENSE_MAX_BYTES, DENSE_BELOW, DENSE_FILL,
	iterationMatrix, makeIterationMatrix, sparseIterationMatrix,
} from './sparse.js';
export { crosses, anyCrossing, crossingTolerance, firstCrossing, locateCrossing } from './events.js';
export { ndf, SolverError, NdfFailure, MAX_ORDER } from './ndf.js';
