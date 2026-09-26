/**
 * Cutting a model into parts that cannot see each other.
 *
 * A large assessment is rarely one problem. model A carries
 * 22,842 states, and they fall into 32 groups with no path between them: the
 * radionuclides, with each decay chain held together by its own ingrowth and
 * nothing joining one chain to the next. Solved as one system, every state
 * moves at the step size the *worst* of them needs -- `ndf` picks it from an
 * infinity norm over all of them, so at any step exactly one
 * state chose it. On one 23,436-state model, 262 states ever set that step and half the
 * steps came from 26 of them. The other seventeen thousand are carried along.
 *
 * The idea is not new -- the desktop tools in this family call it batch mode,
 * and describe it as solving the equations for each contaminant separately,
 * with the exception that radionuclides of one decay chain stay together. That
 * description and this partition agree exactly on the corpus here: every state
 * of one such model carries a nuclide, no nuclide's states land in more than one part,
 * and the 32 parts hold 10, 6, 5, 3 and 3 nuclides with 27 alone -- which is a
 * list of decay chains. The graph is not told any of that; it finds it.
 *
 * **This file finds the partition. It does not decide what to do with one.**
 *
 * ---
 *
 * **Why the Jacobian pattern is the right graph, and where it is not enough.**
 *
 * Two states belong together when one can reach the other, and `df/dy` is
 * exactly that relation: the pattern has an entry at (i, j) when the
 * derivative of state i reads state j, through however many expressions and
 * transfer rates. It is already computed for the analytic Jacobian, it is
 * per-index rather than per-block, and the algebraic blocks between two states
 * are already collapsed into it.
 *
 * What it is not is a record of everything a model *does*. `jacobian.js` says
 * so where it handles the blocks that remember:
 *
 *     A snapshot and a delay report the past, which no present state can move,
 *     so neither gains a column.
 *
 * That is right for a Jacobian -- the derivative through a delay genuinely is
 * zero -- and wrong for this. A block reading a Delay of a compartment in
 * another part depends on it just as surely as a transfer would, and the
 * pattern shows nothing. An event is the same shape from the other end: its
 * action moves a state its condition never mentions. This is a known trap
 * rather than a theoretical one -- every implementation of batching that has
 * shipped has had to add a pass that merges the states an event, a min/max or
 * a snapshot reaches across.
 *
 * So a partition taken off the pattern alone is unsafe for a model with any of
 * those, and a wrong partition does not run slowly -- it returns a different
 * answer, quietly. `whyNotSplit` therefore refuses the model rather than
 * splitting it on an incomplete graph. What it refuses is narrow: of the
 * eleven assessment models of one series, not one carries a delay, a snapshot or an
 * event, so the pattern is their whole dependency graph and the partition is
 * provably complete. one assessment model carries 1 delay, 4 snapshots and
 * 14 discrete events, and is declined until the graph is widened to hold them.
 *
 * A min/max and a running mean are not in that list on purpose: `jacobian.js`
 * gives both a column through `rec.aux.target`, so the pattern already carries
 * them.
 */

/**
 * The states of each part, from the Jacobian's sparsity pattern.
 *
 * Undirected: a path either way puts two states together, because solving them
 * apart needs them not to reach each other in *either* direction. (The
 * directed version -- blocks that only feed downstream -- is a different and
 * weaker condition, and needs the interpolated coupling this does not.)
 *
 * @param {{n: number, colPtr: Int32Array|number[], rowIdx: Int32Array|number[]}} pattern
 * @returns {{count: number, of: Int32Array, sizes: Int32Array, largest: number}}
 *   `of[i]` is the part state i belongs to, numbered from 0 in the order the
 *   states first appear, so part 0 holds state 0.
 */
export function statePartition(pattern) {
	const n = pattern?.n ?? 0;
	const parent = new Int32Array(n);
	const rank = new Int32Array(n);
	for (let i = 0; i < n; i++) parent[i] = i;

	// Path halving: every other node on the way up is pointed at its
	// grandparent, which flattens the tree without a second pass.
	const find = (x) => {
		while (parent[x] !== x) {
			parent[x] = parent[parent[x]];
			x = parent[x];
		}
		return x;
	};
	const union = (a, b) => {
		a = find(a);
		b = find(b);
		if (a === b) return;
		if (rank[a] < rank[b]) { const t = a; a = b; b = t; }
		parent[b] = a;
		if (rank[a] === rank[b]) rank[a]++;
	};

	const { colPtr, rowIdx } = pattern ?? {};
	for (let j = 0; j < n; j++) {
		for (let k = colPtr[j]; k < colPtr[j + 1]; k++) union(j, rowIdx[k]);
	}

	// Number the parts in the order their first state appears, so the numbering
	// is a property of the model rather than of the union-find's internals.
	const label = new Int32Array(n).fill(-1);
	const of = new Int32Array(n);
	let count = 0;
	for (let i = 0; i < n; i++) {
		const r = find(i);
		if (label[r] < 0) label[r] = count++;
		of[i] = label[r];
	}

	const sizes = new Int32Array(count);
	for (let i = 0; i < n; i++) sizes[of[i]]++;
	let largest = 0;
	for (let c = 0; c < count; c++) if (sizes[c] > largest) largest = sizes[c];

	return { count, of, sizes, largest };
}

/** The blocks whose dependency the Jacobian pattern deliberately leaves out. */
const UNSEEN = {
	delay: 'a delay reports the past, which no present state can move, so the '
		+ 'Jacobian gives it no column and a dependency through it is invisible '
		+ 'to this partition',
	snapshot: 'a snapshot reports the past, which no present state can move, so '
		+ 'the Jacobian gives it no column and a dependency through it is '
		+ 'invisible to this partition',
	trigger: 'an event moves a state its condition never mentions, which '
		+ 'is not a derivative and so is not in the Jacobian',
};

/**
 * Why this system may not be split, or null when it may.
 *
 * Conservative by design: it names the first thing it cannot account for
 * rather than guessing. A model that is refused is solved whole, which is what
 * every model here did until now.
 *
 * @param {object} system  from `buildSystem`
 * @returns {string|null}
 */
export function whyNotSplit(system) {
	if (!system?.jacobian?.available) {
		return 'the model has no analytic Jacobian, so there is no sparsity '
			+ 'pattern to read the parts off';
	}
	if (!system.jacobian.pattern?.n) return 'the model has no states to split';

	for (const rec of system.recorders ?? []) {
		const why = UNSEEN[rec.kind];
		if (why) return `'${rec.name}' is a ${rec.kind.replace(/_/g, ' ')}: ${why}`;
	}
	// A semi-analytical path's release is a convolution over what flowed into
	// it during the run, and the series of a split run are worked out
	// afterwards on the whole model's system, which never saw that history.
	const laplace = (system.layout?.farfields ?? []).find((p) => p.farf?.laplace);
	if (laplace) {
		return `'${laplace.name}' is worked out semi-analytically: its release is a convolution `
			+ 'over what flowed into it during the run, which the whole model the series are '
			+ 'worked out on afterwards does not have';
	}
	// Events arrive as a compiled bundle rather than as recorders when the
	// model declares them that way, so both routes are checked.
	if (system.events?.n) {
		return `the model has ${system.events.n === 1 ? 'an event' : `${system.events.n} events`}`
			+ ', and an event moves a state its condition never mentions, which is '
			+ 'not a derivative and so is not in the Jacobian';
	}
	return null;
}

/**
 * The partition, with the reason when there is not one.
 *
 * @param {object} system  from `buildSystem`
 * @returns {{ok: boolean, refusal: string|null, count: number,
 *   of: Int32Array|null, sizes: Int32Array|null, largest: number}}
 */
export function partitionOf(system) {
	const refusal = whyNotSplit(system);
	if (refusal) {
		return { ok: false, refusal, count: 1, of: null, sizes: null, largest: 0 };
	}
	const p = statePartition(system.jacobian.pattern);
	return { ok: true, refusal: null, ...p };
}
