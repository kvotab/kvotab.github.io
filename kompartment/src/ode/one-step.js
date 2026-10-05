/**
 * The two one-step solvers, in this tool's words.
 *
 * ./solvers/dormand-prince.js and ./solvers/rosenbrock23.js, and the driver
 * they share in ./core/onestep.js, are the solver core this tool shares with
 * facsimile.html and rtm.html (resources/js/ode/ in the site, at the same
 * relative paths; the copies here are the same bytes). What a run is told
 * when one of them cannot go on is in the solver's terms, and each page adds
 * what its reader can do about it in its own: `hints`, as ndf takes them from
 * ./variable-order.js. These are this tool's -- the compartment's setting
 * that holds an inventory at zero, the switch times a model declares, and
 * what a singular matrix usually means here.
 */

import { dormandPrince as dormandPrinceSolve, SolverError, nonFiniteError } from './solvers/dormand-prince.js';
import { rosenbrock23 as rosenbrock23Solve } from './solvers/rosenbrock23.js';

export { SolverError, nonFiniteError };

/** Sentences for the one-step solvers' messages, in this tool's terms. */
export const HINTS = Object.freeze({
	floor: 'turn "cannot go negative" off on the compartment to see what the model really does',
	switches: 'declare its switch times',
	singular: 'A compartment with no way in and no way out will do this.',
	singularDense: 'A compartment may be disconnected or a transfer rate may be non-finite.',
});

/** Dormand-Prince (4,5), with this tool's hints. Same signature as ndf's adapter. */
export function dormandPrince(f, tspan, y0, opts = {}) {
	return dormandPrinceSolve(f, tspan, y0, { ...opts, hints: opts.hints ?? HINTS });
}

/** Rosenbrock (2,3), with this tool's hints. */
export function rosenbrock23(f, tspan, y0, opts = {}) {
	return rosenbrock23Solve(f, tspan, y0, { ...opts, hints: opts.hints ?? HINTS });
}
