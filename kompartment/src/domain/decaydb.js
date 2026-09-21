/**
 * Reading the ICRP 107 database, and collapsing a decay chain onto the
 * nuclides a model actually carries.
 *
 * The problem this exists for. A compartment model tracks one inventory per
 * nuclide per compartment, so every nuclide it names costs a state variable
 * per box -- and the U-238 chain has fifteen members, of which nine live for
 * minutes or less. Nobody integrates Po-214 (164 microseconds) over a hundred
 * thousand years: its activity follows its parent's within a rounding error,
 * which is *secular equilibrium*, and the standard move is to leave it out and
 * let its parent decay straight through to the next member worth modelling.
 *
 * Doing that by hand is where the errors are. Leaving out Pa-234m means
 * U-238's daughter is now U-234, and the branching that reaches it is the
 * product of the ratios along the way -- 0.9984 through Pa-234m, not 1 -- and
 * the 0.0016 that goes the other way ends up somewhere else. Multiply that by
 * four decay series and the ninety-odd fission and activation products, and a
 * table typed by hand is a table with mistakes in it. See ./nuclides.js, whose
 * chains were typed by hand and whose own note says so.
 *
 * So: choose which nuclides to model, and let `collapse` work out the pairs.
 * The rule it implements is one sentence -- the effective branching from A to
 * B is the total probability that a decay of A reaches B through nuclides that
 * are not being modelled -- and the implementation is that sentence memoised
 * over an acyclic graph.
 */

import { ICRP107, ELEMENTS } from './icrp107.js';

/** Every row by name. */
const BY_NAME = new Map(ICRP107.map((row) => [row[0], row]));

/** Element metadata by symbol, and by Z. */
const BY_SYMBOL = new Map(ELEMENTS.map((e) => [e[1], e]));

/** @returns {{name: string, z: number, a: number, halfLife: number, text: string,
 *             progeny: Array<{name: string, branching: number, mode: string}>}|null} */
export function nuclide(name) {
	const row = BY_NAME.get(name);
	if (!row) return null;
	return {
		name: row[0], z: row[1], a: row[2], halfLife: row[3], text: row[4],
		progeny: row[5].map(([n, br, mode]) => ({ name: n, branching: br, mode })),
	};
}

/** Whether the database has heard of it. */
export function known(name) { return BY_NAME.has(name); }

/** Half-life in years; `Infinity` for a stable nuclide, `null` for a stranger. */
export function halfLife(name) {
	const row = BY_NAME.get(name);
	return row ? row[3] : null;
}

/**
 * ICRP calls a nuclide stable when it does not decay in its tables -- which
 * includes Bi-209, whose half-life is longer than the age of the universe by
 * nine orders of magnitude. Either way it is not something a model integrates.
 */
export function isStable(name) { return halfLife(name) === Infinity; }

/** Every nuclide of one element, by symbol, lightest first. */
export function isotopesOf(symbol) {
	return ICRP107.filter((row) => row[0].split('-')[0] === symbol).map((row) => row[0]);
}

/** The element a nuclide belongs to: `Cs-137` -> `Cs`. */
export function elementOf(name) { return String(name).split('-')[0]; }

/**
 * The elements the database has nuclides for, in atomic order.
 *
 * @returns {Array<{z: number, symbol: string, name: string, category: string,
 *                  isotopes: string[], unstable: number}>}
 */
export function elements() {
	const out = [];
	for (const [z, symbol, name, category] of ELEMENTS) {
		const isotopes = isotopesOf(symbol);
		if (!isotopes.length) continue;
		out.push({
			z, symbol, name, category, isotopes,
			unstable: isotopes.filter((n) => !isStable(n)).length,
		});
	}
	return out;
}

/** Every unstable nuclide, which is what a model can carry. */
export function allUnstable() {
	return ICRP107.filter((row) => row[3] !== Infinity).map((row) => row[0]);
}

// --- collapsing -------------------------------------------------------------

/**
 * Where a decay of `name` ends up, counting only the nuclides in `keep`.
 *
 * A map from a kept nuclide to the probability that one decay of `name`
 * reaches it, having passed only through nuclides that are not kept. What
 * reaches a stable nuclide, or a branch that fissions, is simply absent -- it
 * has left the chain, which is what a model with no stable end-product does
 * with it too.
 *
 * Memoised per call, which is what makes this linear in the graph's edges
 * rather than in its paths: `dist(Pa-234m)` is asked for by everything above
 * it. Safe because the database is acyclic -- the test suite checks that, and
 * a cycle here would be an infinite recursion rather than a wrong answer.
 */
function distribution(name, keep, memo, through, ceiling = Infinity) {
	const cached = memo.get(name);
	if (cached) return cached;
	const out = new Map();
	// Placed before the walk: a cycle would otherwise recurse forever, and
	// while the database has none, a hand-edited one might.
	memo.set(name, out);
	for (const [daughter, branching] of BY_NAME.get(name)?.[5] ?? []) {
		if (keep.has(daughter)) {
			out.set(daughter, (out.get(daughter) ?? 0) + branching);
			continue;
		}
		if (isStable(daughter)) continue;   // the activity leaves the chain
		// A daughter that outlives the ceiling is a sink too: Th-232 at
		// fourteen billion years passes nothing on within any assessment,
		// and walking through it would hand U-236's activity to Ra-228 at
		// U-236's rate, which is not a thing that happens.
		if (halfLife(daughter) > ceiling) continue;
		through?.add(daughter);
		for (const [target, share] of distribution(daughter, keep, memo, through, ceiling)) {
			out.set(target, (out.get(target) ?? 0) + branching * share);
		}
	}
	return out;
}

/**
 * The decay pairs among a chosen set of nuclides.
 *
 * @param {Iterable<string>} names the nuclides the model carries
 * @param {{minBranching?: number, ceiling?: number}} [opts] pairs below
 *   `minBranching` are dropped, since a branch of 1e-9 is a row in the matrix
 *   that changes no result; zero keeps everything. An un-modelled daughter
 *   whose half-life is above `ceiling` (years) is treated as stable -- a sink
 *   -- rather than passed through; Infinity, the default, passes everything.
 * @returns {{pairs: Array<[string, string, number]>, through: string[],
 *            unknown: string[]}}
 *   `pairs` is [parent, daughter, branching], in the same shape as
 *   ./nuclides.js's DECAY_CHAINS. `through` names the nuclides that were
 *   passed through and are not modelled -- the ones assumed to be in secular
 *   equilibrium. `unknown` names any input the database does not have.
 */
export function collapse(names, opts = {}) {
	const minBranching = opts.minBranching ?? 1e-9;
	const ceiling = opts.ceiling ?? Infinity;
	const wanted = [...new Set(names)];
	const unknown = wanted.filter((n) => !BY_NAME.has(n));
	const keep = new Set(wanted.filter((n) => BY_NAME.has(n)));

	const memo = new Map();
	const through = new Set();
	const pairs = [];
	// In the database's own order -- by Z then A -- so the result does not
	// depend on the order the nuclides happened to be chosen in.
	for (const row of ICRP107) {
		if (!keep.has(row[0])) continue;
		const reach = distribution(row[0], keep, memo, through, ceiling);
		for (const [daughter, branching] of reach) {
			if (branching < minBranching) continue;
			pairs.push([row[0], daughter, branching]);
		}
	}
	// A nuclide that is modelled is not "passed through", however the walk
	// reached it: the walk only ever recurses into ones that are not kept, but
	// a kept nuclide can be a stepping stone for a branch that starts above it.
	for (const n of keep) through.delete(n);
	return {
		pairs: pairs.sort((x, y) => x[0].localeCompare(y[0]) || y[2] - x[2]),
		through: [...through].sort(),
		unknown,
	};
}

/**
 * Everything worth modelling in the chains below a set of parents.
 *
 * The selection rule: start at the parents, follow every branch, and keep what
 * lives at least `threshold` years. Short-lived members are still walked
 * *through* -- Pb-210 is 22 years old and sits below nine nuclides that live
 * for minutes, so a walk that stopped at the first short one would never find
 * it.
 *
 * The parents are always kept, whatever their half-life: picking Po-210 (138
 * days) with a one-year threshold is a deliberate act, and dosimetry has
 * reasons for it.
 *
 * The other end of the rule is a *ceiling*: a daughter that lives longer than
 * the assessment is long -- Th-232 at fourteen billion years -- is a sink,
 * not a member. It is not modelled, not walked through, and the parent's
 * activity ends there, exactly as it would at a stable nuclide. GoldSim's
 * ICRP dialog offers the same pair of bounds ("auto-include daughters with
 * half-lives ≥ X and ≤ Y"); the roots are exempt from both, since choosing one
 * is a deliberate act.
 *
 * @param {Iterable<string>} roots
 * @param {{threshold?: number, ceiling?: number, minBranching?: number}} [opts]
 *   threshold and ceiling in years; `minBranching` prunes branches too small
 *   to lead anywhere worth having, which also keeps the walk out of the far
 *   tail of the fission products.
 * @returns {{members: string[], skipped: string[], sinks: string[], unknown: string[]}}
 *   `members` includes the roots, in database order. `skipped` names the
 *   short-lived nuclides the walk passed through; `sinks` the long-lived ones
 *   it stopped at.
 */
export function chainFrom(roots, opts = {}) {
	const threshold = opts.threshold ?? 1;
	const ceiling = opts.ceiling ?? Infinity;
	const minBranching = opts.minBranching ?? 1e-6;
	const wanted = [...new Set(roots)];
	const unknown = wanted.filter((n) => !BY_NAME.has(n));

	const members = new Set(wanted.filter((n) => BY_NAME.has(n)));
	const skipped = new Set();
	const sinks = new Set();
	const seen = new Set();

	const walk = (name, weight) => {
		if (weight < minBranching) return;
		// Weight matters, so a nuclide reached twice by different branches is
		// walked twice -- but only until the weight decides nothing.
		if (seen.has(`${name}|${weight >= 0.01}`)) return;
		seen.add(`${name}|${weight >= 0.01}`);
		for (const [daughter, branching] of BY_NAME.get(name)?.[5] ?? []) {
			if (isStable(daughter)) continue;
			const w = weight * branching;
			if (w < minBranching) continue;
			const hl = halfLife(daughter);
			if (hl > ceiling && !members.has(daughter)) { sinks.add(daughter); continue; }
			if (hl >= threshold) members.add(daughter);
			else skipped.add(daughter);
			walk(daughter, w);
		}
	};
	for (const root of members) walk(root, 1);
	for (const n of members) { skipped.delete(n); sinks.delete(n); }

	const order = new Map(ICRP107.map((row, i) => [row[0], i]));
	const byOrder = (a, b) => (order.get(a) ?? 0) - (order.get(b) ?? 0);
	return {
		members: [...members].sort(byOrder),
		skipped: [...skipped].sort(byOrder),
		sinks: [...sinks].sort(byOrder),
		unknown,
	};
}

/**
 * The un-modelled nuclides a decay of `parent` passes through on its shortest
 * way to `daughter`.
 *
 * What `stepsBetween` counts, named: `U-238 -> U-234` is `[Th-234, Pa-234m]`,
 * `Ra-226 -> Pb-210` the radon and the polonia. Shown beside a pair in the
 * chain panel the way GoldSim's species dialog shows "skipped intermediates"
 * in parentheses, so a pair the model asked for carries its assumption on its
 * face.
 *
 * @returns {string[]|null} empty for a direct decay; null when unreachable
 */
export function pathBetween(parent, daughter, kept) {
	const modelled = new Set(kept);
	const row = BY_NAME.get(parent);
	if (!row) return null;
	// Breadth-first with the path carried, so the first arrival is the
	// shortest. Only un-modelled nuclides may be passed through.
	let frontier = row[5].map(([d]) => ({ name: d, via: [] }));
	const seen = new Set([parent]);
	for (let steps = 0; frontier.length && steps < 64; steps++) {
		const next = [];
		for (const { name, via } of frontier) {
			if (name === daughter) return via;
			if (seen.has(name) || modelled.has(name) || isStable(name)) continue;
			seen.add(name);
			for (const [d] of BY_NAME.get(name)?.[5] ?? []) next.push({ name: d, via: [...via, name] });
		}
		frontier = next;
	}
	return null;
}

/**
 * How many un-modelled nuclides sit between a parent and one of its collapsed
 * daughters.
 *
 * Zero when the pair is a decay in its own right. Two for `U-238 -> U-234`,
 * which really goes through Th-234 and Pa-234m; five for `Ra-226 -> Pb-210`,
 * which goes through the radon and the polonia. Worth knowing, because it is
 * the difference between a pair the database states and a pair this model
 * asked for -- and the second kind carries an assumption with it.
 *
 * The shortest such path, since that is the one the chain is named for; a
 * branch that reaches the same daughter the long way round is not what the
 * pair is about.
 *
 * @param {string} parent
 * @param {string} daughter
 * @param {Iterable<string>} kept the nuclides being modelled
 * @returns {number|null} null when the daughter is not reachable at all
 */
export function stepsBetween(parent, daughter, kept) {
	const via = pathBetween(parent, daughter, kept);
	return via ? via.length : null;
}

/** The decay mode of a pair the database states directly, or null. */
export function directMode(parent, daughter) {
	const row = BY_NAME.get(parent);
	const hit = row?.[5].find(([d]) => d === daughter);
	return hit ? hit[2] : null;
}

/**
 * Half-life thresholds worth offering, and what each is for.
 *
 * The numbers are not arbitrary: a threshold is a statement about the
 * timescale of the assessment. A repository safety case integrates over
 * 100,000 years and models nothing under a year; a dose calculation after a
 * release cares about Po-210 and I-131.
 */
/**
 * Ceilings worth offering: how long-lived a daughter has to be before it is a
 * sink rather than a member. Never, by default -- the database is walked to
 * its stable ends -- because a model that wants Th-232 as a sink should say
 * so, and one that carries it is not wrong.
 */
export const CEILINGS = [
	{ years: Infinity, label: 'never', what: 'every long-lived daughter is modelled' },
	{ years: 1e8, label: '100 My', what: 'U-238, Th-232, K-40 become sinks' },
	{ years: 1e10, label: '10 Gy', what: 'Th-232, Rb-87, Sm-147 become sinks' },
	{ years: 1e12, label: '1 Ty', what: 'only the near-stable' },
];

export const THRESHOLDS = [
	{ years: 1e4, label: '10 ky', what: 'the very long-lived only' },
	{ years: 1, label: '1 year', what: 'long-term safety assessment' },
	{ years: 1 / 12, label: '1 month', what: 'includes Po-210, Th-228' },
	{ years: 1 / 365.25, label: '1 day', what: 'includes Rn-222, Th-234' },
	{ years: 1 / 8766, label: '1 hour', what: 'nearly everything' },
	{ years: 0, label: 'everything', what: 'every member of every branch' },
];

/** `30.1671 y` from the database, or a formatted fallback for a stranger. */
export function halfLifeText(name) {
	const row = BY_NAME.get(name);
	if (row) return row[4];
	return null;
}

/** The element's own name and category, for a heading: `Cs` -> Caesium. */
export function element(symbol) {
	const e = BY_SYMBOL.get(symbol);
	return e ? { z: e[0], symbol: e[1], name: e[2], category: e[3] } : null;
}
