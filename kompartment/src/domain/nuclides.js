/**
 * Radionuclide data: half-lives, and the decay pairs a set of nuclides makes.
 *
 * PROVENANCE. Ecolego ships its nuclide data in a native database that a
 * browser cannot read. This tool
 * uses the tables of **ICRP Publication 107** instead -- see ./icrp107.js for
 * where they came from -- and they are the only radionuclide data in it.
 *
 * There used to be a second inflow: a table of fifty half-lives and
 * twenty-four decay pairs, typed by hand into this file, covering the nuclides
 * an assessment usually singles out. Its own note said it was not the Ecolego
 * database and that assessment work should import the real one. It is gone.
 * What it held is now read from 1,512 nuclides of published data, and what it
 * *claimed* is kept in the test suite, where it does more good: an independent
 * hand-typed table to check the computed one against.
 *
 * The chains are the part worth understanding. There is no table of them.
 * A model's decay pairs are worked out from the nuclides it carries, by
 * collapsing the published chains onto exactly that set -- so a model holding
 * U-238, U-234, Th-230, Ra-226 and Pb-210 gets the four pairs between them,
 * with the branching that actually reaches each one, and never has to say so.
 * See ./decaydb.js.
 */

import { ICRP107 } from './icrp107.js';
import { collapse } from './decaydb.js';

/**
 * Half-life in years, `Infinity` for a stable nuclide.
 *
 * Every nuclide ICRP 107 has, which is every nuclide this application knows:
 * a name typed into the radionuclide list now arrives with its half-life
 * already right, instead of starting stable and waiting to be told.
 */
export const HALF_LIVES = Object.fromEntries(ICRP107.map((row) => [row[0], row[3]]));

/**
 * The decay pairs a set of nuclides makes, when the model does not say.
 *
 * Computed rather than tabulated, which is the whole point: a table of pairs
 * is only right for the nuclides it was written for. Ask for the pairs among
 * `[U-238, U-234, Th-230, Ra-226, Pb-210]` and you get the four between them,
 * each carrying the branching that reaches it through the eleven short-lived
 * members in between; ask for `[U-238, Pb-210]` and you get the one pair, with
 * the same total probability. Neither is a row anybody had to type.
 *
 * `project.chains` still overrides it, for a model that means something else.
 *
 * @param {string[]} nuclides the names the model carries
 * @returns {Array<[string, string, number]>} parent, daughter, branching
 */
export function defaultChains(nuclides, ceiling = Infinity) {
	return collapse(nuclides ?? [], { ceiling }).pairs;
}

/** The nuclide selections a safety assessment reports against. */
export const SKB_TOP10 = [
	'Mo-93', 'C-14', 'I-129', 'Ni-59', 'Cs-135', 'Cl-36',
	'Se-79', 'Pu-239', 'Tc-99', 'Zr-93',
];

export const SKB_TOP30 = [
	'Mo-93', 'C-14', 'I-129', 'Ni-59', 'Cs-135', 'Cl-36', 'Se-79', 'Tc-99',
	'Zr-93', 'Ag-108m', 'Ca-41', 'Pu-238', 'Pu-239', 'Pu-240', 'Pu-241',
	'Pu-242', 'U-238', 'Th-230', 'Ra-226', 'Pb-210', 'Po-210', 'U-235',
	'Pa-231', 'Ac-227', 'Am-241', 'Am-243', 'Nb-93m', 'Nb-94', 'Pd-107',
	'Sn-126', 'Sr-90', 'Cs-137', 'Np-237',
];

const LN2 = Math.log(2);

/** Seconds per year used by Ecolego's unit system (Julian year). */
export const SECONDS_PER_YEAR = 365.25 * 24 * 3600;

/**
 * Decay constant in 1/timeUnit.
 *
 * lambda = ln(2) / halfLife, with the
 * half-life first converted into the simulation's time unit.
 */
export function lambda(nuclide, timeUnit = 'year', halfLives = HALF_LIVES) {
	const hlYears = halfLives[nuclide];
	if (hlYears == null) return 0; // unknown or stable: no decay
	if (!Number.isFinite(hlYears)) return 0;
	return LN2 / convertYears(hlYears, timeUnit);
}

/**
 * The half-life, in years, that a decay constant implies.
 *
 * The inverse of `lambda` above, and here rather than at the one place that
 * needs it so the pair cannot drift: a model that showed λ from one formula and
 * read it back with another would round-trip a half-life into a different one,
 * which is the sort of thing nobody notices until a dose is 3% out.
 *
 * λ is per `timeUnit` -- it is the number the solver multiplies an inventory by,
 * so it is in the model's own unit -- while a half-life is stored in years.
 * Both conversions are `convertYears`, in opposite directions.
 *
 * Zero is `Infinity`, which is how a nuclide that does not decay is written: a
 * decay constant of zero and a half-life of forever are the same statement.
 *
 * @param {number} lam       the decay constant, per `timeUnit`
 * @param {string} timeUnit
 * @returns {number|null} years, `Infinity` for stable, or null for a λ that is
 *   not a decay constant at all
 */
export function halfLifeFromLambda(lam, timeUnit = 'year') {
	// Nothing is not zero. `Number(null)` and `Number('')` are both 0, and 0
	// here means *stable* -- so a null falling through would quietly make a
	// nuclide immortal. Only an actual number, or text that is one.
	if (lam == null) return null;
	if (typeof lam !== 'number' && String(lam).trim() === '') return null;
	const v = Number(lam);
	if (!Number.isFinite(v) || v < 0) return null;
	if (v === 0) return Infinity;
	const f = TIME_UNITS[timeUnit];
	if (f == null) throw new Error(`Unknown time unit '${timeUnit}'`);
	// ln2/λ is the half-life in the model's unit; × f puts it back in years.
	return (LN2 / v) * f;
}

/**
 * The time units a simulation may be written in, and a year in each.
 *
 * On a null prototype, because this is a whitelist and the name being looked
 * up comes out of a project file. On a plain object `TIME_UNITS.constructor`
 * is a function and therefore truthy, so a file declaring its time unit to be
 * `constructor` passed the check that exists to refuse exactly that -- and the
 * conversion factor it then got was a function, which is how a run ends up
 * with NaN everywhere for a reason nothing can explain.
 */
export const TIME_UNITS = Object.assign(Object.create(null), {
	second: 1 / SECONDS_PER_YEAR,
	minute: 60 / SECONDS_PER_YEAR,
	hour: 3600 / SECONDS_PER_YEAR,
	day: 1 / 365.25,
	year: 1,
});

/** Converts a duration in years into `unit`. */
export function convertYears(years, unit) {
	const f = TIME_UNITS[unit];
	if (f == null) throw new Error(`Unknown time unit '${unit}'`);
	return years / f;
}

/**
 * The units a radionuclide inventory can be held in.
 *
 * the contaminant catalogue in Ecolego keeps one of these for the whole model -- and
 * keeps every nuclide's own unit in step with it, which is how an .eco file
 * carries the choice: `<nuclide><unit>Bq</unit></nuclide>`. `Bq` is its
 * default, and every real model in the corpus says `Bq`.
 */
export const DECAY_UNITS = ['Bq', 'mol'];

/**
 * Builds the decay model for a chosen set of nuclides.
 * Returns { lambdas, parents } where parents[i] lists
 * { index, lambda, ratio } contributing ingrowth into nuclide i.
 *
 * `decayUnit` decides which decay constant multiplies the parent's inventory,
 * and it is the whole difference between holding activity and holding an
 * amount. Both are the same physics in different variables -- A = lambda*n --
 * so each is exact for its own quantity and neither is an approximation of the
 * other:
 *
 *   mol   dn_D/dt = -lambda_D*n_D + sum(lambda_P * ratio * n_P)
 *   Bq    dA_D/dt = -lambda_D*A_D + sum(lambda_D * ratio * A_P)
 *
 * The amount form is the classical Bateman equation for numbers of nuclei.
 * Multiplying it through by lambda_D turns it into the activity form, since
 * lambda_D*(lambda_P*n_P) = lambda_D*A_P. What must not happen is mixing them:
 * the two coefficients differ by T(P)/T(D), which for U-238 into U-234 is a
 * factor of 18,200.
 *
 * the standard decay term makes exactly this choice
 * -- `ingrowthLambda = lambda` unless `decayUnit == UnitFactory.MOLE()`, when
 * it is `ln(2) / halfLife(parent)` -- and so does the simplified path in
 * the standard lambda lookup. Self-decay is the daughter's own lambda
 * either way.
 */
export function buildDecayModel(nuclideNames, timeUnit = 'year', options = {}) {
	const halfLives = options.halfLives ?? HALF_LIVES;
	// Worked out for these nuclides when the caller does not bring its own.
	// `ceiling` is the half-life above which an un-modelled daughter is a
	// sink rather than passed through; see `collapse`.
	const chains = options.chains ?? defaultChains(nuclideNames, options.ceiling ?? Infinity);
	const idx = new Map(nuclideNames.map((n, i) => [n, i]));

	const lambdas = nuclideNames.map((n) => lambda(n, timeUnit, halfLives));
	const parents = nuclideNames.map(() => []);

	// Which lambda the parent's inventory is multiplied by: see DECAY_UNITS.
	const amounts = options.decayUnit === 'mol';
	for (const [parent, daughter, ratio] of chains) {
		const pi = idx.get(parent);
		const di = idx.get(daughter);
		// Ingrowth only applies when both members are part of the simulation.
		if (pi === undefined || di === undefined) continue;
		parents[di].push({ index: pi, lambda: amounts ? lambdas[pi] : lambdas[di], ratio });
	}

	return { names: nuclideNames.slice(), lambdas, parents };
}

/**
 * The chemical element a nuclide belongs to: `Cs-137` -> `Cs`.
 *
 * Ecolego keeps an element dimension beside the nuclide one, because chemistry
 * is a property of the element and not of the isotope -- a sorption
 * coefficient, a concentration ratio and a partition factor are all per
 * element, while inventory and decay are per nuclide.
 *
 * The name is everything up to the first digit, which covers every spelling
 * the corpus uses: `Cs-137`, `C-14`, `Nb-93m`, `Ag-108m`, `C-14 organic`,
 * `C-14-inorg`. It deliberately does *not* try to keep the organic and
 * inorganic forms of carbon apart -- a model that needs that distinction
 * declares its own list, and this one steps aside for it.
 *
 * @returns {string|null} the symbol, or null when there is nothing to take
 */
export function elementOf(nuclide) {
	const name = String(nuclide ?? '').trim();
	const m = /^([A-Za-z]{1,3})(?=$|[-\s0-9])/.exec(name);
	if (!m) return null;
	// Capitalised the way a symbol is, so `cs-137` and `Cs-137` agree.
	return m[1][0].toUpperCase() + m[1].slice(1).toLowerCase();
}

/** Every nuclide in the database, in its own order: by Z, then by A. */
export function knownNuclides() {
	return ICRP107.map((row) => row[0]);
}

/** The ones that decay, which is what a model can carry. */
export function decayingNuclides() {
	return ICRP107.filter((row) => row[3] !== Infinity).map((row) => row[0]);
}
