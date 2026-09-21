/**
 * One line that tells one block from another.
 *
 * The block tree and the graph both need a short second line under a name --
 * the endpoints of a transfer, the equation of an expression, the span of a
 * lookup table -- and it has to be the same line in both places, or the same
 * block reads as two different things depending on where you look at it.
 */

/** `12 points, 0 to 1e4` -- enough to tell one table from another. */
export function summariseTable(b) {
	const pts = b.points ?? [];
	if (!pts.length) return b.entries?.length ? `${b.entries.length} entries` : 'no points';
	const xs = pts.map((p) => Number(p[0]));
	const lo = Math.min(...xs);
	const hi = Math.max(...xs);
	const num = (v) => (Number.isFinite(v) ? String(Number(v.toPrecision(4))) : '?');
	return pts.length === 1
		? `1 point at ${num(lo)}`
		: `${pts.length} points, ${num(lo)} to ${num(hi)}`;
}

/**
 * @param {string} collection the plural the block lives in
 * @param {object} b
 */
export function summarise(collection, b) {
	const dims = b.index_lists ?? [];
	const entries = b.entries ?? [];
	// For an indexed block the dimensions are the useful summary; the
	// block-level value is usually just the fallback.
	const indexed = dims.length ? `[${dims.join(' x ')}]` : '';

	switch (collection) {
		case 'compartments':
			if (indexed) return indexed;
			return entries.length ? `${entries.length} entries` : String(b.initial ?? '0');
		case 'transfers':
			return `${b.from ?? 'outside'} to ${b.to ?? 'outside'}`;
		case 'inflows':
			return `into ${b.to}`;
		case 'expressions':
			// The two parts of a transport whose equation the run writes say
			// what they are instead; N shows its equation like any expression.
			if (b.transport === 'counter') return 'element counter';
			if (b.transport === 'operation') {
				return `${b.operation ?? 'mean'} over ${
					{ all: 'the chain', point: 'a point', range: 'a stretch' }[b.argument ?? 'all']}`;
			}
			return b.equation ?? '';
		case 'parameters':
			if (indexed) return indexed;
			return entries.length ? `${entries.length} entries` : String(b.value ?? 0);
		case 'lookups':
			if (indexed) return indexed;
			return summariseTable(b);
		case 'functions':
			// Its signature: what it is called with, which is the one thing
			// worth knowing about a function from a list.
			return `(${(b.parameters ?? []).join(', ')})`;
		case 'index_reductions':
			return `${b.operation ?? 'sum'} of ${b.target ?? '—'}`;
		case 'block_reductions': {
			const n = (b.targets ?? []).length;
			return `${b.operation ?? 'sum'} of ${n === 1 ? b.targets[0] : `${n} blocks`}`;
		}
		case 'min_maxes':
			return `${b.operation ?? 'max'} of ${b.target ?? '—'}`;
		case 'running_means':
			return `mean of ${b.target ?? '—'}`;
		case 'snapshots':
			return `${b.target ?? '—'} at ${b.trigger ?? 'no trigger'}`;
		case 'delays':
			return `${b.target ?? '—'} delayed by ${b.delay ?? '0'}`;
		case 'farfields':
			return `${b.n_f ?? 20} x ${b.n_m ?? 20} cells`
				+ `${b.to ? `, into ${b.to}` : ''}`;
		case 'triggers':
			return `${b.first ?? '0'} ${
				{ rising: '↗', falling: '↘', both: '↕' }[b.direction] ?? '↗'
			} ${b.second ?? '0'}`;
		default:
			return '';
	}
}

/**
 * What an index list is, in three words: `sub-set of Nuclide`.
 *
 * Here rather than in the Index lists panel because the Information view says
 * the same thing about the same list, and a dimension that is "a grouping of
 * Nuclide" in one panel and something else in the other is two vocabularies
 * for one idea.
 */
export function summariseIndexList(list) {
	if (list.for_contaminants) return 'materials';
	if (list.for_nuclides) {
		return list.sub_set_of ? `radionuclides of ${list.sub_set_of}` : 'radionuclides';
	}
	// The three derived ones say what they are made of: the elements follow
	// the nuclides, and the other two follow the model's own blocks.
	if (list.auto === 'compartments') return 'one per compartment';
	if (list.auto === 'transfers') return 'one per transfer';
	if (list.derived) return `one per element of ${list.mapping?.to ?? 'the nuclides'}`;
	if (list.for_scenarios) return 'scenarios';
	if (list.sub_set_of) return `sub-set of ${list.sub_set_of}`;
	if (list.mapping) return `grouping of ${list.mapping.to}`;
	return 'an axis of its own';
}

/**
 * Where a flux's dimensions came from, in words.
 *
 * A transfer is indexed by the indices its two ends have in common, and that
 * is not a choice -- the dimension rule keeps Ecolego's in step with
 * both ends and there is no picker for it there. So what the interface has to
 * do is say what was inherited, and say when the two ends differed and an
 * intersection had to be taken, which is the one case where the answer is not
 * simply one of the ends' own lists.
 *
 * @param shared what `transferDims` worked out, or null when the ends do not
 *   correspond and there was no rule to follow
 * @param dims what the block is actually indexed by, which may be narrower
 * @returns a sentence, or '' when there is nothing worth saying
 */
export function describeSharedDims(shared, dims, { from, to } = {}) {
	if (!shared) return '';
	const ends = [from, to].filter(Boolean);
	const between = ends.length === 2 ? `${ends[0]} and ${ends[1]}`
		: ends.length === 1 ? ends[0] : 'its ends';
	const narrowed = (dims ?? []).join(',') !== shared.dims.join(',');
	const taken = shared.dims.length ? shared.dims.join(' × ') : 'nothing';

	if (shared.shared.length) {
		// The interesting case: the two ends are on different lists, and this
		// is the one that holds the indices both of them have. The arrow is
		// only worth drawing where there is more than one dimension and which
		// pair became which is a question; with one it repeats the answer.
		const many = shared.dims.length > 1;
		const pairs = shared.shared
			.map((p) => `${p.from} ∩ ${p.to}${many ? ` → ${p.dims}` : ''}`)
			.join(', ');
		return `${taken} — the indices ${between} have in common (${pairs}).`
			+ (narrowed ? ' This block states a narrower dimension of its own.' : '');
	}
	return `Inherited from ${between}: ${taken}.`
		+ (narrowed ? ' This block states a narrower dimension of its own.' : '');
}

/**
 * A time on the simulation clock, short enough for a panel.
 *
 * Shared by the left panel's Simulation badge and the Information view, so the
 * end of a run reads as `1e5` in both rather than as `1e5` in one place and
 * `100000` in the other.
 *
 * Four significant figures either side of the switch to exponential form. It
 * used to be one digit above 1e5, which rounded a run ending at 123456 years
 * to `1e5` -- fine as a badge, wrong in a panel whose job is to say what the
 * settings are. Also used for the tolerances, where a rounded `3e-7` for
 * 2.5e-7 would be the same kind of lie.
 */
export function fmtTime(v) {
	const n = Number(v ?? 0);
	if (!Number.isFinite(n)) return String(v ?? '');
	if (n !== 0 && (Math.abs(n) >= 1e5 || Math.abs(n) < 1e-3)) {
		return Number(n.toPrecision(4)).toExponential().replace('e+', 'e');
	}
	return String(Number(n.toPrecision(4)));
}
