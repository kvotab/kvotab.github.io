/**
 * The two blocks that reduce many values to one.
 *
 * The two reduce along different axes, which is why they are separate blocks
 * here and in every file format this reads:
 *
 *   index operation   one block, reduced along one of its index lists --
 *                     `Total[nuclide] = sum over objects of Soil[nuclide][obj]`
 *   aggregate         several blocks, reduced element-wise at each index --
 *                     `RegoGL[nuclide] = RegoGL1[nuclide] + ... + RegoGL5[nuclide]`
 *
 * Both are, in the end, a call to a function the equation language already
 * has, over arguments the builder works out. That is not a shortcut: an
 * aggregate is exactly the tokens `sum ( t1 , t2 , ... )` handed to the
 * ordinary equation compiler, and an index operation is exactly the loop the
 * language's own `sum` writes. Building on the existing machinery means these
 * blocks get
 * the analytic Jacobian, the dependency ordering and the per-index entries for
 * nothing.
 *
 * Counts across the 200 .eco files on this machine:
 *
 *   index operation   281 blocks in 21 files: 237 sum, 32 mean, 12 max
 *   aggregate          17 blocks in  5 files, median 5 targets, largest 40
 *
 * Neither `product`, `min` nor `percentile` appears; they are here because the
 * enum has them and they cost a line each.
 */

/** The reductions, in the order the interface offers them. */
export const OPERATIONS = ['sum', 'product', 'min', 'max', 'mean', 'percentile'];

/** An aggregate reduces over blocks, and Ecolego gives it no percentile. */
export const AGGREGATE_OPERATIONS = OPERATIONS.filter((o) => o !== 'percentile');

/**
 * How Ecolego spells them. The capitalised forms are the enum names; the
 * others are the display names an older version wrote instead, which
 * the file format still translates on the way in.
 */
/**
 * Lookups keyed by something a project file said.
 *
 * On a null prototype, every one of them. A plain object answers
 * `obj.constructor`, `obj.toString`, `obj.valueOf` and the rest with an
 * inherited member -- truthy, and not what was asked for -- so a whitelist
 * written as a plain object admits exactly the names it exists to refuse. The
 * damage is different in each case (a solver that is `Object`, a reduction
 * whose name prints as `function Object() { [native code] }`) and the cure is
 * the same.
 */
const FROM_ECO = Object.assign(Object.create(null), {
	SUM: 'sum',
	PRODUCT: 'product',
	MIN: 'min',
	MAX: 'max',
	MEAN: 'mean',
	PERCENTILE: 'percentile',
	Sum: 'sum',
	Product: 'product',
	Minimum: 'min',
	Maximum: 'max',
	Mean: 'mean',
	Percentile: 'percentile',
});

export function operationFromEco(name) {
	return FROM_ECO[String(name ?? '').trim()] ?? null;
}

/** The function in this tool's equation language that each reduction is. */
export const OPERATION_FUNCTION = Object.assign(Object.create(null), {
	sum: 'sum',
	product: 'prod',
	min: 'min',
	max: 'max',
	mean: 'mean',
	percentile: 'percentile',
});

/** A one-line description, for the inspector and the import report. */
export const OPERATION_BLURB = {
	sum: 'adds them up',
	product: 'multiplies them together',
	min: 'the smallest of them',
	max: 'the largest of them',
	mean: 'their arithmetic mean',
	percentile: 'the value below which the given percentage of them falls',
};

/**
 * The index list an index operation reduces over: the one dimension of the
 * target that the block itself is not indexed by.
 *
 * the operation's own target list, which is where the rule that a
 * reduction has one dimension fewer than its target comes from -- with no
 * dimension of its own it takes the target's first list, and otherwise the
 * first list the two do not share.
 *
 * `isScenario` marks Ecolego's scenario dimension, which the format leaves out of
 * the count -- so a block indexed by [Scenarios, A,
 * B] and reduced to [A] is reduced over B, not over the scenarios. Eight real
 * blocks in the corpus are shaped exactly that way.
 *
 * @returns {string|null} the list's name, or null when there is nothing to
 *                        reduce (a scalar target, or a block already indexed
 *                        by everything the target is)
 */
export function operatedList(ownDims, targetDims, isScenario = null) {
	const target = (targetDims ?? []).filter((d) => !isScenario?.(d));
	if (!target.length) return null;
	const own = ownDims ?? [];
	if (!own.length) return target[0];
	return target.find((d) => !own.includes(d)) ?? null;
}

/**
 * The percentile of a sample, as the standard percentile definition --
 * the sorted values sit at the midpoints (i - 0.5) / n, the
 * smallest and largest are pinned to 0 and 1, and anything between is a
 * straight line. So the 50th percentile of an even-sized sample is the average
 * of the middle two, and the 0th and 100th are the extremes.
 *
 * @param {number} phi   0 to 100
 * @param {number[]} xs
 */
export function percentile(phi, xs) {
	const n = xs.length;
	if (!n || !(phi >= 0) || !(phi <= 100)) return NaN;
	const p = phi / 100;

	const sorted = [...xs].sort((a, b) => a - b);
	if (p === 0.5) {
		// The usual code takes the median by a shorter route, and on an even-sized
		// sample the two agree only because the midpoints are symmetric.
		// Following it exactly keeps them agreeing on ties and on NaN.
		return n % 2 === 1
			? sorted[(n + 1) / 2 - 1]
			: (sorted[n / 2 - 1] + sorted[n / 2]) / 2;
	}

	// The sample with its own extremes appended, so the curve reaches 0 and 1.
	const xx = [sorted[0], ...sorted, sorted[n - 1]];
	const pp = [0];
	for (let i = 1; i <= n; i++) pp.push((i - 0.5) / n);
	pp.push(1);

	let j = 1;
	while (j < n + 2 && p > pp[j]) j++;
	if (j >= n + 2) return xx[n + 1];
	const span = pp[j] - pp[j - 1];
	if (span === 0) return xx[j];
	return ((p - pp[j - 1]) / span) * (xx[j] - xx[j - 1]) + xx[j - 1];
}
